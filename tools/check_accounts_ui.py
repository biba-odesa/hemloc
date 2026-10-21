"""Isolated real-browser acceptance: sorting, forms, private cross-node login history."""
from dataclasses import replace
from pathlib import Path
import argparse
import secrets
import sys
import tempfile
import threading
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import uvicorn
from playwright.sync_api import sync_playwright,expect
from hemlock.auth import Auth,password_hash
from hemlock.config import Config
from hemlock.domain import Actor
from hemlock.service import Service
from hemlock.store import Store
from hemlock.web import create_app
from tools.check_gobgp import port,wait_for


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--directory',required=True);args=parser.parse_args()
    output=Path(args.directory);output.mkdir(parents=True,exist_ok=False)
    with tempfile.TemporaryDirectory(prefix='hemlock-account-ui-') as tmp:
        cfg=Config(tls=False,database=str(Path(tmp)/'a.sqlite'),node_id='Hemlock-A',peer_node_id='Hemlock-B',protected_asns=(),protected_prefixes=(),metadata_enabled=False)
        store=Store(cfg);service=Service(store);actor=Actor('lab','admin');password='a1'+secrets.token_urlsafe(24)
        for login,role in [('admin','admin'),('guest','guest'),('empty','guest')]:service.save_user(actor,login,role=role,password_hash=password_hash(password))
        for i in reversed(range(1,62)):service.add_manual(actor,f'192.0.2.{i}',('Alpha' if i%2 else 'zulu')+f' {i:02}')
        service.add_manual(actor,'2001:db8::10','IPv6 host')
        asrule=service.add_asn(actor,64520,'ASN comment');service.update_asn(actor,asrule['id'],['198.51.100.0/24'],name='Example')
        for login in ('admin','guest'):
            for i in range(7):Auth(store,lambda h,p:True).login(login,'fixture',f'192.0.2.{100+i}')
        slave=Store(replace(cfg,role='slave',node_id='Hemlock-B',peer_node_id='Hemlock-A',database=str(Path(tmp)/'b.sqlite')))
        slave.install_snapshot(store.snapshot())
        for login in ('admin','guest'):Auth(slave,lambda h,p:True).login(login,'fixture','2001:db8::123')
        batch=slave.local_security_events();store.ingest_security(batch);slave.apply_events(store.events(slave.info()['history'],slave.info()['sequence']))
        servers=[];threads=[]
        for config in (cfg,slave.config):
            server=uvicorn.Server(uvicorn.Config(create_app(config,adapter=object(),background=False),host='127.0.0.1',port=port(),proxy_headers=False,access_log=False,log_level='error'))
            thread=threading.Thread(target=server.run);thread.start();servers.append(server);threads.append(thread)
        try:
            for server in servers:wait_for(lambda:server.started)
            with sync_playwright() as pw:
                browser=pw.chromium.launch(executable_path='/usr/bin/chromium-headless-shell',headless=True)
                context=browser.new_context(viewport={'width':1440,'height':1050},timezone_id='Europe/Kyiv',extra_http_headers={'X-Forwarded-For':'203.0.113.99','Forwarded':'for=203.0.113.98'})
                page=context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                def login(login,server=servers[0]):
                    page.goto(f'http://127.0.0.1:{server.config.port}')
                    page.locator('#login-form input[name=login]').fill(login);page.locator('#login-form input[name=password]').fill(password);page.locator('#login-form button').click();expect(page.locator('#workspace')).to_be_visible()
                def users():page.locator('nav button[data-view=users]').click();expect(page.locator('.own-account')).to_be_visible()
                login('admin')
                assert page.locator('aside #password-button').count()==0
                expect(page.locator('nav button[data-view=manual]')).to_have_text('Blocked IP list')
                page.locator('nav button[data-view=manual]').click();page.locator('#add').click()
                expect(page.locator('#edit-title')).to_have_text('Add IP network');expect(page.locator('#value-caption')).to_have_text('IP/CIDR');page.locator('[data-close=editor]').click()
                page.locator('#content').get_by_role('button',name='Edit comment').first.click();expect(page.locator('#edit-title')).to_have_text('Edit IP network');expect(page.locator('#value-caption')).to_have_text('IP/CIDR');page.locator('[data-close=editor]').click()
                page.locator('nav button[data-view=asn]').click();page.locator('#add').click();expect(page.locator('#edit-title')).to_have_text('Add ASN');expect(page.locator('#value-caption')).to_have_text('ASN');page.locator('[data-close=editor]').click()
                page.locator('#content').get_by_role('button',name='Edit comment').click();expect(page.locator('#edit-title')).to_have_text('Edit ASN');expect(page.locator('#value-caption')).to_have_text('ASN');page.locator('[data-close=editor]').click()
                page.locator('nav button[data-view=dashboard]').click()
                def heading(name):return page.locator('.route-list thead').get_by_role('button',name=name,exact=False)
                expect(page.locator('.route-list th').nth(0)).to_have_attribute('aria-sort','ascending')
                expect(page.locator('.route-link').first).to_have_text('192.0.2.1/32')
                page.locator('#next').click();expect(page.locator('.route-link').first).to_have_text('192.0.2.26/32')
                heading('Prefix').click();expect(page.locator('#page-label')).to_contain_text('Page 1 of 3');expect(page.locator('.route-link').first).to_have_text('2001:db8::10/128')
                expect(page.locator('.route-list th').nth(0)).to_have_attribute('aria-sort','descending')
                page.locator('#reload').click();expect(page.locator('.route-link').first).to_have_text('2001:db8::10/128');expect(page.locator('.route-list th').nth(0)).to_have_attribute('aria-sort','descending')
                for name,column in [('Source',1),('Comment',2),('Added',3)]:
                    heading(name).click();expect(page.locator('.route-list th').nth(column)).to_have_attribute('aria-sort','ascending');expect(page.locator('.route-link').first).to_have_text({'Source':'198.51.100.0/24','Comment':'192.0.2.1/32','Added':'192.0.2.61/32'}[name]);heading(name).click();expect(page.locator('.route-list th').nth(column)).to_have_attribute('aria-sort','descending');expect(page.locator('.route-link').first).to_have_text({'Source':'192.0.2.1/32','Comment':'192.0.2.60/32','Added':'198.51.100.0/24'}[name])
                page.locator('#search-mode').select_option('text');page.locator('#search').fill('Alpha');page.locator('#search').press('Enter')
                heading('Prefix').click();expect(page.locator('#page-label')).to_contain_text('of 2');expect(page.locator('.route-link').first).to_have_text('192.0.2.1/32')
                page.locator('#next').click();expect(page.locator('.route-link').first).to_have_text('192.0.2.51/32')
                expect(page.locator('.route-list')).to_contain_text('Blocked from IP networks list')
                page.locator('.route-link').first.click();expect(page.locator('.expanded-row:not([hidden])')).to_contain_text('Blocked from IP networks list')
                page.get_by_role('button',name='State help').click();expect(page.locator('.state-dialog')).to_contain_text('remote router');page.locator('.state-dialog').get_by_role('button',name='Close').click()
                users();expect(page.locator('.own-account')).to_contain_text('admin');expect(page.locator('.own-login-history tbody tr')).to_have_count(5)
                expect(page.locator('.own-login-history')).to_contain_text('Hemlock-B');expect(page.locator('.own-login-history')).to_contain_text('2001:db8::123');expect(page.locator('.own-login-history')).to_contain_text('127.0.0.1');expect(page.locator('.own-login-history')).to_contain_text('GMT+3')
                expect(page.locator('.own-login-history')).not_to_contain_text('203.0.113.99')
                empty=page.locator('#content table').last.locator('tbody tr').filter(has=page.get_by_role('cell',name='empty',exact=True))
                empty.get_by_role('button',name='Login history').click();expect(page.locator('.login-history-dialog')).to_contain_text('No successful logins recorded.');page.locator('.login-history-dialog').get_by_role('button',name='Close').click()
                for theme in ('dark','light'):
                    if page.locator('html').get_attribute('data-theme')!=theme:page.locator('#theme').click()
                    page.screenshot(path=str(output/f'users-{theme}.png'),full_page=True)
                page.reload();expect(page.locator('.own-login-history tbody tr')).to_have_count(5)
                page.locator('#logout').click();expect(page.locator('#login-panel')).to_be_visible();login('guest');users();expect(page.locator('.own-account')).to_contain_text('guest');expect(page.locator('#content')).not_to_contain_text('User management');expect(page.locator('#password-button')).to_be_enabled()
                assert page.request.get(f'http://127.0.0.1:{servers[0].config.port}/api/login-history?login=admin').status==403
                page.evaluate("action(()=>showLoginHistory('admin'))");expect(page.locator('.login-history-dialog .dialog-notice')).to_contain_text('own login history');page.locator('.login-history-dialog').get_by_role('button',name='Close').click()
                page.locator('#password-button').click();expect(page.locator('#password-form input[name=current_password]')).to_be_visible();page.locator('[data-close=password-editor]').click()
                page.screenshot(path=str(output/'guest.png'),full_page=True)
                page.locator('#logout').click();expect(page.locator('#login-panel')).to_be_visible();login('guest',servers[1]);users();expect(page.locator('#password-button')).to_be_disabled();expect(page.locator('.own-account')).to_contain_text('master (Hemlock-A)');expect(page.locator('.own-login-history')).to_contain_text('Hemlock-B');expect(page.locator('.login-freshness')).to_contain_text('may lag')
                page.screenshot(path=str(output/'slave.png'),full_page=True)
                page.locator('nav button[data-view=info]').click()
                for language in ('EN','RU','UK'):
                    page.locator('.language-switch').get_by_role('button',name=language,exact=True).click()
                    for state in ('Applied','Pending','Failed','Excluded by protection','Unknown','Stale'):expect(page.locator('.info-page')).to_contain_text(state)
                assert not errors,errors
                browser.close()
            print('PASS: form titles/labels; numeric/all-page filtered sort/aria/persistence; provenance and State help/Info EN/RU/UK; guest/admin own cards, latest five real socket IPs/nodes, spoof headers ignored, empty/private history, slave password disabled; both themes.')
        finally:
            for server in servers:server.should_exit=True
            for thread in threads:thread.join(timeout=15);assert not thread.is_alive()

if __name__=='__main__':main()
