from dataclasses import replace
import tempfile
from pathlib import Path
import unittest
import uuid
from unittest.mock import patch

from hemlock.auth import Auth
from hemlock.config import Config
from hemlock.domain import Actor, Conflict, Forbidden
from hemlock.reconcile import Path as BGPPath, Reconciler
from hemlock.replication import PeerTransport, PeerUnavailable, Replicator
from hemlock.service import Service
from hemlock.store import Store

ADMIN = Actor('admin', 'admin')
HASH = '$argon2id$v=19$m=65536,t=3,p=4$fake$fake'


class FakeBGP:
    def __init__(self):
        self.rib = []
        self.calls = []
        self.crash = False

    def paths(self):
        return list(self.rib)

    def add(self, candidate, attrs):
        self.calls.append(('add', candidate))
        self.rib.append(BGPPath(str(uuid.uuid4()), candidate, *attrs))
        if self.crash:
            self.crash = False
            raise OSError('crash after gRPC success')

    def delete(self, path):
        self.calls.append(('delete', path.uuid))
        self.rib = [p for p in self.rib if p.uuid != path.uuid]


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.a = Config(database=str(Path(self.tmp.name)/'a.sqlite'), node_id='a', peer_node_id='b', tls=False, protected_asns=())
        self.b = replace(self.a, database=str(Path(self.tmp.name)/'b.sqlite'), node_id='b', peer_node_id='a', role='slave')
        self.store = Store(self.a)
        self.service = Service(self.store)
        self.slave = Store(self.b)

    def tearDown(self):
        self.tmp.cleanup()

    def user(self):
        self.service.save_user(ADMIN, 'admin', role='admin', password_hash=HASH)

    def test_session_revocation_on_both_nodes_after_replication(self):
        self.user()
        self.slave.install_snapshot(self.store.snapshot())
        auth = Auth(self.store, lambda h,p: p == 'correct')
        slave_auth = Auth(self.slave, lambda h,p: p == 'correct')
        token, csrf = auth.login('admin', 'correct', 'client')
        slave_token, _ = slave_auth.login('admin', 'correct', 'client')
        self.assertEqual(auth.session(token), (ADMIN, csrf))
        self.service.save_user(ADMIN, 'admin', password_hash=HASH)
        with self.assertRaises(Forbidden):
            auth.session(token)
        slave_auth.session(slave_token)
        self.slave.apply_events(self.store.events(self.slave.info()['history'], self.slave.info()['sequence']))
        with self.assertRaises(Forbidden):
            slave_auth.session(slave_token)
        self.assertNotIn(token, str(self.store.list('audit')))

    def test_disabled_user_and_persistent_login_limit(self):
        self.user()
        auth = Auth(self.store, lambda h,p: False)
        for _ in range(5):
            with self.assertRaises(Forbidden):
                auth.login('admin', 'wrong', 'client')
        with self.assertRaisesRegex(Forbidden, 'Too many'):
            Auth(Store(self.a), lambda h,p: True).login('admin', 'correct', 'client')
        good = Auth(self.store, lambda h,p: True)
        token, _ = good.login('admin', 'correct', 'other-client')
        self.service.save_user(ADMIN, 'admin', enabled=False)
        with self.assertRaises(Forbidden):
            good.session(token)

    def test_disabled_announcements_do_not_even_read_adapter(self):
        self.service.add_manual(ADMIN, '192.0.2.0/24')
        result = Reconciler(self.service, None).step()
        self.assertEqual(result['confirmed'], [])
        self.assertEqual(result['desired'], 1)
        self.assertFalse(result['reconciliation_performed'])
        self.assertIn('existing paths retained', result['mode'])

    def test_recovery_crash_restart_attribute_repair_only_owned(self):
        config = replace(self.a, announcements=True)
        service = Service(Store(config))
        rule = service.add_manual(ADMIN, '192.0.2.0/24')
        bgp = FakeBGP()
        foreign = BGPPath('foreign', '198.51.100.0/24', '192.0.2.1', 100, (), (), True)
        learned = BGPPath('learned', '203.0.113.0/24', config.v4_next_hop, 200, (config.community,), config.owner, False)
        bgp.rib.extend([foreign, learned])
        bgp.crash = True
        reconciler = Reconciler(service, bgp)
        with self.assertRaises(OSError):
            reconciler.step()
        result = reconciler.step()
        self.assertEqual(result['confirmed'], ['192.0.2.0/24'])
        self.assertEqual(len([p for p in bgp.rib if p.prefix == '192.0.2.0/24']), 1)
        owned = next(p for p in bgp.rib if p.prefix == '192.0.2.0/24')
        bgp.rib[bgp.rib.index(owned)] = replace(owned, local_pref=100)
        reconciler.step()
        self.assertEqual(next(p for p in bgp.rib if p.prefix == owned.prefix).local_pref, 200)
        bgp.rib = [foreign, learned]
        reconciler.step()
        self.assertEqual(len(bgp.rib), 3)
        service.delete_rule(ADMIN, rule['id'])
        reconciler.step()
        self.assertEqual(bgp.rib, [foreign, learned])

    def test_protection_change_withdraws_and_missing_v6_next_hop(self):
        config = replace(self.a, announcements=True)
        service = Service(Store(config))
        service.add_manual(ADMIN, '192.0.2.0/24')
        service.add_manual(ADMIN, '2001:db8::/32')
        bgp = FakeBGP()
        Reconciler(service, bgp).step()
        self.assertEqual(len(bgp.rib), 1)
        changed = replace(config, protected_prefixes=('192.0.2.0/24',))
        result = Reconciler(Service(Store(changed)), bgp).step()
        self.assertEqual(bgp.rib, [])
        self.assertEqual(result['missing_next_hop'], ['2001:db8::/32'])

    def test_removing_ipv6_next_hop_withdraws_previously_owned_route(self):
        config = replace(self.a, announcements=True, v6_next_hop='2001:db8::1')
        service = Service(Store(config))
        service.add_manual(ADMIN, '2001:db8::/32')
        bgp = FakeBGP()
        Reconciler(service,bgp).step()
        self.assertEqual(len(bgp.rib),1)
        changed = Service(Store(replace(config,v6_next_hop='')))
        result = Reconciler(changed,bgp).step()
        self.assertEqual(bgp.rib,[])
        self.assertEqual(result['missing_next_hop'],['2001:db8::/32'])

    def test_route_snapshot_revision_cannot_advance_past_its_rule_set(self):
        self.service.add_manual(ADMIN,'192.0.2.0/24')
        before = self.store.info()
        writer = Service(Store(self.a,activate=False))
        connect = self.store.connect
        fired = False
        def connection_with_concurrent_write():
            db = connect()
            def trace(statement):
                nonlocal fired
                if not fired and statement == "SELECT body FROM local WHERE key='protection'":
                    fired = True
                    writer.add_manual(ADMIN,'2001:db8::/32')
            db.set_trace_callback(trace)
            return db
        with patch.object(self.store,'connect',side_effect=connection_with_concurrent_write):
            routes,_,revision = self.service.route_snapshot()
        self.assertTrue(fired)
        self.assertEqual(set(routes),{'192.0.2.0/24'})
        self.assertEqual(revision['sequence'],before['sequence'])
        self.assertEqual(set(self.service.routes()[0]),{'192.0.2.0/24','2001:db8::/32'})

    def test_replication_disconnect_restart_then_catchup(self):
        master = self.store
        class Transport:
            broken = False
            def get(inner, path, query=None):
                if inner.broken:
                    raise PeerUnavailable('disconnect')
                if path.endswith('/status'):
                    return master.info()
                if path.endswith('/snapshot'):
                    return master.snapshot()
                return master.events(query['history'], query['cursor'])
        transport = Transport()
        worker = Replicator(self.slave, transport)
        self.service.add_manual(ADMIN, '192.0.2.0/24')
        worker.step()
        last_success = self.slave.local('sync')['last_success']
        transport.broken = True
        self.service.add_manual(ADMIN, '2001:db8::/32')
        with self.assertRaises(PeerUnavailable):
            worker.step()
        self.assertEqual(len(self.slave.list('rule')), 1)
        self.assertFalse(self.slave.local('sync')['ok'])
        self.assertEqual(self.slave.local('sync')['last_success'], last_success)
        transport.broken = False
        Replicator(Store(self.b), transport).step()
        self.assertEqual(self.slave.list('rule'), self.store.list('rule'))

    def test_two_masters_report_conflict(self):
        other = Store(replace(self.b, role='master'))
        class Transport:
            def get(inner, path, query=None):
                return other.info()
        with self.assertRaises(Conflict):
            Replicator(self.store, Transport()).step()
        self.assertFalse(self.store.local('sync')['ok'])
        self.assertEqual(self.store.local('sync')['code'],'two_masters')

    def test_replication_transport_explicitly_disables_environment_proxy(self):
        with patch('hemlock.replication.build_opener') as opener:
            transport = PeerTransport(replace(self.a, use_proxy=True, https_proxy='http://proxy:3128'))
            proxy_handler = opener.call_args.args[0]
            self.assertEqual(proxy_handler.proxies, {})
            transport.token='x'*40
            self.assertFalse(transport.authorized('Bearer \u00ff',self.a.peer_node_id))


if __name__ == '__main__':
    unittest.main()
