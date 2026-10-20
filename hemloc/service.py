"""Shared authorization and mutation service for web, workers and CLI."""

import time
import uuid
import json

from .domain import Actor, Conflict, Duplicate, Forbidden, Invalid, Protection, asn, desired, lookup, prefix
from .store import digest
from .audit import audit_failures

SYSTEM = Actor("system:irr", "admin")


class Service:
    def __init__(self, store):
        self.store = store
        self.config = store.config

    def writable(self, actor):
        actor.require_admin()
        with self.store.connect() as db:
            self.store.require_master(db)

    def protection(self, db=None):
        if db is None:
            state = self.store.local("protection", {"prefixes": [], "success": {}})
        else:
            row = db.execute("SELECT body FROM local WHERE key='protection'").fetchone()
            state = json.loads(row[0]) if row else {"prefixes": [], "success": {}}
        return Protection(set(self.config.protected_prefixes) | set(state["prefixes"]), self.config.protected_asns)

    def protection_ready(self):
        state = self.store.local("protection", {"prefixes": [], "success": {}})
        return all(str(a) in state["success"] for a in self.config.protected_asns)

    def grow_protection(self, number, prefixes):
        number = asn(number)
        if number not in self.config.protected_asns:
            raise Invalid("ASN not configured for local protection")
        accepted = {prefix(p) for p in prefixes}
        if not accepted:
            raise Invalid("Empty protected expansion cannot initialize protection")
        with self.store.transaction() as db:
            row = db.execute("SELECT body FROM local WHERE key='protection'").fetchone()
            import json
            state = json.loads(row[0]) if row else {"prefixes": [], "success": {}}
            state["prefixes"] = sorted(set(state["prefixes"]) | accepted)
            state["success"][str(number)] = time.time()
            self.store.write_local(db, "protection", state)

    def routes(self):
        routes, exclusions, _ = self.route_snapshot()
        return routes, exclusions

    def route_snapshot(self):
        """Read rules, protection and revision from the same SQLite snapshot."""
        with self.store.connect() as db:
            db.execute('BEGIN')
            rules = [json.loads(r[0]) for r in db.execute("SELECT body FROM documents WHERE kind='rule' ORDER BY id")]
            protection = self.protection(db)
            info = {'history': self.store.meta(db, 'history'),
                    'sequence': int(self.store.meta(db, 'sequence', '0'))}
            routes, excluded = desired(rules, protection)
            return routes, excluded, info

    def search(self, address):
        return lookup(address, self.store.list("rule"))

    @audit_failures('rule.create', 'rule')
    def add_manual(self, actor, value, comment="", origins=()):
        self.writable(actor)
        candidate = prefix(value)
        self.protection().check(candidate)
        now = time.time()
        doc = {"id": str(uuid.uuid4()), "kind": "manual", "asn": None, "name": "",
               "comment": comment, "author": actor.login, "created": now,
               "prefixes": [candidate], "origins": list(origins), "last_success": None,
               "last_error": "", "next_update": None, "pending": None}
        return self.store.change(actor, "rule.create", "rule", doc["id"], lambda old: doc)

    @audit_failures('rule.import', 'rule')
    def import_manual(self, actor, items):
        self.writable(actor)
        if not isinstance(items, list) or not 1 <= len(items) <= 1000:
            raise Invalid("Import requires 1..1000 manual rules")
        changes = []
        for item in items:
            if set(item) != {'value', 'comment'}:
                raise Invalid("Invalid import item")
            candidate = prefix(item['value'])
            self.protection().check(candidate)
            doc = {"id": str(uuid.uuid4()), "kind": "manual", "asn": None, "name": "",
                   "comment": item['comment'], "author": actor.login, "created": time.time(),
                   "prefixes": [candidate], "origins": [], "last_success": None,
                   "last_error": "", "next_update": None, "pending": None}
            changes.append(('rule', doc['id'], lambda old, doc=doc: doc))
        try:
            return self.store.change_many(actor, 'rule.import', changes)
        except Duplicate as exc:
            if exc.rule_id in {key for _, key, _ in changes}:
                raise Conflict('Import contains duplicate rules; no records were saved.') from None
            raise

    @audit_failures('rule.create', 'rule')
    def add_asn(self, actor, number, comment=""):
        self.writable(actor)
        number = asn(number)
        if number in self.config.protected_asns:
            raise Forbidden("Protected ASN cannot be blocked")
        now = time.time()
        doc = {"id": str(uuid.uuid4()), "kind": "asn", "asn": number, "name": "",
               "comment": comment, "author": actor.login, "created": now, "prefixes": [],
               "origins": [], "last_success": None, "last_error": "Awaiting initial IRR fetch",
               "next_update": now, "pending": None}
        def create(old):
            return doc
        return self.store.change(actor, "rule.create", "rule", doc["id"], create)

    @audit_failures('rule.comment', 'rule')
    def update_comment(self, actor, rule_id, comment):
        self.writable(actor)
        def update(old):
            if old is None:
                raise Invalid("Rule not found")
            old["comment"] = comment
            return old
        return self.store.change(actor, "rule.comment", "rule", rule_id, update)

    @audit_failures('rule.delete', 'rule')
    def delete_rule(self, actor, rule_id):
        self.writable(actor)
        def remove(old):
            if old is None:
                raise Invalid("Rule not found")
            return None
        return self.store.change(actor, "rule.delete", "rule", rule_id, remove)

    @audit_failures('asn.refresh', 'rule')
    def update_asn(self, actor, rule_id, prefixes=None, name="", failed=False, expected=None):
        self.writable(actor)
        candidates = sorted({prefix(p) for p in prefixes}) if prefixes is not None else None
        def update(old):
            if old is None or old["kind"] != "asn":
                raise Invalid("ASN rule not found")
            if expected is not None and digest(old) != expected:
                raise Conflict("ASN rule changed during fetch")
            if old["asn"] in self.config.protected_asns:
                raise Forbidden("Protected ASN cannot be refreshed as a blocking rule")
            now = time.time()
            if failed or candidates is None:
                old["last_error"] = "IRR lookup failed; previous set retained"
                old["next_update"] = now + 3600
                return old
            current = set(old["prefixes"])
            changes = len(current.symmetric_difference(candidates))
            suspicious = (not candidates or len(candidates) > self.config.max_prefixes or
                          (old["last_success"] is not None and
                           (changes > self.config.change_absolute or changes / max(1, len(current)) > self.config.change_ratio)))
            old["name"] = name or old["name"]
            old["last_error"] = ""
            old["next_update"] = now + self.config.irr_refresh_days * 86400
            if suspicious:
                old["pending"] = {"prefixes": candidates, "digest": digest(candidates),
                                  "reason": "Empty result or configured change threshold exceeded", "fetched": now}
            else:
                old["prefixes"] = candidates
                old["last_success"] = now
                old["pending"] = None
            return old
        return self.store.change(actor, "asn.refresh", "rule", rule_id, update)

    @audit_failures('asn.confirm', 'rule')
    def confirm_asn(self, actor, rule_id, proposal_digest):
        self.writable(actor)
        def confirm(old):
            if not old or old["kind"] != "asn" or not old["pending"]:
                raise Invalid("No pending ASN proposal")
            if old["pending"]["digest"] != proposal_digest:
                raise Conflict("Proposal changed; review the latest set")
            if old["asn"] in self.config.protected_asns:
                raise Forbidden("Protected ASN")
            old["prefixes"] = old["pending"]["prefixes"]
            old["last_success"] = old["pending"]["fetched"]
            old["pending"] = None
            return old
        return self.store.change(actor, "asn.confirm", "rule", rule_id, confirm)

    @audit_failures('user.update', 'user')
    def save_user(self, actor, login, role=None, password_hash=None, enabled=None, own=False,
                  create_only=False, require_existing=False, expected_version=None):
        if not own:
            self.writable(actor)
        elif actor.login != login:
            raise Forbidden("Cannot change another user's password")
        def update(old):
            if create_only and old is not None:
                raise Conflict('User already exists')
            if require_existing and old is None:
                raise Invalid('User not found')
            if expected_version is not None and (old is None or old['version'] != expected_version):
                raise Conflict('Account changed during password verification')
            if own and (old is None or not old["enabled"] or password_hash is None or role is not None or enabled is not None):
                raise Forbidden("Only own password may be changed")
            if old is None:
                if password_hash is None:
                    raise Invalid("Password required for a new user")
                old = {"id": login, "role": role or "guest", "enabled": True, "password_hash": password_hash, "version": 0}
            old["version"] += 1
            if role is not None:
                old["role"] = role
            if enabled is not None:
                old["enabled"] = enabled
            if password_hash is not None:
                old["password_hash"] = password_hash
            return old
        return self.store.change(actor, "user.update", "user", login, update)
