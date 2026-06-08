# =============================================================================
#  SkiSafe — Wearable Node Production Firmware
#  File   : wearable.py   (flash as main.py)
#  Board  : Pycom LoPy4 standalone (no expansion board)
#  Runtime: Pycom MicroPython 1.20.2.r6
# =============================================================================
#
#  AUTHORITATIVE PIN MAP  (verified by Full-Hardware_Test.py — do not change):
#    P2   OUT   Green LED        Alert L0 normal / steady ON
#    P3   OUT   Yellow LED       Alert L1 warning / L3 SOS rapid flash
#    P4   OUT   Red LED          Alert L2 fall    / L3 SOS rapid flash
#    P9   I2C   SDA              Hardware SDA — shared bus (MPU-6050 + BH1750)
#    P10  I2C   SCL              Hardware SCL
#    P21  OUT   Passive buzzer   Active HIGH
#    P22  IN    Dismiss button   PULL_UP, active LOW  (idle HIGH, press LOW)
#    P14  ADC   NTC thermistor   ATTN_11DB; 3V3->10k->P14->10k NTC->GND
#    P15  ADC   Battery divider  ATTN_11DB; LiPo+->100k->P15->100k->GND
#    P19  RX    GPS UART1        NEO-6M TX->P19, 9600 baud, receive only
#    P0/P1      UART0 console    Default REPL — not initialised in firmware
#
#  I2C DEVICES (verified scan):
#    MPU-6050 @ 0x68  (AD0 -> GND)
#    BH1750   @ 0x23  (ADDR confirmed by hardware scan — NOT 0x46)
#
#  CRITICAL POWER RULE — read before every hardware session:
#    PowerBoost 5V -> LoPy4 VIN ONLY.
#    Every sensor, LED, buzzer, and GPS module runs from LoPy4 3V3.
#    Applying 5V to any GPIO or sensor pin WILL destroy it.
#    The NEO-6M GPS was destroyed once by 5V — do not repeat.
#
#  PYCOM MICROPYTHON CONSTRAINTS — enforced throughout:
#    No f-strings  ->  use string concatenation
#    Use utime     ->  not time
#    Use ujson     ->  not json
#    No walrus, no match/case, no structural pattern matching
#
#  FLASH COMMAND (Windows — adjust COM port):
#    uvx mpremote connect COM10 cp Wearable/wearable.py :main.py + reset + repl
# =============================================================================

from machine import Pin, I2C, ADC, UART
from network import LoRa
import socket
import utime
import math
import ujson
import gc


# =============================================================================
#  SECTION 1 — CONFIGURATION
#  All tuneable parameters in one place — safe to edit.
# =============================================================================

# ── Device identity ───────────────────────────────────────────────────────────
SKIER_ID = 'SK01'

# ── LoRa link (must match receiver.py exactly) ─────────────────────────
LORA_FREQUENCY = 915000000   # Hz — 915 MHz AU915 band
LORA_SF        = 7           # Spreading factor  (7 = fastest / lowest range)

# ── Telemetry timing (from wearable.py: SEND_INTERVAL_MS = 5000) ─────────
TELEMETRY_INTERVAL_MS = 5000   # Normal TX cadence (ms)
FAST_TX_INTERVAL_MS   = 2000   # TX cadence when alert level >= 2 (ms)
LOOP_SLEEP_MS         = 20     # Main loop yield — keeps IMU sampling near 50 Hz
GC_INTERVAL_MS        = 60000  # Periodic garbage collection (ms)
WARMUP_MS             = 15000  # ms before first TX and alert activation (prevents false alarms on boot)
L2_ACK_TIMEOUT_MS     = 60000  # ms before unacknowledged L2 escalates to L3

# ── Alert thresholds (match wearable.py and wearable.py exactly) ───
FALL_MAG_THRESHOLD  = 35000   # Raw IMU units — sudden spike -> fall
MOTION_BAND_LOW     = 14000   # Below this: unusual low-g (free fall / tumble)
MOTION_BAND_HIGH    = 18000   # Above this: movement / normal vibration
IMMOBILITY_L1_SECS  = 30      # Immobile this long -> L1 warning
IMMOBILITY_L2_SECS  = 60      # Immobile this long -> L2 alert
IMMOBILITY_L3_SECS  = 120     # Fall + immobile this long -> L3 SOS
FALL_LATCH_MS       = 300000  # Fall holds L2 minimum for 5 minutes (ms)

SKIN_TEMP_L1_C      = 15.0    # C  below this -> L1 cold warning
SKIN_TEMP_L3_C      = 10.0    # C  below this -> L3 critical cold
BURIAL_LUX          = 10.0    # lux — darkness threshold for burial detection
BATTERY_L1_PCT      = 20      # %  below this -> L1 battery warning

# ── GPS ───────────────────────────────────────────────────────────────────────
GPS_STALE_MS = 30000   # ms after last fix before GPS data is zeroed in packet

# ── Buzzer patterns: (on_ms, off_ms) per alert level ─────────────────────────
#    From wearable.py — proven on hardware.
BUZ_PATTERNS = {
    1: (100, 1900),   # Gentle single beep — cold / battery warning
    2: (300,  700),   # Urgent — fall detected
    3: (200,  200),   # Rapid SOS — burial / critical
}

# ── LED flash timing for L3 SOS (from hardware test test_leds: 120ms) ────────
LED_FLASH_MS = 120   # on/off half-period for yellow + red SOS flash

# ── Rolling average buffer depths ────────────────────────────────────────────
BUF_LIGHT = 3   # ~15 s at 5 s cadence
BUF_TEMP  = 5   # ~25 s
BUF_GPS   = 3   # ~15 s

# ── Button debounce ───────────────────────────────────────────────────────────
DEBOUNCE_MS = 50


# =============================================================================
#  SECTION 2 — CONSTANTS
#  Verified hardware values — these match the physical build.  Do not change
#  without corresponding hardware rework and re-verification.
# =============================================================================

# ── Pin names ─────────────────────────────────────────────────────────────────
PIN_LED_GREEN  = 'P2'
PIN_LED_YELLOW = 'P3'
PIN_LED_RED    = 'P4'
PIN_I2C_SDA    = 'P9'
PIN_I2C_SCL    = 'P10'
PIN_BUTTON     = 'P22'
PIN_BUZZER     = 'P21'
PIN_NTC_ADC    = 'P14'
PIN_BATT_ADC   = 'P15'
PIN_GPS_RX     = 'P19'

# ── I2C addresses (confirmed by hardware scan) ────────────────────────────────
MPU6050_ADDR = 0x68   # AD0 -> GND
BH1750_ADDR  = 0x23   # Hardware scan confirmed — NOT 0x46

# ── MPU-6050 register addresses ───────────────────────────────────────────────
MPU_PWR_MGMT_1 = 0x6B
MPU_ACCEL_CFG  = 0x1C
MPU_ACCEL_XOUT = 0x3B
MPU_ACCEL_LSB  = 16384.0   # LSB per g at default +/-2g range

# ── BH1750 command bytes (init sequence verified by Full-Hardware_Test.py) ────
BH1750_POWER_ON   = 0x01   # Must send BEFORE continuous-mode command
BH1750_CONT_HIRES = 0x10   # Continuous high-res mode (~120-180 ms/sample)
BH1750_LUX_DIV    = 1.2    # raw counts -> lux

# ── ADC / NTC — proven 3.3 V reference convention from hardware test ──────────
ADC_FULL_SCALE = 4095.0
ADC_VREF       = 3.3      # Verified reference voltage for all ADC formulas
NTC_SERIES_R   = 10000.0  # Fixed series resistor (3V3 side)
NTC_NOMINAL_R  = 10000.0  # NTC nominal resistance at 25 C
NTC_NOMINAL_T  = 25.0     # Celsius
NTC_BETA       = 3950.0
NTC_RAW_MIN    = 10       # <= this: open or short fault
NTC_RAW_MAX    = 4085     # >= this: open or short fault

# ── Battery divider ───────────────────────────────────────────────────────────
BATT_DIVIDER = 2.0    # V_bat = V_pin * 2 (two equal 100 k resistors)
BATT_FULL_V  = 4.2    # Full charge
BATT_EMPTY_V = 3.3    # Empty
BATT_OK_LOW  = 3.0    # Below this: likely no battery, skip reading
BATT_OK_HIGH = 4.3    # Above this: impossible, skip reading

# ── Lux sentinel ─────────────────────────────────────────────────────────────
LUX_UNAVAILABLE = -1.0   # Returned / cached when BH1750 has no valid reading


# =============================================================================
#  HARDWARE INITIALISATION
#  Every device is wrapped in try/except.  A failed device sets its flag to
#  False; the rest of the firmware checks that flag before using the device.
# =============================================================================

print('')
print('SkiSafe ' + SKIER_ID + ' — Pycom MicroPython 1.20.2.r6')
print('Initialising hardware...')
print('')

# ── GPIO outputs (LEDs and buzzer) ───────────────────────────────────────────
led_green  = Pin(PIN_LED_GREEN,  mode=Pin.OUT, value=0)
led_yellow = Pin(PIN_LED_YELLOW, mode=Pin.OUT, value=0)
led_red    = Pin(PIN_LED_RED,    mode=Pin.OUT, value=0)
buzzer     = Pin(PIN_BUZZER,     mode=Pin.OUT, value=0)

# ── GPIO input (dismiss button) ───────────────────────────────────────────────
button = Pin(PIN_BUTTON, mode=Pin.IN, pull=Pin.PULL_UP)   # idle HIGH, press LOW

# ── I2C shared bus ────────────────────────────────────────────────────────────
# Hardware SDA = P9, SCL = P10.  Verified final build.  NOT P21/P22.
_i2c = None
_i2c_found = []
try:
    _i2c = I2C(0, pins=(PIN_I2C_SDA, PIN_I2C_SCL))
    utime.sleep_ms(50)
    _i2c_found = _i2c.scan()
    print('I2C scan    : ' + str([hex(d) for d in _i2c_found]))
except Exception as _e:
    print('I2C FATAL   : ' + str(_e))
    _i2c = None
    _i2c_found = []

# ── MPU-6050  (accelerometer / fall detection) ────────────────────────────────
# Wake from sleep: write 0x00 to PWR_MGMT_1 (0x6B).
# Set accelerometer to +/-2g range: write 0x00 to ACCEL_CONFIG (0x1C).
# Both steps verified by Full-Hardware_Test.py test_mpu6050().
_mpu_ok = False
if _i2c is not None and MPU6050_ADDR in _i2c_found:
    try:
        _i2c.writeto_mem(MPU6050_ADDR, MPU_PWR_MGMT_1, bytes([0x00]))
        utime.sleep_ms(50)
        _i2c.writeto_mem(MPU6050_ADDR, MPU_ACCEL_CFG, bytes([0x00]))
        _mpu_ok = True
        print('MPU-6050    : OK  (0x68)  fall detection enabled')
    except Exception as _e:
        print('MPU-6050    : FAILED  ' + str(_e) + '  (fall detection degraded)')
else:
    print('MPU-6050    : NOT FOUND  (fall detection degraded)')

# ── BH1750  (ambient light / burial detection) ────────────────────────────────
# Init sequence verified by Full-Hardware_Test.py test_bh1750():
#   1. Send POWER_ON  (0x01) — some chips skip ACK here; that is non-fatal.
#   2. Wait 10 ms.
#   3. Send CONT_HIRES (0x10) — starts continuous high-resolution measurement.
#   4. Wait 180 ms for the first conversion to complete.
# Without the power-on step, first reads may return 0 or 65535.
_bh1750_ok = False
_bh1750_errors = 0
if _i2c is not None and BH1750_ADDR in _i2c_found:
    try:
        try:
            _i2c.writeto(BH1750_ADDR, bytes([BH1750_POWER_ON]))
            utime.sleep_ms(10)
        except Exception:
            pass   # Power-on ACK not always reliable — not fatal
        _i2c.writeto(BH1750_ADDR, bytes([BH1750_CONT_HIRES]))
        utime.sleep_ms(180)
        _bh1750_ok = True
        print('BH1750      : OK  (0x23)  burial detection enabled')
    except Exception as _e:
        print('BH1750      : FAILED  ' + str(_e) + '  (burial detection degraded)')
else:
    print('BH1750      : NOT FOUND  (burial detection degraded)')

# ── ADC channels ─────────────────────────────────────────────────────────────
_adc      = ADC()
_ntc_ch   = _adc.channel(pin=PIN_NTC_ADC,  attn=ADC.ATTN_11DB)
_batt_ch  = _adc.channel(pin=PIN_BATT_ADC, attn=ADC.ATTN_11DB)
print('ADC         : OK  NTC=P14  Battery=P15  ATTN_11DB')

# ── GPS UART ─────────────────────────────────────────────────────────────────
# UART1, 9600 8N1, receive-only.
# pins=(TX, RX): TX=None — GPS RX line left disconnected (not needed).
# Verified syntax from Full-Hardware_Test.py test_gps().
_gps_uart = None
try:
    _gps_uart = UART(1, baudrate=9600, pins=(None, PIN_GPS_RX))
    print('GPS UART    : OK  UART1  P19=RX  9600 baud  receive-only')
except Exception as _e:
    print('GPS UART    : FAILED  ' + str(_e))

# ── LoRa radio ────────────────────────────────────────────────────────────────
# Config must match receiver.py exactly.
# LoRa.ALWAYS_ON keeps the radio ready to receive downlink ACKs between TXs.
_lora_sock = None
_lora_ok   = False
try:
    _lora = LoRa(
        mode        = LoRa.LORA,
        region      = LoRa.AU915,
        frequency   = LORA_FREQUENCY,
        bandwidth   = LoRa.BW_125KHZ,
        sf          = LORA_SF,
        preamble    = 8,
        coding_rate = LoRa.CODING_4_5,
        power_mode  = LoRa.ALWAYS_ON,
    )
    _lora_sock = socket.socket(socket.AF_LORA, socket.SOCK_RAW)
    _lora_sock.setblocking(False)
    _lora_ok = True
    print('LoRa        : OK  ' + str(LORA_FREQUENCY // 1000000) + ' MHz  SF' + str(LORA_SF) + '  ALWAYS_ON')
except Exception as _e:
    print('LoRa        : FATAL  ' + str(_e))
    _lora_ok = False

print('')


# =============================================================================
#  SECTION 4 — GPS PROCESSING
#  Non-blocking character-by-character UART drain.
#  Parses GNRMC / GPRMC (position + speed) and GNGGA / GPGGA (altitude + sats).
#  GPS globals are updated in-place; stale check uses ticks_ms.
# =============================================================================

_gps_rx_buf  = b''         # Accumulates bytes until \n or \r
_gps_fix_ms  = 0           # ticks_ms of last valid fix (0 = never)

gps_lat   = 0.0
gps_lon   = 0.0
gps_alt   = 0.0
gps_speed = 0.0
gps_fix   = False
gps_sats  = 0


def _nmea_to_decimal(raw, hemi):
    """Convert NMEA DDDMM.MMMM + hemisphere character to signed decimal degrees."""
    try:
        dot  = raw.index('.')
        deg  = int(raw[:dot - 2])
        mins = float(raw[dot - 2:])
        dec  = deg + mins / 60.0
        if hemi in ('S', 'W'):
            dec = -dec
        return dec
    except Exception:
        return None


def _parse_nmea(sentence):
    """
    Parse one complete NMEA sentence (stripped, no CRLF) and update GPS globals.
    Handles: $GPRMC $GNRMC $GPGGA $GNGGA.
    All exceptions are silently swallowed — malformed sentences are discarded.
    """
    global gps_lat, gps_lon, gps_alt, gps_speed, gps_fix, gps_sats, _gps_fix_ms

    if not sentence.startswith('$'):
        return

    # Strip NMEA checksum (*HH)
    if '*' in sentence:
        sentence = sentence[:sentence.index('*')]

    fields = sentence.split(',')
    if not fields:
        return
    msg = fields[0]

    # RMC — recommended minimum: position, speed, validity flag
    if msg in ('$GPRMC', '$GNRMC') and len(fields) >= 8:
        if fields[2] == 'A':   # 'A' = data valid,  'V' = void / no fix
            lat = _nmea_to_decimal(fields[3], fields[4])
            lon = _nmea_to_decimal(fields[5], fields[6])
            if lat is not None and lon is not None:
                gps_lat  = lat
                gps_lon  = lon
                gps_fix  = True
                _gps_fix_ms = utime.ticks_ms()
            try:
                gps_speed = float(fields[7]) * 1.852   # knots -> km/h
            except Exception:
                gps_speed = 0.0
        else:
            gps_fix = False

    # GGA — fix data: altitude, satellite count, fix quality indicator
    elif msg in ('$GPGGA', '$GNGGA') and len(fields) >= 10:
        try:
            s = fields[7].strip()
            if s:
                gps_sats = int(s)
        except Exception:
            pass
        
        if fields[6] not in ('', '0') and fields[9].strip():
            try:
                gps_alt = float(fields[9])
            except Exception:
                pass


def update_gps():
    """
    Drain all available bytes from the GPS UART and parse complete NMEA sentences.
    Non-blocking — returns immediately when the RX buffer is empty.
    A 128-byte hard limit on the accumulation buffer guards against runaway growth
    if the GPS sends non-terminated data (e.g. at power-on).
    """
    global _gps_rx_buf
    if _gps_uart is None:
        return
    while _gps_uart.any():
        ch = _gps_uart.read(1)
        if ch is None:
            break
        if ch in (b'\n', b'\r'):
            if _gps_rx_buf:
                try:
                    _parse_nmea(_gps_rx_buf.decode('ascii', 'ignore').strip())
                except Exception:
                    pass
                _gps_rx_buf = b''
        else:
            _gps_rx_buf += ch
            if len(_gps_rx_buf) > 128:
                _gps_rx_buf = b''   # Overflow guard


def gps_is_fresh(now_ms):
    """Return True if the last valid GPS fix is less than GPS_STALE_MS old."""
    if not gps_fix or _gps_fix_ms == 0:
        return False
    return utime.ticks_diff(now_ms, _gps_fix_ms) < GPS_STALE_MS


# =============================================================================
#  SECTION 5 — ACCELEROMETER PROCESSING  (MPU-6050)
#  Direct register reads — no driver object needed.
#  Falls back to 1g resting value if the IMU is unavailable or errors.
# =============================================================================

def read_imu_magnitude():
    """
    Read the MPU-6050 acceleration vector magnitude in raw 16-bit units.
    At rest, magnitude ~= 16384 (1g at ±2g range, 16384 LSB/g).
    Fall detection threshold is 35000 raw units (~2.1g sudden spike).
    Returns 16384.0 (safe 1g default) on any error or if IMU is absent.
    """
    if not _mpu_ok or _i2c is None:
        return 16384.0
    try:
        d  = _i2c.readfrom_mem(MPU6050_ADDR, MPU_ACCEL_XOUT, 6)
        ax = (d[0] << 8) | d[1]
        ay = (d[2] << 8) | d[3]
        az = (d[4] << 8) | d[5]
        if ax > 32767: ax -= 65536
        if ay > 32767: ay -= 65536
        if az > 32767: az -= 65536
        return math.sqrt(ax * ax + ay * ay + az * az)
    except Exception:
        return 16384.0


# =============================================================================
#  SECTION 6 — LIGHT SENSOR  (BH1750)
#  Sensor runs in continuous high-resolution mode set at initialisation.
#  Returns LUX_UNAVAILABLE (-1.0) on read failure.
#  Auto-recovery: after 5 consecutive errors, attempts to re-send the
#  continuous-mode command so a transient I2C glitch does not permanently
#  disable burial detection.
# =============================================================================

def read_lux():
    """
    Read ambient illuminance from BH1750 (lux, float).
    Returns LUX_UNAVAILABLE (-1.0) if the sensor is absent or read fails.
    """
    global _bh1750_ok, _bh1750_errors
    if not _bh1750_ok or _i2c is None:
        return LUX_UNAVAILABLE
    try:
        data = _i2c.readfrom(BH1750_ADDR, 2)
        raw  = (data[0] << 8) | data[1]
        _bh1750_errors = 0
        return raw / BH1750_LUX_DIV
    except Exception:
        _bh1750_errors += 1
        if _bh1750_errors >= 5:
            # Attempt to restore continuous mode after repeated failures
            try:
                try:
                    _i2c.writeto(BH1750_ADDR, bytes([BH1750_POWER_ON]))
                    utime.sleep_ms(10)
                except Exception:
                    pass
                _i2c.writeto(BH1750_ADDR, bytes([BH1750_CONT_HIRES]))
                utime.sleep_ms(180)   # Blocking — acceptable on rare recovery path
                _bh1750_errors = 0
                print('BH1750: continuous mode re-sent after read errors')
            except Exception:
                pass
        return LUX_UNAVAILABLE


# =============================================================================
#  SECTION 7 — TEMPERATURE AND BATTERY READING
# =============================================================================

def read_skin_temp():
    """
    Read skin temperature via NTC thermistor on P14.
    Circuit: 3V3 -> 10k (series) -> P14 -> 10k NTC -> GND.
    NTC is on the GND side of the divider.

    Formula proven by Full-Hardware_Test.py test_ntc_temperature():
      voltage = raw / 4095.0 * 3.3
      r_ntc   = R_SERIES * voltage / (3.3 - voltage)
      T (K)   = 1 / (1/T_nominal + ln(r_ntc/R_nominal) / Beta)

    Averages 8 ADC samples to reduce noise (adds ~16 ms blocking per read;
    acceptable — only called on TX cadence, not every tick).

    Returns temperature in Celsius, or -99.0 as a fault sentinel.
    """
    total = 0
    for _ in range(8):
        total += _ntc_ch.value()
        utime.sleep_ms(2)
    raw = total >> 3   # integer divide by 8

    if raw <= NTC_RAW_MIN or raw >= NTC_RAW_MAX:
        return -99.0   # Open circuit or short

    voltage = raw / ADC_FULL_SCALE * ADC_VREF
    if voltage >= ADC_VREF:
        return -99.0

    r_ntc = NTC_SERIES_R * voltage / (ADC_VREF - voltage)

    try:
        inv_t = ((1.0 / (NTC_NOMINAL_T + 273.15))
                 + math.log(r_ntc / NTC_NOMINAL_R) / NTC_BETA)
        return (1.0 / inv_t) - 273.15
    except Exception:
        return -99.0


def read_battery():
    """
    Read battery voltage and charge percentage via voltage divider on P15.
    Circuit: LiPo+ -> 100k -> P15 -> 100k -> GND  =>  V_P15 = V_bat / 2.

    Averages 16 samples to suppress ADC noise (adds ~32 ms).
    Called on TX cadence only.

    Returns (voltage_volts, percent_int).
    Returns (0.0, 0) when the reading is outside the plausible 3.0-4.3 V range
    (e.g. no cell connected, or USB power only).
    """
    total = 0
    for _ in range(16):
        total += _batt_ch.value()
        utime.sleep_ms(2)
    raw   = total >> 4              # divide by 16
    v_pin = raw / ADC_FULL_SCALE * ADC_VREF
    v_bat = v_pin * BATT_DIVIDER

    if v_bat < BATT_OK_LOW or v_bat > BATT_OK_HIGH:
        return 0.0, 0

    pct = int((v_bat - BATT_EMPTY_V) / (BATT_FULL_V - BATT_EMPTY_V) * 100)
    if pct < 0:   pct = 0
    if pct > 100: pct = 100
    return v_bat, pct


# =============================================================================
#  SECTION 8 — ROLLING AVERAGE HELPERS
#  Each sensor maintains a small FIFO buffer.  Averages smooth noisy readings
#  without introducing long blocking windows.
# =============================================================================

_lux_buf   = []
_temp_buf  = []
_lat_buf   = []
_lon_buf   = []
_alt_buf   = []
_speed_buf = []


def _avg(buf):
    """Return the mean of a list, or 0.0 if empty."""
    return sum(buf) / len(buf) if buf else 0.0


def _push(buf, val, maxlen):
    """Append val to buf, discarding the oldest entry when full."""
    buf.append(val)
    if len(buf) > maxlen:
        buf.pop(0)


# =============================================================================
#  SECTION 9 — ALERT EVALUATION
#  Implements the SkiSafe four-level alert state machine.
#
#  Level 0 — Normal     : no significant hazard detected
#  Level 1 — Warning    : low battery, cold temperature, or short immobility
#  Level 2 — Alert      : fall detected (latched 5 min) or prolonged immobility
#  Level 3 — SOS        : burial (darkness+immobility), critical cold, or
#                         fall with long unresponsiveness
#
#  Fall latch uses ticks_ms so it works correctly regardless of RTC state.
#  Thresholds match wearable.py scenarios and wearable.py exactly.
# =============================================================================

_last_motion_ms  = utime.ticks_ms()   # ticks_ms of last detected movement
_fall_latch_ms   = 0                   # ticks_ms when fall was latched (0 = none)


def compute_alert(mag, lux, skin_temp, batt_pct, now_ms):
    """
    Compute the current alert level (0-3) from all sensor inputs.

    Parameters:
      mag       - IMU magnitude (raw 16-bit units, default 16384 = 1g)
      lux       - Ambient light (lux, LUX_UNAVAILABLE = sensor absent)
      skin_temp - Skin temperature (C, -99.0 = sensor fault)
      batt_pct  - Battery percentage (int 0-100, 0 = reading unavailable)
      now_ms    - Current utime.ticks_ms()

    Returns (level, fall_spike_this_tick, immobile_seconds).
    """
    global _last_motion_ms, _fall_latch_ms

    # ── Motion / immobility tracking ─────────────────────────────────────────
    # Movement is defined as the IMU vector leaving the normal 1g resting band.
    # The motion timer resets whenever the skier moves.  Immobility accumulates
    # when the wearable stays flat and still.
    if mag < MOTION_BAND_LOW or mag > MOTION_BAND_HIGH:
        _last_motion_ms = now_ms

    immobile_ms   = utime.ticks_diff(now_ms, _last_motion_ms)
    immobile_secs = immobile_ms // 1000

    # ── Fall detection ────────────────────────────────────────────────────────
    # A fall produces a sharp spike well above the 1g resting magnitude.
    # Once latched, the alert stays at L2+ for FALL_LATCH_MS milliseconds
    # even if the skier gets back up, to prevent premature auto-clearance.
    fall_now = (mag > FALL_MAG_THRESHOLD)
    if fall_now:
        _fall_latch_ms = now_ms   # refresh latch timestamp on every spike tick

    fall_latched = (
        _fall_latch_ms > 0 and
        utime.ticks_diff(now_ms, _fall_latch_ms) < FALL_LATCH_MS
    )

    # ── Burial detection ─────────────────────────────────────────────────────
    # Requires BOTH darkness AND sustained immobility to avoid false triggers
    # from the sensor being briefly covered (e.g. glove placed on wearable).
    # A lux reading of LUX_UNAVAILABLE (-1.0) disables burial detection cleanly
    # so an absent BH1750 does not generate false SOS alerts.
    buried = (
        lux >= 0.0 and
        lux < BURIAL_LUX and
        immobile_secs >= IMMOBILITY_L2_SECS
    )

    # ── Level computation: highest applicable condition wins ─────────────────
    level = 0

    # L1 — local warnings
    if batt_pct > 0 and batt_pct < BATTERY_L1_PCT:
        level = max(level, 1)
    if skin_temp > -50.0 and skin_temp < SKIN_TEMP_L1_C:
        level = max(level, 1)
    if immobile_secs >= IMMOBILITY_L1_SECS:
        level = max(level, 1)

    # L2 — serious events
    if fall_latched:
        level = max(level, 2)
    if immobile_secs >= IMMOBILITY_L2_SECS:
        level = max(level, 2)

    # L3 — critical / SOS
    if skin_temp > -50.0 and skin_temp < SKIN_TEMP_L3_C:
        level = max(level, 3)
    if buried:
        level = max(level, 3)
    if fall_latched and immobile_secs >= IMMOBILITY_L3_SECS:
        level = max(level, 3)

    return level, fall_now, immobile_secs


def clear_fall_latch():
    """Clear the fall latch (call on button press or hub ACK)."""
    global _fall_latch_ms
    _fall_latch_ms = 0


# =============================================================================
#  SECTION 10 — LED CONTROL  (non-blocking state machine)
#
#  LED mapping (from pinout_mapping.md and hardware test):
#    L0 Normal  : Green steady ON,  Yellow OFF, Red OFF
#    L1 Warning : Yellow steady ON, Green OFF,  Red OFF
#    L2 Alert   : Red steady ON,    Green OFF,  Yellow OFF
#    L3 SOS     : Yellow + Red rapid flash (120 ms on/off), Green OFF
#
#  L3 flash pattern verified by test_leds() in Full-Hardware_Test.py.
#  All level transitions are immediate — no sleep required.
# =============================================================================

_led_flash_state = False
_led_flash_ms    = 0


def update_leds(level, now_ms):
    """
    Update LED outputs to match current alert level.
    Non-blocking: the L3 flash is driven entirely by elapsed timestamp.
    Safe to call every main loop iteration without impacting other subsystems.
    """
    global _led_flash_state, _led_flash_ms

    if level == 0:
        led_green(1); led_yellow(0); led_red(0)

    elif level == 1:
        led_green(0); led_yellow(1); led_red(0)

    elif level == 2:
        led_green(0); led_yellow(0); led_red(1)

    else:   # level == 3 — Yellow + Red rapid flash, Green always OFF
        led_green(0)
        if utime.ticks_diff(now_ms, _led_flash_ms) >= LED_FLASH_MS:
            _led_flash_state = not _led_flash_state
            v = 1 if _led_flash_state else 0
            led_yellow(v)
            led_red(v)
            _led_flash_ms = now_ms


# =============================================================================
#  SECTION 11 — BUZZER CONTROL  (non-blocking state machine)
#
#  The buzzer alternates between HIGH (on) and LOW (off) at pattern-defined
#  intervals without any sleep().  For a passive piezo this produces audible
#  click-based alerts whose cadence clearly indicates the severity level.
#
#  Buzzer is muted when:
#    - Alert level is 0 (normal)
#    - User presses the dismiss button  (_buz_muted flag)
#    - Hub sends ACK downlink           (_buz_muted flag)
#  Mute is automatically cleared when the alert level escalates.
# =============================================================================

_buz_state   = False
_buz_last_ms = 0
_buz_muted   = False


def update_buzzer(level, now_ms):
    """
    Drive the buzzer output according to the current alert level.
    Non-blocking — uses elapsed timestamps instead of sleep().
    Call every main loop iteration.
    """
    global _buz_state, _buz_last_ms, _buz_muted

    if _buz_muted or level == 0:
        buzzer(0)
        _buz_state = False
        return

    on_ms, off_ms = BUZ_PATTERNS.get(level, (200, 200))
    period = on_ms if _buz_state else off_ms

    if utime.ticks_diff(now_ms, _buz_last_ms) >= period:
        _buz_state = not _buz_state
        buzzer(1 if _buz_state else 0)
        _buz_last_ms = now_ms


# =============================================================================
#  SECTION 12 — LORA TRANSMISSION
# =============================================================================

_pkt_count = 0


def build_and_send(level, skin_temp, lux, lat, lon, alt, speed, batt_pct):
    """
    Build a compact JSON telemetry packet and transmit over LoRa.

    Packet keys (match wearable.py and wearable.py exactly):
      i  — skier ID         c  — packet counter
      st — skin temp (C)    lx — illuminance (lux)
      la — latitude         lo — longitude
      al — altitude (m)     sp — speed (km/h)
      bt — battery (%)      a  — alert level (0-3)

    GPS lat/lon/alt/speed are 0.0 when no valid fix is available, so the
    hub always receives valid parseable JSON regardless of GPS state.

    Typical packet size: ~105 bytes.
    Receiver uses recv(256) — no split-read risk.
    EAGAIN retry: up to 3 attempts with 50 ms backoff if the radio is busy.
    """
    global _pkt_count
    if not _lora_ok or _lora_sock is None:
        return
    _pkt_count += 1

    # Clamp lux for transmission: send 0.0 when unavailable (-1.0 sentinel)
    tx_lux = max(lux, 0.0)

    payload  = '{"i":"' + SKIER_ID + '"'
    payload += ',"c":'  + str(_pkt_count)
    payload += ',"st":' + str(round(skin_temp, 1))
    payload += ',"lx":' + str(round(tx_lux, 1))
    payload += ',"la":' + str(round(lat, 6))
    payload += ',"lo":' + str(round(lon, 6))
    payload += ',"al":' + str(round(alt, 1))
    payload += ',"sp":' + str(round(speed, 1))
    payload += ',"bt":' + str(batt_pct)
    payload += ',"a":'  + str(level)
    payload += '}'

    # Send — identical pattern to wearable.py (plain try/except, no recv).
    # Do NOT call recv() anywhere near this send.  On Pycom ALWAYS_ON, any
    # recv() call puts the SX1276 into aggressive RX mode which blocks the next
    # send() with EAGAIN and prevents the packet from leaving the antenna.
    try:
        _lora_sock.send(payload.encode())
        _gps_info = ('  lat=' + str(round(lat, 4)) + ' lon=' + str(round(lon, 4))
                     if gps_fix else '  gps=none')
        print('TX #' + str(_pkt_count) +
              ' [' + str(len(payload)) + 'B]' +
              '  a=' + str(level) +
              '  skin=' + str(round(skin_temp, 1)) + 'C' +
              '  lux=' + str(round(tx_lux, 1)) +
              '  bat=' + str(batt_pct) + '%' +
              _gps_info)
    except Exception as _e:
        print('TX FAILED #' + str(_pkt_count) + ': ' + str(_e))


def check_downlink():
    """
    Non-blocking check for incoming LoRa messages from the hub.
    Hub sends an 'ACK' string after an alert is acknowledged via the dashboard.
    ACK mutes the buzzer and clears the fall latch on this device.
    """
    global _buz_muted
    if not _lora_ok or _lora_sock is None:
        return
    try:
        data = _lora_sock.recv(64)
        if data:
            msg = data.decode('ascii', 'ignore').strip()
            print('RX downlink: ' + msg)
            if 'ACK' in msg:
                _buz_muted = True
                clear_fall_latch()
                print('Hub ACK received — buzzer muted, fall latch cleared')
    except Exception:
        pass


# =============================================================================
#  SECTION 13 — MAIN LOOP
#  Timestamp-based non-blocking scheduler.  Every subsystem is independent
#  and driven by elapsed time, not by sequential blocking sleeps.
#
#  Loop structure (each iteration, ~20 ms):
#    1.  Drain GPS UART (non-blocking, every tick)
#    2.  Read IMU magnitude (every tick, ~50 Hz)
#    3.  Refresh slow sensors on TX cadence (temp / lux / batt / GPS buffer)
#    4.  Debounce button and handle dismiss
#    5.  Compute alert level
#    6.  Auto-unmute buzzer if alert escalates past muted level
#    7.  Log alert level transitions
#    8.  Update LEDs (non-blocking)
#    9.  Update buzzer (non-blocking)
#   10.  Transmit LoRa telemetry (on TX cadence)
#   11.  Check for downlink ACK
#   12.  Periodic garbage collection (every 60 s)
#   13.  Yield LOOP_SLEEP_MS
# =============================================================================

print('All devices ready.')
print('Warming up ' + str(WARMUP_MS // 1000) + 's — TX and alerts suppressed.')
print('')

# Set initial LED state — green ON during warmup
led_green(1); led_yellow(0); led_red(0)

# ── Loop state ────────────────────────────────────────────────────────────────
_last_tx_ms    = utime.ticks_ms()
_last_gc_ms    = utime.ticks_ms()
_last_level      = 0
_l2_enter_ms     = 0                   # ticks_ms when level first reached L2+ (0 = inactive)
_warmup_start_ms = utime.ticks_ms()    # used to gate TX and alerts during the warmup window
_warmup_done     = False               # True once the warmup completion message has been printed

# ── Sensor caches (populated on first TX cadence tick) ───────────────────────
_cached_skin   = 0.0
_cached_lux    = LUX_UNAVAILABLE   # -1.0 until first BH1750 read
_cached_lat    = 0.0
_cached_lon    = 0.0
_cached_alt    = 0.0
_cached_speed  = 0.0
_cached_batt_v = 0.0
_cached_batt_p = 100               # Assume full until first ADC read
_batt_ema_p    = -1.0              # EMA of battery %; -1 = not yet initialised
BATT_EMA_ALPHA = 0.15              # Smoothing factor (lower = smoother, slower)

# ── Button debounce state ─────────────────────────────────────────────────────
_btn_last     = 1                   # Idle HIGH (PULL_UP, active LOW)
_btn_edge_ms  = utime.ticks_ms()   # ticks_ms of last state change

# ── Main loop ─────────────────────────────────────────────────────────────────
while True:
    now_ms = utime.ticks_ms()

    # ── Warmup gate — suppress TX, alerts, and buzzer for the first WARMUP_MS ─
    _warming_up = utime.ticks_diff(now_ms, _warmup_start_ms) < WARMUP_MS
    if not _warming_up and not _warmup_done:
        _warmup_done = True
        print('Warmup complete — telemetry and alerts active.')
        print('TX: ' + str(TELEMETRY_INTERVAL_MS) + 'ms normal  / ' +
              str(FAST_TX_INTERVAL_MS) + 'ms at L2+')
        print('')

    # ── 1. GPS — drain UART every tick (non-blocking) ─────────────────────────
    update_gps()

    # ── 2. IMU — read magnitude every tick (~50 Hz) ───────────────────────────
    mag = read_imu_magnitude()

    # ── 3. Slow sensor refresh on TX cadence ──────────────────────────────────
    tx_interval = FAST_TX_INTERVAL_MS if _last_level >= 2 else TELEMETRY_INTERVAL_MS
    tx_due = utime.ticks_diff(now_ms, _last_tx_ms) >= tx_interval

    if tx_due:
        # Skin temperature
        raw_temp = read_skin_temp()
        if raw_temp > -50.0:
            _push(_temp_buf, raw_temp, BUF_TEMP)
        _cached_skin = _avg(_temp_buf) if _temp_buf else 0.0

        # Ambient light
        raw_lux = read_lux()
        if raw_lux >= 0.0:
            _push(_lux_buf, raw_lux, BUF_LIGHT)
        # Use LUX_UNAVAILABLE (-1.0) when no readings exist — prevents
        # false burial detection if BH1750 is absent or has not yet read.
        _cached_lux = _avg(_lux_buf) if _lux_buf else LUX_UNAVAILABLE

        # GPS — only buffer readings from a current valid fix
        if gps_is_fresh(now_ms):
            _push(_lat_buf,   gps_lat,   BUF_GPS)
            _push(_lon_buf,   gps_lon,   BUF_GPS)
            _push(_alt_buf,   gps_alt,   BUF_GPS)
            _push(_speed_buf, gps_speed, BUF_GPS)
        _cached_lat   = _avg(_lat_buf)   if _lat_buf   else 0.0
        _cached_lon   = _avg(_lon_buf)   if _lon_buf   else 0.0
        _cached_alt   = _avg(_alt_buf)   if _alt_buf   else 0.0
        _cached_speed = _avg(_speed_buf) if _speed_buf else 0.0

        # Battery — 16-sample average + EMA to suppress ADC noise and load spikes
        _cached_batt_v, raw_batt_p = read_battery()
        if raw_batt_p > 0:
            if _batt_ema_p < 0.0:
                _batt_ema_p = float(raw_batt_p)   # seed EMA on first valid read
            else:
                _batt_ema_p = BATT_EMA_ALPHA * raw_batt_p + (1.0 - BATT_EMA_ALPHA) * _batt_ema_p
            _cached_batt_p = int(_batt_ema_p)

    # ── 4. Button — debounce and dismiss ─────────────────────────────────────
    btn_raw = button()
    if btn_raw != _btn_last:
        _btn_last    = btn_raw
        _btn_edge_ms = now_ms   # Capture edge timestamp for debounce window

    if (btn_raw == 0 and
            utime.ticks_diff(now_ms, _btn_edge_ms) >= DEBOUNCE_MS and
            not _buz_muted):
        _buz_muted = True
        clear_fall_latch()
        print('Alert dismissed via button')

    # ── 5. Alert evaluation ───────────────────────────────────────────────────
    level, fall_now, immobile_secs = compute_alert(
        mag, _cached_lux, _cached_skin, _cached_batt_p, now_ms
    )

    # ── 5a. L2 ACK timer — hold at L2, escalate to L3 if unacknowledged ──────
    # Once level reaches L2, it is latched there until the operator ACKs.
    # If no ACK arrives within L2_ACK_TIMEOUT_MS, automatically escalate to L3.
    # ACK is signalled by _buz_muted=True (button press or hub LoRa ACK).
    if not _warming_up:
        if level >= 2 and _l2_enter_ms == 0:
            _l2_enter_ms = now_ms
            print('L2+ entered — ACK within ' + str(L2_ACK_TIMEOUT_MS // 1000) + 's or auto-escalate to L3')
        if _l2_enter_ms > 0:
            if _buz_muted:
                # Operator acknowledged — release latch, let level fall naturally
                _l2_enter_ms = 0
            else:
                # Not yet acknowledged — hold at minimum L2
                level = max(level, 2)
                # Escalate to L3 after timeout
                if utime.ticks_diff(now_ms, _l2_enter_ms) >= L2_ACK_TIMEOUT_MS:
                    level = max(level, 3)

    # ── 6. Auto-unmute when alert escalates past the muted level ─────────────
    if not _warming_up and _buz_muted and level > _last_level:
        _buz_muted = False

    # ── 7. Log level transitions (suppressed during warmup) ───────────────────
    if not _warming_up and level != _last_level:
        msg = 'Alert: L' + str(_last_level) + ' -> L' + str(level)
        if fall_now:
            msg += '  (fall spike  mag=' + str(int(mag)) + ')'
        if immobile_secs >= IMMOBILITY_L1_SECS:
            msg += '  (immobile ' + str(immobile_secs) + 's)'
        if _cached_skin > -50.0:
            msg += '  skin=' + str(round(_cached_skin, 1)) + 'C'
        if _cached_lux >= 0.0:
            msg += '  lux=' + str(round(_cached_lux, 1))
        print(msg)
    _last_level = level

    # ── 8. LEDs — green during warmup, normal alert levels after ─────────────
    if _warming_up:
        led_green(1); led_yellow(0); led_red(0)
    else:
        update_leds(level, now_ms)

    # ── 9. Buzzer — silent during warmup ─────────────────────────────────────
    if not _warming_up:
        update_buzzer(level, now_ms)
    else:
        buzzer(0)

    # ── 10. LoRa transmit (suppressed during warmup) ─────────────────────────
    if tx_due and not _warming_up:
        build_and_send(
            level,
            _cached_skin,
            _cached_lux,
            _cached_lat,
            _cached_lon,
            _cached_alt,
            _cached_speed,
            _cached_batt_p,
        )
        _last_tx_ms = now_ms

    # ── 12. Garbage collection — every 60 s to prevent heap growth ───────────
    if utime.ticks_diff(now_ms, _last_gc_ms) >= GC_INTERVAL_MS:
        gc.collect()
        _last_gc_ms = now_ms

    # ── 13. Yield — maintains ~50 Hz IMU sampling cadence ────────────────────
    utime.sleep_ms(LOOP_SLEEP_MS)
