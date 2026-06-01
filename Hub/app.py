#!/usr/bin/env python3
"""
SkiSafe — app.py
Flask hub application for the Raspberry Pi.

Templates are loaded from ./templates/ (dashboard.html, review.html).
Run from the skisafe directory so Flask can find the templates folder:
    cd ~/skisafe && python3 app.py

Routes:
    /                   Live dashboard
    /review             Post-session review
    /api/state          Latest flat sensor reading (polled by dashboard every 5s)
    /api/history        Last N sensor_log rows (oldest first, for charts)
    /api/alerts         Full alert_log (most recent first)
    /api/session        Session summary statistics
    /api/ack  POST      Acknowledge active alert(s)
    /api/alert POST     Inject a test alert (for testing email escalation)

Environment variables (set in ~/.bashrc — do NOT hard-code credentials):
    SMTP_USER           Gmail address used to send SOS email
    SMTP_APP_PASSWORD   16-char Gmail App Password
    EMERGENCY_EMAIL     Comma-separated recipient addresses
    SKISAFE_DB          Path to skisafe.db  (default: ~/skisafe/skisafe.db)
    ACK_TIMEOUT         Seconds before L2 escalates to email (default: 60)
"""

from flask import Flask, request, jsonify, render_template
import sqlite3
import smtplib
import ssl
import time
import os
import threading
from datetime import datetime
from email.message import EmailMessage

# ── App setup ─────────────────────────────────────────────────────────────────
# template_folder resolves to ./templates relative to this file.
# Always run: cd ~/skisafe && python3 app.py  (not python3 ~/skisafe/app.py)
app = Flask(__name__, template_folder='templates')

# ── Configuration ─────────────────────────────────────────────────────────────
DB_PATH           = os.path.expanduser(os.environ.get('SKISAFE_DB', '~/skisafe/skisafe.db'))
SMTP_USER         = os.environ.get('SMTP_USER', '')
SMTP_APP_PASSWORD = os.environ.get('SMTP_APP_PASSWORD', '')
EMERGENCY_EMAIL   = os.environ.get('EMERGENCY_EMAIL', '')
ACK_TIMEOUT       = int(os.environ.get('ACK_TIMEOUT', '60'))


# ── Database helpers ───────────────────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    return conn


def ensure_schema():
    conn = get_db()
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS sensor_log (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
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
            snr          REAL
        );
        CREATE TABLE IF NOT EXISTS alert_log (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
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
    conn.close()


# ── Email ─────────────────────────────────────────────────────────────────────
def send_sos_email(alert_row):
    if not SMTP_USER or not SMTP_APP_PASSWORD or not EMERGENCY_EMAIL:
        print('[email] Credentials not configured — skipping email send.')
        return False

    skier    = alert_row['skier_id'] or 'Unknown'
    lat      = alert_row['lat']  or 0.0
    lon      = alert_row['lon']  or 0.0
    maps_url = 'https://www.google.com/maps?q=' + str(lat) + ',' + str(lon)
    age_mins = int((time.time() - alert_row['created_epoch']) / 60)

    body = (
        'SKISAFE SOS ALERT\n'
        '=================\n\n'
        'Skier   : ' + skier + '\n'
        'Level   : ' + str(alert_row['level']) + '\n'
        'Event   : ' + (alert_row['message'] or 'SOS') + '\n'
        'Age     : alert active for ~' + str(age_mins) + ' minute(s)\n'
        'Location: ' + str(lat) + ', ' + str(lon) + '\n'
        'Maps    : ' + maps_url + '\n\n'
        'Not acknowledged within ' + str(ACK_TIMEOUT) + ' seconds.\n'
        'Please check on the skier immediately.\n\n'
        '-- SkiSafe Hub'
    )

    msg            = EmailMessage()
    msg['Subject'] = 'SKISAFE SOS — ' + skier + ' needs assistance'
    msg['From']    = SMTP_USER
    recipients     = [r.strip() for r in EMERGENCY_EMAIL.split(',') if r.strip()]
    msg['To']      = ', '.join(recipients)
    msg.set_content(body)

    try:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL('smtp.gmail.com', 465, context=context) as server:
            server.login(SMTP_USER, SMTP_APP_PASSWORD)
            server.send_message(msg)
        print('[email] SOS sent to: ' + ', '.join(recipients))
        return True
    except smtplib.SMTPAuthenticationError:
        print('[email] AUTHENTICATION FAILED — use a Gmail App Password, not your account password.')
        print('[email] Generate at: myaccount.google.com/apppasswords')
        return False
    except Exception as e:
        print('[email] Send failed: ' + str(e))
        return False


# ── Alert monitor thread ───────────────────────────────────────────────────────
def alert_monitor():
    print('[monitor] Alert escalation monitor started (ACK_TIMEOUT=' + str(ACK_TIMEOUT) + 's)')
    while True:
        time.sleep(5)
        try:
            conn = get_db()
            rows = conn.execute('''
                SELECT * FROM alert_log
                WHERE acknowledged=0 AND escalated=0 AND level >= 2
            ''').fetchall()
            for row in rows:
                age = time.time() - row['created_epoch']
                if age >= ACK_TIMEOUT:
                    print('[monitor] Alert ' + str(row['id']) + ' unacked ' +
                          str(int(age)) + 's — escalating')
                    sent = send_sos_email(row)
                    conn.execute(
                        'UPDATE alert_log SET escalated=1, email_sent=? WHERE id=?',
                        (1 if sent else 0, row['id'])
                    )
                    conn.commit()
            conn.close()
        except Exception as e:
            print('[monitor] Error: ' + str(e))


# ── Flask routes ───────────────────────────────────────────────────────────────
@app.route('/')
def dashboard():
    return render_template('dashboard.html')


@app.route('/review')
def review():
    return render_template('review.html')


@app.route('/api/state')
def api_state():
    """
    Latest sensor reading as a flat dict — consumed directly by dashboard.html.
    Returns the most recent row from sensor_log.

    Shape: { ts, skier_id, skin_temp, light, lat, lon, altitude, speed,
             alert, rssi, snr, packet_count }
    """
    conn = get_db()
    try:
        row = conn.execute(
            'SELECT * FROM sensor_log ORDER BY id DESC LIMIT 1'
        ).fetchone()
        if row is None:
            return jsonify({})
        return jsonify(dict(row))
    finally:
        conn.close()


@app.route('/api/history')
def api_history():
    """Last N sensor readings, oldest first (charts need chronological order)."""
    conn = get_db()
    try:
        limit = int(request.args.get('limit', 200))
        rows  = conn.execute(
            'SELECT * FROM sensor_log ORDER BY id ASC LIMIT ?', (limit,)
        ).fetchall()
        return jsonify([dict(r) for r in rows])
    finally:
        conn.close()


@app.route('/api/alerts')
def api_alerts():
    """Full alert log, most recent first."""
    conn = get_db()
    try:
        limit = int(request.args.get('limit', 100))
        rows  = conn.execute(
            'SELECT * FROM alert_log ORDER BY id DESC LIMIT ?', (limit,)
        ).fetchall()
        return jsonify([dict(r) for r in rows])
    finally:
        conn.close()


@app.route('/api/session')
def api_session():
    """
    Session summary statistics.
    Includes aliased field names that review.html expects:
        duration_min, alert_count, min_temp, max_speed
    """
    conn = get_db()
    try:
        s = conn.execute('''
            SELECT
                COUNT(*)                                      AS total_readings,
                MIN(ts)                                       AS session_start,
                MAX(ts)                                       AS session_end,
                MIN(skin_temp)                                AS min_skin_temp,
                MAX(skin_temp)                                AS max_skin_temp,
                MAX(speed)                                    AS max_speed,
                MAX(altitude)                                 AS max_altitude,
                SUM(CASE WHEN alert >= 2 THEN 1 ELSE 0 END)  AS total_alerts
            FROM sensor_log
        ''').fetchone()

        row = dict(s)

        # Compute duration in minutes from first/last timestamp
        dur = None
        if row['session_start'] and row['session_end']:
            try:
                # Trim microseconds for safe parsing
                fmt = '%Y-%m-%dT%H:%M:%S.%f'
                t0  = datetime.strptime(row['session_start'][:26], fmt)
                t1  = datetime.strptime(row['session_end'][:26],   fmt)
                dur = round((t1 - t0).total_seconds() / 60, 1)
            except Exception:
                pass

        # Aliased fields for review.html
        row['duration_min'] = dur
        row['alert_count']  = row['total_alerts']
        row['min_temp']     = row['min_skin_temp']

        return jsonify(row)
    finally:
        conn.close()


@app.route('/api/ack', methods=['POST'])
def api_ack():
    """
    Acknowledge active alert(s).

    Called by dashboard.html with no body  → acknowledges ALL active alerts.
    Or with JSON { "alert_id": <int>, "ack_by": "<name>" } for a specific one.
    """
    body = {}
    if request.is_json:
        body = request.get_json(force=True) or {}
    elif request.form:
        body = request.form

    alert_id = body.get('alert_id')
    ack_by   = body.get('ack_by', 'dashboard')
    now_ts   = datetime.now().isoformat()

    conn = get_db()
    try:
        if alert_id is not None:
            # Specific alert
            row = conn.execute(
                'SELECT id FROM alert_log WHERE id=?', (int(alert_id),)
            ).fetchone()
            if row is None:
                return jsonify({'error': 'alert not found'}), 404
            conn.execute(
                'UPDATE alert_log SET acknowledged=1, ack_ts=?, ack_by=? WHERE id=?',
                (now_ts, ack_by, int(alert_id))
            )
            print('[ack] Alert ' + str(alert_id) + ' acknowledged by ' + str(ack_by))
        else:
            # No alert_id — acknowledge everything active
            conn.execute(
                'UPDATE alert_log SET acknowledged=1, ack_ts=?, ack_by=? WHERE acknowledged=0',
                (now_ts, ack_by)
            )
            print('[ack] All active alerts acknowledged by ' + str(ack_by))

        conn.commit()
        return jsonify({'ok': True, 'ack_by': ack_by})
    finally:
        conn.close()


@app.route('/api/alert', methods=['POST'])
def api_inject_alert():
    """
    Inject a test alert — use this to verify dashboard + email without a real event.

    curl example:
        curl -X POST http://192.168.0.208:5000/api/alert \\
             -H "Content-Type: application/json" \\
             -d '{"skier_id":"SK01","level":2,"message":"TEST — do not action"}'
    """
    body = {}
    if request.is_json:
        body = request.get_json(force=True) or {}
    elif request.form:
        body = request.form

    skier_id = body.get('skier_id', 'SK01')
    level    = int(body.get('level', 2))
    message  = body.get('message', 'Test alert injected via /api/alert')

    conn = get_db()
    try:
        conn.execute('''
            INSERT INTO alert_log
                (ts, created_epoch, skier_id, level, lat, lon, message,
                 acknowledged, escalated, email_sent)
            VALUES (?,?,?,?,0,0,?,0,0,0)
        ''', (datetime.now().isoformat(), time.time(), skier_id, level, message))
        conn.commit()
        print('[test] Injected L' + str(level) + ' alert for ' + skier_id)
        return jsonify({'ok': True, 'skier_id': skier_id, 'level': level})
    finally:
        conn.close()


# ── Entry point ────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    print('SkiSafe app.py starting')
    print('DB      : ' + DB_PATH)
    print('SMTP    : ' + (SMTP_USER or '[NOT SET — email will not send]'))
    print('RCPT    : ' + (EMERGENCY_EMAIL or '[NOT SET]'))
    print('TIMEOUT : ' + str(ACK_TIMEOUT) + 's')

    ensure_schema()

    t = threading.Thread(target=alert_monitor, daemon=True, name='alert-monitor')
    t.start()

    app.run(host='0.0.0.0', port=5000, debug=False)
