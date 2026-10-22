"""Real gRPC startup demotion on own loopback daemons and synthetic DBs only."""
from dataclasses import replace
from pathlib import Path
import argparse
import json
import subprocess
import sys
import tempfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from hemlock.config import Config
from hemlock.domain import Actor,Conflict
from hemlock.gobgp import GoBGP
from hemlock.reconcile import Reconciler
from hemlock.service import Service
from hemlock.store import Store
from hemlock.transition import RoleTransition
from tools.check_gobgp import port,wait_for


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--binary',required=True);args=parser.parse_args()
    binary=str(Path(args.binary).resolve())
    assert 'version 4.10.0' in subprocess.check_output([binary,'--version'],text=True)
    with tempfile.TemporaryDirectory(prefix='hemlock-role-grpc-') as temporary:
        root=Path(temporary);grpc_port,bgp_port=port(),port();assert grpc_port!=bgp_port
        conf=root/'gobgp.toml';conf.write_text(f'[global.config]\nas = 64512\nrouter-id = "127.0.0.1"\nport = {bgp_port}\nlocal-address-list = ["127.0.0.1"]\n')
        process=None;adapters=[]
        cfg=Config(tls=False,database=str(root/'node.sqlite'),node_id='a',peer_node_id='b',
                   grpc_target=f'127.0.0.1:{grpc_port}',timeout=1,announcements=True,
                   protected_asns=(),protected_prefixes=(),v6_next_hop='2001:db8::1')
        def adapter(config):
            obj=GoBGP(config);adapters.append(obj);return obj
        def start():
            nonlocal process
            process=subprocess.Popen([binary,'-f',str(conf),f'--api-hosts=127.0.0.1:{grpc_port}'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            probe=adapter(cfg);wait_for(lambda:probe.observe()['peers']==[])
        def stop():
            if process and process.poll() is None:process.terminate();process.wait(timeout=10)
        def seed(config):
            db=Store(config);service=Service(db);a=Actor('fixture','admin')
            service.add_manual(a,'192.0.2.1');service.add_manual(a,'2001:db8::1')
            service.store.set_local('protection',{'prefixes':['203.0.113.0/24'],'success':{}})
            rpc=adapter(config);Reconciler(service,rpc).step()
            foreign=adapter(replace(config,owner=(64512,100,99),database=str(root/'external.sqlite')))
            foreign.add('198.51.100.1/32',(config.v4_next_hop,200,(config.community,),foreign.config.owner))
            assert len(rpc.paths())==3
            return db
        authority=Store(replace(cfg,node_id='b',peer_node_id='a',database=str(root/'authority.sqlite')))
        Service(authority).add_manual(Actor('fixture','admin'),'198.51.100.5')
        try:
            start();pid=process.pid;seed(cfg)
            slave_cfg=replace(cfg,role='slave',announcements=False)
            rpc=adapter(slave_cfg);transition=RoleTransition(slave_cfg);transition.prepare(rpc)
            assert rpc.paths()==[] and process.pid==pid and process.poll() is None
            slave=Store(slave_cfg);assert slave.list('rule')==[] and slave.local('protection')['prefixes']
            slave.install_snapshot(authority.snapshot())
            active=replace(slave_cfg,announcements=True)
            Reconciler(Service(Store(active)),adapter(active)).step()
            assert {p.prefix for p in rpc.paths()}=={'198.51.100.5/32'}
            # The stopped-daemon evidence here comes from the harness's own child,
            # not the host's production unit or process table.
            stop();cfg2=replace(cfg,database=str(root/'absent.sqlite'));old=Store(cfg2)
            Service(old).add_manual(Actor('fixture','admin'),'192.0.2.1')
            slave2=replace(cfg2,role='slave');rpc2=adapter(slave2)
            rpc2.confirmed_absent=lambda:process.poll() is not None
            transition2=RoleTransition(slave2);transition2.prepare(rpc2)
            assert transition2.read()['cleanup_required'] and Store(slave2).list('rule')==[]
            Store(slave2).install_snapshot(authority.snapshot())
            try:Reconciler(Service(Store(slave2)),rpc2).step();raise AssertionError('Absent daemon bypassed fence')
            except Conflict:pass
            start();injector=adapter(replace(cfg2,database=str(root/'external-2.sqlite')))
            injector.add('192.0.2.1/32',(cfg.v4_next_hop,200,(cfg.community,),cfg.owner))
            Reconciler(Service(Store(slave2)),rpc2).step()
            assert transition2.read()['phase']=='complete'
            assert {p.prefix for p in rpc2.paths()}=={'198.51.100.5/32'}
            # An unavailable endpoint without independent evidence is uncertain.
            stop();cfg3=replace(cfg,database=str(root/'uncertain.sqlite'));old3=Store(cfg3)
            Service(old3).add_manual(Actor('fixture','admin'),'192.0.2.1')
            slave3=replace(cfg3,role='slave');rpc3=adapter(slave3);rpc3.confirmed_absent=lambda:False
            try:RoleTransition(slave3).prepare(rpc3);raise AssertionError('Uncertain endpoint accepted')
            except Conflict:pass
            with old3.connect() as db:assert old3.meta(db,'role')=='master'
            start();RoleTransition(slave3).prepare(rpc3);assert Store(slave3).list('rule')==[]
            # Fail after a real addressed deletion, then resume against the same daemon.
            cfg4=replace(cfg,database=str(root/'partial.sqlite'));seed(cfg4)
            slave4=replace(cfg4,role='slave');rpc4=adapter(slave4);rpc4.paths();delete=rpc4.delete_path
            rpc4.confirmed_absent=lambda:False
            def partial(*a,**k):delete(*a,**k);raise OSError('simulated post-delete interruption')
            rpc4.delete_path=partial;pid=process.pid
            try:RoleTransition(slave4).prepare(rpc4);raise AssertionError('Partial drain accepted')
            except Conflict:pass
            assert len(rpc4.paths())==2
            rpc4.delete_path=delete;RoleTransition(slave4).prepare(rpc4)
            assert rpc4.paths()==[] and process.pid==pid and process.poll() is None
            print('PASS real GoBGP: IPv4/IPv6 + unmarked-owner addressed drain with announcements=no; unchanged daemon PID; fresh slave snapshot; stopped-daemon deferred cleanup before new routes; uncertain gRPC refusal; post-delete failure/resume. Only own peer-free loopback daemons, no host services accessed.')
        finally:
            stop()
            for obj in adapters:obj.close()


if __name__=='__main__':main()
