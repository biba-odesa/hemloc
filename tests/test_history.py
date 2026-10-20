"""Deleted secrets and commit messages remain in the publication history scan."""
from contextlib import contextmanager
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from tools.check_history import scan


class HistoryTests(unittest.TestCase):
    def test_deleted_file_and_commit_metadata_are_scanned(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            def git(*args):return subprocess.check_output(['git','-C',tmp,*args],stderr=subprocess.DEVNULL)
            git('init','-q');git('config','user.name','Fixture');git('config','user.email','fixture@example.invalid')
            (root/'retired.key').write_text('-----BEGIN '+'PRIVATE KEY-----\nSynthetic fixture only\n')
            git('add','.');git('commit','-qm','first fixture')
            (root/'retired.key').unlink();(root/'safe.txt').write_text('No secrets in the current tree.\n')
            credential=''.join(('https', '://', 'user', ':', 'synthetic-pass', '@', 'example.invalid'))
            git('add','-A');git('commit','-qm','credential URL fixture: '+credential)
            previous=Path.cwd()
            try:
                os.chdir(tmp);report,_=scan()
            finally:os.chdir(previous)
            categories={f['category'] for f in report['findings']}
            self.assertEqual(report['commits'],2)
            self.assertIn('private-key-content',categories)
            self.assertIn('runtime-or-private-artifact',categories)
            self.assertIn('credential-url',categories)
            self.assertTrue(any(f['path']=='retired.key' for f in report['findings']))
            self.assertTrue(any(f['path']=='<commit metadata/message>' for f in report['findings']))

if __name__=='__main__':unittest.main()
