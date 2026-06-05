# SkiSafe — Hardware Pinout & Wiring Reference
**Board:** Pycom LoPy4 (standalone, no expansion board)  
**Runtime:** Pycom MicroPython 1.20.2.r6  

---

## ⚠ Critical Power Rules

> **The 5V rail (PowerBoost 1000C output) connects ONLY to LoPy4 VIN.**  
> Every sensor, module, LED, and buzzer runs from LoPy4 **3V3** only.  
> Connecting any LoPy4 GPIO or sensor directly to 5V WILL destroy it.  
> The NEO-6M GPS was destroyed once by 5V exposure — do not repeat.

> **Never disconnect or reconnect sensors while powered.**  
> The LoPy4 ADC inputs are not 5V tolerant and have limited ESD protection.

---

## LoPy4 Pin Assignment — Complete

| LoPy4 Pin | Direction | Connected To | Signal | Notes |
|-----------|-----------|--------------|--------|-------|
| **P2**  | Output | Green LED → 220 Ω → GND | Status LED green | Alert level 0 = normal |
| **P3**  | Output | Yellow LED → 220 Ω → GND | Status LED yellow | Alert level 1 = warning |
| **P4**  | Output | Red LED → 220 Ω → GND | Status LED red | Alert level 2 = fall / SOS |
| **P9**  | I2C SDA | MPU-6050 SDA + BH1750 SDA | I2C data | Hardware SDA. Shared bus — both devices on same wires. |
| **P10** | I2C SCL | MPU-6050 SCL + BH1750 SCL | I2C clock | Hardware SCL. Shared bus. |
| **P21** | Output | Piezo buzzer (+) → GND | Alert buzzer | Active HIGH. Non-blocking pattern in firmware. |
| **P22** | Input  | Tactile button → GND | Alert dismiss | `PULL_UP`, active LOW. Idle = HIGH. Press = LOW. |
| **P14** | ADC in | NTC thermistor (GND-side of divider) | Skin temperature | `ATTN_11DB` (0–3.6V). 10 kΩ NTC from P14→GND, 10 kΩ series from 3V3→P14. |
| **P15** | ADC in | Battery divider midpoint | Battery % monitor | `ATTN_11DB`. 100 kΩ from LiPo+→P15, 100 kΩ from P15→GND. V_pin = V_bat/2. |
| **P19** | UART1 RX | NEO-6M GPS TX | GPS NMEA receive | Data flows GPS→LoPy4. |
| **P0**  | UART0 RX0 | USB-UART adapter TXD | Serial console in | REPL input / mpremote code upload, 115200 baud. |
| **P1**  | UART0 TX0 | USB-UART adapter RXD | Serial console out | REPL + print()/debug output, 115200 baud. |

> ⚠ **P13–P18 are input-only** (ESP32 GPIO34–39 — no internal pullup/pulldown, cannot drive outputs). P14 and P15 are intentionally used as ADC inputs only.
> ⚠ **P5–P12 conflict with the LoPy4 internal LoRa SPI bus** — do not use as GPIO outputs. Initialising any of these as Pin.OUT silently breaks LoRa TX (confirmed by hardware testing June 2026). Use P2–P4, P21–P23 for GPIO outputs instead.

### Firmware declaration reference
```python
# I2C shared bus — hardware pins (MPU-6050 @ 0x68, BH1750 @ 0x23)
i2c = I2C(0, pins=('P9', 'P10'))

# GPS UART1 — P19=RX only
gps_uart = UART(1, baudrate=9600, pins=(None, 'P19'))

# Debug / REPL console — default UART0 on P0 (RX0) / P1 (TX0), 115200 baud.
# Nothing to initialise: print() output and the REPL/mpremote use UART0 automatically.

# ADC channels
adc       = ADC()
ntc_chan  = adc.channel(pin='P14', attn=ADC.ATTN_11DB)
batt_chan = adc.channel(pin='P15', attn=ADC.ATTN_11DB)

# Outputs
buzzer     = Pin('P21', mode=Pin.OUT, value=0)
led_green  = Pin('P2',  mode=Pin.OUT, value=0)
led_yellow = Pin('P3',  mode=Pin.OUT, value=0)
led_red    = Pin('P4',  mode=Pin.OUT, value=0)

# Input
button = Pin('P22', mode=Pin.IN, pull=Pin.PULL_UP)   # active LOW
```

---

## I2C Bus — Shared Devices

| Device | I2C Address | ADDR Pin | Pull-up Resistors |
|--------|-------------|----------|-------------------|
| MPU-6050 (IMU) | `0x68` | AD0 → GND | Breakout has on-board 4.7 kΩ pull-ups on SDA/SCL |
| BH1750 (Light) | `0x46` | ADDR → 3V3 | Breakout has on-board pull-ups |

```
3V3 ──┬── MPU-6050 VCC              3V3 ──┬── BH1750 VCC
      │                                   │
P9  ──┼── MPU-6050 SDA              P9  ──┼── BH1750 SDA
P10 ──┼── MPU-6050 SCL              P10 ──┼── BH1750 SCL
      │                                   │
GND ──┴── MPU-6050 GND              GND ──┴── BH1750 GND
GND ───── MPU-6050 AD0              3V3 ───── BH1750 ADDR
```

> Both sensors share the same SDA and SCL lines. The MPU-6050 SDA/SCL wires connect into the same nodes as the BH1750 SDA/SCL — the breadboard/perfboard junction carries signal from both sensors to the LoPy4 on P9/P10.

Verify I2C bus with:
```python
from machine import I2C
i2c = I2C(0, pins=('P9', 'P10'))
print([hex(d) for d in i2c.scan()])
# Expected: ['0x46', '0x68']
```

---

## GPS Module (GY-NEO6MV2 / u-blox NEO-6M)

| GPS Pin | Connects To | Notes |
|---------|-------------|-------|
| VCC | LoPy4 **3V3** | **3.3V ONLY — 5V will destroy the module (confirmed once).** |
| GND | GND | Common ground |
| TX | LoPy4 **P19** | GPS sends NMEA sentences → LoPy4 UART1 RX |
| RX | **LEAVE OPEN** | No commands sent to GPS. |

```
NEO-6M module
┌──────────┐
│ VCC ─────┼──── 3V3
│ GND ─────┼──── GND
│ TX  ─────┼──── P19  (LoPy4 UART1 RX)
│ RX  ─────┼──── (nothing)
└──────────┘
```

**UART config:** 9600 baud, 8N1  
**Sentences parsed:** `$GPRMC` / `$GNRMC` (position, speed, validity), `$GPGGA` / `$GNGGA` (altitude, satellite count)  
**Fix indicator:** TIMEPULSE LED on the breakout board blinks at 1 Hz once a fix is acquired  
**Cold start time:** 1–15 minutes outdoors; indoor fix with ceramic patch antenna is unreliable

---

## NTC Thermistor Circuit (Skin Temperature — P14)

```
3V3 ──── 10 kΩ (series, fixed) ──── P14 (ADC) ──── 10 kΩ NTC ──── GND
```

- NTC is on the **GND side** (bottom) of the voltage divider  
- Higher temperature → lower NTC resistance → lower voltage at P14 → lower ADC raw value  
- `ATTN_11DB` sets full-scale ≈ 3.6V, raw range 0–4095  
- Steinhart-Hart Beta: **B = 3950**, T₀ = 25°C, R₀ = 10 kΩ  
- Sentinel: raw ≤ 10 or ≥ 4085 → open/short detected → firmware returns −99.0°C  
- Valid skin range: approximately 15°C – 40°C in field use  
- NTC body sits against the inner wrist strap for skin contact

---

## Battery Monitor Circuit (P15)

```
LiPo+ (BAT pin) ──── 100 kΩ ──── P15 (ADC) ──── 100 kΩ ──── GND
```

- Equal-value divider: V_P15 = V_bat / 2  
- LiPo range: 3.3V (empty) → 4.2V (full) → P15 sees 1.65V → 2.10V  
- `ATTN_11DB` comfortably covers this range with no risk of exceeding 3.6V  
- Formula: `batt_pct = (V_bat − 3.3) / (4.2 − 3.3) × 100`, clamped 0–100  
- BAT pin is the output of the PowerBoost 1000C (same node as LiPo positive)

---

## LED Wiring

Each LED uses a **220 Ω** current-limiting series resistor.  
At 3.3V with a typical LED Vf ≈ 2.0V: I = (3.3 − 2.0) / 220 ≈ **6 mA** — safe for LoPy4 GPIO.

```
P2 ──── Green LED anode  ──── cathode ──── 220 Ω ──── GND
P3 ──── Yellow LED anode ──── cathode ──── 220 Ω ──── GND
P4 ──── Red LED anode    ──── cathode ──── 220 Ω ──── GND
```

| Alert Level | Meaning | LED State |
|-------------|---------|-----------|
| 0 — Normal | All good | Green steady ON, Yellow OFF, Red OFF |
| 1 — Warning | Low battery / cold / immobility warning | Yellow steady ON, Green OFF, Red OFF |
| 2 — Alert | Fall detected / prolonged immobility | Red steady ON, Green OFF, Yellow OFF |
| 3 — SOS | Burial / extreme cold / fall + unconscious | Yellow rapid flash + Red rapid flash, Green OFF |

---

## Buzzer

```
P21 ──── Buzzer positive ──── Buzzer negative ──── GND
```

- Passive piezo, direct GPIO drive at 3.3V (no transistor needed at this current draw)  
- Non-blocking pattern controlled by `update_buzzer()` — uses timestamps, not `sleep()`

| Alert Level | Pattern | Cadence |
|-------------|---------|---------|
| 0 — Normal | Silent | — |
| 1 — Warning | Short pip | 100 ms ON / 1900 ms OFF |
| 2 — Fall | Urgent beep | 300 ms ON / 700 ms OFF |
| 3 — SOS | Rapid pulse | 200 ms ON / 200 ms OFF |

**Mute behaviour:** Physical button press OR hub LoRa ACK clears both the buzzer mute flag and the fall detection latch.

---

## Button (Alert Dismiss)

```
P22 ──── one terminal of button
GND ─── other terminal of button
```

- Internal `PULL_UP` enabled — idle state P11 = HIGH (1)  
- Press pulls P11 to GND → LOW (0)  
- Firmware uses 50 ms software debounce  
- Action: mutes buzzer, clears fall detection latch

---

## Power Architecture

```
LiPo cell (3.7V nominal, 1200–2000 mAh)
    │
    ▼
Adafruit PowerBoost 1000C
    │  ← USB-C input for charging (charges while running)
    │
    ├── 5V output ──────────────── LoPy4 VIN            ← ONLY 5V connection
    └── BAT pin ─── 100 kΩ ─── P15 (battery monitor)
                         └─── 100 kΩ ─── GND

LoPy4 VIN (5V) ──── LoPy4 onboard 3.3V regulator
                        │
                        ├── LoPy4 3V3 supply
                        ├── MPU-6050 VCC
                        ├── BH1750 VCC
                        ├── NEO-6M GPS VCC  ← 3.3V only
                        ├── 10 kΩ NTC series resistor (top of divider)
                        └── 100 kΩ battery divider (top resistor)
```

---

## Alert Escalation Logic (Firmware)

| Condition | Alert Level | Hub Action |
|-----------|-------------|------------|
| Battery < 20% | L1 | Local warning only (no hub action) |
| Skin temp < 15°C | L1 | Local warning only |
| Immobile ≥ 30 s | L1 | Local warning only |
| Immobile ≥ 60 s | L2 | Hub shows ALERT, enables ACK button |
| Fall detected (latch 5 min) | L2 | Hub shows ALERT |
| Skin temp < 10°C | L3 | Hub sends SOS email |
| Burial (dark + immobile ≥ 60 s) | L3 | Hub sends SOS email |
| Fall + immobile ≥ 120 s | L3 | Hub sends SOS email |

**Fall latch:** Once a fall spike is detected, the alert holds at minimum L2 for 5 minutes even if the skier stands up.  
Only a physical button press or a hub LoRa ACK clears the latch early.

---

## LoRa Link (Wearable → Hub)

| Parameter | Value |
|-----------|-------|
| Frequency | 915 MHz |
| Region plan | AU915 |
| Spreading factor | SF7 |
| Bandwidth | 125 kHz |
| Coding rate | 4/5 |
| Preamble | 8 symbols |
| TX power | Default (Pycom LoPy4 max ≈ 20 dBm) |
| Packet size | ~85–100 bytes (JSON) |
| Normal TX cadence | 5 seconds |
| Alert (L2+) TX cadence | 2 seconds |

**Packet format (short keys — matches reader.py KEY_MAP):**
```
{"i":"SK01","c":12,"st":28.3,"lx":1102.4,"la":-37.1522,"lo":146.4418,"al":1707.0,"sp":42.1,"a":0}
```

---

## Hub Node — LoPy4 in Pytrack

| Connection | Detail |
|-----------|--------|
| USB | Pytrack USB-C → Raspberry Pi `/dev/ttyACM0` |
| Serial baud | 115200 |
| LoRa antenna | 915 MHz whip on **bottom-left U.FL** connector of LoPy4 |
| LoRa config | Identical to wearable (915 MHz AU915 SF7 BW_125KHz CR 4/5 preamble 8) |

The hub LoPy4 runs `receiver.py` — receives LoRa packets and prints them to serial in the format `reader.py` expects:
```
Received: {"i":"SK01","c":12,...}
RSSI: -72
SNR: 8.5
```

---

## Component I2C Address Reference

| Address | Device | Config |
|---------|--------|--------|
| `0x68` | MPU-6050 IMU | AD0 → GND (default) |
| `0x69` | MPU-6050 (alt) | AD0 → 3V3 — not used |
| `0x46` | BH1750 light sensor | ADDR → 3V3 |
| `0x23` | BH1750 (alt) | ADDR → GND or floating — not used |

---

## Bill of Materials — Prototype

| Qty | Component | Value / Part | Notes |
|-----|-----------|--------------|-------|
| 1 | Pycom LoPy4 | — | Standalone — no expansion board |
| 1 | MPU-6050 breakout | GY-521 | I2C, AD0 → GND |
| 1 | BH1750 breakout | GY-302 | I2C, ADDR → 3V3 |
| 1 | GPS module | GY-NEO6MV2 (u-blox NEO-6M) | **3.3V VCC only** |
| 1 | NTC thermistor | 10 kΩ, B=3950 | Skin contact sensor |
| 1 | Fixed resistor | 10 kΩ | NTC series / divider top |
| 2 | Fixed resistor | 100 kΩ | Battery voltage divider |
| 3 | Fixed resistor | 220 Ω | LED current limiting |
| 1 | Green LED | 3mm or 5mm | Status level 0 |
| 1 | Yellow LED | 3mm or 5mm | Status level 1 |
| 1 | Red LED | 3mm or 5mm | Status level 2 |
| 1 | Piezo buzzer | Passive, 3V–5V | P21 direct drive |
| 1 | Tactile button | Momentary NO | Dismiss / mute |
| 1 | Adafruit PowerBoost 1000C | — | USB-C charge + 5V boost |
| 1 | LiPo battery | 3.7V, 1200–2000 mAh | Connected to PowerBoost |
| 1 | LoRa antenna | 915 MHz whip | On LoPy4 U.FL |
| 1 | USB-to-UART adapter | CP2102 or similar | UART0 console / REPL / flashing (P0/P1) |
