"""Isolated Chromium review of agreed EN/RU/UK Info and dynamic local protection."""
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
    with tempfile.TemporaryDirectory(prefix='hemlock-info-ui-') as tmp:
        cfg=Config(tls=False,database=str(Path(tmp)/'info.sqlite'),node_id='Info-lab-node',protected_asns=(64496,),protected_prefixes=('10.0.0.0/8','2001:db8::/32'),metadata_enabled=False)
        store=Store(cfg);password='a1'+secrets.token_urlsafe(24)
        Service(store).save_user(Actor('lab','admin'),'guest',role='guest',password_hash=password_hash(password))
        store.set_local('protection',{'prefixes':['10.0.0.0/8']+[f'192.0.2.{i}/32' for i in range(1,62)],'success':{'64496':1234}})
        server=uvicorn.Server(uvicorn.Config(create_app(cfg,adapter=object(),background=False),host='127.0.0.1',port=port(),proxy_headers=False,access_log=False,log_level='error'))
        thread=threading.Thread(target=server.run);thread.start()
        try:
            wait_for(lambda:server.started)
            with sync_playwright() as pw:
                browser=pw.chromium.launch(executable_path='/usr/bin/chromium-headless-shell',headless=True)
                page=browser.new_page(viewport={'width':1440,'height':1050},timezone_id='Europe/Kyiv');errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
                page.goto(f'http://127.0.0.1:{server.config.port}');expect(page.locator('#app-version')).to_be_hidden();page.locator('#login-form input[name=login]').fill('guest');page.locator('#login-form input[name=password]').fill(password);page.locator('#login-form button').click();expect(page.locator('#workspace')).to_be_visible()
                identity=page.request.get(f'http://127.0.0.1:{server.config.port}/api/me').json()['application']
                expected=f"Hemlock v{identity['version']}" if identity['version'] else 'Hemlock · Version unavailable'
                expect(page.locator('#app-version')).to_have_text(expected)
                assert page.locator('#app-version').evaluate("el=>el.nextElementSibling.id")=='logout'
                expect(page.locator('#app-version')).to_have_attribute('title',f"Build commit: {identity['build_commit']}" if identity['build_commit'] else '')
                before=store.snapshot();cached=store.local('protection')
                page.locator('nav button[data-view=info]').click()
                for theme in ('dark','light'):
                    if page.locator('html').get_attribute('data-theme')!=theme:page.locator('#theme').click()
                    expect(page.locator('#app-version')).to_be_visible()
                    page.locator('#navigation').screenshot(path=str(output/f'version-{theme}.png'))
                    for lang,title,mtr,caution,empty in [('EN','About Hemlock','Checking a block','keeping BGP isolated','No results'),('RU','О Hemlock','Проверка блокировки','сохраняя изоляцию BGP','Нет результатов'),('UK','Про Hemlock','Перевірка блокування','зберігаючи ізоляцію BGP','Немає результатів')]:
                        page.locator('.language-switch').get_by_role('button',name=lang,exact=True).click()
                        article=page.locator('.info-page');expect(article.locator('h2').first).to_have_text(title)
                        expect(article.locator('.info-section')).to_have_count(6);expect(article.locator('ol')).to_have_count(2)
                        for ol in article.locator('ol').all():expect(ol.locator('li')).to_have_count(4)
                        expect(article).to_contain_text(mtr);expect(article).to_contain_text('MTR');expect(article).to_contain_text('blackhole');expect(article).to_contain_text(caution)
                        assert 'announcements=no' not in article.inner_text();assert 'withdraw-owned' not in article.inner_text();assert '/etc/' not in article.inner_text()
                        expect(article.locator('.info-states tbody tr')).to_have_count(6)
                        assert article.locator('.info-states tbody tr td:first-child').all_text_contents()==['Applied','Pending','Failed','Excluded by protection','Unknown','Stale']
                        expect(article.locator('.info-protection')).to_contain_text('Info-lab-node')
                        asns=article.locator('[data-protection-kind=asns]');prefixes=article.locator('[data-protection-kind=prefixes]')
                        expect(prefixes.locator('summary')).to_contain_text('(63)');assert prefixes.locator('tbody tr').count()==0
                        asns.locator('summary').click();expect(asns).to_contain_text('AS64496');expect(asns).to_contain_text('GMT+3')
                        prefixes.locator('summary').click();expect(prefixes.locator('tbody tr')).to_have_count(25)
                        expect(prefixes.locator('tbody tr').first).to_contain_text('10.0.0.0/8')
                        expect(prefixes.locator('tbody tr').first).to_contain_text('+')
                        prefixes.locator('[data-page-action=last]').click();expect(prefixes.locator('tbody tr')).to_have_count(13);expect(prefixes).to_contain_text('2001:db8::/32')
                        expect(prefixes.locator('[data-page-action=last]')).to_be_disabled()
                        search=prefixes.locator('input');search.fill('2001:db8');search.press('Enter');expect(prefixes.locator('tbody tr')).to_have_count(1);expect(prefixes.locator('.sub-pagination span')).to_contain_text('1–1')
                        search.fill('no-match');search.press('Enter');expect(prefixes.locator('.sub-pagination span')).to_have_text(empty)
                        search.fill('');search.press('Enter');expect(prefixes.locator('tbody tr')).to_have_count(25)
                        page.locator('.info-protection').screenshot(path=str(output/f'{lang.lower()}-{theme}-protection.png'))
                        page.locator('.info-states').screenshot(path=str(output/f'{lang.lower()}-{theme}-states.png'))
                page.set_viewport_size({'width':390,'height':844});page.locator('.info-states').screenshot(path=str(output/'mobile-states.png'))
                assert before==store.snapshot(),'Info modified shared documents'
                assert cached==store.local('protection'),'Info modified local protection'
                page.locator('#logout').click();expect(page.locator('#login-panel')).to_be_visible()
                expect(page.locator('#app-version')).to_be_hidden()
                assert not errors,errors
                browser.close()
            print('PASS: EN/RU/UK in dark/light, six agreed sections/MTR/ordered failover steps/BGP isolation caveat, one six-row English-key State table, removed duplicate/announcements/path text, live-node config+cache union/ASN expansion time, collapsed 25-row filtered/clamped pagination, timezone/mobile and no data writes.')
        finally:
            server.should_exit=True;thread.join(timeout=15);assert not thread.is_alive()

if __name__=='__main__':main()
