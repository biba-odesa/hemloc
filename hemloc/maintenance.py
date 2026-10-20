"""Explicit local route drain; never changes desired rules or foreign paths."""
from dataclasses import replace
from .audit import audited_error, failure_result
from .domain import Conflict
from .gobgp import GoBGP
from .workers import process_lock


def withdraw_owned(store, execute=False, adapter_factory=GoBGP):
    try:
        return _withdraw_owned(store, execute, adapter_factory)
    except Exception as exc:
        store.security_event('root:cli','routes.withdraw-owned','route',failure_result(exc))
        if isinstance(exc, Conflict):
            raise audited_error(exc)
        raise audited_error(Conflict('Route drain failed; inspect local GoBGP and retry with Hemloc stopped')) from None


def _withdraw_owned(store, execute, adapter_factory):
    if store.config.announcements:
        raise Conflict('Set announcements=no and stop Hemloc before draining routes')
    with process_lock(store.config.database):
        # This adapter is used only for guarded deletions, never for additions.
        adapter = adapter_factory(replace(store.config, announcements=True))
        try:
            paths = adapter.paths()
            owned = [p for p in paths if p.local and p.owner == store.config.owner]
            foreign = {p.key for p in paths if p not in owned}
            result = {'mode':'execute' if execute else 'dry-run', 'owned':len(owned),
                      'foreign':len(foreign), 'withdrawn':0}
            if execute:
                for path in owned:
                    adapter.delete(path)
                    result['withdrawn'] += 1
                remaining = adapter.paths()
                if any(p.local and p.owner == store.config.owner for p in remaining):
                    raise Conflict('Owned paths remain; inspect RIB and retry with Hemloc stopped')
                if not foreign.issubset({p.key for p in remaining}):
                    raise Conflict('Concurrent foreign RIB change detected; inspect local GoBGP')
                store.security_event('root:cli','routes.withdraw-owned','route','success')
            return result
        finally:
            adapter.close()
