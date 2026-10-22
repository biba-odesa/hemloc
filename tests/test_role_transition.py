"""Startup transitions are fenced, durable and resumable on isolated databases."""
from contextlib import closing
from dataclasses import replace
from pathlib import Path
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from hemlock.config import Config
from hemlock.domain import Actor, Conflict
from hemlock.presentation import View
from hemlock.reconcile import Reconciler
from hemlock.service import Service
from hemlock.store import Store
from hemlock.transition import RoleTransition, checkpoint, digest_file, DrainFailure

ADMIN=Actor('fixture','admin')


class Crash(BaseException):pass


class Daemon:
    def __init__(self, mode='up'):
        self.mode=mode;self.paths=['192.0.2.1/32','2001:db8::1/128','198.51.100.1/32'];self.deleted=[]
    def confirmed_absent(self):return self.mode=='absent'
    def drain_for_transition(self):
        if self.mode in ('absent','unknown'):raise OSError('Not a safe log message')
        while self.paths:
            self.deleted.append(self.paths.pop())
            if self.mode=='partial':raise DrainFailure('withdrawal')


class TransitionTests(unittest.TestCase):
    def fixture(self, root):
        cfg=Config(database=str(root/'node.sqlite'),tls=False,node_id='a',peer_node_id='b',protected_asns=(64496,),protected_prefixes=('203.0.113.128/25',))
        master=Store(cfg);service=Service(master)
        service.add_manual(ADMIN,'192.0.2.1','Old branch')
        service.save_user(ADMIN,'operator',role='admin',password_hash='$argon2id$fake')
        master.set_local('protection',{'prefixes':['203.0.113.0/24'],'success':{'64496':10}})
        master.set_local('protection_schedule',{'64496':{'next':time.time()+10000,'error':''}})
        with master.transaction() as db:
            db.execute('INSERT INTO sessions VALUES(?,?,?,?,?)',('fixture-token','operator',1,'fixture-csrf',time.time()+100))
        return cfg,master,replace(cfg,role='slave')

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.cfg,self.master,self.slave_cfg=self.fixture(Path(self.tmp.name))

    def assert_new_database(self,cfg,old_documents):
        state=RoleTransition(cfg).read();slave=Store(cfg)
        self.assertEqual(slave.list('rule'),[]);self.assertEqual(slave.list('user'),[]);self.assertEqual(slave.audit_history(),[])
        self.assertEqual(slave.info()['role'],'slave');self.assertEqual(slave.info()['history'],'')
        self.assertEqual(slave.local('protection')['prefixes'],['203.0.113.0/24'])
        self.assertTrue(Service(slave).protection_ready())
        self.assertTrue(Service(slave).protection().reason('203.0.113.1/32'))
        self.assertIsNone(Service(slave).protection().reason('203.0.0.0/16'))
        self.assertIn('64496',slave.local('protection_schedule'))
        with slave.connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM sessions').fetchone()[0],0)
        backup=Path(state['backup']);self.assertTrue(backup.exists());self.assertEqual(backup.stat().st_mode&0o777,0o600)
        with closing(sqlite3.connect(backup)) as db:
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0],'ok')
            self.assertEqual(db.execute('SELECT COUNT(*) FROM documents').fetchone()[0],old_documents)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM sessions').fetchone()[0],1)
        return slave,state

    def document_count(self):
        with self.master.connect() as db:return db.execute('SELECT COUNT(*) FROM documents').fetchone()[0]

    def test_demotion_drains_all_then_fresh_slave_preserves_only_protection(self):
        count=self.document_count();daemon=Daemon();transition=RoleTransition(self.slave_cfg)
        transition.prepare(daemon)
        slave,state=self.assert_new_database(self.slave_cfg,count)
        self.assertFalse(daemon.paths);self.assertEqual(len(daemon.deleted),3)
        self.assertEqual(state['phase'],'complete');self.assertFalse(state['cleanup_required'])
        before=digest_file(Path(state['backup']))
        transition.prepare(daemon);Store(self.slave_cfg)
        self.assertEqual(RoleTransition(self.slave_cfg).read()['backup'],state['backup'])
        self.assertEqual(digest_file(Path(state['backup'])),before)
        # A stale Store object cannot mutate the new slave or reuse its old branch.
        with self.assertRaises(Exception):Service(self.master).add_manual(ADMIN,'192.0.2.2')
        self.assertEqual(Service(slave).routes()[0],{})

    def test_absent_daemon_keeps_fence_through_snapshot_and_restart(self):
        daemon=Daemon('absent');transition=RoleTransition(self.slave_cfg);transition.prepare(daemon)
        slave=Store(self.slave_cfg)
        authority=Store(replace(self.cfg,node_id='b',peer_node_id='a',database=self.tmp.name+'/authority.sqlite'))
        fresh=Service(authority).add_manual(ADMIN,'198.51.100.5')
        slave.install_snapshot(authority.snapshot())
        with self.assertRaises(Conflict):Reconciler(Service(slave),daemon).step()
        with self.assertRaises(Conflict):transition.assert_add_allowed()
        slave.set_local('rib',{'at':time.time(),'paths':[]})
        self.assertTrue(View(Service(slave)).dashboard()['errors'])
        self.assertIsNone(View(Service(slave)).dashboard()['blocked'])
        backup=transition.read()['backup']
        transition.prepare(daemon)
        self.assertEqual(Store(self.slave_cfg).list('rule'),[fresh])
        self.assertEqual(transition.read()['backup'],backup)
        daemon.mode='up';transition.guard(daemon)
        self.assertFalse(daemon.paths)
        transition.assert_add_allowed()
        self.assertEqual(Store(self.slave_cfg).list('rule'),[fresh])
        self.assertEqual(transition.read()['phase'],'complete')

    def test_unknown_or_partial_failure_never_installs_or_applies_old_branch(self):
        for mode in ('unknown','partial'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as temporary:
                cfg,master,slave_cfg=self.fixture(Path(temporary));daemon=Daemon(mode)
                transition=RoleTransition(slave_cfg)
                with self.assertRaises(Conflict):transition.prepare(daemon)
                self.assertEqual(transition.read()['phase'],'prepared')
                self.assertEqual(transition.read()['gobgp'],'withdraw_failed' if mode=='partial' else 'grpc_unknown')
                self.assertTrue(transition.read()['cleanup_required'])
                with self.assertRaises(Conflict):Store(slave_cfg)
                with self.assertRaises(Conflict):Store(cfg)
                with self.assertRaises(Conflict):Reconciler(Service(master),daemon).step()
                daemon.mode='up';transition.prepare(daemon)
                self.assertFalse(daemon.paths);self.assertEqual(Store(slave_cfg).list('rule'),[])

    def test_resume_after_every_persisted_phase(self):
        for phase in ('prepared','drain_attempted','checkpointed','backed_up','new_ready','db_ready','complete'):
            with self.subTest(phase=phase),tempfile.TemporaryDirectory() as temporary:
                cfg,master,slave_cfg=self.fixture(Path(temporary));transition=RoleTransition(slave_cfg);daemon=Daemon()
                original=transition.save;crashed=[False]
                def save(state):
                    original(state)
                    if state['phase']==phase and not crashed[0]:crashed[0]=True;raise Crash()
                with patch.object(transition,'save',side_effect=save):
                    with self.assertRaises(Crash):transition.prepare(daemon)
                self.assertTrue(crashed[0]);backup=transition.read()['backup']
                RoleTransition(slave_cfg).prepare(daemon)
                self.assertEqual(RoleTransition(slave_cfg).read()['backup'],backup)
                self.assertEqual(Store(slave_cfg).list('rule'),[])
                with closing(sqlite3.connect(backup)) as db:self.assertGreater(db.execute('SELECT COUNT(*) FROM documents').fetchone()[0],0)
                self.assertEqual(RoleTransition(slave_cfg).read()['phase'],'complete')

    def test_resume_no_overwrite_moves_after_link_before_unlink(self):
        for crash_on in (1,2):
            with self.subTest(crash_on=crash_on),tempfile.TemporaryDirectory() as temporary:
                cfg,master,slave_cfg=self.fixture(Path(temporary));transition=RoleTransition(slave_cfg);daemon=Daemon()
                link=os.link;calls=[0]
                def interrupted(*args,**kwargs):
                    link(*args,**kwargs);calls[0]+=1
                    if calls[0]==crash_on:raise Crash()
                with patch('hemlock.transition.os.link',side_effect=interrupted):
                    with self.assertRaises(Crash):transition.prepare(daemon)
                transition.prepare(daemon)
                self.assertEqual(Store(slave_cfg).list('rule'),[])
                self.assertEqual(transition.read()['phase'],'complete')

    def test_checkpoint_failure_free_space_and_new_database_failure_are_fenced(self):
        transition=RoleTransition(self.slave_cfg);daemon=Daemon()
        usage=shutil.disk_usage(self.tmp.name)
        with patch('hemlock.transition.shutil.disk_usage',return_value=usage._replace(free=0)):
            with self.assertRaises(Conflict):transition.prepare(daemon)
        self.assertTrue(transition.read()['cleanup_required'])
        with self.assertRaises(Conflict):Service(self.master).add_manual(ADMIN,'192.0.2.8')
        with patch('hemlock.transition.checkpoint',side_effect=OSError('checkpoint failed')):
            with self.assertRaises(OSError):transition.prepare(daemon)
        self.assertEqual(transition.read()['phase'],'drain_attempted')
        with patch('hemlock.transition.move_exclusive',side_effect=OSError('backup failed')):
            with self.assertRaises(OSError):transition.prepare(daemon)
        self.assertEqual(transition.read()['phase'],'checkpointed')
        original_save=transition.save
        def fail_stage(state):
            original_save(state)
            if state['phase']=='backed_up':raise Crash()
        with patch.object(transition,'save',side_effect=fail_stage):
            with self.assertRaises(Crash):transition.prepare(daemon)
        with patch('hemlock.store.Store',side_effect=OSError('new database failed')):
            with self.assertRaises(OSError):transition.prepare(daemon)
        self.assertFalse(Path(self.cfg.database).exists())
        transition.prepare(daemon)
        self.assertEqual(Store(self.slave_cfg).list('rule'),[])

    def test_promotion_preserves_everything_and_archives_old_journal_without_delete(self):
        slave_cfg=replace(self.cfg,node_id='b',peer_node_id='a',database=self.tmp.name+'/b.sqlite',role='slave')
        slave=Store(slave_cfg);slave.install_snapshot(self.master.snapshot())
        slave.set_local('protection',{'prefixes':['203.0.113.0/24'],'success':{}})
        before=(slave.list('rule'),slave.list('user'),slave.audit_history(),slave.local('protection'))
        old_history=slave.info()['history']
        with slave.transaction() as db:db.execute('INSERT INTO journal VALUES(?,?)',(77,'[]'))
        promoted=Store(replace(slave_cfg,role='master'))
        self.assertEqual(before,(promoted.list('rule'),promoted.list('user'),promoted.audit_history(),promoted.local('protection')))
        self.assertNotEqual(promoted.info()['history'],old_history)
        with promoted.connect() as db:
            table=db.execute('SELECT table_name FROM journal_generations WHERE history=?',(old_history,)).fetchone()[0]
            self.assertEqual(tuple(db.execute('SELECT seq,body FROM '+table).fetchone()),(77,'[]'))
        history=promoted.info()['history'];RoleTransition(promoted.config).prepare(Daemon())
        self.assertEqual(Store(promoted.config).info()['history'],history)
        with self.assertRaises(Conflict):promoted.install_snapshot(self.master.snapshot())

    def test_regular_slave_restart_does_not_reset_cached_rules(self):
        slave_cfg=replace(self.cfg,node_id='b',peer_node_id='a',database=self.tmp.name+'/b.sqlite',role='slave')
        slave=Store(slave_cfg);slave.install_snapshot(self.master.snapshot())
        before=slave.info(),slave.list('rule')
        RoleTransition(slave_cfg).prepare(Daemon('unknown'))
        self.assertEqual((Store(slave_cfg).info(),Store(slave_cfg).list('rule')),before)
        self.assertFalse(RoleTransition(slave_cfg).path.exists())

    def test_backup_restore_requires_exact_bytes_stopped_owner_and_master_role(self):
        transition=RoleTransition(self.slave_cfg);transition.prepare(Daemon())
        backup=Path(transition.read()['backup'])
        current=Path(self.cfg.database);checkpoint(current)
        current.rename(current.with_name('saved-current.sqlite'))
        shutil.copy2(backup,current)
        with self.assertRaises(Conflict):transition.reset_after_restore(backup,True)
        rollback=RoleTransition(self.cfg)
        self.assertFalse(rollback.reset_after_restore(backup)['restored'])
        self.assertTrue(rollback.reset_after_restore(backup,True)['restored'])
        master=Store(self.cfg)
        self.assertEqual(master.list('rule')[0]['comment'],'Old branch')
        self.assertEqual(rollback.read()['phase'],'restored')

    def test_busy_reader_prevents_wal_detach_then_resume(self):
        reader=self.master.connect();reader.execute('BEGIN');reader.execute('SELECT COUNT(*) FROM documents').fetchone()
        Service(self.master).add_manual(ADMIN,'192.0.2.9')
        transition=RoleTransition(self.slave_cfg)
        try:
            with self.assertRaises((Conflict,sqlite3.OperationalError)):transition.prepare(Daemon())
            self.assertEqual(transition.read()['phase'],'drain_attempted')
            with self.assertRaises(Conflict):Store(self.slave_cfg)
        finally:reader.close()
        transition.prepare(Daemon())
        self.assertEqual(Store(self.slave_cfg).list('rule'),[])

    def test_reserved_backup_and_bad_permissions_never_overwrite(self):
        transition=RoleTransition(self.slave_cfg);save=transition.save
        def reserve(state):
            save(state)
            if state['phase']=='prepared':
                Path(state['backup']).write_bytes(b'reserved')
                raise Crash()
        with patch.object(transition,'save',side_effect=reserve):
            with self.assertRaises(Crash):transition.prepare(Daemon())
        backup=Path(transition.read()['backup'])
        with self.assertRaises(Conflict):transition.prepare(Daemon())
        self.assertEqual(backup.read_bytes(),b'reserved')
        transition.path.chmod(0o644)
        with self.assertRaises(Conflict):transition.read()
        with self.assertRaises(Conflict):Store(self.slave_cfg)

    def test_real_process_death_hot_journal_recovers_active_and_staging(self):
        script = """import os,sqlite3,sys
conn=sqlite3.connect(sys.argv[1],isolation_level=None)
conn.execute('PRAGMA journal_mode=DELETE')
conn.execute('PRAGMA cache_size=1')
conn.execute('BEGIN IMMEDIATE')
conn.execute("UPDATE meta SET value='uncommitted-role' WHERE key='role'")
conn.execute('CREATE TABLE crash_payload(data BLOB)')
conn.execute('INSERT INTO crash_payload VALUES(zeroblob(500000))')
os._exit(9)
"""
        for staging in (False, True):
            with self.subTest(staging=staging),tempfile.TemporaryDirectory() as temporary:
                cfg,master,slave_cfg=self.fixture(Path(temporary));transition=RoleTransition(slave_cfg)
                if staging:
                    save=transition.save
                    def stop(state):
                        save(state)
                        if state['phase']=='backed_up':raise Crash()
                    with patch.object(transition,'save',side_effect=stop):
                        with self.assertRaises(Crash):transition.prepare(Daemon())
                    path=transition.read()['staging'];Store(replace(slave_cfg,database=path))
                else:path=cfg.database
                process=subprocess.run([sys.executable,'-c',script,path],capture_output=True)
                self.assertEqual(process.returncode,9)
                self.assertTrue(Path(path+'-journal').exists())
                transition.prepare(Daemon())
                slave=Store(slave_cfg)
                self.assertEqual(slave.info()['role'],'slave');self.assertFalse(slave.list('rule'))
                self.assertEqual(transition.read()['phase'],'complete')

    def test_durable_state_write_failure_cannot_flip_role(self):
        transition=RoleTransition(self.slave_cfg)
        with patch('hemlock.transition.os.replace',side_effect=OSError('disk failure')):
            with self.assertRaises(OSError):transition.prepare(Daemon())
        with self.master.connect() as db:self.assertEqual(self.master.meta(db,'role'),'master')
        with self.assertRaises(Conflict):Store(self.slave_cfg)
        transition.prepare(Daemon())
        self.assertEqual(Store(self.slave_cfg).list('rule'),[])


if __name__=='__main__':unittest.main()
