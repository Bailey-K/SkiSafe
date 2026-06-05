"""
SkiSafe Wearable - Full Hardware Component Test
================================================

PURPOSE
-------
Bench / bring-up validation for the assembled SkiSafe wearable prototype
(Pycom LoPy4, standalone - no expansion board). This script proves that every
physically-connected component on the VERIFIED final build is alive and
responding BEFORE any wearable application firmware is written.

This file is a TEST HARNESS only. It does NOT:
  * transmit any LoRa packets
  * talk to the hub
  * run fall-detection / alert / escalation logic
  * touch any cloud, dashboard, or storage

It DOES:
  * probe each component with its own dedicated function
  * print [PASS] / [WARNING] / [FAIL] for every individual check
  * keep going even if a component fails (no single test can abort the run)
  * never crash on a failed component (every test traps its own exceptions)
  * print a final summary report (totals + the warning/fail punch-list)

VERIFIED PIN MAP  (authoritative - from Hardware/pinout_mapping.md and
Hardware/breadboard_layout.md; do NOT change these):

    P2    Green  LED    output, anode -> 220R -> GND, active HIGH (level 0)
    P3    Yellow LED    output                              (level 1 / SOS flash)
    P4    Red    LED    output                              (level 2 / SOS flash)
    P9    I2C SDA       hardware SDA, shared bus
    P10   I2C SCL       hardware SCL, shared bus
    P21   Buzzer        output, passive piezo, active HIGH
    P22   Button        input, PULL_UP, active LOW (idle HIGH, press LOW)
    P14   NTC ADC       ATTN_11DB; 3V3 -> 10k -> P14 -> 10k NTC -> GND
    P15   Battery ADC   ATTN_11DB; LiPo+ -> 100k -> P15 -> 100k -> GND (Vpin=Vbat/2)
    P19   UART1 RX      NEO-6M GPS TX -> P19, 9600 8N1, RECEIVE ONLY
    P0    UART0 RX0     USB-UART adapter TXD -> P0; REPL + mpremote upload, 115200
    P1    UART0 TX0     LoPy4 TX -> USB-UART adapter RXD; print()/REPL output here

    I2C devices :  MPU-6050 @ 0x68 (AD0->GND),  BH1750 @ 0x23 (ADDR->3V3)
    Expected scan: ['0x23', '0x68']
    LoRa        :  built-in SX1276 - 915 MHz, AU915, SF7, BW125, CR 4/5, preamble 8

POWER SAFETY (do not violate):
    PowerBoost 1000C 5V -> LoPy4 VIN ONLY. Every sensor/LED/buzzer/GPS runs on
    3V3. 5V on the NEO-6M GPS already destroyed one module - never repeat.

USAGE
-----
Upload to the LoPy4 and either run it as main, or from the REPL:
    import hardware_test
    hardware_test.run()
The interactive checks (LED visual, buzzer audible, button press) prompt you on
the serial terminal.
"""

import time
import gc
import sys
import math

from machine import Pin, I2C, ADC, UART


# ---------------------------------------------------------------------------
# VERIFIED CONSTANTS  (match the final build - do not edit)
# ---------------------------------------------------------------------------

# GPIO / pin names
PIN_LED_GREEN  = 'P2'
PIN_LED_YELLOW = 'P3'
PIN_LED_RED    = 'P4'
PIN_I2C_SDA    = 'P9'
PIN_I2C_SCL    = 'P10'
PIN_BUZZER     = 'P21'
PIN_BUTTON     = 'P22'
PIN_NTC_ADC    = 'P14'
PIN_BATT_ADC   = 'P15'
PIN_GPS_RX     = 'P19'          # UART1 RX  (GPS module TX wires here)

# Buses
I2C_BUS_ID     = 0
GPS_UART_ID    = 1
GPS_BAUD       = 9600

# I2C device addresses (7-bit, as returned by i2c.scan())
MPU6050_ADDR   = 0x68           # AD0 -> GND
BH1750_ADDR    = 0x23           # ADDR -> 3V3  (verified by scan)
EXPECTED_I2C   = (0x23, 0x68)

# MPU-6050 registers
MPU_WHO_AM_I   = 0x75           # reads back 0x68
MPU_PWR_MGMT_1 = 0x6B           # write 0x00 to wake from sleep
MPU_ACCEL_XOUT = 0x3B           # 6 bytes: AX,AY,AZ (hi,lo each)
MPU_TEMP_OUT   = 0x41           # 2 bytes die temperature
MPU_ACCEL_LSB  = 16384.0        # LSB per g at default +/-2g range

# BH1750 commands
BH1750_POWER_ON   = 0x01
BH1750_CONT_HIRES = 0x10        # continuous high-res mode (~120-180 ms)
BH1750_LUX_DIV    = 1.2         # raw counts -> lux

# NTC divider + Steinhart-Hart (Beta) - matches verified NTC_test.py
NTC_R_SERIES   = 10000.0        # fixed series resistor (3V3 side)
NTC_R_NOMINAL  = 10000.0        # NTC nominal resistance @ 25 C
NTC_T_NOMINAL  = 25.0           # nominal temperature (C)
NTC_B_COEFF    = 3950.0         # Beta coefficient
NTC_VREF       = 3.3            # divider top rail / ADC scale (proven convention)
NTC_RAW_MIN    = 10             # <= this -> open/short fault
NTC_RAW_MAX    = 4085           # >= this -> open/short fault

# Battery divider
BATT_VREF      = 3.3            # ADC scale (proven convention)
BATT_DIVIDER   = 2.0           # Vbat = Vpin * 2 (two equal 100k resistors)
BATT_FULL_V    = 4.2
BATT_EMPTY_V   = 3.3
BATT_OK_LOW    = 3.0           # plausible-range gate (low)
BATT_OK_HIGH   = 4.3           # plausible-range gate (high)

# LoRa link config (init/verify ONLY - never transmit here)
LORA_FREQ_HZ   = 915000000     # 915 MHz, AU915 band
LORA_SF        = 7
LORA_PREAMBLE  = 8

# ADC full-scale counts (12-bit)
ADC_FULL_SCALE = 4095.0


# ---------------------------------------------------------------------------
# RESULT TRACKING
# ---------------------------------------------------------------------------

PASS = 'PASS'
WARNING = 'WARNING'
FAIL = 'FAIL'


class Report(object):
    """Collects [STATUS] lines and produces the final summary."""

    def __init__(self):
        self.rows = []          # list of (status, label, detail)

    def reset(self):
        self.rows = []

    def log(self, status, label, detail=''):
        self.rows.append((status, label, detail))
        line = '[{0}] {1}'.format(status, label)
        if detail:
            line += ' :: ' + detail
        print(line)

    def ok(self, label, detail=''):
        self.log(PASS, label, detail)

    def warn(self, label, detail=''):
        self.log(WARNING, label, detail)

    def fail(self, label, detail=''):
        self.log(FAIL, label, detail)

    def counts(self):
        p = w = f = 0
        for status, _, _ in self.rows:
            if status == PASS:
                p += 1
            elif status == WARNING:
                w += 1
            elif status == FAIL:
                f += 1
        return p, w, f, len(self.rows)


# Module-level singletons (reset at the start of every run()).
report = Report()
_i2c = None             # shared I2C bus, created once by the scan test


# ---------------------------------------------------------------------------
# SMALL HELPERS
# ---------------------------------------------------------------------------

def _section(title):
    print('')
    print('-' * 64)
    print('  ' + title)
    print('-' * 64)


def _trace(e):
    """Print a full traceback without ever raising."""
    try:
        sys.print_exception(e)
    except Exception:
        try:
            print('  (exception: {0})'.format(repr(e)))
        except Exception:
            pass


def _hexstr(buf):
    try:
        return ''.join('{:02x}'.format(b) for b in buf)
    except Exception:
        return str(buf)


def _s16(hi, lo):
    """Combine two bytes into a signed 16-bit value."""
    v = (hi << 8) | lo
    if v > 32767:
        v -= 65536
    return v


def _get_i2c():
    """Return the shared I2C bus, creating it on first use."""
    global _i2c
    if _i2c is None:
        _i2c = I2C(I2C_BUS_ID, pins=(PIN_I2C_SDA, PIN_I2C_SCL))
    return _i2c


def _tone(pin, freq_hz, dur_ms):
    """Drive a square-wave tone so a PASSIVE piezo actually sounds.
    (An active buzzer also sounds; this is safe for either type.)"""
    half_us = int(500000 / freq_hz)                 # half period, microseconds
    cycles = int((dur_ms * 1000) / (2 * half_us))
    for _ in range(cycles):
        pin(1)
        time.sleep_us(half_us)
        pin(0)
        time.sleep_us(half_us)


# ---------------------------------------------------------------------------
# 1. STARTUP / SELF-TEST
# ---------------------------------------------------------------------------

def test_startup():
    _section('1. STARTUP / SELF-TEST')

    # Device info + firmware version
    try:
        import os
        u = os.uname()
        print('  Board / sysname : {0}'.format(getattr(u, 'sysname', '?')))
        print('  Hardware        : {0}'.format(getattr(u, 'machine', '?')))
        print('  MicroPython rel : {0}'.format(getattr(u, 'release', '?')))
        print('  Firmware build  : {0}'.format(getattr(u, 'version', '?')))
        report.ok('Device / firmware info',
                  '{0} rel {1}'.format(getattr(u, 'sysname', '?'),
                                       getattr(u, 'release', '?')))
    except Exception as e:
        _trace(e)
        report.fail('Device / firmware info', repr(e))

    # Unique ID + CPU clock
    try:
        import machine
        print('  Unique ID       : {0}'.format(_hexstr(machine.unique_id())))
        try:
            print('  CPU frequency   : {0} Hz'.format(machine.freq()))
        except Exception:
            pass
    except Exception as e:
        _trace(e)
        report.warn('Unique ID', repr(e))

    # Available memory
    try:
        gc.collect()
        free = gc.mem_free()
        alloc = gc.mem_alloc()
        print('  Heap free       : {0} bytes'.format(free))
        print('  Heap allocated  : {0} bytes'.format(alloc))
        if free > 8000:
            report.ok('Available memory', '{0} bytes free'.format(free))
        else:
            report.warn('Available memory', 'low: {0} bytes free'.format(free))
    except Exception as e:
        _trace(e)
        report.warn('Available memory', repr(e))

    # Core driver APIs present?
    try:
        _ = (Pin, I2C, ADC, UART)
        report.ok('Core machine APIs', 'Pin / I2C / ADC / UART available')
    except Exception as e:
        _trace(e)
        report.fail('Core machine APIs', repr(e))

    # Debug console: if this text is visible, the UART0 (P0/P1) REPL path works.
    print('  Debug console   : you are reading this over UART0 (P0 RX0 / P1 TX0)')
    report.ok('Debug console (UART0 P0/P1)', 'output visible -> serial path OK')


# ---------------------------------------------------------------------------
# 2. I2C BUS SCAN  (shared SDA=P9 / SCL=P10)
# ---------------------------------------------------------------------------

def test_i2c_bus():
    _section('2. I2C BUS SCAN  (SDA=P9, SCL=P10)')
    try:
        i2c = _get_i2c()
        found = i2c.scan()
        found_hex = [hex(a) for a in found]
        print('  Devices found   : {0}'.format(found_hex))
        print('  Expected        : {0}'.format([hex(a) for a in EXPECTED_I2C]))
        missing = [hex(a) for a in EXPECTED_I2C if a not in found]
        if not missing:
            report.ok('I2C bus scan',
                      'both expected devices present {0}'.format(found_hex))
        elif found:
            report.warn('I2C bus scan',
                        'missing {0} (found {1})'.format(missing, found_hex))
        else:
            report.fail('I2C bus scan',
                        'no devices responded - check SDA/SCL/3V3/GND')
    except Exception as e:
        _trace(e)
        report.fail('I2C bus scan', repr(e))


# ---------------------------------------------------------------------------
# 3. MPU-6050 IMU  (I2C 0x68)
# ---------------------------------------------------------------------------

def test_mpu6050():
    _section('3. MPU-6050 IMU  (I2C 0x68)')
    try:
        i2c = _get_i2c()
        if MPU6050_ADDR not in i2c.scan():
            report.fail('MPU-6050', 'no ACK at 0x68 - check wiring / AD0->GND')
            return

        # WHO_AM_I should read back 0x68
        who = i2c.readfrom_mem(MPU6050_ADDR, MPU_WHO_AM_I, 1)[0]
        print('  WHO_AM_I (0x75) : 0x{0:02x}  (expect 0x68)'.format(who))

        # Wake the device (clear sleep bit in PWR_MGMT_1)
        i2c.writeto_mem(MPU6050_ADDR, MPU_PWR_MGMT_1, bytes([0x00]))
        time.sleep_ms(50)

        # Read accelerometer (signed 16-bit, 16384 LSB/g at +/-2g)
        d = i2c.readfrom_mem(MPU6050_ADDR, MPU_ACCEL_XOUT, 6)
        ax = _s16(d[0], d[1]) / MPU_ACCEL_LSB
        ay = _s16(d[2], d[3]) / MPU_ACCEL_LSB
        az = _s16(d[4], d[5]) / MPU_ACCEL_LSB
        mag = (ax * ax + ay * ay + az * az) ** 0.5
        print('  Accel X/Y/Z (g) : {0:+.2f} / {1:+.2f} / {2:+.2f}'.format(ax, ay, az))
        print('  |acceleration|  : {0:.2f} g  (expect ~1.0 g at rest)'.format(mag))

        # Die temperature (bonus): degC = raw/340 + 36.53
        t = i2c.readfrom_mem(MPU6050_ADDR, MPU_TEMP_OUT, 2)
        tc = _s16(t[0], t[1]) / 340.0 + 36.53
        print('  Die temperature : {0:.1f} C'.format(tc))

        if who == 0x68 and 0.3 < mag < 3.0:
            report.ok('MPU-6050', 'ID 0x68, |a|={0:.2f} g'.format(mag))
        elif who == 0x68:
            report.warn('MPU-6050',
                        'ID ok but |a|={0:.2f} g outside 0.3-3.0 g'.format(mag))
        else:
            report.warn('MPU-6050', 'unexpected WHO_AM_I 0x{0:02x}'.format(who))
    except Exception as e:
        _trace(e)
        report.fail('MPU-6050', repr(e))


# ---------------------------------------------------------------------------
# 4. BH1750 AMBIENT LIGHT  (I2C 0x23)
# ---------------------------------------------------------------------------

def test_bh1750():
    _section('4. BH1750 LIGHT SENSOR  (I2C 0x23)')
    try:
        i2c = _get_i2c()
        if BH1750_ADDR not in i2c.scan():
            report.fail('BH1750', 'no ACK at 0x23 - check wiring / ADDR->3V3')
            return

        # Power on, then start continuous high-resolution measurement
        try:
            i2c.writeto(BH1750_ADDR, bytes([BH1750_POWER_ON]))
            time.sleep_ms(10)
        except Exception:
            pass
        i2c.writeto(BH1750_ADDR, bytes([BH1750_CONT_HIRES]))
        time.sleep_ms(180)                      # max conversion time

        data = i2c.readfrom(BH1750_ADDR, 2)
        raw = (data[0] << 8) | data[1]
        lux = raw / BH1750_LUX_DIV
        print('  Raw counts      : {0}'.format(raw))
        print('  Illuminance     : {0:.1f} lux'.format(lux))

        if 0.0 <= lux < 100000.0:
            report.ok('BH1750', '{0:.1f} lux'.format(lux))
        else:
            report.warn('BH1750', 'reading out of range: {0:.1f} lux'.format(lux))
    except Exception as e:
        _trace(e)
        report.fail('BH1750', repr(e))


# ---------------------------------------------------------------------------
# 5. NTC THERMISTOR  (ADC P14)
# ---------------------------------------------------------------------------

def test_ntc_temperature():
    _section('5. NTC THERMISTOR  (ADC P14)')
    try:
        adc = ADC()
        chan = adc.channel(pin=PIN_NTC_ADC, attn=ADC.ATTN_11DB)
        raw = chan.value()
        print('  Raw ADC         : {0}'.format(raw))

        # Open/short sentinel per firmware spec
        if raw <= NTC_RAW_MIN or raw >= NTC_RAW_MAX:
            report.fail('NTC thermistor',
                        'open/short sentinel (raw={0}) - check divider'.format(raw))
            return

        # Divider math (proven convention): 3V3 -> 10k -> P14 -> 10k NTC -> GND
        voltage = raw / ADC_FULL_SCALE * NTC_VREF
        r_ntc = NTC_R_SERIES * voltage / (NTC_VREF - voltage)
        temp_k = 1.0 / ((1.0 / (NTC_T_NOMINAL + 273.15))
                        + (math.log(r_ntc / NTC_R_NOMINAL) / NTC_B_COEFF))
        temp_c = temp_k - 273.15
        print('  Pin voltage     : {0:.3f} V'.format(voltage))
        print('  NTC resistance  : {0:.0f} ohm'.format(r_ntc))
        print('  Temperature     : {0:.1f} C'.format(temp_c))

        if 15.0 <= temp_c <= 40.0:
            report.ok('NTC thermistor', '{0:.1f} C'.format(temp_c))
        elif -10.0 < temp_c < 60.0:
            report.warn('NTC thermistor',
                        '{0:.1f} C (outside 15-40 skin band, plausible ambient)'.format(temp_c))
        else:
            report.warn('NTC thermistor',
                        'implausible temperature {0:.1f} C'.format(temp_c))
    except Exception as e:
        _trace(e)
        report.fail('NTC thermistor', repr(e))


# ---------------------------------------------------------------------------
# 6. BATTERY MONITOR  (ADC P15)
# ---------------------------------------------------------------------------

def test_battery():
    _section('6. BATTERY MONITOR  (ADC P15)')
    try:
        adc = ADC()
        chan = adc.channel(pin=PIN_BATT_ADC, attn=ADC.ATTN_11DB)
        raw = chan.value()
        v_pin = raw / ADC_FULL_SCALE * BATT_VREF
        v_bat = v_pin * BATT_DIVIDER
        pct = (v_bat - BATT_EMPTY_V) / (BATT_FULL_V - BATT_EMPTY_V) * 100.0
        if pct < 0.0:
            pct = 0.0
        elif pct > 100.0:
            pct = 100.0
        print('  Raw ADC         : {0}'.format(raw))
        print('  Pin voltage     : {0:.3f} V  (divider /2)'.format(v_pin))
        print('  Battery voltage : {0:.2f} V'.format(v_bat))
        print('  Estimated charge: {0:.0f} %'.format(pct))

        if BATT_OK_LOW <= v_bat <= BATT_OK_HIGH:
            report.ok('Battery monitor', '{0:.2f} V ({1:.0f}%)'.format(v_bat, pct))
        else:
            report.warn('Battery monitor',
                        '{0:.2f} V outside {1}-{2} V (USB only / no cell?)'.format(
                            v_bat, BATT_OK_LOW, BATT_OK_HIGH))
    except Exception as e:
        _trace(e)
        report.fail('Battery monitor', repr(e))


# ---------------------------------------------------------------------------
# 7. GPS  (UART1 RX = P19, 9600 8N1, receive only)
# ---------------------------------------------------------------------------

def _parse_nmea(line, state):
    """Update state dict from one NMEA sentence. Never raises."""
    try:
        body = line.split('*')[0]
        parts = body.split(',')
        head = parts[0]
        if head.endswith('GGA'):
            # parts[6]=fix quality (0=none), parts[7]=sat count, parts[9]=alt
            if len(parts) > 6 and parts[6] not in ('', '0'):
                state['fix'] = True
            if len(parts) > 7 and parts[7] != '':
                try:
                    state['sats'] = int(parts[7])
                except Exception:
                    pass
        elif head.endswith('RMC'):
            # parts[2] = A (valid) / V (void)
            if len(parts) > 2 and parts[2] == 'A':
                state['fix'] = True
    except Exception:
        pass


def test_gps(read_seconds=6):
    _section('7. GPS  (UART1 RX=P19, 9600 8N1, receive-only)')
    try:
        # pins=(TX, RX): TX=None because the GPS RX line is intentionally open.
        gps = UART(GPS_UART_ID, baudrate=GPS_BAUD, pins=(None, PIN_GPS_RX))
        print('  Listening for NMEA for up to {0} s ...'.format(read_seconds))

        deadline = time.ticks_ms() + read_seconds * 1000
        count = 0
        sample = []
        state = {'fix': False, 'sats': None}

        while time.ticks_diff(deadline, time.ticks_ms()) > 0:
            try:
                if gps.any():
                    raw = gps.readline()
                    if raw:
                        try:
                            line = raw.decode('utf-8').strip()
                        except Exception:
                            line = ''
                        if line.startswith('$'):
                            count += 1
                            if len(sample) < 6:
                                sample.append(line)
                            _parse_nmea(line, state)
                else:
                    time.sleep_ms(50)
            except Exception:
                # A stray decode/parse error must not stop the listen loop.
                pass

        print('  NMEA sentences  : {0} received'.format(count))
        for s in sample:
            print('    {0}'.format(s))

        if count == 0:
            report.fail('GPS UART communication',
                        'no NMEA received - check P19 wiring / 3V3 power')
            return

        report.ok('GPS UART communication',
                  '{0} NMEA sentences received'.format(count))

        if state['fix']:
            extra = '' if state['sats'] is None else ', {0} sats'.format(state['sats'])
            report.ok('GPS satellite fix', 'valid fix{0}'.format(extra))
        else:
            extra = '' if state['sats'] is None else ' ({0} sats visible)'.format(state['sats'])
            report.warn('GPS satellite fix',
                        'no fix - normal indoors{0}'.format(extra))
    except Exception as e:
        _trace(e)
        report.fail('GPS UART communication', repr(e))


# ---------------------------------------------------------------------------
# 8. LoRa RADIO  (built-in SX1276 - init / verify only, NO transmit)
# ---------------------------------------------------------------------------

def test_lora():
    _section('8. LoRa RADIO  (built-in - init only, NO TX)')
    try:
        from network import LoRa
        # Verified link config. Raw LORA mode (point-to-point), not LoRaWAN.
        lora = LoRa(mode=LoRa.LORA,
                    region=LoRa.AU915,
                    frequency=LORA_FREQ_HZ,
                    bandwidth=LoRa.BW_125KHZ,
                    sf=LORA_SF,
                    coding_rate=LoRa.CODING_4_5,
                    preamble=LORA_PREAMBLE)

        # Read settings back to prove the radio configured.
        for label, fn in (('Frequency  ', 'frequency'),
                          ('Spreading f', 'sf'),
                          ('Bandwidth  ', 'bandwidth'),
                          ('Coding rate', 'coding_rate'),
                          ('Preamble   ', 'preamble')):
            try:
                print('  {0} : {1}'.format(label, getattr(lora, fn)()))
            except Exception:
                pass

        mac = None
        try:
            mac = lora.mac()
            print('  LoRa MAC    : {0}'.format(_hexstr(mac)))
        except Exception:
            pass

        # NOTE: deliberately NOT opening a socket and NOT calling send().
        if mac and len(mac) >= 6:
            report.ok('LoRa init',
                      'radio configured @915 MHz SF{0}, MAC {1}'.format(
                          LORA_SF, _hexstr(mac)))
        else:
            report.ok('LoRa init', 'radio object created (MAC unavailable)')
    except Exception as e:
        _trace(e)
        report.fail('LoRa init', repr(e))


# ---------------------------------------------------------------------------
# 9. LEDs  (Green P5, Yellow P6, Red P7) - visual check
# ---------------------------------------------------------------------------

def test_leds():
    _section('9. LEDs  (Green=P2, Yellow=P3, Red=P4) - WATCH THE LEDs')
    try:
        g = Pin(PIN_LED_GREEN,  mode=Pin.OUT)
        y = Pin(PIN_LED_YELLOW, mode=Pin.OUT)
        r = Pin(PIN_LED_RED,    mode=Pin.OUT)
        g(0); y(0); r(0)

        # 1) each LED individually
        for name, pin in (('GREEN', g), ('YELLOW', y), ('RED', r)):
            print('  {0} on...'.format(name))
            pin(1)
            time.sleep_ms(600)
            pin(0)
            time.sleep_ms(150)

        # 2) the level-3 SOS pattern: yellow + red flash together, green OFF
        print('  Level-3 SOS pattern: YELLOW + RED rapid flash (green stays OFF)')
        g(0)
        for _ in range(8):
            y(1); r(1)
            time.sleep_ms(120)
            y(0); r(0)
            time.sleep_ms(120)

        # 3) settle in the "all normal" state: green steady ON
        g(1)
        print('  Settled to NORMAL state: GREEN steady ON (green never flashes)')
        report.ok('LED drive sequence',
                  'all three driven + SOS pattern; confirm visually')
    except Exception as e:
        _trace(e)
        report.fail('LED drive sequence', repr(e))


# ---------------------------------------------------------------------------
# 10. BUZZER  (P12) - audible check
# ---------------------------------------------------------------------------

def test_buzzer():
    _section('10. BUZZER  (P21) - LISTEN FOR BEEPS')
    try:
        buz = Pin(PIN_BUZZER, mode=Pin.OUT)
        buz(0)
        print('  Sounding 3 short tones ...')
        tone_ok = True
        for _ in range(3):
            try:
                _tone(buz, 2000, 150)           # 2 kHz square wave, 150 ms
            except Exception:
                tone_ok = False
                buz(1); time.sleep_ms(150); buz(0)   # fallback: static drive
            time.sleep_ms(200)
        buz(0)
        if tone_ok:
            report.ok('Buzzer drive', '2 kHz tone pattern sent; confirm audibly')
        else:
            report.warn('Buzzer drive',
                        'sleep_us unavailable - used static drive; confirm audibly')
    except Exception as e:
        _trace(e)
        report.fail('Buzzer drive', repr(e))


# ---------------------------------------------------------------------------
# 11. BUTTON  (P11, PULL_UP, active LOW) - interactive
# ---------------------------------------------------------------------------

def test_button(timeout_s=10):
    _section('11. BUTTON  (P22, PULL_UP, active LOW) - PRESS WHEN PROMPTED')
    try:
        btn = Pin(PIN_BUTTON, mode=Pin.IN, pull=Pin.PULL_UP)
        idle = btn()
        print('  Idle level      : {0}  (expect 1 = HIGH with PULL_UP)'.format(idle))
        if idle != 1:
            report.warn('Button idle level',
                        'idle reads {0}, expected 1 (stuck / miswired?)'.format(idle))

        print('  >>> PRESS THE DISMISS BUTTON within {0} s <<<'.format(timeout_s))
        deadline = time.ticks_ms() + timeout_s * 1000
        detected = False
        while time.ticks_diff(deadline, time.ticks_ms()) > 0:
            if btn() == 0:
                time.sleep_ms(50)               # 50 ms debounce
                if btn() == 0:
                    detected = True
                    break
            time.sleep_ms(20)

        if detected:
            print('  Press detected!')
            # wait for release so it doesn't bleed into anything after
            rel = time.ticks_ms() + 2000
            while btn() == 0 and time.ticks_diff(rel, time.ticks_ms()) > 0:
                time.sleep_ms(20)
            report.ok('Button press', 'P11 went LOW on press')
        else:
            report.warn('Button press',
                        'no press within {0} s (skipped or not wired)'.format(timeout_s))
    except Exception as e:
        _trace(e)
        report.fail('Button press', repr(e))


# ---------------------------------------------------------------------------
# SUMMARY + RUNNER
# ---------------------------------------------------------------------------

def _summary():
    p, w, f, total = report.counts()
    print('')
    print('=' * 64)
    print('  FINAL SUMMARY REPORT')
    print('=' * 64)
    print('  Total tests : {0}'.format(total))
    print('  Passed      : {0}'.format(p))
    print('  Warnings    : {0}'.format(w))
    print('  Failed      : {0}'.format(f))

    if w or f:
        print('  ' + ('-' * 60))
        print('  Items needing attention:')
        for status, label, detail in report.rows:
            if status in (WARNING, FAIL):
                line = '    [{0}] {1}'.format(status, label)
                if detail:
                    line += ' :: ' + detail
                print(line)

    print('=' * 64)
    if f == 0 and w == 0:
        print('  RESULT: ALL CLEAR - full hardware stack is responding.')
    elif f == 0:
        print('  RESULT: OK WITH WARNINGS - review the items above.')
    else:
        print('  RESULT: FAILURES PRESENT - fix [FAIL] items before final firmware.')
    print('=' * 64)


def run():
    """Run every component test in order and print the summary."""
    global report, _i2c
    report = Report()
    _i2c = None

    print('')
    print('#' * 64)
    print('#  SkiSafe Wearable - Full Hardware Component Test')
    print('#  LoPy4 standalone build - bring-up validation (no app logic)')
    print('#' * 64)

    # Order: info -> passive sensors -> radios -> interactive (LED/buzzer/button).
    tests = (
        test_startup,
        test_i2c_bus,
        test_mpu6050,
        test_bh1750,
        test_ntc_temperature,
        test_battery,
        test_gps,
        test_lora,
        test_leds,
        test_buzzer,
        test_button,
    )

    for fn in tests:
        # Each test already traps its own exceptions; this is a last-resort
        # guard so nothing whatsoever can abort the overall run.
        try:
            fn()
        except Exception as e:
            _trace(e)
            try:
                report.fail(fn.__name__, 'uncaught: ' + repr(e))
            except Exception:
                pass

    _summary()


if __name__ == '__main__':
    run()
