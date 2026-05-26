### 1. The Wearable Edge Node (On the Skier)

Worn directly on the body via a secure chest harness, this node acts as the real-time physical sensor hub. It coordinates a variety of components to monitor distinct alpine risks:

* **MPU-6050 IMU:** Processes acceleration data using low-latency hardware interrupts to instantly flag sudden crashes or prolonged immobility.
* **BH1750 Light Sensor:** Monitors ambient light levels via I2C to immediately detect avalanche burial if the skier is plunged into sudden darkness following a fall.
* **NTC Thermistor:** Tracks skier skin temperature via an analog voltage divider to proactively catch hypothermia exposure risks.
* **u-blox NEO-6M GPS Module:** Continuously parses satellite data via UART to extract precise coordinates, speed, and altitude metrics.

The wearable processes these inputs locally and bundles them into unique skier-identified packets, transmitting them over point-to-point **LoRa**. LoRa is crucial here: it bypasses the need for unreliable mountain Wi-Fi or cellular grids, punching through kilometers of open terrain directly back to the lodge receiver.

### 2. The Base Hub & Dashboard (At the Lodge)

Back at the base station, a **Raspberry Pi 4** acts as the high-compute brain of the network, running a multi-threaded Python application. 

* **Thread 1:** Continuously ingests incoming raw LoRa telemetry packets.
* **Thread 2:** Executes the automated alert logic engine and updates the local SQLite session database.
* **Thread 3:** Serves a live **Flask web dashboard** pushed to the public web via an **ngrok** secure tunnel.

If you are out on the slopes, friends, family, or emergency contacts back at the lodge (or anywhere in the world) can open the dashboard to view real-time vitals, track live map coordinates, and review post-session performance timelines.

---

## 🚨 The 3-Tier Escalation Path

To prevent false alarms from flooding emergency networks while ensuring critical situations are handled immediately, SkiSafe implements a strict 3-tier alert system:

| Alert Severity                 | Trigger Condition                                                                                                                     | System Response                                                                                                                                                                             |
|:------------------------------ |:------------------------------------------------------------------------------------------------------------------------------------- |:------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Level 1: Local Alert**       | Single sensor breach (e.g., skin temperature dipping below safe threshold).                                                           | Wearable onboard piezo buzzer sounds. The skier can ciquickly press a hardware-interrupt button on their harness to dismiss it locally without involving the hub.                           |
| **Level 2: Dashboard Warning** | Compound sensor event (e.g., the IMU flags a massive impact and detects zero movement afterward).                                     | Prominent warning flashes on the lodge dashboard and the wearable buzzes aggressively. A 60-second countdown timer begins. If not dismissed, it escalates.                                  |
| **Level 3: SOS Mode**          | Level 2 timer expires unacknowledged, OR catastrophic event detected immediately (e.g., impact + total light loss indicating burial). | The Raspberry Pi bypasses local clearing and uses **Gmail SMTP** routing to instantly blast automated emergency emails containing your exact last-known GPS coordinates to rescue contacts. |

---

## 🛡️ Built for Architectural Fault-Tolerance

Because alpine conditions are inherently unstable, the system is engineered to degrade gracefully under failure:

> ### 🔌 Graceful Degradation Specs
> 
> * **Hub Offline:** If the base station loses internet or goes down, the wearable operates entirely independently, protecting the skier locally with hardware audio alerts.
> * **Wearable Offline:** If the wearable node is physically damaged in a crash, the hub preserves your last known GPS coordinate track and environmental history on a local SQLite database, ensuring search-and-rescue teams have an immediate starting point. 

Neither device's failure completely cripples the safety and tracing capabilities of the other.