"""Isolated audit classification, exact maintenance, transport and calendar contracts."""
import copy
from dataclasses import replace
from datetime import datetime
import json
from pathlib import Path
import tempfile
import time
import unittest
import uuid
from zoneinfo import ZoneInfo

from hemlock.config import Config, load
from hemlock.domain import Actor, Conflict, Forbidden, Invalid
from hemlock.history import query
from hemlock.retention import CAPABILITY, RetentionWorker, due_day, execute, export, preview, write_private
from hemlock.service import Service
from hemlock.store import Store, digest, encode

ADMIN = Actor('admin', 'admin')
GUEST = Actor('guest', 'guest')
NOW = 1800000000.


class RetentionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg = Config(tls=False, protected_asns=(), database=self.tmp.name+'/a.sqlite', node_id='a', peer_node_id='b', retention_batch_size=2)
        self.a = Store(self.cfg)
        self.b = Store(replace(self.cfg, role='slave', node_id='b', peer_node_id='a', database=self.tmp.name+'/b.sqlite'))

    def event(self, action='http.request', result='invalid', age=10, actor='anonymous', node='a', after=None):
        doc = {'id':str(uuid.uuid4()), 'at':NOW-age*86400, 'node':node, 'actor':actor,
               'action':action, 'object':'request', 'before':None, 'after':after, 'result':result}
        with self.a.transaction() as db:
            self.a.operation(db, {'kind':'audit', 'id':doc['id'], 'doc':doc})
            self.a.append_journal(db, [{'kind':'audit', 'id':doc['id'], 'doc':doc}])
        return doc

    def test_sql_classification_permissions_search_and_pagination(self):
        self.event('rule.create', 'saved', after={'comment':'searchable Український текст'})
        self.event('rule.create', 'denied', actor='guest')
        self.event('auth.login', 'denied')
        self.event('future.unknown', 'failed', age=1000)
        self.assertEqual(query(self.a, GUEST)['total'], 1)
        self.assertEqual(query(self.a, ADMIN, 'errors_security')['total'], 1)
        self.assertEqual(query(self.a, ADMIN, 'users_access')['total'], 1)
        self.assertEqual(query(self.a, ADMIN, 'unknown')['total'], 1)
        with self.assertRaises(Forbidden):query(self.a, GUEST, 'errors_security')
        self.assertEqual(query(self.a, GUEST, q='searchable')['total'], 1)
        self.assertEqual(query(self.a, GUEST, q='УКРАЇНСЬКИЙ')['total'], 1)
        self.assertEqual(query(self.a, GUEST, q='no match')['total'], 0)
        self.assertEqual(query(self.a, GUEST, number=999, size=1)['page'], 1)
        self.assertEqual(len(preview(self.a, NOW)['payload']['entries']), 1)

    def test_cutoff_boundary_last_five_disabled_identities_and_unknown_retained(self):
        boundary = self.event(age=7)
        expired = self.event(age=7.000001)
        self.event('future.unknown', 'failed', age=1000)
        old_login_ids=[]
        for i in range(8):
            old_login_ids.append(self.event('auth.login','success',age=100+i, actor='disabled',node='a' if i%2 else 'b')['id'])
        plan = preview(self.a, NOW)
        ids = {e['id'] for e in plan['payload']['entries']}
        self.assertNotIn(boundary['id'], ids)
        self.assertIn(expired['id'], ids)
        self.assertTrue(set(old_login_ids[:5]).isdisjoint(ids))
        self.assertTrue(set(old_login_ids[5:]) <= ids)
        execute(self.a, plan, NOW)
        self.assertEqual(len(self.a.successful_logins('disabled')), 5)

    def test_prune_replay_snapshot_race_reconnect_and_promotion_no_resurrection(self):
        deleted = self.event()
        self.b.install_snapshot(self.a.snapshot())
        snap_before = self.a.snapshot()
        before = self.b.info()
        plan = preview(self.a, NOW)
        execute(self.a, plan, NOW)
        batch = self.a.events(before['history'], before['sequence'])
        self.b.apply_events(batch); self.b.apply_events(batch)
        self.assertEqual(self.b.list('audit'), self.a.list('audit'))
        self.assertNotIn(deleted['id'], {d['id'] for d in self.b.audit_history()})
        self.assertEqual(self.a.snapshot()['payload']['schema'], 2)
        # Even an older, valid snapshot cannot resurrect already receipted IDs.
        self.b.install_snapshot(snap_before)
        self.assertIsNone(self.b.get('audit', deleted['id']))
        self.b.apply_events(self.a.events(self.b.info()['history'], self.b.info()['sequence']))
        self.b.install_snapshot(self.a.snapshot())
        promoted = Store(replace(self.b.config, role='master'))
        self.assertNotIn(deleted['id'], {d['id'] for d in promoted.audit_history()})
        old = Store(replace(self.cfg, role='slave'))
        old.install_snapshot(promoted.snapshot())
        self.assertEqual(old.audit_history(), promoted.audit_history())

    def test_outbox_pending_acknowledged_pruned_and_promotion(self):
        self.b.install_snapshot(self.a.snapshot())
        doc = self.b.security_event('anonymous','http.request','request','invalid')
        # Age only this isolated fixture; preserve transport id and sequence.
        with self.b.transaction() as db:
            doc['at']=NOW-10*86400
            db.execute('UPDATE security_audit SET body=? WHERE id=?',(encode(doc),doc['id']))
        outbox = self.b.local_security_events()
        self.a.ingest_security(outbox)
        self.b.apply_events(self.a.events(self.b.info()['history'],self.b.info()['sequence']))
        execute(self.a, preview(self.a,NOW), NOW)
        pending = self.b.security_event('anonymous','auth.login','session','denied')
        self.b.install_snapshot(self.a.snapshot())
        self.assertEqual(len(self.b.local_security_events()['events']), 2)
        self.assertNotIn(doc['id'], {d['id'] for d in self.b.audit_history()})
        self.assertIn(pending['id'], {d['id'] for d in self.b.audit_history()})
        promoted=Store(replace(self.b.config, role='master'))
        self.assertNotIn(doc['id'], {d['id'] for d in promoted.audit_history()})
        self.assertIn(pending['id'], {d['id'] for d in promoted.audit_history()})
        # Replaying old security payload on a fresh history is tombstone-safe.
        self.a.ingest_security(outbox)
        self.assertIsNone(self.a.get('audit',doc['id']))

    def test_manifest_tamper_stale_role_and_generic_audit_immutability(self):
        self.event()
        plan=preview(self.a,NOW)
        bad=copy.deepcopy(plan);bad['payload']['entries'][0]['digest']='0'*64
        with self.assertRaises(Invalid):execute(self.a,bad,NOW)
        with self.assertRaises(Forbidden):execute(self.b,plan,NOW)
        with self.a.transaction() as db:
            with self.assertRaises(Invalid):self.a.operation(db,{'kind':'audit','id':plan['payload']['entries'][0]['id'],'doc':None})
        execute(self.a,plan,NOW)
        execute(self.a,plan,NOW)  # Exact replay is safe.

    def test_mixed_protocol_cleanup_gate_and_pending_outbox_gate(self):
        cfg=replace(self.cfg,peer_url='https://peer.invalid')
        a=Store(cfg)
        self.event()
        plan=preview(a,NOW)
        with self.assertRaises(Conflict):execute(a,plan,NOW)
        self.b.install_snapshot(a.snapshot())
        with self.b.connect() as db:security_history=self.b.meta(db,'security_history')
        a.ingest_security(self.b.local_security_events())
        a.set_local('peer',{'at':NOW,'status':{'role':'slave','capabilities':[CAPABILITY], 'security_history':security_history,'security_sequence':0}})
        a.set_local('peer_ack',{'history':a.info()['history'],'sequence':a.info()['sequence']})
        execute(a,plan,NOW)

    def test_daily_catchup_restart_dst_and_disabled(self):
        zone=ZoneInfo('Europe/Kyiv')
        cfg=replace(self.cfg,retention_enabled=True)
        a=Store(cfg)
        self.event()
        worker=RetentionWorker(a,lambda:NOW)
        worker.step(); seq=a.info()['sequence'];worker.step()
        self.assertEqual(a.info()['sequence'],seq)
        RetentionWorker(Store(cfg),lambda:NOW+3*86400).step()
        self.assertGreater(a.local('retention_schedule')['completed_day'],due_day(cfg,NOW))
        for day in ('2026-03-29','2026-10-25'):
            before=datetime.fromisoformat(day+'T00:59:00').replace(tzinfo=zone).timestamp()
            after=datetime.fromisoformat(day+'T01:01:00').replace(tzinfo=zone).timestamp()
            self.assertNotEqual(due_day(cfg,before),due_day(cfg,after))
        disabled=Store(self.cfg);state=disabled.local('retention_schedule');RetentionWorker(disabled,lambda:NOW+5*86400).step()
        self.assertEqual(state,disabled.local('retention_schedule'))

    def test_snapshot_read_transaction_is_consistent_during_prune(self):
        import threading
        self.event()
        plan=preview(self.a,NOW)
        fixed=threading.Event();resume=threading.Event();snapshots=[]
        original=self.a.meta
        def meta(db,key,default=''):
            value=original(db,key,default)
            if threading.current_thread().name=='snapshot-test' and key=='history':
                fixed.set();self.assertTrue(resume.wait(5))
            return value
        self.a.meta=meta
        thread=threading.Thread(target=lambda:snapshots.append(self.a.snapshot()),name='snapshot-test')
        thread.start();self.assertTrue(fixed.wait(5))
        try:execute(self.a,plan,NOW)
        finally:resume.set();thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(snapshots[0]['payload']['schema'],1)
        self.b.install_snapshot(snapshots[0]);self.b.apply_events(self.a.events(self.b.info()['history'],self.b.info()['sequence']))
        self.assertEqual(self.a.list('audit'),self.b.list('audit'))

    def test_partial_batch_restart_exact_replay_and_serialization(self):
        from unittest.mock import patch
        from hemlock.workers import process_lock
        for _ in range(5):self.event()
        plan=preview(self.a,NOW);original=self.a.append_journal;calls=[0]
        def append(db,operations):
            calls[0]+=1
            if calls[0]==2:raise RuntimeError('Simulated interrupted batch')
            return original(db,operations)
        with patch.object(self.a,'append_journal',side_effect=append):
            with self.assertRaises(RuntimeError):execute(self.a,plan,NOW)
        self.assertEqual(sum(d['action']=='http.request' for d in self.a.audit_history()),3)
        with process_lock(self.cfg.database+'.retention'):
            with self.assertRaises(Conflict):execute(self.a,plan,NOW)
        execute(Store(self.cfg),plan,NOW)
        self.assertEqual(sum(d['action']=='http.request' for d in self.a.audit_history()),0)
        self.assertEqual(sum(d['action']=='audit.prune' for d in self.a.audit_history()),3)

    def test_actual_v010_store_works_before_prune_and_rejects_v2(self):
        import importlib.util,subprocess,tarfile,io,sys
        root=Path(self.tmp.name)/'legacy';root.mkdir()
        archive=subprocess.check_output(['git','archive','v0.1.0','hemloc'])
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:tar.extractall(root,filter='data')
        name='hemloc_legacy_retention_test'
        spec=importlib.util.spec_from_file_location(name,root/'hemloc/__init__.py',submodule_search_locations=[str(root/'hemloc')])
        module=importlib.util.module_from_spec(spec);sys.modules[name]=module;spec.loader.exec_module(module)
        legacy=__import__(name+'.store',fromlist=['Store'])
        old=legacy.Store(self.b.config)
        event=self.event();old.install_snapshot(self.a.snapshot())
        service=Service(self.a);service.add_manual(ADMIN,'192.0.2.1')
        old.apply_events(self.a.events(old.info()['history'],old.info()['sequence']))
        self.assertEqual(old.list('rule'),self.a.list('rule'))
        before=old.info()
        execute(self.a,preview(self.a,NOW),NOW)
        with self.assertRaises(ValueError):old.apply_events(self.a.events(before['history'],before['sequence']))
        self.assertEqual(old.info(),before)
        with self.assertRaises(ValueError):old.install_snapshot(self.a.snapshot())
        upgraded=Store(self.b.config);upgraded.install_snapshot(self.a.snapshot())
        self.assertIsNone(upgraded.get('audit',event['id']))

    def test_prune_preserves_rules_users_credentials_sessions_and_protection(self):
        from hemlock.auth import Auth
        service=Service(self.a)
        service.save_user(ADMIN,'admin',role='admin',password_hash='$argon2id$v=19$m=65536,t=3,p=4$fake$fake')
        service.add_manual(ADMIN,'192.0.2.1','Keep rule')
        token,csrf=Auth(self.a,lambda h,p:True).login('admin','fixture','192.0.2.10')
        self.a.set_local('protection',{'prefixes':['198.51.100.0/24'],'success':{}})
        before=[self.a.list('rule'),self.a.list('user'),self.a.local('protection'),service.routes()]
        self.event();execute(self.a,preview(self.a,NOW),NOW)
        self.assertEqual(before,[self.a.list('rule'),self.a.list('user'),self.a.local('protection'),service.routes()])
        self.assertEqual(Auth(self.a).session(token)[1],csrf)

    def test_private_export_and_config_validation(self):
        self.event()
        dest=Path(self.tmp.name)/'export.jsonl'
        self.assertFalse(export(self.a)['written']);self.assertFalse(dest.exists())
        self.assertTrue(export(self.a,dest)['written']);self.assertEqual(dest.stat().st_mode & 0o777,0o600)
        with self.assertRaises(FileExistsError):export(self.a,dest)
        plan=Path(self.tmp.name)/'plan.json';write_private(plan,preview(self.a,NOW));self.assertEqual(plan.stat().st_mode & 0o777,0o600)
        cfg=load('deploy/hemlock.example.ini');self.assertFalse(cfg.retention_enabled);self.assertFalse(cfg.notifications_enabled)
        for change in ({'blocklist_days':0},{'cleanup_time':'25:00'},{'retention_timezone':'Nowhere/Invalid'},{'notification_workers':100}):
            with self.assertRaises(Invalid):replace(self.cfg,**change).validate()


if __name__=='__main__':unittest.main()
