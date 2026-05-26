from machine import I2C, Pin, ADC
import time
import math

print("=== SkiSafe Hardware Test ===")
time.sleep(1)

# I2C - MPU6050 and BH1750
print("\n-- I2C Scan --")
i2c = I2C(0, pins=('P21', 'P22'))
devices = i2c.scan()
print("I2C devices: " + str([hex(d) for d in devices]))
if 0x68 in devices:
    print("MPU-6050: OK")
else:
    print("MPU-6050: NOT FOUND - check SDA/SCL wiring")
if 0x23 in devices:
    print("BH1750: OK")
else:
    print("BH1750: NOT FOUND - check SDA/SCL wiring")

time.sleep(1)

# Wake MPU
i2c.writeto_mem(0x68, 0x6B, bytes([0]))
time.sleep(0.2)

# BH1750 continuous mode
i2c.writeto(0x23, bytes([0x10]))
time.sleep(0.5)

# Read MPU
print("\n-- MPU-6050 Accelerometer --")
for i in range(5):
    data = i2c.readfrom_mem(0x68, 0x3B, 6)
    ax = (data[0] << 8 | data[1])
    ay = (data[2] << 8 | data[3])
    az = (data[4] << 8 | data[5])
    if ax > 32767: ax -= 65536
    if ay > 32767: ay -= 65536
    if az > 32767: az -= 65536
    print("AX:" + str(ax) + " AY:" + str(ay) + " AZ:" + str(az))
    time.sleep(0.5)

# Read BH1750
print("\n-- BH1750 Light Sensor --")
for i in range(5):
    data = i2c.readfrom(0x23, 2)
    lux = round((data[0] << 8 | data[1]) / 1.2, 1)
    print("Light: " + str(lux) + " lux")
    time.sleep(0.5)

# NTC thermistor
print("\n-- NTC Thermistor --")
adc = ADC()
ntc = adc.channel(pin='P14', attn=ADC.ATTN_11DB)
for i in range(5):
    raw = ntc.value()
    if raw > 0:
        voltage = raw / 4095.0 * 3.3
        r = 10000 * voltage / (3.3 - voltage)
        temp_k = 1.0 / ((1.0 / 298.15) + (math.log(r / 10000) / 3950))
        print("Skin temp: " + str(round(temp_k - 273.15, 1)) + "C  Raw: " + str(raw))
    else:
        print("NTC: check wiring")
    time.sleep(0.5)

# LED test - one at a time, 2 seconds each
print("\n-- LED Test --")
red = Pin('P12', mode=Pin.OUT)
yellow = Pin('P11', mode=Pin.OUT)
green = Pin('P10', mode=Pin.OUT)
red(0); yellow(0); green(0)

print("RED on for 2 seconds...")
red(1)
time.sleep(2)
red(0)
time.sleep(0.5)

print("YELLOW on for 2 seconds...")
yellow(1)
time.sleep(2)
yellow(0)
time.sleep(0.5)

print("GREEN on for 2 seconds...")
green(1)
time.sleep(2)
green(0)
time.sleep(0.5)

print("ALL on for 2 seconds...")
red(1); yellow(1); green(1)
time.sleep(2)
red(0); yellow(0); green(0)
print("LEDs done")

# Buzzer test - multiple beeps
print("\n-- Buzzer Test --")
buzzer = Pin('P9', mode=Pin.OUT)
print("3 beeps...")
for i in range(3):
    buzzer(1)
    time.sleep(0.5)
    buzzer(0)
    time.sleep(0.5)
print("Buzzer done")

# Button test
print("\n-- Button Test --")
button = Pin('P8', mode=Pin.IN, pull=Pin.PULL_UP)
print("Press the button within 10 seconds...")
start = time.time()
pressed = False
while time.time() - start < 10:
    if button() == 0:
        print("Button: PRESSED - OK!")
        pressed = True
        time.sleep(0.3)
        break
    time.sleep(0.1)
if not pressed:
    print("Button: not pressed - check wiring")

print("\n=== Test Complete ===")