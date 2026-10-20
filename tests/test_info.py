"""Read-only protection presentation and actual snapshot preservation semantics."""
from contextlib import closing
from dataclasses import replace
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from fastapi.testclient import TestClient
from hemloc.auth import password_hash
from hemloc.config import Config
from hemloc.domain import Actor
from hemloc.presentation import protection_page
from hemloc.service import Service
from hemloc.store import Store
from hemloc.web import create_app


class InfoTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.cfg=Config(tls=False,node_id='a',peer_node_id='b',protected_asns=(64496,),protected_prefixes=('10.0.0.0/8','2001:db8::/32'),database=str(Path(self.tmp.name)/'a.sqlite'),metadata_enabled=False)
        self.store=Store(self.cfg);self.service=Service(self.store);self.actor=Actor('admin','admin')
        self.service.save_user(self.actor,'guest',role='guest',password_hash=password_hash('abcde1'))
        self.store.set_local('protection',{'prefixes':['10.0.0.0/8']+[f'192.0.2.{i}/32' for i in range(1,62)],'success':{'64496':1234,'64599':10}})

    def tearDown(self):self.tmp.cleanup()

    def test_authenticated_filtered_pagination_union_sources_no_writes(self):
        before=self.store.snapshot();local=self.store.local('protection')
        with TestClient(create_app(self.cfg,adapter=object(),background=False)) as client:
            self.assertEqual(client.get('/api/info/protection').status_code,403)
            client.post('/api/login',json={'login':'guest','password':'abcde1'})
            baseline=self.store.snapshot()
            summary=client.get('/api/info/protection').json()
            self.assertEqual(summary,{'node_id':'a','asn_count':1,'prefix_count':63})
            self.assertNotIn('items',summary)
            rows=client.get('/api/info/protection?kind=prefixes').json();self.assertEqual(len(rows['items']),25)
            self.assertEqual(rows['items'][0],{'prefix':'10.0.0.0/8','sources':['configuration','cache']})
            last=client.get('/api/info/protection?kind=prefixes&page_number=99').json();self.assertEqual(last['page'],3)
            self.assertEqual(last['items'][-1]['prefix'],'2001:db8::/32')
            found=client.get('/api/info/protection?kind=prefixes&q=2001:db8').json();self.assertEqual(found['total'],1)
            asns=client.get('/api/info/protection?kind=asns').json();self.assertEqual(asns['items'],[{'asn':64496,'last_success':1234}])
            empty=client.get('/api/info/protection?kind=prefixes&q=absent').json();self.assertEqual((empty['items'],empty['total'],empty['page']),([],0,1))
            self.assertEqual(self.store.snapshot(),baseline)
            self.assertEqual(self.store.local('protection'),local)
            self.assertEqual(client.get('/api/info/protection?kind=bad').status_code,422)
            self.assertEqual(client.get('/api/info/protection?kind=prefixes&size=101').status_code,422)

    def test_snapshot_backs_up_and_replaces_only_replicated_data(self):
        master=self.store
        cfg=replace(self.cfg,role='slave',node_id='b',peer_node_id='a',database=str(Path(self.tmp.name)/'b.sqlite'))
        prior=Store(replace(cfg,role='master'))
        Service(prior).add_manual(self.actor,'203.0.113.1','Old branch retained in backup')
        slave=Store(cfg);service=Service(slave)
        slave.set_local('protection',{'prefixes':['198.51.100.0/24'],'success':{'64496':10}})
        old=slave.snapshot();local=slave.local('protection');settings=service.config
        backup=slave.install_snapshot(master.snapshot())
        with closing(sqlite3.connect(backup)) as db:
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0],'ok')
            self.assertEqual(db.execute('SELECT count(*) FROM documents').fetchone()[0],len(old['payload']['documents']))
        self.assertEqual(slave.list('user'),master.list('user'))
        self.assertEqual(slave.list('rule'),master.list('rule'))
        self.assertEqual(slave.local('protection'),local);self.assertEqual(service.config,settings)
        summary=protection_page(service);self.assertEqual(summary['node_id'],'b');self.assertEqual(summary['prefix_count'],3)
        self.assertIn('198.51.100.0/24',[p['prefix'] for p in protection_page(service,'prefixes')['items']])

if __name__=='__main__':unittest.main()
