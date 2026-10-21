"""Synthetic scale acceptance; no operator configs or databases are loaded."""
import argparse
from dataclasses import replace
import gc
import ipaddress
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import tempfile
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.check_gobgp import port, wait_for
from hemlock.auth import password_hash
from hemlock.config import Config
from hemlock.domain import Actor
from hemlock.gobgp import GoBGP
from hemlock.reconcile import Reconciler
from hemlock.service import Service
from hemlock.store import Store, encode
from hemlock.web import create_app
from fastapi.testclient import TestClient


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--binary', required=True)
    parser.add_argument('--count', type=int, choices=(10000,100000), required=True)
    args = parser.parse_args()
    if os.geteuid() == 0:
        raise SystemExit("Run isolated test processes as an unprivileged user")
    binary = str(Path(args.binary).resolve())
    assert '4.10.0' in subprocess.check_output([binary,'--version'],text=True)
    report = {'prefixes':args.count, 'times_seconds':{}}
    def measured(name, action):
        start = time.monotonic()
        result = action()
        report['times_seconds'][name] = round(time.monotonic()-start,3)
        print(name,report['times_seconds'][name],file=sys.stderr,flush=True)
        return result
    with tempfile.TemporaryDirectory(prefix='hemlock-load-') as tmp:
        root = Path(tmp)
        gp,bp = port(),port()
        cfg = Config(database=str(root/'a.sqlite'),tls=False,node_id='a',peer_node_id='b',
                     protected_asns=(),protected_prefixes=(),metadata_enabled=False,announcements=True,
                     grpc_target=f'127.0.0.1:{gp}',timeout=120,v6_next_hop='2001:db8::1')
        master = Store(cfg)
        service = Service(master)
        actor = Actor('load','admin')
        service.save_user(actor,'load',role='admin',password_hash=password_hash('Load-test-password-123'))
        # Documentation IPv6 /32 supports 100k distinct host prefixes safely.
        base = int(ipaddress.IPv6Address('2001:db8::'))
        values = [f'{ipaddress.IPv6Address(base+i+1)}/128' for i in range(args.count)]
        def imports():
            for offset in range(0,len(values),1000):
                service.import_manual(actor,[{'value':p,'comment':'synthetic load'} for p in values[offset:offset+1000]])
        measured('import',imports)
        snapshot = measured('snapshot_export', master.snapshot)
        report['snapshot_bytes'] = len(encode(snapshot).encode())
        slave = Store(replace(cfg,database=str(root/'b.sqlite'),node_id='b',peer_node_id='a',role='slave'))
        measured('snapshot_install',lambda: slave.install_snapshot(snapshot))
        del snapshot
        gc.collect()
        rule = master.list('rule')[0]
        service.update_comment(actor,rule['id'],'journal update')
        batch = master.events(slave.info()['history'],slave.info()['sequence'])
        measured('journal_catchup',lambda: slave.apply_events(batch))
        assert slave.get('rule',rule['id']) == master.get('rule',rule['id'])
        matches = measured('ip_lookup',lambda: service.search('2001:db8::1'))
        assert len(matches) == 1
        with TestClient(create_app(cfg,adapter=object(),background=False)) as client:
            assert client.post('/api/login',json={'login':'load','password':'Load-test-password-123'}).status_code == 200
            response = measured('web_last_page',lambda: client.get(f'/api/rules?kind=manual&page_number={args.count//25}&size=25'))
            assert response.status_code == 200 and len(response.json()['items']) == 25
        toml = root/'gobgp.toml'
        toml.write_text(f'[global.config]\nas=64512\nrouter-id="127.0.0.1"\nport={bp}\nlocal-address-list=["127.0.0.1"]\n')
        adapter = GoBGP(cfg,service.protection().check)
        with (root/'gobgp.log').open('ab') as log:
            process = subprocess.Popen([binary,'-f',str(toml),f'--api-hosts=127.0.0.1:{gp}'],stdout=log,stderr=log)
            try:
                def ready():
                    adapter.paths()
                    return True
                wait_for(ready)
                rec = Reconciler(service,adapter)
                status = measured('gobgp_initial_apply',rec.step)
                assert len(status['confirmed']) == args.count
                measured('gobgp_no_change',rec.step)
                service.delete_rule(actor,rule['id'])
                status = measured('gobgp_one_withdrawal',rec.step)
                assert len(status['confirmed']) == args.count-1
                report['gobgp_rss_kib'] = int(next(line.split()[1] for line in Path(f'/proc/{process.pid}/status').read_text().splitlines() if line.startswith('VmRSS:')))
            finally:
                adapter.close()
                process.terminate()
                try:
                    process.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
        for name,store in [('master',master),('slave',slave)]:
            with store.connect() as db:
                db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
            report[name+'_db_bytes'] = Path(store.config.database).stat().st_size
        report['python_peak_rss_kib'] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        report['checks'] = 'normal service import, validated snapshot, journal, all-reason IP lookup, authenticated ASGI pagination, actual isolated gRPC apply/no-change/withdrawal'
    print(json.dumps(report,indent=2))

if __name__ == '__main__':
    main()
