"""Explicitly invoked HTTPS two-process acceptance smoke test.

GoBGP is launched only with --gobgp-binary, using fresh peer-free daemons.
No systemd or production configuration is used.
"""

import argparse
from configparser import ConfigParser
from dataclasses import replace
import getpass
import json
import os
from pathlib import Path
import ssl
import socket
import secrets
import subprocess
import sys
import time
from http.cookiejar import CookieJar
from urllib.error import HTTPError, URLError
from urllib.request import HTTPCookieProcessor, HTTPSHandler, ProxyHandler, Request, build_opener

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hemlock.auth import password_hash
from hemlock.config import load
from hemlock.domain import Actor
from hemlock.service import Service
from hemlock.store import Store


class Client:
    def __init__(self, config):
        self.base = f'https://127.0.0.1:{config.port}'
        self.opener = build_opener(ProxyHandler({}), HTTPSHandler(context=ssl.create_default_context(cafile=config.ca)), HTTPCookieProcessor(CookieJar()))
        self.csrf = ''

    def call(self, path, method='GET', body=None, headers=None):
        request = Request(self.base + path, method=method, headers=headers or {})
        if method != 'GET':
            request.add_header('Content-Type', 'application/json')
            request.add_header('X-CSRF-Token', self.csrf)
            request.data = json.dumps(body or {}).encode()
        with self.opener.open(request, timeout=5) as response:
            return json.load(response)

    def login(self, login, password):
        self.csrf = self.call('/api/login', 'POST', {'login':login, 'password':password})['csrf']


def eventually(fn, timeout=25):
    deadline = time.monotonic() + timeout
    while True:
        try:
            result = fn()
            if result:
                return result
        except (HTTPError, URLError, OSError, KeyError):
            pass
        if time.monotonic() >= deadline:
            raise AssertionError('Timed out waiting for integration condition')
        time.sleep(0.1)


def role(path, value):
    ini = ConfigParser(interpolation=None)
    ini.read(path)
    ini['node']['role'] = value
    with path.open('w') as output:
        ini.write(output)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--directory', default='var/lab')
    parser.add_argument('--cli', action='store_true', help='Exercise the authorized root CLI through sudo and a real PTY')
    parser.add_argument('--gobgp-binary',help='Enable routing checks only in two fresh isolated peer-free daemons')
    args = parser.parse_args()
    if os.geteuid() == 0:
        raise SystemExit('Run the lab as an unprivileged user')
    os.umask(0o077)
    directory = Path(args.directory).resolve()
    paths = {name: directory/f'{name}.ini' for name in ('a','b')}
    configs = {name: load(path) for name,path in paths.items()}
    for config in configs.values():
        if config.announcements or config.host != '127.0.0.1' or config.protected_asns or config.metadata_enabled:
            raise SystemExit('Refusing a non-isolated lab configuration')
        if Path(config.database).exists():
            raise SystemExit('Use a fresh prepared lab; databases must not already exist')
    daemon_specs,daemon_processes,daemon_logs,adapters={},{},{},{}
    if args.gobgp_binary:
        from hemlock.gobgp import GoBGP
        from tools.check_gobgp import port
        binary=str(Path(args.gobgp_binary).resolve())
        assert 'version 4.10.0' in subprocess.check_output([binary,'--version'],text=True)
        used={c.port for c in configs.values()}
        def unique_port():
            value=port()
            while value in used:
                value=port()
            used.add(value)
            return value
        for name in configs:
            grpc_port,bgp_port=unique_port(),unique_port()
            ini=ConfigParser(interpolation=None)
            ini.read(paths[name])
            ini['gobgp'].update(announcements='yes',grpc_target=f'127.0.0.1:{grpc_port}')
            ini['gobgp_ipv6']['next_hop']='2001:db8::1'
            with paths[name].open('w') as output:
                ini.write(output)
            configs[name]=load(paths[name])
            daemon_config=directory/f'gobgp-{name}.toml'
            daemon_config.write_text(f'[global.config]\nas = 64512\nrouter-id = "127.0.0.1"\nport = {bgp_port}\nlocal-address-list = ["127.0.0.1"]\n')
            daemon_specs[name]=[binary,'-f',str(daemon_config),f'--api-hosts=127.0.0.1:{grpc_port}']
            adapters[name]=GoBGP(configs[name])
    first = getpass.getpass('Temporary lab password: ')
    if first != getpass.getpass('Repeat temporary lab password: '):
        raise SystemExit('Passwords do not match')
    hashed = password_hash(first)
    checked_passwords = [first]
    service = Service(Store(configs['a']))
    admin = Actor('lab:bootstrap', 'admin')
    for login,user_role in [('lab-admin','admin'),('lab-guest','guest')]:
        service.save_user(admin, login, role=user_role, password_hash=hashed)
    processes, logs = {}, {}
    token = (directory/'peer.token').read_text().strip()
    def ready(name, client, history=None):
        other = 'b' if name == 'a' else 'a'
        status = client.call('/replication/status', headers={'Authorization':'Bearer '+token, 'X-Hemloc-Node':f'block-{other}'})
        return bool(status['history']) and (history is None or status['history'] == history)
    def start(name):
        logs[name] = (directory/f'{name}.log').open('ab')
        environment=dict(os.environ)
        for key in ('HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','http_proxy','https_proxy','all_proxy'):
            environment[key]='http://127.0.0.1:9'
        environment.update(NO_PROXY='',no_proxy='')
        processes[name] = subprocess.Popen([sys.executable, '-m', 'hemlock', '--config', str(paths[name]), 'serve'],
                                          cwd=Path(__file__).resolve().parents[1], stdout=logs[name], stderr=logs[name],env=environment)
    def stop(name):
        process = processes.pop(name, None)
        if process:
            process.terminate()
            try:
                process.wait(timeout=40)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        if name in logs:
            logs.pop(name).close()
    def start_daemon(name):
        daemon_logs[name]=(directory/f'gobgp-{name}.log').open('ab')
        daemon_processes[name]=subprocess.Popen(daemon_specs[name],stdout=daemon_logs[name],stderr=daemon_logs[name])
    def stop_daemon(name):
        process=daemon_processes.pop(name,None)
        if process:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill(); process.wait()
        if name in daemon_logs:
            daemon_logs.pop(name).close()
    def bgp_equals(name,prefixes):
        try:
            return {p.prefix for p in adapters[name].paths() if p.local and p.owner==configs[name].owner}==set(prefixes)
        except Exception:
            return False
    try:
        for name in daemon_specs:
            start_daemon(name)
            def daemon_ready(name=name):
                try:
                    return adapters[name].observe()['peers']==[]
                except Exception:
                    return False
            eventually(daemon_ready)
        start('a')
        start('b')
        a, b = Client(configs['a']), Client(configs['b'])
        eventually(lambda: ready('a', a))
        a.login('lab-admin',first)
        eventually(lambda: ready('b', b, a.call('/api/observation')['local']['history']))
        b.login('lab-admin',first)
        assert a.call('/api/me')['node_role'] == 'master'
        assert b.call('/api/me')['node_role'] == 'slave'
        # Verify TLS authentication with real handshakes, without disabling checks.
        try:
            untrusted = build_opener(ProxyHandler({}),HTTPSHandler(context=ssl.create_default_context()))
            untrusted.open(a.base+'/',timeout=5)
            raise AssertionError('Untrusted CA was accepted')
        except URLError as exc:
            assert isinstance(exc.reason,ssl.SSLCertVerificationError)
        try:
            context = ssl.create_default_context(cafile=configs['a'].ca)
            with socket.create_connection(('127.0.0.1',configs['a'].port),timeout=5) as plain:
                with context.wrap_socket(plain,server_hostname='wrong-name.invalid'):
                    raise AssertionError('Wrong certificate hostname was accepted')
        except ssl.SSLCertVerificationError:
            pass
        try:
            a.call('/replication/status',headers={'Authorization':'Bearer rejected-test-value','X-Hemloc-Node':'block-b'})
            raise AssertionError('Invalid peer token was accepted')
        except HTTPError as exc:
            assert exc.code == 403
        result = a.call('/api/rules/manual','POST',{'value':'192.0.2.0/24','comment':'lab <script>text</script>'})
        rule_id = result['rule']['id']
        eventually(lambda: any(r['id']==rule_id for r in b.call('/api/rules')['items']))
        peer_headers = {'Authorization':'Bearer '+token,'X-Hemloc-Node':'block-b'}
        snapshot = a.call('/replication/snapshot',headers=peer_headers)
        after_snapshot = a.call('/api/rules/manual','POST',{'value':'198.51.100.0/24'})['rule']
        from urllib.parse import urlencode
        query = urlencode({'history':snapshot['payload']['history'],'cursor':snapshot['payload']['sequence']})
        journal = a.call('/replication/events?'+query,headers=peer_headers)
        verifier = Store(replace(configs['b'],database=str(directory/'snapshot-check.sqlite')))
        verifier.install_snapshot(snapshot)
        verifier.apply_events(journal)
        verifier.apply_events(journal)
        assert verifier.get('rule',after_snapshot['id']) == after_snapshot
        assert verifier.get('rule',rule_id) is not None
        a.call('/api/rules/'+after_snapshot['id'],'DELETE')
        eventually(lambda: b.call('/api/rules')['total'] == 1)
        if adapters:
            eventually(lambda: bgp_equals('a',{'192.0.2.0/24'}) and bgp_equals('b',{'192.0.2.0/24'}))
            stop('b')
            ini=ConfigParser(interpolation=None)
            ini.read(paths['b'])
            ini['protection']['protected_prefixes']+=',192.0.2.0/24'
            with paths['b'].open('w') as output:
                ini.write(output)
            start('b')
            eventually(lambda: ready('b',b))
            b.login('lab-admin',first)
            eventually(lambda: bgp_equals('b',set()))
            assert b.call('/api/rules')['total']==1
            assert any(item['prefix']=='192.0.2.0/24' for item in b.call('/api/observation')['excluded'])
        try:
            b.call('/api/rules/manual','POST',{'value':'198.51.100.0/24'})
            raise AssertionError('Slave accepted a mutation')
        except HTTPError as exc:
            assert exc.code == 403
        guest = Client(configs['a'])
        guest.login('lab-guest', first)
        try:
            guest.call('/api/rules/manual','POST',{'value':'198.51.100.0/24'})
            raise AssertionError('Guest accepted a mutation')
        except HTTPError as exc:
            assert exc.code == 403
        if args.cli:
            import pexpect
            executable = str(Path(sys.executable).parent/'hemlock')
            listing = subprocess.check_output(['sudo','-n',executable,'--config',str(paths['a']),'user','list'],text=True)
            assert 'lab-admin' in listing and '$argon2' not in listing
            changed_password = 'a1'+secrets.token_urlsafe(24)
            checked_passwords.append(changed_password)
            cli = pexpect.spawn('sudo',['-n',executable,'--config',str(paths['a']),'user','reset-password','lab-admin'],
                                encoding='utf-8',timeout=30)
            cli.expect_exact('New password: ')
            cli.sendline(changed_password)
            cli.expect_exact('Repeat password: ')
            cli.sendline(changed_password)
            cli.expect(pexpect.EOF)
            cli.close()
            assert cli.exitstatus == 0, 'Real root CLI password reset failed'
            def revoked(client):
                try:
                    client.call('/api/me')
                except HTTPError as exc:
                    return exc.code == 403
                return False
            eventually(lambda: revoked(a))
            eventually(lambda: revoked(b))
            try:
                Client(configs['a']).login('lab-admin',first)
                raise AssertionError('Old password was accepted after CLI reset')
            except HTTPError as exc:
                assert exc.code == 403
            first = changed_password
            a.login('lab-admin',first)
            b.login('lab-admin',first)
            history = a.call('/api/audit?size=100')['items']
            assert any(item['actor']=='root:cli' and item['action']=='user.update' for item in history)
            assert all(password not in json.dumps(history) for password in checked_passwords)
            assert '$argon2' not in json.dumps(history)
            for config in configs.values():
                assert Path(config.database).stat().st_uid == os.getuid()
                for suffix in ('-wal','-shm'):
                    sidecar = Path(config.database+suffix)
                    if sidecar.exists():
                        assert sidecar.stat().st_uid == os.getuid()
            print('Real root CLI list/reset passed; old sessions revoked on both nodes; SQLite ownership preserved.')
        stop('b')
        a.call('/api/rules/manual','POST',{'value':'2001:db8::/32'})
        start('b')
        b = Client(configs['b'])
        eventually(lambda: ready('b', b))
        b.login('lab-admin',first)
        eventually(lambda: b.call('/api/rules')['total'] == 2)
        if adapters:
            eventually(lambda: bgp_equals('a',{'192.0.2.0/24','2001:db8::/32'}) and bgp_equals('b',{'2001:db8::/32'}))
            stop_daemon('b')
            start_daemon('b')
            eventually(lambda: bgp_equals('b',{'2001:db8::/32'}))
            daemon_pids={name:process.pid for name,process in daemon_processes.items()}
        old_history = a.call('/api/observation')['local']['history']
        stop('a')
        assert b.call('/api/rules')['total'] == 2
        if adapters:
            assert bgp_equals('b',{'2001:db8::/32'})
        stop('b')
        role(paths['b'],'master')
        start('b')
        b = Client(configs['b'])
        eventually(lambda: ready('b', b))
        b.login('lab-admin',first)
        b.call('/api/rules/'+rule_id,'DELETE')
        assert b.call('/api/observation')['local']['history'] != old_history
        role(paths['a'],'slave')
        start('a')
        a = Client(configs['a'])
        expected_history = b.call('/api/observation')['local']['history']
        eventually(lambda: ready('a', a, expected_history))
        a.login('lab-admin',first)
        eventually(lambda: a.call('/api/rules')['total'] == 1)
        eventually(lambda: a.call('/api/observation')['local']['history'] == b.call('/api/observation')['local']['history'])
        if adapters:
            eventually(lambda: bgp_equals('a',{'2001:db8::/32'}) and bgp_equals('b',{'2001:db8::/32'}))
            assert all(daemon_processes[name].pid==pid and daemon_processes[name].poll() is None for name,pid in daemon_pids.items())
            print('Two independent GoBGP daemons passed: background reconciliation, slave protection divergence, daemon recovery and failover without daemon restarts.')
        print('HTTPS two-node checks passed: CA/SAN and token rejection, snapshot+journal replay, read-only roles, replication, restart, retained data, promotion and old-master replacement.')
        print('No production neighbors or systemd services were used.')
    finally:
        for name in list(processes):
            stop(name)
        for name in list(daemon_processes):
            stop_daemon(name)
        for adapter in adapters.values():
            adapter.close()
        for path in directory.glob('*.log'):
            contents=path.read_text()
            assert token not in contents and all(password not in contents for password in checked_passwords), 'A secret leaked into a process log'


if __name__ == '__main__':
    main()
