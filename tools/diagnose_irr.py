"""Read-only IRR probe for the installed canonical resolver."""
import argparse
from contextlib import closing
import json
import hashlib
import os
from pathlib import Path
import subprocess
import sqlite3
import time
from unittest.mock import patch

from hemlock.config import load
from hemlock.domain import asn
from hemlock.irr import IRR, bounded_process
import hemlock.irr as installed_irr


def probe(config, number):
    events = []
    last = {}
    real_popen, real_read = subprocess.Popen, os.read

    def runner(args, timeout):
        nonlocal last
        captured = bytearray()
        process = None
        error_fd = None
        count = 0
        last = {'family': 4 if '-4' in args else 6, 'exit_code': None}
        started = time.monotonic()

        def spawn(*values, **options):
            nonlocal process, error_fd
            process = real_popen(*values, **options)
            error_fd = process.stderr.fileno()
            return process

        def read(fd, size):
            nonlocal count
            data = real_read(fd, size)
            if fd == error_fd:
                count += len(data)
                captured.extend(data[:max(0,4096-len(captured))])
            return data

        try:
            # Run the actual installed bounded_process, including its limits,
            # proxy removal, selector loop, stderr checks and cleanup.
            with patch('hemlock.irr.subprocess.Popen', side_effect=spawn), patch('hemlock.irr.os.read', side_effect=read):
                data = bounded_process(args, timeout)
            last['stdout_bytes'] = len(data)
            return data
        except Exception as error:
            last['failure'] = classify(error)
            raise
        finally:
            if process is not None:
                last['exit_code'] = process.returncode
            last['stderr_bytes'] = count
            labels = {
                b'permission denied':'permission_denied',
                b'operation not permitted':'operation_not_permitted',
                b'connection refused':'connection_refused',
                b'connection timed out':'connection_timeout',
                b'network is unreachable':'network_unreachable',
                b'no route to host':'no_route',
                b'name or service not known':'dns_failure',
                b'temporary failure in name resolution':'dns_failure',
                b'invalid option':'invalid_option',
                b'unrecognized option':'invalid_option',
            }
            last['stderr_hint'] = next((label for pattern,label in labels.items() if pattern in captured.lower()),None)
            last['elapsed_seconds'] = round(time.monotonic()-started,3)
            events.append(last)

    result = {'asn': number, 'families': events, 'configured_timeout_seconds': config.timeout}
    try:
        prefixes = IRR(config, runner=runner).expand(number)
        result.update(ok=True, prefix_count=len(prefixes))
    except Exception as error:
        result.update(ok=False, failure=classify(error), failing_family=last.get('family'))
    return result


def classify(error):
    # Exception strings are used only for equality against fixed legacy labels;
    # neither exception text, subprocess text, argv nor prefix data is emitted.
    legacy = {'IRR timeout':'timeout', 'IRR output limit exceeded':'output_limit',
              'IRR utility failed':'exit', 'IRR utility reported an error':'utility_error',
              'Unexpected IRR address family':'family_mismatch',
              'IRR response unavailable or invalid':'invalid_output',
              'IRR process unavailable':'os_error'}
    category = legacy.get(str(error), 'internal')
    if isinstance(error, OSError):
        category = 'os_error'
    cause = error
    while cause is not None:
        if isinstance(cause, OSError):
            return {'type':category, 'errno':cause.errno, 'timeout':category=='timeout'}
        cause = cause.__cause__
    return {'type':category, 'timeout':category=='timeout'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',default='/etc/hemlock/hemlock.ini')
    parser.add_argument('--asn',action='append',required=True,type=asn)
    args = parser.parse_args()
    try:
        config = load(args.config)
    except Exception as error:
        print(json.dumps({'configuration_error':classify(error)}))
        return 1
    own = {}
    for line in Path('/proc/self/status').read_text().splitlines():
        if line.startswith(('NoNewPrivs:', 'Seccomp:', 'CapEff:')):
            key,value=line.split(':',1);own[key]=value.strip()
    properties = ['User','Group','NoNewPrivileges','PrivateTmp','ProtectSystem','ProtectHome',
                  'RestrictAddressFamilies','PrivateNetwork','IPAddressDeny','IPAddressAllow','MainPID',
                  'WorkingDirectory','RootDirectory','ReadWritePaths','NoExecPaths','InaccessiblePaths',
                  'SystemCallFilter']
    try:
        process = subprocess.run(['systemctl','show','hemlock']+['--property='+p for p in properties],
                                 capture_output=True,text=True,timeout=5)
        unit = dict(line.split('=',1) for line in process.stdout.splitlines() if '=' in line) if process.returncode==0 else {'available':False}
    except (OSError,subprocess.SubprocessError):
        unit = {'available':False}
    schedule = {}
    try:
        with closing(sqlite3.connect(Path(config.database).resolve().as_uri()+'?mode=ro',uri=True)) as db:
            db.execute('PRAGMA query_only=ON')
            row=db.execute("SELECT body FROM local WHERE key='protection_schedule'").fetchone()
            state=json.loads(row[0]) if row else {}
            for number in args.asn:
                item=state.get(str(number),{})
                schedule[str(number)]={'error_recorded':bool(item.get('error')),
                                       'next_attempt':item.get('next'),
                                       'retry_in_seconds':max(0,round(item.get('next',0)-time.time()))}
    except (OSError,ValueError,sqlite3.Error):
        schedule={'available':False}
    results = [probe(config,number) for number in args.asn]
    resolver_sha256 = hashlib.sha256(Path(installed_irr.__file__).read_bytes()).hexdigest()
    print(json.dumps({'read_only':True,'resolver_sha256':resolver_sha256,
                      'own_process':own,'service_properties':unit,
                      'persisted_schedule':schedule,'results':results},indent=2))
    return int(any(not result['ok'] for result in results))


if __name__ == '__main__':
    raise SystemExit(main())
