"""Explicit offline protection transfer, never a database clone."""
import argparse
from contextlib import closing
import json
import math
import os
from pathlib import Path
import sqlite3
import time
from hemlock.config import load
from hemlock.domain import asn, prefix
from hemlock.store import Store, digest
from hemlock.workers import process_lock

def validate(payload):
    if not set(payload) == {'schema', 'node', 'exported_at', 'asns', 'explicit', 'cache'}:
        raise ValueError('Protection transfer validation failed')
    if not (payload['schema'] == 1 and isinstance(payload['node'], str)):
        raise ValueError('Protection transfer validation failed')
    if not (type(payload['exported_at']) in (int, float) and math.isfinite(payload['exported_at'])):
        raise ValueError('Protection transfer validation failed')
    if not (isinstance(payload['asns'], list) and all((type(n) is int and asn(n) == n for n in payload['asns']))):
        raise ValueError('Protection transfer validation failed')
    if not len(set(payload['asns'])) == len(payload['asns']):
        raise ValueError('Protection transfer validation failed')
    for values in (payload['explicit'], payload['cache']['prefixes']):
        if not (isinstance(values, list) and len(values) <= 1000000):
            raise ValueError('Protection transfer validation failed')
        if not all((isinstance(p, str) and prefix(p) == p for p in values)):
            raise ValueError('Protection transfer validation failed')
    if not set(payload['cache']) == {'prefixes', 'success'}:
        raise ValueError('Protection transfer validation failed')
    if not isinstance(payload['cache']['success'], dict):
        raise ValueError('Protection transfer validation failed')
    for key, value in payload['cache']['success'].items():
        if not str(asn(key)) == key:
            raise ValueError('Protection transfer validation failed')
        if not (type(value) in (int, float) and math.isfinite(value) and (value > 0)):
            raise ValueError('Protection transfer validation failed')
    if not all((str(n) in payload['cache']['success'] for n in payload['asns'])):
        raise ValueError('Protection transfer validation failed')
    if not (not payload['asns'] or payload['cache']['prefixes']):
        raise ValueError('Protection transfer validation failed')

def main(argv=None):
    os.umask(63)
    parser = argparse.ArgumentParser()
    parser.add_argument('operation', choices=('export', 'import'))
    parser.add_argument('--config', required=True)
    parser.add_argument('--file', required=True)
    args = parser.parse_args(argv)
    if not os.geteuid() == 0:
        raise ValueError('Root only')
    config = load(args.config)
    if not Path(config.database).is_file():
        raise ValueError('Initialize the target database first')
    target = Path(args.file)
    if args.operation == 'export':
        uri = Path(config.database).resolve().as_uri() + '?mode=ro'
        with closing(sqlite3.connect(uri, uri=True)) as db:
            db.execute('PRAGMA query_only=ON')
            db.execute('BEGIN')
            row = db.execute("SELECT body FROM local WHERE key='protection'").fetchone()
            cache = json.loads(row[0]) if row else {'prefixes': [], 'success': {}}
        payload = dict(schema=1, node=config.node_id, exported_at=time.time(), asns=list(config.protected_asns), explicit=list(config.protected_prefixes), cache=cache)
        validate(payload)
        envelope = dict(payload=payload, digest=digest(payload))
        with target.open('x', encoding='utf-8') as out:
            json.dump(envelope, out, ensure_ascii=False, sort_keys=True)
        target.chmod(384)
    else:
        if not (config.role == 'slave' and (not config.announcements)):
            raise ValueError('Offline slave, announcements=no required')
        if not target.stat().st_size <= 32 * 1024 * 1024:
            raise ValueError('Protection transfer validation failed')
        envelope = json.loads(target.read_text())
        if not set(envelope) == {'payload', 'digest'}:
            raise ValueError('Protection transfer validation failed')
        payload = envelope['payload']
        if not digest(payload) == envelope['digest']:
            raise ValueError('Transfer integrity check failed')
        validate(payload)
        if not payload['node'] == config.peer_node_id:
            raise ValueError('Unexpected protection source node')
        if not set(payload['asns']) <= set(config.protected_asns):
            raise ValueError('Configure source protected ASNs first')
        if not set(payload['explicit']) <= set(config.protected_prefixes):
            raise ValueError('Configure source explicit prefixes first')
        owner = Path(config.database).stat()
        if owner.st_uid:
            os.setgroups([])
            os.setgid(owner.st_gid)
            os.setuid(owner.st_uid)
        with process_lock(config.database):
            store = Store(config, activate=False)
            with store.transaction() as db:
                if not store.meta(db, 'role') == 'slave':
                    raise ValueError('Protection transfer validation failed')
                if not store.meta(db, 'node_id') == config.node_id:
                    raise ValueError('Protection transfer validation failed')
                row = db.execute("SELECT body FROM local WHERE key='protection'").fetchone()
                old = json.loads(row[0]) if row else {'prefixes': [], 'success': {}}
                state = dict(prefixes=sorted(set(old['prefixes']) | set(payload['cache']['prefixes'])), success=dict(old['success']))
                for key, value in payload['cache']['success'].items():
                    state['success'][key] = max(state['success'].get(key, 0), value)
                store.write_local(db, 'protection', state)
    print('Protection transfer complete; no rules, users, sessions, keys or tokens transferred.')
if __name__ == '__main__':
    main()
