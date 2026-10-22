"""Crash-resumable startup demotion; its durable fence lives outside SQLite."""
from contextlib import closing
from dataclasses import replace
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import sqlite3
import stat
import time
import uuid

from .domain import Conflict

TERMINAL = {'complete', 'restored'}
PHASES = {'prepared', 'drain_attempted', 'checkpointed', 'backed_up', 'new_ready', 'db_ready'} | TERMINAL


class DrainFailure(Conflict):
    def __init__(self, stage, error=None):
        super().__init__('Dedicated GoBGP drain did not finish')
        self.stage = stage
        code = getattr(error, 'code', lambda:None)()
        self.rpc_code = getattr(code, 'name', None)


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:os.fsync(fd)
    finally:os.close(fd)


def private_file(path, *, uid=None):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != (os.geteuid() if uid is None else uid) or info.st_mode & 0o077:
        raise Conflict('Role transition requires regular, service-owned mode 0600 files')
    return info


def digest_file(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def identity(path, *, recover=False):
    if not path.exists():return {}
    private_file(path)
    if path.stat().st_size == 0:return {}
    # Active/staging files may need SQLite's own hot-journal recovery after a
    # crash. Immutable backup validation always keeps the read-only default.
    mode = 'rw' if recover else 'ro'
    with closing(sqlite3.connect(path.resolve().as_uri()+'?mode='+mode, uri=True, timeout=2)) as db:
        return dict(db.execute('SELECT key,value FROM meta'))


def checkpoint(path):
    private_file(path)
    with closing(sqlite3.connect(path, timeout=2, isolation_level=None)) as db:
        result = db.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()
        if result[0] or (result[1] >= 0 and result[1] != result[2]):
            raise Conflict('WAL checkpoint busy; stop other database clients before retrying')
        # This obtains the stronger lock required to detach WAL/SHM safely.
        if db.execute('PRAGMA journal_mode=DELETE').fetchone()[0].lower() != 'delete':
            raise Conflict('Could not detach SQLite sidecars')
    if any(Path(str(path)+suffix).exists() for suffix in ('-wal', '-shm')):
        raise Conflict('SQLite sidecars remain; database backup was not moved')
    with path.open('rb') as stream:os.fsync(stream.fileno())


def move_exclusive(source, destination):
    """No-overwrite move with a recoverable same-inode intermediate state."""
    if destination.exists():
        if source.exists() and not os.path.samestat(source.stat(), destination.stat()):
            raise Conflict('Role transition destination already exists')
    else:
        os.link(source, destination, follow_symlinks=False)
        sync_directory(source.parent)
    if source.exists():source.unlink()
    sync_directory(source.parent)


class RoleTransition:
    def __init__(self, config):
        self.config = config
        self.database = Path(config.database).absolute()
        self.path = Path(str(self.database)+'.role-transition.json')

    def read(self):
        if not self.path.exists():return None
        private_file(self.path)
        try:
            state = json.loads(self.path.read_text())
            assert state['version'] == 1 and state['phase'] in PHASES
            assert state['node_id'] == self.config.node_id and state['owner'] == list(self.config.owner)
            assert state['database'] == str(self.database)
            uuid.UUID(state['id'])
            assert re.fullmatch(r'[0-9]{8}T[0-9]{6}Z', state['stamp'])
            assert state['backup'] == str(self.database)+'.backup-'+state['stamp']+'-'+state['id']
            assert state['staging'] == str(self.database)+'.new-'+state['id']
            assert type(state['cleanup_required']) is bool
            return state
        except (ValueError, KeyError, TypeError, AssertionError):
            raise Conflict('Invalid role-transition state; operator recovery required') from None

    def save(self, state):
        temporary = Path(str(self.path)+'.tmp-'+uuid.uuid4().hex)
        try:
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'w') as stream:
                json.dump(state, stream, sort_keys=True, allow_nan=False)
                stream.flush();os.fsync(stream.fileno())
            os.replace(temporary, self.path)
            sync_directory(self.path.parent)
        finally:
            if temporary.exists():temporary.unlink()

    def status(self):
        state = self.read()
        if not state:return None
        return {key:state.get(key) for key in ('phase','cleanup_required','gobgp','cleanup_stage','rpc_code','error')}

    def preflight(self):
        private_file(self.database)
        if not os.access(self.database.parent, os.W_OK | os.X_OK):
            raise Conflict('Database directory is not writable for role transition')
        size = self.database.stat().st_size
        wal = Path(str(self.database)+'-wal')
        needed = size + (wal.stat().st_size if wal.exists() else 0) + 16*1024*1024
        if shutil.disk_usage(self.database.parent).free < needed:
            raise Conflict('Insufficient free space for safe role transition')

    def drain(self, state, adapter):
        try:
            adapter.drain_for_transition()
        except Exception as error:
            # Only a separate conservative OS probe may classify a stopped daemon.
            if getattr(adapter, 'confirmed_absent', lambda:False)():
                state.update(gobgp='confirmed_absent', error='GoBGP is absent; cleanup remains required')
                self.save(state)
                return False
            stage = getattr(error, 'stage', 'inspection')
            condition = 'withdraw_failed' if stage == 'withdrawal' else ('verification_failed' if stage == 'verification' else 'grpc_unknown')
            state.update(gobgp=condition, cleanup_stage=stage, rpc_code=getattr(error,'rpc_code',None),
                         error='GoBGP cleanup not verified ('+condition+'); route application is fenced')
            self.save(state)
            raise Conflict(state['error']) from None
        state.update(cleanup_required=False, gobgp='verified_empty', cleanup_stage='verified', rpc_code=None, error='')
        self.save(state)
        return True

    def prepare(self, adapter):
        state = self.read()
        saved = identity(self.database, recover=True)
        if saved.get('node_id') not in (None, self.config.node_id):
            raise Conflict('Database belongs to a different node')
        if state and state['phase'] not in TERMINAL:
            if self.config.role != 'slave':
                raise Conflict('Unfinished demotion; restore backup and use transition reset-after-restore')
        elif self.config.role == 'slave' and saved.get('role') == 'master':
            with closing(sqlite3.connect(self.database.resolve().as_uri()+'?mode=ro', uri=True)) as db:
                preserved = {key:json.loads(body) for key,body in db.execute("SELECT key,body FROM local WHERE key IN ('protection','protection_schedule')")}
            identifier = str(uuid.uuid4())
            stamp = time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())
            state = {'version':1, 'id':identifier, 'stamp':stamp, 'phase':'prepared',
                     'node_id':self.config.node_id, 'owner':list(self.config.owner),
                     'database':str(self.database), 'backup':str(self.database)+'.backup-'+stamp+'-'+identifier,
                     'staging':str(self.database)+'.new-'+identifier, 'preserved':preserved,
                     'cleanup_required':True, 'gobgp':'unknown', 'error':''}
            self.save(state)
        else:return
        if state['phase'] == 'prepared':
            self.preflight()
            self.drain(state, adapter)
            state['phase'] = 'drain_attempted';self.save(state)
        if state['phase'] == 'drain_attempted':
            self.preflight()
            checkpoint(self.database)
            state['source_digest'] = digest_file(self.database)
            state['phase'] = 'checkpointed';self.save(state)
        if state['phase'] == 'checkpointed':
            backup = Path(state['backup'])
            source = self.database if self.database.exists() else backup
            if digest_file(source) != state['source_digest']:
                raise Conflict('Checkpointed source changed; backup move refused')
            move_exclusive(self.database, backup)
            state['phase'] = 'backed_up';self.save(state)
        if state['phase'] == 'backed_up':
            if self.database.exists():raise Conflict('Unexpected active database during transition')
            from .store import Store
            staging = Path(state['staging'])
            store = Store(replace(self.config, database=str(staging)))
            with store.transaction() as db:
                if db.execute('SELECT COUNT(*) FROM documents').fetchone()[0] or db.execute('SELECT COUNT(*) FROM sessions').fetchone()[0] or db.execute('SELECT COUNT(*) FROM security_audit').fetchone()[0]:
                    raise Conflict('Staging database is not empty')
                store.set_meta(db, 'bootstrap_transition_id', state['id'])
                for key,value in state['preserved'].items():store.write_local(db, key, value)
            checkpoint(staging)
            state['new_digest'] = digest_file(staging)
            state['phase'] = 'new_ready';self.save(state)
        if state['phase'] == 'new_ready':
            staging = Path(state['staging'])
            source = staging if staging.exists() else self.database
            if digest_file(source) != state['new_digest']:
                raise Conflict('New database changed before installation')
            move_exclusive(staging, self.database)
            state['phase'] = 'db_ready';self.save(state)
        if state['phase'] == 'db_ready':
            self.check_store(activate=False)
            if not state['cleanup_required']:
                state['phase'] = 'complete';self.save(state)

    def check_store(self, activate):
        state = self.read()
        if state and state['phase'] not in TERMINAL and (self.config.role != 'slave' or state['phase'] != 'db_ready'):
            raise Conflict('Incomplete startup transition; database use is fenced')
        saved = identity(self.database, recover=True)
        if state and state['phase'] not in TERMINAL:
            if (self.config.role != 'slave' or state['phase'] != 'db_ready'
                    or saved.get('role') != 'slave' or saved.get('bootstrap_transition_id') != state['id']):
                raise Conflict('Incomplete startup transition; database use is fenced')
        if activate and self.config.role == 'slave' and saved.get('role') == 'master':
            raise Conflict('Master-to-slave demotion requires application startup migration')

    def guard(self, adapter):
        state = self.read()
        if not state or state['phase'] in TERMINAL:return
        self.check_store(activate=False)
        if not self.drain(state, adapter):
            raise Conflict('GoBGP absent; cleanup required before applying routes')
        state['phase'] = 'complete';self.save(state)

    def assert_add_allowed(self):
        state = self.read()
        if state and state['phase'] not in TERMINAL:
            raise Conflict('Role-transition cleanup must finish before adding routes')

    def assert_write_allowed(self):
        state = self.read()
        if state and state['phase'] not in TERMINAL:self.check_store(activate=False)

    def reset_after_restore(self, backup, execute=False):
        if self.config.role != 'master':raise Conflict('Restore requires role=master in local configuration')
        state = self.read()
        if not state:raise Conflict('No role transition to reset')
        backup = Path(backup).absolute()
        if backup == self.database:raise Conflict('Backup must be a separate file')
        if any(Path(str(path)+suffix).exists() for path in (backup,self.database) for suffix in ('-wal','-shm')):
            raise Conflict('Restored database and backup must not have WAL/SHM sidecars')
        expected,restored = identity(backup),identity(self.database)
        if expected.get('role') != 'master' or expected.get('node_id') != self.config.node_id or restored != expected:
            raise Conflict('Restored master identity does not match backup')
        if digest_file(self.database) != digest_file(backup):raise Conflict('Database is not an exact backup restore')
        if execute:
            state.update(phase='restored',cleanup_required=False,error='',restored_at=time.time())
            self.save(state)
        return {'mode':'execute' if execute else 'dry-run', 'restored':bool(execute)}
