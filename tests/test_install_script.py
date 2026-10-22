"""Installer command contract in a private fake root; no host install/services."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


HANDLER = r'''#!/usr/bin/env python3
import json,os,pathlib,shutil,subprocess,sys
name=pathlib.Path(sys.argv[0]).name
args=sys.argv[1:]
with open(os.environ['INSTALL_LOG'],'a') as log:
    log.write(json.dumps([name,args,bool(os.environ.get('https_proxy'))])+'\n')
if name=='git':
    if args[0]=='clone':shutil.copytree(os.environ['INSTALL_SOURCE'],args[-1])
    if 'rev-parse' in args:print('a'*40)
elif name=='getent':sys.exit(2)
elif name=='builder.py':
    if os.environ.get('INSTALL_FAIL')=='build':sys.exit(5)
    target=pathlib.Path(args[args.index('--output')+1]);target.mkdir()
    shutil.copy2(os.environ['INSTALL_BINARY'],target/'gobgpd')
    (target/'build-report.json').write_text('{"fixture":true}')
elif name=='install':
    filtered=[];i=0
    while i<len(args):
        if args[i] in ('-o','-g'):i+=2
        else:filtered.append(args[i]);i+=1
    sys.exit(subprocess.call(['/usr/bin/install',*filtered]))
elif name in ('python3.13','python'):
    if args[:2]==['-m','venv']:
        target=pathlib.Path(args[2])/'bin';target.mkdir(parents=True)
        (target/'python').symlink_to(pathlib.Path(sys.argv[0]).resolve())
    elif args==['-']:
        sys.exit(subprocess.call([os.environ['INSTALL_PYTHON'],'-'],stdin=sys.stdin))
    elif args[:2]==['-m','pip']:
        if os.environ.get('INSTALL_FAIL')=='pip':sys.exit(4)
'''


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.log=self.root/'commands.log'
        self.fake=self.root/'root'
        for path in ('opt','etc/systemd/system','usr/local/bin','usr/local/share','usr/lib/systemd/system','var/lib'):
            (self.fake/path).mkdir(parents=True,exist_ok=True)
        (self.fake/'etc/os-release').write_text('ID=debian\nVERSION_ID=13\nVERSION="13 (trixie)"\n')
        self.source=self.root/'source';self.source.mkdir()
        for name in ('deploy','hemlock'):
            shutil.copytree(name,self.source/name,ignore=shutil.ignore_patterns('__pycache__'))
        shutil.copy2('pyproject.toml',self.source/'pyproject.toml')
        bin_dir=self.root/'bin';bin_dir.mkdir()
        handler=bin_dir/'handler';handler.write_text(HANDLER);handler.chmod(0o755)
        for name in ('git','apt-get','useradd','getent','chown','systemctl','install','python3.13'):
            (bin_dir/name).symlink_to(handler)
        self.binary=self.root/'verified-gobgpd';self.binary.write_text('#!/bin/sh\necho gobgpd version 4.10.0+hemlock-ibgp-ttl1\n');self.binary.chmod(0o755)
        builder=self.root/'builder.py';builder.write_text(HANDLER)
        (self.source/'deploy/build-gobgp.sh').write_text('#!/bin/bash\nexec "$INSTALL_PYTHON" "$INSTALL_BUILD_HANDLER" "$@"\n')
        self.sha=hashlib.sha256(self.binary.read_bytes()).hexdigest()
        body=Path('deploy/install-debian13.sh').read_text()
        for prefix in ('/opt/','/etc/','/var/lib/','/usr/local/','/usr/lib/systemd/'):
            body=body.replace(prefix,str(self.fake)+prefix)
        body=body.replace('df -Pk /opt','df -Pk '+str(self.fake/'opt'))
        body=body.replace('[[ $EUID == 0 ]]','[[ 0 == 0 ]]')
        self.script=self.root/'install.sh';self.script.write_text(body)
        self.env=dict(os.environ,PATH=str(bin_dir)+':'+os.environ['PATH'],INSTALL_LOG=str(self.log),INSTALL_SOURCE=str(self.source),INSTALL_PYTHON=sys.executable,INSTALL_BUILD_HANDLER=str(builder),INSTALL_BINARY=str(self.binary))

    def run_installer(self,role='master',extra=(),failure=None,prebuilt=True):
        args=['--role',role,'--version','a'*40,'--expected-commit','a'*40,'--node-id','fixture-a','--peer-node-id','fixture-b','--owner','64512,100,1',*(['--gobgp-binary',str(self.binary),'--gobgp-sha256',self.sha] if prebuilt else []),*extra]
        env=self.env|({'INSTALL_FAIL':failure} if failure else {})
        return subprocess.run(['bash',str(self.script),*args],capture_output=True,text=True,env=env)

    def commands(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def test_master_install_no_secrets_db_admin_or_service_start(self):
        result=self.run_installer();self.assertEqual(result.returncode,0,result.stderr)
        commands=self.commands();names=[name for name,args,proxy in commands]
        self.assertLess(names.index('apt-get'),names.index('git'))
        self.assertEqual([args for name,args,proxy in commands if name=='systemctl'],[['daemon-reload']])
        config=(self.fake/'etc/hemlock/hemlock.ini').read_text()
        for value in ('role = master','node_id = fixture-a','owner = 64512,100,1','announcements = no','next_hop =\n','protected_asns = \n','tls = yes'):
            self.assertIn(value,config)
        self.assertEqual((self.fake/'etc/hemlock/hemlock.ini').stat().st_mode&0o777,0o640)
        self.assertEqual(list((self.fake/'var/lib/hemlock').iterdir()),[])
        self.assertFalse((self.fake/'etc/hemlock/replication.token').exists())
        self.assertFalse((self.fake/'etc/gobgp/gobgpd.toml').exists())
        self.assertIn('No services enabled or started',result.stdout)
        # Existing environment proxies are explicitly ignored without --proxy.
        self.assertFalse(any(proxy for name,args,proxy in commands if name=='apt-get'))

    def test_slave_and_explicit_download_proxy(self):
        result=self.run_installer('slave',('--proxy','http://proxy.example.invalid:3128'))
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('role = slave',(self.fake/'etc/hemlock/hemlock.ini').read_text())
        self.assertTrue(all(proxy for name,args,proxy in self.commands() if name=='apt-get'))
        self.assertFalse(any('user' in args and 'create' in args for name,args,proxy in self.commands()))

    def test_existing_installation_is_not_touched(self):
        path=self.fake/'etc/hemlock';path.mkdir();(path/'keep').write_text('sentinel')
        result=self.run_installer();self.assertNotEqual(result.returncode,0)
        self.assertEqual((path/'keep').read_text(),'sentinel')
        self.assertFalse(any(name=='apt-get' for name,args,proxy in self.commands()))

    def test_check_does_not_install_and_checksum_or_proxy_errors_fail_early(self):
        result=self.run_installer(extra=('--check',));self.assertEqual(result.returncode,0,result.stderr)
        self.assertFalse(any(name in ('apt-get','useradd','systemctl') for name,args,proxy in self.commands()))
        self.assertNotEqual(self.run_installer(extra=('--proxy','{}://user:secret@proxy.invalid:3128'.format('http'))).returncode,0)
        self.assertNotEqual(self.run_installer(extra=('--gobgp-sha256','0'*64)).returncode,0)

    def test_dependency_failure_never_creates_users_config_or_starts_services(self):
        result=self.run_installer(failure='pip');self.assertNotEqual(result.returncode,0)
        self.assertIn('Installation failed',result.stderr)
        self.assertFalse(any(name in ('useradd','systemctl') for name,args,proxy in self.commands()))
        self.assertFalse((self.fake/'etc/hemlock').exists())

    def test_default_build_and_failure_before_users(self):
        result=self.run_installer(prebuilt=False)
        self.assertEqual(result.returncode,0,result.stderr)
        builds=[args for name,args,proxy in self.commands() if name=='builder.py']
        self.assertEqual(len(builds),1)
        self.assertTrue((self.fake/'usr/local/share/hemlock/gobgp-build.json').exists())

    def test_default_build_failure_starts_nothing(self):
        result=self.run_installer(prebuilt=False,failure='build')
        self.assertNotEqual(result.returncode,0)
        self.assertFalse(any(name in ('useradd','systemctl') for name,args,proxy in self.commands()))
        self.assertFalse((self.fake/'etc/hemlock').exists())

    def test_default_preflight_needs_no_binary_or_download(self):
        result=self.run_installer(prebuilt=False,extra=('--check',))
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertFalse(any(name in ('apt-get','builder.py','git') for name,args,proxy in self.commands()))
