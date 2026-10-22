"""Compare old/new idle-loop disk writes on synthetic temporary databases only."""
import argparse
from dataclasses import asdict
import importlib
import importlib.util
import io
import ipaddress
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


def counters():
    return {k:int(v.strip()) for k,v in (line.split(':',1) for line in Path('/proc/self/io').read_text().splitlines())}


def run(package, root, cycles):
    config = importlib.import_module(package+'.config').Config
    store_type = importlib.import_module(package+'.store').Store
    service_type = importlib.import_module(package+'.service').Service
    actor = importlib.import_module(package+'.domain').Actor('fixture','admin')
    reconcile = importlib.import_module(package+'.reconcile')
    replication = importlib.import_module(package+'.replication')
    cfg = config(database=str(root/'db.sqlite'),node_id='a',peer_node_id='b',tls=False,
                 protected_asns=(),protected_prefixes=(),announcements=True)
    store = store_type(cfg);service = service_type(store)
    rule = service.add_asn(actor,64500,'Synthetic benchmark only')
    prefixes = [str(ipaddress.ip_network((int(ipaddress.ip_address('198.18.0.0'))+n,32))) for n in range(664)]
    service.update_asn(actor,rule['id'],prefixes,name='Documentation fixture')
    paths = [reconcile.Path(str(n),p,cfg.v4_next_hop,cfg.local_pref,(cfg.community,),cfg.owner) for n,p in enumerate(prefixes)]
    class Adapter:
        def paths(self):return list(paths)
        def add(self,*args):raise AssertionError('Unexpected route addition')
        def delete(self,*args):raise AssertionError('Unexpected route deletion')
    class Transport:
        def handshake(self):return {"replication_protocol_version":3}
        def get(self,path,query=None):
            if path=='/replication/status':
                return {'replication_protocol_version':3,'node_id':'b','role':'slave','history':store.info()['history'],'sequence':store.info()['sequence']}
            if path=='/replication/local-audit':
                return {'node_id':'b','history':'00000000-0000-4000-8000-000000000001','events':[]}
            raise AssertionError(path)
    worker = reconcile.Reconciler(service,Adapter());peer = replication.Replicator(store,Transport())
    def cycle():
        worker.step()
        store.set_local('rib',{'at':time.time(),'paths':[{k:v for k,v in asdict(p).items() if k!='wire'} for p in paths],
                              'peers':[{'description':'Fixture','session_state':6}],
                              'export':{'192.0.2.10':{'prefixes':prefixes}}})
        peer.step()
    cycle()
    before=counters();started=time.monotonic();cpu=time.process_time()
    for _ in range(cycles):cycle()
    elapsed=time.monotonic()-started;cpu=time.process_time()-cpu;after=counters()
    return {'cycles':cycles,'wall_seconds':round(elapsed,3),'cpu_seconds':round(cpu,3),
            'write_bytes':after['write_bytes']-before['write_bytes'],'wchar':after['wchar']-before['wchar'],
            'db_bytes':Path(cfg.database).stat().st_size,'rule_count':len(store.list('rule')),
            'rib_paths':len(store.local('rib')['paths'])}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--baseline',default='00dea5b4b75ff234d73b3e01035889896a7136a6');parser.add_argument('--cycles',type=int,default=50)
    parser.add_argument('--directory',help='Temporary database parent; select a disk-backed filesystem for write_bytes')
    args=parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='hemlock-observation-benchmark-',dir=args.directory) as tmp:
        root=Path(tmp);old=root/'baseline';old.mkdir()
        raw=subprocess.check_output(['git','archive',args.baseline,'hemlock'])
        with tarfile.open(fileobj=io.BytesIO(raw)) as tar:tar.extractall(old,filter='data')
        name='old_observation_benchmark'
        spec=importlib.util.spec_from_file_location(name,old/'hemlock/__init__.py',submodule_search_locations=[str(old/'hemlock')])
        module=importlib.util.module_from_spec(spec);sys.modules[name]=module;spec.loader.exec_module(module)
        results={}
        for label,package in (('baseline',name),('memory','hemlock')):
            directory=root/label;directory.mkdir(exist_ok=True)
            results[label]=run(package,directory,args.cycles)
        assert results['memory']['rib_paths']==results['baseline']['rib_paths']==664
        assert results['memory']['rule_count']==results['baseline']['rule_count']==1
        assert results['memory']['wchar']<results['baseline']['wchar']
        results['write_reduction_percent']=(round(100*(1-results['memory']['write_bytes']/results['baseline']['write_bytes']),2)
                                           if results['baseline']['write_bytes'] else None)
        print(json.dumps(results,indent=2))


if __name__=='__main__':main()
