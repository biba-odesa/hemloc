import unittest

from tools.check_artifacts import inspect_artifact


class ArtifactTests(unittest.TestCase):
    def test_runtime_and_secret_material_are_detected_without_echoing_content(self):
        for path in ['var/lab/a.ini','.venv/bin/python','state.sqlite-wal','state.db','ca.key','server.crt','peer.token','trace.log','__pycache__/a.pyc']:
            with self.subTest(path=path):
                self.assertIn('runtime-or-private-artifact',inspect_artifact(path,b''))
        secret = b'-----BEGIN ' + b'PRIVATE KEY-----\nnever echo this'
        findings = inspect_artifact('accidental.txt',secret)
        self.assertEqual(findings,['private-key-content'])
        self.assertNotIn('never echo this',str(findings))
        encoded = b'$argon2id$v=19$m=' + b'65536,t=3,p=4$abcdefghijklmno$abcdefghijklmnopqrstuvwxyz'
        self.assertEqual(inspect_artifact('accidental.txt',encoded),['password-hash-content'])

    def test_code_and_documentation_are_allowed(self):
        self.assertEqual(inspect_artifact('hemloc/auth.py',b'code'),[])
        self.assertEqual(inspect_artifact('docs/PLAN.md',b'status'),[])
        self.assertEqual(inspect_artifact('requirements.lock',b'package==1'),[])


if __name__ == '__main__':
    unittest.main()
