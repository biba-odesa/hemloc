"""Explicit stopped-slave recovery; preserve damaged files and local TLS state."""
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import time
import uuid

from .domain import Conflict
from .tls import write_private,private,fsync_dir
from .store import Store
from .workers import process_lock


def reinitialize(config,execute=False):
    if config.role!='slave' or config.announcements:
        raise Conflict('Reinitialization requires role=slave and announcements=no; stop Hemlock first')
    path=Path(config.database).resolve();marker=path.with_name(path.name+'.recovery.json')
    sources=[path,Path(str(path)+'-wal'),Path(str(path)+'-shm')]
    if not execute:return {'dry_run':True,'files':[str(p) for p in sources if p.exists()],'trust_preserved':True}
    from .transition import RoleTransition,TERMINAL
    transition=RoleTransition(config).status()
    if transition and transition.get('phase') not in TERMINAL:raise Conflict('Finish or restore the pending role transition before database recovery')
    with process_lock(config.database):
        if marker.exists():
            private(marker,purpose="Recovery");state=json.loads(marker.read_text())
            if (not isinstance(state,dict) or state.get('phase') not in ('prepared','archived','complete')
                    or not isinstance(state.get('backup'),str) or Path(state['backup']).parent!=path.parent
                    or not Path(state['backup']).name.startswith('corrupt-backup-')):raise Conflict('Invalid recovery marker; no files changed')
            if state.get('node_id')!=config.node_id or state.get('database')!=str(path):raise Conflict('Recovery marker identity mismatch')
            if state['phase']=='complete':raise Conflict('Previous recovery completed; archive its marker explicitly before another recovery')
        else:
            protection=None
            try:
                with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=2)) as db:
                    role=db.execute("SELECT value FROM meta WHERE key='role'").fetchone()
                    if role and role[0]=='master':raise Conflict('Use the startup master-to-slave transition for an identifiable master database')
                    row=db.execute("SELECT body FROM local WHERE key='protection'").fetchone()
                    if row:protection=json.loads(row[0])
            except sqlite3.Error:pass
            backup=path.parent/('corrupt-backup-'+time.strftime('%Y%m%d-%H%M%S')+'-'+str(uuid.uuid4()))
            backup.mkdir(mode=0o700)
            state={'node_id':config.node_id,'database':str(path),'backup':str(backup),'phase':'prepared','protection':protection}
            write_private(marker,json.dumps(state).encode())
        backup=Path(state['backup']);private(backup,True,purpose="Recovery")
        if state['phase']=='prepared':
            for source in sources:
                target=backup/source.name
                if source.exists():
                    private(source,purpose="Recovery")
                    if target.exists():raise Conflict('Recovery backup collision; no file was overwritten')
                    os.rename(source,target)
            fsync_dir(path.parent);fsync_dir(backup)
            state['phase']='archived';write_private(marker,json.dumps(state).encode())
        if state['phase']=='archived':
            # An interrupted new database is preserved separately, never merged.
            if path.exists():
                partial=backup/('partial-'+str(uuid.uuid4()));partial.mkdir(mode=0o700)
                for source in sources:
                    if source.exists():os.rename(source,partial/source.name)
            store=Store(config)
            if state['protection'] is not None:store.set_local('protection',state['protection'])
            with store.connect() as db:db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
            state['phase']='complete';write_private(marker,json.dumps(state).encode())
        return {'backup':str(backup),'phase':state['phase'],'protection_recovered':state['protection'] is not None,'trust_preserved':True}
