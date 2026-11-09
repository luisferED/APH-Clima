"""Local isolated acceptance tests. Never touches the original database or MET."""
import base64
import hashlib
import http.client
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server
from scripts.db_admin import backup, inspect

class Acceptance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        server.DB_FILE = Path(cls.temp.name) / 'live.db'
        backup(Path('tiempo_aph.db'), server.DB_FILE, True)
        server.DB_READY = False
        server.init_db()
        server.OPERATOR_USER = 'test'
        salt = b'1234567890123456'
        server.PASSWORD_HASH = '600000:' + salt.hex() + ':' + hashlib.pbkdf2_hmac('sha256', b'test-only-password', salt, 600000).hex()
        server.PUBLIC_ORIGIN = 'https://aph.test'
        cls.http = server.ReliableThreadingHTTPServer(('127.0.0.1', 0), server.APHHandler)
        threading.Thread(target=cls.http.serve_forever, daemon=True).start()
        cls.port = cls.http.server_address[1]
        cls.auth = {'Authorization': 'Basic ' + base64.b64encode(b'test:test-only-password').decode(), 'Origin': server.PUBLIC_ORIGIN, 'X-APH-Request': 'operator', 'Content-Type': 'application/json'}

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown(); cls.http.server_close(); cls.temp.cleanup()

    def request(self, path, method='GET', body=None, headers=None):
        c = http.client.HTTPConnection('127.0.0.1', self.port, timeout=5)
        c.request(method, path, body=body, headers=headers or {})
        r = c.getresponse(); result = (r.status, r.read(), r.headers); c.close(); return result

    def test_static_isolation(self):
        for path in ['/server.py','/tiempo_aph.db','/tiempo_aph.db-wal','/.env','/runtime/','/../server.py','/%2e%2e/server.py','/assets/fonts/../server.py']:
            self.assertEqual(self.request(path)[0],404,path)
            self.assertEqual(self.request(path,'HEAD')[0],404,path)
        self.assertEqual(self.request('/')[0],401)
        self.assertEqual(self.request('/',headers=self.auth)[0],200)

    def test_read_routes(self):
        for path in ['/healthz','/api/state','/api/weather','/output.html','/output.html?view=current','/output.html?view=extended','/weather/local','/weather/local?view=extended']:
            status, body, headers = self.request(path)
            self.assertEqual(status,200,path)
            self.assertIsNone(headers.get('Access-Control-Allow-Origin'))
        html = self.request('/weather/local')[1]
        self.assertIn(b'canvas',html)

    def test_auth_csrf_json(self):
        for path in ['/api/output','/api/state','/api/weather/refresh']:
            self.assertEqual(self.request(path,'POST','{}')[0],401)
            bad = {**self.auth, 'Origin':'https://evil.test'}
            self.assertEqual(self.request(path,'POST','{}',bad)[0],403)
            self.assertEqual(self.request(path,'POST','[1]',self.auth)[0],400)
        self.assertEqual(self.request('/api/state','POST','x'*8193,self.auth)[0],413)

    def test_sse_and_state(self):
        streams=[]
        try:
            for _ in range(2):
                c=http.client.HTTPConnection('127.0.0.1',self.port,timeout=5)
                c.request('GET','/api/events'); r=c.getresponse(); streams.append((c,r))
                self.assertTrue(r.readline().startswith(b'data: ')); r.readline()
            status,body,_=self.request('/api/output','POST',json.dumps({'mode':'weather','weatherCity':'la-paz','weatherView':'extended'}),self.auth)
            self.assertEqual(status,200); self.assertTrue(json.loads(body)['ok'])
            for c,r in streams:
                self.assertEqual(json.loads(r.readline()[6:])['weatherCity'],'la-paz')
        finally:
            for c,r in streams: r.close(); c.close()
        snapshot=Path(self.temp.name)/'snapshot.db'
        backup(server.DB_FILE,snapshot,True)
        self.assertEqual(inspect(snapshot,True)['state'],inspect(server.DB_FILE,True)['state'])
        server.DB_READY=False; server.init_db()
        self.assertEqual(server.read_state()['weatherCity'],'la-paz')
        with self.assertRaises(RuntimeError): backup(snapshot,server.DB_FILE)

    def test_weather_transaction(self):
        from datetime import datetime, timezone, timedelta
        start = datetime.now(timezone(timedelta(hours=-4))).replace(hour=0, minute=0, second=0, microsecond=0)
        series = [{'time': (start+timedelta(hours=i)).isoformat(), 'data': {'instant': {'details': {'air_temperature': 20+i%10, 'wind_speed': 2, 'wind_from_direction': 90}}, 'next_1_hours': {'summary': {'symbol_code':'clearsky_day'}}}} for i in range(120)]
        # Synthetic data exists only in this isolated temporary test DB.
        payloads = [{'properties':{'timeseries':series}} for _ in range(9)]
        with patch.object(server,'fetch_met_norway',return_value=payloads):
            self.assertTrue(server._refresh_weather_cache()['ok'])
        result=inspect(server.DB_FILE,True)
        self.assertEqual((result['cities'],result['forecasts']),(9,36))
        invalid = payloads[:-1]+[{'properties':{'timeseries':[]}}]
        with patch.object(server,'fetch_met_norway',return_value=invalid):
            self.assertFalse(server._refresh_weather_cache()['ok'])
        self.assertEqual(inspect(server.DB_FILE,True),result)

    def test_weather_failure_preserves_data(self):
        before=inspect(server.DB_FILE,True)
        with patch.object(server,'fetch_met_norway',side_effect=RuntimeError('offline')):
            self.assertFalse(server._refresh_weather_cache()['ok'])
        self.assertEqual(before,inspect(server.DB_FILE,True))
        with self.assertRaises(ValueError): server.parse_weather_payloads([])

if __name__ == '__main__': unittest.main(verbosity=2)
