"""Isolated browser password policy check; no live DB or GoBGP interaction."""
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
    with tempfile.TemporaryDirectory(prefix='hemloc-password-ui-') as tmp:
        cfg=Config(database=str(Path(tmp)/'ui.sqlite'),tls=False,protected_asns=(),metadata_enabled=False)
        password='a1'+secrets.token_urlsafe(24)
        Service(Store(cfg)).save_user(Actor('lab','admin'),'admin',role='admin',password_hash=password_hash(password))
        server=uvicorn.Server(uvicorn.Config(create_app(cfg,adapter=object(),background=False),host='127.0.0.1',port=port(),access_log=False,log_level='error'))
        thread=threading.Thread(target=server.run)
        thread.start()
        try:
            wait_for(lambda:server.started)
            with sync_playwright() as playwright:
                browser=playwright.chromium.launch(executable_path='/usr/bin/chromium-headless-shell',headless=True)
                page=browser.new_page()
                page.goto(f'http://127.0.0.1:{server.config.port}')
                def login(value):
                    page.locator('#login-form input[name=login]').fill('admin')
                    page.locator('#login-form input[name=password]').fill(value)
                    page.locator('#login-form button').click()
                    expect(page.locator('#workspace')).to_be_visible()
                login(password)
                page.locator('nav button[data-view=users]').click()
                page.locator('#add').click()
                form=page.locator('#user-form')
                expect(form).to_contain_text('at least one letter and one digit')
                expect(form.locator('input[name=password]')).to_have_attribute('minlength','6')
                form.locator('input[name=login]').fill('six-character-user')
                form.locator('input[name=password]').fill('123456')
                form.locator('button.primary').click()
                expect(form.locator('[role=alert]')).to_contain_text('at least one letter and one digit')
                form.locator('input[name=password]').fill('abcde1')
                form.locator('button.primary').click()
                expect(page.locator('#user-editor')).not_to_be_visible()
                expect(page.locator('#content')).to_contain_text('six-character-user')
                page.locator('#password-button').click()
                change=page.locator('#password-form')
                change.locator('input[name=current_password]').fill(password)
                change.locator('input[name=new_password]').fill('ABCDE1')
                change.locator('input[name=repeat]').fill('ABCDE1')
                change.locator('button.primary').click()
                expect(page.locator('#login-panel')).to_be_visible()
                login('ABCDE1')
                browser.close()
            print('Browser: numeric-only password rejected; six-character lowercase+digit create and uppercase+digit own change/login pass; hints and minlength agree.')
        finally:
            server.should_exit=True
            thread.join(timeout=15)
            assert not thread.is_alive()

if __name__=='__main__':
    main()
