"""Canonical name and compatibility without changing deployed identities."""
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
    def test_legacy_imports_are_identical_and_launchers_use_canonical_name(self):
        for name in ('cli','domain','service','store','auth','replication','irr'):
            self.assertIs(importlib.import_module('hemloc.'+name),importlib.import_module('hemlock.'+name))
        for name in ('hemloc','hemlock'):
            result=subprocess.check_output([sys.executable,'-m',name,'--help'],text=True)
            self.assertTrue(result.startswith('usage: hemlock '))
        self.assertEqual(Config().database,'var/hemloc.sqlite')

    def test_only_fresh_success_with_zero_lag_is_healthy(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg=Config(tls=False,database=tmp+'/a.sqlite',peer_url='https://peer.invalid')
            store=Store(cfg);service=Service(store);now=time.time();info=store.info()
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
