"""Measure real HTTPS snapshot/journal on a running check_load temporary DB.

Run while check_load.py is in its GoBGP phase. The database must be that
harness's isolated /tmp tree. Only a synthetic rule comment is changed.
"""
import argparse
from dataclasses import replace
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import threading
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import uvicorn
from hemlock.config import Config
from hemlock.domain import Actor
from hemlock.replication import PeerTransport
from hemlock.service import Service
from hemlock.store import Store, digest
from hemlock.web import create_app
from tools.check_gobgp import port, wait_for

parser=argparse.ArgumentParser()
parser.add_argument('--database',required=True)
parser.add_argument('--journal-only',action='store_true')
args=parser.parse_args()
if os.geteuid() == 0:
    raise SystemExit("Run isolated test processes as an unprivileged user")
database=Path(args.database).resolve()
if database.parent.parent != Path('/tmp') or not database.parent.name.startswith('hemlock-load-') or database.name != 'a.sqlite':
    raise SystemExit('Only an active check_load.py temporary database is accepted')
with tempfile.TemporaryDirectory(prefix='hemlock-load-https-') as tmp:
    root=Path(tmp)
    cert,key=root/'cert.crt',root/'cert.key'
    subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-keyout',str(key),'-out',str(cert),
                    '-days','1','-subj','/CN=localhost','-addext','subjectAltName=IP:127.0.0.1'],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    token=root/'peer.token'
    token.write_text(secrets.token_urlsafe(48))
    token.chmod(0o600)
    listen=port()
    cfg=Config(database=str(database),node_id='a',peer_node_id='b',tls=True,cert=str(cert),key=str(key),
               token_file=str(token),protected_asns=(),metadata_enabled=False,timeout=120)
    server=uvicorn.Server(uvicorn.Config(create_app(cfg,adapter=object(),background=False),host='127.0.0.1',port=listen,
                                        ssl_certfile=str(cert),ssl_keyfile=str(key),access_log=False,log_level='error'))
    thread=threading.Thread(target=server.run)
    thread.start()
    report={}
    try:
        wait_for(lambda: server.started)
        slave_cfg=replace(cfg,database=str(root/'b.sqlite'),node_id='b',peer_node_id='a',role='slave',
                          peer_url=f'https://127.0.0.1:{listen}',ca=str(cert))
        transport=PeerTransport(slave_cfg)
        slave=Store(slave_cfg)
        if args.journal_only:
            master=Store(cfg,activate=False)
            info=master.info()
            # Sequence zero is this newly created lab history before its first write.
            payload={'schema':1,'history':info['history'],'sequence':0,'master_id':'a','documents':[]}
            slave.install_snapshot({'payload':payload,'digest':digest(payload)})
            start=time.monotonic()
            batches=0
            while slave.info()['sequence'] < master.info()['sequence']:
                cursor=slave.info()
                slave.apply_events(transport.get('/replication/events',{'history':cursor['history'],'cursor':cursor['sequence']}))
                batches+=1
            report['https_full_journal_fetch_apply_seconds']=round(time.monotonic()-start,3)
            report['batches']=batches
            with slave.connect() as local, master.connect() as upstream:
                counts=lambda db: dict(db.execute('SELECT kind,COUNT(*) FROM documents GROUP BY kind').fetchall())
                assert counts(local) == counts(upstream)
                report['documents']=counts(local)
            assert slave.list('user') == master.list('user')
            assert slave.info()['sequence'] == master.info()['sequence']
        else:
            start=time.monotonic()
            snapshot=transport.get('/replication/snapshot')
            report['https_snapshot_fetch_seconds']=round(time.monotonic()-start,3)
            start=time.monotonic()
            slave.install_snapshot(snapshot)
            report['snapshot_install_seconds']=round(time.monotonic()-start,3)
            report['rules']=len(slave.list('rule'))
            del snapshot
            service=Service(Store(cfg,activate=False))
            rule=service.store.list('rule')[0]
            service.update_comment(Actor('load','admin'),rule['id'],'HTTPS load journal update')
            start=time.monotonic()
            slave.apply_events(transport.get('/replication/events',{'history':slave.info()['history'],'cursor':slave.info()['sequence']}))
            report['https_journal_fetch_apply_seconds']=round(time.monotonic()-start,3)
            assert slave.get('rule',rule['id']) == service.store.get('rule',rule['id'])
            assert slave.info()['sequence'] == service.store.info()['sequence']
        report['tls']='self-signed CA and IP SAN validated; authenticated, direct transport'
        print(json.dumps(report,indent=2))
    finally:
        server.should_exit=True
        thread.join(timeout=20)
        assert not thread.is_alive()
