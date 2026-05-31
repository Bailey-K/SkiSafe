#!/usr/bin/env python3
"""
SkiSafe — app.py
Flask hub application for the Raspberry Pi.
Routes: / (dashboard), /review, /api/state, /api/history, /api/alerts,
        /api/session, /api/ack (POST), /api/alert (POST for testing).

Reads from SQLite (populated by reader.py running as a separate process).
Runs an alert monitor thread that escalates unacknowledged Level-2 alerts
to Level 3 / email after ACK_TIMEOUT_SECONDS.

Environment variables (set these — do NOT hard-code credentials):
    SMTP_USER         Gmail address used to send email
    SMTP_APP_PASSWORD 16-char Gmail App Password (not your account password)
    EMERGENCY_EMAIL   Comma-separated list of recipient addresses for SOS
    SKISAFE_DB        Path to skisafe.db  (default: ~/skisafe/skisafe.db)
    ACK_TIMEOUT       Seconds before L2 escalates to email (default: 60)

Quick-start:
    export SMTP_USER="your@gmail.com"
    export SMTP_APP_PASSWORD="xxxx xxxx xxxx xxxx"
    export EMERGENCY_EMAIL="emergency@contact.com"
    python3 ~/skisafe/app.py

WARNING — if you committed credentials to git:
    1. Revoke the old App Password immediately at myaccount.google.com/apppasswords
    2. Scrub history: pip install git-filter-repo
       git filter-repo --path-glob '*.py' --replace-text <(echo "old_password==>REDACTED")
    3. Force push: git push --force-with-lease origin main
"""

from flask import Flask, request, jsonify, render_template_string
import sqlite3
import smtplib
import ssl
import json
import time
import os
import threading
from datetime import datetime
from email.message import EmailMessage

app = Flask(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────
DB_PATH           = os.path.expanduser(os.environ.get('SKISAFE_DB', '~/skisafe/skisafe.db'))
SMTP_USER         = os.environ.get('SMTP_USER', '')
SMTP_APP_PASSWORD = os.environ.get('SMTP_APP_PASSWORD', '')
EMERGENCY_EMAIL   = os.environ.get('EMERGENCY_EMAIL', '')
ACK_TIMEOUT       = int(os.environ.get('ACK_TIMEOUT', '60'))

# ── Database helpers ───────────────────────────────────────────────────────────
def get_db():
    """Open a new SQLite connection.  Each call creates a fresh connection — thread-safe."""
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    return conn


def ensure_schema():
    """Create tables if missing — matches reader.py schema exactly."""
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
    """Send a Gmail SOS email for a Level-3 / unacknowledged alert."""
    if not SMTP_USER or not SMTP_APP_PASSWORD or not EMERGENCY_EMAIL:
        print('[email] Credentials not configured — skipping email send.')
        print('[email] Set SMTP_USER, SMTP_APP_PASSWORD, EMERGENCY_EMAIL env vars.')
        return False

    skier    = alert_row['skier_id'] or 'Unknown'
    lat      = alert_row['lat']  or 0.0
    lon      = alert_row['lon']  or 0.0
    level    = alert_row['level']
    message  = alert_row['message'] or 'SOS'
    maps_url = 'https://www.google.com/maps?q=' + str(lat) + ',' + str(lon)
    age_mins = int((time.time() - alert_row['created_epoch']) / 60)

    body = (
        'SKISAFE SOS ALERT\n'
        '=================\n\n'
        'Skier   : ' + skier + '\n'
        'Level   : ' + str(level) + '\n'
        'Event   : ' + message + '\n'
        'Age     : alert has been active for ~' + str(age_mins) + ' minute(s)\n'
        'Location: ' + str(lat) + ', ' + str(lon) + '\n'
        'Maps    : ' + maps_url + '\n\n'
        'This alert was not acknowledged within ' + str(ACK_TIMEOUT) + ' seconds.\n'
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
        print('[email] AUTHENTICATION FAILED — check SMTP_USER and SMTP_APP_PASSWORD.')
        print('[email] Must be a Gmail App Password, not your account password.')
        print('[email] Generate at: myaccount.google.com/apppasswords')
        return False
    except Exception as e:
        print('[email] Send failed: ' + str(e))
        return False


# ── Alert monitor thread ───────────────────────────────────────────────────────
def alert_monitor():
    """Background thread: escalate unacknowledged L2 alerts to L3 + email after timeout."""
    print('[monitor] Alert escalation monitor started (ACK_TIMEOUT=' + str(ACK_TIMEOUT) + 's)')
    while True:
        time.sleep(5)   # check every 5 seconds
        try:
            conn = get_db()
            rows = conn.execute('''
                SELECT * FROM alert_log
                WHERE acknowledged=0 AND escalated=0 AND level >= 2
            ''').fetchall()

            for row in rows:
                age = time.time() - row['created_epoch']
                if age >= ACK_TIMEOUT:
                    print('[monitor] Alert ' + str(row['id']) + ' for ' + str(row['skier_id']) +
                          ' unacked for ' + str(int(age)) + 's — escalating to email')
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
    return render_template_string(DASHBOARD_HTML)


@app.route('/review')
def review():
    return render_template_string(REVIEW_HTML)


@app.route('/api/state')
def api_state():
    """Latest reading per skier + active unacknowledged alerts."""
    conn = get_db()
    try:
        # Latest reading per skier (last row per skier_id)
        readings = conn.execute('''
            SELECT s.* FROM sensor_log s
            INNER JOIN (
                SELECT skier_id, MAX(id) AS max_id FROM sensor_log GROUP BY skier_id
            ) latest ON s.id = latest.max_id
        ''').fetchall()

        # Active (unacknowledged) alerts
        alerts = conn.execute('''
            SELECT * FROM alert_log WHERE acknowledged=0 ORDER BY created_epoch DESC
        ''').fetchall()

        return jsonify({
            'ts':       datetime.now().isoformat(),
            'readings': [dict(r) for r in readings],
            'alerts':   [dict(a) for a in alerts],
        })
    finally:
        conn.close()


@app.route('/api/history')
def api_history():
    """Last 200 sensor readings (most recent first)."""
    conn = get_db()
    try:
        limit = int(request.args.get('limit', 200))
        rows  = conn.execute(
            'SELECT * FROM sensor_log ORDER BY id DESC LIMIT ?', (limit,)
        ).fetchall()
        return jsonify([dict(r) for r in rows])
    finally:
        conn.close()


@app.route('/api/alerts')
def api_alerts():
    """Full alert log (most recent first)."""
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
    """Session summary statistics."""
    conn = get_db()
    try:
        stats = conn.execute('''
            SELECT
                COUNT(*)                     AS total_readings,
                MIN(ts)                      AS session_start,
                MAX(ts)                      AS session_end,
                MIN(skin_temp)               AS min_skin_temp,
                MAX(skin_temp)               AS max_skin_temp,
                MAX(speed)                   AS max_speed,
                MAX(altitude)                AS max_altitude,
                SUM(CASE WHEN alert>=2 THEN 1 ELSE 0 END) AS total_alerts
            FROM sensor_log
        ''').fetchone()
        return jsonify(dict(stats))
    finally:
        conn.close()


@app.route('/api/ack', methods=['POST'])
def api_ack():
    """Acknowledge an active alert.
    Body (JSON or form): { "alert_id": <int>, "ack_by": "<name>" }
    Dashboard ACK clears the countdown and records who acknowledged.
    Note: the wearable buzzer is silenced by pressing the physical button (P8)
    OR by a best-effort LoRa downlink if your receiver_final.py implements TX.
    """
    if request.is_json:
        body = request.get_json(force=True) or {}
    else:
        body = request.form

    alert_id = body.get('alert_id')
    ack_by   = body.get('ack_by', 'dashboard')

    if alert_id is None:
        return jsonify({'error': 'alert_id required'}), 400

    conn = get_db()
    try:
        row = conn.execute('SELECT * FROM alert_log WHERE id=?', (int(alert_id),)).fetchone()
        if row is None:
            return jsonify({'error': 'alert not found'}), 404

        conn.execute(
            'UPDATE alert_log SET acknowledged=1, ack_ts=?, ack_by=? WHERE id=?',
            (datetime.now().isoformat(), ack_by, int(alert_id))
        )
        conn.commit()
        print('[ack] Alert ' + str(alert_id) + ' acknowledged by ' + str(ack_by))
        return jsonify({'ok': True, 'alert_id': alert_id, 'ack_by': ack_by})
    finally:
        conn.close()


@app.route('/api/alert', methods=['POST'])
def api_inject_alert():
    """Inject a test alert — use this to verify dashboard + email without a real event.
    Body: { "skier_id": "SK01", "level": 2, "message": "Test" }
    """
    if request.is_json:
        body = request.get_json(force=True) or {}
    else:
        body = request.form

    skier_id = body.get('skier_id', 'SK01')
    level    = int(body.get('level', 2))
    message  = body.get('message', 'Test alert injected via /api/alert')

    conn = get_db()
    try:
        conn.execute('''
            INSERT INTO alert_log (ts, created_epoch, skier_id, level, lat, lon, message,
                                   acknowledged, escalated, email_sent)
            VALUES (?,?,?,?,0,0,?,0,0,0)
        ''', (datetime.now().isoformat(), time.time(), skier_id, level, message))
        conn.commit()
        print('[test] Injected L' + str(level) + ' alert for ' + skier_id)
        return jsonify({'ok': True, 'skier_id': skier_id, 'level': level})
    finally:
        conn.close()


# ── HTML Templates ─────────────────────────────────────────────────────────────
# If you have existing working templates in ~/skisafe/templates/, use those via
# Flask's template_folder and render_template() instead of render_template_string().
# These inline templates are a complete fallback / reference implementation.

DASHBOARD_HTML = '''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SkiSafe Dashboard</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: system-ui, sans-serif; background: #0d1117; color: #e6edf3; min-height: 100vh; }
  header { background: #161b22; padding: 1rem 1.5rem; border-bottom: 1px solid #30363d;
           display: flex; align-items: center; gap: 1rem; }
  header h1 { font-size: 1.25rem; }
  #status-badge { padding: .35rem .9rem; border-radius: 1rem; font-weight: 700;
                  font-size: .85rem; letter-spacing: .05em; }
  .ok    { background: #1a7f37; }
  .warn  { background: #9e6a03; }
  .alert { background: #b91c1c; }
  .sos   { background: #b91c1c; animation: pulse 0.8s infinite; }
  @keyframes pulse { 0%,100% { opacity:1 } 50% { opacity:.4 } }
  main { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; padding: 1rem; max-width: 1100px; }
  @media (max-width:700px) { main { grid-template-columns: 1fr; } }
  .card { background: #161b22; border: 1px solid #30363d; border-radius: .5rem; padding: 1rem; }
  .card h2 { font-size: .9rem; color: #8b949e; margin-bottom: .75rem; text-transform: uppercase; letter-spacing: .05em; }
  .sensor-grid { display: grid; grid-template-columns: 1fr 1fr; gap: .5rem; }
  .sensor-item label { display: block; font-size: .75rem; color: #8b949e; }
  .sensor-item span  { font-size: 1.2rem; font-weight: 600; }
  #map { height: 260px; border-radius: .5rem; }
  .alert-box { background: #450a0a; border: 1px solid #b91c1c; border-radius: .5rem;
               padding: 1rem; margin-bottom: .75rem; }
  .alert-box p { margin-bottom: .5rem; font-weight: 600; }
  .alert-box small { color: #f87171; }
  .ack-btn { background: #1a7f37; color: #fff; border: none; padding: .5rem 1.2rem;
             border-radius: .25rem; cursor: pointer; font-size: .85rem; }
  .ack-btn:hover { background: #276739; }
  #ts { font-size: .75rem; color: #8b949e; margin-left: auto; }
</style>
</head>
<body>
<header>
  <h1>&#9917; SkiSafe</h1>
  <span id="status-badge" class="ok">OK</span>
  <span id="ts">--</span>
</header>
<main>
  <div class="card" style="grid-column:1/-1">
    <h2>Active Alerts</h2>
    <div id="alerts-container"><p style="color:#8b949e">No active alerts</p></div>
  </div>
  <div class="card">
    <h2>Sensor Readings — <span id="skier-id">--</span></h2>
    <div class="sensor-grid">
      <div class="sensor-item"><label>Skin Temp</label><span id="skin_temp">--</span> °C</div>
      <div class="sensor-item"><label>Light</label><span id="light">--</span> lux</div>
      <div class="sensor-item"><label>Speed</label><span id="speed">--</span> km/h</div>
      <div class="sensor-item"><label>Altitude</label><span id="altitude">--</span> m</div>
      <div class="sensor-item"><label>Alert Level</label><span id="alert">--</span></div>
      <div class="sensor-item"><label>RSSI</label><span id="rssi">--</span> dBm</div>
    </div>
  </div>
  <div class="card">
    <h2>GPS Map</h2>
    <div id="map"></div>
  </div>
</main>
<div style="padding:0 1rem;max-width:1100px">
  <a href="/review" style="color:#58a6ff;font-size:.85rem">&#8594; Session Review Page</a>
</div>

<script>
const map = L.map('map').setView([-37.84, 144.96], 12);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
  attribution: '&copy; OpenStreetMap contributors', maxZoom: 19
}).addTo(map);
let marker = null;

function badgeClass(level) {
  if (level === 0) return 'ok';
  if (level === 1) return 'warn';
  if (level === 2) return 'alert';
  return 'sos';
}
function badgeLabel(level) {
  return ['OK','WARNING','ALERT','SOS'][level] || 'UNKNOWN';
}
function ack(alertId) {
  fetch('/api/ack', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({alert_id: alertId, ack_by: 'dashboard'})
  }).then(r => r.json()).then(d => { if (d.ok) poll(); });
}

function poll() {
  fetch('/api/state').then(r => r.json()).then(data => {
    document.getElementById('ts').textContent = new Date(data.ts).toLocaleTimeString();

    // Readings
    const r = data.readings[0];
    if (r) {
      document.getElementById('skier-id').textContent  = r.skier_id || '--';
      document.getElementById('skin_temp').textContent = r.skin_temp != null ? r.skin_temp.toFixed(1) : '--';
      document.getElementById('light').textContent     = r.light    != null ? r.light.toFixed(0)    : '--';
      document.getElementById('speed').textContent     = r.speed    != null ? r.speed.toFixed(1)    : '--';
      document.getElementById('altitude').textContent  = r.altitude != null ? r.altitude.toFixed(0) : '--';
      document.getElementById('alert').textContent     = r.alert    != null ? r.alert               : '--';
      document.getElementById('rssi').textContent      = r.rssi     != null ? r.rssi                : '--';

      // Map
      if (r.lat && r.lon && (r.lat !== 0 || r.lon !== 0)) {
        const ll = [r.lat, r.lon];
        if (!marker) { marker = L.marker(ll).addTo(map); map.setView(ll, 14); }
        else marker.setLatLng(ll);
      }

      // Status badge
      const level = r.alert || 0;
      const badge = document.getElementById('status-badge');
      badge.className = badgeClass(level);
      badge.textContent = badgeLabel(level);
    }

    // Active alerts
    const container = document.getElementById('alerts-container');
    if (data.alerts.length === 0) {
      container.innerHTML = '<p style="color:#8b949e">No active alerts</p>';
    } else {
      container.innerHTML = data.alerts.map(a => {
        const age = Math.round((Date.now()/1000 - a.created_epoch));
        const mapsUrl = a.lat && a.lon ? `https://www.google.com/maps?q=${a.lat},${a.lon}` : '#';
        return `<div class="alert-box">
          <p>&#128680; Level ${a.level} — ${a.message || ''}</p>
          <small>Skier: ${a.skier_id} &nbsp;|&nbsp; Active for ${age}s
            ${a.lat && a.lon ? `&nbsp;|&nbsp; <a href="${mapsUrl}" target="_blank" style="color:#f87171">Map</a>` : ''}
          </small><br><br>
          <button class="ack-btn" onclick="ack(${a.id})">&#10003; Acknowledge</button>
        </div>`;
      }).join('');
    }
  }).catch(e => console.log('poll error', e));
}

poll();
setInterval(poll, 3000);
</script>
</body>
</html>'''


REVIEW_HTML = '''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SkiSafe — Session Review</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: system-ui, sans-serif; background: #0d1117; color: #e6edf3; padding: 1rem; }
  h1 { margin-bottom: 1rem; }
  .card { background: #161b22; border: 1px solid #30363d; border-radius: .5rem;
          padding: 1rem; margin-bottom: 1rem; }
  .card h2 { font-size: .9rem; color: #8b949e; text-transform: uppercase;
             letter-spacing: .05em; margin-bottom: .75rem; }
  .stats-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap: .75rem; }
  .stat label { display: block; font-size: .75rem; color: #8b949e; }
  .stat span  { font-size: 1.3rem; font-weight: 700; }
  #map-review { height: 300px; border-radius: .5rem; }
  table { width: 100%; border-collapse: collapse; font-size: .8rem; }
  th, td { padding: .4rem .6rem; border-bottom: 1px solid #30363d; text-align: left; }
  th { color: #8b949e; }
  tr:hover td { background: #1c2128; }
  .l0 { color: #3fb950; } .l1 { color: #d29922; } .l2,.l3 { color: #f85149; }
  a { color: #58a6ff; font-size: .85rem; }
</style>
</head>
<body>
<a href="/">&larr; Back to Dashboard</a>
<h1 style="margin-top:.75rem">&#9917; SkiSafe — Session Review</h1>

<div class="card">
  <h2>Session Summary</h2>
  <div class="stats-grid" id="stats"></div>
</div>

<div class="card">
  <h2>GPS Track</h2>
  <div id="map-review"></div>
</div>

<div class="card">
  <h2>Skin Temperature &amp; Alert Level Over Time</h2>
  <canvas id="temp-chart" height="100"></canvas>
</div>

<div class="card">
  <h2>Speed Over Time</h2>
  <canvas id="speed-chart" height="80"></canvas>
</div>

<div class="card">
  <h2>Alert Log</h2>
  <table id="alert-table">
    <thead><tr><th>Time</th><th>Skier</th><th>Level</th><th>Message</th><th>Acked?</th><th>Escalated?</th></tr></thead>
    <tbody></tbody>
  </table>
</div>

<script>
const map2 = L.map('map-review').setView([-37.84, 144.96], 12);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
  attribution: '&copy; OpenStreetMap contributors'
}).addTo(map2);

// Session stats
fetch('/api/session').then(r=>r.json()).then(s => {
  document.getElementById('stats').innerHTML = [
    ['Readings', s.total_readings],
    ['Start', s.session_start ? new Date(s.session_start).toLocaleTimeString() : '--'],
    ['End',   s.session_end   ? new Date(s.session_end).toLocaleTimeString()   : '--'],
    ['Min Skin Temp', s.min_skin_temp != null ? s.min_skin_temp.toFixed(1)+' °C' : '--'],
    ['Max Skin Temp', s.max_skin_temp != null ? s.max_skin_temp.toFixed(1)+' °C' : '--'],
    ['Max Speed', s.max_speed != null ? s.max_speed.toFixed(1)+' km/h' : '--'],
    ['Max Altitude', s.max_altitude != null ? s.max_altitude.toFixed(0)+' m' : '--'],
    ['Total Alerts', s.total_alerts],
  ].map(([l,v]) => `<div class="stat"><label>${l}</label><span>${v}</span></div>`).join('');
});

// History
fetch('/api/history?limit=300').then(r=>r.json()).then(rows => {
  // Reverse so oldest first for charts
  rows.reverse();

  const labels     = rows.map(r => r.ts ? new Date(r.ts).toLocaleTimeString() : '');
  const skinTemps  = rows.map(r => r.skin_temp);
  const alertLevels= rows.map(r => r.alert);
  const speeds     = rows.map(r => r.speed);

  // GPS track
  const points = rows.filter(r => r.lat && r.lon && (r.lat !== 0 || r.lon !== 0))
                      .map(r => [r.lat, r.lon]);
  if (points.length > 0) {
    L.polyline(points, {color:'#58a6ff', weight:3}).addTo(map2);
    L.marker(points[0]).addTo(map2).bindPopup('Start');
    L.marker(points[points.length-1]).addTo(map2).bindPopup('Last position');
    map2.fitBounds(points);
  }

  // Alert pins on map
  rows.filter(r => r.alert >= 2 && r.lat && r.lon).forEach(r => {
    L.circleMarker([r.lat,r.lon], {radius:8, color:'#f85149', fillOpacity:0.8})
      .addTo(map2).bindPopup('Alert L'+r.alert);
  });

  // Temperature chart
  new Chart(document.getElementById('temp-chart'), {
    type: 'line',
    data: {
      labels,
      datasets: [
        { label: 'Skin Temp (°C)', data: skinTemps, borderColor:'#f97316', tension:0.3, pointRadius:0 },
        { label: 'Alert Level',    data: alertLevels, borderColor:'#f85149', tension:0.1, pointRadius:0, yAxisID:'y2' }
      ]
    },
    options: { scales: { y: {ticks:{color:'#8b949e'}}, y2:{position:'right',ticks:{color:'#f85149'},max:3},
               x:{ticks:{color:'#8b949e',maxTicksLimit:10}} },
               plugins:{legend:{labels:{color:'#e6edf3'}}} }
  });

  // Speed chart
  new Chart(document.getElementById('speed-chart'), {
    type: 'line',
    data: { labels, datasets: [{ label:'Speed (km/h)', data:speeds, borderColor:'#58a6ff', tension:0.3, pointRadius:0 }] },
    options: { scales: { y:{ticks:{color:'#8b949e'}}, x:{ticks:{color:'#8b949e',maxTicksLimit:10}} },
               plugins:{legend:{labels:{color:'#e6edf3'}}} }
  });
});

// Alert log table
fetch('/api/alerts').then(r=>r.json()).then(alerts => {
  document.querySelector('#alert-table tbody').innerHTML = alerts.map(a =>
    `<tr>
      <td>${a.ts ? new Date(a.ts).toLocaleTimeString() : '--'}</td>
      <td>${a.skier_id||'--'}</td>
      <td class="l${a.level}">L${a.level}</td>
      <td>${a.message||''}</td>
      <td>${a.acknowledged ? '&#10003; ' + (a.ack_by||'') : '&#10007;'}</td>
      <td>${a.escalated ? '&#128231; emailed' : '—'}</td>
    </tr>`
  ).join('');
});
</script>
</body>
</html>'''


# ── Entry point ────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    print('SkiSafe app.py starting')
    print('DB: ' + DB_PATH)
    print('SMTP_USER: ' + (SMTP_USER or '[NOT SET — email will not send]'))
    print('EMERGENCY_EMAIL: ' + (EMERGENCY_EMAIL or '[NOT SET]'))
    print('ACK_TIMEOUT: ' + str(ACK_TIMEOUT) + 's')

    ensure_schema()

    # Start alert escalation monitor in a background daemon thread
    t = threading.Thread(target=alert_monitor, daemon=True, name='alert-monitor')
    t.start()

    app.run(host='0.0.0.0', port=5000, debug=False)
