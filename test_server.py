import importlib.util
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
import io
import time
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from http.cookiejar import CookieJar
from urllib.request import build_opener, HTTPCookieProcessor

spec = importlib.util.spec_from_file_location('server', Path(__file__).parent/'app/server.py')
app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)

class FakeBoard(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != '/api/status':
            self.send_error(404); return
        payload=b'{"status":"Connecting"}'
        self.send_response(200); self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload)
    def log_message(self,*args): pass

class Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory(); app.DB=str(Path(cls.tmp.name)/'state.db');app.PASSWORD='a-test-password-only'
        cls.signer=ec.generate_private_key(ec.SECP256R1())
        app.LICENSE_PUBLIC_KEY=cls.signer.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        app.license_status(app.licensing.issue(cls.signer, 'Test owner', app.VERSION))
        cls.upstream=ThreadingHTTPServer(('127.0.0.1',0),FakeBoard)
        app.UPSTREAM='http://127.0.0.1:'+str(cls.upstream.server_port)
        cls.http=ThreadingHTTPServer(('127.0.0.1',0),app.Handler)
        cls.url='http://127.0.0.1:'+str(cls.http.server_port)
        app.SESSIONS['test-api-session']=time.time()+app.SESSION_SECONDS
        for server in [cls.http,cls.upstream]: threading.Thread(target=server.serve_forever,daemon=True).start()
    @classmethod
    def tearDownClass(cls):
        for server in [cls.http,cls.upstream]: server.shutdown();server.server_close()
        cls.tmp.cleanup()
    def setUp(self):
        app.SESSIONS['test-api-session']=time.time()+app.SESSION_SECONDS

    def request(self,path,method='GET',body=None,auth=True,write=True):
        headers={}
        if auth: headers['Cookie']='poolmarshall_session=test-api-session'
        if write: headers['X-Poolside-Write']='1'
        req=Request(self.url+path,data=json.dumps(body).encode() if body is not None else None,headers=headers,method=method)
        try:
            with urlopen(req) as r:return r.status,json.load(r)
        except HTTPError as e:return e.code,None
    def test_license_activation_and_gating(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(app, 'DB', str(Path(folder)/'license.db')), patch.dict(app.os.environ, {'POOLMARSHALL_LICENSE_KEY': ''}):
            self.assertEqual(self.request('/api/license', auth=False)[0], 401)
            self.assertEqual(self.request('/api/license')[1]['isValid'], False)
            for path, method, body in [('/api/state','GET',None),('/api/weather','GET',None),('/api/controller-status','GET',None),('/api/state','PUT',{}),('/api/command','POST',{})]:
                self.assertEqual(self.request(path, method, body)[0], 402)
            req=Request(self.url+'/',headers={'Cookie':'poolmarshall_session=test-api-session'})
            with urlopen(req) as response:
                self.assertTrue(response.url.endswith('/license'))
                self.assertIn(b'Activate license', response.read())
            self.assertEqual(self.request('/api/license','PUT',{'key':'invalid'})[0],400)
            key=app.licensing.issue(self.signer,'Owner',app.VERSION)
            self.assertEqual(self.request('/api/license','PUT',{'key':key},write=False)[0],403)
            status,value=self.request('/api/license','PUT',{'key':key})
            self.assertEqual(status,200);self.assertTrue(value['isValid'])
            self.assertNotIn('key',value)
            self.assertEqual(self.request('/api/state')[0],200)
            self.assertTrue(app.license_status()['isValid'])

    def test_trial_expiration_and_replacement(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(app, 'DB', str(Path(folder)/'trial.db')):
            trial=app.licensing.issue(self.signer,'Trial',app.VERSION,30)
            now=time.time()
            with patch.object(app.time,'time',return_value=now):
                self.assertTrue(app.license_status(trial)['isValid'])
            with patch.object(app.time,'time',return_value=now+30*86400):
                self.assertFalse(app.license_status()['isValid'])
                replacement=app.licensing.issue(self.signer,'Another trial',app.VERSION,30)
                self.assertFalse(app.license_status(replacement)['isValid'])
                app.SESSIONS['test-api-session']=now+31*86400
                self.assertEqual(self.request('/api/state')[0],402)
                self.assertTrue(app.license_status(app.licensing.issue(self.signer,'Paid',app.VERSION))['isValid'])
            with patch.object(app.time,'time',return_value=now-1):
                self.assertFalse(app.license_status(trial)['isValid'])

    def test_license_signature_and_major_version(self):
        licensing=app.licensing
        key=licensing.issue(self.signer,'Owner','1.0.0')
        grant=licensing.verify(key,app.LICENSE_PUBLIC_KEY)
        self.assertTrue(licensing.covers(grant,'1.99.999'))
        self.assertFalse(licensing.covers(grant,'2.0.0'))
        for invalid in [None, '', key.replace('PM1','SW1'), key+'x', 'PM1.e30.AAAA', 'x'*5000, 42]:
            self.assertIsNone(licensing.verify(invalid,app.LICENSE_PUBLIC_KEY))
        parts=key.split('.')
        payload=json.loads(licensing.decode(parts[1]));payload['Customer']='Tampered'
        parts[1]=licensing.encode(json.dumps(payload).encode())
        self.assertIsNone(licensing.verify('.'.join(parts),app.LICENSE_PUBLIC_KEY))
        other=ec.generate_private_key(ec.SECP256R1())
        self.assertIsNone(licensing.verify(licensing.issue(other,'Other','1.0.0'),app.LICENSE_PUBLIC_KEY))
        with tempfile.TemporaryDirectory() as folder, patch.object(app,'DB',str(Path(folder)/'version.db')), patch.object(app,'VERSION','2.0.0'):
            with self.assertRaises(ValueError):app.license_status(key)

    def test_auth_required(self): self.assertEqual(self.request('/api/state',auth=False)[0],401)
    def browser(self):
        return build_opener(HTTPCookieProcessor(CookieJar()))
    def login(self, browser, password='a-test-password-only', write=True):
        headers={'Content-Type':'application/json'}
        if write: headers['X-Poolside-Write']='1'
        return browser.open(Request(self.url+'/api/login',data=json.dumps({'username':'poolside','password':password}).encode(),headers=headers))
    def test_login_page_replaces_browser_prompt(self):
        with urlopen(self.url+'/') as response:
            self.assertTrue(response.url.endswith('/login'))
            html=response.read()
            self.assertIn(b'autocomplete="current-password"',html)
            self.assertIn(('PoolMarshall v'+app.VERSION).encode(),html)
            self.assertIsNone(response.headers.get('WWW-Authenticate'))
        with self.assertRaises(HTTPError) as error:
            urlopen(self.url+'/api/state')
        self.assertIsNone(error.exception.headers.get('WWW-Authenticate'))
        error.exception.close()
    def test_session_login_logout_and_expiry(self):
        browser=self.browser()
        with self.login(browser) as response:
            cookie=response.headers['Set-Cookie']
            self.assertIn('HttpOnly',cookie);self.assertIn('SameSite=Lax',cookie)
            token=cookie.split(';')[0].split('=',1)[1]
        with browser.open(self.url+'/api/state') as response:self.assertEqual(response.status,200)
        with browser.open(self.url+'/') as response:self.assertIn(('PoolMarshall v'+app.VERSION).encode(),response.read())
        with browser.open(Request(self.url+'/api/logout',data=b'',headers={'X-Poolside-Write':'1'})) as response:self.assertEqual(response.status,204)
        with self.assertRaises(HTTPError) as error:
            urlopen(Request(self.url+'/api/state',headers={'Cookie':'poolmarshall_session='+token}))
        self.assertEqual(error.exception.code,401);error.exception.close()
        with self.login(browser) as response:token=response.headers['Set-Cookie'].split(';')[0].split('=',1)[1]
        app.SESSIONS[token]=0
        with self.assertRaises(HTTPError) as error:browser.open(self.url+'/api/state')
        self.assertEqual(error.exception.code,401);error.exception.close()
    def test_login_guards_and_secure_cookie(self):
        browser=self.browser()
        for password,write,status in [('wrong',True,401),('a-test-password-only',False,403)]:
            with self.assertRaises(HTTPError) as error:self.login(browser,password,write)
            self.assertEqual(error.exception.code,status);error.exception.close()
        request=Request(self.url+'/api/login',data=json.dumps({'username':'poolside','password':'a-test-password-only'}).encode(),headers={'X-Poolside-Write':'1','X-Forwarded-Proto':'https'})
        with urlopen(request) as response:self.assertIn('; Secure',response.headers['Set-Cookie'])
    def test_login_rate_limit(self):
        browser=self.browser()
        try:
            app.LOGIN_FAILURES.clear()
            for _ in range(8):
                with self.assertRaises(HTTPError) as error:self.login(browser,'wrong')
                self.assertEqual(error.exception.code,401);error.exception.close()
            with self.assertRaises(HTTPError) as error:self.login(browser)
            self.assertEqual(error.exception.code,429);error.exception.close()
        finally:app.LOGIN_FAILURES.clear()
    def test_persistence_and_conflicts(self):
        payload={'tasks':{},'logs':[{'kind':'Water test','ph':'7.4'}],'findings':[],'settings':{},'care':{'active':'main','profiles':[{'id':'main','gallons':18000}],'products':[]}}
        self.assertEqual(self.request('/api/state','PUT',{'revision':0,'data':payload})[0],200)
        status,record=self.request('/api/state');self.assertEqual(record['data'],payload);self.assertEqual(record['revision'],1)
        self.assertEqual(self.request('/api/state','PUT',{'revision':0,'data':payload})[0],409)
        with app.connect() as db:self.assertEqual(json.loads(db.execute('SELECT payload FROM state').fetchone()[0]),payload)
    def test_write_guard(self): self.assertEqual(self.request('/api/state','PUT',{},write=False)[0],403)
    def test_bad_record(self): self.assertEqual(self.request('/api/state','PUT',{'revision':0,'data':{}})[0],400)
    def test_bridge_does_not_claim_panel_connection(self):
        status,record=self.request('/api/controller-status');self.assertEqual(status,200);self.assertTrue(record['httpAvailable']);self.assertIn('Unverified',record['panelConnection']);self.assertEqual(record['status']['status'],'Connecting')
    def test_commands_locked_by_default(self):
        status,_=self.request('/api/command','POST',{'circuit':'Filter_Pump','value':1})
        self.assertEqual(status,403)
    def test_unsupported_command_blocked(self):
        app.CONTROL_ENABLED=True
        try:self.assertEqual(self.request('/api/command','POST',{'circuit':'Pool_Heater','value':1})[0],400)
        finally:app.CONTROL_ENABLED=False
    def test_unverified_panel_blocks_command(self):
        app.CONTROL_ENABLED=True
        try:self.assertEqual(self.request('/api/command','POST',{'circuit':'Filter_Pump','value':1})[0],409)
        finally:app.CONTROL_ENABLED=False
    def test_feature_assets_are_served(self):
        for path,mime in [('/features.js','text/javascript'),('/pool-math.js','text/javascript'),('/sw.js','text/javascript')]:
            req=Request(self.url+path,headers={'Cookie':'poolmarshall_session=test-api-session'})
            with urlopen(req) as r:
                self.assertEqual(r.status,200);self.assertIn(mime,r.headers['Content-Type']);self.assertGreater(len(r.read()),100)
    def test_weather_uses_fixed_host_and_cache(self):
        app.WEATHER_CACHE.clear()
        point=io.BytesIO(b'{"properties":{"forecast":"https://api.weather.gov/gridpoints/HGX/1,1/forecast"}}')
        forecast=io.BytesIO(b'{"properties":{"periods":[{"name":"Today","temperature":80,"temperatureUnit":"F","shortForecast":"Sunny"}]}}')
        with patch.object(app,'urlopen',side_effect=[point,forecast]) as upstream:
            code,value=self.request('/api/weather');self.assertEqual(code,200);self.assertEqual(value['periods'][0]['name'],'Today')
            self.assertEqual(self.request('/api/weather')[0],200);self.assertEqual(upstream.call_count,2)
        app.WEATHER_CACHE.clear()
    def test_weather_rejects_non_nws_forecast_url(self):
        point=io.BytesIO(b'{"properties":{"forecast":"http://127.0.0.1/private"}}')
        with patch.object(app,'urlopen',return_value=point) as upstream:
            self.assertEqual(self.request('/api/weather')[0],503);self.assertEqual(upstream.call_count,1)
    def test_no_command_proxy(self): self.assertEqual(self.request('/api/Filter_Pump/set?value=1')[0],404)

if __name__=='__main__': unittest.main()
