"""Canonical packaging identity and replication presentation."""
from dataclasses import replace
import importlib
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from hemlock.config import Config
from hemlock.presentation import View
from hemlock.service import Service
from hemlock.store import Store


class BrandingTests(unittest.TestCase):
    def test_canonical_launcher_and_defaults(self):
        result=subprocess.check_output([sys.executable,'-m','hemlock','--help'],text=True)
        self.assertTrue(result.startswith('usage: hemlock '))
        self.assertEqual(Config().database,'/var/lib/hemlock/hemlock.sqlite')

    def test_only_fresh_success_with_zero_lag_is_healthy(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg=Config(tls=False,database=tmp+'/a.sqlite',peer_url='https://peer.invalid')
            store=Store(cfg);service=Service(store);now=time.time();info=store.info()
            store.set_local('peer_compatibility',{'ok':True,'at':now,'local_protocol_version':3,'peer_protocol_version':3})
            store.set_local('sync',{'ok':True,'at':now,'last_success':now})
            store.set_local('peer',{'at':now,'status':{'history':info['history'],'sequence':info['sequence']}})
            self.assertTrue(View(service,now).dashboard()['peer']['healthy'])
            self.assertFalse(View(service,now+60).dashboard()['peer']['healthy'])
            store.set_local('peer',{'at':now,'status':{'history':'other','sequence':info['sequence']}})
            self.assertFalse(View(service,now).dashboard()['peer']['healthy'])
            store.set_local('sync',{'ok':False,'at':now,'last_success':now})
            self.assertFalse(View(service,now).dashboard()['peer']['healthy'])
            store.set_local('sync',{'ok':False,'at':now,'code':'two_masters'})
            self.assertFalse(View(service,now).dashboard()['peer']['healthy'])
