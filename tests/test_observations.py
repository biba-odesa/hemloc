"""Volatile observations cannot become durable truth or weaken replication gates."""
from tests.role_helpers import demote

from dataclasses import asdict, replace
from pathlib import Path
import json
import sqlite3
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from hemlock.config import Config
from hemlock.domain import Actor, Conflict, Invalid
from hemlock.observations import Observations
from hemlock.presentation import View
from hemlock.replication import Replicator, observe_peer
from hemlock.retention import CAPABILITY, execute, peer_ready, preview
from hemlock.service import Service
from hemlock.store import Store
from hemlock.web import observe_bgp

ADMIN = Actor('fixture', 'admin')


class Transport:
    protocol_version=3
    application_version="fixture"

    def handshake(self):
        return self.peer.info() | {"replication_protocol_version":3,"application_version":"fixture"}

    def __init__(self, peer):
        self.peer = peer

    def get(self, path, query=None):
        query = query or {}
        if path == '/replication/status':
            with self.peer.connect() as db:
                security_history = self.peer.meta(db, 'security_history')
                security_sequence = db.execute('SELECT COALESCE(MAX(seq),0) FROM security_audit').fetchone()[0]
            return self.peer.info() | {'replication_protocol_version':3,'capabilities':[CAPABILITY], 'security_history':security_history,
                                       'security_sequence':security_sequence}
        if path == '/replication/local-audit':
            return self.peer.local_security_events(query.get('after', 0), history=query.get('history', ''))
        if path == '/replication/snapshot':
            return self.peer.snapshot()
        if path == '/replication/events':
            return self.peer.events(query['history'], query['cursor'])
        raise AssertionError(path)


class ObservationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg = Config(database=self.tmp.name+'/a.sqlite', node_id='a', peer_node_id='b',
                          tls=False, protected_asns=(), protected_prefixes=())
        self.store = Store(self.cfg)
        self.service = Service(self.store)
        self.rule = self.service.add_manual(ADMIN, '192.0.2.1')
        self.now = time.time()
        self.rib = {'at':self.now, 'paths':[{'prefix':'192.0.2.1/32', 'local':True,
                    'owner':list(self.cfg.owner), 'next_hop':self.cfg.v4_next_hop,
                    'local_pref':self.cfg.local_pref, 'communities':[self.cfg.community]}],
                    'peers':[], 'export':{}}

    def test_volatile_updates_make_no_sqlite_changes_and_copies_are_isolated(self):
        with self.store.connect() as db:
            before = db.execute('PRAGMA data_version').fetchone()[0]
            with patch.object(self.store, 'connect', side_effect=AssertionError('Unexpected SQLite access')):
                for number in range(50):
                    self.store.set_local('rib', self.rib)
                    self.store.set_local('bgp', {'at':self.now+number})
                    self.store.set_local('peer', {'at':self.now+number})
                    self.store.set_local('sync', {'ok':True})
                    self.store.set_local('worker:bgp', {'error':'failed'})
                    value = self.store.local('rib')
                    value['paths'].clear()
                    self.assertEqual(len(self.store.local('rib')['paths']), 1)
            self.assertEqual(db.execute('PRAGMA data_version').fetchone()[0], before)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM local WHERE key IN ('rib','bgp','peer','sync') OR key LIKE 'worker:%'").fetchone()[0], 0)
        self.rib['paths'].clear()
        self.assertEqual(len(self.store.local('rib')['paths']), 1)
        with self.store.transaction() as db:
            with self.assertRaises(Invalid):self.store.write_local(db,'rib',{})

    def test_cold_restart_and_backup_ignore_legacy_applied_and_sync_rows(self):
        info = self.store.info()
        legacy = {'rib':self.rib, 'bgp':{'at':self.now},
                  'peer':{'at':self.now,'status':info}, 'sync':{'at':self.now,'ok':True}}
        with self.store.transaction() as db:
            for key,value in legacy.items():
                db.execute('INSERT INTO local VALUES(?,?)',(key,json.dumps(value)))
        self.store.set_local('rib', self.rib)
        self.assertEqual(View(self.service,self.now).route_state('192.0.2.1/32'),'Applied')
        cold = Store(replace(self.cfg,peer_url='https://peer.invalid'))
        view = View(Service(cold),self.now)
        self.assertEqual(view.route_state('192.0.2.1/32'),'Unknown')
        self.assertFalse(view.dashboard()['peer']['healthy'])
        self.assertIsNone(cold.local('rib'))
        backup = self.tmp.name+'/backup.sqlite'
        self.store.backup(backup)
        restored = Store(replace(self.cfg,database=backup))
        self.assertEqual(View(Service(restored),self.now).route_state('192.0.2.1/32'),'Unknown')
        self.assertEqual(restored.list('rule'),self.store.list('rule'))

    def test_error_stale_and_recovery_use_real_observations(self):
        self.store.set_local('rib',self.rib)
        self.assertEqual(View(self.service,self.now+46).route_state('192.0.2.1/32'),'Stale')
        self.store.set_local('worker:observation',{'at':self.now+1,'error':'failed'})
        self.assertEqual(View(self.service,self.now+2).route_state('192.0.2.1/32'),'Unknown')
        class Adapter:
            def observe(inner):return dict(self.rib)
        with patch('hemlock.web.time.time',return_value=self.now+3):observe_bgp(self.store,Adapter())
        self.assertEqual(View(self.service,self.now+4).route_state('192.0.2.1/32'),'Applied')

    def test_http_cold_start_is_unknown_until_successful_observation(self):
        from fastapi.testclient import TestClient
        from hemlock.auth import password_hash
        from hemlock.web import create_app
        self.service.save_user(ADMIN,'viewer',role='guest',password_hash=password_hash('fixture1'))
        self.store.set_local('rib',self.rib)
        app=create_app(self.cfg,adapter=object(),background=False)
        with TestClient(app) as client:
            self.assertEqual(client.post('/api/login',json={'login':'viewer','password':'fixture1'}).status_code,200)
            data=client.get('/api/dashboard').json()
            self.assertEqual(data['application_status'],'Unknown');self.assertIsNone(data['blocked'])
            self.assertEqual(client.get('/api/route-detail',params={'prefix':'192.0.2.1'}).json()['state'],'Unknown')
            app.state.store.set_local('rib',self.rib)
            self.assertEqual(client.get('/api/route-detail',params={'prefix':'192.0.2.1'}).json()['state'],'Applied')
            self.assertEqual(client.get('/api/observation').json()['rib']['paths'][0]['prefix'],'192.0.2.1/32')

    def test_fixed_keys_latest_values_and_concurrent_snapshot_isolation(self):
        cache = Observations()
        errors=[]
        def writer():
            for number in range(200):cache.set('rib', {'paths':[number]*20})
        def reader():
            for _ in range(200):
                paths = cache.get('rib',{'paths':[]})['paths']
                if len(set(paths))>1:errors.append(paths)
                cache.snapshot().clear()
        threads=[threading.Thread(target=fn) for fn in (writer,reader,writer,reader)]
        for thread in threads:thread.start()
        for thread in threads:thread.join(5);self.assertFalse(thread.is_alive())
        self.assertFalse(errors)
        self.assertEqual(set(cache.snapshot()),{'rib'})
        with self.assertRaises(ValueError):cache.set('worker:unbounded-key',{})
        with self.assertRaises(ValueError):cache.set('protection',{})

    def test_repeated_durable_values_do_not_dirty_sqlite(self):
        self.store.set_local('peer_ack',{'history':'fixture','sequence':3})
        self.store.set_local('security_ack',{'history':'fixture','sequence':4})
        with self.store.connect() as db:
            before=db.execute('PRAGMA data_version').fetchone()[0]
            for _ in range(10):
                self.store.set_local('peer_ack',{'history':'fixture','sequence':3})
                self.store.set_local('security_ack',{'history':'fixture','sequence':4})
                with self.store.transaction() as other:self.store.set_meta(other,'sequence',self.store.meta(other,'sequence'))
            self.assertEqual(db.execute('PRAGMA data_version').fetchone()[0],before)
        fresh=Store(self.cfg)
        self.assertEqual(fresh.local('peer_ack')['sequence'],3)
        self.assertEqual(fresh.local('security_ack')['sequence'],4)

    def test_restart_replay_snapshot_outbox_and_promotion_preserve_durable_facts(self):
        bcfg=replace(self.cfg,role='slave',node_id='b',peer_node_id='a',database=self.tmp.name+'/b.sqlite')
        a,b=self.store,Store(bcfg)
        ar,br=Replicator(a,Transport(b)),Replicator(b,Transport(a))
        br.step();ar.step();br.step()
        b.set_local('protection',{'prefixes':['198.51.100.0/24'],'success':{}})
        b.set_local('security_ack',{'history':'fixture','sequence':1})
        event=b.security_event('guest','auth.login','session','success')
        cursor=b.info()
        a,b=Store(self.cfg),Store(bcfg)
        self.assertFalse(a.observations.snapshot());self.assertFalse(b.observations.snapshot())
        self.assertEqual(b.info(),cursor)
        self.assertEqual(b.local('protection')['prefixes'],['198.51.100.0/24'])
        self.assertEqual(b.local('security_ack')['sequence'],1)
        self.assertEqual(b.local_security_events()['events'][0]['doc']['id'],event['id'])
        ar,br=Replicator(a,Transport(b)),Replicator(b,Transport(a))
        ar.step();br.step();ar.step()
        self.assertIsNotNone(a.get('audit',event['id']))
        with a.connect() as db:
            version=db.execute('PRAGMA data_version').fetchone()[0]
            for _ in range(5):ar.step()
            self.assertEqual(db.execute('PRAGMA data_version').fetchone()[0],version)
        b.install_snapshot(a.snapshot())
        pending=b.security_event('guest','auth.login','session','success')
        promoted=Store(replace(bcfg,role='master'))
        self.assertIsNotNone(promoted.get('audit',pending['id']))
        self.assertEqual(promoted.local('protection')['prefixes'],['198.51.100.0/24'])
        old=demote(replace(self.cfg,role='slave'))
        old.install_snapshot(promoted.snapshot())
        self.assertEqual(old.list('rule'),promoted.list('rule'))

    def test_cli_style_live_probe_rejects_stale_durable_ack_and_old_protocol(self):
        cfg=replace(self.cfg,peer_url='https://peer.invalid')
        a=Store(cfg)
        b=Store(replace(self.cfg,role='slave',node_id='b',peer_node_id='a',database=self.tmp.name+'/b.sqlite'))
        b.install_snapshot(a.snapshot());a.ingest_security(b.local_security_events())
        transport=Transport(b)
        observe_peer(a,transport)
        with a.connect() as db:peer_ready(a,db,time.time())
        fresh=Store(cfg)
        with fresh.connect() as db:
            with self.assertRaises(Conflict):peer_ready(fresh,db,time.time())
        observe_peer(fresh,transport)
        with fresh.connect() as db:peer_ready(fresh,db,time.time())
        status=transport.get('/replication/status');status['sequence']-=1
        with patch.object(transport,'get',return_value=status):observe_peer(fresh,transport)
        with fresh.connect() as db:
            with self.assertRaises(Conflict):peer_ready(fresh,db,time.time())
        status['capabilities']=[]
        with patch.object(transport,'get',return_value=status):observe_peer(fresh,transport)
        with fresh.connect() as db:
            with self.assertRaises(Conflict):peer_ready(fresh,db,time.time())


if __name__=='__main__':unittest.main()
