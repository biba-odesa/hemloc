"""Embedded web launcher and root-only maintenance commands."""

import argparse
import getpass
import os
from pathlib import Path
import sys

from .auth import password_hash, PASSWORD_MIN_LENGTH, PASSWORD_MAX_LENGTH
from .config import load
from .domain import Actor, Invalid
from .protocol import ProtocolFailure
from .service import Service
from .store import Store, encode
from .workers import process_lock


def prompt_password():
    print(f'Password: {PASSWORD_MIN_LENGTH}..{PASSWORD_MAX_LENGTH} characters; at least one letter and one digit; special characters optional.')
    first = getpass.getpass('New password: ')
    second = getpass.getpass('Repeat password: ')
    if first != second:
        raise Invalid('Passwords do not match')
    return password_hash(first)


def main(argv=None):
    os.umask(0o077)
    parser = argparse.ArgumentParser(prog='hemlock')
    parser.add_argument('--config', default='/etc/hemlock/hemlock.ini')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('serve')
    sub.add_parser('init-db')
    sub.add_parser('desired')
    transition = sub.add_parser('transition')
    transitions = transition.add_subparsers(dest='operation', required=True)
    transitions.add_parser('status')
    check = transitions.add_parser('checkpoint')
    check.add_argument('--execute', action='store_true', help='Checkpoint/detach current SQLite file with application stopped; default dry-run')
    reset = transitions.add_parser('reset-after-restore')
    reset.add_argument('backup')
    reset.add_argument('--execute', action='store_true', help='Reset the fence only after validating an exact offline master backup restore')
    backup = sub.add_parser('backup')
    backup.add_argument('destination')
    routes = sub.add_parser('routes')
    route_ops = routes.add_subparsers(dest='operation', required=True)
    drain = route_ops.add_parser('withdraw-owned')
    drain.add_argument('--execute', action='store_true', help='Withdraw owned paths; default is a dry-run')
    audit = sub.add_parser('audit')
    audits = audit.add_subparsers(dest='operation', required=True)
    for name in ('preview', 'export', 'prune'):
        command = audits.add_parser(name)
        command.add_argument('--output')
        command.add_argument('--plan')
        command.add_argument('--execute', action='store_true', help='Explicitly perform export or apply the exact prune plan')
    user = sub.add_parser('user')
    users = user.add_subparsers(dest='operation', required=True)
    users.add_parser('list')
    create = users.add_parser('create')
    create.add_argument('login')
    create.add_argument('--role', choices=['admin', 'guest'], required=True)
    reset = users.add_parser('reset-password')
    reset.add_argument('login')
    args = parser.parse_args(argv)
    store = None
    try:
        config = load(args.config)
        if args.command == 'serve':
            if os.geteuid() == 0:
                raise Invalid('Run the application as an unprivileged service user')
            import uvicorn
            from .web import create_app
            uvicorn.run(create_app(config), host=config.host, port=config.port, workers=1,
                        ssl_certfile=config.cert if config.tls else None,
                        ssl_keyfile=config.key if config.tls else None,
                        proxy_headers=False, access_log=False)
            return 0
        if os.geteuid() != 0:
            raise Invalid('Maintenance CLI requires root')
        if args.command == 'init-db':
            with process_lock(config.database):
                Store(config)
            print('Database initialized; set ownership for the service user before starting Hemlock')
            return 0
        if args.command == 'transition':
            from .transition import RoleTransition, checkpoint
            transition = RoleTransition(config)
            owner_path = Path(config.database) if Path(config.database).exists() else transition.path
            if owner_path.exists():
                owner = owner_path.stat()
                if owner.st_uid != 0:
                    os.setgroups([]);os.setgid(owner.st_gid);os.setuid(owner.st_uid)
            if args.operation == 'status':
                state = transition.read()
                print(encode({'transition':transition.status(), 'backup':state.get('backup') if state else None, 'staging':state.get('staging') if state else None}))
            else:
                with process_lock(config.database):
                    if args.operation == 'checkpoint':
                        if args.execute:checkpoint(Path(config.database))
                        print(encode({'mode':'execute' if args.execute else 'dry-run','checkpointed':bool(args.execute)}))
                    else:
                        print(encode(transition.reset_after_restore(args.backup, args.execute)))
            return 0
        if not Path(config.database).exists():
            raise Invalid('Run init-db before maintenance commands')
        # Root invokes recovery, but SQLite sidecars must belong to the DB owner.
        owner = Path(config.database).stat()
        if owner.st_uid != 0:
            os.setgroups([])
            os.setgid(owner.st_gid)
            os.setuid(owner.st_uid)
        store = Store(config, activate=False)
        service = Service(store)
        if args.command == 'backup':
            print(store.backup(args.destination))
        elif args.command == 'desired':
            routes, excluded = service.routes()
            print(encode({'routes': routes, 'excluded': excluded}))
        elif args.command == 'routes':
            from .maintenance import withdraw_owned
            print(encode(withdraw_owned(store, execute=args.execute)))
        elif args.command == 'audit':
            import json
            from .retention import preview, execute, export, write_private, validate_plan
            if args.operation == 'export':
                if args.execute and not args.output:
                    raise Invalid('Export --execute requires --output')
                print(encode(export(store, args.output if args.execute else None)))
            elif args.operation == 'prune' and args.execute:
                if not args.plan:
                    raise Invalid('Prune --execute requires an existing exact --plan')
                plan = json.loads(Path(args.plan).read_text())
                if config.peer_url:
                    from .replication import PeerTransport, observe_peer
                    # A CLI process cannot borrow the running application's RAM cache.
                    # Probe directly over verified TLS before the transactional gate.
                    observe_peer(store, PeerTransport(config))
                print(encode({'removed':execute(store, plan), 'digest':plan['digest']}))
            else:
                plan = json.loads(Path(args.plan).read_text()) if args.plan else preview(store)
                validate_plan(store, plan)
                if args.output:
                    write_private(args.output, plan)
                from datetime import datetime
                from zoneinfo import ZoneInfo
                times = {k:datetime.fromtimestamp(v, ZoneInfo(config.retention_timezone)).isoformat() for k,v in plan['payload']['cutoffs'].items()}
                print(encode({k:v for k,v in plan['payload'].items() if k!='entries'} | {'digest':plan['digest'], 'dry_run':True, 'cutoff_local':times, 'timezone':config.retention_timezone}))
        elif args.operation == 'list':
            for item in store.list('user'):
                print(f"{item['id']}\t{item['role']}\tenabled={item['enabled']}")
        else:
            actor = Actor('root:cli', 'admin')
            service.writable(actor)
            existing = store.get('user', args.login)
            if args.operation == 'create' and existing:
                raise Invalid('User already exists')
            if args.operation == 'reset-password' and not existing:
                raise Invalid('User not found')
            service.save_user(actor, args.login, role=getattr(args, 'role', None), password_hash=prompt_password(),
                              create_only=args.operation == 'create', require_existing=args.operation == 'reset-password')
            print('User saved; replication and GoBGP status are independent')
        return 0
    except (ValueError, PermissionError, RuntimeError, OSError, ImportError) as exc:
        if store is not None and args.command == 'user' and args.operation != 'list' and not getattr(exc, 'hemlock_audited', False):
            from .audit import failure_result
            store.security_event('root:cli', 'user.' + args.operation, 'user', failure_result(exc))
        if store is not None and args.command == 'audit' and args.operation == 'prune' and args.execute:
            from .audit import failure_result
            store.security_event('root:cli', 'audit.prune', 'maintenance', failure_result(exc))
        message = str(exc) if isinstance(exc, (Invalid, PermissionError, ProtocolFailure)) else 'Operation failed; check configuration and local service health'
        if isinstance(exc, ImportError):
            message = 'Project dependencies are missing; install them in the virtual environment'
        print(f'Hemlock: {message}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
