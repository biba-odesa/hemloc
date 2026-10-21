"""Real Chromium: isolated login, blue theme, partial batch input and expired sessions."""
import argparse
from dataclasses import replace
from pathlib import Path
import secrets
import sys
import tempfile
import threading
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import uvicorn
from playwright.sync_api import sync_playwright,expect
from hemloc.auth import password_hash
from hemloc.config import Config
from hemloc.domain import Actor
from hemloc.service import Service
from hemloc.store import Store
from hemloc.web import create_app
from tools.check_gobgp import port,wait_for


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--directory',required=True);args=parser.parse_args()
    output=Path(args.directory);output.mkdir(parents=True,exist_ok=False)
    with tempfile.TemporaryDirectory(prefix='hemloc-login-batch-') as tmp:
        cfg=Config(tls=False,database=str(Path(tmp)/'a.sqlite'),node_id='a',peer_node_id='b',protected_asns=(),protected_prefixes=('10.0.0.0/8',),metadata_enabled=False)
        store=Store(cfg);actor=Actor('fixture','admin');password='a1'+secrets.token_urlsafe(24)
        Service(store).save_user(actor,'admin',role='admin',password_hash=password_hash(password))
        Service(store).add_manual(actor,'192.0.2.1','Existing')
        app=create_app(cfg,adapter=object(),background=False)
        server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=port(),proxy_headers=False,access_log=False,log_level='error'))
        thread=threading.Thread(target=server.run);thread.start()
        try:
            wait_for(lambda:server.started)
            with sync_playwright() as pw:
                browser=pw.chromium.launch(executable_path='/usr/bin/chromium-headless-shell',headless=True)
                context=browser.new_context(viewport={'width':1440,'height':1050},timezone_id='Europe/Kyiv')
                page=context.new_page();errors=[];requests=[]
                page.on('pageerror',lambda e:errors.append(str(e)))
                page.on('request',lambda request:requests.append(request.url.split(server_url)[-1]) if request.url.startswith(server_url) else None)
                server_url=f'http://127.0.0.1:{server.config.port}'
                # Hide assertions also run while the session probe is unresolved.
                page.route('**/api/session',lambda route:route.fulfill(json={'authenticated':False}))
                page.goto(server_url)
                expect(page.locator('#login-panel')).to_be_visible();expect(page.locator('aside')).to_be_hidden();expect(page.locator('#app-header')).to_be_hidden();expect(page.locator('#workspace')).to_be_hidden()
                assert not [r for r in requests if r.startswith('/api/') and r!='/api/session'],requests
                expect(page.locator('#login-form [name=login]')).to_have_attribute('autocomplete','username')
                expect(page.locator('#login-form [name=password]')).to_have_attribute('autocomplete','current-password')
                for theme in ('dark','light'):
                    if page.locator('html').get_attribute('data-theme')!=theme:page.locator('#theme').evaluate('(button)=>button.click()')
                    page.screenshot(path=str(output/f'login-{theme}.png'),full_page=True)
                page.set_viewport_size({'width':390,'height':844});page.screenshot(path=str(output/'login-mobile.png'),full_page=True)
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                page.unroute('**/api/session');page.set_viewport_size({'width':1440,'height':1050})
                page.locator('#login-form [name=login]').fill('admin');page.locator('#login-form [name=password]').fill(password)
                page.locator('#login-form [name=password]').press('Enter');expect(page.locator('#workspace')).to_be_visible()
                page.locator('nav [data-view=manual]').click();page.locator('#add').click()
                value=page.locator('#edit-form [name=value]');comment=page.locator('#edit-form [name=comment]')
                expect(value).to_have_attribute('rows','6')
                raw='192.0.2.2, 2001:db8::2\n192.0.2.1,10.1.1.1\n192.0.2.7/24,broken,2001:0db8::2/128'
                value.fill(raw);comment.fill('Shared Unicode «тест»\nSecond line')
                page.locator('#edit-form button.primary').click()
                expect(page.locator('#batch-result')).to_contain_text('Added: 2 · Skipped: 2 · Invalid: 3')
                expect(value).to_have_value('192.0.2.1\n10.1.1.1\n192.0.2.7/24\nbroken\n2001:0db8::2/128')
                expect(comment).to_have_value('Shared Unicode «тест»\nSecond line')
                expect(page.locator('#batch-result')).to_contain_text('existing duplicate');expect(page.locator('#batch-result')).to_contain_text('protected network')
                for theme in ('dark','light'):
                    if page.locator('html').get_attribute('data-theme')!=theme:page.locator('#theme').evaluate('(button)=>button.click()')
                    page.screenshot(path=str(output/f'batch-{theme}.png'),full_page=True)
                # Re-submit retained items: no extra rules and explicit zero additions.
                page.locator('#edit-form button.primary').click();expect(page.locator('#batch-result')).to_contain_text('Added: 0')
                self_before=store.list('rule');assert len(self_before)==3
                page.locator('[data-close=editor]').click();page.locator('#add').click();value.fill('198.51.100.10');comment.fill('Keep during network uncertainty')
                def lose_response(route):
                    route.fetch()  # Commit succeeds; the browser never receives confirmation.
                    route.abort()
                page.route('**/api/rules/manual-batch',lose_response)
                page.locator('#edit-form button.primary').click();expect(page.locator('#edit-form .dialog-notice')).to_be_visible()
                expect(value).to_have_value('198.51.100.10');expect(comment).to_have_value('Keep during network uncertainty')
                assert len(store.list('rule'))==len(self_before)+1
                page.unroute('**/api/rules/manual-batch')
                page.locator('#edit-form button.primary').click();expect(page.locator('#batch-result')).to_contain_text('Added: 0 · Skipped: 1 · Invalid: 0')
                expect(value).to_have_value('198.51.100.10');page.locator('[data-close=editor]').click()
                # Existing coverage badge colors and read-only tables in the new palette.
                for theme in ('dark','light'):
                    if page.locator('html').get_attribute('data-theme')!=theme:page.locator('#theme').evaluate('(button)=>button.click()')
                    page.locator('#add').click();value.fill('192.0.2.1');expect(page.locator('#coverage-preview')).to_contain_text('Covered by')
                    page.screenshot(path=str(output/f'coverage-{theme}.png'),full_page=True);page.locator('[data-close=editor]').click()
                page.reload();expect(page.locator('#workspace')).to_be_visible();expect(page.locator('html')).to_have_attribute('data-theme','light')
                # Force expiry only in this fixture and invoke the same bounded refresh.
                with store.transaction() as db:db.execute('UPDATE sessions SET expires=0')
                page.evaluate('refreshSession()');expect(page.locator('#login-panel')).to_be_visible();expect(page.locator('aside')).to_be_hidden();expect(page.locator('#workspace')).to_be_hidden()
                assert page.locator('#content').inner_text()==''
                count=len(requests);page.evaluate('refreshSession()');assert len(requests)==count
                page.locator('#login-form [name=login]').fill('admin');page.locator('#login-form [name=password]').fill(password);page.locator('#login-form button').click();expect(page.locator('#workspace')).to_be_visible()
                page.locator('#logout').click();expect(page.locator('#login-panel')).to_be_visible();expect(page.locator('aside')).to_be_hidden()
                assert not errors,errors
                browser.close()
            print('PASS: no protected pre-login requests/flash; autocomplete/keyboard/mobile/themes; partial IPv4/IPv6 batch counts/reasons/retained input/comment; retry/network uncertainty; coverage; session expiry/logout hide and stop refresh. Isolated fixture only.')
        finally:
            server.should_exit=True;thread.join(15);assert not thread.is_alive()


if __name__=='__main__':main()
