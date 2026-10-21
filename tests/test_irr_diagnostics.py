"""Protection diagnostics preserve actionable fields without subprocess text."""
from dataclasses import replace
from pathlib import Path
import logging
import sys
import tempfile
import unittest
from unittest.mock import patch

from hemlock.config import Config
from hemlock.irr import IRR, IRRError, bounded_process, failure_details
from hemlock.service import Service
from hemlock.store import Store
from hemlock.workers import ProtectionWorker

LOGGER = 'uvicorn.error.protection'


class ProtectionDiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.config = Config(tls=False, database=str(Path(self.directory.name)/'db.sqlite'))
        self.store = Store(self.config)
        self.service = Service(self.store)
        self.service.grow_protection(64496, ['192.0.2.0/24'])

    def test_failure_is_logged_without_exception_text(self):
        class Broken:
            def expand(self, number):
                raise IRRError('SENSITIVE_FIXTURE_VALUE')
        old = self.store.local('protection')
        with self.assertLogs(LOGGER, logging.WARNING) as records:
            ProtectionWorker(self.service, Broken()).step()
        output = '\n'.join(records.output)
        self.assertIn('asn=64496', output)
        self.assertIn('type=resolver', output)
        self.assertIn('family=combined', output)
        self.assertNotIn('SENSITIVE_FIXTURE_VALUE', output)
        self.assertEqual(self.store.local('protection'), old)

    def test_persisted_retry_and_success_clears_error_without_shrinking(self):
        class Resolver:
            calls = 0
            def expand(self, number):
                self.calls += 1
                if self.calls == 1:
                    raise IRRError('upstream failed')
                return ['198.51.100.0/24']
        resolver = Resolver()
        with patch('hemlock.workers.time.time', return_value=10000):
            with self.assertLogs(LOGGER, logging.WARNING):
                ProtectionWorker(self.service, resolver).step()
        self.assertEqual(self.store.local('protection_schedule')['64496']['next'],13600)
        restarted = Service(Store(self.config))
        with patch('hemlock.workers.time.time', return_value=10001):
            ProtectionWorker(restarted, resolver).step()
        self.assertEqual(resolver.calls, 1)
        with patch('hemlock.workers.time.time', return_value=13600):
            with self.assertLogs(LOGGER, logging.INFO):
                ProtectionWorker(restarted, resolver).step()
        state = self.store.local('protection_schedule')['64496']
        self.assertEqual(state['error'], '')
        self.assertNotIn('diagnostic', state)
        self.assertEqual(state['next'],13600+30*86400)
        self.assertEqual(set(self.store.local('protection')['prefixes']),{'192.0.2.0/24','198.51.100.0/24'})

    def test_real_process_failure_context_and_redaction(self):
        def runner(args, timeout):
            if '-4' in args:
                return b'192.0.2.0/24\n'
            return bounded_process([sys.executable, '-c',
                'import sys; sys.stderr.write("ERROR: Connection refused SENSITIVE_FIXTURE_VALUE"); sys.exit(7)'], timeout)
        with self.assertRaises(IRRError) as caught:
            IRR(self.config, runner).expand(64496)
        detail = failure_details(caught.exception)
        self.assertEqual((detail['family'], detail['exit_code'], detail['category']),(6,7,'exit'))
        self.assertEqual(detail['detail'],'connection_refused')
        self.assertNotIn('SENSITIVE_FIXTURE_VALUE',str(caught.exception))
        class Broken:
            def expand(inner, number):
                return IRR(self.config, runner).expand(number)
        with self.assertLogs(LOGGER, logging.WARNING) as log:
            ProtectionWorker(self.service, Broken()).step()
        self.assertIn('family=6', '\n'.join(log.output))
        self.assertIn('exit_code=7', '\n'.join(log.output))
        self.assertNotIn('SENSITIVE_FIXTURE_VALUE','\n'.join(log.output))

    def test_timeout_os_parse_wrong_family_and_empty_are_classified(self):
        with self.assertRaises(IRRError) as caught:
            IRR(self.config, lambda args,t: bounded_process(
                [sys.executable,'-c','import time; time.sleep(5)'],0.03)).expand(64496)
        self.assertEqual(failure_details(caught.exception)['category'],'timeout')
        self.assertTrue(caught.exception.timed_out)
        self.assertEqual(caught.exception.family,4)
        with self.assertRaises(IRRError) as caught:
            IRR(replace(self.config,irr_command='/missing-fixture/bgpq4')).expand(64496)
        self.assertEqual((caught.exception.category,caught.exception.os_errno),('os_error',2))
        for value,category in ((b'bad response','invalid_output'),(b'2001:db8::/32','family_mismatch')):
            with self.assertRaises(IRRError) as caught:
                IRR(self.config, lambda a,t: value).expand(64496)
            self.assertEqual((caught.exception.category,caught.exception.family),(category,4))
        class Empty:
            def expand(self, number):return []
        old = self.store.local('protection')
        with self.assertLogs(LOGGER, logging.WARNING) as log:
            ProtectionWorker(self.service, Empty()).step()
        self.assertIn('type=empty','\n'.join(log.output))
        self.assertEqual(self.store.local('protection'),old)

    def test_one_empty_family_is_valid_and_zero_exit_errors_are_not_success(self):
        for empty in ('-4','-6'):
            result = IRR(self.config,lambda a,t: b'' if empty in a else (
                b'192.0.2.0/24\n' if '-4' in a else b'2001:db8::/32\n')).expand(64496)
            self.assertEqual(len(result),1)
        with self.assertRaises(IRRError) as caught:
            bounded_process([sys.executable,'-c','import sys; sys.stderr.write("FATAL: SENSITIVE_FIXTURE_VALUE")'],1)
        self.assertEqual((caught.exception.category,caught.exception.exit_code),('utility_error',0))

    def test_read_only_probe_never_emits_subprocess_or_exception_text(self):
        from tools.diagnose_irr import probe
        class Resolver:
            def __init__(self, config, runner):self.runner=runner
            def expand(self, number):
                return self.runner([sys.executable,'-c',
                    'import sys; sys.stderr.write("Connection refused SENSITIVE_FIXTURE_VALUE"); sys.exit(9)',
                    '-6'],1)
        with patch('tools.diagnose_irr.IRR',Resolver):
            result=probe(self.config,64496)
        self.assertFalse(result['ok'])
        self.assertEqual(result['families'][0]['exit_code'],9)
        self.assertEqual(result['families'][0]['stderr_hint'],'connection_refused')
        self.assertNotIn('SENSITIVE_FIXTURE_VALUE',str(result))
        self.assertNotIn('Connection refused',str(result))


if __name__ == '__main__':
    unittest.main()
