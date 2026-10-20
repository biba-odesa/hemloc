"""Actual verified HTTPS transport with interrupted snapshot and journal racing it."""

from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import shutil
import ssl
import subprocess
import tempfile
import threading
import unittest
from urllib.parse import parse_qs,urlsplit

from hemloc.config import Config
from hemloc.domain import Actor
from hemloc.replication import PeerTransport, PeerUnavailable, Replicator
from hemloc.service import Service
from hemloc.store import Store,encode


@unittest.skipUnless(shutil.which('openssl'),'OpenSSL is unavailable')
class HTTPSReplicationTests(unittest.TestCase):
    def test_interrupted_snapshot_preserves_routes_then_snapshot_and_journal_catchup(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory=Path(temporary)
            subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','1',
                            '-keyout',str(directory/'tls.key'),'-out',str(directory/'tls.crt'),
                            '-subj','/CN=localhost','-addext','subjectAltName=IP:127.0.0.1'],
                           check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            token=secrets.token_urlsafe(48)
            (directory/'peer.token').write_text(token)
            config=Config(tls=False,node_id='a',peer_node_id='b',database=str(directory/'old.sqlite'),protected_asns=())
            admin=Actor('admin','admin')
            old=Store(config)
            Service(old).add_manual(admin,'192.0.2.0/24')
            slave_cfg=replace(config,node_id='b',peer_node_id='a',role='slave',database=str(directory/'slave.sqlite'))
            slave=Store(slave_cfg)
            slave.install_snapshot(old.snapshot())
            master=Store(replace(config,database=str(directory/'new.sqlite')))
            service=Service(master)
            service.add_manual(admin,'198.51.100.0/24')
            state={'truncate':True,'race':False}
            class Handler(BaseHTTPRequestHandler):
                def log_message(self,*args):
                    pass
                def do_GET(self):
                    if self.headers.get('Authorization')!='Bearer '+token or self.headers.get('X-Hemloc-Node')!='b':
                        self.send_error(403)
                        return
                    url=urlsplit(self.path)
                    if url.path.endswith('/status'):
                        payload=master.info()
                    elif url.path.endswith('/snapshot'):
                        payload=master.snapshot()
                        if state['race']:
                            state['race']=False
                            service.add_manual(admin,'203.0.113.0/24')
                    else:
                        query=parse_qs(url.query)
                        payload=master.events(query['history'][0],int(query['cursor'][0]))
                    body=encode(payload).encode()
                    declared_length=len(body)
                    if state['truncate'] and url.path.endswith('/snapshot'):
                        body=body[:len(body)//2]
                    self.send_response(200)
                    self.send_header('Content-Type','application/json')
                    self.send_header('Content-Length',str(declared_length))
                    self.end_headers()
                    self.wfile.write(body)
            server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
            context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(directory/'tls.crt',directory/'tls.key')
            server.socket=context.wrap_socket(server.socket,server_side=True)
            thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':0.05})
            thread.start()
            try:
                peer_cfg=replace(slave_cfg,peer_url=f'https://127.0.0.1:{server.server_port}',
                                 token_file=str(directory/'peer.token'),ca=str(directory/'tls.crt'))
                transport=PeerTransport(peer_cfg)
                poller=Replicator(slave,transport)
                before=slave.info()
                with self.assertRaises(PeerUnavailable):
                    poller.step()
                self.assertEqual(slave.info(),before)
                self.assertEqual(set(Service(slave).routes()[0]),{'192.0.2.0/24'})
                state.update(truncate=False,race=True)
                poller.step()
                self.assertEqual(slave.info()['history'],master.info()['history'])
                self.assertEqual(set(Service(slave).routes()[0]),{'198.51.100.0/24','203.0.113.0/24'})
                batch=transport.get('/replication/events',{'history':master.info()['history'],'cursor':0})
                slave.apply_events(batch)
                self.assertEqual(slave.list('audit'),master.list('audit'))
            finally:
                server.shutdown()
                server.server_close()
                thread.join()


if __name__ == '__main__':
    unittest.main()
