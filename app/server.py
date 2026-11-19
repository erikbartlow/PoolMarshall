"""Single-owner, private-network dashboard and read-only AqualinkD status bridge."""
import hmac
import json
import os
from pathlib import Path
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import urlopen, Request
from urllib.parse import urlparse
import time
import secrets
import threading
from http.cookies import SimpleCookie, CookieError
from urllib.error import URLError

WEATHER_CACHE = {}
DB = os.environ.get('DB_PATH', '/data/poolside.db')
PASSWORD = os.environ.get('POOLSIDE_PASSWORD', '')
CONTROL_ENABLED = os.environ.get('POOL_CONTROL_ENABLED', 'false').lower() == 'true'
UPSTREAM = os.environ.get('AQUALINKD_URL', 'http://aqualinkd:80').rstrip('/')
SESSIONS = {}
LOGIN_FAILURES = {}
AUTH_LOCK = threading.Lock()
SESSION_SECONDS = 12 * 60 * 60
VERSION = Path(__file__).with_name('VERSION').read_text().strip()

def connect():
    db = sqlite3.connect(DB, timeout=10)
    db.execute('CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY CHECK(id=1), revision INTEGER NOT NULL, payload TEXT NOT NULL)')
    return db

class Handler(BaseHTTPRequestHandler):
    def page(self, filename):
        return Path(__file__).with_name(filename).read_bytes().replace(b'{{VERSION}}', VERSION.encode())

    def session_token(self):
        try:
            cookie = SimpleCookie(self.headers.get('Cookie', ''))
            return cookie['poolmarshall_session'].value if 'poolmarshall_session' in cookie else ''
        except CookieError:
            return ''

    def session_valid(self):
        token = self.session_token()
        with AUTH_LOCK:
            expires = SESSIONS.get(token, 0)
            if expires <= time.time():
                SESSIONS.pop(token, None)
                return False
        return True

    def session_cookie(self, token='', age=0):
        secure = '; Secure' if self.headers.get('X-Forwarded-Proto', '').lower() == 'https' else ''
        return f'poolmarshall_session={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age={age}{secure}'

    def redirect(self, target):
        self.send_response(303)
        self.send_header('Location', target)
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', '0')
        self.end_headers()

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
        if self.session_valid():
            return True
        self.reply(401, {'error': 'Sign in to continue.'})
        return False

    def do_GET(self):
        if self.path == '/healthz':
            return self.reply(200, {'ok': True})
        if self.path == '/login':
            if self.session_valid():
                return self.redirect('/')
            return self.reply(200, self.page('login.html'), 'text/html; charset=utf-8')
        if self.path in ('/poolside-icon.png', '/favicon.png'):
            return self.reply(200, Path(__file__).with_name(self.path[1:]).read_bytes(), 'image/png')
        if self.path == '/' and not self.session_valid():
            return self.redirect('/login')
        if not self.authorized():
            return
        if self.path == '/':
            return self.reply(200, self.page('index.html'), 'text/html; charset=utf-8')
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
        if self.path in ('/api/login', '/api/logout'):
            # A custom header prevents cross-origin forms from creating or ending sessions.
            if self.headers.get('X-Poolside-Write') != '1':
                return self.reply(403, {'error': 'Request not permitted'})
            if self.path == '/api/logout':
                with AUTH_LOCK:
                    SESSIONS.pop(self.session_token(), None)
                self.send_response(204)
                self.send_header('Set-Cookie', self.session_cookie())
                self.send_header('Cache-Control', 'no-store')
                self.send_header('Content-Length', '0')
                self.end_headers()
                return
            now = time.time()
            # Rate limiting uses the socket peer, not spoofable forwarded IP headers.
            peer = self.client_address[0]
            with AUTH_LOCK:
                for address in list(LOGIN_FAILURES):
                    LOGIN_FAILURES[address] = [t for t in LOGIN_FAILURES[address] if now - t < 60]
                    if not LOGIN_FAILURES[address]:
                        del LOGIN_FAILURES[address]
                if len(LOGIN_FAILURES.get(peer, [])) >= 8:
                    return self.reply(429, {'error': 'Too many attempts. Wait a minute and try again.'})
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if length < 1 or length > 4096:
                    raise ValueError()
                body = json.loads(self.rfile.read(length))
                user, password = body['username'], body['password']
                if not isinstance(user, str) or not isinstance(password, str):
                    raise ValueError()
            except (ValueError, KeyError, TypeError):
                return self.reply(400, {'error': 'Enter your username and password.'})
            valid_password = hmac.compare_digest(password.encode(), PASSWORD.encode())
            if user != 'poolside' or not valid_password:
                with AUTH_LOCK:
                    LOGIN_FAILURES.setdefault(peer, []).append(now)
                return self.reply(401, {'error': 'Username or password is incorrect.'})
            token = secrets.token_urlsafe(32)
            with AUTH_LOCK:
                for old, expires in list(SESSIONS.items()):
                    if expires <= now:
                        del SESSIONS[old]
                if len(SESSIONS) >= 1024:
                    return self.reply(503, {'error': 'Please try signing in again later.'})
                SESSIONS.pop(self.session_token(), None)
                SESSIONS[token] = now + SESSION_SECONDS
                LOGIN_FAILURES.pop(peer, None)
            self.send_response(204)
            self.send_header('Set-Cookie', self.session_cookie(token, SESSION_SECONDS))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Length', '0')
            self.end_headers()
            return
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
