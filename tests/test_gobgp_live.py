"""Opt-in test of an explicitly provided, peer-free loopback GoBGP 4.10.0."""

from dataclasses import replace
import os
from pathlib import Path
import tempfile
import unittest

from hemlock.config import Config
from hemlock.gobgp import GoBGP

TARGET = os.environ.get('HEMLOCK_LIVE_GOBGP', os.environ.get('HEMLOC_LIVE_GOBGP', ''))


@unittest.skipUnless(TARGET, 'Explicit isolated GoBGP target not provided')
class GoBGPLiveTests(unittest.TestCase):
    def test_binary_api_roundtrip_and_addressed_withdrawal(self):
        if TARGET.rsplit(':',1)[0] not in ('127.0.0.1','[::1]'):
            self.fail('Live integration test is restricted to loopback')
        config = Config(tls=False, announcements=True, grpc_target=TARGET, protected_asns=(), owner=(64512,100,4294967294))
        adapter = GoBGP(config)
        safe_to_clean = False
        candidates = [('192.0.2.254/32','192.0.2.254'), ('2001:db8:ffff::1/128','2001:db8::1')]
        try:
            baseline = adapter.observe()
            self.assertEqual(baseline['peers'], [], 'Refusing a daemon with configured BGP peers')
            self.assertFalse(any(tuple(p['owner']) == config.owner for p in baseline['paths']), 'Test marker is already in use')
            self.assertFalse(any(p['prefix'] in {n for n,h in candidates} for p in baseline['paths']), 'Test prefix already exists')
            safe_to_clean = True
            before = {(p['prefix'],p['identifier']) for p in baseline['paths']}
            for candidate, hop in candidates:
                created_uuid = adapter.add(candidate, (hop, 200, ('64512:666',), config.owner))
                owned = [p for p in adapter.paths() if p.prefix == candidate and p.owner == config.owner]
                self.assertEqual(len(owned),1)
                self.assertEqual(owned[0].next_hop,hop)
                self.assertTrue(owned[0].local)
                self.assertTrue(created_uuid)
                self.assertEqual(owned[0].identifier,adapter.identifier)
                adapter.delete(owned[0])
                self.assertFalse(any(p.key == owned[0].key for p in adapter.paths()))
            self.assertEqual({p.key for p in adapter.paths()},before)
        finally:
            # Only paths created under this test marker are eligible for cleanup.
            # No broad withdrawals and no daemon restart.
            try:
                if safe_to_clean:
                    for path in adapter.paths():
                        if path.local and path.owner == config.owner:
                            adapter.delete(path)
            finally:
                adapter.close()


if __name__ == '__main__':
    unittest.main()
