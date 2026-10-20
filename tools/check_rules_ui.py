"""Real Chromium checks for duplicate feedback, coverage, pagination and theme."""
import argparse
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
    with tempfile.TemporaryDirectory(prefix='hemloc-rules-ui-') as tmp:
        cfg=Config(database=str(Path(tmp)/'a.sqlite'),tls=False,protected_asns=(),protected_prefixes=(),metadata_enabled=False)
        store=Store(cfg);service=Service(store);actor=Actor('lab','admin');password='a1'+secrets.token_urlsafe(24)
        service.save_user(actor,'admin',role='admin',password_hash=password_hash(password))
        host=service.add_manual(actor,'192.0.2.1','Host reason')
        subnet=service.add_manual(actor,'192.0.2.0/25','Subnet reason')
        aggregate=service.add_manual(actor,'192.0.2.0/24','Network reason')
        v6=service.add_manual(actor,'2001:db8::1','IPv6 host reason')
        service.add_manual(actor,'2001:db8::/32','IPv6 aggregate reason')
        asn=service.add_asn(actor,64520,'ASN reason')
        service.update_asn(actor,asn['id'],['192.0.2.0/24','192.0.2.0/26','2001:db8::/32'],name='Test AS')
        service.import_manual(actor,[{'value':f'198.51.100.{i}','comment':'Pagination fixture'} for i in range(1,47)])
        server=uvicorn.Server(uvicorn.Config(create_app(cfg,adapter=object(),background=False),host='127.0.0.1',port=port(),log_level='error',access_log=False))
        thread=threading.Thread(target=server.run);thread.start()
        try:
            wait_for(lambda:server.started)
            with sync_playwright() as pw:
                browser=pw.chromium.launch(executable_path='/usr/bin/chromium-headless-shell',headless=True)
                context=browser.new_context(viewport={'width':1440,'height':1050},color_scheme='light')
                page=context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                page.goto(f'http://127.0.0.1:{server.config.port}/#observation')
                expect(page.locator('html')).to_have_attribute('data-theme','dark')
                page.locator('#login-form input[name=login]').fill('admin');page.locator('#login-form input[name=password]').fill(password);page.locator('#login-form button').click()
                expect(page.locator('#title')).to_have_text('Dashboard')
                expect(page.locator('.metrics')).to_be_visible()
                assert 'Prefix blocking with clear provenance.' not in page.locator('body').inner_text()
                assert page.locator('aside #theme').count()==0
                def manual():
                    page.locator('nav button[data-view=manual]').click();expect(page.locator('.metrics')).to_be_hidden()
                def search(value):
                    page.locator('#search').fill(value);page.locator('#search').press('Enter')
                def row(key):return page.locator(f'[data-rule-id="{key}"]')
                for theme in ('dark','light'):
                    if page.locator('html').get_attribute('data-theme')!=theme:page.locator('#theme').click()
                    expect(page.locator('#theme')).to_have_attribute('aria-label','Switch to '+('light' if theme=='dark' else 'dark')+' theme')
                    page.reload();expect(page.locator('html')).to_have_attribute('data-theme',theme)
                    manual();search('192.0.2.')
                    expect(row(host['id'])).to_contain_text('Covered by AS64520')
                    expect(row(host['id'])).to_contain_text('Covered by 192.0.2.')
                    expect(row(subnet['id'])).to_contain_text('Contains 2 blocks')
                    expect(row(aggregate['id'])).to_contain_text('Contains 3 blocks')
                    expect(row(aggregate['id'])).to_contain_text('Covered by AS64520')
                    row(host['id']).locator('.coverage-amber summary').click()
                    expect(row(host['id']).locator('.coverage-amber')).to_contain_text('ASN reason')
                    expect(row(host['id']).locator('.coverage-amber')).to_contain_text('AS64520 — Test AS')
                    row(host['id']).locator('.coverage-blue summary').click()
                    expect(row(host['id']).locator('.coverage-blue')).to_contain_text('Network reason')
                    page.screenshot(path=str(output/f'{theme}.png'),full_page=True)
                    page.locator('#add').click();page.locator('#edit-form input[name=value]').fill('192.0.2.1/32')
                    expect(page.locator('#coverage-preview')).to_contain_text('Covered by AS64520')
                    page.locator('#edit-form button.primary').click()
                    expect(page.locator('#edit-form .dialog-notice')).to_contain_text('already exists')
                    page.get_by_role('button',name='Open existing record').click()
                    expect(row(host['id']).locator('details').first).to_have_attribute('open','')
                    expect(row(host['id'])).to_contain_text('Host reason')
                    manual();search('2001:db8')
                    expect(row(v6['id'])).to_contain_text('Covered by 2001:db8::/32')
                    expect(row(v6['id'])).to_contain_text('Covered by AS64520')
                manual();search('Pagination fixture')
                expect(page.locator('#page-label')).to_have_text('Page 1 of 2 · Showing 1–25 of 46')
                expect(page.locator('#first')).to_be_disabled();expect(page.locator('#previous')).to_be_disabled()
                page.locator('#last').click();expect(page.locator('#page-label')).to_have_text('Page 2 of 2 · Showing 26–46 of 46')
                expect(page.locator('#next')).to_be_disabled();expect(page.locator('#last')).to_be_disabled()
                page.locator('#first').click();expect(page.locator('#page-label')).to_contain_text('Page 1 of 2')
                search('Nothing-matches-this');expect(page.locator('#page-label')).to_have_text('No results')
                for name in ('first','previous','next','last'):expect(page.locator('#'+name)).to_be_disabled()
                # Put one item on the last page, then delete it through the UI.
                for r in store.list('rule'):
                    if r['comment']=='Pagination fixture':service.delete_rule(actor,r['id'])
                service.import_manual(actor,[{'value':f'203.0.113.{i}','comment':'Delete page fixture'} for i in range(1,27)])
                search('Delete page fixture');page.locator('#last').click();expect(page.locator('#page-label')).to_contain_text('Page 2 of 2')
                page.once('dialog',lambda dialog:dialog.accept());page.locator('#content').get_by_role('button',name='Delete',exact=True).click()
                expect(page.locator('#page-label')).to_have_text('Page 1 of 1 · Showing 1–25 of 25')
                manual();search('192.0.2.')
                service.delete_rule(actor,aggregate['id']);page.evaluate('refreshCoverage()')
                expect(row(host['id'])).not_to_contain_text('192.0.2.0/24')
                # Removing ASN prefixes invalidates old badges; the remaining manual covers stay.
                service.delete_rule(actor,asn['id']);page.evaluate('refreshCoverage()')
                expect(row(host['id'])).not_to_contain_text('Covered by AS64520')
                expect(row(host['id'])).to_contain_text('Covered by 192.0.2.0/25')
                for section in ('asn','audit','users','info'):
                    page.locator(f'nav button[data-view={section}]').click();expect(page.locator('.metrics')).to_be_hidden()
                page.locator('#theme').focus();page.keyboard.press('Enter')
                expect(page.locator('html')).to_have_attribute('data-theme','dark')
                page.set_viewport_size({'width':390,'height':844});page.screenshot(path=str(output/'mobile.png'),full_page=True)
                rect=page.locator('#theme').bounding_box();brand=page.locator('.brand span').bounding_box()
                assert rect['x']>=brand['x']+brand['width'],(rect,brand)
                assert not errors,errors
                browser.close()
            print('PASS: both themes/default/persistence/keyboard/mobile; duplicate form/link; ASN/manual IPv4/IPv6 coverage, unique Contains, preview, invalidation; pagination/filter/empty/delete-last; Dashboard-only cards and old URL.')
        finally:
            server.should_exit=True;thread.join(timeout=15);assert not thread.is_alive()

if __name__=='__main__':main()
