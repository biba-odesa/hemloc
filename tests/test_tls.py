"""Real isolated HTTPS/mTLS peers; no working data, credentials or BGP services."""
from dataclasses import replace
from datetime import datetime,timedelta,timezone
from pathlib import Path
import json
import os
import ssl
import tempfile
import threading
import time
import unittest
from unittest.mock import patch,Mock
from urllib.request import build_opener,ProxyHandler,HTTPSHandler,Request

from cryptography import x509
from cryptography.hazmat.primitives import hashes,serialization
from hemlock.config import Config
from hemlock.domain import Actor,Conflict,Invalid
from hemlock.replication import PeerTransport,Replicator
from hemlock.protocol import REPLICATION_PROTOCOL_VERSION
from hemlock.service import Service
from hemlock.tls import (Trust,ensure_identity,own_info,server_context,refresh_context,discover,
                         Lifecycle,TLSFailure,PinnedConnection)
from hemlock.tls_runtime import make_server
from tools.check_gobgp import port,wait_for

ADMIN=Actor('fixture','admin')


class TLSFiles(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.config=Config(database=str(self.root/'db.sqlite'),tls_mode='pinned',tls_state_dir=str(self.root/'tls'),
                           cert=str(self.root/'tls/identity/server.crt'),key=str(self.root/'tls/identity/server.key'),
                           protected_asns=(),metadata_enabled=False)

    def expire(self,cfg=None):
        cfg=cfg or self.config
        cert=x509.load_pem_x509_certificate(Path(cfg.cert).read_bytes())
        key=serialization.load_pem_private_key(Path(cfg.key).read_bytes(),None)
        now=datetime.now(timezone.utc)
        replacement=(x509.CertificateBuilder().subject_name(cert.subject).issuer_name(cert.issuer).public_key(key.public_key())
                     .serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(days=3)).not_valid_after(now-timedelta(days=1)))
        for extension in cert.extensions:replacement=replacement.add_extension(extension.value,extension.critical)
        Path(cfg.cert).write_bytes(replacement.sign(key,hashes.SHA256()).public_bytes(serialization.Encoding.PEM))

    def test_generation_permissions_existing_and_rotation(self):
        first=ensure_identity(self.config)
        self.assertEqual(first,ensure_identity(self.config))
        for name in (self.config.cert,self.config.key):self.assertEqual(Path(name).stat().st_mode&0o777,0o600)
        self.assertEqual(Path(self.config.cert).parent.stat().st_mode&0o777,0o700)
        old=Path(self.config.key).read_bytes();self.expire();rotated=ensure_identity(self.config)
        self.assertNotEqual(first['fingerprint'],rotated['fingerprint']);self.assertNotEqual(Path(self.config.key).read_bytes(),old)
        self.assertEqual(list(Path(self.config.cert).parent.parent.glob('.*-expired-*')),[])
        self.assertEqual([e['action'] for e in Trust(self.config).read()['events']],['certificate.created','certificate.rotated'])

    def test_partial_corrupt_mismatch_permissions_never_replaced(self):
        ensure_identity(self.config);key=Path(self.config.key);cert=Path(self.config.cert);old=key.read_bytes()
        cert.chmod(0o644)
        with self.assertRaisesRegex(Invalid,'0600'):ensure_identity(self.config)
        self.assertEqual(key.read_bytes(),old);cert.chmod(0o000)
        with self.assertRaisesRegex(Invalid,'0600'):ensure_identity(self.config)
        cert.chmod(0o600)
        content=cert.read_bytes();cert.write_bytes(b'damaged')
        with self.assertRaisesRegex(Invalid,'damaged'):ensure_identity(self.config)
        self.assertEqual(cert.read_bytes(),b'damaged');cert.write_bytes(content)
        other=replace(self.config,tls_state_dir=str(self.root/'other'),cert=str(self.root/'other/identity/cert'),key=str(self.root/'other/identity/key'))
        ensure_identity(other);key.write_bytes(Path(other.key).read_bytes())
        with self.assertRaisesRegex(Invalid,'does not match'):ensure_identity(self.config)
        key.write_bytes(old);cert.unlink()
        with self.assertRaisesRegex(Invalid,'Only one'):ensure_identity(self.config)
        self.assertEqual(key.read_bytes(),old)

    def test_warning_debounce_and_runtime_restart_request(self):
        ensure_identity(self.config);notify=Mock();restart=Mock()
        worker=Lifecycle(self.config,notify,restart)
        info=own_info(self.config)
        with patch('hemlock.tls.time.time',return_value=info['not_after']-86400):worker.step();worker.step()
        self.assertEqual(notify.submit.call_count,1)
        self.expire();worker.step();restart.assert_called_once()
        self.assertTrue(Path(self.config.key).exists())  # Replacement waits until HTTPS stops.

    def test_pending_state_does_not_create_an_audit_per_poll(self):
        import asyncio
        from hemlock.store import Store
        from hemlock.workers import repeat
        store=Store(replace(self.config,database=str(self.root/'pending.sqlite'),tls_mode='legacy_ca',tls=False))
        async def check():
            stop=asyncio.Event();calls=[]
            def pending():
                calls.append(1)
                if len(calls)==2:stop.set()
                raise TLSFailure('peer_approval_required','Peer approval required')
            await repeat(stop,pending,.01,store,'replication')
        asyncio.run(check())
        self.assertEqual(sum(e['action']=='system.error' for e in store.audit_history()),1)


class TLSPair(TLSFiles):
    def setUp(self):
        super().setUp();token=self.root/'token';token.write_text('isolated-fixture-token-'+'x'*40)
        p1,p2=port(),port()
        while p1==p2:p2=port()
        self.a=replace(self.config,node_id='a',peer_node_id='b',port=p1,peer_url=f'https://127.0.0.1:{p2}',token_file=str(token))
        self.b=replace(self.a,node_id='b',peer_node_id='a',role='slave',database=str(self.root/'b.sqlite'),port=p2,peer_url=f'https://127.0.0.1:{p1}',tls_state_dir=str(self.root/'btls'),cert=str(self.root/'btls/identity/server.crt'),key=str(self.root/'btls/identity/server.key'))
        self.servers=[];self.threads=[];self.requests=[]
        self.sa=self.start(self.a);self.sb=self.start(self.b)
        self.ta,self.tb=PeerTransport(self.a),PeerTransport(self.b)
        self.ra,self.rb=Replicator(self.sa.config.app.state.store,self.ta),Replicator(self.sb.config.app.state.store,self.tb)
        Service(self.ra.store).add_manual(ADMIN,'192.0.2.8')

    def start(self,cfg):
        server=make_server(cfg,adapter=object(),background=False)
        @server.config.app.middleware('http')
        async def capture(request,call_next):
            self.requests.append((request.url.path,bool(request.headers.get('authorization')),bool(request.headers.get('cookie'))))
            return await call_next(request)
        thread=threading.Thread(target=server.run);thread.start();self.servers.append(server);self.threads.append(thread)
        def cleanup():
            server.should_exit=True;thread.join(10);self.assertFalse(thread.is_alive())
        self.addCleanup(cleanup);wait_for(lambda:server.started)
        return server

    def approve(self):
        for cfg,server in ((self.a,self.sa),(self.b,self.sb)):
            trust=Trust(cfg);candidate=trust.discover();trust.approve(candidate['fingerprint']);refresh_context(cfg,server.config.ssl)

    def test_mutual_approval_no_credentials_before_and_snapshot(self):
        before=self.rb.store.info()
        with self.assertRaises(TLSFailure):self.rb.step()
        self.assertEqual(self.rb.store.info(),before)
        self.assertTrue(self.requests);self.assertTrue(all(p=='/tls/introduction' and not auth and not cookie for p,auth,cookie in self.requests))
        ca=Trust(self.a).discover();Trust(self.a).approve(ca['fingerprint']);refresh_context(self.a,self.sa.config.ssl)
        with self.assertRaises(TLSFailure):self.ra.step()
        self.assertFalse(any(auth for _,auth,_ in self.requests))
        cb=Trust(self.b).discover();Trust(self.b).approve(cb['fingerprint']);refresh_context(self.b,self.sb.config.ssl)
        self.rb.step();self.ra.step();self.rb.step()
        self.assertEqual(self.ra.store.list('rule'),self.rb.store.list('rule'))
        self.assertEqual(REPLICATION_PROTOCOL_VERSION,3)
        self.assertTrue(any(auth for _,auth,_ in self.requests))
        self.assertTrue(Trust(self.b).pin())
        # Repeated delivery and snapshot do not modify local trust.
        pin=Trust(self.b).read()['pin'];self.rb.step();self.rb.store.install_snapshot(self.ra.store.snapshot())
        self.assertEqual(pin,Trust(self.b).read()['pin'])

    def test_candidate_change_and_explicit_replacement(self):
        trust=Trust(self.a);candidate=trust.discover()
        self.expire(self.b);ensure_identity(self.b)
        # The served certificate still differs from the file until HTTPS reloads: reject introduction.
        with self.assertRaises(TLSFailure):trust.approve(candidate['fingerprint'])
        self.sb.should_exit=True;self.threads[-1].join(10)
        self.sb=self.start(self.b)
        with self.assertRaises(Conflict):trust.approve(candidate['fingerprint'])
        new=trust.discover();trust.approve(new['fingerprint']);self.assertNotEqual(candidate['fingerprint'],new['fingerprint'])

    def test_revoke_direct_endpoint_mtls_and_url_change(self):
        self.approve();self.rb.step()
        token=self.ta.token
        # A valid shared token and claimed node header are insufficient without mTLS.
        context=ssl.create_default_context(cafile=self.b.cert)
        opener=build_opener(ProxyHandler({}),HTTPSHandler(context=context))
        request=Request(self.a.peer_url+'/replication/status',headers={'Authorization':'Bearer '+token,'X-Hemlock-Node':'a','X-Hemlock-Protocol':'3'})
        from urllib.error import HTTPError
        with self.assertRaises(HTTPError) as result:opener.open(request)
        self.assertEqual(result.exception.code,503);result.exception.close()
        # A new URL with the same expected identity/key reuses local approval.
        changed=replace(self.a,peer_url=self.a.peer_url.replace('127.0.0.1','localhost'))
        self.assertEqual(PeerTransport(changed).handshake()['node_id'],'b')
        pin=Trust(self.b).pin();Trust(self.b).revoke(pin['fingerprint'])
        with self.assertRaises(TLSFailure):self.ra.step()
        self.assertEqual(self.rb.store.list('rule'),self.ra.store.list('rule'))

    def test_wrong_expected_identity_and_data_socket_substitution(self):
        self.approve()
        changed=replace(self.a,peer_node_id='different')
        with self.assertRaises(TLSFailure):PeerTransport(changed).handshake()
        # Swap only the actual connection after discovery; connect() must reject SPKI before HTTP.
        other=self.b
        conn=PinnedConnection(self.a,pin=Trust(self.a).pin(),client=True)
        conn.host='127.0.0.1';conn.port=self.a.port
        with self.assertRaises(TLSFailure):conn.connect()
        self.assertIsNone(conn.sock)

    def browser(self,cfg,login='admin'):
        from http.cookiejar import CookieJar
        from urllib.request import HTTPCookieProcessor
        import urllib.error
        context=ssl.create_default_context(cafile=cfg.cert)
        opener=build_opener(ProxyHandler({}),HTTPSHandler(context=context),HTTPCookieProcessor(CookieJar()))
        base=f'https://127.0.0.1:{cfg.port}'
        def call(path,method='GET',body=None,csrf=None):
            headers={'Content-Type':'application/json'}
            if csrf:headers['X-CSRF-Token']=csrf
            request=Request(base+path,data=json.dumps(body).encode() if body is not None else None,headers=headers,method=method)
            with opener.open(request,timeout=10) as response:return json.load(response)
        response=call('/api/login','POST',{'login':login,'password':'Fixture123'})
        return call,response['csrf']

    def test_web_admin_slave_guest_csrf_and_audit(self):
        from hemlock.auth import password_hash
        service=Service(self.ra.store)
        service.save_user(ADMIN,'admin',role='admin',password_hash=password_hash('Fixture123'))
        service.save_user(ADMIN,'guest',role='guest',password_hash=password_hash('Fixture123'))
        self.approve();self.rb.step()
        guest,csrf=self.browser(self.a,'guest')
        admin,admin_csrf=self.browser(self.b)
        self.assertNotIn('events',guest('/api/tls'))
        from urllib.error import HTTPError
        for caller,token in ((guest,csrf),(admin,None)):
            with self.assertRaises(HTTPError) as result:caller('/api/tls/revoke','POST',{'fingerprint':Trust(self.a).pin()['fingerprint']},token)
            self.assertEqual(result.exception.code,403);result.exception.close()
        pin=Trust(self.b).pin();admin('/api/tls/revoke','POST',{'fingerprint':pin['fingerprint']},admin_csrf)
        candidate=admin('/api/tls/discover','POST',{},admin_csrf)
        admin('/api/tls/approve','POST',{'fingerprint':candidate['fingerprint']},admin_csrf)
        self.assertEqual(Trust(self.b).read()['events'][-1]['actor'],'admin')
        self.rb.step()
        self.assertEqual(self.rb.store.info()['role'],'slave')

    def test_key_rotation_pause_reapproval_and_protocol_mismatch(self):
        self.approve();self.rb.step();before=self.rb.store.info()
        self.sb.should_exit=True;self.threads[-1].join(10)
        self.expire(self.b);self.sb=self.start(self.b)
        with self.assertRaises(TLSFailure):self.ra.step()
        self.assertEqual(self.rb.store.info(),before)
        new=Trust(self.a).discover();old=Trust(self.a).pin()
        with self.assertRaises(Conflict):Trust(self.a).approve(new['fingerprint'])
        Trust(self.a).revoke(old['fingerprint']);Trust(self.a).approve(new['fingerprint']);refresh_context(self.a,self.sa.config.ssl)
        self.tb=PeerTransport(self.b);self.rb=Replicator(self.sb.config.app.state.store,self.tb)
        self.rb.step();self.ra.step()
        self.assertEqual(self.ra.store.list('rule'),self.rb.store.list('rule'))
        self.sb.config.app.state.replication_gate.version=4
        from hemlock.protocol import ProtocolFailure
        with self.assertRaises(ProtocolFailure):self.ra.step()
        self.assertEqual(self.ra.store.info()['role'],'master')

    def test_root_cli_without_users_and_corrupt_database(self):
        import subprocess,sys
        from configparser import ConfigParser
        if subprocess.run(['sudo','-n','true'],capture_output=True).returncode:self.skipTest('root CLI test needs authorized sudo')
        cfg=self.a;ini=ConfigParser(interpolation=None)
        ini['node']={'node_id':cfg.node_id,'peer_node_id':cfg.peer_node_id,'role':'slave','database':str(self.root/'damaged.sqlite'),'peer_url':cfg.peer_url,'token_file':cfg.token_file}
        ini['web']={'host':'127.0.0.1','port':str(cfg.port),'tls':'yes','cert':cfg.cert,'key':cfg.key}
        ini['tls']={'mode':'pinned','state_dir':cfg.tls_state_dir}
        path=self.root/'cli.ini'
        with path.open('w') as stream:ini.write(stream)
        damaged=self.root/'damaged.sqlite';damaged.write_bytes(b'not a database');damaged.chmod(0o600)
        def cli(*args):
            run=subprocess.run(['sudo','-n',sys.executable,'-m','hemlock','--config',str(path),*args],capture_output=True,text=True)
            self.assertEqual(run.returncode,0,run.stderr);return json.loads(run.stdout)
        own=cli('tls','self');self.assertEqual(own['fingerprint'],own_info(cfg)['fingerprint'])
        candidate=cli('tls','peer');cli('tls','approve','--fingerprint',candidate['fingerprint'])
        self.assertEqual(damaged.read_bytes(),b'not a database')
        self.assertIsNotNone(cli('tls','trust')['pin'])
        result=cli('database','reinitialize');self.assertTrue(result['dry_run']);self.assertEqual(damaged.read_bytes(),b'not a database')
        result=cli('database','reinitialize','--execute');self.assertEqual(Path(result['backup'],'damaged.sqlite').read_bytes(),b'not a database')
        self.assertIsNotNone(cli('tls','trust')['pin'])
        # Empty slave approval via root CLI is picked up by the periodic TLS step.
        self.assertEqual(self.rb.store.list('user'),[])
        ini['node'].update(node_id=self.b.node_id,peer_node_id=self.b.peer_node_id,database=self.b.database,peer_url=self.b.peer_url)
        ini['web'].update(cert=self.b.cert,key=self.b.key,port=str(self.b.port))
        ini['tls']['state_dir']=self.b.tls_state_dir
        path=self.root/'cli-b.ini'
        with path.open('w') as stream:ini.write(stream)
        peer=cli('tls','peer');cli('tls','approve','--fingerprint',peer['fingerprint'])
        for cfg,server in ((self.a,self.sa),(self.b,self.sb)):
            Lifecycle(cfg,Mock(),Mock(),server.config.ssl).step()
        self.rb.step();self.assertEqual(self.ra.store.list('rule'),self.rb.store.list('rule'))
        self.assertEqual(self.rb.store.list('user'),[])

    def test_tls_pin_survives_promotion_and_demotion(self):
        from hemlock.store import Store
        from hemlock.transition import RoleTransition
        self.approve();self.rb.step();pin=Trust(self.b).pin()
        self.sb.should_exit=True;self.threads[-1].join(10)
        promoted=replace(self.b,role='master')
        promoted_store=Store(promoted)
        self.assertEqual(Trust(promoted).pin(),pin)
        self.assertEqual(len(promoted_store.list('rule')),1)
        empty_daemon=Mock();empty_daemon.drain_for_transition.return_value=None
        RoleTransition(self.b).prepare(empty_daemon)
        slave_store=Store(self.b)
        self.assertEqual(slave_store.list('rule'),[])
        self.assertEqual(Trust(self.b).pin(),pin)

    def test_runtime_expiry_stops_https_before_replacing_pair(self):
        self.approve();self.rb.step()
        self.expire(self.b);key=Path(self.b.key).read_bytes()
        worker=Lifecycle(self.b,Mock(),lambda:setattr(self.sb,'should_exit',True),self.sb.config.ssl)
        worker.step();self.threads[-1].join(10);self.assertFalse(self.threads[-1].is_alive())
        self.assertEqual(Path(self.b.key).read_bytes(),key)
        old=Trust(self.a).pin()['fingerprint'];self.sb=self.start(self.b)
        self.assertNotEqual(own_info(self.b)['fingerprint'],old)
        self.assertNotEqual(Path(self.b.key).read_bytes(),key)
        with self.assertRaises(TLSFailure):self.ra.step()

    def test_unavailable_peer_preserves_trust_and_local_state(self):
        self.approve();self.rb.step();before=self.ra.store.info();pin=Trust(self.a).pin()
        self.sb.should_exit=True;self.threads[-1].join(10)
        with self.assertRaises(TLSFailure):self.ra.step()
        self.assertEqual(Trust(self.a).pin(),pin)
        self.assertEqual(self.ra.store.info(),before)

    def test_recovery_interruption_resumes_without_overwriting_backup(self):
        from hemlock.recovery import reinitialize
        cfg=replace(self.a,role='slave',database=str(self.root/'corrupt.sqlite'),announcements=False)
        path=Path(cfg.database);path.write_bytes(b'corrupt fixture');path.chmod(0o600)
        pin_before=Trust(cfg).read()
        with patch('hemlock.recovery.Store',side_effect=RuntimeError('isolated failure')):
            with self.assertRaises(RuntimeError):reinitialize(cfg,True)
        marker=json.loads(Path(str(path)+'.recovery.json').read_text())
        backup=Path(marker['backup'])/'corrupt.sqlite';self.assertEqual(backup.read_bytes(),b'corrupt fixture')
        result=reinitialize(cfg,True);self.assertEqual(result['phase'],'complete')
        self.assertEqual(backup.read_bytes(),b'corrupt fixture');self.assertEqual(Trust(cfg).read(),pin_before)
        with self.assertRaises(Conflict):reinitialize(cfg,True)

    def test_rotation_notification_once_and_no_historical_replay(self):
        self.sb.should_exit=True;self.threads[-1].join(10)
        self.expire(self.b);rotated=ensure_identity(self.b)
        notifications=Mock();worker=Lifecycle(self.b,notifications,Mock(),rotation=rotated['rotation_event'])
        worker.step();worker.step();self.assertEqual(notifications.submit.call_count,1)
        other=Mock();Lifecycle(self.b,other,Mock()).step();other.submit.assert_not_called()

    def test_one_sided_approval_cannot_bypass_inbound_endpoints(self):
        from urllib.error import HTTPError
        from hemlock.tls import PinnedConnection
        candidate=Trust(self.a).discover();Trust(self.a).approve(candidate['fingerprint']);refresh_context(self.a,self.sa.config.ssl)
        # B has not approved A. Even a handcrafted mTLS+token request must not get data.
        connection=PinnedConnection(self.b,client=True)
        try:
            connection.request('GET','/replication/handshake',headers={'Authorization':'Bearer '+self.tb.token,'X-Hemlock-Node':'b','X-Hemlock-Protocol':'3'})
            response=connection.getresponse();data=json.loads(response.read())
            self.assertEqual(response.status,503);self.assertEqual(data['code'],'remote_approval_required')
            self.assertNotIn('exchange_token',data)
        finally:connection.close()

    def test_damaged_local_trust_never_shows_in_sync_or_resets_data(self):
        from hemlock.presentation import View
        self.approve();self.rb.step();self.ra.step();before=self.ra.store.info()
        Trust(self.a).path.write_text('damaged local trust')
        dashboard=View(Service(self.ra.store)).dashboard()
        self.assertEqual(dashboard['peer']['status'],'Local TLS state error')
        self.assertFalse(dashboard['peer']['healthy']);self.assertEqual(self.ra.store.info(),before)
