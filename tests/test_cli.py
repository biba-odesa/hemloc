"""CLI service-layer tests. Root identity/UID switching are mocked explicitly."""

from contextlib import ExitStack, redirect_stderr, redirect_stdout
from dataclasses import replace
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from hemlock.auth import Auth
from hemlock.cli import main
from hemlock.config import Config
from hemlock.domain import Actor, Conflict, Invalid
from hemlock.service import Service
from hemlock.store import Store

HASH = '$argon2id$v=19$m=65536,t=3,p=4$fake$fake'
ADMIN = Actor('admin','admin')


class CLITests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = Config(tls=False,database=str(Path(self.tmp.name)/'a.sqlite'),node_id='a',peer_node_id='b')
        self.store = Store(self.cfg)
        self.service = Service(self.store)
        self.service.save_user(ADMIN,'admin',role='admin',password_hash=HASH)

    def tearDown(self):
        self.tmp.cleanup()

    def invoke(self, arguments, root=True, config=None, passwords=('new-test-password1','new-test-password1'), hasher=None):
        output, error = io.StringIO(), io.StringIO()
        with ExitStack() as stack:
            stack.enter_context(patch('hemlock.cli.load',return_value=config or self.cfg))
            stack.enter_context(patch('hemlock.cli.os.geteuid',return_value=0 if root else 1000))
            for method in ('setgroups','setgid','setuid'):
                stack.enter_context(patch('hemlock.cli.os.'+method))
            prompt = stack.enter_context(patch('hemlock.cli.getpass.getpass',side_effect=passwords))
            if hasher is not None:
                stack.enter_context(patch('hemlock.cli.password_hash',side_effect=hasher))
            stack.enter_context(redirect_stdout(output))
            stack.enter_context(redirect_stderr(error))
            result = main(arguments)
        return result, output.getvalue(), error.getvalue(), prompt.call_count

    def test_audit_preview_export_and_exact_plan_prune(self):
        import json,time,uuid
        from hemlock.store import encode
        event={'id':str(uuid.uuid4()),'at':time.time()-10*86400,'node':'a','actor':'anonymous','action':'http.request','object':'request','before':None,'after':None,'result':'invalid'}
        with self.store.transaction() as db:self.store.operation(db,{'kind':'audit','id':event['id'],'doc':event})
        plan=str(Path(self.tmp.name)/'plan.json');output=str(Path(self.tmp.name)/'export.jsonl')
        self.assertEqual(self.invoke(['audit','preview','--output',plan])[0],0)
        self.assertIsNotNone(self.store.get('audit',event['id']))
        self.assertEqual(self.invoke(['audit','export','--output',output])[0],0);self.assertFalse(Path(output).exists())
        self.assertEqual(self.invoke(['audit','export','--output',output,'--execute'])[0],0);self.assertTrue(Path(output).exists())
        self.assertEqual(self.invoke(['audit','prune','--plan',plan])[0],0);self.assertIsNotNone(self.store.get('audit',event['id']))
        self.assertEqual(self.invoke(['audit','prune','--plan',plan,'--execute'])[0],0);self.assertIsNone(self.store.get('audit',event['id']))

    def test_password_create_reset_lengths_and_composition(self):
        from hemlock.auth import password_verify
        for command, password in [(['user','create','policy-user','--role','admin'],'abcde1'),
                                  (['user','reset-password','policy-user'],'a'+'9'*1023)]:
            result, _, _, prompts = self.invoke(command,passwords=(password,password))
            self.assertEqual((result,prompts),(0,2))
            self.assertTrue(password_verify(self.store.get('user','policy-user')['password_hash'],password))
        saved = self.store.get('user','policy-user')
        for password in ('abcd1','a'+'9'*1024,'123456','abcdef','ABCDEF','!!!!!!'):
            for command in (['user','create','rejected','--role','admin'],['user','reset-password','policy-user']):
                result, _, error, prompts = self.invoke(command,passwords=(password,password))
                self.assertEqual((result,prompts),(1,2))
                self.assertIn('Password must contain',error)
                self.assertIsNone(self.store.get('user','rejected'))
                self.assertEqual(self.store.get('user','policy-user'),saved)

    def test_nonroot_cli_is_rejected_before_password_prompt(self):
        result, output, error, prompts = self.invoke(['user','list'],root=False)
        self.assertEqual(result,1)
        self.assertIn('requires root',error)
        self.assertEqual(prompts,0)

    def test_reset_changes_version_and_revokes_session_with_running_store(self):
        auth = Auth(self.store,lambda h,p:True)
        token,_ = auth.login('admin','old','client')
        old_version = self.store.get('user','admin')['version']
        result,output,error,prompts = self.invoke(['user','reset-password','admin'],hasher=lambda p:HASH)
        self.assertEqual((result,prompts),(0,2))
        self.assertEqual(self.store.get('user','admin')['version'],old_version+1)
        from hemlock.domain import Forbidden
        with self.assertRaises(Forbidden):
            auth.session(token)
        self.assertNotIn(HASH,output+error)
        self.assertNotIn('new-test-password1',output+error)

    def test_mismatch_is_audited_without_password_or_account_change(self):
        before = self.store.get('user','admin')
        result,output,error,prompts = self.invoke(['user','reset-password','admin'],passwords=('sentinel-one','sentinel-two'))
        self.assertEqual((result,prompts),(1,2))
        self.assertEqual(self.store.get('user','admin'),before)
        self.assertNotIn('sentinel',output+error+str(self.store.audit_history()))
        self.assertTrue(any(a['action']=='user.reset-password' and a['result']=='invalid' for a in self.store.audit_history()))

    def test_slave_reset_is_denied_without_prompt_and_only_local_audit(self):
        cfg = replace(self.cfg,role='slave')
        slave = Store(cfg)
        before = slave.info()
        result,output,error,prompts = self.invoke(['user','reset-password','admin'],config=cfg)
        self.assertEqual((result,prompts),(1,0))
        self.assertEqual(slave.info(),before)
        self.assertTrue(any(a['action']=='user.reset-password' and a['result']=='denied' for a in slave.audit_history()))

    def test_service_create_reset_and_password_races_are_checked_inside_transaction(self):
        with self.assertRaises(Conflict):
            self.service.save_user(ADMIN,'admin',password_hash=HASH,create_only=True)
        with self.assertRaises(Invalid):
            self.service.save_user(ADMIN,'missing',password_hash=HASH,require_existing=True)
        version = self.store.get('user','admin')['version']
        self.service.save_user(ADMIN,'admin',password_hash=HASH)
        with self.assertRaises(Conflict):
            self.service.save_user(ADMIN,'admin',password_hash=HASH,own=True,expected_version=version)

    @unittest.skipUnless(importlib.util.find_spec('argon2'),'Argon2 is unavailable; UID switching remains mocked in this test')
    def test_cli_reset_with_real_argon2(self):
        from hemlock.auth import password_verify
        result,_,_,prompts = self.invoke(['user','reset-password','admin'])
        self.assertEqual((result,prompts),(0,2))
        encoded = self.store.get('user','admin')['password_hash']
        self.assertTrue(password_verify(encoded,'new-test-password1'))
        self.assertFalse(password_verify(encoded,'wrong-test-password'))


if __name__ == '__main__':
    unittest.main()
