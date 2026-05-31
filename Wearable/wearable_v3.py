from network import LoRa
import socket
import time
from machine import I2C, ADC, Pin, UART
import math
import ujson

lora = LoRa(mode=LoRa.LORA, region=LoRa.AU915, frequency=915000000, bandwidth=LoRa.BW_125KHZ, sf=7)
time.sleep(2)
s = socket.socket(socket.AF_LORA, socket.SOCK_RAW)
s.setblocking(True)
time.sleep(1)

i2c = I2C(0, pins=('P21', 'P22'))
i2c.writeto_mem(0x68, 0x6B, bytes([0]))
time.sleep(0.1)
i2c.writeto(0x23, bytes([0x10]))
time.sleep(0.2)

uart = UART(1, baudrate=9600, pins=('P19', 'P20'))

adc = ADC()
ntc = adc.channel(pin='P14', attn=ADC.ATTN_11DB)

buzzer = Pin('P9', mode=Pin.OUT)
red = Pin('P12', mode=Pin.OUT)
yellow = Pin('P11', mode=Pin.OUT)
green = Pin('P10', mode=Pin.OUT)
buzzer(0); red(0); yellow(0); green(0)

button = Pin('P8', mode=Pin.IN, pull=Pin.PULL_UP)

light_buf = []
temp_buf = []
lat_buf = []
lon_buf = []
alt_buf = []
speed_buf = []

def averaged(buf, new_val, size=5):
    if new_val is not None:
        buf.append(new_val)
        if len(buf) > size:
            buf.pop(0)
    if buf:
        return round(sum(buf) / len(buf), 2)
    return None

def read_mpu():
    try:
        data = i2c.readfrom_mem(0x68, 0x3B, 6)
        ax = (data[0] << 8 | data[1])
        ay = (data[2] << 8 | data[3])
        az = (data[4] << 8 | data[5])
        if ax > 32767: ax -= 65536
        if ay > 32767: ay -= 65536
        if az > 32767: az -= 65536
        return ax, ay, az
    except:
        return 0, 0, 0

def read_light():
    try:
        data = i2c.readfrom(0x23, 2)
        raw = round((data[0] << 8 | data[1]) / 1.2, 1)
        return averaged(light_buf, raw, 3)
    except:
        return 0

def read_skin_temp():
    try:
        raw = ntc.value()
        if raw == 0:
            return 0
        voltage = raw / 4095.0 * 3.3
        r = 10000 * voltage / (3.3 - voltage)
        temp_k = 1.0 / ((1.0 / 298.15) + (math.log(r / 10000) / 3950))
        return averaged(temp_buf, round(temp_k - 273.15, 1), 5)
    except:
        return 0

def read_gps():
    lat, lon, alt, speed = None, None, None, None
    deadline = time.time() + 1
    while time.time() < deadline:
        if uart.any():
            line = uart.readline()
            if line:
                try:
                    decoded = line.decode('utf-8').strip()
                    if decoded.startswith('$GNGGA') or decoded.startswith('$GPGGA'):
                        parts = decoded.split(',')
                        if len(parts) > 9 and parts[2] and parts[4]:
                            raw_lat = float(parts[2])
                            raw_lon = float(parts[4])
                            lat = round(int(raw_lat/100) + (raw_lat % 100)/60, 6)
                            lon = round(int(raw_lon/100) + (raw_lon % 100)/60, 6)
                            if parts[3] == 'S': lat = -lat
                            if parts[5] == 'W': lon = -lon
                            if parts[9]: alt = round(float(parts[9]), 1)
                    if decoded.startswith('$GNRMC') or decoded.startswith('$GPRMC'):
                        parts = decoded.split(',')
                        if len(parts) > 7 and parts[7]:
                            speed = round(float(parts[7]) * 1.852, 2)
                except:
                    pass
    return averaged(lat_buf, lat, 5), averaged(lon_buf, lon, 5), averaged(alt_buf, alt, 5), averaged(speed_buf, speed, 3)

def update_leds(skin_temp):
    if skin_temp < 10:
        red(1); yellow(0); green(0)
    elif skin_temp < 20:
        red(0); yellow(1); green(0)
    else:
        red(0); yellow(0); green(1)

print('Wearable v3 starting...')
count = 0

while True:
    ax, ay, az = read_mpu()
    light = read_light()
    skin_temp = read_skin_temp()
    lat, lon, alt, speed = read_gps()

    update_leds(skin_temp)

    packet = {
        'id': 'skier_01',
        'count': count,
        'skin_temp': skin_temp,
        'light': light,
        'ax': ax,
        'ay': ay,
        'az': az,
        'lat': lat,
        'lon': lon,
        'alt': alt,
        'speed': speed,
        'alert': 0
    }

    msg = ujson.dumps(packet)
    try:
        s.send(msg.encode())
        print('Sent: ' + msg)
    except Exception as e:
        print('Send error: ' + str(e))

    count += 1
    time.sleep(2)