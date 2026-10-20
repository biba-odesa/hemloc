"""Embedded web launcher and root-only maintenance commands."""

import argparse
import getpass
import os
from pathlib import Path
import sys

from .auth import password_hash, PASSWORD_MIN_LENGTH, PASSWORD_MAX_LENGTH
from .config import load
from .domain import Actor, Invalid
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
    parser = argparse.ArgumentParser(prog='hemloc')
    parser.add_argument('--config', default='/etc/hemloc/hemloc.ini')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('serve')
    sub.add_parser('init-db')
    sub.add_parser('desired')
    backup = sub.add_parser('backup')
    backup.add_argument('destination')
    routes = sub.add_parser('routes')
    route_ops = routes.add_subparsers(dest='operation', required=True)
    drain = route_ops.add_parser('withdraw-owned')
    drain.add_argument('--execute', action='store_true', help='Withdraw owned paths; default is a dry-run')
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
            print('Database initialized; set ownership for the service user before starting Hemloc')
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
        if store is not None and args.command == 'user' and args.operation != 'list' and not getattr(exc, 'hemloc_audited', False):
            from .audit import failure_result
            store.security_event('root:cli', 'user.' + args.operation, 'user', failure_result(exc))
        message = str(exc) if isinstance(exc, (Invalid, PermissionError)) else 'Operation failed; check configuration and local service health'
        if isinstance(exc, ImportError):
            message = 'Project dependencies are missing; install them in the virtual environment'
        print(f'Hemloc: {message}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
