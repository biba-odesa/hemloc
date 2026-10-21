"""Real Chromium brand and synchronization color checks, using only isolated data."""
import argparse
from pathlib import Path
import secrets
import sys
import tempfile
import threading
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import uvicorn
from playwright.sync_api import sync_playwright,expect
from hemlock.auth import password_hash
from hemlock.config import Config
from hemlock.domain import Actor
from hemlock.service import Service
from hemlock.store import Store
from hemlock.web import create_app
from tools.check_gobgp import port,wait_for


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--directory',required=True);args=parser.parse_args()
    output=Path(args.directory);output.mkdir(parents=True,exist_ok=False)
    with tempfile.TemporaryDirectory(prefix='hemlock-branding-') as tmp:
        cfg=Config(tls=False,database=str(Path(tmp)/'a.sqlite'),node_id='hemloc-a',peer_node_id='hemloc-b',protected_asns=(),metadata_enabled=False)
        store=Store(cfg);password='a1'+secrets.token_urlsafe(24)
        Service(store).save_user(Actor('fixture','admin'),'viewer',role='guest',password_hash=password_hash(password))
        server=uvicorn.Server(uvicorn.Config(create_app(cfg,adapter=object(),background=False),host='127.0.0.1',port=port(),proxy_headers=False,access_log=False,log_level='error'))
        thread=threading.Thread(target=server.run);thread.start()
        try:
            wait_for(lambda:server.started)
            with sync_playwright() as pw:
                browser=pw.chromium.launch(executable_path='/usr/bin/chromium-headless-shell',headless=True)
                page=browser.new_page(viewport={'width':1440,'height':1000});errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                page.goto(f'http://127.0.0.1:{server.config.port}')
                expect(page.locator('#login-panel h1')).to_have_text('Hemlock');expect(page).to_have_title('Hemlock · Prefix control')
                page.locator('#login-form [name=login]').fill('viewer');page.locator('#login-form [name=password]').fill(password);page.locator('#login-form button').click();expect(page.locator('#workspace')).to_be_visible()
                expect(page.locator('.brand span')).to_contain_text('Hemlock');expect(page.locator('#peer-title')).to_have_text('Hemlock-B status')
                initial=page.evaluate("fetch('/api/dashboard').then(r=>r.json())")
                for theme in ('dark','light'):
                    if page.locator('html').get_attribute('data-theme')!=theme:page.locator('#theme').click()
                    for status in ('In sync','Catching up','Unavailable','Stale / unavailable','Not configured','Conflict: two masters'):
                        data={**initial,'peer':{**initial['peer'],'status':status,'healthy':status=='In sync','lag':0 if status=='In sync' else None}}
                        page.route('**/api/dashboard',lambda route,request,data=data:route.fulfill(json=data))
                        page.evaluate('metrics()');expect(page.locator('#peer-state')).to_have_text(status)
                        expect(page.locator('#peer-state')).to_have_class('sync-healthy' if status=='In sync' else 'sync-unhealthy')
                        color=page.locator('#peer-state').evaluate('el=>getComputedStyle(el).color')
                        channels=list(map(int,color.removeprefix('rgb(').removesuffix(')').split(',')))
                        assert (channels[1]>channels[0]) if status=='In sync' else (channels[0]>channels[1]),color
                        if status in ('In sync','Unavailable'):page.screenshot(path=str(output/f'{theme}-{status.replace(" ","-")}.png'),full_page=True)
                        page.unroute('**/api/dashboard')
                assert not errors,errors
                browser.close()
            print('PASS: Hemlock login/title/sidebar, legacy peer identity display, green only In sync, all nonhealthy labels red, both themes and text retained; no working data used.')
        finally:
            server.should_exit=True;thread.join(15);assert not thread.is_alive()


if __name__=='__main__':main()
