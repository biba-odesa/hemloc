#!/usr/bin/env bash
# Fresh installation only. Does not initialize a database or start any service.
set -Eeuo pipefail
umask 077
trap 'printf "Installation failed at line %s. Services were not started; inspect the partial installation before retrying.\n" "$LINENO" >&2' ERR

usage() {
  cat <<'HELP'
Usage: install-debian13.sh --role master|slave --version TAG|FULL_COMMIT \
  --node-id ID --peer-node-id ID --owner A,B,C \
  --gobgp-binary FILE --gobgp-sha256 SHA256 [--expected-commit FULL_COMMIT] \
  [--proxy http://HOST:PORT] [--check]
Install fixed canonical Hemlock sources on a clean Debian 13 host as root.
Supply an independently verified GoBGP 4.10.0+hemlock-ibgp-ttl1 binary.
--check performs preflight only, without apt, downloads or filesystem changes.
Proxy credentials in arguments are forbidden. No configuration secrets are created.
HELP
}
fail() { printf 'Error: %s\n' "$*" >&2; exit 1; }
ROLE='' RELEASE_REF='' NODE_ID='' PEER_ID='' OWNER='' BINARY='' CHECKSUM='' EXPECTED='' PROXY=''
CHECK=no
while (($#)); do
  case "$1" in
    --help|-h) usage; exit 0 ;;
    --check) CHECK=yes; shift ;;
    --role|--version|--node-id|--peer-node-id|--owner|--gobgp-binary|--gobgp-sha256|--expected-commit|--proxy)
      (($# >= 2)) || fail "Missing value for $1"
      case "$1" in
        --role) ROLE=$2 ;; --version) RELEASE_REF=$2 ;; --node-id) NODE_ID=$2 ;;
        --peer-node-id) PEER_ID=$2 ;; --owner) OWNER=$2 ;; --gobgp-binary) BINARY=$2 ;;
        --gobgp-sha256) CHECKSUM=$2 ;; --expected-commit) EXPECTED=$2 ;; --proxy) PROXY=$2 ;;
      esac
      shift 2 ;;
    *) fail 'Unknown argument; use --help' ;;
  esac
done
[[ $EUID == 0 ]] || fail 'Run as root'
# shellcheck source=/dev/null
source /etc/os-release
[[ $ID == debian && $VERSION_ID == 13 ]] || fail 'Debian 13 is required'
[[ $ROLE == master || $ROLE == slave ]] || fail 'Specify --role master or slave'
[[ $RELEASE_REF =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ || $RELEASE_REF =~ ^[0-9a-f]{40}$ ]] || fail 'Use a release tag or full 40-character commit, never main'
[[ -z $EXPECTED || $EXPECTED =~ ^[0-9a-f]{40}$ ]] || fail 'Invalid expected commit'
[[ $NODE_ID =~ ^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$ && $PEER_ID =~ ^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$ && $NODE_ID != "$PEER_ID" ]] || fail 'Supply distinct local/peer node IDs'
[[ $OWNER =~ ^[0-9]+,[0-9]+,[0-9]+$ ]] || fail 'Specify a unique owner as three comma-separated uint32 values'
IFS=, read -r -a OWNER_PARTS <<< "$OWNER"
for PART in "${OWNER_PARTS[@]}"; do
  if [[ ${#PART} -gt 10 ]] || ((10#$PART > 4294967295)); then
    fail 'Owner component exceeds uint32'
  fi
done
[[ $CHECKSUM =~ ^[0-9a-fA-F]{64}$ && $BINARY == /* && -f $BINARY && ! -L $BINARY ]] || fail 'Supply a regular GoBGP binary and SHA256'
printf '%s  %s\n' "$CHECKSUM" "$BINARY" | sha256sum --check --status || fail 'GoBGP checksum mismatch'
[[ -x $BINARY ]] || fail 'Verified GoBGP input must already be executable'
BINARY_VERSION=$("$BINARY" --version)
[[ $BINARY_VERSION == *4.10.0+hemlock-ibgp-ttl1* ]] || fail 'Expected verified GoBGP 4.10.0+hemlock-ibgp-ttl1'
[[ -z $PROXY || $PROXY =~ ^https?://[A-Za-z0-9._-]+:[0-9]+/?$ ]] || fail 'Proxy must be http(s)://HOST:PORT without credentials'

# Refuse both canonical and earlier installations instead of silently migrating.
for PATTERN in /opt/hemlo* /etc/hemlo* /var/lib/hemlo* /etc/systemd/system/hemlo*.service* \
  /etc/gobgp /usr/local/bin/gobgpd /etc/systemd/system/gobgp.service \
  /usr/lib/systemd/system/gobgp.service /usr/lib/systemd/system/hemlock.service; do
  [[ ! -e $PATTERN && ! -L $PATTERN ]] || fail 'Existing application/GoBGP installation detected; use the migration/update guide'
done
if getent passwd | awk -F: '$1 ~ /^hemlo/ || $1 == "gobgp" {found=1} END {exit !found}'; then
  fail 'Existing service user detected; no users were changed'
fi
if getent group | awk -F: '$1 ~ /^hemlo/ || $1 == "gobgp" {found=1} END {exit !found}'; then
  fail 'Existing service group detected; no groups were changed'
fi
[[ $(df -Pk /opt | awk 'END {print $4}') -ge 1048576 ]] || fail 'At least 1 GiB free in /opt is required'
if [[ $CHECK == yes ]]; then
  printf 'Preflight OK. Planned: apt dependencies, fixed checkout/venv, private directories, disabled units. No service start.\n'
  exit 0
fi

# Explicit direct downloads by default; the application proxy is unrelated.
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY all_proxy ALL_PROXY no_proxy NO_PROXY
if [[ -n $PROXY ]]; then
  export http_proxy="$PROXY" https_proxy="$PROXY" HTTP_PROXY="$PROXY" HTTPS_PROXY="$PROXY"
fi
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends git python3.13-venv ca-certificates tzdata bgpq4 openssl patch curl systemd

# Git is installed before its first invocation. Never resolve a moving branch.
git clone --no-checkout https://github.com/biba-odesa/hemlock.git /opt/hemlock
if [[ $RELEASE_REF == v* ]]; then
  git -C /opt/hemlock fetch --depth=1 origin "refs/tags/$RELEASE_REF"
else
  git -C /opt/hemlock fetch --depth=1 origin "$RELEASE_REF"
fi
COMMIT=$(git -C /opt/hemlock rev-parse --verify 'FETCH_HEAD^{commit}')
[[ -z $EXPECTED || $COMMIT == "$EXPECTED" ]] || fail 'Release commit does not match --expected-commit'
[[ $RELEASE_REF == v* || $COMMIT == "$RELEASE_REF" ]] || fail 'Fetched commit mismatch'
git -C /opt/hemlock checkout --detach "$COMMIT"
[[ -f /opt/hemlock/deploy/install-debian13.sh ]] || fail 'This release predates canonical fresh installation support; select 0.4.0 or later'
python3.13 - <<'PY'
from pathlib import Path
import tomllib
root=Path('/opt/hemlock')
project=tomllib.loads((root/'pyproject.toml').read_text())['project']
assert project['name']=='hemlock' and tuple(map(int,project['version'].split('.'))) >= (0,4,0), 'Canonical release 0.4.0 or later required'
assert 'User=hemlock\n' in (root/'deploy/hemlock.service').read_text()
PY
python3.13 -m venv /opt/hemlock/.venv
/opt/hemlock/.venv/bin/python -m pip install --require-hashes -r /opt/hemlock/requirements-build.lock
/opt/hemlock/.venv/bin/python -m pip install --require-hashes -r /opt/hemlock/requirements.lock
/opt/hemlock/.venv/bin/python -m pip install --no-deps --no-build-isolation /opt/hemlock
/opt/hemlock/.venv/bin/python -m pip check

useradd --system --user-group --home-dir /var/lib/hemlock --no-create-home --shell /usr/sbin/nologin hemlock
useradd --system --user-group --no-create-home --shell /usr/sbin/nologin gobgp
install -d -o root -g hemlock -m 0750 /etc/hemlock /etc/hemlock/tls
install -d -o hemlock -g hemlock -m 0700 /var/lib/hemlock
install -d -o root -g gobgp -m 0750 /etc/gobgp
install -o root -g hemlock -m 0640 /opt/hemlock/deploy/hemlock.example.ini /etc/hemlock/hemlock.ini
ROLE="$ROLE" NODE_ID="$NODE_ID" PEER_ID="$PEER_ID" OWNER="$OWNER" python3.13 - <<'PY'
import os,re
from pathlib import Path
path=Path('/etc/hemlock/hemlock.ini')
body=path.read_text()
for key,value in {'role':os.environ['ROLE'],'node_id':os.environ['NODE_ID'],'peer_node_id':os.environ['PEER_ID'],'owner':os.environ['OWNER'],'protected_asns':'','protected_prefixes':''}.items():
    body=re.sub(r'^'+key+r' =.*$',key+' = '+value,body,flags=re.M)
path.write_text(body)
PY
chown root:hemlock /etc/hemlock/hemlock.ini
chmod 0640 /etc/hemlock/hemlock.ini
install -o root -g root -m 0755 "$BINARY" /usr/local/bin/gobgpd
install -o root -g root -m 0644 /opt/hemlock/deploy/patches/LICENSE.GoBGP /usr/local/share/LICENSE.GoBGP
install -o root -g gobgp -m 0640 /opt/hemlock/deploy/gobgpd.managed.example.toml /etc/gobgp/gobgpd.toml.example
install -o root -g root -m 0644 /opt/hemlock/deploy/hemlock.service /etc/systemd/system/hemlock.service
install -o root -g root -m 0644 /opt/hemlock/deploy/gobgp.service /etc/systemd/system/gobgp.service
chown -R root:root /opt/hemlock
chmod -R a+rX /opt/hemlock
chmod -R go-w /opt/hemlock
if [[ -d /run/systemd/system ]]; then
  systemctl daemon-reload
else
  printf 'No running systemd manager: unit files installed offline; reload on boot.\n'
fi
printf '\nInstalled commit: %s\nNo services enabled or started. No DB or administrator created.\n' "$COMMIT"
cat <<'NEXT'
Next, as root (see /opt/hemlock/docs/DEPLOYMENT.md for full TLS/replication steps):
1. Prepare /etc/hemlock/tls/{server.crt,server.key,ca.crt} and replication secret.
2. Edit /etc/hemlock/hemlock.ini: HTTPS, peer identity/URL, protection, operator-approved route attributes. Keep announcements=no.
3. Prepare /etc/gobgp/gobgpd.toml from the example using approved addresses/ASN. All real peers remain administratively disabled; import/export reject by default.
4. Recheck INI root:hemlock 0640 and readability as hemlock after editing.
5. Validate config: runuser -u hemlock -- /opt/hemlock/.venv/bin/python -c 'from hemlock.config import load; load("/etc/hemlock/hemlock.ini"); print("Config OK")'
6. Initialize: /opt/hemlock/.venv/bin/hemlock --config /etc/hemlock/hemlock.ini init-db
7. Set DB ownership: chown -R hemlock:hemlock /var/lib/hemlock
8. MASTER ONLY: /opt/hemlock/.venv/bin/hemlock --config /etc/hemlock/hemlock.ini user create LOGIN --role admin
9. After TLS/config/protection review: systemctl enable --now gobgp.service hemlock.service
SLAVE: never create an administrator; users/rules/audit arrive by snapshot/journal.
NEXT
