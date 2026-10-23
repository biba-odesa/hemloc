"""Old fixed release CA -> new CA -> explicit pinned TLS; isolated nodes only."""
from dataclasses import replace
from pathlib import Path
import io
import argparse
import subprocess
import sys
import tarfile
import tempfile
import threading
import json
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import uvicorn
from hemlock.config import load
from hemlock.domain import Actor
from hemlock.service import Service
from hemlock.store import Store
from hemlock.replication import Replicator,PeerTransport
from hemlock.web import create_app
from hemlock.tls import Trust,refresh_context,TLSFailure
from hemlock.tls_runtime import make_server
from tools.check_gobgp import port,wait_for

OLD='72443a50b944b8e49929ba8422add5feb157236e'


def main():
    with tempfile.TemporaryDirectory(prefix='hemlock-tls-legacy-') as tmp:
        root=Path(tmp);p1,p2=port(),port()
        while p1==p2:p2=port()
        subprocess.run([sys.executable,'tools/prepare_lab.py','--directory',str(root/'lab'),'--port-a',str(p1),'--port-b',str(p2)],check=True,stdout=subprocess.DEVNULL)
        from configparser import ConfigParser
        for name in ('a','b'):
            path=root/'lab'/f'{name}.ini';ini=ConfigParser(interpolation=None);ini.read(path)
            ini['gobgp']['grpc_target']=f'127.0.0.1:{port()}'
            with path.open('w') as f:ini.write(f)
        ca,cb=[load(str(root/'lab'/f'{name}.ini')) for name in ('a','b')]
        a=Store(ca);Service(a).add_manual(Actor('fixture','admin'),'192.0.2.6')
        old=root/'old';old.mkdir()
        export=subprocess.check_output(['git','archive',OLD])
        with tarfile.open(fileobj=io.BytesIO(export)) as t:t.extractall(old,filter='data')
        log=(root/'old.log').open('wb');process=None;servers=[];threads=[]
        subprocess.run([sys.executable,'-c',"import setuptools.build_meta as b; b.prepare_metadata_for_build_wheel('.')"],cwd=old,stdout=log,stderr=log,check=True)
        originals={p:p.read_bytes() for p in (Path(ca.cert),Path(ca.key),Path(cb.cert),Path(cb.key),Path(ca.ca),root/'lab/ca.key')}
        def start(config,pinned=False):
            server=make_server(config,adapter=object(),background=False) if pinned else uvicorn.Server(uvicorn.Config(create_app(config,adapter=object(),background=False),host=config.host,port=config.port,ssl_certfile=config.cert,ssl_keyfile=config.key,proxy_headers=False,access_log=False,log_level='error'))
            thread=threading.Thread(target=server.run);thread.start();servers.append(server);threads.append(thread);wait_for(lambda:server.started)
            return server
        try:
            process=subprocess.Popen([sys.executable,'-m','hemlock','--config',str(root/'lab/a.ini'),'serve'],cwd=old,stdout=log,stderr=log)
            transport=PeerTransport(cb)
            def old_ready():
                try:
                    identity=transport.handshake()
                    return identity['replication_protocol_version']==3 and identity['application_version']=='0.4.1'
                except Exception:return False
            wait_for(old_ready)
            bserver=start(cb);b=bserver.config.app.state.store
            Replicator(b,transport).step();assert len(b.list('rule'))==1
            history=b.info()['history']
            process.terminate();process.wait(15);process=None
            aserver=start(ca);a=aserver.config.app.state.store
            Service(a).add_manual(Actor('fixture','admin'),'2001:db8::6')
            Replicator(b,transport).step();assert len(b.list('rule'))==2
            for server,thread in zip(servers,threads):server.should_exit=True;thread.join(15)
            configs=[]
            for name,config in [('a',ca),('b',cb)]:
                configs.append(replace(config,tls_mode='pinned',tls_state_dir=str(root/(name+'tls')),cert=str(root/(name+'tls/identity/cert')),key=str(root/(name+'tls/identity/key'))))
            aserver=start(configs[0],True);bserver=start(configs[1],True)
            a,b=[s.config.app.state.store for s in (aserver,bserver)]
            ra,rb=Replicator(a,PeerTransport(configs[0])),Replicator(b,PeerTransport(configs[1]))
            try:rb.step();raise AssertionError('No approval accepted')
            except TLSFailure:pass
            for config,server in zip(configs,(aserver,bserver)):
                candidate=Trust(config).discover();Trust(config).approve(candidate['fingerprint']);refresh_context(config,server.config.ssl)
            rb.step();ra.step();rb.step()
            assert b.info()['history']==history==a.info()['history']
            assert a.list('rule')==b.list('rule') and len(b.list('rule'))==2
            for path,data in originals.items():assert path.read_bytes()==data
            print('PASS: actual fixed 0.4.1 master + new slave in legacy CA mode; master update retains history; explicit switch both to pinned pauses until independent approval, then journal resumes; protocol 3 unchanged; original CA keys/certs untouched; only own loopback nodes.')
        finally:
            if process:process.terminate();process.wait(15)
            for server in servers:server.should_exit=True
            for thread in threads:thread.join(15)
            log.close()


if __name__=='__main__':main()
