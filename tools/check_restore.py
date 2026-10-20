"""Online SQLite backup and offline restore drill, entirely in temporary directories."""
from dataclasses import replace
import json
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hemloc.auth import password_hash, password_verify
from hemloc.config import Config
from hemloc.domain import Actor
from hemloc.service import Service
from hemloc.store import Store

with tempfile.TemporaryDirectory(prefix='hemloc-restore-') as tmp:
    root = Path(tmp)
    cfg = Config(database=str(root/'master.sqlite'),tls=False,node_id='a',peer_node_id='b')
    master = Store(cfg)
    service = Service(master)
    actor = Actor('drill','admin')
    service.add_manual(actor,'192.0.2.99')
    service.save_user(actor,'drill',role='admin',password_hash=password_hash('Restore-drill-password-123'))
    slave_cfg = replace(cfg,database=str(root/'slave.sqlite'),node_id='b',peer_node_id='a',role='slave')
    slave = Store(slave_cfg)
    Service(slave).grow_protection(64496,['192.0.2.0/24'])
    slave.install_snapshot(master.snapshot())
    service.add_manual(actor,'2001:db8::99')
    slave.apply_events(master.events(slave.info()['history'],slave.info()['sequence']))
    for name, store, config in [('master',master,cfg),('slave',slave,slave_cfg)]:
        backup = root/f'{name}.backup'
        store.backup(backup)
        destination = root/f'{name}-restored'
        destination.mkdir()
        restored_path = destination/'hemloc.sqlite'
        # The source is a completed online backup, never an open live DB file.
        shutil.copyfile(backup,restored_path)
        restored = Store(replace(config,database=str(restored_path)),activate=False)
        assert restored.info() == store.info()
        assert restored.list('rule') == store.list('rule')
        assert restored.list('user') == store.list('user')
        assert restored.audit_history() == store.audit_history()
        assert restored.local('protection') == store.local('protection')
        assert password_verify(restored.get('user','drill')['password_hash'],'Restore-drill-password-123')
        with restored.connect() as db:
            assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        if name == 'slave':
            service.add_manual(actor,'192.0.2.100')
            restored.apply_events(master.events(restored.info()['history'],restored.info()['sequence']))
            assert restored.list('rule') == master.list('rule')
            assert Service(restored).protection().reason('192.0.2.1/32')
    print(json.dumps({'online_backup':'master and slave', 'restored':'rules, users/password verification, audit, history/sequence cursor, local protection',
                      'integrity':'ok for both', 'post_restore_journal':'caught up without snapshot; local protection retained',
                      'runtime':'separate temporary directories, removed after drill'},indent=2))
