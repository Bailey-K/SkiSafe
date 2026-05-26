from machine import ADC
import time
import math

adc = ADC()
pin = adc.channel(pin='P14', attn=ADC.ATTN_11DB)

R_SERIES = 10000
R_NOMINAL = 10000
T_NOMINAL = 25
B_COEFF = 3950

print("Reading NTC thermistor...")
while True:
    raw = pin.value()
    if raw == 0:
        print("Error: check wiring")
    else:
        voltage = raw / 4095.0 * 3.3
        r_thermistor = R_SERIES * voltage / (3.3 - voltage)
        temp_k = 1.0 / ((1.0 / (T_NOMINAL + 273.15)) + (math.log(r_thermistor / R_NOMINAL) / B_COEFF))
        temp_c = temp_k - 273.15
        print("Skin temp: " + str(round(temp_c, 1)) + "C  Raw: " + str(raw))
    time.sleep(1)