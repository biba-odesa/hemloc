"""Mixed previous/canonical peer-header rejection over verified test HTTPS."""
import importlib.util
import argparse
from dataclasses import asdict,replace
import io
from pathlib import Path
import secrets
import ssl
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import uuid
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import httpx
import uvicorn
from hemlock.auth import password_hash
from hemlock.batch import add
from hemlock.config import Config
from hemlock.domain import Actor
from hemlock.replication import PeerTransport,Replicator
from hemlock.retention import execute,preview
from hemlock.service import Service
from hemlock.store import Store
from hemlock.web import create_app
from tools.check_gobgp import port,wait_for


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--baseline',default='779594070fe922c21efe7284d812c4cf1fbb0050')
    parser.add_argument('--package',choices=('hemlock',),default='hemlock')
    args=parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='hemlock-rolling-') as tmp:
        root=Path(tmp);legacy=root/'legacy';legacy.mkdir()
        raw=subprocess.check_output(['git','archive',args.baseline,args.package])
        with tarfile.open(fileobj=io.BytesIO(raw)) as tar:tar.extractall(legacy,filter='data')
        name='pre_rename_compatibility';spec=importlib.util.spec_from_file_location(name,legacy/args.package/'__init__.py',submodule_search_locations=[str(legacy/args.package)])
        module=importlib.util.module_from_spec(spec);sys.modules[name]=module;spec.loader.exec_module(module)
        old={part:importlib.import_module(name+'.'+part) for part in ('config','store','web','replication')}
        subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','1','-keyout',str(root/'tls.key'),'-out',str(root/'tls.crt'),'-subj','/CN=localhost','-addext','subjectAltName=IP:127.0.0.1'],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        (root/'secret').write_text(secrets.token_urlsafe(48));p1,p2=port(),port()
        cfg=Config(database=str(root/'a.sqlite'),node_id='a',peer_node_id='b',peer_url=f'https://127.0.0.1:{p2}',host='127.0.0.1',port=p1,cert=str(root/'tls.crt'),key=str(root/'tls.key'),ca=str(root/'tls.crt'),token_file=str(root/'secret'),protected_asns=(),metadata_enabled=False)
        bcfg_values=asdict(replace(cfg,role='slave',node_id='b',peer_node_id='a',database=str(root/'b.sqlite'),port=p2,peer_url=f'https://127.0.0.1:{p1}'))
        import dataclasses
        bcfg=old['config'].Config(**{k:v for k,v in bcfg_values.items() if k in {f.name for f in dataclasses.fields(old['config'].Config)}})
        a,b=Store(cfg),old['store'].Store(bcfg);actor=Actor('fixture','admin');password='a1'+secrets.token_urlsafe(24)
        Service(a).save_user(actor,'viewer',role='guest',password_hash=password_hash(password))
        with a.transaction() as db:
            doc={'id':str(uuid.uuid4()),'at':time.time()-10*86400,'node':'a','actor':'anonymous','action':'http.request','object':'request','before':None,'after':None,'result':'invalid'}
            op={'kind':'audit','id':doc['id'],'doc':doc};a.operation(db,op);a.append_journal(db,[op])
        b.install_snapshot(a.snapshot());servers=[];threads=[]
        try:
            for config,app in ((cfg,create_app(cfg,adapter=object(),background=False)),(bcfg,old['web'].create_app(bcfg,adapter=object(),background=False))):
                server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=config.port,ssl_certfile=config.cert,ssl_keyfile=config.key,proxy_headers=False,access_log=False,log_level='error'))
                thread=threading.Thread(target=server.run);thread.start();servers.append(server);threads.append(thread);wait_for(lambda:server.started)
            ar=Replicator(a,PeerTransport(cfg));br=old['replication'].Replicator(b,old['replication'].PeerTransport(bcfg))
            from hemlock.replication import PeerUnavailable
            from hemlock.protocol import ProtocolFailure
            try:ar.step()
            except (PeerUnavailable,ProtocolFailure):pass
            assert a.local('sync',{}).get('ok') is False
            assert a.info()['role']=='master' and b.info()['role']=='slave'
            assert a.info()['history']==b.info()['history']
            assert a.list('rule')==b.list('rule')
            print('PASS: mixed canonical/previous handshake/protocol are rejected without changing role, generation or rules. Coordinate both-node upgrade before replication resumes.')
        finally:
            for server in servers:server.should_exit=True
            for thread in threads:thread.join(15);assert not thread.is_alive()


if __name__=='__main__':main()
