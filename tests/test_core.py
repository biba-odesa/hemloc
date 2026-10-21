import copy
from dataclasses import replace
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from hemlock.config import Config, proxy_for
from hemlock.domain import Actor, Conflict, Forbidden, Invalid, NeedSnapshot, Protection, prefix
from hemlock.irr import IRR, IRRError, Metadata
from hemlock.service import Service
from hemlock.store import Store, digest, encode

ADMIN = Actor('alice', 'admin')
GUEST = Actor('viewer', 'guest')
HASH = '$argon2id$v=19$m=65536,t=3,p=4$fake$fake'


class PrefixTests(unittest.TestCase):
    def test_protection_both_families(self):
        p = Protection(['192.0.2.0/24', '2001:db8:1::/48', '10.0.0.0/8'])
        for n in ['192.0.2.0/24', '192.0.2.128/25', '192.0.2.1/32', '2001:db8:1::/48', '2001:db8:1::1/128', '10.1.0.0/16']:
            with self.subTest(n=n), self.assertRaises(Forbidden):
                p.check(n)
        for n in ['192.0.0.0/16', '2001:db8::/32', '0.0.0.0/0', '::/0', '198.51.100.0/24']:
            p.check(n)

    def test_host_normalization_and_host_bits(self):
        self.assertEqual(prefix('192.0.2.1'), '192.0.2.1/32')
        self.assertEqual(prefix('2001:db8::1'), '2001:db8::1/128')
        with self.assertRaisesRegex(Invalid, '192.0.2.0/24'):
            prefix('192.0.2.1/24')
        with self.assertRaisesRegex(Invalid, '2001:db8::/64'):
            prefix('2001:db8::1/64')


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.a = Config(database=str(self.base/'a.sqlite'), node_id='a', peer_node_id='b', tls=False)
        self.b = replace(self.a, database=str(self.base/'b.sqlite'), node_id='b', peer_node_id='a', role='slave')
        self.master, self.slave = Store(self.a), Store(self.b)
        self.service = Service(self.master)

    def tearDown(self):
        self.temp.cleanup()

    def manual(self, value='192.0.2.0/24'):
        return self.service.add_manual(ADMIN, value, '<script>alert(1)</script>')

    def sync(self):
        self.slave.install_snapshot(self.master.snapshot())

    def test_multiple_reasons_and_deletion(self):
        a = self.manual()
        b = self.service.add_asn(ADMIN, 64501)
        self.service.update_asn(ADMIN, b["id"], ["192.0.2.0/24"])
        self.manual('192.0.2.2')
        self.assertEqual(len(self.service.search('192.0.2.2')), 3)
        self.assertEqual(len(self.service.routes()[0]['192.0.2.0/24']), 2)
        self.service.delete_rule(ADMIN, a['id'])
        self.assertEqual(self.service.routes()[0]['192.0.2.0/24'], [b['id']])

    def test_guest_and_slave_mutations(self):
        for service, actor in [(self.service, GUEST), (Service(self.slave), ADMIN)]:
            with self.assertRaises(Forbidden):
                service.add_manual(actor, '192.0.2.1')
            with self.assertRaises(Forbidden):
                service.add_asn(actor, 64500)
            with self.assertRaises(Forbidden):
                service.save_user(actor, 'new', password_hash=HASH)
        with self.assertRaises(Forbidden):
            Service(self.slave).save_user(ADMIN, ADMIN.login, password_hash=HASH, own=True)

    def test_transaction_rollback_and_audit_redaction(self):
        self.service.save_user(ADMIN, 'alice', role='admin', password_hash=HASH)
        self.assertNotIn(HASH, encode(self.master.list('audit')))
        self.assertNotIn('password_hash', encode(self.master.list('audit')))
        info = self.master.info()
        with self.assertRaises(Invalid):
            self.service.add_manual(ADMIN, '192.0.2.1', comment=1)
        self.assertEqual(self.master.info(), {**info, 'sequence': info['sequence'] + 1})
        self.assertEqual(len(self.master.list('rule')), 0)
        with self.master.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM journal').fetchone()[0], 2)
        self.assertEqual([a['result'] for a in self.master.list('audit')].count('invalid'), 1)

    def test_snapshot_journal_without_gap_repeat_restart(self):
        self.manual()
        snapshot = self.master.snapshot()
        second = self.manual('2001:db8::/32')
        backup = self.slave.install_snapshot(snapshot)
        self.assertTrue(Path(backup).is_file())
        batch = self.master.events(snapshot['payload']['history'], snapshot['payload']['sequence'])
        self.slave.apply_events(batch)
        self.slave.apply_events(batch)
        restarted = Store(self.b)
        self.assertEqual(restarted.get('rule', second['id']), second)
        self.assertEqual(self.master.list('rule'), restarted.list('rule'))
        self.assertEqual(self.master.list('audit'), restarted.list('audit'))

    def test_partial_delivery_rolls_back(self):
        self.sync()
        self.manual()
        self.manual('2001:db8::/32')
        batch = self.master.events(self.slave.info()['history'], 0)
        broken = copy.deepcopy(batch)
        broken['events'][1]['seq'] += 1
        with self.assertRaises((Invalid, NeedSnapshot)):
            self.slave.apply_events(broken)
        self.assertEqual(self.slave.info()['sequence'], 0)
        self.assertEqual(self.slave.list('rule'), [])
        self.slave.apply_events(batch)
        self.assertEqual(self.slave.info()['sequence'], 2)

    def test_bad_snapshot_preserves_working_data_and_local_state(self):
        old = self.manual()
        self.sync()
        self.slave.set_local('protection', {'prefixes': ['198.51.100.0/24'], 'success': {}})
        bad = self.master.snapshot()
        bad['payload']['documents'][0]['id'] = 'tampered'
        with self.assertRaises(Invalid):
            self.slave.install_snapshot(bad)
        self.assertEqual(self.slave.get('rule', old['id']), old)
        good = self.master.snapshot()
        self.slave.install_snapshot(good)
        self.assertEqual(self.slave.local('protection')['prefixes'], ['198.51.100.0/24'])

    def test_promotion_return_and_split_brain(self):
        old = self.manual()
        self.sync()
        old_history = self.master.info()['history']
        new_master = Store(replace(self.b, role='master'))
        self.assertNotEqual(old_history, new_master.info()['history'])
        Service(new_master).delete_rule(ADMIN, old['id'])
        fresh = Service(new_master).add_manual(ADMIN, '198.51.100.0/24')
        with self.assertRaises(Conflict):
            self.master.install_snapshot(new_master.snapshot())
        self.manual('203.0.113.0/24')
        returned = Store(replace(self.a, role='slave'))
        returned.install_snapshot(new_master.snapshot())
        self.assertEqual(returned.list('rule'), [fresh])
        with self.assertRaises(Forbidden):
            self.manual('192.0.2.3')

    def test_journal_retention_and_wrong_peer(self):
        self.sync()
        self.manual()
        with self.master.transaction() as db:
            db.execute('DELETE FROM journal')
        with self.assertRaises(NeedSnapshot):
            self.master.events(self.slave.info()['history'], 0)
        bad = self.master.snapshot()
        bad['payload']['master_id'] = 'stranger'
        bad['digest'] = digest(bad['payload'])
        with self.assertRaises(Conflict):
            self.slave.install_snapshot(bad)

    def test_irr_error_empty_anomaly_and_confirmation(self):
        rule = self.service.add_asn(ADMIN, 64500)
        initial = self.service.update_asn(ADMIN, rule['id'], ['192.0.2.0/24'], 'Example')
        self.assertEqual(initial['prefixes'], ['192.0.2.0/24'])
        failed = self.service.update_asn(ADMIN, rule['id'], failed=True)
        self.assertEqual(failed['prefixes'], initial['prefixes'])
        pending = self.service.update_asn(ADMIN, rule['id'], [])
        self.assertEqual(pending['prefixes'], initial['prefixes'])
        with self.assertRaises(Conflict):
            self.service.confirm_asn(ADMIN, rule['id'], 'stale')
        accepted = self.service.confirm_asn(ADMIN, rule['id'], pending['pending']['digest'])
        self.assertEqual(accepted['prefixes'], [])
        changed = self.service.update_asn(ADMIN, rule['id'], ['198.51.100.0/24'])
        self.assertIsNotNone(changed['pending'])

    def test_protection_persist_grow_and_local_slave_difference(self):
        self.assertFalse(self.service.protection_ready())
        with self.assertRaises(Forbidden):
            self.service.add_asn(ADMIN, 64496)
        rule = self.service.add_asn(ADMIN, 64500)
        self.service.update_asn(ADMIN, rule['id'], ['192.0.2.0/24', '10.1.0.0/16'])
        self.assertEqual(set(self.service.routes()[0]), {'192.0.2.0/24'})
        self.assertEqual(len(self.service.routes()[1]), 1)
        self.service.grow_protection(64496, ['198.51.100.0/24'])
        self.service.grow_protection(64496, ['203.0.113.0/24'])
        restarted = Service(Store(self.a))
        self.assertTrue(restarted.protection_ready())
        self.assertIsNotNone(restarted.protection().reason('198.51.100.1/32'))
        with self.assertRaises(Invalid):
            restarted.grow_protection(64496, [])
        self.sync()
        slave_service = Service(self.slave)
        slave_service.grow_protection(64496, ['192.0.2.0/24'])
        self.assertEqual(slave_service.routes()[0], {})
        self.assertEqual(len(self.slave.get('rule', rule['id'])['prefixes']), 2)


class ClientTests(unittest.TestCase):
    def test_irr_partial_family_failure(self):
        def runner(args, timeout):
            if '-4' in args:
                return b'192.0.2.0/24\n'
            raise IRRError('timeout')
        with self.assertRaises(IRRError):
            IRR(Config(), runner).expand(64500)

    def test_irr_strict_parse_no_aggregation_or_shell(self):
        calls = []
        def runner(args, timeout):
            calls.append(args)
            return b'192.0.2.0/24\n' if '-4' in args else b'2001:db8::/32\n'
        self.assertEqual(len(IRR(Config(), runner).expand('AS64500')), 2)
        self.assertNotIn('-A', calls[0])
        self.assertEqual(calls[0][-1], 'AS64500')
        with self.assertRaises(IRRError):
            IRR(Config(), lambda a,t: b'192.0.2.1/24').expand(64500)
        self.assertEqual(IRR(Config(), lambda a,t: b'').expand(64500), [])

    def test_proxy_explicit_policy_ignores_env(self):
        direct = Config()
        proxied = replace(direct, use_proxy=True, http_proxy='http://proxy:3128', https_proxy='http://proxy:3128')
        self.assertIsNone(proxy_for(direct, 'https://example.org'))
        self.assertEqual(proxy_for(proxied, 'https://example.org'), 'http://proxy:3128')
        for host in ['localhost', '127.0.0.1', '[::1]', 'block-a', 'block-b']:
            self.assertIsNone(proxy_for(proxied, 'https://' + host))
        self.assertEqual(proxy_for(proxied, 'https://block-a.evil.test'), 'http://proxy:3128')

    def test_no_first_ip_origin_for_network(self):
        def forbidden(*args):
            self.fail('Network metadata must not look up first address')
        self.assertEqual(Metadata(Config(), forbidden).origins('192.0.2.0/24'), [])


if __name__ == '__main__':
    unittest.main()
