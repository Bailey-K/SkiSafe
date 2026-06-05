from network import LoRa
import socket
import time

# Initialise LoRa
lora = LoRa(mode=LoRa.LORA, region=LoRa.AU915, frequency=915000000, bandwidth=LoRa.BW_125KHZ, sf=7)
time.sleep(2)

# Open socket
s = socket.socket(socket.AF_LORA, socket.SOCK_RAW)
s.setblocking(False)
time.sleep(2)

print('Receiver ready...')

while True:
    try:
        data = s.recv(64)
        if data:
            print('Received: {}'.format(data.decode('utf-8')))
            print('RSSI: {}'.format(lora.stats().rssi))
            print('SNR:  {}'.format(lora.stats().snr))
            print('---')
    except Exception as e:
        print('Error: {}'.format(e))
    time.sleep(0.1)