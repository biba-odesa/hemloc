"""Partial-success batches use only isolated SQLite files and fake notification handlers."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from hemlock.batch import add
from hemlock.config import Config
from hemlock.domain import Actor, Forbidden, Invalid
from hemlock.notifications import Notifications
from hemlock.service import Service
from hemlock.store import Store, encode

ADMIN=Actor('operator','admin')


class BatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.cfg=Config(tls=False,database=self.tmp.name+'/a.sqlite',node_id='a',peer_node_id='b',protected_asns=(),protected_prefixes=('10.0.0.0/8','2001:db8:ffff::/48'),notifications_enabled=True)
        self.store=Store(self.cfg);self.service=Service(self.store)
        self.notifications=Notifications(self.store);self.store.notifications=self.notifications;self.store.on_commit=self.notifications.committed

    def test_partial_dual_stack_normalization_audit_notification_and_replication(self):
        self.service.add_manual(ADMIN,'192.0.2.1')
        self.notifications.queue.get_nowait()
        values='192.0.2.1/32, 192.0.2.2\n2001:0db8:0:0::1,2001:db8::1/128\n10.1.2.3,2001:db8:ffff::1\n192.0.2.5/24\nnot-an-address'
        result=add(self.service,ADMIN,values,'Shared «comment»')
        self.assertEqual((result['added'],result['skipped'],result['invalid']),(2,2,4))
        self.assertEqual({i['code'] for i in result['items']},{'existing_duplicate','batch_duplicate','saved','protected','invalid_cidr'})
        self.assertEqual(self.notifications.queue.qsize(),1)
        message=self.notifications.queue.get_nowait();self.assertIn('Added: 2',message['body']);self.assertIn(result['batch_id'],message['body'])
        audits=self.store.audit_history()
        changes=[e for e in audits if (e.get('after') or {}).get('batch_id')==result['batch_id'] and e['result']=='saved']
        self.assertEqual(len(changes),2)
        self.assertTrue(all(e['after']['comment']=='Shared «comment»' and e['actor']=='operator' for e in changes))
        summary=[e for e in audits if e['action']=='rule.batch'];self.assertEqual(len(summary),1)
        self.assertNotIn('not-an-address',encode(summary));self.assertEqual(summary[0]['after']['invalid'],4)
        b=Store(replace(self.cfg,database=self.tmp.name+'/b.sqlite',role='slave',node_id='b',peer_node_id='a'))
        b.install_snapshot(self.store.snapshot());b.on_commit=lambda events:self.fail('Replica must not notify')
        self.assertEqual(self.store.list('rule'),b.list('rule'))
        follow=add(self.service,ADMIN,'198.51.100.1,198.51.100.2','Follow-up')
        b.apply_events(self.store.events(b.info()['history'],b.info()['sequence']))
        self.assertEqual(self.store.list('audit'),b.list('audit'))
        self.assertEqual(self.store.list('rule'),b.list('rule'))

    def test_concurrent_and_repeated_requests_never_duplicate_or_repeat_change_notice(self):
        def run(_):return add(Service(self.store),ADMIN,'192.0.2.10,2001:db8::10','Concurrent')
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(run,range(2)))
        self.assertEqual(sum(r['added'] for r in results),2)
        self.assertEqual(sum(r['skipped'] for r in results),2)
        self.assertEqual(len(self.store.list('rule')),2)
        before=self.notifications.queue.qsize();again=run(0)
        self.assertEqual((again['added'],again['skipped']),(0,2))
        self.assertEqual(before,self.notifications.queue.qsize())

    def test_limits_before_writes_and_role_checks(self):
        small=Service(Store(replace(self.cfg,batch_max_items=2)))
        with self.assertRaises(Invalid):add(small,ADMIN,'192.0.2.1,192.0.2.2,192.0.2.3')
        with self.assertRaises(Invalid):add(small,ADMIN,'x'*(self.cfg.request_max_bytes+1))
        with self.assertRaises(Forbidden):add(small,Actor('guest','guest'),'192.0.2.1')
        slave=Store(replace(self.cfg,role='slave',database=self.tmp.name+'/slave.sqlite'))
        with self.assertRaises(Forbidden):add(Service(slave),ADMIN,'192.0.2.1')
        self.assertEqual(self.store.list('rule'),[])

    def test_infrastructure_failure_returns_confirmed_results_and_keeps_rest(self):
        original=self.store.change_many;calls=[0]
        def change(*args,**kwargs):
            calls[0]+=1
            if calls[0]==2:raise OSError('Sensitive infrastructure exception')
            return original(*args,**kwargs)
        with patch.object(self.store,'change_many',side_effect=change):
            result=add(self.service,ADMIN,'192.0.2.1,192.0.2.2,192.0.2.3')
        self.assertEqual((result['added'],result['unconfirmed']),(1,2))
        self.assertEqual(result['status'],'interrupted');self.assertTrue(result['error'])
        self.assertNotIn('Sensitive',encode(result));self.assertEqual(len(self.store.list('rule')),1)
        self.assertEqual([i['status'] for i in result['items']],['added','unconfirmed','unconfirmed'])

    def test_summary_failure_does_not_claim_full_success_or_lose_committed_results(self):
        with patch.object(self.store,'security_event',side_effect=OSError('Do not expose')):
            result=add(self.service,ADMIN,'192.0.2.1,invalid')
        self.assertEqual(result['added'],1);self.assertTrue(result['error']);self.assertEqual(result['status'],'interrupted')
        self.assertIsNotNone(self.store.get('rule',result['items'][0]['rule_id']))

    def test_classifier_index_upgrade_keeps_audit_and_uses_current_expression(self):
        from hemlock.history import CATEGORY,VISIBLE
        self.service.add_manual(ADMIN,'192.0.2.30','Keep audit')
        before=self.store.audit_history()
        with self.store.connect() as db:
            db.execute('DROP INDEX history_v2_documents')
            db.execute("CREATE INDEX history_documents ON documents(json_extract(body,'$.at')) WHERE kind='audit'")
        upgraded=Store(self.cfg)
        self.assertEqual(upgraded.audit_history(),before)
        with upgraded.connect() as db:
            plans=[r['detail'] for r in db.execute('EXPLAIN QUERY PLAN SELECT body FROM '+VISIBLE+' AND ('+CATEGORY+")=? LIMIT 25",('blocklist',))]
        self.assertTrue(any('history_v2_documents' in plan for plan in plans))
        self.assertTrue(any('history_v2_security_audit' in plan for plan in plans))

    def test_metadata_is_not_called_by_batch(self):
        with patch('hemlock.irr.Metadata.origins',side_effect=RuntimeError('Unavailable metadata')) as origins:
            result=add(self.service,ADMIN,'192.0.2.20,2001:db8::20')
        self.assertEqual(result['added'],2);origins.assert_not_called()


if __name__=='__main__':unittest.main()
