"""Browser acceptance for the read-only redesign on isolated data and fake observations."""
from dataclasses import asdict
from pathlib import Path
import argparse
import secrets
import sys
import tempfile
import threading
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import uvicorn
from playwright.sync_api import sync_playwright,expect
from hemloc.auth import password_hash
from hemloc.config import Config
from hemloc.domain import Actor
from hemloc.reconcile import Path as Route
from hemloc.service import Service
from hemloc.store import Store
from hemloc.web import create_app
from tools.check_gobgp import port,wait_for


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--directory',required=True)
    args=parser.parse_args()
    output=Path(args.directory);output.mkdir(parents=True,exist_ok=False)
    with tempfile.TemporaryDirectory(prefix='hemloc-ui-redesign-') as tmp:
        cfg=Config(tls=False,database=str(Path(tmp)/'a.sqlite'),node_id='hemloc-a',peer_node_id='hemloc-b',
                   protected_asns=(),protected_prefixes=(),metadata_enabled=False,announcements=True,v6_next_hop='2001:db8::1')
        store=Store(cfg);service=Service(store);actor=Actor('lab','admin');password='a1'+secrets.token_urlsafe(24)
        service.save_user(actor,'admin',role='admin',password_hash=password_hash(password))
        for value,comment in [('192.0.2.0/24','Shared network'),('192.0.2.1','<img src=x onerror=alert(1)>'),('2001:db8::1','IPv6 reason')]:
            service.add_manual(actor,value,comment)
        second=service.add_asn(actor,64521,'Second host reason')
        service.update_asn(actor,second['id'],['192.0.2.1/32'])
        asn=service.add_asn(actor,64520,'ASN example')
        service.update_asn(actor,asn['id'],['192.0.2.0/24'],name='Example network')
        service.import_manual(actor,[{'value':f'2001:db8:1::{i:x}','comment':'Synthetic pagination'} for i in range(1,62)])
        routes,_=service.routes()
        def path(p):
            return {'prefix':p,'local':True,'owner':list(cfg.owner),'next_hop':cfg.v6_next_hop if ':' in p else cfg.v4_next_hop,
                    'local_pref':200,'communities':['64512:666']}
        rib={'at':time.time(),'paths':[path('192.0.2.0/24'),path('192.0.2.1/32')],
             'peers':[{'address':'192.0.2.10','description':'Peer One','session_state':6,'admin_state':1,'established_at':time.time()-120},
                      {'address':'192.0.2.11','description':'Peer Two','session_state':3,'admin_state':1},
                      {'address':'192.0.2.12','description':'','session_state':1,'admin_state':2}],
             'export':{'192.0.2.10':{'prefixes':['192.0.2.0/24','192.0.2.1/32']},'192.0.2.11':{'prefixes':[]}}}
        store.set_local('rib',rib)
        server=uvicorn.Server(uvicorn.Config(create_app(cfg,adapter=object(),background=False),host='127.0.0.1',port=port(),log_level='error',access_log=False))
        thread=threading.Thread(target=server.run);thread.start()
        try:
            wait_for(lambda:server.started)
            with sync_playwright() as playwright:
                browser=playwright.chromium.launch(executable_path='/usr/bin/chromium-headless-shell',headless=True)
                context=browser.new_context(viewport={'width':1440,'height':1050},timezone_id='Europe/Kyiv')
                page=context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                page.goto(f'http://127.0.0.1:{server.config.port}')
                page.locator('#login-form input[name=login]').fill('admin');page.locator('#login-form input[name=password]').fill(password);page.locator('#login-form button').click()
                expect(page.locator('#workspace')).to_be_visible()
                for theme in ('dark','light'):
                    if page.locator('html').get_attribute('data-theme')!=theme:page.locator('#theme').click()
                    page.locator('nav button[data-view=dashboard]').click()
                    expect(page.locator('#peer-title')).to_have_text('Hemloc-B status')
                    expect(page.locator('#peer-state')).to_have_text('Not configured')
                    expect(page.locator('#blocked-total')).to_have_text('2')
                    expect(page.locator('#application-warning')).to_contain_text('Pending: 62')
                    assert page.locator('#announce-mode').count()==0
                    expect(page.locator('#sessions')).to_contain_text('Established')
                    expect(page.locator('#sessions')).to_contain_text('Active')
                    expect(page.locator('#sessions')).to_contain_text('Disabled')
                    expect(page.locator('#sessions')).to_contain_text('Unknown')
                    assert page.locator('.route-list .route-link').count()==25
                    page.locator('#next').click();expect(page.locator('#page-label')).to_contain_text('Page 2')
                    page.locator('#search').fill('192.0.2.1');page.locator('#search').press('Enter')
                    expect(page.locator('.search-result')).to_have_text('Matches found: 2')
                    page.locator('.route-link').filter(has_text='192.0.2.1/32').click()
                    expect(page.locator('.expanded-row:not([hidden])')).to_contain_text('Second host reason')
                    expect(page.locator('.expanded-row:not([hidden])')).to_contain_text('<img src=x onerror=alert(1)>')
                    expect(page.locator('.expanded-row:not([hidden])')).to_contain_text('Exported')
                    expect(page.locator('.expanded-row:not([hidden])')).to_contain_text('GMT+3')
                    assert page.locator('#content img').count()==0
                    assert page.locator('#content pre').count()==0
                    page.locator('.route-link').filter(has_text='192.0.2.0/24').click()
                    expect(page.locator('.expanded-row:not([hidden])').filter(has_text='AS64520')).to_contain_text('AS64520 — Example network')
                    page.evaluate('refreshVisibleRoutes()')
                    expect(page.locator('.expanded-row:not([hidden])').filter(has_text='AS64520')).to_contain_text('Example network')
                    page.screenshot(path=str(output/f'{theme}.png'),full_page=True)
                    page.locator('#search').fill('198.51.100.1');page.locator('#search').press('Enter')
                    expect(page.locator('.search-result')).to_have_text('No matches')
                    page.locator('#search').fill('bad IP');page.locator('#search').press('Enter')
                    expect(page.locator('#notice')).to_contain_text('IPv4 or IPv6')
                    page.locator('nav button[data-view=audit]').click()
                    page.locator('summary').first.click()
                    expect(page.locator('#content')).to_contain_text('Before')
                    assert page.locator('#content pre').count()==0
                    for rule in store.list('rule'):assert rule['id'] not in page.locator('#content').inner_text()
                    page.locator('nav button[data-view=info]').click()
                    for language,title in [('EN','About Hemloc'),('RU','О Hemloc'),('UK','Про Hemloc')]:
                        page.locator('.language-switch button').filter(has_text=language).click()
                        expect(page.locator('.info-page')).to_contain_text(title)
                        expect(page.locator('.info-page')).to_contain_text('192.0.0.0/16')
                page.locator('nav button[data-view=dashboard]').click()
                rib['at']=time.time()-60;store.set_local('rib',rib)
                page.evaluate('metrics().then(refreshVisibleRoutes)')
                expect(page.locator('#blocked-total')).to_have_text('Unknown')
                expect(page.locator('#sessions')).to_contain_text('Stale')
                page.set_viewport_size({'width':390,'height':844});page.screenshot(path=str(output/'mobile.png'),full_page=True)
                assert not errors,errors
                browser.close()
            print('Both themes: bounded routes, expansion/all reasons/XSS safety, IP matches/no matches/errors, history without IDs/JSON, sessions/uptime/Unknown/Stale, applied counters, Info EN/RU/UK passed.')
        finally:
            server.should_exit=True;thread.join(timeout=15);assert not thread.is_alive()

if __name__=='__main__':main()
