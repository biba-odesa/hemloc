"""Real HTTPS handshake pause/recovery and own peer-free GoBGP processes only."""
from dataclasses import replace
import argparse
import json
from pathlib import Path
import secrets
import ssl
import subprocess
import tempfile
import threading
import time
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import uvicorn
from hemlock.config import Config
from hemlock.domain import Actor
from hemlock.gobgp import GoBGP
from hemlock.presentation import View
from hemlock.protocol import ProtocolFailure
from hemlock.reconcile import Reconciler
from hemlock.replication import Replicator
from hemlock.web import create_app
from tools.check_gobgp import port,wait_for


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--binary',required=True);args=parser.parse_args()
    binary=str(Path(args.binary).resolve())
    with tempfile.TemporaryDirectory(prefix='hemlock-protocol-lab-') as tmp:
        root=Path(tmp);servers=[];threads=[];daemons=[];adapters=[];logs=[];apps=[];pollers=[];poll_stop=threading.Event()
        subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','1','-keyout',str(root/'tls.key'),'-out',str(root/'tls.crt'),'-subj','/CN=localhost','-addext','subjectAltName=IP:127.0.0.1'],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        token=root/'peer.token';token.write_text(secrets.token_urlsafe(48))
        used=set()
        def free():
            p=port()
            while p in used:p=port()
            used.add(p);return p
        aweb,bweb=free(),free()
        cfg=Config(database=str(root/'a.sqlite'),node_id='a',peer_node_id='b',peer_url=f'https://127.0.0.1:{bweb}',host='127.0.0.1',port=aweb,
                   cert=str(root/'tls.crt'),key=str(root/'tls.key'),ca=str(root/'tls.crt'),token_file=str(token),
                   protected_asns=(),protected_prefixes=(),metadata_enabled=False,announcements=True,
                   v4_next_hop='192.0.2.254',v6_next_hop='2001:db8::1')
        bcfg=replace(cfg,database=str(root/'b.sqlite'),role='slave',node_id='b',peer_node_id='a',peer_url=f'https://127.0.0.1:{aweb}',port=bweb,owner=(64512,100,2))
        try:
            for name,config in [('a',cfg),('b',bcfg)]:
                rpc,bgp=free(),free();toml=root/(name+'.toml')
                toml.write_text(f'[global.config]\nas=64512\nrouter-id="127.0.0.1"\nport={bgp}\nlocal-address-list=["127.0.0.1"]\n')
                log=(root/(name+'.log')).open('wb');logs.append(log)
                process=subprocess.Popen([binary,'-f',str(toml),f'--api-hosts=127.0.0.1:{rpc}','--pprof-disable'],stdout=log,stderr=log);daemons.append(process)
                config=replace(config,grpc_target=f'127.0.0.1:{rpc}')
                adapter=GoBGP(config);adapters.append(adapter)
                def ready(adapter=adapter):
                    try:adapter.paths();return True
                    except Exception:return False
                wait_for(ready)
                app=create_app(config,adapter=adapter,background=False);apps.append(app)
                server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=config.port,ssl_certfile=config.cert,ssl_keyfile=config.key,proxy_headers=False,access_log=False,log_level='error'))
                thread=threading.Thread(target=server.run);thread.start();threads.append(thread);servers.append(server);wait_for(lambda:server.started)
            a,b=[app.state.store for app in apps];sa,sb=[app.state.service for app in apps]
            ta,tb=[app.state.peer for app in apps];ra,rb=Replicator(a,ta),Replicator(b,tb)
            apps[0].state.replication_gate.application_version=ta.application_version='0.4.1'
            apps[1].state.replication_gate.application_version=tb.application_version='9.8.7'
            admin=Actor('lab','admin')
            sa.add_manual(admin,'192.0.2.11');sa.add_manual(admin,'2001:db8::11')
            rb.step();ra.step();rb.step()
            recon=[Reconciler(sa,adapters[0]),Reconciler(sb,adapters[1])]
            for item in recon:assert len(item.step()['confirmed'])==2
            old_rib=[sorted((p.prefix,p.next_hop,p.communities) for p in adapter.paths()) for adapter in adapters]
            old_info=[store.info() for store in (a,b)];old_ack=[store.local('peer_ack') for store in (a,b)]
            apps[1].state.replication_gate.version=4;tb.protocol_version=4;b.replication_protocol_version=4
            errors=[]
            def poll(worker):
                while not poll_stop.is_set():
                    try:worker.step()
                    except ProtocolFailure:pass
                    except Exception as error:errors.append(type(error).__name__)
                    poll_stop.wait(0.2)
            for worker in (rb,ra):
                thread=threading.Thread(target=poll,args=(worker,));thread.start();pollers.append(thread)
            wait_for(lambda:all(View(service).dashboard()['peer']['status']=='Protocol version mismatch' for service in (sa,sb)))
            time.sleep(0.6)
            assert [store.info() for store in (a,b)]==old_info
            assert [store.local('peer_ack') for store in (a,b)]==old_ack
            assert all(View(service).dashboard()['peer']['status']=='Protocol version mismatch' for service in (sa,sb))
            for item in recon:item.step()
            assert old_rib==[sorted((p.prefix,p.next_hop,p.communities) for p in adapter.paths()) for adapter in adapters]
            fact=b.security_event('lab','auth.login','session','success',{'client_ip':'2001:db8::8'})
            sa.add_manual(admin,'198.51.100.12')
            # Represents upgrading A after B: protocol equality returns, app releases differ.
            apps[0].state.replication_gate.version=4;ta.protocol_version=4;a.replication_protocol_version=4
            wait_for(lambda:a.list('rule')==b.list('rule') and a.get('audit',fact['id']) is not None and b.get('audit',fact['id']) is not None)
            wait_for(lambda:all(View(service).dashboard()['peer']['healthy'] for service in (sa,sb)))
            assert not errors,errors
            assert a.list('rule')==b.list('rule')
            assert sum(e['id']==fact['id'] for e in a.audit_history())==1
            assert sum(e['id']==fact['id'] for e in b.audit_history())==1
            for item in recon:assert len(item.step()['confirmed'])==3
            assert all(View(service).dashboard()['peer']['healthy'] for service in (sa,sb))
            assert all(p.poll() is None for p in daemons)
            print('PASS: two CA-verified HTTPS nodes; same protocol/different app releases; B-first mismatch pause with unchanged rules/cursors/acks/real IPv4+IPv6 RIB and daemon PIDs; local outbox accumulated; A upgrade automatically resumed snapshot/journal/outbox exactly once; Dashboard recovered. Only own loopback daemons, no host services or real notifications.')
        finally:
            poll_stop.set()
            for thread in pollers:thread.join(15);assert not thread.is_alive()
            for server in servers:server.should_exit=True
            for thread in threads:thread.join(15);assert not thread.is_alive()
            for adapter in adapters:adapter.close()
            for process in daemons:
                process.terminate()
                try:process.wait(timeout=10)
                except subprocess.TimeoutExpired:process.kill();process.wait()
            for log in logs:log.close()


if __name__=='__main__':main()
