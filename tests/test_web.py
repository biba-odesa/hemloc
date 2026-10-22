"""ASGI permission tests, enabled when local optional dependencies are installed."""

from dataclasses import replace
import importlib.util
from pathlib import Path
import tempfile
import unittest

AVAILABLE = all(importlib.util.find_spec(m) for m in ('fastapi', 'httpx', 'argon2'))


@unittest.skipUnless(AVAILABLE, 'FastAPI, HTTPX and Argon2 dependencies are unavailable')
class WebTests(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        from hemlock.auth import password_hash
        from hemlock.config import Config
        from hemlock.domain import Actor
        from hemlock.service import Service
        from hemlock.store import Store
        from hemlock.web import create_app
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = Config(database=str(Path(self.tmp.name)/'a.sqlite'), tls=False, protected_asns=(), node_id='a', peer_node_id='b',metadata_enabled=False)
        self.store = Store(self.cfg)
        service = Service(self.store)
        admin = Actor('admin', 'admin')
        self.password = 'Test-password-12345'
        hashed = password_hash(self.password)
        service.save_user(admin, 'admin', role='admin', password_hash=hashed)
        service.save_user(admin, 'guest', role='guest', password_hash=hashed)
        self.client = TestClient(create_app(self.cfg, adapter=object(), background=False), client=('192.0.2.100',12345))
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.tmp.cleanup()

    def login(self, login='admin', client=None):
        client = client or self.client
        result = client.post('/api/login', json={'login':login, 'password':self.password})
        self.assertEqual(result.status_code, 200)
        return {'x-csrf-token':result.json()['csrf']}

    def test_running_backend_identity_is_authenticated_and_available_to_guest(self):
        from unittest.mock import patch
        self.assertNotEqual(self.client.get('/api/me').status_code,200)
        self.login('guest')
        identity={'version':'9.8.7','build_commit':'a'*40}
        with patch('hemlock.installed.application_identity',return_value=identity):
            response=self.client.get('/api/me')
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()['application'],identity)

    def test_history_tabs_are_server_side_authorized_with_filtered_counts(self):
        headers = self.login()
        self.client.post('/api/rules/manual', json={'value':'192.0.2.99','comment':'visible'}, headers=headers)
        self.client.get('/missing-unknown-path?secret=do-not-store')
        for category in ('blocklist','users_access','errors_security'):
            self.assertGreater(self.client.get('/api/history',params={'category':category}).json()['total'],0)
        self.client.post('/api/logout',headers=headers)
        self.login('guest')
        for endpoint in ('history','audit'):
            for category in ('users_access','errors_security','unknown'):
                response=self.client.get('/api/'+endpoint,params={'category':category,'q':'admin'})
                self.assertEqual(response.status_code,403)
                self.assertNotIn('total',response.json())
            data=self.client.get('/api/'+endpoint,params={'q':'visible'}).json()
            self.assertEqual(data['total'],1)
        self.assertEqual(self.client.get('/api/login-history',params={'login':'admin'}).status_code,403)
        self.assertEqual(len(self.client.get('/api/login-history').json()['items']),1)
        self.assertNotIn('do-not-store',str(self.store.audit_history()))

    def test_batch_http_limits_metadata_and_session_expiry_contract(self):
        from unittest.mock import patch
        self.assertEqual(self.client.get('/api/session').json(),{'authenticated':False})
        self.assertEqual(self.client.get('/api/rules').status_code,403)
        headers=self.login()
        self.assertTrue(self.client.get('/api/session').json()['authenticated'])
        with patch.object(self.client.app.state.metadata,'origins',side_effect=RuntimeError('Unavailable')) as metadata:
            result=self.client.post('/api/rules/manual-batch',json={'value':'192.0.2.1,2001:db8::1\n10.1.1.1,broken,192.0.2.1/32','comment':'shared'},headers=headers)
            metadata.assert_not_called()
        self.assertEqual(result.status_code,200)
        self.assertEqual((result.json()['added'],result.json()['skipped'],result.json()['invalid']),(2,1,2))
        before=len(self.store.list('rule'))
        oversized=','.join('192.0.2.2' for _ in range(1001))
        response=self.client.post('/api/rules/manual-batch',json={'value':oversized},headers=headers)
        self.assertEqual(response.status_code,422);self.assertIn('1000',response.json()['error'])
        response=self.client.post('/api/rules/manual-batch',content=b'x'*(self.cfg.request_max_bytes+1),headers={**headers,'content-type':'application/json'})
        self.assertEqual(response.status_code,413);self.assertEqual(len(self.store.list('rule')),before)
        preview=self.client.post('/api/coverage/batch',json={'value':'192.0.2.1,2001:db8::1'},headers=headers)
        self.assertEqual(preview.status_code,200)
        with self.store.transaction() as db:db.execute('UPDATE sessions SET expires=0')
        self.assertEqual(self.client.get('/api/session').json(),{'authenticated':False})
        self.assertTrue(self.client.get('/api/routes').json()['session_required'])

    def test_admin_validation_does_not_feed_suspicion_but_anonymous_scan_does(self):
        from dataclasses import replace
        from hemlock.notifications import Notifications
        from hemlock.store import Store
        cfg=replace(self.cfg,notifications_enabled=True,suspicious_threshold=2)
        notifier=Notifications(Store(cfg))
        self.client.app.state.store.notifications=notifier
        headers=self.login()
        for _ in range(4):
            self.assertEqual(self.client.post('/api/rules/manual-batch',json={'value':''},headers=headers).status_code,422)
        for _ in range(3):
            self.assertEqual(self.client.post('/api/rules/manual',json={'value':'10.1.1.1'},headers=headers).status_code,403)
        self.assertEqual(notifier.queue.qsize(),0)
        self.assertEqual(len(notifier.sources),0)
        self.client.cookies.clear()
        for _ in range(2):self.client.get('/missing')
        self.assertEqual(notifier.queue.qsize(),1)

    def test_unconfigured_replication_is_explicit_without_contacting_peer(self):
        self.login()
        response = self.client.get('/api/observation')
        self.assertEqual(response.json()['replication']['status'], 'not_configured')
        self.assertFalse(response.json()['replicated'])

    def test_password_create_reset_change_policy_and_boundaries(self):
        from hemlock.auth import password_verify
        headers = self.login()
        for value in ('abcd1','a'+'8'*1024):
            self.assertEqual(self.client.put('/api/users/numeric',json={'role':'guest','password':value},headers=headers).status_code,422)
            self.assertEqual(self.client.post('/api/password',json={'current_password':self.password,'new_password':value},headers=headers).status_code,422)
        for value in ('123456','abcdef','ABCDEF','!!!!!!'):
            self.assertEqual(self.client.put('/api/users/numeric',json={'role':'guest','password':value},headers=headers).status_code,422)
            self.assertEqual(self.client.post('/api/password',json={'current_password':self.password,'new_password':value},headers=headers).status_code,422)
        for value in ('abcde1','a'+'8'*1023):
            response = self.client.put('/api/users/numeric',json={'role':'guest','password':value},headers=headers)
            self.assertEqual(response.status_code,200)
            self.assertTrue(password_verify(self.store.get('user','numeric')['password_hash'],value))
        response = self.client.post('/api/login',json={'login':'numeric','password':'a'+'8'*1023})
        self.assertEqual(response.status_code,200)
        csrf = {'x-csrf-token':response.json()['csrf']}
        response = self.client.post('/api/password',json={'current_password':'a'+'8'*1023,'new_password':'ABCDE2'},headers=csrf)
        self.assertEqual(response.status_code,200)
        self.assertEqual(self.client.get('/api/me').status_code,403)
        self.assertEqual(self.client.post('/api/login',json={'login':'numeric','password':'ABCDE2'}).status_code,200)

    def test_duplicate_conflicts_and_clamped_pagination(self):
        headers=self.login()
        for value,other,kind in [('AS123','123','asn'),('192.0.2.1','192.0.2.1/32','manual'),('2001:db8::1','2001:0db8:0:0::1/128','manual')]:
            first=self.client.post('/api/rules/'+kind,json={'value':value},headers=headers)
            self.assertEqual(first.status_code,200)
            duplicate=self.client.post('/api/rules/'+kind,json={'value':other},headers=headers)
            self.assertEqual(duplicate.status_code,409)
            self.assertEqual(duplicate.json()['existing_rule_id'],first.json()['rule']['id'])
        for endpoint in ('rule-cards','routes','history','users'):
            page=self.client.get('/api/'+endpoint+'?size=1&page_number=9999').json()
            self.assertEqual(page['page'],page['total'])
            self.assertEqual(len(page['items']),1)
            empty=self.client.get('/api/'+endpoint+'?q=zzzz-no-match').json()
            self.assertEqual((empty['total'],empty['page'],empty['items']),(0,1,[]))

    def test_read_only_presentation_endpoints_are_paged_and_do_not_modify_documents(self):
        headers=self.login()
        self.assertEqual(self.client.post('/api/rules/manual',json={'value':'192.0.2.1','comment':'first reason'},headers=headers).status_code,200)
        from hemlock.service import Service
        from hemlock.domain import Actor
        service=Service(self.store);actor=Actor('admin','admin')
        other=service.add_asn(actor,64501,'second reason')
        service.update_asn(actor,other['id'],['192.0.2.1/32'])
        before=self.store.snapshot()
        result=self.client.get('/api/dashboard').json()
        self.assertIsNone(result['blocked'])
        self.assertEqual(result['required']['total'],1)
        page=self.client.get('/api/routes?ip=192.0.2.1&size=1').json()
        self.assertEqual((page['total'],len(page['items'])),(1,1))
        self.assertEqual(len(page['items'][0]['sources']),2)
        self.assertEqual(len(self.client.get('/api/route-detail?prefix=192.0.2.1').json()['sources']),2)
        cards=self.client.get('/api/rule-cards?size=1').json()
        self.assertEqual(cards['total'],2)
        self.assertNotIn('prefixes',cards['items'][0])
        identity=self.client.get('/api/rule-cards?kind=manual').json()['items'][0]['id']
        self.assertEqual(self.client.get(f'/api/rules/{identity}/prefixes?size=1').json()['items'],['192.0.2.1/32'])
        history=self.client.get('/api/history?size=1').json()
        self.assertEqual(len(history['items']),1)
        self.assertNotIn('id',history['items'][0])
        self.assertEqual(self.store.snapshot(),before)
        self.assertEqual(self.client.get('/api/routes?size=101').status_code,422)

    def test_argon2_and_http_cookie(self):
        from hemlock.auth import password_verify
        self.login()
        self.assertTrue(password_verify(self.store.get('user', 'admin')['password_hash'], self.password))
        self.assertFalse(next(c for c in self.client.cookies.jar if c.name == 'hemloc_session').secure)
        response = self.client.get('/api/users')
        self.assertNotIn('password_hash', response.text)
        self.assertEqual(response.status_code, 200)

    def test_csrf_and_cross_origin(self):
        headers = self.login()
        self.assertEqual(self.client.post('/api/rules/manual', json={'value':'192.0.2.1'}).status_code, 403)
        self.assertEqual(self.client.post('/api/rules/manual', json={'value':'192.0.2.1'},headers={'x-csrf-token':b'\xff'}).status_code,403)
        self.assertEqual(self.client.post('/api/rules/manual', json={'value':'192.0.2.1'}, headers={**headers, 'origin':'https://attacker'}).status_code, 403)
        self.assertEqual(self.client.post('/api/rules/manual', json={'value':'192.0.2.1'}, headers=headers).status_code, 200)

    def test_guest_denied_and_comment_never_rendered_as_html(self):
        headers = self.login('guest')
        self.assertEqual(self.client.post('/api/rules/asn', json={'value':'64500'}, headers=headers).status_code, 403)
        self.assertEqual(self.client.put('/api/users/hacker', json={'role':'admin','password':self.password}, headers=headers).status_code, 403)
        self.assertEqual(self.client.get('/api/observation').status_code, 200)
        self.assertNotIn('innerHTML', (Path(__file__).parents[1]/'hemlock/static/app.js').read_text())

    def test_slave_denies_all_mutation_paths_and_revokes_after_replication(self):
        from fastapi.testclient import TestClient
        from hemlock.web import create_app
        from hemlock.store import Store
        slave_cfg = replace(self.cfg, database=str(Path(self.tmp.name)/'b.sqlite'), node_id='b', peer_node_id='a', role='slave')
        slave = Store(slave_cfg)
        slave.install_snapshot(self.store.snapshot())
        with TestClient(create_app(slave_cfg, adapter=object(), background=False)) as client:
            headers = self.login(client=client)
            for path, body in [('/api/rules/manual',{'value':'192.0.2.1'}),('/api/rules/asn',{'value':'64500'}),('/api/password',{'current_password':self.password,'new_password':self.password+'x'})]:
                self.assertEqual(client.post(path,json=body,headers=headers).status_code,403)
            self.assertEqual(client.put('/api/users/other',json={'role':'admin','password':self.password},headers=headers).status_code,403)
            master_headers = self.login()
            self.client.put('/api/users/admin',json={'enabled':False},headers=master_headers)
            slave.apply_events(self.store.events(slave.info()['history'],slave.info()['sequence']))
            self.assertEqual(client.get('/api/me').status_code,403)

    def test_validation_does_not_echo_password(self):
        response = self.client.post('/api/login',json={'login':'admin','password':'secret-value','extra':True})
        self.assertEqual(response.status_code,422)
        self.assertNotIn('secret-value',response.text)

    def test_failure_audit_covers_validation_csrf_denial_and_exceptions_once(self):
        from unittest.mock import patch
        from hemlock.store import encode
        headers = self.login()
        before = len(self.store.audit_history())
        response = self.client.post('/api/rules/manual',json={'value':'192.0.2.1'})
        self.assertEqual(response.status_code,403)
        self.assertEqual(len(self.store.audit_history()),before+1)
        response = self.client.put('/api/users/test',json={'password':'secret-value','invalid':'secret-value'},headers=headers)
        self.assertEqual(response.status_code,422)
        with patch.object(self.client.app.state.service,'routes',side_effect=RuntimeError('sensitive-exception')):
            response = self.client.get('/api/observation')
        self.assertEqual(response.status_code,500)
        self.assertNotIn('sensitive-exception',response.text)
        audit = encode(self.store.audit_history())
        self.assertNotIn('secret-value',audit)
        self.assertNotIn('sensitive-exception',audit)
        self.assertTrue(any(a['result']=='failed' for a in self.store.audit_history()))

    def test_ip_search_returns_every_rule_and_host_bits_error_is_readable(self):
        headers = self.login()
        for value in ('192.0.2.0/24','192.0.2.1'):
            self.assertEqual(self.client.post('/api/rules/manual',json={'value':value,'comment':'<script>text</script>'},headers=headers).status_code,200)
        response = self.client.get('/api/observation?ip=192.0.2.1')
        self.assertEqual(len(response.json()['matches']),2)
        invalid = self.client.post('/api/rules/manual',json={'value':'192.0.2.1/24'},headers=headers)
        self.assertEqual(invalid.status_code,422)
        self.assertIn('192.0.2.0/24',invalid.json()['error'])


if __name__ == '__main__':
    unittest.main()
