from machine import UART
import time

uart = UART(1, baudrate=9600, pins=('P19', 'P20'))

def parse_gps(decoded):
    lat, lon, alt, speed = None, None, None, None
    try:
        if decoded.startswith('$GNGGA') or decoded.startswith('$GPGGA'):
            parts = decoded.split(',')
            print("GPGGA parts: " + str(parts))
            if len(parts) > 9 and parts[2] and parts[4]:
                raw_lat = float(parts[2])
                raw_lon = float(parts[4])
                lat = round(int(raw_lat/100) + (raw_lat % 100)/60, 6)
                lon = round(int(raw_lon/100) + (raw_lon % 100)/60, 6)
                if parts[3] == 'S': lat = -lat
                if parts[5] == 'W': lon = -lon
                if parts[9]: alt = round(float(parts[9]), 1)
                print("LAT: " + str(lat) + "  LON: " + str(lon) + "  ALT: " + str(alt))

        if decoded.startswith('$GNRMC') or decoded.startswith('$GPRMC'):
            parts = decoded.split(',')
            print("GPRMC parts: " + str(parts))
            if len(parts) > 7 and parts[7]:
                speed = round(float(parts[7]) * 1.852, 2)
                print("SPEED: " + str(speed) + " km/h")
    except Exception as e:
        print("Parse error: " + str(e))
    return lat, lon, alt, speed

print("GPS test 2 starting - raw NMEA + parsed output...")
print("Place near window for fix...")

while True:
    if uart.any():
        line = uart.readline()
        if line:
            try:
                decoded = line.decode('utf-8').strip()
                if decoded.startswith('$'):
                    print("RAW: " + decoded)
                    parse_gps(decoded)
                    print("---")
            except:
                pass
    time.sleep(0.1)