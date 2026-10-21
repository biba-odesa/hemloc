"""All-set route sorting and private, replicated successful-login facts."""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from hemlock.auth import Auth,password_hash
from hemlock.config import Config
from hemlock.domain import Actor,Forbidden,Invalid
from hemlock.presentation import View
from hemlock.service import Service
from hemlock.store import Store,encode
from hemlock.web import create_app

ADMIN=Actor('admin','admin')


class LoginHistoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.cfg=Config(tls=False,protected_asns=(),protected_prefixes=(),metadata_enabled=False,node_id='a',peer_node_id='b',database=str(Path(self.tmp.name)/'a.sqlite'))
        self.store=Store(self.cfg);self.service=Service(self.store)
        self.password='abcde1';hashed=password_hash(self.password)
        for login,role in [('admin','admin'),('guest','guest')]:self.service.save_user(ADMIN,login,role=role,password_hash=hashed)
        self.slave=Store(replace(self.cfg,node_id='b',peer_node_id='a',role='slave',database=str(Path(self.tmp.name)/'b.sqlite')))
        self.slave.install_snapshot(self.store.snapshot())

    def tearDown(self):self.tmp.cleanup()

    def test_five_successes_ip_node_union_restart_replay_snapshot_no_sessions(self):
        auth=Auth(self.store,lambda h,p:p=='good')
        for number in range(7):
            with patch('hemlock.store.time.time',return_value=100+number):auth.login('guest','good',f'192.0.2.{number+1}')
        with self.assertRaises(Forbidden):auth.login('guest','bad','192.0.2.99')
        self.assertEqual([e['ip'] for e in self.store.successful_logins('guest')],['192.0.2.7','192.0.2.6','192.0.2.5','192.0.2.4','192.0.2.3'])
        self.slave.install_snapshot(self.store.snapshot())
        with patch('hemlock.store.time.time',return_value=110):
            token,_=Auth(self.slave,lambda h,p:True).login('guest','unused','2001:0DB8:0:0::1')
        expected={'at':110,'node':'b','ip':'2001:db8::1'}
        self.assertEqual(self.slave.successful_logins('guest')[0],expected)
        batch=self.slave.local_security_events();self.store.ingest_security(batch);sequence=self.store.info()['sequence'];self.store.ingest_security(batch)
        self.assertEqual(self.store.info()['sequence'],sequence)
        self.slave.apply_events(self.store.events(self.slave.info()['history'],self.slave.info()['sequence']))
        self.assertEqual(self.slave.successful_logins('guest'),self.store.successful_logins('guest'))
        self.assertEqual(len(self.slave.successful_logins('guest')),5)
        restarted=Store(self.slave.config,activate=False)
        self.assertEqual(restarted.successful_logins('guest')[0],expected)
        before=self.slave.successful_logins('guest')
        Auth(self.slave).session(token);Auth(self.slave).session(token)
        self.assertEqual(self.slave.successful_logins('guest'),before)
        self.slave.install_snapshot(self.store.snapshot())
        self.assertEqual(self.slave.successful_logins('guest'),before)
        self.assertEqual(self.store.successful_logins('nobody'),[])
        text=encode(self.store.audit_history())
        for secret in (token,'unused','good','password_hash'):self.assertNotIn(secret,text)

    def test_legacy_unknown_ip_and_constrained_peer_metadata(self):
        self.store.security_event('guest','auth.login','session','success')
        self.assertIsNone(self.store.successful_logins('guest')[0]['ip'])
        with self.slave.transaction() as db:self.slave.security_record(db,'guest','auth.login','session','success',{'client_ip':'2001:db8::1'})
        valid=self.slave.local_security_events()
        for payload in ({'client_ip':'spoofed'},{'client_ip':'192.0.2.1','extra':'data'},{'password':'secret'}):
            bad=deepcopy(valid);bad['events'][0]['doc']['after']=payload
            with self.assertRaises(Invalid):self.store.ingest_security(bad)
        for field,value in [('action','auth.logout'),('result','denied')]:
            bad=deepcopy(valid);bad['events'][0]['doc'][field]=value
            with self.assertRaises(Invalid):self.store.ingest_security(bad)
        self.store.ingest_security(valid)
        self.assertEqual(self.store.successful_logins('guest')[0]['ip'],'2001:db8::1')

    def test_api_privacy_spoof_headers_reload_and_slave_password(self):
        with TestClient(create_app(self.cfg,adapter=object(),background=False),client=('192.0.2.10',4444)) as client:
            response=client.post('/api/login',json={'login':'admin','password':self.password},headers={'x-forwarded-for':'203.0.113.99','forwarded':'for=203.0.113.98'})
            self.assertEqual(response.status_code,200)
            self.assertEqual(client.get('/api/login-history?login=admin').json()['items'][0]['ip'],'192.0.2.10')
            client.post('/api/login',json={'login':'guest','password':self.password})
            for _ in range(3):client.get('/');client.get('/api/me')
            self.assertEqual(len(client.get('/api/login-history').json()['items']),1)
            self.assertEqual(client.get('/api/login-history?login=admin').status_code,403)
            self.assertEqual(client.get('/api/users').status_code,403)
            audit=client.get('/api/audit').json()['items']
            self.assertFalse(any(e['action']=='auth.login' and e['actor']=='admin' for e in audit))
            history=client.get('/api/history').json()['items']
            self.assertFalse(any(e['action']=='Sign in' and e['actor']=='admin' for e in history))
            response=client.post('/api/login',json={'login':'admin','password':self.password})
            self.assertEqual(client.get('/api/login-history?login=guest').status_code,200)
        with TestClient(create_app(self.slave.config,adapter=object(),background=False),client=('2001:db8::2',4444)) as client:
            response=client.post('/api/login',json={'login':'guest','password':self.password});csrf=response.json()['csrf']
            self.assertEqual(client.get('/api/login-history').json()['items'][0]['ip'],'2001:db8::2')
            self.assertEqual(client.get('/api/me').json()['password_change_node'],'a')
            self.assertEqual(client.post('/api/password',json={'current_password':self.password,'new_password':'newpwd1'},headers={'x-csrf-token':csrf}).status_code,403)

    def test_guest_changes_own_password_with_current_password_on_master(self):
        with TestClient(create_app(self.cfg,adapter=object(),background=False)) as client:
            response=client.post('/api/login',json={'login':'guest','password':self.password});headers={'x-csrf-token':response.json()['csrf']}
            previous=self.store.get('user','guest')
            self.assertEqual(client.post('/api/password',json={'current_password':'wrong1','new_password':'newpwd1'},headers=headers).status_code,403)
            self.assertEqual(self.store.get('user','guest'),previous)
            self.assertEqual(client.post('/api/password',json={'current_password':self.password,'new_password':'newpwd1'},headers=headers).status_code,200)
            self.assertEqual(client.get('/api/me').status_code,403)
            self.assertEqual(client.post('/api/login',json={'login':'guest','password':'newpwd1'}).status_code,200)
            self.assertEqual(self.store.get('user','guest')['role'],'guest')

    def test_state_precedence_and_exact_freshness_boundary(self):
        import time
        now=time.time();rule=self.service.add_manual(ADMIN,'192.0.2.1')
        self.assertEqual(View(self.service,now).route_state('192.0.2.1/32'),'Unknown')
        path={'prefix':'192.0.2.1/32','local':True,'owner':list(self.cfg.owner),'local_pref':self.cfg.local_pref,'next_hop':self.cfg.v4_next_hop,'communities':[self.cfg.community]}
        self.store.set_local('rib',{'at':now,'paths':[path]})
        self.assertEqual(View(self.service,now+45).route_state(path['prefix']),'Applied')
        self.assertEqual(View(self.service,now+45.001).route_state(path['prefix']),'Stale')
        self.store.set_local('worker:observation',{'at':now+1,'error':'Observation failed'})
        self.assertEqual(View(self.service,now+2).route_state(path['prefix']),'Unknown')
        self.store.set_local('worker:observation',{})
        self.store.set_local('rib',{'at':now,'paths':[]})
        self.assertEqual(View(self.service,now).route_state(path['prefix']),'Pending')
        self.store.set_local('bgp',{'error':'Reconciliation failed'})
        self.assertEqual(View(self.service,now).route_state(path['prefix']),'Failed')
        self.store.set_local('bgp',{})
        missing=Service(Store(replace(self.cfg,v4_next_hop=''),activate=False))
        self.assertEqual(View(missing,now).route_state(path['prefix']),'Failed')
        self.store.set_local('protection',{'prefixes':['192.0.2.1/32'],'success':{}})
        self.assertEqual(View(self.service,now+100).route_state(path['prefix']),'Excluded by protection')

    def test_all_set_sort_filtered_then_paged_stable_and_numeric(self):
        for value,comment in [('192.0.2.0/24','mask 24'),('192.0.2.0/25','mask 25'),('192.0.2.10','zulu'),('192.0.2.2','Alpha'),('192.0.2.1','alpha'),('2001:db8::10','Beta'),('2001:db8::2','beta')]:
            self.service.add_manual(ADMIN,value,comment)
        asrule=self.service.add_asn(ADMIN,123,'ASN comment');self.service.update_asn(ADMIN,asrule['id'],['198.51.100.0/24'])
        view=View(self.service)
        def all_pages(sort,direction='asc',q=''):
            first=view.route_page(q=q,sort=sort,direction=direction,size=2)
            result=[]
            for number in range(1,(first['total']+1)//2+1):result+=view.route_page(q=q,sort=sort,direction=direction,size=2,number=number)['items']
            return result
        numeric=['192.0.2.0/24','192.0.2.0/25','192.0.2.1/32','192.0.2.2/32','192.0.2.10/32','198.51.100.0/24','2001:db8::2/128','2001:db8::10/128']
        self.assertEqual([r['prefix'] for r in all_pages('prefix')],numeric)
        self.assertEqual([r['prefix'] for r in all_pages('prefix','desc')],numeric[::-1])
        for key in ('source','comment'):
            for direction in ('asc','desc'):
                items=all_pages(key,direction)
                values=[(r['sources'][0][key] or '—').casefold() for r in items]
                self.assertEqual(values,sorted(values,reverse=direction=='desc'))
        added=all_pages('added','desc');times=[min(s['added'] for s in r['sources']) for r in added]
        self.assertEqual(times,sorted(times,reverse=True))
        self.assertEqual([r['prefix'] for r in all_pages('comment',q='alpha')],['192.0.2.1/32','192.0.2.2/32'])
        self.assertEqual([r['prefix'] for r in all_pages('comment','desc',q='alpha')],['192.0.2.1/32','192.0.2.2/32'])
        with self.assertRaises(Invalid):view.route_page(sort='invalid')
        with self.assertRaises(Invalid):view.route_page(direction='invalid')
        with TestClient(create_app(self.cfg,adapter=object(),background=False)) as client:
            client.post('/api/login',json={'login':'guest','password':self.password})
            page=client.get('/api/routes?sort=prefix&direction=desc&size=2').json()
            self.assertEqual([r['prefix'] for r in page['items']],numeric[::-1][:2])
            self.assertEqual(client.get('/api/routes?sort=invalid').status_code,422)

if __name__=='__main__':unittest.main()
