# SkiSafe — wearable_sim.py
# Simulated wearable for hub testing — NO sensors or electronics required.
# Runs on a bare LoPy4 (LoRa antenna must be connected, nothing else needed).
#
# Automatically cycles through all 4 alert scenarios so you can verify:
#   - Dashboard updates live
#   - Alert log populates
#   - Acknowledge button works
#   - SOS email fires after 60s unacknowledged L2
#
# Flash:
#   uvx mpremote connect COM12 cp wearable_sim.py :main.py + reset + repl
#
# PYCOM MICROPYTHON 1.20.2.r6 — no f-strings, use utime not time.

from network import LoRa
import socket
import utime
import math
import ujson

# ── Config ────────────────────────────────────────────────────────────────────
SKIER_ID           = 'SK01'
LORA_FREQUENCY     = 915000000
LORA_SF            = 7
SEND_INTERVAL_MS   = 5000      # Match real wearable cadence

# Simulated GPS start point — Mt Buller ski resort, Victoria
BASE_LAT   = -37.1522
BASE_LON   = 146.4418
BASE_ALT   = 1600.0

# ── Scenario definitions ──────────────────────────────────────────────────────
# Each scenario runs for DURATION seconds then advances to the next.
# Values match the real wearable's alert thresholds exactly.
#
# alert levels:
#   0 = normal        green LED, no hub action
#   1 = L1 warning    skin_temp < 15 or battery < 15%  (local only)
#   2 = L2 fall       IMU spike — dashboard alert + 60s ACK timer
#   3 = L3 SOS        burial / unacked fall — immediate email
#
SCENARIOS = [
    {
        'name':     'Normal skiing',
        'duration': 25,
        'alert':    0,
        'skin_temp_range': (27.0, 31.0),   # warm skin, active skiing
        'light_range':     (800.0, 1400.0), # bright outdoor
        'speed_range':     (18.0, 35.0),    # moving
        'alt_drift':       5.0,
    },
    {
        'name':     'COLD WARNING (L1) — skin_temp below 15C',
        'duration': 20,
        'alert':    1,
        'skin_temp_range': (11.0, 14.5),   # cold — triggers L1
        'light_range':     (400.0, 700.0),
        'speed_range':     (2.0, 8.0),     # slowing down
        'alt_drift':       2.0,
    },
    {
        'name':     'FALL DETECTED (L2) — dashboard alert starts',
        'duration': 25,
        'alert':    2,
        'skin_temp_range': (11.0, 13.0),
        'light_range':     (300.0, 500.0),
        'speed_range':     (0.0, 1.0),     # stopped after fall
        'alt_drift':       0.0,
    },
    {
        'name':     'BURIAL / SOS (L3) — darkness + immobility',
        'duration': 35,
        'alert':    3,
        'skin_temp_range': (8.0, 10.5),    # critical cold
        'light_range':     (1.0, 6.0),     # darkness — triggers burial
        'speed_range':     (0.0, 0.0),     # completely still
        'alt_drift':       0.0,
    },
    {
        'name':     'Recovery — back to normal',
        'duration': 20,
        'alert':    0,
        'skin_temp_range': (24.0, 28.0),
        'light_range':     (600.0, 1000.0),
        'speed_range':     (5.0, 15.0),
        'alt_drift':       3.0,
    },
]

# ── LoRa setup ────────────────────────────────────────────────────────────────
print('')
print('SkiSafe SIMULATOR starting — ' + SKIER_ID)
print('No sensors required — all values are simulated.')
print('Antenna must be connected to the bottom-left U.FL connector.')
print('')

lora = LoRa(
    mode        = LoRa.LORA,
    region      = LoRa.AU915,
    frequency   = LORA_FREQUENCY,
    bandwidth   = LoRa.BW_125KHZ,
    sf          = LORA_SF,
    preamble    = 8,
    coding_rate = LoRa.CODING_4_5,
    power_mode  = LoRa.ALWAYS_ON
)
lora_sock = socket.socket(socket.AF_LORA, socket.SOCK_RAW)
lora_sock.setblocking(False)
print('LoRa OK — ' + str(LORA_FREQUENCY // 1000000) + ' MHz SF' + str(LORA_SF))
print('')

# ── Simple pseudo-random number generator (no random module in Pycom) ─────────
_seed = utime.ticks_ms()

def _rand():
    """Return a float between 0.0 and 1.0."""
    global _seed
    _seed = (_seed * 1103515245 + 12345) & 0x7fffffff
    return _seed / 0x7fffffff

def rand_range(lo, hi):
    """Return a float between lo and hi."""
    if lo == hi:
        return lo
    return lo + _rand() * (hi - lo)

# ── GPS drift — wander slightly each packet ───────────────────────────────────
_cur_lat = BASE_LAT
_cur_lon = BASE_LON
_cur_alt = BASE_ALT

def drift_gps(max_deg, alt_drift):
    """Nudge lat/lon/alt slightly to simulate movement."""
    global _cur_lat, _cur_lon, _cur_alt
    if max_deg > 0:
        _cur_lat += (_rand() - 0.5) * max_deg * 0.0001
        _cur_lon += (_rand() - 0.5) * max_deg * 0.0001
    if alt_drift > 0:
        _cur_alt += (_rand() - 0.5) * alt_drift
    return round(_cur_lat, 6), round(_cur_lon, 6), round(_cur_alt, 1)

# ── Packet builder ────────────────────────────────────────────────────────────
_pkt_count = 0

def send_packet(scenario):
    global _pkt_count
    _pkt_count += 1

    st  = round(rand_range(*scenario['skin_temp_range']), 1)
    lx  = round(rand_range(*scenario['light_range']), 1)
    spd = round(rand_range(*scenario['speed_range']), 1)
    lat, lon, alt = drift_gps(scenario.get('speed_range', (0, 0))[1], scenario['alt_drift'])
    lvl = scenario['alert']

    payload  = '{"i":"' + SKIER_ID + '"'
    payload += ',"c":'  + str(_pkt_count)
    payload += ',"st":' + str(st)
    payload += ',"lx":' + str(lx)
    payload += ',"la":' + str(lat)
    payload += ',"lo":' + str(lon)
    payload += ',"al":' + str(alt)
    payload += ',"sp":' + str(spd)
    payload += ',"a":'  + str(lvl)
    payload += '}'

    try:
        lora_sock.send(payload.encode())
        print('TX #' + str(_pkt_count) + ' [L' + str(lvl) + '] ' +
              'temp=' + str(st) + 'C  ' +
              'lux=' + str(lx) + '  ' +
              'spd=' + str(spd) + 'km/h  ' +
              str(len(payload)) + 'B')
    except Exception as e:
        print('TX FAILED: ' + str(e))

# ── Main loop ─────────────────────────────────────────────────────────────────
scenario_idx   = 0
scenario_start = utime.ticks_ms()
last_send_ms   = 0

total_scenarios = len(SCENARIOS)

print('Cycling through ' + str(total_scenarios) + ' scenarios.')
print('Watch your dashboard at http://192.168.0.208:5000')
print('─' * 55)

while True:
    now_ms = utime.ticks_ms()
    scene  = SCENARIOS[scenario_idx]

    # ── Check if it is time to advance to the next scenario ──
    elapsed_s = utime.ticks_diff(now_ms, scenario_start) // 1000
    if elapsed_s >= scene['duration']:
        scenario_idx   = (scenario_idx + 1) % total_scenarios
        scenario_start = now_ms
        scene          = SCENARIOS[scenario_idx]
        print('')
        print('>>> SCENARIO ' + str(scenario_idx + 1) + '/' + str(total_scenarios) +
              ': ' + scene['name'])
        print('    Duration: ' + str(scene['duration']) + 's  Alert level: L' +
              str(scene['alert']))
        print('─' * 55)

    # ── Send on interval ──
    if utime.ticks_diff(now_ms, last_send_ms) >= SEND_INTERVAL_MS:
        send_packet(scene)
        last_send_ms = now_ms

    utime.sleep_ms(100)
