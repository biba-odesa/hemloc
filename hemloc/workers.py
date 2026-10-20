"""Single-process background work without cron or external queues."""

import asyncio
from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
import time

from .domain import Conflict
from .irr import IRR, Metadata
from .service import SYSTEM
from .store import digest


@contextmanager
def process_lock(database):
    path = Path(str(Path(database).resolve()) + '.owner.lock')
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise Conflict('Another Hemloc process owns background tasks for this database') from exc
        yield
    finally:
        os.close(fd)


class ASNWorker:
    def __init__(self, service, irr=None, metadata=None):
        self.service = service
        self.irr = irr or IRR(service.config)
        self.metadata = metadata or Metadata(service.config)

    def refresh(self, actor, rule_id):
        self.service.writable(actor)
        old = self.service.store.get('rule', rule_id)
        if not old or old['kind'] != 'asn':
            from .domain import Invalid
            raise Invalid('ASN rule not found')
        try:
            prefixes = self.irr.expand(old['asn'])
        except Exception:
            return self.service.update_asn(actor, rule_id, failed=True, expected=digest(old))
        try:
            name = self.metadata.asn_name(old['asn'])
        except Exception:
            name = ''
        return self.service.update_asn(actor, rule_id, prefixes, name, expected=digest(old))

    def step(self):
        if self.service.config.role != 'master':
            return
        for rule in self.service.store.list('rule'):
            if rule['kind'] == 'asn' and (rule['next_update'] or 0) <= time.time():
                try:
                    self.refresh(SYSTEM, rule['id'])
                except Exception:
                    # A concurrent deletion or role change must not terminate the scheduler.
                    continue


class ProtectionWorker:
    def __init__(self, service, irr=None):
        self.service = service
        self.irr = irr or IRR(service.config)

    def step(self):
        state = self.service.store.local('protection_schedule', {})
        for number in self.service.config.protected_asns:
            if state.get(str(number), {}).get('next', 0) > time.time():
                continue
            try:
                self.service.grow_protection(number, self.irr.expand(number))
                state[str(number)] = {'next': time.time() + 30*86400, 'error': ''}
            except Exception:
                state[str(number)] = {'next': time.time() + 3600, 'error': 'Protected IRR lookup failed; cache retained'}
            self.service.store.set_local('protection_schedule', state)


async def repeat(stop, function, interval, store, label):
    while not stop.is_set():
        try:
            await asyncio.to_thread(function)
        except Exception:
            store.set_local('worker:' + label, {'at': time.time(), 'error': 'Background operation failed; previous state retained'})
            if label == 'bgp':
                previous = store.local('bgp', {})
                previous.update({'error': 'GoBGP inspection or reconciliation failed', 'last_attempt': time.time()})
                store.set_local('bgp', previous)
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
        except TimeoutError:
            pass
