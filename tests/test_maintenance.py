"""Drain is explicit, locked, local-only and preserves foreign paths."""
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from hemloc.config import Config
from hemloc.domain import Conflict
from hemloc.maintenance import withdraw_owned
from hemloc.reconcile import Path as Route
from hemloc.store import Store
from hemloc.workers import process_lock


class DrainTests(unittest.TestCase):
    def test_drain_gates_ownership_idempotence_and_audit(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Config(database=str(Path(tmp)/'a.sqlite'), tls=False)
            store = Store(cfg)
            owned = Route('', '192.0.2.1/32', '', 200, (), cfg.owner)
            foreign = replace(owned, prefix='192.0.2.2/32', owner=())
            learned = replace(owned, prefix='192.0.2.3/32', local=False)
            paths = [owned, foreign, learned]
            class Adapter:
                def __init__(self, config):
                    self.config = config
                def paths(self):
                    return list(paths)
                def delete(self, path):
                    paths.remove(path)
                def close(self):
                    pass
            self.assertEqual(withdraw_owned(store, adapter_factory=Adapter)['owned'], 1)
            self.assertEqual(len(paths), 3)
            with process_lock(cfg.database), self.assertRaises(Conflict):
                withdraw_owned(store, True, Adapter)
            store.config = replace(cfg, announcements=True)
            with self.assertRaises(Conflict):
                withdraw_owned(store, True, Adapter)
            store.config = cfg
            self.assertEqual(withdraw_owned(store, True, Adapter)['withdrawn'], 1)
            self.assertEqual(paths, [foreign, learned])
            self.assertEqual(withdraw_owned(store, True, Adapter)['withdrawn'], 0)
            self.assertTrue(any(a['action']=='routes.withdraw-owned' for a in store.audit_history()))
            self.assertTrue(any(a['result']=='conflict' for a in store.audit_history()))
            class Broken(Adapter):
                def paths(self):
                    raise RuntimeError('sentinel-private-wire')
            with self.assertRaises(Conflict) as error:
                withdraw_owned(store, True, Broken)
            self.assertNotIn('sentinel-private-wire',str(error.exception)+str(store.audit_history()))
            self.assertTrue(any(a['result']=='failed' for a in store.audit_history()))
