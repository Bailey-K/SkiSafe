from network import LoRa
import socket
import time

# Initialise LoRa
lora = LoRa(mode=LoRa.LORA, region=LoRa.AU915, frequency=915000000, bandwidth=LoRa.BW_125KHZ, sf=7)
time.sleep(2)

# Open socket
s = socket.socket(socket.AF_LORA, socket.SOCK_RAW)
s.setblocking(True)
time.sleep(2)

print('Sender ready...')
count = 0

while True:
    try:
        msg = bytes('Hello #{}'.format(count), 'utf-8')
        s.send(msg)
        print('Sent: Hello #{}'.format(count))
        count += 1
    except Exception as e:
        print('Error: {}'.format(e))
    time.sleep(2)