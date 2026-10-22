"""Both HTTP directions enforce one negotiated protocol before remote state."""
from contextlib import ExitStack
from dataclasses import replace
from io import BytesIO
from pathlib import Path
import tempfile
import time
import unittest
from urllib.error import HTTPError
from urllib.parse import urlsplit
from unittest.mock import patch

from fastapi.testclient import TestClient
from hemlock.config import Config
from hemlock.domain import Actor,Conflict
from hemlock.presentation import View
from hemlock.protocol import REPLICATION_PROTOCOL_VERSION,ProtocolFailure,VERSION_HEADER,EXCHANGE_HEADER,NODE_HEADER,APP_HEADER
from hemlock.replication import PeerTransport,PeerAuthenticationFailed,Replicator
from hemlock.retention import execute,preview
from hemlock.service import Service
from hemlock.transition import RoleTransition
from hemlock.web import create_app

ADMIN=Actor('fixture','admin')


class Response(BytesIO):
    def __init__(self,response,url):
        super().__init__(response.content);self.headers=response.headers;self.url=url
    def geturl(self):return self.url


class Opener:
    def __init__(self,client):self.client=client;self.paths=[];self.edit=None
    def open(self,request,timeout=None):
        path=urlsplit(request.full_url).path
        self.paths.append(path)
        response=self.client.get(request.full_url,headers=dict(request.header_items()))
        if self.edit:response=self.edit(path,response)
        if response.status_code>=400:
            raise HTTPError(request.full_url,response.status_code,'Peer refused',response.headers,BytesIO(response.content))
        return Response(response,request.full_url)


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        root=Path(self.tmp.name);token=root/'peer.token';token.write_text('fixture-shared-credential-'+'a'*40)
        self.cfg=Config(tls=False,protected_asns=(),metadata_enabled=False,database=str(root/'a.sqlite'),node_id='a',peer_node_id='b',peer_url='https://peer.invalid',token_file=str(token))
        self.bcfg=replace(self.cfg,database=str(root/'b.sqlite'),node_id='b',peer_node_id='a',role='slave')
        stack=ExitStack();self.addCleanup(stack.close)
        self.appa=create_app(self.cfg,adapter=object(),background=False)
        self.appb=create_app(self.bcfg,adapter=object(),background=False)
        self.ca=stack.enter_context(TestClient(self.appa,base_url='https://peer.invalid'))
        self.cb=stack.enter_context(TestClient(self.appb,base_url='https://peer.invalid'))
        self.a,self.b=self.appa.state.store,self.appb.state.store
        self.ta,self.tb=PeerTransport(self.cfg),PeerTransport(self.bcfg)
        self.ta.opener,self.tb.opener=Opener(self.cb),Opener(self.ca)
        self.ra,self.rb=Replicator(self.a,self.ta),Replicator(self.b,self.tb)
        self.appa.state.replication_gate.application_version=self.ta.application_version='0.4.1'
        self.appb.state.replication_gate.application_version=self.tb.application_version='9.8.7'
        Service(self.a).add_manual(ADMIN,'192.0.2.1')
        self.rb.step();self.ra.step();self.rb.step()

    def state(self,store):
        with store.connect() as db:
            meta=tuple(db.execute("SELECT key,value FROM meta WHERE key IN ('history','sequence','role','node_id','peer_security_history','peer_security_cursor') ORDER BY key"))
        return (store.list('rule'),store.list('user'),meta,store.local('peer_ack'),store.local('security_ack'),store.local('protection'))

    def mismatch(self):
        self.appb.state.replication_gate.version=4
        self.b.replication_protocol_version=4;self.ta.exchange_token=None;self.tb.protocol_version=4
        for worker in (self.rb,self.ra):
            with self.assertRaises(ProtocolFailure):worker.step()

    def recover(self):
        self.appb.state.replication_gate.version=3
        self.b.replication_protocol_version=3;self.tb.protocol_version=3
        for _ in range(3):self.rb.step();self.ra.step()
        self.rb.step()

    def test_same_protocol_different_application_releases_and_paused_state(self):
        self.assertEqual(self.a.list('rule'),self.b.list('rule'))
        before_a,before_b=self.state(self.a),self.state(self.b)
        previous=self.a.local('sync')['last_success']
        self.ta.opener.paths.clear();self.tb.opener.paths.clear()
        self.mismatch()
        self.assertEqual(self.state(self.a),before_a);self.assertEqual(self.state(self.b),before_b)
        self.assertEqual(self.a.local('sync')['last_success'],previous)
        self.assertEqual(set(self.ta.opener.paths+self.tb.opener.paths),{'/replication/handshake'})
        for store in (self.a,self.b):
            peer=View(Service(store)).dashboard()['peer']
            self.assertEqual(peer['status'],'Protocol version mismatch');self.assertFalse(peer['healthy'])
            self.assertIsNone(RoleTransition(store.config).status())
        self.assertEqual(self.a.local('peer_compatibility')['peer_application_version'],'9.8.7')

    def test_outbox_backlog_replay_and_history_recovery(self):
        self.mismatch()
        event=self.b.security_event(ADMIN,'auth.login','session','success',{'client_ip':'2001:db8::9'})
        Service(self.a).add_manual(ADMIN,'2001:db8::1')
        before=self.b.info()
        with self.assertRaises(ProtocolFailure):self.rb.step()
        self.assertEqual(self.b.info(),before)
        self.recover()
        self.assertEqual(self.a.list('rule'),self.b.list('rule'))
        self.assertEqual(sum(e['id']==event['id'] for e in self.a.audit_history()),1)
        self.assertEqual(sum(e['id']==event['id'] for e in self.b.audit_history()),1)
        self.assertEqual(self.a.info()['history'],before['history'])
        self.assertEqual(self.a.info()['sequence'],self.b.info()['sequence'])
        # Simulate expired journal coverage: recovery requests a normal full snapshot.
        self.mismatch();Service(self.a).add_manual(ADMIN,'198.51.100.8')
        with self.a.transaction() as db:db.execute('DELETE FROM journal')
        self.recover();self.assertEqual(self.a.list('rule'),self.b.list('rule'))

    def test_direct_requests_no_ticket_wrong_version_and_restart_ticket(self):
        headers={'Authorization':'Bearer '+self.tb.token,NODE_HEADER:'a',VERSION_HEADER:'3',APP_HEADER:'fixture'}
        endpoints=['/replication/status','/replication/snapshot','/replication/events?history=fixture&cursor=0','/replication/local-audit']
        for endpoint in endpoints:
            response=self.cb.get(endpoint,headers=headers);self.assertEqual(response.status_code,428)
            self.assertNotIn('events',response.json());self.assertNotIn('security_ack',response.json())
        ticket=self.cb.get('/replication/handshake',headers=headers).json()['exchange_token']
        headers[EXCHANGE_HEADER]=ticket;headers[VERSION_HEADER]='4'
        before=self.b.info()
        for endpoint in endpoints:self.assertEqual(self.cb.get(endpoint,headers=headers).status_code,412)
        self.assertEqual(self.b.info(),before)
        headers[VERSION_HEADER]='3';self.appb.state.replication_gate.tokens.clear()
        self.assertEqual(self.cb.get('/replication/status',headers=headers).status_code,428)
        headers.pop(VERSION_HEADER)
        self.assertEqual(self.cb.get('/replication/status',headers=headers).status_code,426)

    def test_old_peer_missing_handshake_no_fallback_and_auth_distinct(self):
        before=self.state(self.b)
        def old(path,response):
            if path.endswith('/handshake'):response.status_code=404
            return response
        self.tb.opener.edit=old;self.tb.opener.paths.clear()
        with self.assertRaises(ProtocolFailure):self.rb.step()
        self.assertEqual(self.state(self.b),before)
        self.assertEqual(self.tb.opener.paths,['/replication/handshake'])
        self.assertEqual(View(Service(self.b)).dashboard()['peer']['status'],'Peer upgrade required')
        self.tb.opener.edit=None;self.tb.token='incorrect-fixture'
        with self.assertRaises(PeerAuthenticationFailed):self.rb.step()
        self.assertEqual(View(Service(self.b)).dashboard()['peer']['status'],'Authentication failed')

    def test_response_proof_missing_blocks_mutation_and_prune_is_gated(self):
        Service(self.a).add_manual(ADMIN,'198.51.100.9')
        before=self.state(self.b)
        def no_proof(path,response):
            if path.endswith('/events'):del response.headers[VERSION_HEADER]
            return response
        self.tb.opener.edit=no_proof
        with self.assertRaises(ProtocolFailure):self.rb.step()
        self.assertEqual(self.state(self.b),before)
        self.mismatch()
        old=time.time()-10*86400
        with patch('hemlock.store.time.time',return_value=old):self.a.security_event('anonymous','http.request','request','invalid')
        plan=preview(self.a)
        self.assertTrue(plan['payload']['entries'])
        before=self.a.list('audit')
        with self.assertRaises(Conflict):execute(self.a,plan)
        self.assertEqual(self.a.list('audit'),before)
        with self.a.connect() as db:
            from hemlock.retention import peer_ready
            with self.assertRaises(Conflict):peer_ready(self.a,db,time.time())
        self.assertFalse(self.a.local('peer_compatibility')['ok'])

    def test_handshake_without_version_and_expired_lease_fail_closed(self):
        import httpx
        before=self.state(self.b)
        def obsolete(path,response):
            if path.endswith('/handshake'):
                return httpx.Response(200,json={'node_id':'a','role':'master'},request=response.request)
            return response
        self.tb.opener.edit=obsolete
        with self.assertRaises(ProtocolFailure) as result:self.rb.step()
        self.assertEqual(result.exception.code,'peer_upgrade_required')
        self.assertEqual(self.state(self.b),before)
        self.tb.opener.edit=None
        headers={'Authorization':'Bearer '+self.ta.token,NODE_HEADER:'a',VERSION_HEADER:'3'}
        token=self.cb.get('/replication/handshake',headers=headers).json()['exchange_token']
        headers[EXCHANGE_HEADER]=token
        with patch('hemlock.protocol.time.monotonic',return_value=time.monotonic()+31):
            self.assertEqual(self.cb.get('/replication/status',headers=headers).status_code,428)
        self.assertEqual(self.state(self.b),before)
