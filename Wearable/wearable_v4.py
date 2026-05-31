from network import LoRa
import socket
import time
from machine import I2C, ADC, Pin, UART
import math
import ujson

# LoRa setup
lora = LoRa(mode=LoRa.LORA, region=LoRa.AU915, frequency=915000000, bandwidth=LoRa.BW_125KHZ, sf=7)
time.sleep(2)
s = socket.socket(socket.AF_LORA, socket.SOCK_RAW)
s.setblocking(True)
time.sleep(1)

# I2C
i2c = I2C(0, pins=('P21', 'P22'))
i2c.writeto_mem(0x68, 0x6B, bytes([0]))
time.sleep(0.1)
i2c.writeto(0x23, bytes([0x10]))
time.sleep(0.2)

# GPS — confirmed working pins
uart = UART(1, baudrate=9600, pins=('P19', 'P20'))

# NTC
adc = ADC()
ntc = adc.channel(pin='P14', attn=ADC.ATTN_11DB)

# Outputs
buzzer = Pin('P9', mode=Pin.OUT)
red = Pin('P12', mode=Pin.OUT)
yellow = Pin('P11', mode=Pin.OUT)
green = Pin('P10', mode=Pin.OUT)
buzzer(0); red(0); yellow(0); green(0)

# Button
button = Pin('P8', mode=Pin.IN, pull=Pin.PULL_UP)

# Averaging buffers
light_buf = []
temp_buf = []
lat_buf = []
lon_buf = []
alt_buf = []
speed_buf = []

# GPS state — persists between loops
gps_lat = None
gps_lon = None
gps_alt = None
gps_speed = None

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

def update_gps():
    global gps_lat, gps_lon, gps_alt, gps_speed
    # Read all available NMEA sentences without blocking
    while uart.any():
        line = uart.readline()
        if not line:
            continue
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
                    gps_lat = averaged(lat_buf, lat, 5)
                    gps_lon = averaged(lon_buf, lon, 5)
                    if parts[9]:
                        gps_alt = averaged(alt_buf, round(float(parts[9]), 1), 5)
            elif decoded.startswith('$GNRMC') or decoded.startswith('$GPRMC'):
                parts = decoded.split(',')
                if len(parts) > 7 and parts[7]:
                    spd = round(float(parts[7]) * 1.852, 2)
                    gps_speed = averaged(speed_buf, spd, 3)
        except:
            pass

def update_leds(skin_temp):
    if skin_temp < 10:
        red(1); yellow(0); green(0)
    elif skin_temp < 20:
        red(0); yellow(1); green(0)
    else:
        red(0); yellow(0); green(1)

print('Wearable v4 starting...')
count = 0

while True:
    # Drain GPS buffer every loop
    update_gps()

    ax, ay, az = read_mpu()
    light = read_light()
    skin_temp = read_skin_temp()

    update_leds(skin_temp)

    packet = {
        'id': 'skier_01',
        'count': count,
        'skin_temp': skin_temp,
        'light': light,
        'ax': ax,
        'ay': ay,
        'az': az,
        'lat': gps_lat,
        'lon': gps_lon,
        'alt': gps_alt,
        'speed': gps_speed,
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