"""Verified HTTPS compatibility: renamed master and actual pre-rename slave sources."""
import importlib.util
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
    with tempfile.TemporaryDirectory(prefix='hemlock-rolling-') as tmp:
        root=Path(tmp);legacy=root/'legacy';legacy.mkdir()
        raw=subprocess.check_output(['git','archive','cefb7a49c2679a9d95f0c3abc566ecaf4b3530a3','hemloc'])
        with tarfile.open(fileobj=io.BytesIO(raw)) as tar:tar.extractall(legacy,filter='data')
        name='pre_rename_compatibility';spec=importlib.util.spec_from_file_location(name,legacy/'hemloc/__init__.py',submodule_search_locations=[str(legacy/'hemloc')])
        module=importlib.util.module_from_spec(spec);sys.modules[name]=module;spec.loader.exec_module(module)
        old={part:importlib.import_module(name+'.'+part) for part in ('config','store','web','replication')}
        subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','1','-keyout',str(root/'tls.key'),'-out',str(root/'tls.crt'),'-subj','/CN=localhost','-addext','subjectAltName=IP:127.0.0.1'],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        (root/'secret').write_text(secrets.token_urlsafe(48));p1,p2=port(),port()
        cfg=Config(database=str(root/'a.sqlite'),node_id='a',peer_node_id='b',peer_url=f'https://127.0.0.1:{p2}',host='127.0.0.1',port=p1,cert=str(root/'tls.crt'),key=str(root/'tls.key'),ca=str(root/'tls.crt'),token_file=str(root/'secret'),protected_asns=(),metadata_enabled=False)
        bcfg=old['config'].Config(**asdict(replace(cfg,role='slave',node_id='b',peer_node_id='a',database=str(root/'b.sqlite'),port=p2,peer_url=f'https://127.0.0.1:{p1}')))
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
            ar.step();br.step();ar.step()
            result=add(Service(a),actor,'192.0.2.1,2001:db8::1,invalid-fixture','Rolling rename')
            assert result['added']==2
            br.step();ar.step();assert a.list('rule')==b.list('rule')
            with httpx.Client(verify=ssl.create_default_context(cafile=cfg.ca),trust_env=False) as client:
                signed=client.post(f'https://127.0.0.1:{p2}/api/login',json={'login':'viewer','password':password});assert signed.status_code==200
                assert 'hemloc_session' in client.cookies
            ar.step();br.step();ar.step()
            assert any(e['node']=='b' and e['action']=='auth.login' for e in a.audit_history())
            execute(a,preview(a));br.step();ar.step()
            assert a.list('audit')==b.list('audit');assert a.get('audit',doc['id']) is None
            b.install_snapshot(a.snapshot());assert a.list('audit')==b.list('audit')
            print('PASS: renamed master + actual cefb7a4 slave over verified HTTPS; unchanged header/cookie/node IDs, partial batch journal, slave auth outbox, prune-v2 and schema-2 snapshot. No working nodes contacted.')
        finally:
            for server in servers:server.should_exit=True
            for thread in threads:thread.join(15);assert not thread.is_alive()


if __name__=='__main__':main()
