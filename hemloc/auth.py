"""Argon2id passwords and local server-side sessions."""

import hashlib
import secrets
import time

from .domain import Actor, Forbidden, Invalid
from .store import Store
from .audit import audited_error, login_context


PASSWORD_MIN_LENGTH = 6
PASSWORD_MAX_LENGTH = 1024


def validate_password(password):
    if not isinstance(password, str) or not PASSWORD_MIN_LENGTH <= len(password) <= PASSWORD_MAX_LENGTH:
        raise Invalid(f"Password must contain {PASSWORD_MIN_LENGTH}..{PASSWORD_MAX_LENGTH} characters")
    if not any(character.isalpha() for character in password) or not any(character.isdigit() for character in password):
        raise Invalid("Password must contain at least one letter and one digit")


def password_hash(password):
    validate_password(password)
    from argon2 import PasswordHasher, Type
    return PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4, type=Type.ID).hash(password)


def password_verify(encoded, password):
    from argon2 import PasswordHasher
    from argon2.exceptions import InvalidHashError, VerificationError
    try:
        return PasswordHasher().verify(encoded, password)
    except (InvalidHashError, VerificationError):
        return False


def token_digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


class Auth:
    def __init__(self, store, verifier=password_verify, clock=time.time):
        self.store, self.verifier, self.clock = store, verifier, clock

    def login(self, login, password, address):
        """Serialize attempts per client address; no trusted forwarded headers."""
        now = self.clock()
        throttle = "login-limit:" + token_digest(address)
        outcome = 'success'
        notify_limit = False
        known_login = None
        with self.store.transaction() as db:
            row = db.execute("SELECT body FROM local WHERE key=?", (throttle,)).fetchone()
            import json
            state = json.loads(row[0]) if row else {"since": now, "count": 0}
            if now - state["since"] >= 900:
                state = {"since": now, "count": 0}
            if state["count"] >= 5:
                outcome = 'throttled'
                user = None
                known = Store.read(db, 'user', login)
                known_login = known['id'] if known else None
                if not state.get('notified'):
                    notify_limit = True
                    state['notified'] = True
                    Store.write_local(db, throttle, state)
            else:
                user = Store.read(db, "user", login)
                try:
                    valid = bool(user and user["enabled"] and self.verifier(user["password_hash"], password))
                except Exception:
                    valid, outcome = False, 'failed'
                if not valid:
                    state["count"] += 1
                    Store.write_local(db, throttle, state)
                    if outcome != 'failed':
                        outcome = 'denied'
                else:
                    token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
                    db.execute("DELETE FROM sessions WHERE expires<=?", (now,))
                    db.execute("INSERT INTO sessions VALUES(?,?,?,?,?)", (token_digest(token), login, user["version"], csrf, now + 8*3600))
                    Store.write_local(db, throttle, {"since": now, "count": 0})
            self.store.security_record(db, user['id'] if outcome == 'success' else 'anonymous',
                                       'auth.login', 'session', outcome,
                                       context=login_context(address) if outcome == 'success' else None)
        if outcome == 'throttled':
            if notify_limit and self.store.notifications:
                self.store.notifications.login_blocked(address, known_login, state['since'] + 900 - now)
            raise audited_error(Forbidden("Too many login attempts; retry after 15 minutes"))
        if outcome == 'failed':
            raise audited_error(RuntimeError("Authentication service unavailable"))
        if outcome == 'denied':
            raise audited_error(Forbidden("Invalid login or password"))
        return token, csrf

    def session(self, token):
        if not token or len(token) > 256:
            raise Forbidden("Login required")
        with self.store.connect() as db:
            row = db.execute("SELECT * FROM sessions WHERE token=?", (token_digest(token),)).fetchone()
            if row is None or row["expires"] <= self.clock():
                raise Forbidden("Session expired")
            user = Store.read(db, "user", row["login"])
            if not user or not user["enabled"] or user["version"] != row["version"]:
                raise Forbidden("Session revoked")
            return Actor(user["id"], user["role"]), row["csrf"]

    def logout(self, token):
        with self.store.transaction() as db:
            row = db.execute("SELECT login FROM sessions WHERE token=?", (token_digest(token),)).fetchone()
            db.execute("DELETE FROM sessions WHERE token=?", (token_digest(token),))
            self.store.security_record(db, row[0] if row else 'anonymous', 'auth.logout', 'session', 'success')
