import base64
import importlib.util
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import io
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.request import Request, urlopen
from urllib.error import HTTPError

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
        cls.upstream=ThreadingHTTPServer(('127.0.0.1',0),FakeBoard)
        app.UPSTREAM='http://127.0.0.1:'+str(cls.upstream.server_port)
        cls.http=ThreadingHTTPServer(('127.0.0.1',0),app.Handler)
        cls.url='http://127.0.0.1:'+str(cls.http.server_port)
        for server in [cls.http,cls.upstream]: threading.Thread(target=server.serve_forever,daemon=True).start()
    @classmethod
    def tearDownClass(cls):
        for server in [cls.http,cls.upstream]: server.shutdown();server.server_close()
        cls.tmp.cleanup()
    def request(self,path,method='GET',body=None,auth=True,write=True):
        headers={}
        if auth: headers['Authorization']='Basic '+base64.b64encode(b'poolside:a-test-password-only').decode()
        if write: headers['X-Poolside-Write']='1'
        req=Request(self.url+path,data=json.dumps(body).encode() if body is not None else None,headers=headers,method=method)
        try:
            with urlopen(req) as r:return r.status,json.load(r)
        except HTTPError as e:return e.code,None
    def test_auth_required(self): self.assertEqual(self.request('/api/state',auth=False)[0],401)
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
            req=Request(self.url+path,headers={'Authorization':'Basic '+base64.b64encode(b'poolside:a-test-password-only').decode()})
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
