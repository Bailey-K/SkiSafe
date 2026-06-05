#!/usr/bin/env python3
"""
SkiSafe — reader.py
Reads serial output from the hub LoPy4 (receiver.py), parses the short-key
JSON telemetry packets, maps to full field names, inserts into SQLite, and creates
alert_log entries when the wearable reports a level ≥ 2 event.

Changes from reader.py:
  • Added 'bt' -> 'battery_pct' to KEY_MAP
  • Added battery_pct REAL column to sensor_log (CREATE TABLE + migration)
  • insert_reading() now writes battery_pct
  • Console RX line includes battery percentage

Sessions:
    A new session is opened when reader.py starts, or when no packet
    has been received for SESSION_GAP_S seconds (default 120).  Every sensor_log and
    alert_log row carries the current session_id so the review page can show
    historical sessions independently.

Run: python3 ~/skisafe/reader.py

The hub LoPy4 (via Pytrack USB) prints lines like:
    Received: {"i":"SK01","c":5,"st":20.3,"lx":240,"la":-37.84,"lo":144.96,"al":523,"sp":12.3,"bt":87,"a":0}
    RSSI: -72
    SNR: 8.5

Short-key → full-name mapping (must match wearable firmware):
    i  = skier_id        (string)
    c  = packet_count    (int)
    st = skin_temp       (float, °C)
    lx = light           (float, lux)
    la = lat             (float, decimal degrees)
    lo = lon             (float)
    al = altitude        (float, metres)
    sp = speed           (float, km/h)
    bt = battery_pct     (int, 0-100)
    a  = alert           (int, 0-3)
"""

import serial
import sqlite3
import json
import time
import os
import sys
from datetime import datetime

# ── Configuration ─────────────────────────────────────────────────────────────
SERIAL_PORT   = os.environ.get('SKISAFE_PORT', '/dev/ttyACM0')
SERIAL_BAUD   = 115200
DB_PATH       = os.path.expanduser(os.environ.get('SKISAFE_DB', '~/skisafe/skisafe.db'))
SESSION_GAP_S = int(os.environ.get('SESSION_GAP_S', '120'))   # seconds gap → new session

# ── Short-key to full-name map ─────────────────────────────────────────────────
KEY_MAP = {
    'i':  'skier_id',
    'c':  'packet_count',
    'st': 'skin_temp',
    'lx': 'light',
    'la': 'lat',
    'lo': 'lon',
    'al': 'altitude',
    'sp': 'speed',
    'bt': 'battery_pct',
    'a':  'alert',
}

# ── Session state ──────────────────────────────────────────────────────────────
_current_session_id  = None
_last_packet_epoch   = 0.0


# ── Database setup ─────────────────────────────────────────────────────────────
def init_db(path):
    """Create / migrate tables.  Idempotent — safe to call on every start."""
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA synchronous=NORMAL')

    conn.executescript('''
        CREATE TABLE IF NOT EXISTS sessions (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            start_ts     TEXT    NOT NULL,
            end_ts       TEXT,
            skier_id     TEXT,
            start_epoch  REAL    NOT NULL
        );

        CREATE TABLE IF NOT EXISTS sensor_log (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id   INTEGER REFERENCES sessions(id),
            ts           TEXT    NOT NULL,
            skier_id     TEXT,
            packet_count INTEGER,
            skin_temp    REAL,
            light        REAL,
            lat          REAL,
            lon          REAL,
            altitude     REAL,
            speed        REAL,
            alert        INTEGER DEFAULT 0,
            rssi         INTEGER,
            snr          REAL,
            battery_pct  REAL
        );

        CREATE TABLE IF NOT EXISTS alert_log (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id    INTEGER REFERENCES sessions(id),
            ts            TEXT    NOT NULL,
            created_epoch REAL    NOT NULL,
            skier_id      TEXT,
            level         INTEGER,
            lat           REAL,
            lon           REAL,
            message       TEXT,
            acknowledged  INTEGER DEFAULT 0,
            ack_ts        TEXT,
            ack_by        TEXT,
            escalated     INTEGER DEFAULT 0,
            email_sent    INTEGER DEFAULT 0
        );
    ''')
    conn.commit()

    # ── Migration: add missing columns to existing tables ─────────────────────
    cols = [r[1] for r in conn.execute('PRAGMA table_info(sensor_log)').fetchall()]
    if 'session_id' not in cols:
        conn.execute('ALTER TABLE sensor_log ADD COLUMN session_id INTEGER')
        conn.commit()
        print('[db] Migrated sensor_log — added session_id column')
    if 'battery_pct' not in cols:
        conn.execute('ALTER TABLE sensor_log ADD COLUMN battery_pct REAL')
        conn.commit()
        print('[db] Migrated sensor_log — added battery_pct column')

    cols_al = [r[1] for r in conn.execute('PRAGMA table_info(alert_log)').fetchall()]
    if 'session_id' not in cols_al:
        conn.execute('ALTER TABLE alert_log ADD COLUMN session_id INTEGER')
        conn.commit()
        print('[db] Migrated alert_log — added session_id column')

    return conn


# ── Session management ─────────────────────────────────────────────────────────
def get_or_create_session(conn, skier_id):
    """
    Return the current session_id.
    Opens a new session when:
      - reader.py just started (no session yet), OR
      - more than SESSION_GAP_S seconds have passed since the last packet.
    """
    global _current_session_id, _last_packet_epoch

    now = time.time()
    gap = now - _last_packet_epoch

    if _current_session_id is None or gap > SESSION_GAP_S:
        ts = datetime.now().isoformat()
        cur = conn.execute(
            'INSERT INTO sessions (start_ts, start_epoch, skier_id) VALUES (?,?,?)',
            (ts, now, skier_id)
        )
        conn.commit()
        _current_session_id = cur.lastrowid
        reason = 'first packet' if gap > 9e8 else ('gap of ' + str(int(gap)) + 's')
        print('[session] New session #' + str(_current_session_id) +
              ' started for ' + skier_id + ' (' + reason + ')')

    _last_packet_epoch = now
    return _current_session_id


def touch_session(conn, session_id):
    """Update the session end_ts to now (called after every inserted packet)."""
    conn.execute(
        'UPDATE sessions SET end_ts=? WHERE id=?',
        (datetime.now().isoformat(), session_id)
    )


# ── Helpers ────────────────────────────────────────────────────────────────────
def make_alert_message(data):
    level = data.get('alert', 0)
    msgs  = []
    if level >= 2:
        msgs.append('Fall detected (IMU threshold exceeded)')
    if data.get('skin_temp', 99) < 15:
        msgs.append('Low skin temperature: ' + str(data.get('skin_temp', '?')) + ' C')
    if data.get('light', 99) < 10:
        msgs.append('Possible burial (very low light + immobility)')
    return '; '.join(msgs) if msgs else 'Alert level ' + str(level)


def insert_reading(conn, data, rssi, snr, session_id):
    """Insert a parsed sensor reading into sensor_log."""
    ts = datetime.now().isoformat()
    conn.execute('''
        INSERT INTO sensor_log
            (session_id, ts, skier_id, packet_count, skin_temp, light,
             lat, lon, altitude, speed, alert, rssi, snr, battery_pct)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    ''', (
        session_id,
        ts,
        data.get('skier_id', 'UNKNOWN'),
        data.get('packet_count', 0),
        data.get('skin_temp', None),
        data.get('light', None),
        data.get('lat', 0.0),
        data.get('lon', 0.0),
        data.get('altitude', 0.0),
        data.get('speed', 0.0),
        data.get('alert', 0),
        rssi,
        snr,
        data.get('battery_pct', None),
    ))
    conn.commit()
    return ts


def maybe_create_alert(conn, data, ts, session_id):
    """Create an alert_log row when alert ≥ 2, but only if no open alert already exists."""
    level    = data.get('alert', 0)
    skier_id = data.get('skier_id', 'UNKNOWN')

    if level < 2:
        return

    existing = conn.execute(
        '''SELECT id, level FROM alert_log
           WHERE skier_id=? AND session_id=? AND acknowledged=0
           ORDER BY created_epoch DESC LIMIT 1''',
        (skier_id, session_id)
    ).fetchone()

    if existing is None:
        conn.execute('''
            INSERT INTO alert_log
                (session_id, ts, created_epoch, skier_id, level, lat, lon,
                 message, acknowledged, escalated, email_sent)
            VALUES (?,?,?,?,?,?,?,?,0,0,0)
        ''', (
            session_id,
            ts,
            time.time(),
            skier_id,
            level,
            data.get('lat', 0.0),
            data.get('lon', 0.0),
            make_alert_message(data),
        ))
        conn.commit()
        print('[ALERT] New alert L' + str(level) + ' for ' + skier_id)
    elif level > dict(existing)['level']:
        conn.execute(
            'UPDATE alert_log SET level=?, message=? WHERE id=?',
            (level, make_alert_message(data), dict(existing)['id'])
        )
        conn.commit()
        print('[ALERT] Escalated to L' + str(level) + ' for ' + skier_id)


def map_keys(raw):
    """Translate short JSON keys to full field names."""
    result = {}
    for k, v in raw.items():
        full_key = KEY_MAP.get(k, k)
        result[full_key] = v
    return result


def parse_line(line):
    """Extract JSON object from a line, handling 'Received: {...}' prefix."""
    line = line.strip()
    if not line:
        return None

    json_str = None
    if line.startswith('Received:'):
        json_str = line[9:].strip()
    elif line.startswith('{'):
        json_str = line
    else:
        return None

    try:
        raw  = json.loads(json_str)
        return map_keys(raw)
    except json.JSONDecodeError as e:
        print('[parse error] ' + str(e) + '  raw: ' + json_str[:80])
        return None


def open_serial():
    """Open the serial port, with a helpful error message if it fails."""
    try:
        ser = serial.Serial(SERIAL_PORT, SERIAL_BAUD, timeout=1)
        print('Serial opened: ' + SERIAL_PORT + ' @ ' + str(SERIAL_BAUD))
        return ser
    except serial.SerialException as e:
        print('ERROR: Cannot open ' + SERIAL_PORT + ' — ' + str(e))
        print('')
        print('Check:')
        print('  • Hub LoPy4 (Pytrack) is connected via USB')
        print('  • ls /dev/ttyACM*  to find the correct port')
        print('  • Set SKISAFE_PORT=/dev/ttyACM1 etc. if different')
        print('  • Are you in the dialout group?  sudo usermod -aG dialout bailey-k')
        sys.exit(1)


# ── Main loop ─────────────────────────────────────────────────────────────────
def main():
    print('SkiSafe reader.py starting')
    print('Serial: ' + SERIAL_PORT + '  DB: ' + DB_PATH)
    print('Session gap: ' + str(SESSION_GAP_S) + 's')

    conn = init_db(DB_PATH)
    ser  = open_serial()

    rssi = None
    snr  = None

    try:
        while True:
            try:
                raw_line = ser.readline()
                if not raw_line:
                    continue
                line = raw_line.decode('utf-8', errors='ignore').strip()
            except (OSError, serial.SerialException) as e:
                print('[serial error] ' + str(e) + ' — reconnecting in 3 s')
                time.sleep(3)
                try:
                    ser.close()
                except Exception:
                    pass
                ser = open_serial()
                continue

            if not line:
                continue

            if line.startswith('RSSI:'):
                try:
                    rssi = int(line.split(':')[1].strip())
                except Exception:
                    pass
                continue
            if line.startswith('SNR:'):
                try:
                    snr = float(line.split(':')[1].strip())
                except Exception:
                    pass
                continue

            data = parse_line(line)
            if data is None:
                if line and not line.startswith('#'):
                    print('[hub] ' + line)
                continue

            if 'skier_id' not in data:
                print('[skip] no skier_id in: ' + str(data))
                rssi = None; snr = None
                continue

            session_id = get_or_create_session(conn, data['skier_id'])
            ts         = insert_reading(conn, data, rssi, snr, session_id)
            touch_session(conn, session_id)
            maybe_create_alert(conn, data, ts, session_id)

            bat_str = str(data.get('battery_pct', '?')) + '%'
            print('[S' + str(session_id) + '] RX ' + str(data.get('skier_id')) +
                  '  alert=' + str(data.get('alert', 0)) +
                  '  skin='  + str(data.get('skin_temp', '?')) + 'C' +
                  '  lux='   + str(data.get('light', '?')) +
                  '  bat='   + bat_str +
                  ('  RSSI=' + str(rssi) if rssi else '') +
                  ('  SNR='  + str(snr)  if snr  else ''))

            rssi = None
            snr  = None

    except KeyboardInterrupt:
        print('\nreader.py stopped.')
    finally:
        try:
            ser.close()
        except Exception:
            pass
        conn.close()


if __name__ == '__main__':
    main()
