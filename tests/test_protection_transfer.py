"""Read-only source export and locked monotonic offline protection import."""
from contextlib import ExitStack
from dataclasses import replace
from pathlib import Path
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from hemlock.config import Config
from hemlock.store import Store
from hemlock.transition import private_file
from hemlock.workers import process_lock
from tools.protection_transfer import main


class ProtectionTransferTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        root=Path(self.tmp.name)
        self.a=Config(tls=False,node_id='a',peer_node_id='b',database=str(root/'a.sqlite'),protected_asns=(64496,))
        self.b=replace(self.a,role='slave',node_id='b',peer_node_id='a',database=str(root/'b.sqlite'))
        self.source=Store(self.a);self.target=Store(self.b)
        self.source.set_local('protection',{'prefixes':['192.0.2.0/24'],'success':{'64496':100}})
        self.target.set_local('protection',{'prefixes':['203.0.113.0/24'],'success':{'64496':50}})
        self.file=root/'transfer.json'

    def invoke(self,operation,config):
        uid=os.geteuid()
        with ExitStack() as context:
            context.enter_context(patch('tools.protection_transfer.load',return_value=config))
            context.enter_context(patch('tools.protection_transfer.os.geteuid',return_value=0))
            for name in ('setgroups','setgid','setuid'):context.enter_context(patch('tools.protection_transfer.os.'+name))
            context.enter_context(patch('hemlock.transition.private_file',side_effect=lambda path:private_file(path,uid=uid)))
            main([operation,'--config','fixture','--file',str(self.file)])

    def test_export_read_only_and_import_union(self):
        before=self.source.snapshot()
        self.invoke('export',self.a)
        self.assertEqual(before,self.source.snapshot())
        self.assertEqual(self.file.stat().st_mode&0o777,0o600)
        self.invoke('import',self.b)
        self.assertEqual(self.target.local('protection'),{'prefixes':['192.0.2.0/24','203.0.113.0/24'],'success':{'64496':100}})
        self.assertEqual(self.target.list('rule'),[])
        self.invoke('import',self.b)
        self.assertEqual(len(self.target.local('protection')['prefixes']),2)
        with self.assertRaises(FileExistsError):self.invoke('export',self.a)

    def test_lock_digest_and_initialization_fail_closed(self):
        self.invoke('export',self.a)
        before=self.target.local('protection')
        with process_lock(self.b.database),self.assertRaises(Exception):self.invoke('import',self.b)
        envelope=json.loads(self.file.read_text());envelope['digest']='incorrect';self.file.write_text(json.dumps(envelope))
        with self.assertRaises(ValueError):self.invoke('import',self.b)
        self.assertEqual(before,self.target.local('protection'))
        self.file.unlink();self.source.set_local('protection',{'prefixes':['192.0.2.0/24'],'success':{}})
        with self.assertRaises(ValueError):self.invoke('export',self.a)
        self.assertFalse(self.file.exists())
