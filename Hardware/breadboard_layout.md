# SkiSafe — Breadboard-Specific Layout & Wiring Guide

## SMALL BOARD — 30 Columns

### Component Placement Overview

| Component                       | Header row(s)                                | Columns  | Notes                                                                                                              |
| ------------------------------- | -------------------------------------------- | -------- | ------------------------------------------------------------------------------------------------------------------ |
| LoPy4                           | **c** (top header) and **h** (bottom header) | 1 – 14   | Module body spans rows c → h across the gap                                                                        |
| 100 kΩ resistor #1 (BAT top)    | **b** (top half)                             | 15 & 18  | Legs at b15 and b18, two-hole gap (cols 16–17 empty). b15 = BAT+ input. b18 = P15 midpoint. No polarity.           |
| 100 kΩ resistor #2 (BAT bottom) | **b** (top half)                             | 18 & 21  | Legs at b18 and b21, two-hole gap (cols 19–20 empty). b18 = P15 midpoint (shared with R1). b21 = GND. No polarity. |
| Adafruit PowerBoost 1000C       | **a** (pins in top half)                     | 23 – 30  | USB charging connector end at col 30; 5V out at col 23                                                             |
| USB-to-UART adapter             | **f** (pins in bottom half)                  | ~25 – 30 | TXD at **f28** (use h28), GND at **f29** (use h29). RXD is adjacent — check silkscreen.                            |

> **Wiring access rule — important:**  
> The LoPy4 module body physically covers rows **d, e** (top half) and **f, g** (bottom half) in cols 1–14.  
> Those rows are inaccessible for wiring under the module.  
> • To connect to the **top header** (row c): place jumper wires in rows **a or b**, same column.  
> • To connect to the **bottom header** (row h): place jumper wires in rows **i or j**, same column.  
> • PowerBoost pins are in row a — use rows **b, c, d, or e** (same column) for wire connections.  
> • USB-UART pins are in row f — use rows **g or h (cols 15–30 only)** for wire connections.

> **Power rule reminder:** PowerBoost 5V → LoPy4 VIN only.  
> LoPy4 3V3 output → large board (+) rail → all sensors. Never connect 5V to sensors.

---

### LoPy4 — Pin Reference Table

The LoPy4 sits directly in the breadboard. Header pins: **top header in row c, bottom header in row h**.

| Col | Row c — Top Header              | Row h — Bottom Header    | Active Signal / Notes                                        |
| --- | ------------------------------- | ------------------------ | ------------------------------------------------------------ |
| 1   | P13 ⚠ input-only                | P12                      | (spare)                                                      |
| 2   | **P14** ⚠ input-only (NTC ADC)  | P11                      | NTC ADC in ← large board / (spare)                           |
| 3   | **P15** ⚠ input-only (batt ADC) | **P10** (I2C SCL)        | Batt ADC in ← large board / SCL → large board (hardware SCL) |
| 4   | P16 ⚠ input-only                | **P9** (I2C SDA)         | SDA → large board (hardware SDA)                             |
| 5   | P17 ⚠ input-only                | P8                       | (spare)                                                      |
| 6   | P18 ⚠ input-only                | P7                       | (spare)                                                      |
| 7   | **P19** (GPS UART1 RX)          | P6                       | GPS NMEA in ← large board / (spare)                          |
| 8   | P20                             | P5                       | (spare)                                                      |
| 9   | **P21** (buzzer out)            | **P4** (red LED out)     | Buzzer → large board / Red LED → large board                 |
| 10  | **P22** (button in)             | **P3** (yellow LED out)  | Button ← large board / Yellow LED → large board              |
| 11  | P23                             | **P2** (green LED out)   | (spare) / Green LED → large board                            |
| 12  | **3V3** (output)                | **P1** (UART0 TX0)      | 3V3 → T+ rail / P1 → USB-UART RXD                            |
| 13  | GND                             | **P0** (UART0 RX0)      | Ground → T− rail / P0 ← USB-UART TXD                         |
| 14  | **VIN**                         | **RST**                 | 5V in from PowerBoost / reset                                |

> ⚠ **P13–P18 are input-only** (ESP32 GPIO34–39 — no internal pullup/pulldown, cannot be used as outputs). P14 and P15 are used as ADC inputs only — this is correct and intentional.
> **P9 = hardware SDA, P10 = hardware SCL.** I2C is initialised on these pins in firmware. P0/P1 = UART0 serial console (REPL + flashing). P5–P8, P11, P12 are spare (avoid using as GPIO outputs — these pins conflict with the LoPy4 internal LoRa SPI bus). P23 is spare.

> Confirm all pin positions against your board's silkscreen before wiring — pin order can vary by board revision.

**Wire access summary for LoPy4 pins:**

| Header        | Pin row | Connect jumpers in                |
| ------------- | ------- | --------------------------------- |
| Top header    | c       | Rows **a** or **b** (same column) |
| Bottom header | h       | Rows **i** or **j** (same column) |

---

### PowerBoost 1000C — Pin Reference Table

Positioned in the **top half** (rows a–e), **cols 23–30**. Pins insert into row **a**. USB-C charging connector end sits at col 30.

| Col | Row a        | Signal                             | From          | To                                                        |
| --- | ------------ | ---------------------------------- | ------------- | --------------------------------------------------------- |
| 23  | **5V** (out) | Boosted 5V to LoPy4 VIN            | **b23**       | **b14** (LoPy4 VIN, top half col 14)                      |
| 24  | GND          | PowerBoost ground                  | **b24**       | T− rail                                                   |
| 25  | EN           | Enable — leave open                | —             | —                                                         |
| 26  | GND          | Ground (BAT side)                  | **b26**       | T− rail                                                   |
| 27  | LBO          | Low battery indicator — leave open | —             | —                                                         |
| 28  | VS           | Battery voltage sense — leave open | —             | —                                                         |
| 29  | **BAT**      | LiPo+ → battery divider            | **b29**       | **a15** (R1 top leg — use a15 since b15 has the resistor) |
| 30  | USB          | Charging input (USB-C)             | plug cable in | —                                                         |

> The LiPo cell connects via the JST-PH connector on the PowerBoost board — the BAT pin at a29 is the same electrical node as solder pad on the board edge, accessible at b29.

---

### USB-to-UART Adapter — Pin Reference Table

Positioned in the **bottom half** (rows f–j). Pins insert into row **f**. Use rows **g, h, i, or j** in the same column as connection points.

| Col   | Row f          | Signal                                | From    | To                             | Purpose                                      |
| ----- | -------------- | ------------------------------------- | ------- | ------------------------------ | -------------------------------------------- |
| 27    | **RXD**        | Adapter receive (data **from** LoPy4) | **h27** | **i12** (LoPy4 P1 — UART0 TX0) | See serial print output in terminal          |
| 28    | **TXD**        | Adapter transmit (data **to** LoPy4)  | **h28** | **i13** (LoPy4 P0 — UART0 RX0) | Send REPL commands to LoPy4                  |
| 29    | **GND**        | Ground                                | **h29** | T− rail                        | Common ground                                |
| other | 3V3 / 5V / CTS | —                                     | —       | **Leave unconnected**          | LoPy4 is powered by PowerBoost independently |

> **RXD ← P1 (UART0 TX0):** This wire lets you see everything the LoPy4 prints — sensor readings, errors, REPL/debug output. Open any serial terminal (e.g. PuTTY, Arduino Serial Monitor) at **115200 baud** on your USB-UART's COM port.
> 
> **TXD → P0 (UART0 RX0):** Full bidirectional REPL — type commands and see responses. UART0 *is* the LoPy4's REPL/programming console, so this is also the port mpremote uses to upload code. No GPS conflict: GPS uses UART1 (P19) and the serial console uses UART0 (P0/P1). Both work simultaneously, permanently, no swapping needed.
> 
> **Flashing (uploading code):** Works over this same adapter. Because UART0 is the REPL console, mpremote uploads through P0/P1 — no separate USB needed. Example (run from the project root): `uvx mpremote connect COM10 cp "Wearable/Code/Component-Testing/Full-Hardware_Test.py" :main.py + reset + repl`.
> 
> **Wire routing:** f27 and f29 are occupied by the adapter pins — use h27, h28, h29 (same bottom-half column, same node) as your jumper wire insertion points.  
> P0 and P1 are on the **bottom header, cols 13 and 12** — use i13 (P0) and i12 (P1) as insertion points.  
> In firmware: nothing to initialise — print() output and the REPL/mpremote both use the default UART0 console automatically.

---

### Battery Voltage Divider — on the Small Board

> Two 100 kΩ resistors at cols 15–21 (row b). R1 legs at b15 and b18; R2 legs at b18 and b21. b15 is occupied by the resistor leg — wire to **a15** (same node). Midpoint at b18 → P15 (wire S5). R2 far end at b21 is occupied — wire to **c21** (same node) → GND (wire S6). See S1–S11 in the Complete Wire Map.

---

## LARGE BOARD — 63 Columns (split into two halves for readability)

### Component Placement Overview

| Component                         | Type                               | Insert row                           | Columns           | Orientation / notes                                                                                                                                                                         |
| --------------------------------- | ---------------------------------- | ------------------------------------ | ----------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| MPU-6050 (GY-521)                 | 8-pin single-row breakout          | **c** (top half)                     | 2 – 9             | Col 2=INT, 3=ADD, 4=XCL, 5=XDA, 6=SDA, 7=SCL, 8=GND, 9=VCC. ADD (col 3) wired to GND for address 0x68. Wires in row e.                                                                      |
| BH1750 (GY-302)                   | 5-pin single-row breakout          | **c** (top half)                     | 12 – 16           | Col 12=VCC, 13=SCL, 14=SDA, 15=ADD, 16=GND. ADD (col 15) connected to B+ (3V3) rail via a 10 kΩ current-limiting resistor to bypass an internal board short. Sets hardware address to 0x23. |
| NEO-6M GPS module                 | 4-pin header (large PCB overhangs) | **a** (top half)                     | 21 – 24           | Col 21=VCC, 22=RX (leave open), 23=TX, 24=GND. Antenna faces back. Wires in row e.                                                                                                          |
| 10 kΩ fixed resistor (NTC series) | Through-hole resistor              | **a** (top half)                     | 31 & 33           | Legs in a31 and a33. Bridges col 32. No polarity. The junction at col 31 is the ADC node shared with the NTC.                                                                               |
| 10 kΩ NTC thermistor              | Through-hole thermistor            | **c** (top half)                     | 31 – 32           | Legs in c31 and c32. Col 31 = ADC node (electrically joined to a31 — same column, same half). Col 32 leg wired to GND. Body extended on a short lead for wrist contact.                     |
| Green LED                         | 5 mm LED (3 holes wide)            | **h** (bottom half)                  | 48, 49 (body), 50 | **Anode (long leg) at h50**, cathode (short leg) at h48. Body over h49 (empty). Signal wire h50 ← small board i8 (P5). Resistor j48 → B− rail.                                              |
| Yellow LED                        | 5 mm LED (3 holes wide)            | **h** (bottom half)                  | 44, 45 (body), 46 | **Anode (long leg) at h46**, cathode (short leg) at h44. Body over h45 (empty). Signal wire h46 ← small board i7 (P6). Resistor j44 → B− rail.                                              |
| Red LED                           | 5 mm LED (3 holes wide)            | **h** (bottom half)                  | 40, 41 (body), 42 | **Anode (long leg) at h42**, cathode (short leg) at h40. Body over h41 (empty). Signal wire h42 ← small board i6 (P7). Resistor j40 → B− rail.                                              |
| 220 Ω resistor — green LED        | Through-hole resistor              | **j** (bottom half)                  | 48                | j48 → B− rail. No polarity.                                                                                                                                                                 |
| 220 Ω resistor — yellow LED       | Through-hole resistor              | **j** (bottom half)                  | 44                | j44 → B− rail. No polarity.                                                                                                                                                                 |
| 220 Ω resistor — red LED          | Through-hole resistor              | **j** (bottom half)                  | 40                | j40 → B− rail. No polarity.                                                                                                                                                                 |
| Piezo buzzer                      | Passive piezo disc                 | **a** and **c** (top half, diagonal) | 55 (+), 57 (−)    | Positive (+) leg at **a55**, negative (−) leg at **c57**. Diagonal placement due to body shape. Both legs in top half — no gap crossing needed.                                             |
| Tactile button                    | Momentary switch                   | **i** (bottom half)                  | 59 & 61           | Legs at **i59** (GND) and **i61** (signal). Wires connect at j59 (GND) and j61 (signal). Pressing bridges cols 59 and 61.                                                                   |

> **Polarity reminders:**  
> — LEDs: long leg = anode (+), short leg = cathode (−). Inserting backwards = no light, no damage.  
> — Buzzer: marked (+) = positive. Inserting backwards = no sound.  
> — Resistors and NTC: no polarity — insert either way.  
> — GPS module: **3.3V VCC only** — double check before powering on.

---

### Component-by-Component Wiring

### MPU-6050 — Cols 2–9, Row c

The MPU-6050 has **8 pins in a single row**. Insert into row **c**. Wires connect in row **e** (same top-half node).

| From             | To                                             | Signal                    |
| ---------------- | ---------------------------------------------- | ------------------------- |
| 3V3 rail (B+)    | **e9** (MPU VCC)                               | 3.3V power                |
| **e8** (MPU GND) | GND rail (B−)                                  | Ground                    |
| **e7** (MPU SCL) | **c13** (BH SCL — shared channel to LoPy4 P10) | I2C clock via daisy-chain |
| **e6** (MPU SDA) | **c14** (BH SDA — shared channel to LoPy4 P9)  | I2C data via daisy-chain  |
| c5 XDA           | —                                              | Not connected             |
| c4 XCL           | —                                              | Not connected             |
| **e3** (MPU ADD) | GND rail (B−)                                  | Set I2C address 0x68      |
| c2 INT           | —                                              | Not connected             |

---

### BH1750 — Cols 12–16, Row c

The BH1750 has **5 pins in a single row**. Insert into row **c**. Wires connect in row **e** (same top-half node).

| From                                 | To                            | Signal                                       |
| ------------------------------------ | ----------------------------- | -------------------------------------------- |
| 3V3 rail (B+)                        | **e12** (BH VCC)              | 3.3V power                                   |
| **e13** (BH SCL)                     | Small board **i3** (P10, SCL) | I2C clock                                    |
| **e14** (BH SDA)                     | Small board **i4** (P9, SDA)  | I2C data                                     |
| **3V3** rail (B+) via 10 kΩ Resistor | e15 (BH ADD)                  | Safely address pull-up (yields address 0x23) |
| **e16** (BH GND)                     | GND rail (B−)                 | Ground                                       |

> **I2C daisy-chain:** The inter-board wires from the LoPy4 (I3/I4) land at c14 (BH SDA) and c13 (BH SCL). Jumper wires L4/L5 connect those same columns at e6 (MPU SDA) and e7 (MPU SCL) — placing both sensors on the same I2C lines. The BH1750 output wires (e13→i3, e14→i4) carry the signal back to the LoPy4.
> The breakout boards include on-board pull-up resistors — do not add extra ones.

---

### NEO-6M GPS Module — Cols 21–24, Row a

Wires connect in row **e** (node in row a).

| From              | To                             | Signal                    |
| ----------------- | ------------------------------ | ------------------------- |
| 3V3 rail (B+)     | **e21** (GPS VCC)              | 3.3V power **(NEVER 5V)** |
| a22 GPS RX        | —                              | Leave unconnected         |
| **e23** (GPS TX)  | Small board **b7** (LoPy4 P19) | GPS NMEA data             |
| **e24** (GPS GND) | GND rail (B−)                  | Ground                    |

> **⚠ 3.3V only.** Double-check before powering on.

---

### NTC Thermistor Circuit — Cols 31–33

This is a voltage divider built from two components: a fixed 10 kΩ resistor and the NTC thermistor. The NTC is fragile — handle legs carefully and don't flex them repeatedly.

```
  Circuit:  3V3 → [10kΩ fixed] → P14 (ADC node) → [10kΩ NTC] → GND
```

**Physical layout:** The fixed resistor sits in row **a** (legs at a31 and a33, bridging col 32). The NTC sits in row **c** (legs at c31 and c32). Because rows a–e in the same column are all connected, **a31 and c31 are the same electrical node** — that junction is the P14 ADC midpoint. No bridge wire needed between them; the breadboard does it internally.

| From                                                   | To                             | Signal                       | Notes                            |
| ------------------------------------------------------ | ------------------------------ | ---------------------------- | -------------------------------- |
| 3V3 rail (B+)                                          | **b33** (resistor top leg)     | 3.3V supply into divider     | a33 = b33 (same top-half column) |
| **b31** (ADC node / resistor bottom leg = NTC top leg) | Small board **b2** (LoPy4 P14) | NTC ADC signal               | a31 = b31 = c31 — all same node  |
| **b32** (NTC bottom leg)                               | GND rail (B−)                  | Divider GND                  | c32 = b32 — same node            |
| Resistor legs                                          | a31 & a33                      | 10 kΩ fixed (bridges col 32) | —                                |
| Thermistor legs                                        | c31 & c32                      | 10 kΩ NTC                    | —                                |

---

### LED Bank — Cols 40–49

The 220 Ω resistor sits between the cathode and the B− GND rail 

#### Green LED (P2) — Cols 48, & 50

| From                    | To                  | Signal                               |
| ----------------------- | ------------------- | ------------------------------------ |
| Small board **i11** (P2) | Large board **h50** | P2 GPIO signal                      |
| **h50**                 | —                   | LED anode, long leg inserted here    |
| **h48**                 | —                   | LED cathode, short leg inserted here |
| **j48**                 | **B− rail**         | 220 Ω resistor (cathode → GND)       |

#### Yellow LED (P3) — Cols 44, & 46

| From                     | To                  | Signal                               |
| ------------------------ | ------------------- | ------------------------------------ |
| Small board **i10** (P3) | Large board **h46** | P3 GPIO signal                       |
| **h46**                  | —                   | LED anode, long leg inserted here    |
| **h44**                  | —                   | LED cathode, short leg inserted here |
| **j44**                  | **B− rail**         | 220 Ω resistor (cathode → GND)       |

#### Red LED (P4) — Cols 40, & 42

| From                    | To                  | Signal                               |
| ----------------------- | ------------------- | ------------------------------------ |
| Small board **i9** (P4) | Large board **h42** | P4 GPIO signal                       |
| **h42**                 | —                   | LED anode, long leg inserted here    |
| **h40**                 | —                   | LED cathode, short leg inserted here |
| **j40**                 | **B− rail**         | 220 Ω resistor (cathode → GND)       |

> **LED polarity:** Long leg = anode (+). Short leg = cathode (−).

---

### Piezo Buzzer — Col 55 (+), Col 57 (−), diagonal

Direct GPIO drive from P21 at 3.3V. Placed diagonally.

| From                             | To                               | Signal          |
| -------------------------------- | -------------------------------- | --------------- |
| Small board **b9** (LoPy4 P21)   | **b55** (= a55, buzzer positive) | P21 GPIO signal |
| **b57** (= c57, buzzer negative) | GND rail (B−)                    | Ground          |

---

### Dismiss Button — Cols 59 & 61

Tactile momentary switch, active LOW with PULL_UP. Entirely in the bottom half.

| From                            | To                          | Signal                           |
| ------------------------------- | --------------------------- | -------------------------------- |
| Small board **b10** (LoPy4 P22) | **j61** (button signal leg) | P22 GPIO signal                  |
| **j59** (button GND leg)        | B− rail                     | Ground (active-LOW when pressed) |

---

## Complete Wire Map

Every wire in the system listed with exact breadboard reference.

### Small Board — Internal Wires

| #   | From                     | To                                                                       | Signal                                  |
| --- | ------------------------ | ------------------------------------------------------------------------ | --------------------------------------- |
| S1  | **b23** (PowerBoost 5V)  | **b14** (LoPy4 VIN)                                                      | 5V power                                |
| S2  | **b24** (PowerBoost GND) | T− rail                                                                  | Ground                                  |
| S3  | **b26** (PowerBoost GND) | T− rail                                                                  | Ground                                  |
| S4  | **b29** (PowerBoost BAT) | **a15** (R1 top leg — b15 is occupied by the resistor, a15 is same node) | LiPo+ into bat divider                  |
| S5  | **a18** (R1/R2 midpoint) | **b3** (LoPy4 P15)                                                       | Battery ADC signal                      |
| S6  | **c21** (R2 bottom leg)  | T− rail                                                                  | Divider GND                             |
| S7  | **b12** (LoPy4 3V3)      | T+ rail                                                                  | 3.3V supply                             |
| S8  | **b13** (LoPy4 GND)      | T− rail                                                                  | Ground                                  |
| S9  | **h29** (USB-UART GND)   | T− rail                                                                  | Ground                                  |
| S10 | **h27** (USB-UART RXD)   | **i12** (LoPy4 P1, UART0 TX0)                                            | Serial + REPL output — LoPy4 → terminal |
| S11 | **h28** (USB-UART TXD)   | **i13** (LoPy4 P0, UART0 RX0)                                            | REPL / flash upload — terminal → LoPy4  |

### Inter-Board Wires (Small Board → Large Board)

| #   | From (small board)            | To (large board)                                        | Signal            |
| --- | ----------------------------- | ------------------------------------------------------- | ----------------- |
| I1  | T+ rail                       | B+ (3V3) rail                                           | 3.3V power        |
| I2  | T− rail                       | GND (B−) rail                                           | Ground            |
| I3  | **i4** (LoPy4 P9, SDA)        | **c14** (BH SDA), daisy-chained over to**e6** (MPU SDA) | I2C data          |
| I4  | **i3** (LoPy4 P10, SCL)       | **c13** (BH SCL), daisy-chained over to**e7** (MPU SCL) | I2C clock         |
| I5  | **b7** (LoPy4 P19, GPS RX)    | **e23** (GPS TX)                                        | GPS NMEA          |
| I6  | **b2** (LoPy4 P14, NTC ADC)   | **b31** (NTC ADC node)                                  | NTC temperature   |
| I7  | **i11** (LoPy4 P2, green LED)  | **h50** (green LED anode)                              | Green LED signal  |
| I8  | **i10** (LoPy4 P3, yellow LED) | **h46** (yellow LED anode)                             | Yellow LED signal |
| I9  | **i9** (LoPy4 P4, red LED)     | **h42** (red LED anode)                                | Red LED signal    |
| I10 | **b9** (LoPy4 P21, buzzer)     | **b55** (= a55, buzzer positive)                       | Buzzer drive      |
| I11 | **b10** (LoPy4 P22, button)    | **j61** (button leg 1)                                 | Button signal     |

### Large Board — Internal Wires

| #   | From                         | To                               | Signal                                      |
| --- | ---------------------------- | -------------------------------- | ------------------------------------------- |
| L1  | B+ (3V3) rail                | **e9** (MPU VCC)                 | 3.3V to MPU-6050                            |
| L2  | **e8** (MPU GND)             | B− rail                          | MPU-6050 ground                             |
| L3  | **e3** (MPU ADD)             | B− rail                          | MPU I2C address = 0x68                      |
| L4  | **e6** (MPU SDA)             | **c14** (BH SDA)                 | SDA daisy-chain between sensors             |
| L5  | **e7** (MPU SCL)             | **c13** (BH SCL)                 | SCL daisy-chain between sensors             |
| L6  | B+ (3V3) rail                | **e12** (BH VCC)                 | 3.3V to BH1750                              |
| L7  | **e15** (BH ADD)             | B+ (3V3) rail via 10k Ω Resistor | Safety bypass: locks BH1750 address to 0x23 |
| L8  | **e16** (BH GND)             | B− rail                          | BH1750 ground                               |
| L9  | B+ (3V3) rail                | **e21** (GPS VCC)                | 3.3V to GPS ⚠ NEVER 5V                      |
| L10 | **e24** (GPS GND)            | B− rail                          | GPS ground                                  |
| L11 | B+ (3V3) rail                | **b33** (NTC fixed R top)        | 3.3V into NTC divider                       |
| L12 | **b32** (NTC GND leg)        | B− rail                          | NTC divider ground                          |
| L13 | **j40** (red LED cathode)    | B− rail                          | Red LED GND return via 220 Ω                |
| L14 | **j44** (yellow LED cathode) | B− rail                          | Yellow LED GND return via 220 Ω             |
| L15 | **j48** (green LED cathode)  | B− rail                          | Green LED GND return via 220 Ω              |
| L16 | **b57** (buzzer negative)    | B− rail                          | Buzzer ground                               |
| L17 | **j59** (button GND leg)     | B− rail                          | Button ground (active-LOW)                  |

> **Totals: 11 small-board internal + 11 inter-board + 17 large-board internal = 39 wires.**
> L4 and L5 are the only inter-sensor jumpers on the large board (I2C daisy-chain).
> Battery divider is fully on the small board — no inter-board wires for P15 or BAT.

---

## Pre-Power Checklist

Before applying power for the first time:

- [ ] LoPy4 VIN connected to PowerBoost 5V — **not** to 3V3
- [ ] GPS VCC connected to 3V3 rail — **not** to 5V or LoPy4 VIN
- [ ] MPU-6050 AD0 connected to GND (not floating)
- [ ] NTC circuit: 3V3 → 10kΩ → P14 node → NTC → GND (NTC on bottom)
- [ ] Battery divider: BAT+ → 100kΩ → P15 node → 100kΩ → GND
- [ ] All three LED cathodes (short leg) to GND rail
- [ ] LED anodes (long leg) away from GND, toward resistors
- [ ] Buzzer polarity: (+) to P21 (b9), (−) to GND
- [ ] Button: P22 (b10) → j61 (signal leg); j59 → GND
- [ ] Large board B+ connected to small board B+ (3V3 inter-board)
- [ ] Large board B− connected to small board B− (GND inter-board)
- [ ] I2C: P9 (i4) → SDA daisy-chain (c14 ↔ e6); P10 (i3) → SCL daisy-chain (c13 ↔ e7)
- [ ] USB-UART on P0/P1 (UART0 console) — GPS on P19 (UART1) — no conflict
- [ ] BH1750 ADD connected to 3V3 rail via 10 kΩ resistor (Bypasses address pin ground short)
- [ ] I2C scan returns `[0x23, '0x68']` before flashing production firmware
