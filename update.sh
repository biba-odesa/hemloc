#!/usr/bin/env bash
# Update an existing canonical installation; never migrate paths or roles.
set -Eeuo pipefail
trap 'printf "Update failed at line %s. If already stopped, Hemlock remains stopped; review the retained backup/staging directory before recovery.\n" "$LINENO" >&2' ERR
[[ $EUID == 0 ]] || { echo 'Run as root' >&2; exit 1; }
REF=main
if (($#)); then
  [[ $# == 2 && $1 == --version ]] || { echo 'Usage: update.sh [--version TAG|FULL_COMMIT]' >&2; exit 1; }
  REF=$2
  [[ $REF =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ || $REF =~ ^[0-9a-f]{40}$ ]] || { echo 'Use a fixed tag or full commit' >&2; exit 1; }
fi
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
# Validate executable/package/config and saved role before stopping anything.
/opt/hemlock/.venv/bin/python -I - <<'PY'
from importlib.metadata import version
from pathlib import Path
import sqlite3
from hemlock.config import load
assert tuple(map(int,version('hemlock').split('.'))) >= (0,4,0), 'Follow docs/MIGRATION_LEGACY.md before using this updater'
cfg=load('/etc/hemlock/hemlock.ini')
with sqlite3.connect(Path(cfg.database).resolve().as_uri()+'?mode=ro',uri=True) as db:
    saved=dict(db.execute('SELECT key,value FROM meta'))
assert saved.get('role')==cfg.role and saved.get('node_id')==cfg.node_id, 'Update must not change role or node identity'
PY
[[ $(systemctl show hemlock.service --property=User --value) == hemlock ]] || { echo 'Canonical service/user required; use migration guide' >&2; exit 1; }
git remote get-url origin
if [[ $REF == main ]]; then
  git fetch origin refs/heads/main
elif [[ $REF == v* ]]; then
  git fetch origin "refs/tags/$REF"
else
  git fetch origin "$REF"
fi
COMMIT=$(git rev-parse --verify 'FETCH_HEAD^{commit}')
[[ $REF == main || $REF == v* || $COMMIT == "$REF" ]]
echo "Installing commit: $COMMIT"
STAGE=$(mktemp -d /var/tmp/hemlock-update.XXXXXX)
git archive "$COMMIT" | tar -x -C "$STAGE"
/opt/hemlock/.venv/bin/python -m pip install --require-hashes -r "$STAGE/requirements-build.lock"
/opt/hemlock/.venv/bin/python -m pip wheel --no-deps --no-build-isolation --wheel-dir "$STAGE/wheels" "$STAGE"
WHEELS=("$STAGE"/wheels/hemlock-*.whl)
[[ ${#WHEELS[@]} == 1 && -f ${WHEELS[0]} ]]
systemctl stop hemlock.service
/opt/hemlock/.venv/bin/python -I -m hemlock --config /etc/hemlock/hemlock.ini backup \
  "/var/lib/hemlock/before-update-$(date +%Y%m%d-%H%M%S).sqlite"
/opt/hemlock/.venv/bin/python -m pip install --require-hashes -r "$STAGE/requirements.lock"
/opt/hemlock/.venv/bin/python -m pip install --no-deps --force-reinstall "${WHEELS[0]}"
/opt/hemlock/.venv/bin/python -m pip check
/opt/hemlock/.venv/bin/python -I -c 'from importlib.metadata import version; print("Installed Hemlock:",version("hemlock"))'
systemctl start hemlock.service
systemctl is-active hemlock.service
