"""Render sanitized observed BGP data in an isolated authenticated browser fixture.

No production users, sessions, rules or gRPC calls are created by this check.
"""
import argparse
from pathlib import Path
import json
import secrets
import sys
import tempfile
import threading
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from hemlock.auth import password_hash
from hemlock.config import Config
from hemlock.domain import Actor
from hemlock.service import Service
from hemlock.store import Store
from hemlock.web import create_app
from tools.check_gobgp import port,wait_for
import uvicorn
from playwright.sync_api import sync_playwright,expect


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--rib',required=True,help='Sanitized local rib observation JSON')
    args=parser.parse_args()
    rib=json.loads(Path(args.rib).read_text())
    assert rib['peers']
    with tempfile.TemporaryDirectory(prefix='hemlock-observed-ui-') as tmp:
        config=Config(database=str(Path(tmp)/'ui.sqlite'),tls=False,protected_asns=(),metadata_enabled=False)
        store=Store(config)
        password='a1'+secrets.token_urlsafe(24)
        Service(store).save_user(Actor('lab','admin'),'viewer',role='guest',password_hash=password_hash(password))
        rib['at']=time.time()
        store.set_local('rib',rib)
        server=uvicorn.Server(uvicorn.Config(create_app(config,adapter=object(),background=False,observations=store.observations),host='127.0.0.1',port=port(),log_level='error',access_log=False))
        thread=threading.Thread(target=server.run)
        thread.start()
        try:
            wait_for(lambda:server.started)
            with sync_playwright() as playwright:
                browser=playwright.chromium.launch(executable_path='/usr/bin/chromium-headless-shell',headless=True)
                page=browser.new_page()
                page.goto(f'http://127.0.0.1:{server.config.port}')
                page.locator('#login-form input[name=login]').fill('viewer')
                page.locator('#login-form input[name=password]').fill(password)
                page.locator('#login-form button').click()
                expect(page.locator('#peer-state')).to_contain_text('Not configured')
                page.locator('nav button[data-view=dashboard]').click()
                states={1:'Idle',2:'Connect',3:'Active',4:'OpenSent',5:'OpenConfirm',6:'Established'}
                for peer in rib['peers']:
                    row=page.locator('#sessions tr').filter(has_text=peer['description'] or peer['address'])
                    expect(row).to_contain_text(peer['description'] or peer['address'])
                    expect(row).to_contain_text('Disabled' if peer['admin_state']==2 else states[peer['session_state']])
                browser.close()
            print('Observed peer names, session/admin states and absent replication render correctly in an isolated authenticated browser fixture.')
        finally:
            server.should_exit=True
            thread.join(timeout=15)
            assert not thread.is_alive()

if __name__=='__main__':
    main()
