#!/usr/bin/env bash
# Update the installed application from origin/main without changing its config.
# Run as root from a Git checkout. Only the Hemloc application is restarted.
set -euo pipefail

cd -- "$(dirname -- "${BASH_SOURCE[0]}")"

git remote get-url origin
git fetch origin refs/heads/main

COMMIT=$(git rev-parse --verify 'FETCH_HEAD^{commit}')
echo "Installing commit: $COMMIT"

STAGE=$(mktemp -d /var/tmp/hemlock-update.XXXXXX)
git archive "$COMMIT" | tar -x -C "$STAGE"

/opt/hemlock/.venv/bin/python -m pip install --require-hashes \
  -r "$STAGE/requirements-build.lock"

/opt/hemlock/.venv/bin/python -m pip wheel --no-deps --no-build-isolation \
  --wheel-dir "$STAGE/wheels" "$STAGE"

systemctl stop hemloc

/opt/hemlock/.venv/bin/hemloc --config /etc/hemloc/hemloc.ini backup \
  "/var/lib/hemloc/before-update-$(date +%Y%m%d-%H%M%S).sqlite"

/opt/hemlock/.venv/bin/python -m pip install --require-hashes \
  -r "$STAGE/requirements.lock"

/opt/hemlock/.venv/bin/python -m pip install --no-deps --force-reinstall \
  "$STAGE"/wheels/hemlock-*.whl

/opt/hemlock/.venv/bin/python -m pip check

/opt/hemlock/.venv/bin/python -I -c \
  'from importlib.metadata import version; print("Installed Hemlock:", version("hemlock"))'

systemctl start hemloc
systemctl is-active hemloc
