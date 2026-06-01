#!/usr/bin/env python3
"""
SkiSafe — app.py
Flask hub application for the Raspberry Pi.

Templates are loaded from ./templates/ (dashboard.html, review.html).
Run from the skisafe directory so Flask can find the templates folder:
    cd ~/skisafe && python3 app.py

Routes:
    /                       Live dashboard
    /review                 Post-session review
    /api/state              Latest flat sensor reading (polled by dashboard every 5s)
    /api/history            Last N sensor_log rows (oldest first, for charts)
                              ?session_id=X   filter to a specific session
                              ?limit=200
    /api/alerts             Full alert_log (most recent first)
                              ?session_id=X
    /api/session            Session summary statistics
                              ?session_id=X
    /api/sessions           List of all sessions (most recent first)
    /api/ack  POST          Acknowledge active alert(s)
    /api/alert POST         Inject a test alert (for testing email escalation)

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
            snr          REAL
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

    # ── Migration: add columns to existing tables if missing ──────────────────
    for tbl in ('sensor_log', 'alert_log'):
        cols = [r[1] for r in conn.execute('PRAGMA table_info(' + tbl + ')').fetchall()]
        if 'session_id' not in cols:
            conn.execute('ALTER TABLE ' + tbl + ' ADD COLUMN session_id INTEGER')
            conn.commit()
            print('[db] Migrated ' + tbl + ' — added session_id column')

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
    Includes session_id so the dashboard can detect session changes.
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


@app.route('/api/sessions')
def api_sessions():
    """
    List of all sessions, most recent first.
    Shape: [{ id, start_ts, end_ts, skier_id, start_epoch, reading_count }]
    """
    conn = get_db()
    try:
        rows = conn.execute('''
            SELECT s.*,
                   COUNT(sl.id) AS reading_count
            FROM sessions s
            LEFT JOIN sensor_log sl ON sl.session_id = s.id
            GROUP BY s.id
            ORDER BY s.id DESC
        ''').fetchall()
        return jsonify([dict(r) for r in rows])
    finally:
        conn.close()


@app.route('/api/history')
def api_history():
    """
    Sensor readings oldest-first (charts need chronological order).
    ?session_id=X  — restrict to a specific session
    ?limit=200     — max rows (default 200)
    """
    conn = get_db()
    try:
        limit      = int(request.args.get('limit', 200))
        session_id = request.args.get('session_id')

        if session_id and session_id != 'latest':
            rows = conn.execute(
                'SELECT * FROM sensor_log WHERE session_id=? ORDER BY id ASC LIMIT ?',
                (int(session_id), limit)
            ).fetchall()
        else:
            # Default: latest session
            latest = conn.execute(
                'SELECT id FROM sessions ORDER BY id DESC LIMIT 1'
            ).fetchone()
            if latest:
                rows = conn.execute(
                    'SELECT * FROM sensor_log WHERE session_id=? ORDER BY id ASC LIMIT ?',
                    (latest['id'], limit)
                ).fetchall()
            else:
                rows = conn.execute(
                    'SELECT * FROM sensor_log ORDER BY id ASC LIMIT ?', (limit,)
                ).fetchall()

        return jsonify([dict(r) for r in rows])
    finally:
        conn.close()


@app.route('/api/alerts')
def api_alerts():
    """
    Alert log, most recent first.
    ?session_id=X — restrict to a specific session
    """
    conn = get_db()
    try:
        limit      = int(request.args.get('limit', 100))
        session_id = request.args.get('session_id')

        if session_id and session_id != 'latest':
            rows = conn.execute(
                'SELECT * FROM alert_log WHERE session_id=? ORDER BY id DESC LIMIT ?',
                (int(session_id), limit)
            ).fetchall()
        else:
            # Default: latest session
            latest = conn.execute(
                'SELECT id FROM sessions ORDER BY id DESC LIMIT 1'
            ).fetchone()
            if latest:
                rows = conn.execute(
                    'SELECT * FROM alert_log WHERE session_id=? ORDER BY id DESC LIMIT ?',
                    (latest['id'], limit)
                ).fetchall()
            else:
                rows = conn.execute(
                    'SELECT * FROM alert_log ORDER BY id DESC LIMIT ?', (limit,)
                ).fetchall()

        return jsonify([dict(r) for r in rows])
    finally:
        conn.close()


@app.route('/api/session')
def api_session():
    """
    Session summary statistics.
    ?session_id=X — specific session (default: latest)
    """
    conn = get_db()
    try:
        session_id = request.args.get('session_id')

        if session_id and session_id != 'latest':
            sid = int(session_id)
        else:
            latest = conn.execute(
                'SELECT id FROM sessions ORDER BY id DESC LIMIT 1'
            ).fetchone()
            sid = latest['id'] if latest else None

        if sid is None:
            return jsonify({})

        # Session metadata
        sess = conn.execute('SELECT * FROM sessions WHERE id=?', (sid,)).fetchone()

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
            WHERE session_id=?
        ''', (sid,)).fetchone()

        row = dict(s)
        if sess:
            row['session_id']  = sess['id']
            row['skier_id']    = sess['skier_id']

        # Duration in minutes
        dur = None
        if row['session_start'] and row['session_end']:
            try:
                fmt = '%Y-%m-%dT%H:%M:%S.%f'
                t0  = datetime.strptime(row['session_start'][:26], fmt)
                t1  = datetime.strptime(row['session_end'][:26],   fmt)
                dur = round((t1 - t0).total_seconds() / 60, 1)
            except Exception:
                pass

        row['duration_min'] = dur
        row['alert_count']  = row['total_alerts']
        row['min_temp']     = row['min_skin_temp']

        return jsonify(row)
    finally:
        conn.close()


@app.route('/api/ack', methods=['POST'])
def api_ack():
    """Acknowledge active alert(s)."""
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
    """Inject a test alert."""
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
        latest = conn.execute(
            'SELECT id FROM sessions ORDER BY id DESC LIMIT 1'
        ).fetchone()
        session_id = latest['id'] if latest else None

        conn.execute('''
            INSERT INTO alert_log
                (session_id, ts, created_epoch, skier_id, level, lat, lon, message,
                 acknowledged, escalated, email_sent)
            VALUES (?,?,?,?,?,0,0,?,0,0,0)
        ''', (session_id, datetime.now().isoformat(), time.time(), skier_id, level, message))
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
