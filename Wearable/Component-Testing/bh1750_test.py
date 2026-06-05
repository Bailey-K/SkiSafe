from machine import I2C
import time

i2c = I2C(0, pins=('P4', 'P8'))

print("Scanning I2C bus...")
devices = i2c.scan()
print("Devices found:", [hex(d) for d in devices])

BH1750_ADDR = 0x23
i2c.writeto(BH1750_ADDR, bytes([0x10]))
time.sleep(0.2)

print("Reading light level...")
while True:
    data = i2c.readfrom(BH1750_ADDR, 2)
    lux = (data[0] << 8 | data[1]) / 1.2
    print("Light: " + str(lux) + " lux")
    time.sleep(1)