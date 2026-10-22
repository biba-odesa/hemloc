"""Pinned builder failures and environment boundaries with synthetic archives."""
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest

HANDLER=r'''#!/usr/bin/env python3
import json,os,pathlib,shutil,sys
name=pathlib.Path(sys.argv[0]).name;args=sys.argv[1:]
with open(os.environ['BUILD_TEST_LOG'],'a') as f:f.write(json.dumps([name,args,os.environ.get('https_proxy'),os.environ.get('GOPROXY')])+'\n')
if name=='curl':
    if os.environ.get('BUILD_TEST_FAIL')=='download':sys.exit(22)
    url=args[-1]
    src='source.tar.gz' if 'codeload.github.com' in url else 'go.tar.gz'
    shutil.copyfile(pathlib.Path(os.environ['BUILD_TEST_INPUT'])/src,args[args.index('--output')+1])
    if os.environ.get('BUILD_TEST_FAIL')=='checksum':pathlib.Path(args[args.index('--output')+1]).write_bytes(b'corrupt')
elif name=='git':
    if os.environ.get('BUILD_TEST_FAIL')=='patch':sys.exit(1)
elif name=='go':
    if args==['version']:print('go version go1.25.14 linux/amd64')
    elif args[0]=='build':
        if os.environ.get('BUILD_TEST_FAIL')=='compile':sys.exit(2)
        p=pathlib.Path(args[args.index('-o')+1]);p.write_text('#!/bin/sh\necho gobgpd version 4.10.0+hemlock-ibgp-ttl1\n');p.chmod(0o755)
'''


class GoBGPBuildTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.log=self.root/'calls';bin_dir=self.root/'bin';bin_dir.mkdir()
        handler=bin_dir/'handler';handler.write_text(HANDLER);handler.chmod(0o755)
        for name in ('curl','git'):(bin_dir/name).symlink_to(handler)
        def archive(name,entries):
            path=self.root/name
            with tarfile.open(path,'w:gz') as tar:
                for member,data,mode in entries:
                    info=tarfile.TarInfo(member);raw=data.encode();info.size=len(raw);info.mode=mode
                    tar.addfile(info,io.BytesIO(raw))
            return hashlib.sha256(path.read_bytes()).hexdigest()
        source_sha=archive('source.tar.gz',[('gobgp-4.10.0/LICENSE','Fixture license',0o644)])
        go_sha=archive('go.tar.gz',[('go/bin/go',HANDLER,0o755)])
        deploy=self.root/'deploy';(deploy/'patches').mkdir(parents=True)
        (deploy/'patches/gobgp-4.10.0-ibgp-ttl.patch').write_text('fixture patch')
        text=Path('deploy/build-gobgp.sh').read_text().replace('27d8ef958100557344be98e459fa43a20d2a15b5ce943d2aed2772958a3bf397',source_sha).replace('a21ae5633a269bcd7e90cf767e48225633795e99d831742cbf3397064fee7712',go_sha)
        self.script=deploy/'build-gobgp.sh';self.script.write_text(text)
        self.output=self.root/'output'
        self.env=dict(os.environ,PATH=str(bin_dir)+':'+os.environ['PATH'],BUILD_TEST_LOG=str(self.log),BUILD_TEST_INPUT=str(self.root))

    def run_build(self,failure=None,proxy=None):
        args=['bash',str(self.script),'--output',str(self.output)]
        if proxy:args+=['--proxy',proxy]
        return subprocess.run(args,capture_output=True,text=True,env=self.env|({'BUILD_TEST_FAIL':failure} if failure else {}))

    def calls(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def test_pins_patch_direct_downloads_and_offline_compile(self):
        result=self.run_build();self.assertEqual(result.returncode,0,result.stderr)
        calls=self.calls();self.assertEqual(len([c for c in calls if c[0]=='curl']),2)
        self.assertTrue(all(c[2] is None for c in calls))
        self.assertEqual([c[1][0] for c in calls if c[0]=='git'],['apply','apply'])
        self.assertEqual([c[3] for c in calls if c[0]=='go'],[None,'https://proxy.golang.org','off','off'])
        report=json.loads((self.output/'build-report.json').read_text())
        self.assertEqual(report['binary_sha256'],hashlib.sha256((self.output/'gobgpd').read_bytes()).hexdigest())
        self.assertEqual(report['gobgp_version'],'4.10.0+hemlock-ibgp-ttl1')
        self.assertTrue((self.output/'LICENSE.GoBGP').exists())

    def test_explicit_proxy(self):
        result=self.run_build(proxy='http://proxy.example.invalid:3128');self.assertEqual(result.returncode,0,result.stderr)
        self.assertTrue(all(c[2]=='http://proxy.example.invalid:3128' for c in self.calls()))

    def test_download_failure_never_executes_source(self):
        self.assertNotEqual(self.run_build('download').returncode,0)
        self.assertFalse(any(c[0] in ('git','go') for c in self.calls()));self.assertFalse(self.output.exists())

    def test_checksum_failure_never_executes_source(self):
        self.assertNotEqual(self.run_build('checksum').returncode,0)
        self.assertFalse(any(c[0] in ('git','go') for c in self.calls()));self.assertFalse(self.output.exists())

    def test_patch_failure_never_compiles(self):
        self.assertNotEqual(self.run_build('patch').returncode,0)
        self.assertFalse(any(c[0]=='go' and c[1][0]=='build' for c in self.calls()));self.assertFalse(self.output.exists())

    def test_build_failure_no_output(self):
        self.assertNotEqual(self.run_build('compile').returncode,0);self.assertFalse(self.output.exists())

    def test_existing_output_is_not_overwritten(self):
        self.output.mkdir();sentinel=self.output/'keep';sentinel.write_text('keep')
        self.assertNotEqual(self.run_build().returncode,0);self.assertEqual(sentinel.read_text(),'keep');self.assertEqual(self.calls(),[])
