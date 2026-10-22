"""Bounded process-local observations, never a source of durable replication state."""
from copy import deepcopy
from threading import RLock


KEYS = frozenset(('peer_compatibility','rib', 'bgp', 'peer', 'sync', 'worker:retention', 'worker:asn',
                  'worker:protection', 'worker:bgp', 'worker:observation', 'worker:replication'))


def volatile(key):
    return key in KEYS or key.startswith('worker:')


class Observations:
    def __init__(self):
        self._lock = RLock()
        self._values = {}

    def get(self, key, default=None):
        with self._lock:
            return deepcopy(self._values.get(key, default))

    def set(self, key, value):
        if key not in KEYS:
            raise ValueError('Not an observation key')
        with self._lock:
            self._values[key] = deepcopy(value)

    def snapshot(self):
        with self._lock:
            return deepcopy(self._values)
