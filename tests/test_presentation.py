"""Presentation distinguishes intent, actual ownership, stale data and provenance."""
from dataclasses import replace
from pathlib import Path
import tempfile
import time
import unittest
from hemloc.config import Config
from hemloc.domain import Actor
from hemloc.service import Service
from hemloc.store import Store
from hemloc.presentation import View, history_card


class PresentationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.cfg=Config(database=str(Path(self.tmp.name)/'a.sqlite'),tls=False,protected_asns=(),protected_prefixes=(),
                        announcements=True,v6_next_hop='2001:db8::1',node_id='hemloc-a',peer_node_id='hemloc-b')
        self.store=Store(self.cfg);self.service=Service(self.store);actor=Actor('operator','admin')
        for value,comment in [('192.0.2.0/24','network'),('192.0.2.1','reason one'),('2001:db8::9','v6')]:
            self.service.add_manual(actor,value,comment)
        second=self.service.add_asn(actor,64501,'reason two')
        self.service.update_asn(actor,second['id'],['192.0.2.1/32'])
        self.cfg=replace(self.cfg,protected_prefixes=('192.0.2.1/32',))
        self.service=Service(Store(self.cfg,activate=False))
        self.now=time.time()
        self.paths=[self.path('192.0.2.0/24'),self.path('192.0.2.0/24'),self.path('192.0.2.1/32'),self.path('2001:db8::9/128',99)]
        self.rib={'at':self.now,'paths':self.paths,'peers':[
            {'address':'192.0.2.10','description':'Peer One','session_state':6,'admin_state':1,'established_at':self.now-70},
            {'address':'192.0.2.11','description':'','session_state':3,'admin_state':1},
            {'address':'192.0.2.12','description':'Disabled peer','session_state':1,'admin_state':2}],
            'export':{'192.0.2.10':{'prefixes':['192.0.2.0/24','192.0.2.0/24']},'192.0.2.11':{'prefixes':[]}}}
        self.store.set_local('rib',self.rib)

    def tearDown(self):self.tmp.cleanup()

    def path(self,candidate,pref=200):
        return {'prefix':candidate,'local':True,'owner':list(self.cfg.owner),'local_pref':pref,
                'next_hop':self.cfg.v6_next_hop if ':' in candidate else self.cfg.v4_next_hop,'communities':[self.cfg.community]}

    def test_unique_actual_counts_pending_failed_and_unique_exclusions(self):
        view=View(self.service, self.now)
        summary=view.dashboard()
        self.assertEqual(summary['blocked'],{'ipv4':1,'ipv6':0,'total':1})
        self.assertEqual(summary['required']['total'],2)
        self.assertEqual((summary['pending'],summary['failed'],summary['excluded']),(2,0,1))
        self.store.set_local('bgp',{'error':'GoBGP inspection or reconciliation failed'})
        summary=View(self.service,self.now).dashboard()
        self.assertEqual((summary['pending'],summary['failed']),(1,1))

    def test_all_reason_ip_search_and_bounded_page_detail(self):
        view=View(self.service,self.now)
        page=view.route_page(ip='192.0.2.1',size=1)
        self.assertEqual((page['total'],len(page['items'])),(2,1))
        item=view.detail('192.0.2.1')
        self.assertEqual({s['comment'] for s in item['sources']},{'reason one','reason two'})
        self.assertEqual(item['state'],'Excluded by protection')
        self.assertTrue(item['local_rib'])
        self.assertEqual(view.detail('192.0.2.0/24')['exports'][0]['state'],'Exported')
        self.assertEqual(view.detail('192.0.2.0/24')['exports'][1]['state'],'Unknown')
        self.assertEqual(view.route_page(ip='198.51.100.1')['total'],0)

    def test_stale_and_failed_observation_never_become_zero_or_applied(self):
        summary=View(self.service,self.now+46).dashboard()
        self.assertIsNone(summary['blocked'])
        self.assertEqual(summary['peers'][0]['status'],'Stale')
        self.assertIsNone(summary['peers'][0]['ipv4_advertised'])
        self.store.set_local('worker:observation',{'at':self.now+1,'error':'Background operation failed'})
        view=View(self.service,self.now+2)
        self.assertIsNone(view.dashboard()['blocked'])
        self.assertIsNone(view.detail('192.0.2.0/24')['local_rib'])
        self.assertEqual(view.route_state('192.0.2.0/24'),'Unknown')

    def test_peer_counts_fallback_uptime_and_truncation(self):
        peers=View(self.service,self.now).peers()
        self.assertEqual(peers[0]['ipv4_advertised'],1)
        self.assertEqual(peers[0]['uptime_seconds'],70)
        self.assertEqual(peers[1]['peer'],'192.0.2.11')
        self.assertIsNone(peers[1]['ipv4_advertised'])
        self.assertEqual(peers[2]['status'],'Disabled')
        self.rib['export']['192.0.2.10']['truncated']=True
        self.store.set_local('rib',self.rib)
        view=View(self.service,self.now)
        self.assertIsNone(view.peers()[0]['ipv4_advertised'])
        self.assertEqual(view.detail('2001:db8::9/128')['exports'][0]['state'],'Unknown')

    def test_replication_absence_failure_lag_and_history(self):
        self.assertEqual(View(self.service,self.now).dashboard()['peer']['status'],'Not configured')
        service=Service(Store(replace(self.cfg,peer_url='https://peer.invalid'),activate=False))
        info=self.store.info()
        self.store.set_local('peer',{'at':self.now,'status':{'history':info['history'],'sequence':info['sequence']-2}})
        self.store.set_local('sync',{'ok':True,'at':self.now,'last_success':self.now})
        self.assertEqual(View(service,self.now).dashboard()['peer']['lag'],2)
        self.store.set_local('worker:replication',{'at':self.now+1,'error':'Background operation failed'})
        self.assertIn('unavailable',View(service,self.now+2).dashboard()['peer']['status'].lower())
        self.store.set_local('sync',{'ok':False,'at':self.now+1,'last_success':self.now})
        result=View(service,self.now+2).dashboard()['peer']
        self.assertIn('unavailable',result['status'].lower())
        self.assertEqual(result['last_success'],self.now)
        self.assertIsNone(result['lag'])
        card=history_card(self.store.audit_history()[0])
        self.assertNotIn('id',card)
        self.assertTrue(card['changes'])
