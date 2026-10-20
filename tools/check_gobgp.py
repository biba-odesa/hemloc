"""Run explicitly authorized, isolated GoBGP 4.10.0 lifecycle checks.

The runner creates its own peer-free daemon on loopback ephemeral ports.
It never attaches to an existing daemon or loads an operator configuration.
"""

import argparse
from dataclasses import replace
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hemloc.config import Config
from hemloc.domain import Actor, Conflict
from hemloc.gobgp import GoBGP, nlri, unicast_attributes
from hemloc.reconcile import Reconciler
from hemloc.service import Service
from hemloc.store import Store


def port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0))
        return sock.getsockname()[1]


def wait_for(function, timeout=20):
    deadline = time.monotonic() + timeout
    while True:
        try:
            result = function()
            if result:
                return result
        except Exception:
            pass
        if time.monotonic() >= deadline:
            raise AssertionError('Timed out waiting for isolated GoBGP')
        time.sleep(0.1)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--binary', required=True, help='Explicit path to verified gobgpd 4.10.0')
    parser.add_argument('--suite', action='store_true', help='Run the full unit/ASGI/live suite against this isolated daemon')
    parser.add_argument('--cli', action='store_true', help='Also exercise root maintenance via sudo -n')
    args = parser.parse_args()
    if os.geteuid() == 0:
        raise SystemExit('Run isolated daemon tests as an unprivileged user')
    binary = str(Path(args.binary).resolve())
    version = subprocess.check_output([binary,'--version'],text=True)
    import re
    if not re.search(r'(?<![\d.])4\.10\.0(?![\d.])',version):
        raise SystemExit('Expected exactly GoBGP 4.10.0')
    for key in ('HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','http_proxy','https_proxy','all_proxy'):
        os.environ[key]='http://127.0.0.1:9'
    os.environ.update(NO_PROXY='',no_proxy='')
    os.umask(0o077)
    grpc_port, bgp_port = port(), port()
    while grpc_port == bgp_port:
        bgp_port = port()
    with tempfile.TemporaryDirectory(prefix='hemloc-gobgp-') as temporary:
        directory = Path(temporary)
        daemon_config = directory/'gobgpd.toml'
        daemon_config.write_text(f'[global.config]\nas = 64512\nrouter-id = "127.0.0.1"\nport = {bgp_port}\nlocal-address-list = ["127.0.0.1"]\n')
        process = None
        adapter = None
        foreign = None
        log = (directory/'gobgpd.log').open('ab')
        def start():
            return subprocess.Popen([binary,'-f',str(daemon_config),f'--api-hosts=127.0.0.1:{grpc_port}'],stdout=log,stderr=log)
        def stop():
            nonlocal process
            if process is not None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                process = None
        def peer_free():
            observed = adapter.observe()
            if observed['peers']:
                raise AssertionError('Unexpected neighbors in isolated daemon')
            return True
        try:
            marker = (64512,100,secrets.randbelow(2**31)+2)
            cfg = Config(tls=False,database=str(directory/'controller.sqlite'),announcements=True,
                         grpc_target=f'127.0.0.1:{grpc_port}',protected_asns=(),timeout=2,
                         v6_next_hop='2001:db8::1',owner=marker)
            service = Service(Store(cfg))
            adapter = GoBGP(cfg, lambda p: service.protection().check(p))
            foreign = GoBGP(replace(cfg,owner=(marker[0],marker[1],marker[2]+1)))
            process = start()
            wait_for(peer_free)
            admin = Actor('lab:integration','admin')
            rules = [service.add_manual(admin,p) for p in ('192.0.2.254/32','2001:db8:ffff::1/128')]
            wanted = {r['prefixes'][0] for r in rules}
            foreign_prefix = '198.51.100.254/32'
            foreign.add(foreign_prefix,('192.0.2.254',99,('666:99',),foreign.config.owner))
            foreign_key = next(p.key for p in foreign.paths() if p.prefix == foreign_prefix)
            reconciler = Reconciler(service,adapter)
            assert set(reconciler.step()['confirmed']) == wanted
            assert any(p.key == foreign_key for p in adapter.paths())
            for route in adapter.paths():
                if route.owner == marker:
                    attrs = reconciler.attributes(route.prefix)
                    assert reconciler.matches(route,attrs)
            damaged = next(p for p in adapter.paths() if p.owner == marker and p.prefix.startswith('192.'))
            adapter.delete(damaged)
            adapter.add(damaged.prefix,('192.0.2.1',99,('666:99',),marker))
            assert set(reconciler.step()['confirmed']) == wanted
            extra = service.add_manual(admin,'203.0.113.254/32')
            rules.append(extra)
            wanted.add(extra['prefixes'][0])
            class CrashAfterAdd:
                def paths(inner):
                    return adapter.paths()
                def delete(inner,path):
                    return adapter.delete(path)
                def add(inner,candidate,attrs):
                    adapter.add(candidate,attrs)
                    raise RuntimeError('Injected crash after successful gRPC AddPath')
            try:
                Reconciler(service,CrashAfterAdd()).step()
                raise AssertionError('Crash injection did not run')
            except RuntimeError:
                pass
            adapter.close()
            adapter = GoBGP(cfg, lambda p: service.protection().check(p))
            reconciler = Reconciler(Service(Store(cfg)),adapter)
            assert set(reconciler.step()['confirmed']) == wanted
            assert len([p for p in adapter.paths() if p.owner == marker]) == len(wanted)
            stop()
            process = start()
            wait_for(peer_free)
            assert adapter.paths() == []
            assert set(reconciler.step()['confirmed']) == wanted
            foreign.add(foreign_prefix,('192.0.2.254',99,('666:99',),foreign.config.owner))
            foreign_key = next(p.key for p in foreign.paths() if p.prefix == foreign_prefix)
            changed = Service(Store(replace(cfg,protected_prefixes=cfg.protected_prefixes + ('192.0.2.254/32',))))
            protected_reconciler = Reconciler(changed,adapter)
            assert '192.0.2.254/32' not in protected_reconciler.step()['confirmed']
            assert not any(p.prefix == '192.0.2.254/32' and p.owner == marker for p in adapter.paths())
            for rule in rules:
                service.delete_rule(admin,rule['id'])
            protected_reconciler.step()
            assert not any(p.owner == marker for p in adapter.paths())
            assert any(p.key == foreign_key for p in adapter.paths())
            service.add_manual(admin,foreign_prefix)
            try:
                protected_reconciler.step()
                raise AssertionError('Foreign local prefix collision was accepted')
            except Conflict:
                pass
            assert any(p.key == foreign_key for p in adapter.paths())
            # Inject two distinct local path IDs at one NLRI through the raw test
            # stub, then prove addressed withdrawal preserves the foreign path.
            shared_prefix = '203.0.113.253/32'
            adapter.add(shared_prefix,('192.0.2.254',200,('64512:666',),marker))
            foreign.initialize()
            raw = foreign.m['Path'](family=foreign.m['Family'](afi=1,safi=1),identifier=foreign.identifier,
                                   nlri_binary=nlri(shared_prefix),
                                   pattrs_binary=unicast_attributes(shared_prefix,('192.0.2.254',99,('666:99',),foreign.config.owner)))
            foreign.add_path(foreign.m['AddPathRequest'](table_type=1,path=raw),timeout=cfg.timeout)
            same_nlri = [p for p in adapter.paths() if p.prefix == shared_prefix]
            assert len(same_nlri) == 2
            adapter.delete(next(p for p in same_nlri if p.owner == marker))
            remaining = [p for p in foreign.paths() if p.prefix == shared_prefix]
            assert len(remaining) == 1 and remaining[0].owner == foreign.config.owner
            foreign.delete(remaining[0])
            # Exercise the explicit maintenance drain against real addressed paths.
            from hemloc.maintenance import withdraw_owned
            adapter.add('192.0.2.253/32', ('192.0.2.254',200,('64512:666',),marker))
            disabled = Store(replace(cfg, announcements=False), activate=False)
            assert withdraw_owned(disabled)['owned'] == 1
            if args.cli:
                cli_config = directory/'maintenance.ini'
                cli_config.write_text(f'[node]\ndatabase={cfg.database}\n[web]\ntls=no\n[gobgp]\nannouncements=no\ngrpc_target={cfg.grpc_target}\nowner={",".join(map(str,marker))}\n')
                import json
                command = ['sudo','-n',sys.executable,'-m','hemloc','--config',str(cli_config),'routes','withdraw-owned']
                preview = json.loads(subprocess.check_output(command,text=True))
                assert preview['mode'] == 'dry-run' and preview['owned'] == 1
                executed = json.loads(subprocess.check_output(command+['--execute'],text=True))
                assert executed['withdrawn'] == 1
                adapter.add('192.0.2.253/32', ('192.0.2.254',200,('64512:666',),marker))
            assert withdraw_owned(disabled, execute=True)['withdrawn'] == 1
            assert withdraw_owned(disabled, execute=True)['withdrawn'] == 0
            assert any(p.key == foreign_key for p in adapter.paths())
            if args.suite:
                environment = dict(os.environ,HEMLOC_LIVE_GOBGP=cfg.grpc_target)
                subprocess.run([sys.executable,'-W','error::ResourceWarning','-m','unittest','discover','-s','tests','-v'],
                               env=environment,check=True)
            print('GoBGP 4.10.0 checks passed: IPv4/IPv6 gRPC attributes, foreign ownership, repair, crash recovery, daemon restart, protection withdrawal and addressed path deletion.')
            print('No BGP neighbors were configured; downstream export/acceptance is not certified.')
        finally:
            stop()
            if adapter is not None:
                adapter.close()
            if foreign is not None:
                foreign.close()
            log.close()


if __name__ == '__main__':
    main()
