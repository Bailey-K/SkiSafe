# Running average buffers
light_buf = []
temp_buf = []
lat_buf = []
lon_buf = []

def averaged(buf, new_val, size=5):
    if new_val is not None:
        buf.append(new_val)
        if len(buf) > size:
            buf.pop(0)
    if buf:
        return round(sum(buf) / len(buf), 2)
    return None

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
    # Average GPS coordinates
    avg_lat = averaged(lat_buf, lat, 5)
    avg_lon = averaged(lon_buf, lon, 5)
    return avg_lat, avg_lon, alt, speed