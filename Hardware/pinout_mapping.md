# SkiSafe — Hardware Pinout Reference
**Board:** Pycom LoPy4 in Pycom Makr expansion board  
**Runtime:** Pycom MicroPython 1.20.2.r6  

---

## ⚡ Critical Power Rule

> **The 5V rail (PowerBoost 1000C output) connects ONLY to Makr VIN.**  
> Every sensor, module, LED, and buzzer runs from Makr **3V3** only.  
> Connecting any LoPy4 GPIO or sensor directly to 5V will destroy it.  
> The NEO-6M GPS was destroyed once by 5V exposure — do not repeat.

---

## LoPy4 Pin Assignment — Wearable Node

| LoPy4 Pin | Direction | Connected To | Signal | Notes |
|-----------|-----------|--------------|--------|-------|
| **P8**  | Input  | Tactile button → GND | Alert dismiss button | `PULL_UP`, active LOW. Press = 0. |
| **P9**  | Output | Piezo buzzer | Alert buzzer | Active HIGH. Non-blocking pattern in firmware. |
| **P10** | Output | Green LED → 220Ω → GND | Status LED (green) | Alert level 0 = normal |
| **P11** | Output | Yellow LED → 220Ω → GND | Status LED (yellow) | Alert level 1 = cold/battery warning |
| **P12** | Output | Red LED → 220Ω → GND | Status LED (red) | Alert level 2 = fall detected |
| **P14** | ADC in | NTC thermistor (bottom of divider) | Skin temperature | `ATTN_11DB` (0–3.6V range). 10kΩ NTC from P14→GND, 10kΩ series from 3V3→P14. |
| **P15** | ADC in | Battery voltage divider midpoint | Battery % monitor | `ATTN_11DB`. Two 100kΩ resistors: LiPo+→100kΩ→P15→100kΩ→GND. V_bat/2 at pin. |
| **P19** | UART1 RX | NEO-6M GPS TX | GPS NMEA receive | **Data flows GPS→LoPy4 on this wire.** P19 = receive. |
| **P20** | UART1 TX | — | (unused) | GPS RX — leave disconnected. No level shifter needed. |
| **P21** | I2C SDA | MPU-6050 SDA + BH1750 SDA | I2C data | Shared bus. Both devices on same wires. |
| **P22** | I2C SCL | MPU-6050 SCL + BH1750 SCL | I2C clock | Shared bus. |

### Firmware declaration reference
```python
# I2C (shared bus — MPU-6050 @ 0x68, BH1750 @ 0x23)
i2c = I2C(0, pins=('P21', 'P22'))

# GPS UART — P20=TX(unused), P19=RX
gps_uart = UART(1, baudrate=9600, pins=('P20', 'P19'))

# ADC channels
adc      = ADC()
ntc_chan  = adc.channel(pin='P14', attn=ADC.ATTN_11DB)
batt_chan = adc.channel(pin='P15', attn=ADC.ATTN_11DB)

# GPIO
buzzer     = Pin('P9',  mode=Pin.OUT, value=0)
button     = Pin('P8',  mode=Pin.IN,  pull=Pin.PULL_UP)
led_red    = Pin('P12', mode=Pin.OUT, value=0)
led_yellow = Pin('P11', mode=Pin.OUT, value=0)
led_green  = Pin('P10', mode=Pin.OUT, value=0)
```

---

## I2C Bus — Shared Devices

| Device | I2C Address | Address Pin Config | Interface |
|--------|------------|-------------------|-----------|
| MPU-6050 (IMU) | `0x68` | AD0 pin → GND | SDA=P21, SCL=P22 |
| BH1750 (Light) | `0x23` | ADDR pin → GND or floating | SDA=P21, SCL=P22 |

```
3V3 ──┬── MPU-6050 VCC          3V3 ──┬── BH1750 VCC
      │                               │
P21 ──┼── MPU-6050 SDA          P21 ──┼── BH1750 SDA
P22 ──┼── MPU-6050 SCL          P22 ──┼── BH1750 SCL
      │                               │
GND ──┴── MPU-6050 GND          GND ──┴── BH1750 GND
GND ───── MPU-6050 AD0                     (ADDR floating = 0x23)
```

---

## GPS Module (GY-NEO6MV2 / u-blox NEO-6M)

| GPS Pin | Connects To | Notes |
|---------|------------|-------|
| VCC | Makr **3V3** | **3.3V ONLY.** 5V will destroy the module (confirmed). |
| GND | GND | |
| TX | LoPy4 **P19** | GPS sends NMEA sentences to LoPy4 UART1 RX |
| RX | **LEAVE OPEN** | No commands sent to GPS. No level shifter needed. |

**UART config:** 9600 baud, 8N1  
**Sentences parsed:** `$GPRMC` / `$GNRMC` (position, speed, validity), `$GPGGA` / `$GNGGA` (altitude, satellite count)  
**Fix indicator:** TIMEPULSE LED blinks at 1 Hz on the breakout board once a fix is acquired.

---

## NTC Thermistor Circuit (Skin Temperature — P14)

```
3V3 ──── 10kΩ (series) ──── P14 (ADC) ──── 10kΩ NTC ──── GND
```

- NTC on the **bottom** (GND side) of the divider
- Higher temperature → lower NTC resistance → lower voltage at P14 → lower ADC raw value
- `ATTN_11DB` sets full-scale to ~3.6V, raw 0–4095
- Steinhart-Hart Beta equation: B = 3950, T₀ = 25°C, R₀ = 10kΩ
- Valid range: raw 11–4084 (outside = open/short circuit sentinel = –99°C returned)

---

## Battery Monitor Circuit (P15)

```
LiPo+ (BAT) ──── 100kΩ ──── P15 (ADC) ──── 100kΩ ──── GND
```

- Equal-value divider: V_P15 = V_bat / 2
- LiPo range: 3.3V (empty) → 4.2V (full) → P15 sees 1.65V → 2.1V
- `ATTN_11DB` comfortably covers this range
- Battery % = `(V_bat - 3.3) / (4.2 - 3.3) * 100`, clamped 0–100

---

## LED Wiring

Each LED uses a 220Ω current-limiting series resistor.

```
P12 ──── 220Ω ──── Red LED (anode) ──── GND (cathode)
P11 ──── 220Ω ──── Yellow LED          GND
P10 ──── 220Ω ──── Green LED           GND
```

| Alert Level | LED State |
|------------|-----------|
| 0 — Normal | Green ON, Yellow OFF, Red OFF |
| 1 — Warning (cold/battery) | Yellow ON, others OFF |
| 2 — Fall detected | Red ON, others OFF |
| 3 — SOS / burial | All three ON |

---

## Buzzer

```
P9 ──── Buzzer+ (positive) ──── Buzzer- ──── GND
```

- Passive piezo, direct drive at 3.3V (no transistor needed at this current)
- Non-blocking pattern controlled by `update_buzzer()` in firmware

| Alert Level | Pattern |
|------------|---------|
| 0 | Silent |
| 1 | 100ms ON / 1900ms OFF |
| 2 | 300ms ON / 700ms OFF |
| 3 | 200ms ON / 200ms OFF |

---

## Button (Alert Dismiss)

```
P8 ──── one side of button
GND ─── other side of button
```

- Internal `PULL_UP` enabled in firmware
- Idle state: P8 = HIGH (1)
- Pressed state: P8 = LOW (0) — pulls pin to GND through switch
- Pressing mutes the buzzer and dismisses the current local alert

---

## Power Architecture

```
LiPo battery (3.7V nominal)
    │
    ▼
Adafruit PowerBoost 1000C
    │  USB input (charging via USB-C)
    │
    ├── 5V output ──── Makr VIN           ← ONLY connection for 5V
    └── BAT pin  ──── 100kΩ divider ──── P15 (battery monitor)

Makr VIN (5V) ──── Makr onboard 3V3 regulator
                        │
                        ├── LoPy4 3V3 supply
                        ├── MPU-6050 VCC
                        ├── BH1750 VCC
                        ├── NEO-6M GPS VCC
                        ├── 10kΩ NTC series resistor (top of divider)
                        └── 100kΩ battery divider (top resistor)
```

---

## Hub Node — LoPy4 in Pytrack

The hub LoPy4 runs `receiver_final.py` and connects via USB to the Raspberry Pi.

| Connection | Detail |
|-----------|--------|
| USB | Pytrack USB-C → Pi `/dev/ttyACM0` |
| Serial baud | 115200 |
| LoRa antenna | 915 MHz whip on **bottom-left U.FL** connector of LoPy4 |
| LoRa config | 915 MHz, AU915, SF7, BW_125KHz, CR 4/5, preamble 8 |

**Hub receiver does not use any GPIO** — it only receives LoRa and prints to serial.

---

## Component I2C Address Quick Reference

| Address | Device | Notes |
|---------|--------|-------|
| `0x68` | MPU-6050 IMU | AD0 → GND |
| `0x69` | MPU-6050 (alt) | AD0 → 3V3 — not used |
| `0x23` | BH1750 light sensor | ADDR floating or GND |
| `0x5C` | BH1750 (alt) | ADDR → 3V3 — not used |

Scan I2C bus with:
```python
from machine import I2C
i2c = I2C(0, pins=('P21', 'P22'))
print([hex(d) for d in i2c.scan()])
# Expected: ['0x23', '0x68']
```
