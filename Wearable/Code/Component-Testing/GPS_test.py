# SkiSafe — GPS Standalone Bring-Up Test
# Board : Pycom LoPy4 in Makr expansion board
# Module: GY-NEO6MV2 (NEO-6M) — NMEA @ 9600 8N1
#
# CORRECT WIRING (the wiring that killed the first module was 5V — never again):
#   GPS VCC  →  Makr 3V3 pin          ← 3.3V ONLY — 5V will destroy the module
#   GPS GND  →  Makr GND
#   GPS TX   →  P19  (LoPy4 UART1 RX) ← data flows GPS→LoPy4 on this wire
#   GPS RX   →  LEAVE DISCONNECTED    ← one-way comms, no level shifter needed
#
# NO logic level converter is required — NEO-6M TX is 3.3V logic, LoPy4 is 3.3V.
#
# HOW TO KNOW THE MODULE IS ALIVE (check these BEFORE running this script):
#   1. Power it up → the red LED on the breakout board should light immediately.
#   2. After 30–120 s outdoors or near a window, the LED blinks at 1 Hz (fix acquired).
#      If no LED at all on any voltage: module is dead on arrival.
#   3. The TIMEPULSE LED blinks even indoors before a fix on a good module.
#
# Flash this file as main.py:
#   uvx mpremote connect COM12 cp gps_test.py :main.py + reset + repl
#   (adjust COM port to match Device Manager — usually COM12 or COM13)
#
# PYCOM MICROPYTHON 1.20.2.r6 — NO f-strings, use string concatenation.

from machine import UART
import utime

# ── UART config ──────────────────────────────────────────────────────────────
# pins=('P20','P19') means P20=TX (unused), P19=RX (receives GPS sentences)
gps_uart = UART(1, baudrate=9600, pins=('P20', 'P19'))

# ── Parser state ─────────────────────────────────────────────────────────────
_buf = b''
gps_lat   = None
gps_lon   = None
gps_alt   = None
gps_speed = None
gps_fix   = False
gps_sats  = 0
sentence_count = 0
byte_count     = 0


def nmea_to_decimal(raw, hemi):
    """Convert NMEA DDDMM.MMMM + hemisphere to signed decimal degrees."""
    try:
        dot = raw.index('.')
        degrees = int(raw[:dot - 2])
        minutes = float(raw[dot - 2:])
        decimal = degrees + minutes / 60.0
        if hemi in ('S', 'W'):
            decimal = -decimal
        return decimal
    except Exception:
        return None


def parse_nmea(sentence):
    """Parse a single NMEA sentence (without the trailing CRLF)."""
    global gps_lat, gps_lon, gps_alt, gps_speed, gps_fix, gps_sats, sentence_count

    if not sentence.startswith('$'):
        return

    # Strip checksum (*XX suffix)
    if '*' in sentence:
        sentence = sentence[:sentence.index('*')]

    f = sentence.split(',')
    msg_type = f[0]
    sentence_count += 1

    # ── $GPRMC or $GNRMC — position, speed, validity ─────────────────────────
    if msg_type in ('$GPRMC', '$GNRMC') and len(f) >= 8:
        if f[2] == 'A':   # 'A' = data valid, 'V' = void (no fix yet)
            gps_fix = True
            lat = nmea_to_decimal(f[3], f[4])
            lon = nmea_to_decimal(f[5], f[6])
            if lat is not None:
                gps_lat = lat
            if lon is not None:
                gps_lon = lon
            try:
                gps_speed = float(f[7]) * 1.852   # knots → km/h
            except Exception:
                gps_speed = 0.0
        else:
            gps_fix = False   # 'V' means receiver is searching

    # ── $GPGGA or $GNGGA — altitude, satellite count ─────────────────────────
    elif msg_type in ('$GPGGA', '$GNGGA') and len(f) >= 10:
        try:
            sat_str = f[7].strip()
            if sat_str:
                gps_sats = int(sat_str)
        except Exception:
            pass
        if f[6] != '0' and f[9].strip():   # fix quality > 0 and altitude field present
            try:
                gps_alt = float(f[9])
            except Exception:
                pass


def update_gps():
    """Drain UART buffer and parse any complete sentences. Call every loop."""
    global _buf, byte_count
    while gps_uart.any():
        ch = gps_uart.read(1)
        if ch is None:
            break
        byte_count += 1
        if ch in (b'\n', b'\r'):
            if _buf:
                try:
                    line = _buf.decode('ascii', 'ignore').strip()
                    if line:
                        parse_nmea(line)
                except Exception:
                    pass
                _buf = b''
        else:
            _buf += ch
            if len(_buf) > 120:   # guard against runaway buffer (no newline)
                _buf = b''


def print_status(elapsed_s):
    """Print a diagnostic summary."""
    print('─' * 60)
    print('Elapsed : ' + str(elapsed_s) + ' s')
    print('Bytes   : ' + str(byte_count))
    print('Sentences: ' + str(sentence_count))

    if byte_count == 0:
        print('')
        print('[!] NO BYTES RECEIVED — check wiring:')
        print('    • GPS TX → P19?  (not P20, not P21)')
        print('    • GPS VCC → 3V3? (red LED should be on)')
        print('    • GND connected?')
        print('    • Baud rate is 9600?')
        return

    if sentence_count == 0:
        print('')
        print('[!] Bytes arriving but no NMEA sentences parsed.')
        print('    • Are you getting garbage characters?  Baud mismatch.')
        print('    • Try 4800 baud if nothing resolves.')
        return

    if gps_fix:
        print('FIX     : YES  ✓')
        print('Lat     : ' + str(gps_lat))
        print('Lon     : ' + str(gps_lon))
        print('Alt     : ' + str(gps_alt) + ' m')
        print('Speed   : ' + str(gps_speed) + ' km/h')
        print('Sats    : ' + str(gps_sats))
        print('')
        print('SUCCESS — GPS is working.  Proceed to wearable firmware.')
    else:
        print('FIX     : searching... (' + str(gps_sats) + ' sats visible)')
        print('')
        print('Normal — NMEA flowing but no fix yet.')
        print('• Cold start takes 1–15 min.  Be outside or at a window.')
        print('• TIMEPULSE LED should be blinking at 1 Hz once fix acquired.')
        print('• If still no fix after 15 min: check antenna connection on module.')


# ── Main loop ────────────────────────────────────────────────────────────────
print('SkiSafe GPS test starting — module: GY-NEO6MV2 (NEO-6M)')
print('UART1: P20=TX(unused), P19=RX, 9600 8N1')
print('Waiting for data...')
print('')

start_ms   = utime.ticks_ms()
last_print = 0

while True:
    update_gps()

    now_ms  = utime.ticks_ms()
    elapsed = utime.ticks_diff(now_ms, start_ms) // 1000

    # Print status every 5 seconds
    if elapsed - last_print >= 5:
        last_print = elapsed
        print_status(elapsed)

    utime.sleep_ms(20)   # ~50 Hz loop
