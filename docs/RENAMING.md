# Hemlock: corrected name and compatible upgrade

The canonical application name is **Hemlock**, Python distribution/package
`hemlock`, version 0.2.1, and CLI `hemlock`. UI, Info EN/RU/UK, notifications,
help/error messages and documentation use that spelling. Canonical templates are
`deploy/hemlock.service` and `deploy/hemlock.example.ini`.

Existing deployments keep their active identities and paths:

- `/opt/hemloc`, its `.venv`, and `/etc/hemloc/hemloc.ini`;
- `/var/lib/hemloc`, the configured SQLite DB and local protection cache;
- service/user/group `hemloc` and the installed `hemloc.service`;
- node IDs, route-owner marker and GoBGP policy names/TTL build provenance;
- replication header `X-Hemloc-Node`, cookie `hemloc_session` and browser theme key.

These remaining legacy strings are compatibility identifiers, not misspelled
branding. They must not be replaced blindly during a rolling upgrade. The existing
GitHub repository URL and immutable v0.1.0 tag keep their historical spelling.
Existing `hemloc` imports are identity-preserving aliases of `hemlock` modules;
the old `hemloc` console entry points to `hemlock.cli:main`. Do not move the
working directories, rename SQLite files/users/node IDs or restart GoBGP.
Historical v0.1.0 installation examples use the legacy package and templates;
they are not instructions to install the corrected-name version. Current updates
use the reviewed commit reported with this change.

## Synchronization color

Green means **In sync**: a fresh successful replication observation, matching
history and zero lag. Catching up, unavailable/stale, not configured and conflicting
masters are red. Text and lag remain visible; color alone is not the status.
The color does not prove BGP export or remote-router installation.

## Existing node update (root)

Use the same fixed approved commit on both nodes. Keep the INI and the active
systemd unit/drop-ins unchanged, including any privileged-port capability override.
Do not run init-db or create a new user on a slave.

The source directory can differ from the installed venv. Select an actual Git
checkout; `git status --short` must not show unexpected tracked modifications.
An untracked private file must not be included in builds: build from `git archive`
of the approved commit, not a dirty working directory. Replace placeholders below.
Commands run as root unless explicitly stated otherwise.

```bash
cd SOURCE_CHECKOUT
git fetch origin main
git switch --detach APPROVED_COMMIT
export HEMLOCK_STAGE=$(mktemp -d /var/tmp/hemlock-update.XXXXXX)
git archive HEAD | tar -x -C "$HEMLOCK_STAGE"
/opt/hemloc/.venv/bin/python -m pip install --require-hashes -r "$HEMLOCK_STAGE/requirements.lock"
/opt/hemloc/.venv/bin/python -m pip install --require-hashes -r "$HEMLOCK_STAGE/requirements-build.lock"
```

Before stopping, prepare a rollback wheel from the previously installed source
commit, plus a normal SQLite API backup in a service-user-writable private backup
directory. Retain the exact old source revision and config backup. Stop only
Hemlock and then use the existing CLI for backup; do not copy an open database.
The rename itself does not migrate rules, users, audit, protection or replication.

```bash
systemctl stop hemloc
/opt/hemloc/.venv/bin/hemloc --config /etc/hemloc/hemloc.ini backup \
  "/var/lib/hemloc/before-hemlock-$(date +%Y%m%d-%H%M%S).sqlite"
/opt/hemloc/.venv/bin/python -m pip uninstall -y hemloc
/opt/hemloc/.venv/bin/python -m pip install --no-build-isolation --no-deps \
  --no-cache-dir --force-reinstall "$HEMLOCK_STAGE"
/opt/hemloc/.venv/bin/python -m pip check
/opt/hemloc/.venv/bin/python -I -c \
  'import hemlock; from pathlib import Path; print(hemlock.__version__); assert hemlock.__version__ == "0.2.1"; assert "Hemlock" in (Path(hemlock.__file__).parent / "static/index.html").read_text()'
/opt/hemloc/.venv/bin/hemloc --help
systemctl start hemloc
systemctl is-active hemloc
journalctl -u hemloc -n 30 --no-pager
```

Stop on any failed command. If installation fails after uninstall, reinstall the
prepared previous wheel, verify it and start only Hemlock. Never replace a working
DB with an empty one to fix a package error. `python -I` avoids a stale source
folder in the working directory shadowing the installed package.

If a node already has distribution `hemlock`, uninstalling legacy `hemloc` is not
needed; do not uninstall `hemloc` later after the new package has installed shared
compatibility files/entry points. A failed uninstall saying the old package is
absent is distinct from a failed new installation.

On completion hard-refresh the browser, verify the corrected name, green In sync
and zero lag on both nodes. Nonhealthy states must remain red. No config key
changes are required; retention/notifications/announcements retain their existing
values. This rename does not enable any feature or clean any audit.
