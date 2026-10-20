"""Build twice from independent Git exports; never install or run a service."""
import argparse
import gzip
import hashlib
from importlib.metadata import version
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import zipfile

SOURCE_SHA='27d8ef958100557344be98e459fa43a20d2a15b5ce943d2aed2772958a3bf397'
GO_SHA='a21ae5633a269bcd7e90cf767e48225633795e99d831742cbf3397064fee7712'


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def run(args,**kwargs):return subprocess.run(args,check=True,**kwargs)


def extract(source,destination):
    with tarfile.open(source) as archive:archive.extractall(destination,filter='data')


def deterministic_sdist(path,epoch):
    with tarfile.open(path) as archive:
        members=[]
        for entry in archive.getmembers():
            data=archive.extractfile(entry).read() if entry.isfile() else None
            entry.mtime=epoch;entry.uid=entry.gid=0;entry.uname=entry.gname='';entry.pax_headers={}
            members.append((entry,data))
    buffer=io.BytesIO()
    with tarfile.open(fileobj=buffer,mode='w',format=tarfile.PAX_FORMAT) as archive:
        for entry,data in sorted(members,key=lambda item:item[0].name):archive.addfile(entry,io.BytesIO(data) if data is not None else None)
    path.write_bytes(gzip.compress(buffer.getvalue(),mtime=0))


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',required=True);parser.add_argument('--ref',default='HEAD');parser.add_argument('--epoch',type=int)
    parser.add_argument('--gobgp-source',type=Path);parser.add_argument('--go-archive',type=Path)
    parser.add_argument('--fetch-modules',action='store_true',help='Explicitly allow Go module downloads before offline builds')
    parser.add_argument('--gomodcache',type=Path);parser.add_argument('--gocache',type=Path)
    args=parser.parse_args();root=Path(__file__).resolve().parents[1]
    if version('setuptools')!='80.9.0' or version('wheel')!='0.45.1':raise SystemExit('Use the dedicated venv with requirements-build.lock')
    out=Path(args.output).resolve();out.mkdir(parents=True,exist_ok=False)
    epoch=args.epoch if args.epoch is not None else int(subprocess.check_output(['git','log','-1','--format=%ct',args.ref],cwd=root))
    env=os.environ|{'SOURCE_DATE_EPOCH':str(max(epoch,315532800)),'PYTHONHASHSEED':'0','TZ':'UTC'}
    exported=subprocess.check_output(['git','archive','--format=tar',args.ref],cwd=root)
    results={};artifacts=[]
    with tempfile.TemporaryDirectory(prefix='release-build-',dir=out) as temporary:
        temp=Path(temporary);sources=[]
        for number in (1,2):
            source=temp/f'python-{number}';source.mkdir();sources.append(source)
            with tarfile.open(fileobj=io.BytesIO(exported)) as archive:archive.extractall(source,filter='data')
            target=out/f'python-{number}';target.mkdir()
            code='from setuptools.build_meta import build_wheel,build_sdist; build_wheel('+repr(str(target))+'); build_sdist('+repr(str(target))+')'
            with (out/f'python-{number}.log').open('wb') as log:run([os.sys.executable,'-c',code],cwd=source,env=env,stdout=log,stderr=log)
            sdist=next(target.glob('*.tar.gz'));deterministic_sdist(sdist,epoch)
            for artifact in sorted(target.glob('*')):
                results.setdefault(artifact.name,[]).append(sha(artifact))
                if number==1:artifacts.append(artifact)
        with tarfile.open(next((out/'python-1').glob('*.tar.gz'))) as archive:
            names=archive.getnames()
            required=['requirements.lock','requirements-test.lock','requirements-build.lock','deploy/hemloc.service','deploy/gobgp.service','deploy/hemloc.example.ini','deploy/patches/gobgp-4.10.0-ibgp-ttl.patch','docs/OPERATIONS.md','tools/build_release.py']
            for name in required:
                if not any(p.endswith('/'+name) for p in names):raise RuntimeError('Missing from sdist: '+name)
        if bool(args.gobgp_source)!=bool(args.go_archive):raise SystemExit('Supply both verified source and Go toolchain archives')
        if args.gobgp_source:
            if sha(args.gobgp_source)!=SOURCE_SHA or sha(args.go_archive)!=GO_SHA:raise SystemExit('Upstream archive checksum mismatch')
            sdk=temp/'sdk';sdk.mkdir();extract(args.go_archive,sdk);go=sdk/'go/bin/go'
            if 'go1.25.14' not in subprocess.check_output([go,'version'],text=True):raise SystemExit('Wrong Go toolchain')
            goenv=env|{'CGO_ENABLED':'0','GOOS':'linux','GOARCH':'amd64','GOTOOLCHAIN':'local','GOPROXY':'off',
                       'GOMODCACHE':str(args.gomodcache.resolve() if args.gomodcache else out/'gomodcache'),
                       'GOCACHE':str(args.gocache.resolve() if args.gocache else out/'gocache')}
            for number in (1,2):
                directory=temp/f'gobgp-{number}';directory.mkdir();extract(args.gobgp_source,directory)
                source=directory/'gobgp-4.10.0';patch=sources[0]/'deploy/patches/gobgp-4.10.0-ibgp-ttl.patch'
                run(['git','init','-q'],cwd=source)
                run(['git','apply','--check',str(patch)],cwd=source);run(['git','apply',str(patch)],cwd=source)
                patched=(source/'pkg/server/fsm.go').read_text()
                if 'Honor an explicitly configured outgoing TTL for internal peers too.' not in patched or 'Keep the configured TTL when a connected internal socket is adopted.' not in patched:raise RuntimeError('TTL patch was not applied')
                binary=out/f'gobgpd-{number}'
                with (out/f'go-{number}.log').open('wb') as log:
                    if number==1 and args.fetch_modules:run([go,'mod','download'],cwd=source,env=goenv|{'GOPROXY':'https://proxy.golang.org'},stdout=log,stderr=log)
                    run([go,'mod','verify'],cwd=source,env=goenv,stdout=log,stderr=log)
                    run([go,'build','-p=2','-mod=readonly','-trimpath','-buildvcs=false','-ldflags','-buildid= -X github.com/osrg/gobgp/v4/internal/pkg/version.METADATA=hemloc-ibgp-ttl1','-o',str(binary),'./cmd/gobgpd'],cwd=source,env=goenv,stdout=log,stderr=log)
                results.setdefault('gobgpd',[]).append(sha(binary))
            run([out/'gobgpd-1','--version'])
    if any(len(set(pair))!=1 for pair in results.values()):raise RuntimeError('Independent builds differ')
    report={'ref':args.ref,'source_date_epoch':epoch,'python':os.sys.version.split()[0],
            'setuptools':version('setuptools'),'wheel':version('wheel'),'sha256':{key:pair[0] for key,pair in results.items()},
            'gobgp_source_sha256':SOURCE_SHA if args.gobgp_source else None,'go_archive_sha256':GO_SHA if args.go_archive else None}
    (out/'build-report.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report,indent=2));print('Two independent builds match. Artifacts stay local; no installation, service action or Git staging.')

if __name__=='__main__':main()
