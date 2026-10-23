"""Own real HTTPS/mTLS nodes, peer-free GoBGP and Chromium; never host services."""
import argparse
from dataclasses import replace
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import threading
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright,expect
from hemlock.auth import password_hash
from hemlock.config import Config
from hemlock.domain import Actor
from hemlock.gobgp import GoBGP
from hemlock.presentation import View
from hemlock.reconcile import Reconciler
from hemlock.replication import Replicator
from hemlock.tls import Trust,TLSFailure,own_info,refresh_context
from hemlock.tls_runtime import make_server
from tools.check_gobgp import port,wait_for


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--binary',required=True);parser.add_argument('--directory',required=True);args=parser.parse_args()
    binary=str(Path(args.binary).resolve());output=Path(args.directory);output.mkdir(parents=True,exist_ok=False)
    with tempfile.TemporaryDirectory(prefix='hemlock-tls-lab-') as tmp:
        root=Path(tmp);servers=[];threads=[];daemons=[];adapters=[];logs=[];used=set()
        def free():
            value=port()
            while value in used:value=port()
            used.add(value);return value
        aweb,bweb=free(),free();token=root/'token';token.write_text(secrets.token_urlsafe(48));password='Fixture1'+secrets.token_urlsafe(16)
        configs=[]
        for name,web,peer,other,role,owner in [('a',aweb,'b',bweb,'master',1),('b',bweb,'a',aweb,'slave',2)]:
            rpc,bgp=free(),free();toml=root/(name+'.toml')
            toml.write_text(f'[global.config]\nas=64512\nrouter-id="127.0.0.1"\nport={bgp}\nlocal-address-list=["127.0.0.1"]\n')
            log=(root/(name+'.log')).open('wb');logs.append(log)
            process=subprocess.Popen([binary,'-f',str(toml),f'--api-hosts=127.0.0.1:{rpc}','--pprof-disable'],stdout=log,stderr=log);daemons.append(process)
            config=Config(database=str(root/(name+'.sqlite')),host='127.0.0.1',port=web,node_id=name,peer_node_id=peer,role=role,
                          peer_url=f'https://127.0.0.1:{other}',token_file=str(token),tls_mode='pinned',tls_state_dir=str(root/(name+'tls')),
                          cert=str(root/(name+'tls/identity/cert')),key=str(root/(name+'tls/identity/key')),protected_asns=(),protected_prefixes=(),
                          metadata_enabled=False,announcements=True,v4_next_hop='192.0.2.254',v6_next_hop='2001:db8::1',grpc_target=f'127.0.0.1:{rpc}',owner=(64512,100,owner))
            adapter=GoBGP(config);adapters.append(adapter);configs.append(config)
            def ready(adapter=adapter):
                try:adapter.paths();return True
                except Exception:return False
            wait_for(ready)
        try:
            for config,adapter in zip(configs,adapters):
                server=make_server(config,adapter=adapter,background=False)
                server.config.log_level='error'
                thread=threading.Thread(target=server.run);thread.start();servers.append(server);threads.append(thread);wait_for(lambda:server.started)
            a,b=[s.config.app.state.store for s in servers];sa,sb=[s.config.app.state.service for s in servers]
            ra,rb=[Replicator(s.config.app.state.store,s.config.app.state.peer) for s in servers]
            admin=Actor('fixture','admin')
            for login,role in [('admin','admin'),('guest','guest')]:sa.save_user(admin,login,role=role,password_hash=password_hash(password))
            sa.add_manual(admin,'192.0.2.7');sa.add_manual(admin,'2001:db8::7')
            Reconciler(sa,adapters[0]).step()
            try:ra.step();raise AssertionError('Unapproved peer exchanged data')
            except TLSFailure:pass
            pids=[p.pid for p in daemons]
            spkis=','.join(own_info(c)['fingerprint'][7:]+'=' for c in configs)
            with sync_playwright() as pw:
                browser=pw.chromium.launch(executable_path='/usr/bin/chromium-headless-shell',headless=True,args=['--ignore-certificate-errors-spki-list='+spkis])
                page=browser.new_page(viewport={'width':1440,'height':1000});errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
                page.on('dialog',lambda dialog:dialog.accept())
                def login(config,name):
                    page.goto(f'https://127.0.0.1:{config.port}')
                    page.locator('#login-form [name=login]').fill(name);page.locator('#login-form [name=password]').fill(password);page.locator('#login-form button').click();expect(page.locator('#workspace')).to_be_visible()
                login(configs[0],'admin')
                for theme in ('dark','light'):
                    if page.locator('html').get_attribute('data-theme')!=theme:page.locator('#theme').click()
                    expect(page.locator('#peer-state')).to_have_text('Peer approval required')
                    expect(page.locator('#peer-state')).to_have_class('sync-pending')
                    expect(page.locator('#peer-tls')).to_have_count(0)
                    expect(page.locator('#review-connection')).to_be_visible()
                    page.screenshot(path=str(output/(theme+'-approval.png')),full_page=True)
                page.get_by_role('button',name='Review connection',exact=True).click()
                expect(page.locator('#title')).to_have_text('Settings')
                expect(page.locator('#peer-tls')).to_contain_text('SHA256:')
                page.get_by_role('button',name='Approve peer certificate',exact=True).click()
                wait_for(lambda:Trust(configs[0]).pin() is not None)
                expect(page.locator('#peer-tls')).not_to_contain_text('Approved fingerprintNone')
                candidate=Trust(configs[1]).discover();Trust(configs[1]).approve(candidate['fingerprint']);refresh_context(configs[1],servers[1].config.ssl)
                rb.step();ra.step();rb.step();Reconciler(sb,adapters[1]).step()
                before=[sorted((p.prefix,p.next_hop,p.communities) for p in ad.paths()) for ad in adapters]
                page.get_by_role('button',name='Dashboard',exact=True).click()
                for theme in ('dark','light'):
                    if page.locator('html').get_attribute('data-theme')!=theme:page.locator('#theme').click()
                    page.evaluate('metrics()');expect(page.locator('#peer-state')).to_have_text('In sync')
                    expect(page.locator('#review-connection')).to_be_hidden()
                    expect(page.locator('#peer-tls')).to_have_count(0)
                    page.screenshot(path=str(output/(theme+'-approved.png')),full_page=True)
                page.set_viewport_size({'width':390,'height':844});page.screenshot(path=str(output/'mobile.png'),full_page=True)
                assert page.evaluate('document.documentElement.scrollWidth<=window.innerWidth'), 'TLS card overflows mobile viewport'
                page.set_viewport_size({'width':1440,'height':1000})
                page.get_by_role('button',name='Settings',exact=True).click()
                for theme in ('dark','light'):
                    if page.locator('html').get_attribute('data-theme')!=theme:page.locator('#theme').click()
                    expect(page.locator('#peer-tls')).to_contain_text('SHA256:')
                    page.screenshot(path=str(output/(theme+'-settings.png')),full_page=True)
                page.set_viewport_size({'width':390,'height':844});page.screenshot(path=str(output/'mobile-settings.png'),full_page=True)
                assert page.evaluate('document.documentElement.scrollWidth<=window.innerWidth')
                page.set_viewport_size({'width':1440,'height':1000})
                page.locator('#logout').click();login(configs[0],'guest')
                page.get_by_role('button',name='Settings',exact=True).click()
                expect(page.locator('#peer-tls')).to_contain_text('SHA256:')
                expect(page.get_by_role('button',name='Approve peer certificate',exact=True)).to_have_count(0)
                expect(page.get_by_role('button',name='Revoke peer trust',exact=True)).to_have_count(0)
                page.locator('#logout').click();login(configs[1],'admin')
                page.get_by_role('button',name='Settings',exact=True).click()
                expect(page.get_by_role('button',name='Revoke peer trust',exact=True)).to_be_visible()
                page.get_by_role('button',name='Revoke peer trust',exact=True).click()
                expect(page.locator('#settings-peer-state')).to_have_text('Peer approval required')
                try:ra.step();raise AssertionError('Revoked peer exchanged data')
                except TLSFailure:pass
                sa.add_manual(admin,'198.51.100.7')
                assert len(b.list('rule'))==2
                page.get_by_role('button',name='Refresh peer certificate',exact=True).click()
                page.get_by_role('button',name='Approve peer certificate',exact=True).click()
                wait_for(lambda:Trust(configs[1]).pin() is not None)
                rb.step();ra.step();rb.step()
                assert len(b.list('rule'))==3
                # TLS operations do not restart daemons or alter their prior routes.
                assert [p.pid for p in daemons]==pids
                assert all(p.poll() is None for p in daemons)
                assert [sorted((p.prefix,p.next_hop,p.communities) for p in ad.paths()) for ad in adapters]==before
                assert not errors,errors
                browser.close()
            print('PASS: Settings-only TLS controls in dark/light/mobile, compact Dashboard with yellow waiting/green sync; guest hidden/admin slave approval/revocation; snapshot/journal resume; real peer-free IPv4/IPv6 GoBGP RIB and PIDs unchanged by TLS; no working data/services or real notifications.')
        finally:
            for server in servers:server.should_exit=True
            for thread in threads:thread.join(15)
            for adapter in adapters:adapter.close()
            for process in daemons:
                process.terminate()
                try:process.wait(timeout=10)
                except subprocess.TimeoutExpired:process.kill();process.wait()
            for log in logs:log.close()


if __name__=='__main__':main()
