"""Two isolated HTTPS FastAPI nodes: login metadata uses the existing audit channel."""
from dataclasses import replace
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import threading
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import httpx
import uvicorn
from hemloc.auth import password_hash
from hemloc.config import Config
from hemloc.domain import Actor
from hemloc.replication import PeerTransport,Replicator,PeerUnavailable
from hemloc.service import Service
from hemloc.store import Store
from hemloc.web import create_app
from tools.check_gobgp import port,wait_for


def main():
    with tempfile.TemporaryDirectory(prefix='hemloc-login-https-') as tmp:
        root=Path(tmp);cert=root/'tls.crt';key=root/'tls.key';token=root/'peer.token';token.write_text(secrets.token_urlsafe(48));token.chmod(0o600)
        subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','1','-keyout',str(key),'-out',str(cert),'-subj','/CN=localhost','-addext','subjectAltName=IP:127.0.0.1'],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        a_port,b_port=port(),port()
        cfg=Config(tls=True,host='127.0.0.1',port=a_port,cert=str(cert),key=str(key),ca=str(cert),token_file=str(token),
                   database=str(root/'a.sqlite'),node_id='a',peer_node_id='b',peer_url=f'https://127.0.0.1:{b_port}',protected_asns=(),protected_prefixes=(),metadata_enabled=False)
        other=replace(cfg,role='slave',port=b_port,node_id='b',peer_node_id='a',peer_url=f'https://127.0.0.1:{a_port}',database=str(root/'b.sqlite'))
        master=Store(cfg);slave=Store(other);password='a1'+secrets.token_urlsafe(24)
        Service(master).save_user(Actor('lab','admin'),'guest',role='guest',password_hash=password_hash(password))
        running=[]
        def start(config):
            server=uvicorn.Server(uvicorn.Config(create_app(config,adapter=object(),background=False),host=config.host,port=config.port,
                      ssl_certfile=config.cert,ssl_keyfile=config.key,timeout_keep_alive=1,timeout_graceful_shutdown=2,proxy_headers=False,access_log=False,log_level='error'))
            thread=threading.Thread(target=server.run);thread.start();running.append((server,thread));wait_for(lambda:server.started);return server,thread
        def stop(pair):
            server,thread=pair;server.should_exit=True;thread.join(timeout=15);assert not thread.is_alive()
        try:
            start(cfg);b=start(other)
            master_poll=Replicator(master,PeerTransport(cfg));slave_poll=Replicator(slave,PeerTransport(other))
            slave_poll.step()
            with httpx.Client(base_url=f'https://127.0.0.1:{a_port}',verify=str(cert),trust_env=False) as a,httpx.Client(base_url=f'https://127.0.0.1:{b_port}',verify=str(cert),trust_env=False) as b_client:
                for client in (a,b_client):
                    response=client.post('/api/login',json={'login':'guest','password':password},headers={'x-forwarded-for':'203.0.113.99'})
                    assert response.status_code==200,response.status_code
                master_poll.step();slave_poll.step()
                for client in (a,b_client):
                    history=client.get('/api/login-history').json();assert len(history['items'])==2,history
                    assert {e['node'] for e in history['items']}=={'a','b'}
                    assert {e['ip'] for e in history['items']}=={'127.0.0.1'}
                for _ in range(2):
                    master_poll.step();slave_poll.step();a.get('/api/me');b_client.get('/api/me')
                assert len(master.successful_logins('guest'))==len(slave.successful_logins('guest'))==2
                b_client.close()
                stop(b)
                try:master_poll.step()
                except PeerUnavailable:pass
                else:raise AssertionError('Offline peer accepted')
                status=a.get('/api/login-history').json()
                assert 'unavailable' in status['peer']['status'].lower()
                assert len(status['items'])==2
                start(other);master_poll.step();slave_poll.step()
                assert master.successful_logins('guest')==slave.successful_logins('guest')
                assert len(master.successful_logins('guest'))==2
            print('PASS: two actual HTTPS FastAPI nodes, verified CA/IP SAN and peer auth, master journal + slave security outbox IP/node facts, replay/dedup, session reads without new logins, disconnect preservation/unavailable status and restart catch-up. No GoBGP adapter or production data.')
        finally:
            for pair in running:stop(pair)

if __name__=='__main__':main()
