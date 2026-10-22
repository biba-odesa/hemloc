"""Exact, replicated audit maintenance. Transport payloads are deliberately retained."""
from datetime import datetime, timedelta
import json
import math
import os
import re
import time
import uuid
from zoneinfo import ZoneInfo

from .domain import Conflict, Invalid
from .protocol import confirmed
from .history import CATEGORY, CATEGORIES, VISIBLE
from .store import Store, digest, encode, redact

CAPABILITY = 'audit-prune-v2'


def validate_entries(entries, bounded=True):
    if not isinstance(entries, list) or (bounded and not 1 <= len(entries) <= 500):
        raise Invalid('Invalid audit maintenance entries')
    seen = set()
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {'id', 'digest'}:
            raise Invalid('Invalid audit maintenance entry')
        try:
            uuid.UUID(entry['id'])
        except (ValueError, TypeError, AttributeError):
            raise Invalid('Invalid audit maintenance identity') from None
        if entry['id'] in seen or not isinstance(entry['digest'], str) or not re.fullmatch('[0-9a-f]{64}', entry['digest']):
            raise Invalid('Invalid audit maintenance digest')
        seen.add(entry['id'])


def apply_operation(db, operation):
    """Only this typed operation may remove audit; generic document deletes stay forbidden."""
    if operation['id'] != 'retention' or not isinstance(operation['doc'], dict) or set(operation['doc']) != {'entries'}:
        raise Invalid('Invalid audit maintenance operation')
    entries = operation['doc']['entries']
    validate_entries(entries)
    for entry in entries:
        existing = Store.read(db, 'audit', entry['id'])
        if existing is not None and digest(existing) != entry['digest']:
            raise Conflict('Audit maintenance digest mismatch')
        pending = db.execute('SELECT body FROM security_audit WHERE id=?', (entry['id'],)).fetchone()
        if pending and digest(json.loads(pending[0])) != entry['digest']:
            raise Conflict('Pending audit maintenance digest mismatch')
        old = db.execute('SELECT digest FROM audit_tombstones WHERE id=?', (entry['id'],)).fetchone()
        if old and old[0] != entry['digest']:
            raise Conflict('Audit maintenance receipt mismatch')
        db.execute('INSERT OR IGNORE INTO audit_tombstones VALUES(?,?)', (entry['id'], entry['digest']))
        db.execute("DELETE FROM documents WHERE kind='audit' AND id=?", (entry['id'],))
    # Keep security_audit transport rows and their sequence numbers. They are hidden
    # by receipts, not locally TTL-deleted, so pending facts and cursors cannot vanish.


def policy(config):
    return {key: getattr(config, key + '_days') for key in CATEGORIES}


def protected_logins(db):
    return {row[0] for row in db.execute('''
        SELECT id FROM (SELECT id,ROW_NUMBER() OVER(
            PARTITION BY json_extract(body,'$.actor')
            ORDER BY json_extract(body,'$.at') DESC,id DESC) AS n
        FROM ''' + VISIBLE + " AND json_extract(body,'$.action')='auth.login' AND json_extract(body,'$.result')='success') WHERE n<=5")}


def preview(store, now=None):
    now = time.time() if now is None else now
    cutoffs = {key: now - days * 86400 for key, days in policy(store.config).items()}
    with store.connect() as db:
        db.execute('BEGIN')
        kept = protected_logins(db)
        entries, counts = [], dict.fromkeys(CATEGORIES, 0)
        clauses = ' OR '.join(f'(({CATEGORY})=? AND json_extract(body,\'$.at\')<?)' for _ in CATEGORIES)
        params = [v for key in CATEGORIES for v in (key, cutoffs[key])]
        for row in db.execute('SELECT id,body,(' + CATEGORY + ') category FROM ' + VISIBLE + ' AND (' + clauses + ') ORDER BY id', params):
            if row['id'] in kept:
                continue
            entries.append({'id':row['id'], 'digest':digest(json.loads(row['body']))})
            counts[row['category']] += 1
        payload = {'version':2, 'history':store.meta(db, 'history'), 'created':now, 'cutoffs':cutoffs,
                   'policy':policy(store.config), 'entries':entries, 'counts':counts}
    return {'payload':payload, 'digest':digest(payload)}


def peer_ready(store, db, now):
    if not store.config.peer_url:
        return
    peer = store.local('peer', {})
    status = peer.get('status', {})
    ack = store.local('peer_ack', {})
    if (not confirmed(store,now) or CAPABILITY not in status.get('capabilities', []) or status.get('role') != 'slave'
            or now - peer.get('at', 0) > 60 or ack.get('history') != store.meta(db, 'history')
            or ack.get('sequence') != int(store.meta(db, 'sequence', '0'))
            or status.get('security_history') != store.meta(db, 'peer_security_history')
            or status.get('security_sequence') != int(store.meta(db, 'peer_security_cursor', '0'))):
        raise Conflict('Cleanup requires a current compatible, fully caught-up peer and drained security outbox')


def validate_plan(store, plan, now=None):
    """Validate a saved manifest without changing data."""
    now = time.time() if now is None else now
    if not isinstance(plan, dict) or set(plan) != {'payload', 'digest'} or digest(plan['payload']) != plan['digest']:
        raise Invalid('Invalid retention plan digest')
    payload = plan['payload']
    if set(payload) != {'version', 'history', 'created', 'cutoffs', 'policy', 'entries', 'counts'} or payload['version'] != 2:
        raise Invalid('Invalid retention plan')
    validate_entries(payload['entries'], bounded=False)
    if payload['policy'] != policy(store.config) or not isinstance(payload['created'], (int, float)) or not math.isfinite(payload['created']) or payload['created'] > now:
        raise Conflict('Retention policy or plan time changed')
    expected = {k:payload['created'] - v * 86400 for k, v in policy(store.config).items()}
    if payload['cutoffs'] != expected:
        raise Invalid('Invalid retention cutoffs')
    return payload, expected


def execute(store, plan, now=None):
    """Apply only preselected IDs; batches and progress are crash-resumable and atomic."""
    live_clock=now is None
    now = time.time() if now is None else now
    payload, expected = validate_plan(store, plan, now)
    with store.connect() as db:
        store.require_master(db)
    # A separate advisory lock serializes CLI and background cleanup, not web/BGP.
    from .workers import process_lock
    with process_lock(store.config.database + '.retention'):
        removed = 0
        for offset in range(0, len(payload['entries']), store.config.retention_batch_size):
            batch = payload['entries'][offset:offset + store.config.retention_batch_size]
            with store.transaction() as db:
                store.require_master(db)
                if store.meta(db, 'history') != payload['history']:
                    raise Conflict('Retention plan belongs to a different history')
                # Compatibility remains mandatory for every batch. The peer may lag
                # this cleanup's own operations, but needs a fresh compatible handshake.
                if offset == 0:
                    peer_ready(store, db, time.time() if live_clock else now)
                elif store.config.peer_url:
                    observed = store.local('peer', {})
                    peer = observed.get('status', {})
                    if (not confirmed(store,time.time() if live_clock else now) or CAPABILITY not in peer.get('capabilities', []) or peer.get('role') != 'slave'
                            or now - observed.get('at', 0) > 60):
                        raise Conflict('Peer compatibility changed')
                kept = protected_logins(db)
                fresh = []
                for item in batch:
                    doc = store.read(db, 'audit', item['id'])
                    if doc is None and db.execute('SELECT 1 FROM audit_tombstones WHERE id=?', (item['id'],)).fetchone():
                        continue
                    if doc is None or digest(doc) != item['digest'] or item['id'] in kept:
                        raise Conflict('Retention plan is stale; preview again')
                    category = db.execute('SELECT (' + CATEGORY + ") FROM documents WHERE kind='audit' AND id=?", (item['id'],)).fetchone()[0]
                    if category not in expected or doc['at'] >= expected[category]:
                        raise Conflict('Retention entry is not eligible')
                    fresh.append(item)
                if not fresh:
                    continue
                batch = fresh
                op = {'kind':'audit_prune', 'id':'retention', 'doc':{'entries':batch}}
                apply_operation(db, op)
                audit = {'id':str(uuid.uuid4()), 'at':now, 'node':store.config.node_id, 'actor':'system:retention',
                         'action':'audit.prune', 'object':'maintenance', 'before':None,
                         'after':{'count':len(batch), 'plan_digest':plan['digest']}, 'result':'saved'}
                audit_op = {'kind':'audit', 'id':audit['id'], 'doc':audit}
                store.operation(db, audit_op)
                store.append_journal(db, [op, audit_op])
                removed += len(batch)
                store.write_local(db, 'retention_progress', {'digest':plan['digest'], 'completed':offset + len(batch), 'at':now})
        return removed


def write_private(path, value):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as stream:
        stream.write(encode(value) + '\n')


def export(store, destination=None):
    count = 0
    stream = None
    if destination:
        fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        stream = os.fdopen(fd, 'w', encoding='utf-8')
    try:
        with store.connect() as db:
            db.execute('BEGIN')
            for row in db.execute('SELECT body FROM ' + VISIBLE + " ORDER BY json_extract(body,'$.at'),id"):
                doc = json.loads(row[0])
                if redact(doc) != doc:
                    raise Invalid('Unsafe audit export rejected')
                # Unknown opaque context is not an export channel for raw requests.
                allowed = {'id','kind','asn','name','comment','author','created','prefixes','origins','last_success','last_error','next_update','pending','role','enabled','version','client_ip','window_seconds','request_type','reason','exit_code','count','plan_digest'}
                for side in ('before', 'after'):
                    context = doc.get(side)
                    doc[side] = {k:v for k,v in context.items() if k in allowed} if isinstance(context, dict) else None
                if stream:
                    stream.write(encode(doc) + '\n')
                count += 1
    finally:
        if stream:
            stream.close()
    return {'events':count, 'written':bool(destination)}


def due_day(config, now):
    """Choose the most recent local daily slot. One execution even across DST folds."""
    zone = ZoneInfo(config.retention_timezone)
    local = datetime.fromtimestamp(now, zone)
    hour, minute = map(int, config.cleanup_time.split(':'))
    slot = local.replace(hour=hour, minute=minute, second=0, microsecond=0, fold=0)
    if slot.timestamp() > now:
        slot -= timedelta(days=1)
    return slot.date().isoformat()


class RetentionWorker:
    def __init__(self, store, clock=time.time):
        self.store, self.clock = store, clock

    def step(self):
        cfg, now = self.store.config, self.clock()
        if not cfg.retention_enabled or cfg.role != 'master':
            return
        day = due_day(cfg, now)
        state = self.store.local('retention_schedule', {})
        if state.get('completed_day', '') >= day or state.get('retry_at', 0) > now:
            return
        # Persist exact plan before the first deletion, so a crash never broadens it.
        saved = state.get('plan')
        if saved and (saved['payload']['history'] != self.store.info()['history'] or saved['payload']['policy'] != policy(cfg)):
            saved = None
        plan = saved or preview(self.store, now)
        job_day = state.get('day', day) if saved else day
        self.store.set_local('retention_schedule', {'completed_day':state.get('completed_day', ''), 'plan':plan, 'day':job_day, 'retry_at':now + 60})
        execute(self.store, plan, now)
        self.store.set_local('retention_schedule', {'completed_day':job_day, 'at':now})
