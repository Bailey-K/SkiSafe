from machine import I2C
import time
from machine import WDT

wdt = WDT(timeout=10000)  # 10 second watchdog timeout

i2c = I2C(0, pins=('P4', 'P8'))

print("Scanning I2C bus...")
devices = i2c.scan()
print("Devices found:", [hex(d) for d in devices])

i2c.writeto_mem(0x68, 0x6B, bytes([0]))
time.sleep(0.1)

print("Reading accelerometer...")
while True:
    wdt.feed()
    data = i2c.readfrom_mem(0x68, 0x3B, 6)
    ax = (data[0] << 8 | data[1])
    ay = (data[2] << 8 | data[3])
    az = (data[4] << 8 | data[5])
    if ax > 32767: ax -= 65536
    if ay > 32767: ay -= 65536
    if az > 32767: az -= 65536
    print("AX:" + str(ax) + " AY:" + str(ay) + " AZ:" + str(az))
    time.sleep(0.5)