"""Absence requires independent local evidence; RPC failure alone is never enough."""
from dataclasses import replace
from pathlib import Path
import socket
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock
from hemlock.config import Config
from hemlock.gobgp_presence import confirmed_absent


class PresenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.proc=Path(self.tmp.name);(self.proc/'self').mkdir();(self.proc/'1').mkdir()
        (self.proc/'self/mountinfo').write_text('22 1 0:1 / /proc rw,nosuid - proc proc rw\n')
        (self.proc/'1/comm').write_text('systemd\n')
        self.cfg=Config(tls=False,grpc_target='127.0.0.1:54444')
        self.status='LoadState=loaded\nActiveState=inactive\nSubState=dead\nMainPID=0\nControlPID=0\n'
        self.run=Mock(side_effect=lambda *a,**k:SimpleNamespace(returncode=0,stdout=self.status.encode()))
        self.connect=Mock(side_effect=ConnectionRefusedError())

    def probe(self):return confirmed_absent(self.cfg,proc=self.proc,run=self.run,connect=self.connect)

    def test_loaded_stopped_unit_visible_proc_and_refused_port(self):
        self.assertTrue(self.probe())
        args=self.run.call_args.args[0]
        self.assertEqual(args[:3],['/usr/bin/systemctl','show','gobgp.service'])
        self.assertNotIn('sudo',args)
        self.assertEqual(self.run.call_args.kwargs['timeout'],2)

    def test_active_unknown_failed_or_unloaded_unit_is_not_absence(self):
        for status in [self.status.replace('inactive','active'),self.status.replace('dead','auto-restart'),self.status.replace('MainPID=0','MainPID=99'),self.status.replace('loaded','not-found'),self.status.replace('inactive','failed')]:
            with self.subTest(status=status):
                self.status=status
                self.assertFalse(self.probe())
        self.run.side_effect=subprocess.TimeoutExpired('systemctl',2)
        self.assertFalse(self.probe())

    def test_other_daemon_restricted_proc_or_unknown_pid_namespace(self):
        (self.proc/'8').mkdir();(self.proc/'8/comm').write_text('gobgpd\n')
        self.assertFalse(self.probe());(self.proc/'8/comm').write_text('python\n')
        (self.proc/'self/mountinfo').write_text('22 1 0:1 / /proc rw - proc proc rw,hidepid=2\n')
        self.assertFalse(self.probe())
        (self.proc/'self/mountinfo').write_text('22 1 0:1 / /proc rw - proc proc rw\n')
        (self.proc/'1/comm').write_text('python\n');self.assertFalse(self.probe())

    def test_listening_timeout_permission_or_unreachable_port_is_not_absence(self):
        connection=Mock();self.connect.side_effect=None;self.connect.return_value=connection
        self.assertFalse(self.probe());connection.close.assert_called_once()
        for error in (TimeoutError(),PermissionError(),OSError('unreachable')):
            self.connect.side_effect=error;self.assertFalse(self.probe())


if __name__=='__main__':unittest.main()
