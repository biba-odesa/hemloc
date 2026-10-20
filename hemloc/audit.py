"""Allowlisted security events; request bodies and exception text never enter audit."""

from functools import wraps
import re

from .domain import Conflict, Forbidden, Invalid

ACTIONS = frozenset({
    'auth.login', 'auth.logout', 'auth.session', 'auth.password', 'http.request',
    'rule.create', 'rule.import', 'rule.comment', 'rule.delete',
    'routes.withdraw-owned', 'asn.refresh', 'asn.confirm', 'user.update', 'user.create', 'user.reset-password',
})
RESULTS = frozenset({'success', 'denied', 'invalid', 'conflict', 'failed', 'throttled'})
OBJECTS = frozenset({'session', 'rule', 'user', 'request', 'route'})


def identity(login):
    """Only established identities should be passed; never use attempted credentials."""
    return login if isinstance(login, str) and re.fullmatch(r'[A-Za-z0-9_.@:-]{1,96}', login) else 'anonymous'


def failure_result(exc):
    if isinstance(exc, Forbidden):
        return 'denied'
    if isinstance(exc, Invalid):
        return 'invalid'
    if isinstance(exc, Conflict):
        return 'conflict'
    return 'failed'


def audited_error(exc):
    exc.hemloc_audited = True
    return exc


def audit_failures(action, object_name):
    def decorate(function):
        @wraps(function)
        def wrapped(self, actor, *args, **kwargs):
            try:
                return function(self, actor, *args, **kwargs)
            except Exception as exc:
                if not getattr(exc, 'hemloc_audited', False):
                    self.store.security_event(actor.login, action, object_name, failure_result(exc))
                    audited_error(exc)
                raise
        return wrapped
    return decorate


def login_context(address):
    """Only a real socket IP can enter successful-login metadata."""
    import ipaddress
    try:
        return {'client_ip': str(ipaddress.ip_address(address))}
    except ValueError:
        return None


def validate_security_context(action, object_name, result, before, after):
    """Keep the existing peer outbox constrained while accepting login socket IPs."""
    from .domain import Invalid
    if before is not None:
        raise Invalid('Security events cannot contain before data')
    if after is None:
        return
    if (action != 'auth.login' or object_name != 'session' or result != 'success' or
            not isinstance(after, dict) or set(after) != {'client_ip'} or
            not isinstance(after['client_ip'], str) or login_context(after['client_ip']) != after):
        raise Invalid('Invalid security event context')
