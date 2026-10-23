from dataclasses import replace
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from hemlock.config import Config, load
from hemlock.domain import Actor, Conflict, Forbidden, Invalid
from hemlock.gobgp import inspect_attributes, nlri, unicast_attributes
from hemlock.irr import IRR, IRRError, bounded_process
from hemlock.replication import NoRedirect, PeerUnavailable
from hemlock.service import Service
from hemlock.store import Store
from hemlock.workers import ASNWorker, ProtectionWorker, process_lock

ADMIN = Actor('admin', 'admin')


class SafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.database = str(Path(self.tmp.name)/'test.sqlite')
        self.config = Config(database=self.database, tls=False)
        self.store = Store(self.config)
        self.service = Service(self.store)

    def tearDown(self):
        self.tmp.cleanup()

    def test_process_lock_and_alias(self):
        with process_lock(self.database):
            with self.assertRaises(Conflict), process_lock(self.database):
                self.fail('Two process owners accepted')
            alias = Path(self.tmp.name)/'alias.sqlite'
            alias.symlink_to(self.database)
            with self.assertRaises(Conflict), process_lock(str(alias)):
                self.fail('Symlink bypassed owner lock')
        with process_lock(self.database):
            pass

    def test_example_config_and_family_settings(self):
        fresh=load('deploy/hemlock.example.ini')
        self.assertEqual(fresh.tls_mode,'pinned');self.assertTrue(fresh.tls)
        example=Path(self.tmp.name)/'example.ini'
        example.write_text(Path('deploy/hemlock.example.ini').read_text().replace('tls = yes','tls = no').replace('mode = pinned','mode = legacy_ca'))
        cfg = load(str(example))
        self.assertFalse(cfg.announcements)
        self.assertFalse(cfg.tls)
        self.assertEqual(cfg.v4_next_hop, '')
        self.assertEqual(cfg.v6_next_hop, '')
        self.assertEqual(cfg.protected_asns, ())
        for changes in [{'peer_url':'http://peer'}, {'owner':(1,2)}, {'community':'666:999999'}, {'grpc_target':'router:50051'}]:
            with self.subTest(changes=changes), self.assertRaises(Invalid):
                replace(cfg, **changes).validate()

    def test_replication_redirect_cannot_leak_token(self):
        with self.assertRaises(PeerUnavailable):
            NoRedirect().redirect_request(None, None, 302, '', {}, 'https://attacker/')

    def test_bgp_binary_attributes_v4_v6_roundtrip(self):
        for candidate, hop in [('192.0.2.0/24','192.0.2.254'), ('2001:db8::/32','2001:db8::1')]:
            attrs = hop, 200, ('64512:666',), (64512,100,1)
            encoded = unicast_attributes(candidate, attrs)
            decoded = inspect_attributes(encoded)
            self.assertEqual(decoded, (hop, 200, ('64512:666',), [(64512,100,1)]))
            self.assertEqual(nlri(candidate)[0], 24 if candidate[0]=='1' else 32)
        with self.assertRaises(Invalid):
            inspect_attributes([b'\x40\x03\x04\x01'])

    def test_actual_process_timeout_and_output_bound(self):
        import sys
        with self.assertRaises(IRRError):
            bounded_process([sys.executable, '-c', 'import time; time.sleep(2)'], 0.05)
        with self.assertRaises(IRRError):
            bounded_process([sys.executable, '-c', 'print("x"*10000)'], 1, 100)
        with self.assertRaises(IRRError):
            bounded_process([sys.executable, '-c', 'raise SystemExit(1)'], 1)
        with self.assertRaises(IRRError) as failure:
            bounded_process([sys.executable, '-c', 'import sys; sys.stderr.write("ERROR: sensitive diagnostic")'], 1)
        self.assertNotIn('sensitive',str(failure.exception))

    def test_scheduler_persists_failures_and_never_clears_protection(self):
        self.service.grow_protection(64496, ['192.0.2.0/24'])
        class Broken:
            def expand(inner, number):
                raise IRRError('upstream failure')
        ProtectionWorker(self.service, Broken()).step()
        self.assertTrue(self.service.protection_ready())
        self.assertIsNotNone(self.service.protection().reason('192.0.2.1'))
        old = self.store.local('protection_schedule')
        ProtectionWorker(Service(Store(self.config)), Broken()).step()
        self.assertEqual(old, self.store.local('protection_schedule'))
        rule = self.service.add_asn(ADMIN, 64500)
        ASNWorker(self.service, Broken(), None).step()
        failed = self.store.get('rule', rule['id'])
        self.assertGreater(failed['next_update'], rule['next_update'])
        self.assertTrue(failed['last_error'])

    def test_concurrent_refresh_does_not_overwrite_comment(self):
        rule = self.service.add_asn(ADMIN, 64500)
        service = self.service
        class RacingIRR:
            def expand(inner, number):
                service.update_comment(ADMIN, rule['id'], 'operator changed this')
                return ['192.0.2.0/24']
        class Metadata:
            def asn_name(inner, number):
                return 'Example'
        with self.assertRaises(Conflict):
            ASNWorker(service, RacingIRR(), Metadata()).refresh(ADMIN, rule['id'])
        self.assertEqual(self.store.get('rule', rule['id'])['comment'], 'operator changed this')

    def test_import_checks_protection_and_rolls_back_whole_batch(self):
        before = self.store.info()
        with self.assertRaises(Forbidden):
            self.service.import_manual(ADMIN, [{'value':'192.0.2.0/24','comment':''}, {'value':'10.1.2.3','comment':''}])
        with self.assertRaises(Invalid):
            self.service.import_manual(ADMIN, [{'value':'192.0.2.0/24','comment':''}, {'value':'2001:db8::/32','comment':42}])
        self.assertEqual(self.store.info(),{**before, 'sequence': before['sequence'] + 2})
        self.assertEqual(self.store.list('rule'),[])
        items = self.service.import_manual(ADMIN, [{'value':'192.0.2.1','comment':'one'}, {'value':'2001:db8::1','comment':'two'}])
        self.assertEqual(len(items),2)
        self.assertEqual(self.store.info()['sequence'],3)
        self.assertEqual(len(self.store.list('audit')),4)

    def test_irr_child_ignores_all_environment_proxy_variants(self):
        import sys
        with patch.dict(os.environ, {'HTTP_PROXY':'http://bad','https_proxy':'http://bad','ALL_PROXY':'http://bad'}):
            result = bounded_process([sys.executable,'-c','import os; print([k for k in os.environ if "proxy" in k.lower()])'],1)
        self.assertEqual(result.strip(),b'[]')


if __name__ == '__main__':
    unittest.main()
