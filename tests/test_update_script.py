"""Updater order and failure handling with fake commands, never production."""
import io
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest

HANDLER=r'''#!/usr/bin/env python3
import json,os,pathlib,sys
name=pathlib.Path(sys.argv[0]).name;args=sys.argv[1:];failure=os.environ['UPDATE_FAIL']
with open(os.environ['UPDATE_LOG'],'a') as log:log.write(json.dumps([name,args])+'\n')
if name=='git':
    if args[:1]==['rev-parse']:print('a'*40)
    if args[:1]==['archive']:
        if failure=='archive':sys.exit(3)
        sys.stdout.buffer.write(pathlib.Path(os.environ['UPDATE_ARCHIVE']).read_bytes())
if name=='systemctl' and args[:1]==['show']:print('hemlock')
if name=='python':
    if args==['-I','-']:
        sys.stdin.read()
        if failure=='preflight':sys.exit(4)
    if 'wheel' in args:
        if failure=='build':sys.exit(5)
        directory=pathlib.Path(args[args.index('--wheel-dir')+1]);directory.mkdir();(directory/'hemlock-test.whl').touch()
    if 'backup' in args and failure=='backup':sys.exit(6)
'''


class UpdateScriptTests(unittest.TestCase):
    def test_success_and_preflight_archive_build_backup_failures(self):
        for failure in ('none','preflight','archive','build','backup'):
            with self.subTest(failure=failure),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);bin_dir=root/'bin';bin_dir.mkdir();stages=root/'stages';stages.mkdir()
                handler=bin_dir/'handler';handler.write_text(HANDLER);handler.chmod(0o755)
                for name in ('git','python','systemctl'):(bin_dir/name).symlink_to(handler)
                archive=root/'source.tar'
                with tarfile.open(archive,'w') as out:
                    for name in ('requirements.lock','requirements-build.lock'):
                        entry=tarfile.TarInfo(name);entry.size=0;out.addfile(entry,io.BytesIO())
                script=root/'update.sh';script.write_text(Path('update.sh').read_text().replace('/opt/hemlock/.venv/bin/',str(bin_dir)+'/').replace('/var/tmp/hemlock-update.',str(stages)+'/update.').replace('[[ $EUID == 0 ]]','[[ 0 == 0 ]]'))
                log=root/'commands'
                env=dict(os.environ,PATH=str(bin_dir)+':'+os.environ['PATH'],UPDATE_LOG=str(log),UPDATE_ARCHIVE=str(archive),UPDATE_FAIL=failure)
                result=subprocess.run(['bash',str(script)],env=env,capture_output=True,text=True)
                commands=[json.loads(line) for line in log.read_text().splitlines()]
                services=[args for name,args in commands if name=='systemctl']
                self.assertFalse(any('gobgp' in arg for name,args in commands for arg in args))
                if failure=='none':
                    self.assertEqual(result.returncode,0,result.stderr)
                    stop=commands.index(['systemctl',['stop','hemlock.service']])
                    start=commands.index(['systemctl',['start','hemlock.service']])
                    backup=next(i for i,(name,args) in enumerate(commands) if 'backup' in args)
                    self.assertLess(stop,backup);self.assertLess(backup,start)
                    self.assertIn(['git',['rev-parse','--verify','FETCH_HEAD^{commit}']],commands)
                else:
                    self.assertNotEqual(result.returncode,0)
                    self.assertNotIn(['start','hemlock.service'],services)
                    if failure!='backup':self.assertNotIn(['stop','hemlock.service'],services)
