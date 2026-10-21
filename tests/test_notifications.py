"""Real executable tests; temporary files and no actual notification service."""
from dataclasses import replace
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from hemloc.auth import Auth
from hemloc.config import Config
from hemloc.domain import Actor, Forbidden
from hemloc.notifications import Notifications
from hemloc.service import Service
from hemloc.store import Store, encode


class NotificationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.handler=self.root/'handler';self.capture=self.root/'capture'
        self.cfg=Config(tls=False,protected_asns=(),protected_prefixes=(),database=str(self.root/'a.sqlite'),notifications_enabled=True,notification_script=str(self.handler),notification_timeout_seconds=2.0,notification_queue_size=2)
        self.store=Store(self.cfg)

    def handler_code(self, code):
        self.handler.write_text('#!/usr/bin/env python3\n'+code)
        self.handler.chmod(0o700)

    def notifier(self, **values):
        store=Store(replace(self.cfg,**values));notifier=Notifications(store)
        store.on_commit=notifier.committed;store.notifications=notifier
        return notifier

    def test_unicode_quotes_multiline_exact_stdin_no_shell_or_argv(self):
        self.handler_code(f'import sys,json\nfrom pathlib import Path\nassert len(sys.argv)==1\nPath({str(self.capture)!r}).write_bytes(sys.stdin.buffer.read())\n')
        n=self.notifier();message={'subject':'Hemloc «тест»', 'body':'Рядок 1\n"quote"\n$(touch /never-run); `false`'}
        n.send(message)
        self.assertEqual(json.loads(self.capture.read_text()),message)
        self.assertEqual(self.store.audit_history(),[])

    def test_nonzero_timeout_missing_one_attempt_no_failure_loop_or_output_leak(self):
        for mode in ('nonzero','timeout','missing'):
            with self.subTest(mode=mode):
                n=self.notifier()
                if mode=='missing':
                    if self.handler.exists():self.handler.unlink()
                else:
                    code=f'from pathlib import Path\np=Path({str(self.capture)!r})\np.write_text(p.read_text()+"x" if p.exists() else "x")\n'
                    code+= 'import sys\nprint("sensitive-process-output",file=sys.stderr)\nraise SystemExit(7)\n' if mode=='nonzero' else 'import time\ntime.sleep(5)\n'
                    self.handler_code(code)
                self.capture.unlink(missing_ok=True)
                n.send({'subject':'safe','body':'not-in-audit'})
                if mode!='missing':self.assertEqual(self.capture.read_text(),'x')
                self.assertEqual(n.queue.qsize(),0)
        history=encode(self.store.audit_history())
        self.assertEqual(len(self.store.audit_history()),3)
        self.assertNotIn('sensitive-process-output',history);self.assertNotIn('not-in-audit',history)

    def test_disabled_queue_overflow_and_worker_parallelism(self):
        self.handler_code('raise SystemExit(99)\n')
        disabled=self.notifier(notifications_enabled=False)
        disabled.start();disabled.submit('x','y');self.assertFalse(disabled.threads);self.assertEqual(disabled.queue.qsize(),0)
        n=self.notifier()
        n.submit('one','one');n.submit('two','two');n.submit('three','three')
        self.assertEqual(n.queue.qsize(),2)
        self.assertEqual(len(self.store.audit_history()),1)
        self.assertEqual(self.store.audit_history()[0]['after']['reason'],'queue_full')
        active=0;maximum=0;lock=threading.Lock()
        def send(message):
            nonlocal active,maximum
            with lock:active+=1;maximum=max(maximum,active)
            time.sleep(.03)
            with lock:active-=1
        n.send=send;n.start();n.queue.join();n.close()
        self.assertEqual(maximum,1)

    def test_aggregate_threshold_cooldown_real_ips_bounded_memory(self):
        now=[1000.]
        n=self.notifier(notification_queue_size=10);n.clock=lambda:now[0]
        for _ in range(29):n.suspicious('2001:db8::1','invalid_request')
        self.assertEqual(n.queue.qsize(),0)
        n.suspicious('2001:db8::1','invalid_request');self.assertEqual(n.queue.qsize(),1)
        for _ in range(100):n.suspicious('2001:db8::1','invalid_request')
        self.assertEqual(n.queue.qsize(),1)
        now[0]+=901
        for _ in range(30):n.suspicious('2001:db8::1','invalid_request')
        self.assertEqual(n.queue.qsize(),2)
        n.suspicious('not-an-ip','invalid_request');n.suspicious('2001:db8::1','notification.failed')
        self.assertEqual(n.queue.qsize(),2)

    def test_bulk_one_notification_no_unchanged_refresh_no_slave_replay(self):
        n=self.notifier(notification_queue_size=10)
        service=Service(n.store);actor=Actor('admin','admin')
        service.import_manual(actor,[{'value':'192.0.2.1','comment':'first'},{'value':'192.0.2.2','comment':'second'}])
        self.assertEqual(n.queue.qsize(),1)
        self.assertIn('Changes: 2',n.queue.get_nowait()['body'])
        rule=service.add_asn(actor,64500,'reason')
        n.queue.get_nowait()
        service.update_asn(actor,rule['id'],['198.51.100.0/24'])
        self.assertEqual(n.queue.qsize(),1);n.queue.get_nowait()
        service.update_asn(actor,rule['id'],['198.51.100.0/24'])
        self.assertEqual(n.queue.qsize(),0)
        b=Store(replace(self.cfg,role='slave',node_id='block-b',peer_node_id='block-a',database=str(self.root/'b.sqlite')))
        bn=Notifications(b);b.on_commit=bn.committed;b.install_snapshot(n.store.snapshot())
        service.add_manual(actor,'2001:db8::1')
        b.apply_events(n.store.events(b.info()['history'],b.info()['sequence']))
        self.assertEqual(bn.queue.qsize(),0)

    def test_slave_local_security_alerts_without_master_and_two_worker_bound(self):
        n=self.notifier(role='slave',node_id='block-b',peer_node_id='block-a',database=str(self.root/'b.sqlite'),notification_queue_size=10,notification_workers=2)
        n.login_blocked('2001:db8::10',None,500)
        self.assertEqual(n.queue.qsize(),1)
        self.assertIn('block-b',n.queue.get_nowait()['body']);n.queue.task_done()
        active=0;maximum=0;lock=threading.Lock()
        def send(message):
            nonlocal active,maximum
            with lock:active+=1;maximum=max(maximum,active)
            time.sleep(.03)
            with lock:active-=1
        n.send=send;n.start()
        for _ in range(8):n.submit('fixture','fixture')
        n.queue.join();n.close();self.assertEqual(maximum,2)

    def test_rate_limit_scope_known_identity_one_alert_per_limit(self):
        n=self.notifier();service=Service(n.store)
        service.save_user(Actor('root:cli','admin'),'known',role='guest',password_hash='$argon2id$v=19$m=65536,t=3,p=4$fake$fake')
        auth=Auth(n.store,lambda h,p:False,clock=lambda:10000)
        for _ in range(8):
            with self.assertRaises(Forbidden):auth.login('known','do-not-record','192.0.2.1')
        self.assertEqual(n.queue.qsize(),1)
        body=n.queue.get_nowait()['body']
        self.assertIn('known',body);self.assertIn('900 seconds',body);self.assertNotIn('firewall',body)
        self.assertNotIn('do-not-record',encode(self.store.audit_history()))


if __name__=='__main__':unittest.main()
