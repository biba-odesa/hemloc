"""Security audit invariants with two stores and an explicit peer outbox."""
from tests.role_helpers import demote


import copy
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest

from hemlock.auth import Auth
from hemlock.config import Config
from hemlock.domain import Actor, Conflict, Forbidden, Invalid
from hemlock.replication import Replicator
from hemlock.service import Service
from hemlock.store import Store, encode, redact

ADMIN = Actor('admin', 'admin')
HASH = '$argon2id$v=19$m=65536,t=3,p=4$fake$fake'


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = Config(tls=False, database=str(Path(self.tmp.name)/'a.sqlite'), node_id='a', peer_node_id='b')
        self.slave_cfg = replace(self.cfg, role='slave', node_id='b', peer_node_id='a', database=str(Path(self.tmp.name)/'b.sqlite'))
        self.master, self.slave = Store(self.cfg), Store(self.slave_cfg)
        self.service = Service(self.master)

    def tearDown(self):
        self.tmp.cleanup()

    def test_rejected_change_rolls_back_data_but_records_sanitized_failure(self):
        sentinel = 'never-include-request-values'
        with self.assertRaises(Forbidden):
            self.service.add_manual(Actor('viewer','guest'), sentinel, comment=sentinel)
        self.assertEqual(self.master.list('rule'), [])
        audit = self.master.list('audit')
        self.assertEqual(len(audit),1)
        self.assertEqual(audit[0]['result'],'denied')
        self.assertEqual(audit[0]['actor'],'viewer')
        self.assertIsNone(audit[0]['before'])
        self.assertIsNone(audit[0]['after'])
        self.assertNotIn(sentinel,encode(audit))
        events = self.master.events(self.master.info()['history'],0)
        self.assertEqual([o['kind'] for o in events['events'][0]['operations']],['audit'])

    def test_login_outcomes_and_logout_never_record_credentials(self):
        self.service.save_user(ADMIN,'admin',role='admin',password_hash=HASH)
        auth = Auth(self.master,lambda h,p: p == 'good-password')
        token, csrf = auth.login('admin','good-password','client')
        auth.logout(token)
        for _ in range(5):
            with self.assertRaises(Forbidden):
                auth.login('password-that-is-not-a-login','bad-password','bad-client')
        with self.assertRaises(Forbidden):
            auth.login('admin','good-password','bad-client')
        history = self.master.audit_history()
        text = encode(history)
        for secret in (HASH,token,csrf,'good-password','bad-password','password-that-is-not-a-login','bad-client'):
            self.assertNotIn(secret,text)
        self.assertEqual(sum(a['result']=='throttled' for a in history),1)
        self.assertEqual(sum(a['result']=='denied' for a in history),5)
        self.assertEqual(sum(a['action']=='auth.logout' for a in history),1)

    def test_auth_verifier_failure_is_generic_and_audited(self):
        self.service.save_user(ADMIN,'admin',role='admin',password_hash=HASH)
        def broken(encoded,password):
            raise RuntimeError('sensitive-exception-string')
        with self.assertRaisesRegex(RuntimeError,'Authentication service unavailable'):
            Auth(self.master,broken).login('admin','sensitive-password','client')
        self.assertNotIn('sensitive',encode(self.master.audit_history()))
        self.assertEqual(sum(a['result']=='failed' for a in self.master.audit_history()),1)

    def test_slave_outbox_cannot_change_shared_data_or_cursor(self):
        self.slave.install_snapshot(self.master.snapshot())
        before = self.slave.info()
        with self.assertRaises(Forbidden):
            Service(self.slave).add_manual(ADMIN,'192.0.2.1')
        self.assertEqual(self.slave.info(),before)
        self.assertEqual(self.slave.list('audit'),[])
        local = self.slave.local_security_events()
        self.assertEqual(len(local['events']),1)
        self.assertEqual(len(self.slave.audit_history()),1)
        cursor = self.master.ingest_security(local)
        self.assertEqual(cursor,1)
        info = self.master.info()
        self.master.ingest_security(local)
        self.assertEqual(self.master.info(),info)
        self.slave.apply_events(self.master.events(before['history'],before['sequence']))
        self.assertEqual(len(self.slave.audit_history()),1)
        self.assertEqual(self.slave.list('audit'),self.master.list('audit'))

    def test_master_polls_security_facts_from_slave(self):
        slave = self.slave
        slave.security_event('anonymous','auth.login','session','denied')
        class Transport:
            def get(inner,path,query=None):
                if path.endswith('/status'):
                    return slave.info()
                return slave.local_security_events(after=query['after'],history=query['history'])
        Replicator(self.master,Transport()).step()
        self.assertEqual(len(self.master.list('audit')),1)
        Replicator(self.master,Transport()).step()
        self.assertEqual(len(self.master.list('audit')),1)

    def test_malicious_peer_batch_rolls_back_including_cursor(self):
        self.slave.security_event('anonymous','auth.login','session','denied')
        self.slave.security_event('anonymous','auth.login','session','denied')
        batch = self.slave.local_security_events()
        bad = copy.deepcopy(batch)
        bad['events'][1]['doc']['after'] = {'password':'do-not-store'}
        with self.assertRaises(Invalid):
            self.master.ingest_security(bad)
        self.assertEqual(self.master.list('audit'),[])
        self.assertEqual(self.master.info()['sequence'],0)
        bad = copy.deepcopy(batch)
        bad['events'][1]['seq'] += 1
        with self.assertRaises(Invalid):
            self.master.ingest_security(bad)
        self.assertEqual(self.master.list('audit'),[])
        self.master.ingest_security(batch)
        self.assertEqual(len(self.master.list('audit')),2)

    def test_new_outbox_generation_restarts_its_cursor(self):
        self.slave.security_event('anonymous','auth.login','session','denied')
        self.master.ingest_security(self.slave.local_security_events())
        new_cfg = replace(self.slave_cfg,database=str(Path(self.tmp.name)/'replacement.sqlite'))
        replacement = Store(new_cfg)
        replacement.security_event('anonymous','auth.login','session','throttled')
        with self.master.connect() as db:
            old_history = self.master.meta(db,'peer_security_history')
        batch = replacement.local_security_events(after=1,history=old_history)
        self.assertEqual(len(batch['events']),1)
        self.master.ingest_security(batch)
        self.assertEqual(len(self.master.list('audit')),2)

    def test_promotion_publishes_local_security_but_not_old_master_branch(self):
        self.slave.install_snapshot(self.master.snapshot())
        self.slave.security_event('anonymous','auth.login','session','denied')
        promoted = Store(replace(self.slave_cfg,role='master'))
        self.assertEqual(len(promoted.list('audit')),1)
        self.service.add_manual(ADMIN,'192.0.2.0/24','discarded branch')
        old = demote(replace(self.cfg,role='slave'))
        old.install_snapshot(promoted.snapshot())
        self.assertEqual(old.list('rule'),[])
        self.assertNotIn('discarded branch',encode(old.audit_history()))

    def test_security_categories_are_allowlisted_and_nested_keys_are_redacted(self):
        with self.assertRaises(Invalid):
            self.master.security_event('anonymous','arbitrary secret','request','failed')
        self.assertEqual(redact({'new_password':'x','accessToken':'x','nested':[{'private-key':'x','ok':1}]}),{'nested':[{'ok':1}]})


if __name__ == '__main__':
    unittest.main()
