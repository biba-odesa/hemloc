"""Explicit local browser acceptance test; no production services or CDNs."""

import argparse
from configparser import ConfigParser
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time
from urllib.parse import urlsplit

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from hemloc.auth import password_hash
from hemloc.config import load
from hemloc.domain import Actor
from hemloc.service import Service
from hemloc.store import Store


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--directory',required=True)
    parser.add_argument('--browser',default='/usr/bin/chromium-headless-shell')
    args = parser.parse_args()
    if os.geteuid() == 0:
        raise SystemExit('Use an unprivileged test user')
    from playwright.sync_api import sync_playwright, expect
    import httpx
    os.umask(0o077)
    directory = Path(args.directory).resolve()
    directory.mkdir(parents=True,exist_ok=False)
    with socket.socket() as listener:
        listener.bind(('127.0.0.1',0))
        port = listener.getsockname()[1]
    ini = ConfigParser(interpolation=None)
    ini.read(Path(__file__).resolve().parents[1]/'deploy/hemloc.example.ini')
    ini['node'].update(database=str(directory/'browser.sqlite'),peer_url='')
    ini['web'].update(host='127.0.0.1',port=str(port),tls='no')
    ini['protection']['protected_asns'] = ''
    ini['metadata']['metadata_enabled'] = 'no'
    ini['gobgp']['grpc_target'] = '127.0.0.1:9'
    path = directory/'app.ini'
    with path.open('w') as output:
        ini.write(output)
    config = load(path)
    service = Service(Store(config))
    password = 'a1'+secrets.token_urlsafe(24)
    for login,role in [('admin','admin'),('guest','guest')]:
        service.save_user(Actor('lab:browser','admin'),login,role=role,password_hash=password_hash(password))
    log = (directory/'app.log').open('wb')
    process = subprocess.Popen([sys.executable,'-m','hemloc','--config',str(path),'serve'],stdout=log,stderr=log)
    base = f'http://127.0.0.1:{port}'
    errors, external = [], []
    try:
        with httpx.Client(trust_env=False) as client:
            for _ in range(100):
                try:
                    if client.get(base,timeout=1).status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(0.1)
            else:
                raise AssertionError('Browser test application did not start')
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path=args.browser,headless=True)
            context = browser.new_context(viewport={'width':1440,'height':1000})
            def network(route):
                if urlsplit(route.request.url).hostname not in ('127.0.0.1','localhost'):
                    external.append('unexpected external request')
                    route.abort()
                else:
                    route.continue_()
            context.route('**/*',network)
            page = context.new_page()
            page.on('pageerror',lambda error: errors.append(str(error)))
            page.goto(base)
            page.locator('#login-form input[name=login]').fill('admin')
            page.locator('#login-form input[name=password]').fill(password)
            page.locator('#login-form button').click()
            expect(page.locator('#workspace')).to_be_visible()
            expect(page.locator('#identity')).to_contain_text('admin')
            assert page.locator('#announce-mode').count()==0
            expect(page.locator('#blocked-total')).to_contain_text('Unknown')
            assert context.cookies()[0]['httpOnly'] and not context.cookies()[0]['secure']
            page.locator('nav button[data-view=manual]').click()
            def add(value,comment=''):
                page.locator('#add').click()
                page.locator('#edit-form input[name=value]').fill(value)
                page.locator('#edit-form textarea').fill(comment)
                page.locator('#edit-form button.primary').click()
            comment = '<img src=x onerror="window.hemlocInjected=true">'
            add('192.0.2.0/24',comment)
            expect(page.locator('#editor')).not_to_be_visible()
            expect(page.locator('#content')).to_contain_text(comment)
            assert page.locator('#content img').count() == 0
            assert page.evaluate('window.hemlocInjected === undefined')
            add('192.0.2.1')
            expect(page.locator('#editor')).not_to_be_visible()
            add('192.0.2.1/24')
            expect(page.locator('#editor [role=alert]')).to_contain_text('192.0.2.0/24')
            page.locator('[data-close=editor]').click()
            page.locator('nav button[data-view=dashboard]').click()
            page.locator('#search').fill('192.0.2.1')
            page.locator('#search').press('Enter')
            expect(page.locator('#content')).to_contain_text('Matches found: 2')
            page.locator('#search').fill('invalid IP')
            page.locator('#search').press('Enter')
            expect(page.locator('#notice')).to_contain_text('IPv4 or IPv6')
            page.locator('#search').fill('192.0.2.1')
            page.locator('#search').press('Enter')
            expect(page.locator('#content')).to_contain_text('Matches found: 2')
            expect(page.locator('#notice')).not_to_be_visible()
            page.screenshot(path=str(directory/'dark.png'),full_page=True)
            page.locator('#theme').click()
            expect(page.locator('html')).to_have_attribute('data-theme','light')
            page.screenshot(path=str(directory/'light.png'),full_page=True)
            page.reload()
            expect(page.locator('#workspace')).to_be_visible()
            expect(page.locator('html')).to_have_attribute('data-theme','light')
            page.set_viewport_size({'width':390,'height':844})
            page.screenshot(path=str(directory/'mobile.png'),full_page=True)
            guest_context = browser.new_context()
            guest_context.route('**/*',network)
            guest = guest_context.new_page()
            guest.on('pageerror',lambda error: errors.append(str(error)))
            guest.goto(base)
            guest.locator('#login-form input[name=login]').fill('guest')
            guest.locator('#login-form input[name=password]').fill(password)
            guest.locator('#login-form button').click()
            expect(guest.locator('#workspace')).to_be_visible()
            expect(guest.locator('#add')).not_to_be_visible()
            expect(guest.locator('#read-only')).to_be_visible()
            expect(guest.locator('nav button[data-view=users]')).to_be_visible()
            guest_context.close()
            context.close()
            browser.close()
        assert not errors, 'Browser JavaScript errors were observed'
        assert not external, 'An external page request was attempted'
        print('Chromium browser checks passed: real login/cookies, themes, mobile viewport, escaped HTML, overlapping IP search, canonical-network errors and guest restrictions.')
        print('Browser UI used explicit HTTP bootstrap; two-node TLS is verified separately.')
    finally:
        process.terminate()
        try:
            process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            process.kill(); process.wait()
        log.close()
        if password in (directory/'app.log').read_text():
            raise AssertionError('A test credential leaked into the application log')


if __name__ == '__main__':
    main()
