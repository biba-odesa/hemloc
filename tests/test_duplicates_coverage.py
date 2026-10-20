"""Transactional duplicate guards and indexed, protection-aware coverage."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import sqlite3
import tempfile
import unittest
import uuid
from hemloc.config import Config
from hemloc.coverage import index_for
from hemloc.domain import Actor, Conflict, Duplicate, Invalid
from hemloc.presentation import View, paginate
from hemloc.service import Service
from hemloc.store import Store, encode

ADMIN=Actor('operator','admin')


class RulesTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.cfg=Config(database=str(Path(self.tmp.name)/'a.sqlite'),node_id='a',peer_node_id='b',tls=False,protected_asns=(),protected_prefixes=())
        self.store=Store(self.cfg);self.service=Service(self.store)

    def tearDown(self):self.tmp.cleanup()

    def manual(self,value):return self.service.add_manual(ADMIN,value,'A reason')

    def test_normalized_duplicates_and_independent_asn_manual(self):
        for left,right in [('192.0.2.1','192.0.2.1/32'),('2001:db8::1','2001:0db8:0:0::1/128'),('2001:db8::/32','2001:0DB8:0000::/32')]:
            first=self.manual(left)
            with self.assertRaises(Duplicate) as exc:self.manual(right)
            self.assertEqual(exc.exception.rule_id,first['id'])
        rule=self.service.add_asn(ADMIN,'AS123')
        with self.assertRaises(Duplicate):self.service.add_asn(ADMIN,123)
        self.service.update_asn(ADMIN,rule['id'],['192.0.2.1/32'])
        self.assertEqual(len(self.service.routes()[0]['192.0.2.1/32']),2)
        with self.assertRaises(Invalid):self.manual('192.0.2.1/24')

    def test_concurrent_writers_and_atomic_import(self):
        def attempt(number):
            try:
                return Service(Store(self.cfg,activate=False)).add_manual(ADMIN,'2001:db8::5' if number%2 else '2001:0db8::5/128')['id']
            except Duplicate:return None
        with ThreadPoolExecutor(max_workers=8) as pool:results=list(pool.map(attempt,range(16)))
        self.assertEqual(len([r for r in results if r]),1)
        def as_attempt(number):
            try:return Service(self.store).add_asn(ADMIN,'AS123' if number%2 else 123)['id']
            except Duplicate:return None
        with ThreadPoolExecutor(max_workers=8) as pool:results=list(pool.map(as_attempt,range(16)))
        self.assertEqual(len([r for r in results if r]),1)
        before=self.store.list('rule')
        with self.assertRaises(Conflict):self.service.import_manual(ADMIN,[{'value':'192.0.2.2','comment':'one'},{'value':'192.0.2.2/32','comment':'two'}])
        self.assertEqual(self.store.list('rule'),before)
        with self.assertRaises(Duplicate):self.service.import_manual(ADMIN,[{'value':'192.0.2.2','comment':''},{'value':'2001:db8::5','comment':''}])
        self.assertEqual(self.store.list('rule'),before)

    def test_database_update_and_replace_cannot_change_identity_to_duplicate(self):
        first=self.manual('192.0.2.1');second=self.manual('192.0.2.2')
        changed=deepcopy(second);changed['prefixes']=first['prefixes']
        with self.store.transaction() as db:
            for statement,args in [
                ("UPDATE documents SET body=? WHERE kind='rule' AND id=?",(encode(changed),second['id'])),
                ("INSERT OR REPLACE INTO documents VALUES('rule',?,?)",(second['id'],encode(changed)))]:
                with self.assertRaises(sqlite3.IntegrityError):db.execute(statement,args)
        self.assertEqual(self.store.get('rule',second['id']),second)

    def test_legacy_migration_replicates_preserves_updates_and_blocks_new(self):
        first=self.manual('192.0.2.1')
        old=deepcopy(first);old['id']=str(uuid.uuid4());old['comment']='Legacy independent reason'
        with self.store.transaction() as db:
            Store.set_meta(db,'role','slave')
            Store.operation(db,{'kind':'rule','id':old['id'],'doc':old})
            Store.set_meta(db,'role','master')
        restarted=Store(self.cfg);service=Service(restarted)
        self.assertEqual(len(restarted.list('rule')),2)
        service.update_comment(ADMIN,first['id'],'Updated comment')
        with self.assertRaises(Duplicate):service.add_manual(ADMIN,'192.0.2.1')
        with restarted.transaction() as db:
            duplicate=deepcopy(old);duplicate['id']=str(uuid.uuid4())
            with self.assertRaises(sqlite3.IntegrityError):db.execute('INSERT INTO documents VALUES(?,?,?)',('rule',duplicate['id'],encode(duplicate)))
        slave=Store(replace(self.cfg,database=str(Path(self.tmp.name)/'b.sqlite'),role='slave',node_id='b',peer_node_id='a'))
        slave.install_snapshot(restarted.snapshot())
        self.assertEqual(slave.list('rule'),restarted.list('rule'))
        service.delete_rule(ADMIN,first['id'])
        slave.apply_events(restarted.events(slave.info()['history'],slave.info()['sequence']))
        self.assertEqual(len(slave.list('rule')),1)
        with self.assertRaises(Duplicate):service.add_manual(ADMIN,'192.0.2.1')
        service.delete_rule(ADMIN,old['id']);service.add_manual(ADMIN,'192.0.2.1')

    def test_covering_containing_families_unique_rules_and_invalidation(self):
        for aggregate,host,subnet in [('192.0.2.0/24','192.0.2.1','192.0.2.0/25'),('2001:db8::/32','2001:db8::1','2001:db8::/48')]:
            small=self.manual(host);middle=self.manual(subnet);large=self.manual(aggregate)
            asrule=self.service.add_asn(ADMIN,64500 if ':' not in host else 64501)
            self.service.update_asn(ADMIN,asrule['id'],[aggregate,subnet])
            view=View(self.service);index=index_for(view)
            self.assertIs(index,index_for(View(self.service)))
            child=index.related(small['prefixes'][0],small['id'])
            self.assertEqual(child['manual'],{middle['id'],large['id']})
            self.assertEqual(child['asn'],{asrule['id']})
            parent=index.related(aggregate,large['id'])
            self.assertEqual(parent['contains'],{small['id'],middle['id'],asrule['id']})
            self.assertEqual(parent['asn'],{asrule['id']})
            middle_groups=index.related(subnet,middle['id'])
            self.assertTrue(middle_groups['manual']);self.assertTrue(middle_groups['contains'])
            self.service.delete_rule(ADMIN,large['id'])
            newer=index_for(View(self.service));self.assertIsNot(index,newer)
            self.assertNotIn(large['id'],newer.related(small['prefixes'][0],small['id'])['manual'])
            self.service.update_asn(ADMIN,asrule['id'],failed=True)
            # A failed refresh retains the previous successful coverage.
            self.assertIn(asrule['id'],index_for(View(self.service)).related(subnet,middle['id'])['asn'])
            self.service.delete_rule(ADMIN,asrule['id'])
            self.assertFalse(index_for(View(self.service)).related(subnet,middle['id'])['asn'])

    def test_successful_asn_replacement_and_local_protection_invalidate(self):
        child=self.manual('192.0.2.1')
        rule=self.service.add_asn(ADMIN,64500)
        self.service.update_asn(ADMIN,rule['id'],['192.0.2.0/24'])
        first=index_for(View(self.service))
        self.assertEqual(first.related('192.0.2.1/32',child['id'])['asn'],{rule['id']})
        result=self.service.update_asn(ADMIN,rule['id'],['198.51.100.0/24'])
        if result['pending']:
            self.service.confirm_asn(ADMIN,rule['id'],result['pending']['digest'])
        second=index_for(View(self.service));self.assertIsNot(first,second)
        self.assertFalse(second.related('192.0.2.1/32',child['id'])['asn'])
        parent=self.manual('192.0.2.0/24')
        third=index_for(View(self.service))
        self.store.set_local('protection',{'prefixes':['192.0.2.0/24'],'success':{}})
        fourth=index_for(View(self.service));self.assertIsNot(third,fourth)
        self.assertEqual(fourth.summary('192.0.2.1/32',child['id']),[])
        self.assertFalse(fourth.related('192.0.2.1/32',child['id'])['manual'])

    def test_protection_exclusion_and_revision(self):
        a=self.manual('192.0.2.0/24');b=self.manual('192.0.2.1')
        index=index_for(View(self.service))
        cfg=replace(self.cfg,protected_prefixes=('192.0.2.0/24',))
        service=Service(Store(cfg,activate=False))
        self.assertFalse(index_for(View(service)).related('192.0.2.1/32',b['id'])['manual'])
        self.assertTrue(index.related('192.0.2.1/32',b['id'])['manual'])
        self.assertEqual(paginate(list(range(26)),99,25)['page'],2)
        self.assertEqual(paginate([],99,25),{'items':[],'total':0,'page':1,'size':25})

if __name__=='__main__':unittest.main()
