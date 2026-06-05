# SkiSafe — receiver.py
# Hub LoPy4 (in Pytrack board) — LoRa receiver / serial bridge.
# Receives packets from the wearable and prints them to serial (USB)
# so reader.py on the Pi can parse them.
#
# Serial output format (reader.py depends on this exactly):
#   Received: {"i":"SK01","c":1,...}
#   RSSI: -72
#   SNR: 8.5
#
# Flash from Pi:
#   uvx mpremote connect /dev/ttyACM0 cp receiver.py :main.py + reset
#
# CRITICAL: recv buffer must be >= max packet size.
# GPS packets from wearable.py are ~95 bytes.
# recv(64) splits them across two reads → parse errors on Pi.
# recv(256) handles any realistic LoRa payload size.

from network import LoRa
import socket
import utime

LORA_FREQUENCY = 915000000
LORA_SF        = 7

print('SkiSafe receiver starting...')

lora = LoRa(
    mode        = LoRa.LORA,
    region      = LoRa.AU915,
    frequency   = LORA_FREQUENCY,
    bandwidth   = LoRa.BW_125KHZ,
    sf          = LORA_SF,
    preamble    = 8,
    coding_rate = LoRa.CODING_4_5,
    power_mode  = LoRa.ALWAYS_ON
)

lora_sock = socket.socket(socket.AF_LORA, socket.SOCK_RAW)
lora_sock.setblocking(False)

print('Listening on ' + str(LORA_FREQUENCY // 1000000) + ' MHz SF' + str(LORA_SF))
print('Waiting for packets...')

while True:
    # recv(256) — must be large enough for the full packet in one read.
    # Original recv(64) caused GPS packets (~95B) to split across two reads,
    # producing invalid JSON on the Pi side.
    data = lora_sock.recv(256)

    if data:
        try:
            print('Received: ' + data.decode('utf-8'))
        except Exception:
            print('Received: ' + str(data))

        stats = lora.stats()
        print('RSSI: ' + str(stats.rssi))
        print('SNR: '  + str(stats.snr))

    utime.sleep_ms(20)
