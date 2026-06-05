# SkiSafe

Real-time alpine safety monitoring system. A wearable sensor node worn by the skier transmits telemetry over LoRa to a base-station hub at the lodge, which stores data in SQLite and serves a live web dashboard.

---

## System Architecture

```
Wearable (LoPy4)
  sensors → wearable.py → LoRa TX
                                  ↓
                          Hub LoPy4 (receiver.py)
                          LoRa RX → USB serial
                                  ↓
                          Raspberry Pi
                          reader.py → SQLite DB
                          app.py    → Flask dashboard
```

### Wearable Node
Pycom LoPy4 standalone (no expansion board), battery-powered via Adafruit PowerBoost 1000C. Reads sensors every loop and transmits a JSON packet over LoRa every 5 seconds (2 seconds at alert level 2+).

**Sensors:**
- MPU-6050 IMU — fall detection and immobility monitoring
- BH1750 light sensor — burial detection (sudden darkness after fall)
- NTC thermistor — skin temperature / hypothermia risk
- u-blox NEO-6M GPS — coordinates, speed, altitude

**Outputs:**
- RGB LEDs (alert state indicator)
- Passive piezo buzzer (alert audio)
- Tactile button (local alert dismiss)

### Hub Node
Pycom LoPy4 in a Pytrack expansion board, connected via USB to the Raspberry Pi. Runs `receiver.py` — listens for LoRa packets and prints them to serial.

### Raspberry Pi
Runs two processes (managed via tmux):
- `reader.py` — reads serial from the hub LoPy4, parses JSON telemetry, writes to SQLite
- `app.py` — Flask web dashboard served locally (and optionally via ngrok tunnel)

---

## Alert Levels

| Level | Trigger | Response |
|-------|---------|----------|
| **L0** | Normal | Green LED steady, silent |
| **L1** | Low battery / cold skin / immobility 30s | Yellow LED, short pip every 2s |
| **L2** | Fall detected / immobility 60s | Red LED, urgent beep, dashboard warning |
| **L3** | L2 unacknowledged for 60s / burial / extreme cold | SOS flash + rapid beep, dashboard SOS, email alert |

Button press or hub ACK clears the buzzer and fall latch at any level.

---

## Repository Structure

```
├── Wearable/
│   ├── wearable.py                   # Production firmware (flash as main.py)
│   └── Code/Component-Testing/
│       ├── hardware_test.py          # Full bring-up validation (PASS/FAIL/WARN)
│       ├── bh1750_test.py
│       ├── mpu6050_test.py
│       ├── ntc_test.py
│       ├── gps_lora_test.py
│       ├── sender_lora_test.py
│       └── receiver_lora_test.py
│
├── Hub/
│   ├── receiver.py                   # Runs on hub LoPy4 — LoRa RX → serial
│   ├── reader.py                     # Runs on Pi — serial → SQLite
│   ├── app.py                        # Runs on Pi — Flask dashboard
│   ├── requirements.txt
│   ├── templates/
│   │   ├── dashboard.html
│   │   └── review.html
│   └── scripts/
│       ├── start_hub.sh
│       ├── stop_hub.sh
│       ├── status_hub.sh
│       └── update-skisafe.sh
│
├── Hardware/
│   ├── pinout_mapping.md             # Full pin reference + circuit details
│   └── breadboard_layout.md         # Breadboard wiring guide
│
└── CAD/
    ├── v1/                           # SolidWorks + STEP files, version 1
    └── v2/                           # SolidWorks + STEP files, version 2
```

---

## Flash Commands

**Wearable firmware:**
```
uvx mpremote connect COM10 cp Wearable/wearable.py :main.py + reset + repl
```

**Hub receiver (one-time, run from project root):**
```
uvx mpremote connect /dev/ttyACM0 cp Hub/receiver.py :main.py + reset
```

---

## Hub Setup (Raspberry Pi)

```bash
# Install dependencies
pip install -r Hub/requirements.txt

# Start both processes in tmux
tmux new-session -d -s reader 'python3 ~/skisafe/reader.py'
tmux new-session -d -s app    'python3 ~/skisafe/app.py'

# Or use the helper scripts
bash Hub/scripts/start_hub.sh
bash Hub/scripts/status_hub.sh
```

Dashboard runs at `http://<pi-ip>:5000`.

---

## Hardware Notes

- **Power:** PowerBoost 1000C 5V → LoPy4 VIN only. All sensors run from LoPy4 3V3. Never connect 5V to any sensor or GPIO pin.
- **LoRa conflict:** P5–P12 on the LoPy4 conflict with the internal LoRa SPI bus and must not be used as GPIO outputs. Use P2–P4 and P21–P23 instead.
- **I2C:** MPU-6050 @ 0x68 (AD0→GND), BH1750 @ 0x23 (ADDR→3V3 via 10kΩ). Shared bus on P9/P10.
- **GPS:** NEO-6M — 3.3V only. One module was destroyed by 5V exposure.
