"""Isolated iBGP export/withdrawal/recovery acceptance against GoBGP 4.10.0."""
import argparse
from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.check_gobgp import port, wait_for
from hemloc.config import Config
from hemloc.domain import Actor
from hemloc.gobgp import GoBGP
from hemloc.service import Service
from hemloc.store import Store
from hemloc.reconcile import Reconciler
from hemloc.auth import password_hash
from hemloc.web import create_app
from hemloc.web import observe_bgp
from fastapi.testclient import TestClient


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--binary', required=True)
    parser.add_argument('--ttl', type=int, choices=(25,), help='Exercise the explicit iBGP TTL patch')
    parser.add_argument('--owned-policy', action='store_true', help='Verify owned-only import/export and SIGHUP reload')
    args = parser.parse_args()
    if os.geteuid() == 0:
        raise SystemExit("Run isolated test processes as an unprivileged user")
    binary = str(Path(args.binary).resolve())
    assert '4.10.0' in subprocess.check_output([binary, '--version'], text=True)
    with tempfile.TemporaryDirectory(prefix='hemloc-peer-') as tmp:
        directory = Path(tmp)
        ports = set()
        while len(ports) < 4:
            ports.add(port())
        ga, gb, ba, bb = ports
        configs, adapters, processes, logs = [], [], [], []
        try:
            for index, (address, remote, api, listen, remote_port) in enumerate([
                ('127.0.0.1', '127.0.0.2', ga, ba, bb),
                ('127.0.0.2', '127.0.0.1', gb, bb, ba),
            ]):
                path = directory / f'{index}.toml'
                path.write_text(f'''[global.config]
as = 64512
router-id = "{address}"
port = {listen}
local-address-list = ["{address}"]
[[neighbors]]
[neighbors.config]
neighbor-address = "{remote}"
peer-as = 64512
[neighbors.transport.config]
local-address = "{address}"
remote-port = {remote_port}
passive-mode = {str(index == 1).lower()}
[neighbors.timers.config]
connect-retry = 1
hold-time = 9
keepalive-interval = 3
[[neighbors.afi-safis]]
[neighbors.afi-safis.config]
afi-safi-name = "ipv4-unicast"
enabled = true
[[neighbors.afi-safis]]
[neighbors.afi-safis.config]
afi-safi-name = "ipv6-unicast"
enabled = true
''')
                if args.owned_policy and index == 0:
                    from tools.export_policy import owned_local_config
                    text=path.read_text().replace('[[neighbors]]', '[global.apply-policy.config]\nimport-policy-list = ["HEMLOC-DENY-ALL"]\nexport-policy-list = ["HEMLOC-DENY-ALL"]\ndefault-import-policy = "reject-route"\ndefault-export-policy = "reject-route"\n[[neighbors]]',1)
                    text+='\n[[policy-definitions]]\nname="HEMLOC-DENY-ALL"\n[[policy-definitions.statements]]\n[policy-definitions.statements.actions]\nroute-disposition="reject-route"\n'
                    path.write_text(owned_local_config(text,(64512,100,1)))
                if args.ttl:
                    with path.open('a') as output:
                        output.write(f'\n[neighbors.ebgp-multihop.config]\nenabled = true\nmultihop-ttl = {args.ttl}\n')
                log = (directory / f'{index}.log').open('ab')
                logs.append(log)
                command = [binary, '-f', str(path), f'--api-hosts=127.0.0.1:{api}']
                configs.append(command)
                processes.append(subprocess.Popen(command, stdout=log, stderr=log))
                cfg = Config(database=str(directory / f'{index}.sqlite'), tls=False,
                             grpc_target=f'127.0.0.1:{api}', announcements=True, protected_asns=(),
                             protected_prefixes=(), v4_next_hop='192.0.2.1', v6_next_hop='2001:db8::1', timeout=5)
                adapters.append(GoBGP(cfg))
            a, b = adapters
            def established():
                return all(x.observe()['peers'][0]['session_state'] == 6 for x in adapters)
            wait_for(established, 35)
            service = Service(Store(a.config))
            actor = Actor('lab', 'admin')
            wanted = {'192.0.2.254/32', '2001:db8:ffff::1/128'}
            rules = [service.add_manual(actor, p) for p in sorted(wanted)]
            rec = Reconciler(service, a)
            assert set(rec.step()['confirmed']) == wanted
            wait_for(lambda: {p.prefix for p in b.paths()} == wanted)
            if args.owned_policy:
                # Even a peer advertising our marker must fail the local-origin condition.
                b.add('203.0.113.252/32',rec.attributes('203.0.113.252/32'))
                time.sleep(1)
                assert not any(p.prefix=='203.0.113.252/32' for p in a.paths())
                b.delete(next(p for p in b.paths() if p.prefix=='203.0.113.252/32'))
                import signal
                processes[0].send_signal(signal.SIGHUP)
                time.sleep(1)
                assert established()
                assert {p.prefix for p in a.paths()} == wanted
            for p in b.paths():
                assert not p.local
                assert (p.next_hop, p.local_pref, p.communities) == rec.attributes(p.prefix)[:3]
            service.save_user(actor, 'lab', role='admin', password_hash=password_hash('Isolated-peer-password-123'))
            with TestClient(create_app(a.config, adapter=a, background=False)) as client:
                assert client.post('/api/login', json={'login':'lab', 'password':'Isolated-peer-password-123'}).status_code == 200
                observe_bgp(service.store, a)
                response = client.get('/api/observation')
                assert response.status_code == 200
                exported = response.json()['rib']['export']['127.0.0.2']
                assert not exported['truncated'] and set(exported['prefixes']) == {p.prefix for p in b.paths()}
            # The app lifespan closes its adapter; use a fresh observer afterward.
            a = GoBGP(a.config)
            adapters[0] = a
            rec = Reconciler(service, a)
            processes[1].kill()
            processes[1].wait(timeout=10)
            def disconnected():
                a.initialize()
                states = list(a.list_peers(a.m['ListPeerRequest'](), timeout=5))
                return states[0].peer.state.session_state != 6
            wait_for(disconnected)
            assert {p.prefix for p in a.paths()} == wanted
            processes[1] = subprocess.Popen(configs[1], stdout=logs[1], stderr=logs[1])
            wait_for(established, 35)
            wait_for(lambda: {p.prefix for p in b.paths()} == wanted)
            for rule in rules:
                service.delete_rule(actor, rule['id'])
            assert rec.step()['confirmed'] == []
            wait_for(lambda: not b.paths())
            wait_for(lambda: not a.observe()['export']['127.0.0.2']['prefixes'])
            print(json.dumps({'session':'iBGP AS64512, 127.0.0.1 <-> 127.0.0.2, ephemeral ports',
                              'received': sorted(wanted), 'attributes':'IPv4/IPv6 next-hop, local-pref 200, community 64512:666 verified at receiver',
                              'web_adj_rib_out':'matches receiver', 'restart':'session and both routes recovered',
                              'withdrawal':'receiver and Adj-RIB-Out empty'}, indent=2))
        finally:
            for process in processes:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
            for adapter in adapters:
                adapter.close()
            for log in logs:
                log.close()

if __name__ == '__main__':
    main()
