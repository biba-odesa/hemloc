"""Real isolated HTTPS pair and Chromium audit/notification acceptance checks."""
import argparse
from dataclasses import replace
import json
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import threading
import time
import uuid
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import uvicorn
from playwright.sync_api import sync_playwright, expect
from hemloc.auth import password_hash
from hemloc.config import Config
from hemloc.domain import Actor, NeedSnapshot
from hemloc.replication import PeerTransport, Replicator
from hemloc.retention import execute, preview
from hemloc.service import Service
from hemloc.store import Store
from hemloc.web import create_app
from tools.check_gobgp import port, wait_for


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--directory',required=True);args=parser.parse_args()
    output=Path(args.directory);output.mkdir(parents=True,exist_ok=False)
    with tempfile.TemporaryDirectory(prefix='hemloc-audit-workflow-') as tmp:
        root=Path(tmp);p1,p2=port(),port()
        subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','1','-keyout',str(root/'tls.key'),'-out',str(root/'tls.crt'),'-subj','/CN=localhost','-addext','subjectAltName=IP:127.0.0.1'],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        (root/'peer.token').write_text(secrets.token_urlsafe(48))
        capture=root/'notifications.jsonl';handler=root/'notify'
        handler.write_text('#!/usr/bin/env python3\nimport sys,json\nmessage=json.load(sys.stdin)\nassert set(message)=={"subject","body"}\nwith open('+repr(str(capture))+',"a") as f:f.write(json.dumps(message)+"\\n")\n');handler.chmod(0o700)
        cfg=Config(database=str(root/'a.sqlite'),node_id='a',peer_node_id='b',peer_url=f'https://127.0.0.1:{p2}',host='127.0.0.1',port=p1,cert=str(root/'tls.crt'),key=str(root/'tls.key'),ca=str(root/'tls.crt'),token_file=str(root/'peer.token'),protected_asns=(),protected_prefixes=(),metadata_enabled=False,notifications_enabled=True,notification_script=str(handler))
        bcfg=replace(cfg,database=str(root/'b.sqlite'),node_id='b',peer_node_id='a',role='slave',port=p2,peer_url=f'https://127.0.0.1:{p1}')
        a,b=Store(cfg),Store(bcfg);service=Service(a);admin=Actor('fixture','admin');password='a1'+secrets.token_urlsafe(24)
        hashed=password_hash(password)
        for login,role in (('admin','admin'),('guest','guest')):service.save_user(admin,login,role=role,password_hash=hashed)
        for i in range(31):service.add_manual(admin,f'192.0.2.{i+1}',f'History fixture {i+1:02}')
        # Old synthetic security events only, never a working audit.
        with a.transaction() as db:
            for _ in range(4):
                doc={'id':str(uuid.uuid4()),'at':time.time()-10*86400,'node':'a','actor':'anonymous','action':'http.request','object':'request','before':None,'after':None,'result':'invalid'}
                op={'kind':'audit','id':doc['id'],'doc':doc};a.operation(db,op);a.append_journal(db,[op])
        b.install_snapshot(a.snapshot());servers=[];threads=[];apps=[]
        def launch(config):
            app=create_app(config,adapter=object(),background=False);apps.append(app)
            server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=config.port,ssl_certfile=config.cert,ssl_keyfile=config.key,proxy_headers=False,access_log=False,log_level='error'))
            thread=threading.Thread(target=server.run);thread.start();servers.append(server);threads.append(thread);wait_for(lambda:server.started)
        try:
            launch(cfg);launch(bcfg)
            ar,br=Replicator(a,PeerTransport(cfg)),Replicator(b,PeerTransport(bcfg))
            ar.step();br.step();ar.step()
            before_snapshot=a.snapshot();plan=preview(a);assert len(plan['payload']['entries'])==4
            execute(a,plan);br.step();ar.step()
            try:
                PeerTransport(bcfg).get("/replication/snapshot")
                raise AssertionError("Legacy snapshot requester unexpectedly accepted")
            except NeedSnapshot:
                pass
            br.step()  # The rejected legacy request itself is correctly audited.
            assert a.list('audit')==b.list('audit')
            # Snapshot captured before prune, then journal catch-up over real HTTPS.
            b.install_snapshot(before_snapshot);br.step();assert a.list('audit')==b.list('audit')
            # Outage preserves state; a restarted node catches up without duplicate notifications.
            servers[1].should_exit=True;threads[1].join(10)
            old=b.info()
            try:ar.step();raise AssertionError('Outage unexpectedly succeeded')
            except OSError:pass
            except RuntimeError:pass
            assert b.info()==old
            service.add_manual(admin,'2001:db8::1','During outage')
            launch(bcfg);br.step();ar.step();assert a.list('audit')==b.list('audit')
            with sync_playwright() as pw:
                spki=subprocess.check_output(['openssl','x509','-in',str(root/'tls.crt'),'-pubkey','-noout'])
                pub=subprocess.run(['openssl','pkey','-pubin','-outform','DER'],input=spki,capture_output=True,check=True).stdout
                import base64,hashlib
                fingerprint=base64.b64encode(hashlib.sha256(pub).digest()).decode()
                browser=pw.chromium.launch(executable_path='/usr/bin/chromium-headless-shell',headless=True,args=['--ignore-certificate-errors-spki-list='+fingerprint])
                page=browser.new_page(viewport={'width':1440,'height':1000},timezone_id='Europe/Kyiv');errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                def login(name,port_number=p1):
                    page.goto(f'https://127.0.0.1:{port_number}');page.locator('#login-form input[name=login]').fill(name);page.locator('#login-form input[name=password]').fill(password);page.locator('#login-form button').click();expect(page.locator('#workspace')).to_be_visible()
                login('admin');page.locator('nav button[data-view=audit]').click()
                for theme in ('dark','light'):
                    if page.locator('html').get_attribute('data-theme')!=theme:page.locator('#theme').click()
                    expect(page.locator('[role=tab]')).to_have_count(3)
                    expect(page.locator('[role=tab][aria-selected=true]')).to_have_text('Blocklist changes')
                    expect(page.locator('#page-label')).to_contain_text('Page 1 of 2');page.locator('#next').click();expect(page.locator('#page-label')).to_contain_text('Page 2 of 2')
                    page.locator('#search').fill('History fixture 01');page.locator('#search').press('Enter');expect(page.locator('#page-label')).to_contain_text('Showing 1–1 of 1')
                    page.locator('#content summary').click();expect(page.locator('#content')).to_contain_text('Before / After')
                    page.locator('#search').fill('no-results-fixture');page.locator('#search').press('Enter');expect(page.locator('#page-label')).to_have_text('No results')
                    page.locator('#search').fill('');page.locator('#search').press('Enter')
                    page.get_by_role('tab',name='Users & access',exact=True).click();expect(page.locator('#content')).to_contain_text('Sign in')
                    page.get_by_role('tab',name='Errors & security',exact=True).click();expect(page.locator('#content tbody')).to_contain_text('Denied')
                    page.get_by_role('tab',name='Blocklist changes',exact=True).click()
                    page.screenshot(path=str(output/f'history-admin-{theme}.png'),full_page=True)
                page.locator('#logout').click();expect(page.locator('#login-panel')).to_be_visible();login('guest');page.locator('nav button[data-view=audit]').click();expect(page.locator('[role=tab]')).to_have_count(1)
                for endpoint in ('history','audit'):
                    denied=page.evaluate('(path)=>fetch(path).then(r=>r.status)', f'/api/{endpoint}?category=users_access')
                    assert denied==403
                page.locator('nav button[data-view=users]').click();expect(page.locator('.own-login-history tbody tr')).to_have_count(1)
                page.locator('#logout').click();expect(page.locator('#login-panel')).to_be_visible();login('guest',p2);page.locator('nav button[data-view=users]').click();expect(page.locator('#password-button')).to_be_disabled()
                # Notifications: only new originating master mutations enqueue; replicas never do.
                apps[0].state.service.import_manual(admin,[{'value':'198.51.100.1','comment':'Unicode «тест»\nquote "x"'},{'value':'198.51.100.2','comment':'second'}])
                apps[0].state.store.notifications.queue.join()
                br.step();ar.step();br.step()
                messages=[json.loads(line) for line in capture.read_text().splitlines()]
                assert len(messages)==1 and 'Changes: 2' in messages[0]['body']
                assert not errors,errors
                browser.close()
            print('PASS: real verified HTTPS snapshot/prune journal/replay/outage/restart catch-up; admin three tabs/guest one tab and direct API denials; SQL search/server pagination/empty/details in dark+light; own/slave account; one Unicode bulk notification and none on replication; isolated data only.')
        finally:
            for server in servers:server.should_exit=True
            for thread in threads:thread.join(15);assert not thread.is_alive()


if __name__=='__main__':main()
