# SkiSafe — GPS + LoRa Integration Test  (GPS_LoRa_test.py → flash as main.py)
# Board : Pycom LoPy4 in Makr expansion board
# Purpose: Confirm GPS module is receiving NMEA data AND that LoRa packets
#          arrive at the hub receiver — without needing a serial monitor.
#
# LED feedback (since USB disconnects make serial unreliable):
#   GREEN  slow blink (1s) = starting up / searching for GPS fix
#   GREEN  solid           = GPS fix acquired
#   YELLOW flash (100ms)   = LoRa packet just transmitted
#   RED    solid           = GPS bytes not arriving (check wiring P19 / 3V3)
#   ALL 3  triple-flash    = boot complete, about to start main loop
#
# What to watch on the hub dashboard / reader.py output:
#   • reader.py will print: [S1] RX SK01  alert=0  skin=0.0C  lux=0.0
#   • If GPS has a fix: lat/lon/alt/speed will be real values on the map
#   • If no fix yet: lat=0 lon=0 — packet still proves LoRa link is working
#
# Flash command (Windows — adjust COM port):
#   uvx mpremote connect COM12 cp "Wearable/Code/Component-Testing/GPS_LoRa_test.py" :main.py + reset
#   (omit '+ repl' — USB will disconnect; just let it run)
#
# PYCOM MICROPYTHON 1.20.2.r6 — no f-strings, utime not time, tuple I2C pins.

from machine import UART, Pin
from network import LoRa
import socket
import utime

# ── Config (must match hub receiver.py exactly) ─────────────────────────
SKIER_ID       = 'SK01'
LORA_FREQUENCY = 915000000
LORA_SF        = 7
TX_INTERVAL_MS = 5000       # send a packet every 5 seconds

# ── GPIO ──────────────────────────────────────────────────────────────────────
led_red    = Pin('P12', mode=Pin.OUT, value=0)
led_yellow = Pin('P11', mode=Pin.OUT, value=0)
led_green  = Pin('P10', mode=Pin.OUT, value=0)


def all_off():
    led_red(0); led_yellow(0); led_green(0)


def triple_flash():
    """3× all-LEDs flash — boot complete indicator."""
    for _ in range(3):
        led_red(1); led_yellow(1); led_green(1)
        utime.sleep_ms(150)
        all_off()
        utime.sleep_ms(150)


def tx_flash():
    """Short yellow flash — fired on every LoRa transmit."""
    led_yellow(1)
    utime.sleep_ms(100)
    led_yellow(0)


# ── GPS UART ──────────────────────────────────────────────────────────────────
# P20 = TX (unused — GPS RX disconnected), P19 = RX (receives GPS NMEA)
gps_uart = UART(1, baudrate=9600, pins=('P20', 'P19'))

_gps_buf  = b''
gps_lat   = 0.0
gps_lon   = 0.0
gps_alt   = 0.0
gps_speed = 0.0
gps_fix   = False
gps_sats  = 0
_byte_count     = 0
_sentence_count = 0


def _nmea_to_decimal(raw, hemi):
    try:
        dot = raw.index('.')
        deg  = int(raw[:dot - 2])
        mins = float(raw[dot - 2:])
        dec  = deg + mins / 60.0
        if hemi in ('S', 'W'):
            dec = -dec
        return dec
    except Exception:
        return None


def _parse_nmea(sentence):
    global gps_lat, gps_lon, gps_alt, gps_speed, gps_fix, gps_sats, _sentence_count
    if not sentence.startswith('$'):
        return
    if '*' in sentence:
        sentence = sentence[:sentence.index('*')]
    f = sentence.split(',')
    t = f[0]
    _sentence_count += 1

    if t in ('$GPRMC', '$GNRMC') and len(f) >= 8:
        if f[2] == 'A':
            gps_fix = True
            lat = _nmea_to_decimal(f[3], f[4])
            lon = _nmea_to_decimal(f[5], f[6])
            if lat is not None: gps_lat = lat
            if lon is not None: gps_lon = lon
            try:    gps_speed = float(f[7]) * 1.852
            except: gps_speed = 0.0
        else:
            gps_fix = False

    elif t in ('$GPGGA', '$GNGGA') and len(f) >= 10:
        try:
            s = f[7].strip()
            if s: gps_sats = int(s)
        except: pass
        if f[6] != '0' and f[9].strip():
            try:    gps_alt = float(f[9])
            except: pass


def update_gps():
    global _gps_buf, _byte_count
    while gps_uart.any():
        ch = gps_uart.read(1)
        if ch is None:
            break
        _byte_count += 1
        if ch in (b'\n', b'\r'):
            if _gps_buf:
                try:
                    _parse_nmea(_gps_buf.decode('ascii', 'ignore').strip())
                except Exception:
                    pass
                _gps_buf = b''
        else:
            _gps_buf += ch
            if len(_gps_buf) > 120:
                _gps_buf = b''


# ── LoRa ──────────────────────────────────────────────────────────────────────
lora = LoRa(
    mode        = LoRa.LORA,
    region      = LoRa.AU915,
    frequency   = LORA_FREQUENCY,
    bandwidth   = LoRa.BW_125KHZ,
    sf          = LORA_SF,
    preamble    = 8,
    coding_rate = LoRa.CODING_4_5,
    tx_iq       = False,
    rx_iq       = False,
    power_mode  = LoRa.ALWAYS_ON
)
lora_sock = socket.socket(socket.AF_LORA, socket.SOCK_RAW)
lora_sock.setblocking(False)

_pkt_count = 0

def send_packet():
    global _pkt_count
    _pkt_count += 1

    # Build exact same short-key JSON as wearable.py
    # Sends zeros when no GPS fix — hub still logs it, confirming LoRa works
    payload  = '{"i":"' + SKIER_ID + '"'
    payload += ',"c":'  + str(_pkt_count)
    payload += ',"st":0.0'        # no NTC in this test script
    payload += ',"lx":0.0'        # no BH1750 in this test script
    payload += ',"la":' + str(round(gps_lat,   6))
    payload += ',"lo":' + str(round(gps_lon,   6))
    payload += ',"al":' + str(round(gps_alt,   1))
    payload += ',"sp":' + str(round(gps_speed, 1))
    payload += ',"a":0'
    payload += '}'

    try:
        lora_sock.send(payload.encode())
        # Yellow flash = TX confirmed
        tx_flash()
        print('TX #' + str(_pkt_count) + ' fix=' + str(gps_fix) +
              ' lat=' + str(gps_lat) + ' lon=' + str(gps_lon) +
              ' sats=' + str(gps_sats) + ' bytes_rx=' + str(_byte_count))
    except Exception as e:
        # Red blink = TX failed
        led_red(1); utime.sleep_ms(300); led_red(0)
        print('TX FAILED: ' + str(e))


# ── Boot sequence ─────────────────────────────────────────────────────────────
print('GPS_LoRa_test starting')
print('LoRa: ' + str(LORA_FREQUENCY // 1000000) + ' MHz  SF' + str(LORA_SF))
print('GPS UART: P19=RX, 9600 baud')
print('TX interval: ' + str(TX_INTERVAL_MS) + ' ms')
print('GREEN solid = fix  YELLOW flash = TX  RED solid = no GPS bytes')

triple_flash()
utime.sleep_ms(500)

# Start with green blinking (searching state)
led_green(1)

# ── Main loop ─────────────────────────────────────────────────────────────────
_last_tx_ms     = utime.ticks_ms()
_last_blink_ms  = utime.ticks_ms()
_blink_state    = True
_no_bytes_warned = False

# How long to wait before flagging "no bytes from GPS" (10 seconds)
_start_ms       = utime.ticks_ms()
GPS_TIMEOUT_MS  = 10000

while True:
    now_ms = utime.ticks_ms()

    # 1. Drain GPS UART
    update_gps()

    # 2. LED status update
    if gps_fix:
        # Solid green = fix acquired
        all_off()
        led_green(1)
    elif _byte_count > 0:
        # Slow blink green = bytes flowing, searching for fix
        if utime.ticks_diff(now_ms, _last_blink_ms) >= 1000:
            _blink_state = not _blink_state
            all_off()
            led_green(1 if _blink_state else 0)
            _last_blink_ms = now_ms
    else:
        # No bytes at all after timeout → solid red (wiring problem)
        if utime.ticks_diff(now_ms, _start_ms) > GPS_TIMEOUT_MS:
            all_off()
            led_red(1)
            if not _no_bytes_warned:
                _no_bytes_warned = True
                print('WARNING: no GPS bytes after 10s')
                print('Check: GPS VCC -> 3V3 (not 5V!), GPS TX -> P19, GND connected')
        else:
            # Still in startup window — blink green quickly
            if utime.ticks_diff(now_ms, _last_blink_ms) >= 250:
                _blink_state = not _blink_state
                all_off()
                led_green(1 if _blink_state else 0)
                _last_blink_ms = now_ms

    # 3. LoRa TX on schedule
    if utime.ticks_diff(now_ms, _last_tx_ms) >= TX_INTERVAL_MS:
        send_packet()
        _last_tx_ms = now_ms

    utime.sleep_ms(20)
