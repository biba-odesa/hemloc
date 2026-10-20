"""Check Git candidates or staged blobs without printing sensitive matches."""

import argparse
from pathlib import Path, PurePosixPath
import re
import subprocess

RUNTIME_DIRECTORIES = {'.venv', '__pycache__', '.pytest_cache', '.ruff_cache', 'var', 'build', 'dist', 'htmlcov'}
RUNTIME_SUFFIXES = ('.key', '.pem', '.crt', '.csr', '.srl', '.token', '.log', '.pyc', '.pyo', '.owner.lock')
PRIVATE_KEY = re.compile(rb'-----BEGIN (?:[A-Z0-9]+ )?PRIVATE KEY-----')
ARGON_HASH = re.compile(rb'\$argon2id\$v=\d+\$m=\d+,t=\d+,p=\d+\$[A-Za-z0-9+/]{8,}\$[A-Za-z0-9+/]{16,}')


def inspect_artifact(name, data):
    path = PurePosixPath(name)
    problems = []
    if (any(part in RUNTIME_DIRECTORIES or part.endswith('.egg-info') for part in path.parts) or
        name.endswith(RUNTIME_SUFFIXES) or re.search(r'\.(?:sqlite|db)(?:$|[.-])', name) or
        '.backup' in path.name or path.name in ('.env', 'hemloc.ini', '.coverage')):
        problems.append('runtime-or-private-artifact')
    if PRIVATE_KEY.search(data):
        problems.append('private-key-content')
    if ARGON_HASH.search(data):
        problems.append('password-hash-content')
    return problems


def git(*args):
    return subprocess.check_output(['git', *args])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--staged', action='store_true', help='Inspect the actual staged blobs, not working-tree files')
    args = parser.parse_args()
    if args.staged:
        names = git('diff', '--cached', '--name-only', '--diff-filter=ACMR', '-z')
    else:
        names = git('ls-files', '--cached', '--others', '--exclude-standard', '-z')
    candidates = sorted({n.decode('utf-8', errors='strict') for n in names.split(b'\0') if n})
    failures = []
    for name in candidates:
        path = Path(name)
        if args.staged:
            data = git('show', ':' + name)
            entry = git('ls-files', '--stage', '--', name).split(b' ',1)[0]
            is_link = entry == b'120000'
        else:
            is_link = path.is_symlink()
            data = b'' if is_link else path.read_bytes()
        problems = inspect_artifact(name, data)
        if is_link:
            problems.append('symlink-requires-review')
        failures.extend((name, problem) for problem in problems)
    for name, problem in failures:
        print(f'{name}: {problem}')
    print(f'Artifact check: {len(candidates)} files, {len(failures)} findings; source={"index" if args.staged else "Git candidates"}')
    if not candidates:
        print('No files to inspect; this does not certify a future commit.')
    return bool(failures)


if __name__ == '__main__':
    raise SystemExit(main())
