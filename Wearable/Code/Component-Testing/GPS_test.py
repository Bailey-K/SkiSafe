from machine import UART
import time

uart = UART(1, baudrate=9600, pins=('P4', 'P3'))

print("Reading GPS...")
print("Note: takes 30-60 seconds for first fix outdoors")

while True:
    if uart.any():
        line = uart.readline()
        if line:
            try:
                decoded = line.decode('utf-8').strip()
                if decoded.startswith('$'):
                    print(decoded)
            except:
                pass
    time.sleep(0.1)