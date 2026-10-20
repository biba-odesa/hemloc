"""Scan every reachable commit/tree/blob without printing matched secret values."""
import argparse
import json
import re
import subprocess
from collections import defaultdict
from pathlib import PurePosixPath
from tools.check_artifacts import inspect_artifact


def git(*args):return subprocess.check_output(['git',*args])


def history():
    commits=git('rev-list','--all').decode().splitlines()
    paths=defaultdict(set);origins=defaultdict(set);special=[]
    for commit in commits:
        for entry in git('ls-tree','-rz','--full-tree',commit).split(b'\0'):
            if not entry:continue
            meta,name=entry.split(b'\t',1);mode,kind,oid=meta.decode().split();name=name.decode()
            if mode!='100644' and mode!='100755':special.append({'commit':commit[:12],'path':name,'category':'nonregular-tree-entry'})
            if kind=='blob':paths[oid].add(name);origins[oid].add(commit)
    return commits,paths,origins,special


RULES={
 'credential-url':rb'(?:https?|ssh)://[^\s/\x00:]+:[^\s/@\x00]+@',
 'provider-token':rb'\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|AKIA[A-Z0-9]{16}|xox[baprs]-[A-Za-z0-9-]{20,}|sk-(?:proj-)?[A-Za-z0-9_-]{32,})\b',
 'jwt-token':rb'\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b',
 'database-content':rb'^SQLite format 3\x00',
 'compiled-binary':rb'^(?:\x7fELF|MZ|\xcf\xfa\xed\xfe)',
 'private-environment-setting':rb'(?im)^\s*(?:export\s+)?(?:AWS_SECRET_ACCESS_KEY|GITHUB_TOKEN|OPENAI_API_KEY|REPLICATION_TOKEN)\s*=\s*[\"\']?[A-Za-z0-9_+/=-]{20,}',
}


def scan(operational=None):
    operational={key:(value.encode() if isinstance(value,str) else value) for key,value in (operational or {}).items()}
    commits,paths,origins,special=history();findings=list(special)
    data={oid:git('cat-file','blob',oid) for oid in paths}
    for oid,body in data.items():
        for name in sorted(paths[oid]):
            categories=inspect_artifact(name,body)
            if b'\0' in body:categories.append('binary-content-requires-review')
            if PurePosixPath(name).suffix.lower() in ('.zip','.gz','.tgz','.whl','.deb','.exe'):categories.append('archive-or-binary-artifact')
            categories += [key for key,pattern in RULES.items() if re.search(pattern,body)]
            categories += [key for key,pattern in operational.items() if re.search(pattern,body)]
            for category in set(categories):findings.append({'object':oid,'path':name,'category':category,'commits':sorted(c[:12] for c in origins[oid])})
    tags=[line.split()[0] for line in git('for-each-ref','--format=%(objectname) %(objecttype)','refs/tags').decode().splitlines() if line.endswith(' tag')]
    for commit in commits+tags:
        body=git('cat-file','-p',commit)
        categories=inspect_artifact('commit-message',body)+[key for key,pattern in {**RULES,**operational}.items() if re.search(pattern,body)]
        for category in categories:findings.append({'object':commit,'path':'<commit metadata/message>','category':category})
    return {'commits':len(commits),'unique_blobs':len(data),'path_versions':sum(len(p) for p in paths.values()),'findings':findings},data


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--report');parser.add_argument('--operational-patterns',help='Local ignored JSON category/regex file; never prints matches');args=parser.parse_args()
    operational=json.loads(__import__('pathlib').Path(args.operational_patterns).read_text()) if args.operational_patterns else {}
    report,_=scan(operational)
    for finding in report['findings']:print(f"{finding['path']}: {finding['category']} ({finding['object'][:12]})")
    print(f"History scan: {report['commits']} commits, {report['unique_blobs']} unique blobs; {len(report['findings'])} findings. Values suppressed.")
    if args.report:
        from pathlib import Path
        Path(args.report).write_text(json.dumps(report,indent=2))
    return bool(report['findings'])

if __name__=='__main__':raise SystemExit(main())
