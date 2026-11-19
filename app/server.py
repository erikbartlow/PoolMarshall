"""Single-owner, private-network dashboard and read-only AqualinkD status bridge."""
import base64
import hmac
import json
import os
from pathlib import Path
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import urlopen, Request
from urllib.parse import urlparse
import time
from urllib.error import URLError

WEATHER_CACHE = {}
DB = os.environ.get('DB_PATH', '/data/poolside.db')
PASSWORD = os.environ.get('POOLSIDE_PASSWORD', '')
CONTROL_ENABLED = os.environ.get('POOL_CONTROL_ENABLED', 'false').lower() == 'true'
UPSTREAM = os.environ.get('AQUALINKD_URL', 'http://aqualinkd:80').rstrip('/')

def connect():
    db = sqlite3.connect(DB, timeout=10)
    db.execute('CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY CHECK(id=1), revision INTEGER NOT NULL, payload TEXT NOT NULL)')
    return db

class Handler(BaseHTTPRequestHandler):
    def reply(self, status, value, mime='application/json'):
        raw = value if isinstance(value, bytes) else json.dumps(value).encode()
        self.send_response(status)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(raw)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.end_headers()
        self.wfile.write(raw)

    def authorized(self):
        try:
            scheme, token = self.headers.get('Authorization', '').split(' ', 1)
            user, pwd = base64.b64decode(token, validate=True).decode().split(':', 1)
            if scheme == 'Basic' and user == 'poolside' and hmac.compare_digest(pwd.encode(), PASSWORD.encode()):
                return True
        except (ValueError, UnicodeError):
            pass
        self.send_response(401)
        self.send_header('WWW-Authenticate', 'Basic realm="PoolMarshall"')
        self.send_header('Content-Length', '0')
        self.end_headers()
        return False

    def do_GET(self):
        if self.path == '/healthz':
            return self.reply(200, {'ok': True})
        if not self.authorized():
            return
        if self.path == '/':
            return self.reply(200, Path(__file__).with_name('index.html').read_bytes(), 'text/html; charset=utf-8')
        assets = {
            '/icon-192.png': 'image/png', '/icon-512.png': 'image/png',
            '/apple-touch-icon.png': 'image/png', '/favicon.png': 'image/png',
            '/poolside-icon.png': 'image/png', '/manifest.webmanifest': 'application/manifest+json',
            '/features.js': 'text/javascript', '/pool-math.js': 'text/javascript', '/sw.js': 'text/javascript'
        }
        if self.path in assets:
            return self.reply(200, Path(__file__).with_name(self.path[1:]).read_bytes(), assets[self.path])
        if self.path == '/api/state':
            with connect() as db:
                row = db.execute('SELECT revision, payload FROM state WHERE id=1').fetchone()
            return self.reply(200, {'revision': row[0] if row else 0, 'data': json.loads(row[1]) if row else None})
        if self.path == '/api/weather':
            try:
                if WEATHER_CACHE.get('expires', 0) > time.time():
                    return self.reply(200, WEATHER_CACHE['value'])
                headers={'User-Agent': 'PoolMarshall/1.1 (https://codedthought.info)', 'Accept': 'application/geo+json'}
                with urlopen(Request('https://api.weather.gov/points/29.7604,-95.3698', headers=headers), timeout=8) as r:
                    metadata=json.loads(r.read(2000000))
                target=metadata['properties']['forecast']; parsed=urlparse(target)
                if parsed.scheme != 'https' or parsed.hostname != 'api.weather.gov' or not parsed.path.startswith('/gridpoints/'):
                    raise ValueError('Unexpected forecast URL')
                with urlopen(Request(target, headers=headers), timeout=8) as r:
                    forecast=json.loads(r.read(2000000))
                result={'periods':forecast['properties']['periods'], 'source':'National Weather Service', 'location':'Houston city center'}
                WEATHER_CACHE.update(expires=time.time()+1800, value=result)
                return self.reply(200, result)
            except (ValueError, KeyError, URLError, OSError, TimeoutError):
                return self.reply(503, {'error':'Forecast unavailable; no weather-based dose inferred'})
        if self.path == '/api/controller-status':
            try:
                with urlopen(UPSTREAM + '/api/status', timeout=4) as response:
                    value = json.loads(response.read(262144))
                # HTTP availability is not evidence of a live RS485 connection.
                return self.reply(200, {'httpAvailable': True, 'controlEnabled': CONTROL_ENABLED, 'panelConnection': 'Unverified; inspect native status and logs', 'status': value})
            except (URLError, ValueError, TimeoutError, OSError):
                return self.reply(503, {'httpAvailable': False, 'panelConnection': 'Unknown / unavailable'})
        self.reply(404, {'error': 'Not found'})

    def do_POST(self):
        if not self.authorized():
            return
        if self.path != '/api/command' or self.headers.get('X-Poolside-Write') != '1':
            return self.reply(403, {'error': 'Command not permitted'})
        if not CONTROL_ENABLED:
            return self.reply(403, {'error': 'Controls are locked. Verify equipment and enable the bridge on the Pi first.'})
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if length < 1 or length > 1024:
                raise ValueError()
            body = json.loads(self.rfile.read(length))
            circuit, value = body.get('circuit'), body.get('value')
            if circuit not in ('Filter_Pump', 'Spa') or type(value) is not int or value not in (0, 1):
                raise ValueError()
            with urlopen(UPSTREAM + '/api/status', timeout=4) as response:
                status = json.load(response)
            if not status.get('version') or status.get('version') == 'xx' or status.get('leds', {}).get(circuit) not in ('on', 'off'):
                return self.reply(409, {'error': 'No verified circuit state available. Command not sent.'})
            with urlopen(UPSTREAM + '/api/' + circuit + '/set?value=' + str(value), timeout=4) as response:
                reply = response.read(4096).decode('utf-8', errors='replace')
            return self.reply(202, {'requested': True, 'confirmed': False, 'upstreamReply': reply})
        except (ValueError, TypeError, AttributeError):
            self.reply(400, {'error': 'Invalid command'})
        except (URLError, TimeoutError, OSError):
            self.reply(502, {'error': 'Controller request failed or timed out. Outcome unknown; refresh status before retrying.'})

    def do_PUT(self):
        if not self.authorized():
            return
        # Browser writes must be same-origin custom-header requests. No CORS is enabled.
        if self.path != '/api/state' or self.headers.get('X-Poolside-Write') != '1':
            return self.reply(403, {'error': 'Write not permitted'})
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if length <= 0 or length > 20_000_000:
                return self.reply(413, {'error': 'Invalid request size'})
            body = json.loads(self.rfile.read(length))
            value = body['data']
            if not isinstance(body['revision'], int) or not isinstance(value, dict) or not isinstance(value.get('tasks'), dict) or not isinstance(value.get('logs'), list) or not isinstance(value.get('findings'), list) or not isinstance(value.get('settings'), dict):
                raise ValueError()
            with connect() as db:
                db.execute('BEGIN IMMEDIATE')
                row = db.execute('SELECT revision FROM state WHERE id=1').fetchone()
                revision = row[0] if row else 0
                if body['revision'] != revision:
                    return self.reply(409, {'error': 'Another browser saved newer records. Export local changes before reloading.'})
                db.execute('INSERT OR REPLACE INTO state VALUES (1, ?, ?)', (revision + 1, json.dumps(value)))
            return self.reply(200, {'revision': revision + 1})
        except (ValueError, KeyError, TypeError):
            self.reply(400, {'error': 'Invalid maintenance record'})

if __name__ == '__main__':
    if len(PASSWORD) < 16 or PASSWORD == 'CHANGE_ME':
        raise SystemExit('Set POOLSIDE_PASSWORD to a unique password of at least 16 characters.')
    with connect():
        pass
    ThreadingHTTPServer(('0.0.0.0', 8080), Handler).serve_forever()
