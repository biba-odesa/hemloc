"""Transactional replicated documents with strictly local operational state."""

from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import time
import uuid

from .domain import Conflict, Duplicate, Forbidden, Invalid, NeedSnapshot, asn, prefix
from .observations import Observations, volatile

SCHEMA = 1
KINDS = {"rule", "user", "audit"}
SECRET_KEYS = {"hash", "key"}


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def digest(value):
    return hashlib.sha256(encode(value).encode()).hexdigest()


def redact(value):
    if isinstance(value, dict):
        def sensitive(key):
            normalized = re.sub('[^a-z]', '', key.lower())
            return normalized in SECRET_KEYS or any(word in normalized for word in
                ('password', 'passwd', 'secret', 'token', 'csrf', 'authorization', 'privatekey', 'cookie'))
        return {k: redact(v) for k, v in value.items() if not sensitive(k)}
    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value]
    return value


def validate_doc(kind, key, doc):
    if kind not in KINDS or not isinstance(key, str) or len(key) > 128 or not key:
        raise Invalid("Invalid replicated object identity")
    if not isinstance(doc, dict) or doc.get("id") != key:
        raise Invalid("Invalid replicated object")
    if kind == "rule":
        required = {"id", "kind", "asn", "name", "comment", "author", "created", "prefixes", "origins", "last_success", "last_error", "next_update", "pending"}
        if set(doc) != required or doc["kind"] not in ("asn", "manual"):
            raise Invalid("Invalid rule schema")
        if not isinstance(doc["prefixes"], list) or len(doc["prefixes"]) > 1000000:
            raise Invalid("Invalid rule prefix list")
        for item in doc["prefixes"]:
            if prefix(item) != item:
                raise Invalid("Noncanonical replicated prefix")
        if len(set(doc["prefixes"])) != len(doc["prefixes"]):
            raise Invalid("Duplicate rule prefixes")
        if doc["kind"] == "manual" and len(doc["prefixes"]) != 1:
            raise Invalid("Manual rule must contain exactly one prefix")
        if doc["kind"] == "asn" and asn(doc["asn"]) != doc["asn"]:
            raise Invalid("Invalid rule ASN")
        if not isinstance(doc["origins"], list):
            raise Invalid("Invalid origins")
        for origin in doc["origins"]:
            if not isinstance(origin, dict) or asn(origin["asn"]) != origin["asn"]:
                raise Invalid("Invalid origin ASN")
        for name in ("name", "comment", "author", "last_error"):
            if not isinstance(doc[name], str) or len(doc[name]) > 10000:
                raise Invalid("Invalid rule text")
        for name in ("created", "last_success", "next_update"):
            if doc[name] is not None and (type(doc[name]) not in (int, float) or doc[name] < 0):
                raise Invalid("Invalid timestamp")
        if doc["pending"] is not None:
            proposal = doc["pending"]
            if not isinstance(proposal, dict) or set(proposal) != {"prefixes", "digest", "reason", "fetched"}:
                raise Invalid("Invalid proposal")
            if not isinstance(proposal["prefixes"], list):
                raise Invalid("Invalid proposal prefix list")
            for item in proposal["prefixes"]:
                if prefix(item) != item:
                    raise Invalid("Noncanonical proposal")
            if digest(proposal["prefixes"]) != proposal["digest"]:
                raise Invalid("Invalid proposal digest")
    elif kind == "user":
        if set(doc) != {"id", "role", "enabled", "password_hash", "version"}:
            raise Invalid("Invalid user schema")
        if not re.fullmatch(r"[A-Za-z0-9_.@-]{1,64}", key) or doc["role"] not in ("admin", "guest"):
            raise Invalid("Invalid user")
        if type(doc["enabled"]) is not bool or type(doc["version"]) is not int or doc["version"] < 1:
            raise Invalid("Invalid user version")
        if not isinstance(doc["password_hash"], str) or not doc["password_hash"].startswith("$argon2id$"):
            raise Invalid("Only Argon2id hashes are permitted")
    elif kind == "audit":
        if set(doc) != {"id", "at", "node", "actor", "action", "object", "before", "after", "result"}:
            raise Invalid("Invalid audit schema")
        if redact(doc) != doc:
            raise Invalid("Secrets in audit")
        if type(doc['at']) not in (int, float) or not math.isfinite(doc['at']) or doc['at'] < 0:
            raise Invalid('Invalid audit timestamp')
        for field in ('node', 'actor', 'action', 'object', 'result'):
            if not isinstance(doc[field], str) or not 1 <= len(doc[field]) <= 256:
                raise Invalid('Invalid audit field')
    encode(doc)


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


class Store:
    def __init__(self, config, activate=True, *, observations=None):
        from .transition import RoleTransition
        RoleTransition(config).check_store(activate)
        self.config = config
        self.observations = observations if observations is not None else Observations()
        self.on_commit = None
        self.notifications = None
        path = Path(config.database)
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(fd)
        with self.connect() as db:
            db.executescript('''
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS documents(kind TEXT NOT NULL, id TEXT NOT NULL,
                    body TEXT NOT NULL CHECK(json_valid(body)), PRIMARY KEY(kind,id));
                CREATE TABLE IF NOT EXISTS journal(seq INTEGER PRIMARY KEY, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS local(key TEXT PRIMARY KEY, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY, login TEXT NOT NULL,
                    version INTEGER NOT NULL, csrf TEXT NOT NULL, expires REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS security_audit(seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    id TEXT NOT NULL UNIQUE, body TEXT NOT NULL CHECK(json_valid(body)));
                CREATE INDEX IF NOT EXISTS successful_login_shared ON documents(
                    json_extract(body,'$.actor'), json_extract(body,'$.at') DESC, id DESC)
                    WHERE kind='audit' AND json_extract(body,'$.action')='auth.login'
                    AND json_extract(body,'$.result')='success';
                CREATE INDEX IF NOT EXISTS successful_login_pending ON security_audit(
                    json_extract(body,'$.actor'), json_extract(body,'$.at') DESC, id DESC)
                    WHERE json_extract(body,'$.action')='auth.login'
                    AND json_extract(body,'$.result')='success';
            ''')
        # Nonunique lookup indexes preserve legacy duplicates. Triggers prevent new
        # duplicate identities on masters, including direct and concurrent writes.
        with self.connect() as db:
            db.executescript("""
                CREATE INDEX IF NOT EXISTS rule_identity_lookup ON documents(
                    json_extract(body,'$.kind'),
                    CASE json_extract(body,'$.kind') WHEN 'asn' THEN json_extract(body,'$.asn')
                    ELSE json_extract(body,'$.prefixes[0]') END) WHERE kind='rule';
            """)
            identity = "CASE json_extract({row}.body,'$.kind') WHEN 'asn' THEN json_extract({row}.body,'$.asn') ELSE json_extract({row}.body,'$.prefixes[0]') END"
            for event in ('INSERT', 'UPDATE'):
                changed = '' if event == 'INSERT' else (
                    " AND (OLD.kind != NEW.kind OR json_extract(OLD.body,'$.kind') != json_extract(NEW.body,'$.kind') OR (" +
                    identity.format(row='OLD') + ") IS NOT (" + identity.format(row='NEW') + "))")
                db.executescript("CREATE TRIGGER IF NOT EXISTS rule_identity_" + event.lower() +
                    " BEFORE " + event + " ON documents WHEN NEW.kind='rule'" + (" AND NOT EXISTS (SELECT 1 FROM documents current WHERE current.kind=NEW.kind AND current.id=NEW.id AND json_extract(current.body,'$.kind')=json_extract(NEW.body,'$.kind') AND (" + identity.format(row='current') + ")=(" + identity.format(row='NEW') + "))" if event == 'INSERT' else '') + changed +
                    " AND (SELECT value FROM meta WHERE key='role')='master' AND EXISTS (SELECT 1 FROM documents d WHERE d.kind='rule' AND d.id != NEW.id AND json_extract(d.body,'$.kind')=json_extract(NEW.body,'$.kind') AND (" +
                    identity.format(row='d') + ")=(" + identity.format(row='NEW') +
                    ")) BEGIN SELECT RAISE(ABORT,'duplicate_rule'); END;")
        from .history import setup
        with self.connect() as db:
            setup(db)
        if activate:
            with self.transaction() as db:
                previous = self.meta(db, "role")
                node = self.meta(db, "node_id")
                if node and node != config.node_id:
                    raise Conflict("Database belongs to a different node")
                self.set_meta(db, "node_id", config.node_id)
                if not self.meta(db, 'security_history'):
                    self.set_meta(db, 'security_history', str(uuid.uuid4()))
                if config.role == "master" and previous != "master":
                    old_history = self.meta(db, 'history')
                    if old_history or db.execute('SELECT 1 FROM journal LIMIT 1').fetchone():
                        # Keep every previous journal row, including an empty journal.
                        # A new generation gets its own active sequence namespace.
                        archive = 'journal_history_' + uuid.uuid4().hex
                        db.execute('CREATE TABLE IF NOT EXISTS journal_generations(history TEXT NOT NULL, table_name TEXT PRIMARY KEY)')
                        db.execute('ALTER TABLE journal RENAME TO ' + archive)
                        db.execute('INSERT INTO journal_generations VALUES(?,?)', (old_history, archive))
                        db.execute('CREATE TABLE journal(seq INTEGER PRIMARY KEY, body TEXT NOT NULL)')
                    self.set_meta(db, "history", str(uuid.uuid4()))
                    self.set_meta(db, "sequence", "0")
                    self.set_meta(db, "master_id", config.node_id)
                self.set_meta(db, "role", config.role)
                if config.role == 'master':
                    self.publish_security(db)

    def connect(self):
        db = sqlite3.connect(self.config.database, timeout=15, isolation_level=None, factory=ClosingConnection)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=15000")
        db.execute("PRAGMA synchronous=FULL")
        return db

    @contextmanager
    def transaction(self):
        from .transition import RoleTransition
        transition = RoleTransition(self.config)
        transition.assert_write_allowed()
        db = self.connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            transition.assert_write_allowed()
            db.audit_events = []
            yield db
            db.commit()
            if self.on_commit and db.audit_events:
                try:
                    self.on_commit(db.audit_events)
                except Exception:
                    import logging
                    logging.getLogger("uvicorn.error.notifications").error("Notification enqueue failed")
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def meta(db, key, default=""):
        row = db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row[0] if row else default

    @staticmethod
    def set_meta(db, key, value):
        db.execute("INSERT INTO meta VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value WHERE meta.value IS NOT excluded.value", (key, str(value)))

    def require_master(self, db):
        if self.config.role != "master" or self.meta(db, "role") != "master":
            raise Forbidden("This node is read-only")

    def info(self):
        with self.connect() as db:
            return {"node_id": self.config.node_id, "role": self.config.role,
                    "history": self.meta(db, "history"), "sequence": int(self.meta(db, "sequence", "0")),
                    "master_id": self.meta(db, "master_id")}

    @staticmethod
    def read(db, kind, key):
        row = db.execute("SELECT body FROM documents WHERE kind=? AND id=?", (kind, key)).fetchone()
        return json.loads(row[0]) if row else None

    def get(self, kind, key):
        with self.connect() as db:
            return self.read(db, kind, key)

    def list(self, kind):
        with self.connect() as db:
            return [json.loads(r[0]) for r in db.execute("SELECT body FROM documents WHERE kind=? ORDER BY id", (kind,))]

    def local(self, key, default=None):
        if volatile(key):
            return self.observations.get(key, default)
        with self.connect() as db:
            row = db.execute("SELECT body FROM local WHERE key=?", (key,)).fetchone()
            return json.loads(row[0]) if row else default

    @staticmethod
    def write_local(db, key, value):
        if volatile(key):
            raise Invalid('Observations cannot be persisted')
        db.execute("INSERT INTO local VALUES(?,?) ON CONFLICT(key) DO UPDATE SET body=excluded.body WHERE local.body IS NOT excluded.body", (key, encode(value)))

    def set_local(self, key, value):
        if volatile(key):
            self.observations.set(key, value)
            return
        with self.transaction() as db:
            self.write_local(db, key, value)

    def append_journal(self, db, operations):
        sequence = int(self.meta(db, 'sequence', '0')) + 1
        db.execute('INSERT INTO journal VALUES(?,?)', (sequence, encode(operations)))
        self.set_meta(db, 'sequence', sequence)

    def security_record(self, db, actor, action, object_name, result, context=None):
        """Commit with login state on master; slave events are a local outbox only."""
        from .audit import ACTIONS, OBJECTS, RESULTS, identity, validate_security_context
        if action not in ACTIONS or object_name not in OBJECTS or result not in RESULTS:
            raise Invalid('Invalid security audit category')
        validate_security_context(action, object_name, result, None, context)
        doc = {'id': str(uuid.uuid4()), 'at': time.time(), 'node': self.config.node_id,
               'actor': identity(actor), 'action': action, 'object': object_name,
               'before': None, 'after': context, 'result': result}
        validate_doc('audit', doc['id'], doc)
        if self.config.role == 'master' and self.meta(db, 'role') == 'master':
            operation = {'kind': 'audit', 'id': doc['id'], 'doc': doc}
            self.operation(db, operation)
            self.append_journal(db, [operation])
        else:
            db.execute('INSERT INTO security_audit(id,body) VALUES(?,?)', (doc['id'], encode(doc)))
        db.audit_events.append(doc)
        return doc

    def security_event(self, actor, action, object_name, result, context=None):
        with self.transaction() as db:
            return self.security_record(db, actor, action, object_name, result, context)

    def local_security_events(self, after=0, limit=100, history=''):
        if type(after) is not int or after < 0:
            raise Invalid('Invalid local audit cursor')
        with self.connect() as db:
            db.execute('BEGIN')
            generation = self.meta(db, 'security_history')
            maximum = db.execute('SELECT COALESCE(MAX(seq),0) FROM security_audit').fetchone()[0]
            if history != generation or after > maximum:
                after = 0
            rows = db.execute('SELECT seq,body FROM security_audit WHERE seq>? ORDER BY seq LIMIT ?',
                              (after, max(1, min(1000, limit)))).fetchall()
            return {'node_id': self.config.node_id, 'history': generation,
                    'events': [{'seq': r[0], 'doc': json.loads(r[1])} for r in rows]}

    def publish_security(self, db):
        """Promotion publishes pending local authentication events, not divergent rules."""
        operations = []
        for row in db.execute('SELECT id,body FROM security_audit ORDER BY seq'):
            if self.read(db, 'audit', row[0]) is None and not db.execute('SELECT 1 FROM audit_tombstones WHERE id=?', (row[0],)).fetchone():
                operation = {'kind': 'audit', 'id': row[0], 'doc': json.loads(row[1])}
                self.operation(db, operation)
                operations.append(operation)
        if operations:
            self.append_journal(db, operations)

    def ingest_security(self, batch):
        """A master imports only constrained peer security facts, never peer state."""
        from .audit import ACTIONS, OBJECTS, RESULTS, identity, validate_security_context
        if not isinstance(batch, dict) or set(batch) != {'node_id', 'history', 'events'} or batch['node_id'] != self.config.peer_node_id:
            raise Invalid('Invalid peer audit envelope')
        try:
            uuid.UUID(batch['history'])
        except (ValueError, TypeError, AttributeError):
            raise Invalid('Invalid peer audit generation') from None
        if not isinstance(batch['events'], list) or len(batch['events']) > 1000:
            raise Invalid('Invalid peer audit batch')
        with self.transaction() as db:
            self.require_master(db)
            cursor = (int(self.meta(db, 'peer_security_cursor', '0'))
                      if self.meta(db, 'peer_security_history') == batch['history'] else 0)
            previous, operations = 0, []
            for event in batch['events']:
                if not isinstance(event, dict) or set(event) != {'seq', 'doc'} or type(event['seq']) is not int or event['seq'] <= previous:
                    raise Invalid('Invalid peer audit ordering')
                previous = event['seq']
                if event['seq'] <= cursor:
                    continue
                if event['seq'] != cursor + 1:
                    raise Invalid('Peer audit gap')
                doc = event['doc']
                if not isinstance(doc, dict):
                    raise Invalid('Invalid peer audit record')
                validate_doc('audit', doc.get('id'), doc)
                if (doc['node'] != self.config.peer_node_id or doc['action'] not in ACTIONS or
                    doc['object'] not in OBJECTS or doc['result'] not in RESULTS or
                    doc['actor'] != identity(doc['actor'])):
                    raise Invalid('Peer may submit only constrained security events')
                validate_security_context(doc['action'], doc['object'], doc['result'], doc['before'], doc['after'])
                receipt = db.execute('SELECT digest FROM audit_tombstones WHERE id=?', (doc['id'],)).fetchone()
                if receipt and receipt[0] != digest(doc):
                    raise Conflict('Pruned peer audit identity mismatch')
                if self.read(db, 'audit', doc['id']) is None and not db.execute('SELECT 1 FROM audit_tombstones WHERE id=?', (doc['id'],)).fetchone():
                    operation = {'kind': 'audit', 'id': doc['id'], 'doc': doc}
                    self.operation(db, operation)
                    operations.append(operation)
                cursor = event['seq']
            if operations:
                self.append_journal(db, operations)
            self.set_meta(db, 'peer_security_cursor', cursor)
            self.set_meta(db, 'peer_security_history', batch['history'])
        return cursor

    def audit_history(self):
        """Deduplicate local pending security facts against the shared audit."""
        with self.connect() as db:
            db.execute('BEGIN')
            docs = {r[0]: json.loads(r[1]) for r in db.execute("SELECT id,body FROM documents WHERE kind='audit'")}
            for row in db.execute('SELECT id,body FROM security_audit'):
                docs.setdefault(row[0], json.loads(row[1]))
            for row in db.execute('SELECT id FROM audit_tombstones'):
                docs.pop(row[0], None)
            return list(docs.values())

    def successful_logins(self, login):
        """Bounded union of shared audit and this node's unacknowledged events."""
        with self.connect() as db:
            db.execute('BEGIN')
            rows = db.execute("""
                WITH shared AS (
                    SELECT id,body FROM documents WHERE kind='audit'
                    AND json_extract(body,'$.action')='auth.login'
                    AND json_extract(body,'$.result')='success'
                    AND json_extract(body,'$.actor')=?
                    AND NOT EXISTS(SELECT 1 FROM audit_tombstones t WHERE t.id=documents.id)
                    ORDER BY json_extract(body,'$.at') DESC,id DESC LIMIT 5),
                pending AS (
                    SELECT id,body FROM security_audit
                    WHERE json_extract(body,'$.action')='auth.login'
                    AND json_extract(body,'$.result')='success'
                    AND json_extract(body,'$.actor')=?
                    AND NOT EXISTS(SELECT 1 FROM audit_tombstones t WHERE t.id=security_audit.id)
                    AND NOT EXISTS (SELECT 1 FROM documents WHERE kind='audit' AND id=security_audit.id)
                    ORDER BY json_extract(body,'$.at') DESC,id DESC LIMIT 5)
                SELECT body FROM (SELECT id,body FROM shared UNION ALL SELECT id,body FROM pending)
                ORDER BY json_extract(body,'$.at') DESC,id DESC LIMIT 5
            """, (login, login)).fetchall()
        from .audit import login_context
        events = [json.loads(row[0]) for row in rows]
        return [{'at':e['at'], 'node':e['node'],
                 'ip':(e['after']['client_ip'] if isinstance(e['after'], dict) and
                       set(e['after'])=={'client_ip'} and isinstance(e['after']['client_ip'], str) and
                       login_context(e['after']['client_ip'])==e['after'] else None)} for e in events]

    @staticmethod
    def operation(db, operation):
        if not isinstance(operation, dict) or set(operation) != {"kind", "id", "doc"}:
            raise Invalid("Invalid journal operation")
        kind, key, doc = operation["kind"], operation["id"], operation["doc"]
        if kind == "audit_prune":
            from .retention import apply_operation
            return apply_operation(db, operation)
        if kind not in KINDS or not isinstance(key, str):
            raise Invalid("Unknown journal entity")
        if doc is None:
            if kind == "audit":
                raise Invalid("Audit deletion prohibited")
            db.execute("DELETE FROM documents WHERE kind=? AND id=?", (kind, key))
        else:
            validate_doc(kind, key, doc)
            if kind == "audit":
                receipt = db.execute("SELECT digest FROM audit_tombstones WHERE id=?", (key,)).fetchone()
                if receipt:
                    if receipt[0] != digest(doc):
                        raise Conflict("Pruned audit identity mismatch")
                    return
            if kind == "audit" and Store.read(db, kind, key) is not None:
                raise Invalid("Audit replacement prohibited")
            try:
                db.execute("INSERT INTO documents VALUES(?,?,?) ON CONFLICT(kind,id) DO UPDATE SET body=excluded.body", (kind, key, encode(doc)))
            except sqlite3.IntegrityError as exc:
                if str(exc) != 'duplicate_rule':
                    raise
                match = db.execute("SELECT id FROM documents WHERE kind='rule' AND id!=? AND json_extract(body,'$.kind')=? AND CASE json_extract(body,'$.kind') WHEN 'asn' THEN json_extract(body,'$.asn') ELSE json_extract(body,'$.prefixes[0]') END=? ORDER BY id LIMIT 1",
                                   (key, doc['kind'], doc['asn'] if doc['kind']=='asn' else doc['prefixes'][0])).fetchone()
                raise Duplicate(match[0]) from None

    def change(self, actor, action, kind, key, transform):
        """Run authorization, transformation, journal and audit in one transaction."""
        return self.change_many(actor, action, [(kind, key, transform)])[0]

    def change_many(self, actor, action, changes, *, batch_id=None, notify=True):
        if not changes or len(changes) > 1000:
            raise Invalid("Expected 1..1000 changes")
        with self.transaction() as db:
            self.require_master(db)
            operations, results = [], []
            for kind, key, transform in changes:
                before = self.read(db, kind, key)
                after = transform(deepcopy(before))
                if kind == "audit":
                    raise Forbidden("Audit is immutable")
                operation = {"kind": kind, "id": key, "doc": after}
                self.operation(db, operation)
                audit = {"id": str(uuid.uuid4()), "at": time.time(), "node": self.config.node_id,
                         "actor": actor.login, "action": action, "object": f"{kind}:{key}",
                         "before": redact(before), "after": redact(after),
                         "result": 'failed' if action == 'asn.refresh' and after and after.get('last_error') else 'saved'}
                if batch_id:
                    audit["after"] = dict(audit["after"] or {}) | {"batch_id":batch_id}
                audit_op = {"kind": "audit", "id": audit["id"], "doc": audit}
                self.operation(db, audit_op)
                if notify:
                    db.audit_events.append(audit)
                operations.extend([operation, audit_op])
                results.append(after)
            sequence = int(self.meta(db, "sequence", "0")) + 1
            db.execute("INSERT INTO journal VALUES(?,?)", (sequence, encode(operations)))
            self.set_meta(db, "sequence", sequence)
        return results

    def snapshot(self):
        db = self.connect()
        try:
            db.execute("BEGIN")
            payload = {"schema": SCHEMA, "history": self.meta(db, "history"),
                       "sequence": int(self.meta(db, "sequence", "0")),
                       "master_id": self.meta(db, "master_id"),
                       "documents": [{"kind": r[0], "id": r[1], "doc": json.loads(r[2])}
                                     for r in db.execute("SELECT kind,id,body FROM documents ORDER BY kind,id")]}
            tombstones = [dict(r) for r in db.execute("SELECT id,digest FROM audit_tombstones ORDER BY id")]
            if tombstones:
                payload["schema"] = 2
                payload["tombstones"] = tombstones
            return {"payload": payload, "digest": digest(payload)}
        finally:
            db.rollback()
            db.close()

    def backup(self, destination):
        destination = Path(destination)
        if destination.exists():
            raise Invalid("Backup destination exists")
        fd = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
        with self.connect() as source, sqlite3.connect(destination, factory=ClosingConnection) as target:
            source.backup(target)
        return str(destination)

    def install_snapshot(self, snapshot):
        if self.config.role != "slave":
            raise Conflict("Master cannot accept a peer snapshot")
        if not isinstance(snapshot, dict) or set(snapshot) != {"payload", "digest"}:
            raise Invalid("Invalid snapshot envelope")
        payload = snapshot["payload"]
        if digest(payload) != snapshot["digest"]:
            raise Invalid("Snapshot digest mismatch")
        expected = {"schema", "history", "sequence", "master_id", "documents"}
        if payload.get("schema") == 2:
            expected.add("tombstones")
        if set(payload) != expected:
            raise Invalid("Invalid snapshot schema")
        self.validate_header(payload)
        if payload["schema"] not in (SCHEMA, 2) or not isinstance(payload["documents"], list):
            raise Invalid("Unsupported snapshot schema")
        from .retention import validate_entries
        validate_entries(payload.get("tombstones", []), bounded=False)
        receipt_ids = {item["id"] for item in payload.get("tombstones", [])}
        identities = set()
        for operation in payload["documents"]:
            if not isinstance(operation, dict) or set(operation) != {"kind", "id", "doc"}:
                raise Invalid("Invalid snapshot object")
            validate_doc(operation["kind"], operation["id"], operation["doc"])
            if operation["kind"] == "audit" and operation["id"] in receipt_ids:
                raise Invalid("Snapshot contains pruned audit")
            identity = operation["kind"], operation["id"]
            if identity in identities:
                raise Invalid("Duplicate snapshot object")
            identities.add(identity)
        backup_path = self.config.database + f".backup-{time.time_ns()}"
        self.backup(backup_path)
        with self.transaction() as db:
            if self.meta(db, "role") != "slave":
                raise Conflict("Role changed during snapshot")
            from .retention import apply_operation
            receipts = payload.get("tombstones", [])
            for offset in range(0, len(receipts), 500):
                apply_operation(db, {"kind":"audit_prune", "id":"retention", "doc":{"entries":receipts[offset:offset+500]}})
            db.execute("DELETE FROM documents")
            db.execute("DELETE FROM journal")
            db.execute("DELETE FROM sessions")
            for operation in payload["documents"]:
                self.operation(db, operation)
            for key in ("history", "sequence", "master_id"):
                self.set_meta(db, key, payload[key])
            self.write_local(db, "last_snapshot", {"at": time.time(), "backup": backup_path})
        return backup_path

    def validate_header(self, payload):
        try:
            uuid.UUID(payload["history"])
        except (ValueError, KeyError, TypeError) as exc:
            raise Invalid("Invalid history identity") from exc
        if type(payload.get("sequence")) is not int or payload["sequence"] < 0:
            raise Invalid("Invalid sequence")
        if payload.get("master_id") != self.config.peer_node_id:
            raise Conflict("Unexpected master identity")

    def events(self, history, cursor, limit=100):
        with self.connect() as db:
            db.execute("BEGIN")
            self.require_master(db)
            current = int(self.meta(db, "sequence", "0"))
            if history != self.meta(db, "history") or cursor < 0 or cursor > current:
                raise NeedSnapshot("History changed or invalid cursor")
            rows = db.execute("SELECT seq,body FROM journal WHERE seq>? ORDER BY seq LIMIT ?", (cursor, max(1, min(limit, 1000)))).fetchall()
            if cursor < current and (not rows or rows[0][0] != cursor + 1):
                raise NeedSnapshot("Journal cursor has expired")
            return {"history": history, "master_id": self.config.node_id, "sequence": current,
                    "events": [{"seq": r[0], "operations": json.loads(r[1])} for r in rows]}

    def apply_events(self, batch):
        if self.config.role != "slave":
            raise Conflict("Master cannot apply peer journal")
        self.validate_header(batch)
        if set(batch) != {"history", "master_id", "sequence", "events"} or not isinstance(batch["events"], list):
            raise Invalid("Invalid event envelope")
        with self.transaction() as db:
            if self.meta(db, "role") != "slave":
                raise Conflict("Role changed during journal apply")
            if self.meta(db, "history") != batch["history"]:
                raise NeedSnapshot("History changed")
            cursor = int(self.meta(db, "sequence", "0"))
            previous = 0
            for event in batch["events"]:
                if set(event) != {"seq", "operations"} or type(event["seq"]) is not int or not isinstance(event["operations"], list):
                    raise Invalid("Invalid event")
                seq = event["seq"]
                if seq <= previous or seq > batch["sequence"]:
                    raise Invalid("Unordered journal batch")
                previous = seq
                if seq <= cursor:
                    continue
                if seq != cursor + 1:
                    raise NeedSnapshot("Journal gap")
                for operation in event["operations"]:
                    self.operation(db, operation)
                cursor = seq
            if cursor > batch["sequence"]:
                raise NeedSnapshot("Master cursor moved backwards")
            self.set_meta(db, "sequence", cursor)
        return cursor
