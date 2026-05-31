# SkiSafe — Wearable Node Firmware  (wearable_final.py → flash as main.py)
# Board : Pycom LoPy4 in Makr expansion board
# Author: Bailey Kooymans  s225409142  Deakin SIT210/SIT730
#
# This is wearable_v6 — identical architecture to v5 with GPS integrated.
# It is self-contained (MPU-6050 and BH1750 drivers are inline — no separate uploads).
#
# PYCOM MICROPYTHON 1.20.2.r6 RULES — enforced throughout this file:
#   • NO f-strings → use "string" + str(value) + "more"
#   • I2C uses tuple pin syntax: I2C(0, pins=('P21','P22'))
#   • ADC: adc.channel(pin='P14', attn=ADC.ATTN_11DB)  — 11dB = 0–3.6 V range
#   • utime not time
#
# CRITICAL WIRING RULE — re-read every session:
#   The 5V rail (PowerBoost output) connects ONLY to Makr VIN.
#   Every sensor and module uses the Makr 3V3 output pin.
#   Connecting ANY LoPy4 GPIO or sensor directly to 5V will destroy it.
#
# Pin map:
#   MPU-6050 SDA → P21,  SCL → P22  (I2C bus 0, addr 0x68, AD0→GND)
#   BH1750   SDA → P21,  SCL → P22  (shared I2C, addr 0x23)
#   NTC thermistor → P14  (3V3—10kΩ—P14—NTC—GND, ATTN_11DB)
#   GPS TX   → P19  (UART1 RX), GPS VCC → 3V3, GPS RX DISCONNECTED
#   Buzzer   → P9
#   Button   → P8  (PULL_UP, active LOW)
#   LED Red  → P12 (220Ω to GND)
#   LED Yellow→ P11 (220Ω to GND)
#   LED Green → P10 (220Ω to GND)
#
# Flash command (Windows, adjust COM port):
#   uvx mpremote connect COM12 cp wearable_final.py :main.py + reset + repl
#
# Safe Boot recovery (if crash-looping):
#   Hold Safe Boot button on Makr board + press Reset → boots without main.py

from machine import UART, I2C, ADC, Pin
from network import LoRa
import socket
import utime
import math
import ujson

# ── User-configurable constants ───────────────────────────────────────────────
SKIER_ID          = 'SK01'
LORA_FREQUENCY    = 915000000    # Hz — must match hub receiver exactly
LORA_SF           = 7            # Spreading factor 7 (fastest, lowest range)
TELEMETRY_INTERVAL_MS = 5000     # Normal send interval (ms)

# Alert thresholds — TUNE for your conditions
FALL_MAG_THRESHOLD   = 35000    # Raw IMU magnitude spike for fall detection
SKIN_TEMP_L1_WARN    = 15.0     # °C — below this → Level 1 buzzer warning
SKIN_TEMP_L3_CRITICAL = 10.0   # °C — below this → Level 3 SOS
DARK_LUX_THRESHOLD   = 10.0    # lux — below this = potential burial darkness
IMMOBILITY_SECS      = 30      # Seconds without motion → immobile flag
BATTERY_LOW_PCT      = 15      # % — below this → Level 1 battery warning

# NTC thermistor constants (10K NTC, 10K series, standard Vishay/generic)
# Circuit: 3V3 → 10kΩ(series) → P14(ADC) → NTC(10K) → GND
NTC_SERIES_OHMS  = 10000.0
NTC_NOMINAL_OHMS = 10000.0
NTC_NOMINAL_T_C  = 25.0        # °C at which NTC = NTC_NOMINAL_OHMS
NTC_BETA         = 3950.0      # TUNE — check your thermistor datasheet

# ── Inline MPU-6050 driver ────────────────────────────────────────────────────
class MPU6050:
    """Minimal register-level MPU-6050 driver for Pycom MicroPython."""
    ADDR        = 0x68
    REG_PWR_MGT = 0x6B
    REG_ACCEL_CFG = 0x1C
    REG_ACCEL_X = 0x3B

    def __init__(self, i2c):
        self.i2c = i2c
        # Wake the chip (clear sleep bit)
        self.i2c.writeto_mem(self.ADDR, self.REG_PWR_MGT, b'\x00')
        utime.sleep_ms(100)
        # Accel range: ±2g (0x00) — LSB = 16384 per g
        # At ±2g, raw magnitude at rest ≈ 16384; threshold 35000 ≈ 2.1g
        self.i2c.writeto_mem(self.ADDR, self.REG_ACCEL_CFG, b'\x00')

    def read_accel_raw(self):
        """Return (ax, ay, az) as signed 16-bit raw values (±2g range)."""
        data = self.i2c.readfrom_mem(self.ADDR, self.REG_ACCEL_X, 6)
        ax = (data[0] << 8) | data[1]
        ay = (data[2] << 8) | data[3]
        az = (data[4] << 8) | data[5]
        if ax > 32767: ax -= 65536
        if ay > 32767: ay -= 65536
        if az > 32767: az -= 65536
        return ax, ay, az

    def magnitude(self):
        """Return vector magnitude of acceleration (raw units)."""
        ax, ay, az = self.read_accel_raw()
        return math.sqrt(ax*ax + ay*ay + az*az)


# ── Inline BH1750 driver ──────────────────────────────────────────────────────
class BH1750:
    """Minimal BH1750 light sensor driver."""
    ADDR           = 0x23
    CMD_CONT_H_RES = 0x10   # Continuous high-resolution mode (1 lx resolution)

    def __init__(self, i2c):
        self.i2c = i2c
        self.i2c.writeto(self.ADDR, bytes([self.CMD_CONT_H_RES]))
        utime.sleep_ms(180)   # measurement time for high-res mode

    def read_lux(self):
        """Return ambient light level in lux (float)."""
        try:
            data = self.i2c.readfrom(self.ADDR, 2)
            raw = (data[0] << 8) | data[1]
            return raw / 1.2
        except Exception:
            return -1.0


# ── Hardware initialisation ───────────────────────────────────────────────────
print('SkiSafe wearable starting — ' + SKIER_ID)

# I2C (MPU-6050 + BH1750 share the bus)
i2c = I2C(0, pins=('P21', 'P22'))
utime.sleep_ms(100)

# MPU-6050
try:
    mpu = MPU6050(i2c)
    print('MPU-6050 OK')
except Exception as e:
    print('MPU-6050 FAILED: ' + str(e))
    mpu = None

# BH1750
try:
    light_sensor = BH1750(i2c)
    print('BH1750 OK')
except Exception as e:
    print('BH1750 FAILED: ' + str(e))
    light_sensor = None

# ADC for NTC thermistor (P14)
# ATTN_11DB extends range to ~3.6 V, raw 0–4095
adc      = ADC()
ntc_chan = adc.channel(pin='P14', attn=ADC.ATTN_11DB)

# GPS UART — P20=TX(unused), P19=RX receives GPS sentences
gps_uart = UART(1, baudrate=9600, pins=('P20', 'P19'))

# Outputs
buzzer     = Pin('P9',  mode=Pin.OUT, value=0)
button     = Pin('P8',  mode=Pin.IN,  pull=Pin.PULL_UP)   # active LOW
led_red    = Pin('P12', mode=Pin.OUT, value=0)
led_yellow = Pin('P11', mode=Pin.OUT, value=0)
led_green  = Pin('P10', mode=Pin.OUT, value=0)

# LoRa
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
print('LoRa OK — ' + str(LORA_FREQUENCY // 1000000) + ' MHz SF' + str(LORA_SF))


# ── GPS state & NMEA parser ───────────────────────────────────────────────────
_gps_buf    = b''
gps_lat     = 0.0
gps_lon     = 0.0
gps_alt     = 0.0
gps_speed   = 0.0
gps_fix     = False


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
        return 0.0


def _parse_nmea(sentence):
    global gps_lat, gps_lon, gps_alt, gps_speed, gps_fix
    if not sentence.startswith('$'):
        return
    if '*' in sentence:
        sentence = sentence[:sentence.index('*')]
    f = sentence.split(',')
    t = f[0]
    if t in ('$GPRMC', '$GNRMC') and len(f) >= 8:
        if f[2] == 'A':
            gps_fix   = True
            gps_lat   = _nmea_to_decimal(f[3], f[4])
            gps_lon   = _nmea_to_decimal(f[5], f[6])
            try:
                gps_speed = float(f[7]) * 1.852
            except Exception:
                gps_speed = 0.0
        else:
            gps_fix = False
    elif t in ('$GPGGA', '$GNGGA') and len(f) >= 10:
        if f[6] != '0' and f[9]:
            try:
                gps_alt = float(f[9])
            except Exception:
                pass


def update_gps():
    """Drain UART buffer, parse NMEA sentences. Non-blocking — call every loop."""
    global _gps_buf
    while gps_uart.any():
        ch = gps_uart.read(1)
        if ch is None:
            break
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


# ── NTC thermistor reading ────────────────────────────────────────────────────
def read_skin_temp():
    """Return skin temperature in °C via Beta equation.
    Circuit: 3V3 → 10kΩ(series) → P14(ADC) → NTC(10K) → GND
    Higher temp → lower NTC → lower voltage at P14 → lower raw.
    ATTN_11DB: full range = 3.6 V ≈ raw 4095.
    """
    samples = 0
    total   = 0
    for _ in range(8):
        total  += ntc_chan.value()
        samples += 1
        utime.sleep_ms(2)
    raw = total // samples

    # Guard against divider extremes (open/short circuit)
    if raw <= 10 or raw >= 4085:
        return -99.0

    # ADC reference voltage for ATTN_11DB is approximately 3.6 V
    v_adc = raw * 3.6 / 4095.0

    # Supply voltage through the divider is 3.3 V
    # V_adc = 3.3 * R_ntc / (R_series + R_ntc)  →  R_ntc = R_series * V_adc / (3.3 - V_adc)
    # Note: this formula is for NTC on the BOTTOM (GND side) of the divider.
    # If your thermistor is on the TOP (3V3 side), invert: R_ntc = R_series * (3.3-V_adc)/V_adc
    v_supply = 3.3
    if v_adc >= v_supply:
        return -99.0
    r_ntc = NTC_SERIES_OHMS * v_adc / (v_supply - v_adc)

    # Steinhart-Hart Beta equation: 1/T = 1/T0 + (1/B)*ln(R/R0)
    try:
        steinhart  = math.log(r_ntc / NTC_NOMINAL_OHMS) / NTC_BETA
        steinhart += 1.0 / (NTC_NOMINAL_T_C + 273.15)
        t_kelvin   = 1.0 / steinhart
        return t_kelvin - 273.15
    except Exception:
        return -99.0


# ── Battery level ─────────────────────────────────────────────────────────────
# Battery voltage divider on P15 (P14 is NTC; P15 is next working ADC pin).
# Circuit: LiPo+/BAT pin → 100kΩ → P15 → 100kΩ → GND  →  V_p15 = V_bat / 2
# Max V_bat = 4.2 V → V_p15 = 2.1 V (well within 3.6 V ATTN_11DB range).
# If you used a different pin or resistors, update here.
batt_chan = adc.channel(pin='P15', attn=ADC.ATTN_11DB)


def read_battery_pct():
    samples = 0
    total   = 0
    for _ in range(4):
        total  += batt_chan.value()
        samples += 1
        utime.sleep_ms(2)
    raw   = total // samples
    v_adc = raw * 3.6 / 4095.0   # voltage at divider midpoint
    v_bat = v_adc * 2.0           # ×2 because equal-value divider
    # LiPo: ~3.3 V empty, ~4.2 V full
    pct = int((v_bat - 3.3) / (4.2 - 3.3) * 100)
    if pct < 0:  pct = 0
    if pct > 100: pct = 100
    return pct


# ── Sensor averaging buffers ──────────────────────────────────────────────────
_lux_buf   = []
_temp_buf  = []
_lat_buf   = []
_lon_buf   = []
_alt_buf   = []
_speed_buf = []
BUF_LIGHT = 3
BUF_TEMP  = 5
BUF_GPS   = 5


def _avg(buf):
    return sum(buf) / len(buf) if buf else 0.0


def _push(buf, val, size):
    buf.append(val)
    if len(buf) > size:
        buf.pop(0)


# ── LED helpers ───────────────────────────────────────────────────────────────
def set_leds(level):
    """Drive LEDs to reflect alert level: 0=green, 1=yellow, 2=red, 3=all flash."""
    if level == 0:
        led_green(1);  led_yellow(0); led_red(0)
    elif level == 1:
        led_green(0);  led_yellow(1); led_red(0)
    elif level == 2:
        led_green(0);  led_yellow(0); led_red(1)
    else:
        # Level 3: all LEDs on (SOS / critical)
        led_green(1);  led_yellow(1); led_red(1)


# ── Buzzer control (non-blocking pattern) ─────────────────────────────────────
_buz_last_toggle = 0
_buz_state       = False
_buz_muted       = False

def update_buzzer(level, now_ms):
    """Non-blocking buzzer pattern based on alert level.
    Level 0: silent.
    Level 1: 100 ms on / 1900 ms off (gentle warning beep).
    Level 2: 300 ms on / 700 ms off (urgent alternating beep).
    Level 3: 200 ms on / 200 ms off (rapid SOS pattern).
    Call this every loop iteration with utime.ticks_ms().
    """
    global _buz_state, _buz_last_toggle, _buz_muted

    if _buz_muted or level == 0:
        buzzer(0)
        _buz_state = False
        return

    # Pattern: (on_ms, off_ms) per level
    patterns = {1: (100, 1900), 2: (300, 700), 3: (200, 200)}
    on_ms, off_ms = patterns.get(level, (200, 200))
    period = on_ms if _buz_state else off_ms

    if utime.ticks_diff(now_ms, _buz_last_toggle) >= period:
        _buz_state = not _buz_state
        buzzer(1 if _buz_state else 0)
        _buz_last_toggle = now_ms


# ── Alert logic ───────────────────────────────────────────────────────────────
_last_motion_ms    = utime.ticks_ms()   # tracks last time significant motion seen
_MOTION_MAG_MIN    = 14000              # below resting 1g band → immobile (raw units)
_MOTION_MAG_MAX    = 18000              # above resting 1g band → movement detected

def compute_alert(mag, lux, skin_temp, batt_pct, now_ms):
    """Compute alert level 0–3 from current sensor readings.
    Level 0: normal.
    Level 1: local concern only (cold warning, low battery). Buzzes, no hub action.
    Level 2: serious event (fall, prolonged immobility). Hub displays alert + ack timer.
    Level 3: critical / SOS (confirmed collapse, burial, extreme cold). Hub emails.
    """
    global _last_motion_ms

    # Track motion — update timer whenever accelerometer exceeds 'movement' band
    if mag < _MOTION_MAG_MIN or mag > _MOTION_MAG_MAX:
        _last_motion_ms = now_ms

    immobile_secs = utime.ticks_diff(now_ms, _last_motion_ms) // 1000
    immobile      = immobile_secs >= IMMOBILITY_SECS

    fall_detected = (mag > FALL_MAG_THRESHOLD)

    # Burial detection: darkness + immobility together
    buried = (lux >= 0 and lux < DARK_LUX_THRESHOLD) and immobile

    level = 0

    if batt_pct < BATTERY_LOW_PCT:
        level = max(level, 1)

    if skin_temp < SKIN_TEMP_L1_WARN and skin_temp > -50:   # guard -99 error sentinel
        level = max(level, 1)

    if skin_temp < SKIN_TEMP_L3_CRITICAL and skin_temp > -50:
        level = max(level, 3)

    if fall_detected:
        level = max(level, 2)

    if immobile and not fall_detected:
        # Immobility alone (e.g., sitting still) is a moderate concern
        level = max(level, 1 if immobile_secs < 60 else 2)

    if fall_detected and immobile:
        # Fell and not moved since — most likely injured / unconscious
        level = max(level, 3)

    if buried:
        level = max(level, 3)

    return level, fall_detected, immobile


# ── LoRa packet builder ───────────────────────────────────────────────────────
_pkt_count = 0

def build_and_send(level, fall, immobile, skin_temp, lux, lat, lon, alt, speed, batt):
    """Build short-key JSON and transmit over LoRa."""
    global _pkt_count
    _pkt_count += 1

    # Short JSON keys (matches reader.py on the Pi)
    #   i=id, c=count, st=skin_temp, lx=lux, la=lat, lo=lon, al=alt, sp=speed, a=alert
    # ax/ay/az intentionally omitted — caused parse errors when too long (v5 lesson)
    payload  = '{"i":"' + SKIER_ID + '"'
    payload += ',"c":'  + str(_pkt_count)
    payload += ',"st":' + str(round(skin_temp, 1))
    payload += ',"lx":' + str(round(lux, 1))
    payload += ',"la":' + str(round(lat, 6))
    payload += ',"lo":' + str(round(lon, 6))
    payload += ',"al":' + str(round(alt, 1))
    payload += ',"sp":' + str(round(speed, 1))
    payload += ',"a":'  + str(level)
    payload += '}'

    try:
        lora_sock.send(payload.encode())
        print('TX [' + str(len(payload)) + 'B]: ' + payload)
    except Exception as e:
        print('TX FAILED: ' + str(e))


def check_downlink():
    """Non-blocking check for incoming LoRa messages (e.g., hub ACK).
    If the hub sends a downlink ACK, mute the buzzer for this alert cycle.
    """
    global _buz_muted
    try:
        data = lora_sock.recv(64)
        if data:
            msg = data.decode('ascii', 'ignore').strip()
            print('RX: ' + msg)
            if 'ACK' in msg:
                _buz_muted = True
                print('Buzzer muted by hub ACK')
    except Exception:
        pass


# ── Main loop ─────────────────────────────────────────────────────────────────
print('Sensors initialised.  Entering main loop.')
set_leds(0)

_last_telemetry_ms = utime.ticks_ms()
_last_level        = 0

while True:
    now_ms = utime.ticks_ms()

    # 1. Drain GPS UART buffer (non-blocking)
    update_gps()

    # 2. Read IMU magnitude for fall / motion detection (fast — every loop)
    mag = 16384.0   # default 1g if IMU failed
    if mpu:
        try:
            mag = mpu.magnitude()
        except Exception:
            pass

    # 3. Read slow sensors only on telemetry cadence (avoids blocking the loop)
    skin_temp = -99.0
    lux       = -1.0
    batt_pct  = 100

    due_telemetry = utime.ticks_diff(now_ms, _last_telemetry_ms) >= TELEMETRY_INTERVAL_MS

    if due_telemetry:
        # Skin temperature (NTC)
        skin_temp_raw = read_skin_temp()
        _push(_temp_buf, skin_temp_raw, BUF_TEMP)
        skin_temp = _avg(_temp_buf)

        # Light (BH1750)
        if light_sensor:
            lux_raw = light_sensor.read_lux()
            if lux_raw >= 0:
                _push(_lux_buf, lux_raw, BUF_LIGHT)
        lux = _avg(_lux_buf) if _lux_buf else 0.0

        # GPS averages
        if gps_fix:
            _push(_lat_buf,   gps_lat,   BUF_GPS)
            _push(_lon_buf,   gps_lon,   BUF_GPS)
            _push(_alt_buf,   gps_alt,   BUF_GPS)
            _push(_speed_buf, gps_speed, BUF_GPS)

        lat   = _avg(_lat_buf)   if _lat_buf   else 0.0
        lon   = _avg(_lon_buf)   if _lon_buf   else 0.0
        alt   = _avg(_alt_buf)   if _alt_buf   else 0.0
        speed = _avg(_speed_buf) if _speed_buf else 0.0

        # Battery
        batt_pct = read_battery_pct()
    else:
        # Use buffered values between telemetry sends
        skin_temp = _avg(_temp_buf) if _temp_buf else -99.0
        lux       = _avg(_lux_buf)  if _lux_buf  else 0.0
        lat       = _avg(_lat_buf)  if _lat_buf  else 0.0
        lon       = _avg(_lon_buf)  if _lon_buf  else 0.0
        alt       = _avg(_alt_buf)  if _alt_buf  else 0.0
        speed     = _avg(_speed_buf)if _speed_buf else 0.0

    # 4. Button check — physical dismiss (active LOW)
    if button() == 0:
        _buz_muted = True
        print('Alert dismissed by button press')

    # 5. Compute alert level
    level, fall, immobile = compute_alert(mag, lux, skin_temp, batt_pct, now_ms)

    # Un-mute if alert level has ESCALATED above what was muted
    if _buz_muted and level > _last_level:
        _buz_muted = False

    _last_level = level

    # 6. Update LEDs
    set_leds(level)

    # 7. Update buzzer (non-blocking)
    update_buzzer(level, now_ms)

    # 8. LoRa send — on schedule OR immediately if alert just increased
    if due_telemetry:
        build_and_send(level, fall, immobile, skin_temp, lux, lat, lon, alt, speed, batt_pct)
        _last_telemetry_ms = now_ms

    # 9. Check for downlink ACK from hub
    check_downlink()

    # 10. Loop delay — keep fast enough for responsive fall detection
    utime.sleep_ms(20)    # ~50 Hz accel sampling
