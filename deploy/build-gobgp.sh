#!/usr/bin/env bash
# Build the pinned TTL-patched daemon; never install files or start services.
set -Eeuo pipefail
umask 077
OUTPUT='' PROXY=''
while (($#)); do
  case "$1" in
    --output|--proxy)
      (($# >= 2)) || { echo 'Missing build argument' >&2; exit 1; }
      if [[ $1 == --output ]]; then OUTPUT=$2; else PROXY=$2; fi
      shift 2 ;;
    *) echo 'Usage: build-gobgp.sh --output NEW_DIRECTORY [--proxy http://HOST:PORT]' >&2; exit 1 ;;
  esac
done
[[ $OUTPUT == /* && ! -e $OUTPUT && ! -L $OUTPUT ]] || { echo 'Supply a new output directory' >&2; exit 1; }
[[ $(uname -m) == x86_64 ]] || { echo 'Pinned build supports Linux amd64 only' >&2; exit 1; }
[[ -z $PROXY || $PROXY =~ ^https?://[A-Za-z0-9._-]+:[0-9]+/?$ ]] || { echo 'Proxy must be http(s)://HOST:PORT without credentials' >&2; exit 1; }
SOURCE_SHA=27d8ef958100557344be98e459fa43a20d2a15b5ce943d2aed2772958a3bf397
GO_SHA=a21ae5633a269bcd7e90cf767e48225633795e99d831742cbf3397064fee7712
PATCH="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/patches/gobgp-4.10.0-ibgp-ttl.patch"
[[ -f $PATCH ]] || { echo 'Pinned TTL patch is missing' >&2; exit 1; }
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY all_proxy ALL_PROXY no_proxy NO_PROXY
if [[ -n $PROXY ]]; then
  export http_proxy="$PROXY" https_proxy="$PROXY" HTTP_PROXY="$PROXY" HTTPS_PROXY="$PROXY"
fi
WORK=$(mktemp -d /var/tmp/hemlock-gobgp-build.XXXXXX)
trap 'rm -rf -- "$WORK"' EXIT
trap 'printf "GoBGP build failed at line %s; no service was started.\n" "$LINENO" >&2' ERR
fetch() {
  curl --fail --location --proto '=https' --proto-redir '=https' --tlsv1.2 \
    --retry 2 --connect-timeout 20 --max-time 600 --output "$2" "$1"
}
fetch https://codeload.github.com/osrg/gobgp/tar.gz/refs/tags/v4.10.0 "$WORK/source.tar.gz"
fetch https://go.dev/dl/go1.25.14.linux-amd64.tar.gz "$WORK/go.tar.gz"
printf '%s  %s\n' "$SOURCE_SHA" "$WORK/source.tar.gz" "$GO_SHA" "$WORK/go.tar.gz" | sha256sum --check --status
# Verify both archives before extracting or executing downloaded code.
mkdir "$WORK/sdk" "$WORK/source"
tar -xzf "$WORK/go.tar.gz" -C "$WORK/sdk" --no-same-owner
tar -xzf "$WORK/source.tar.gz" -C "$WORK/source" --no-same-owner
GO="$WORK/sdk/go/bin/go"
export GOTOOLCHAIN=local GOENV=off GOWORK=off GOFLAGS='' CGO_ENABLED=0 GOOS=linux GOARCH=amd64
export GOMODCACHE="$WORK/gomod" GOCACHE="$WORK/gocache" GOSUMDB=sum.golang.org
unset GOROOT GOPATH GONOSUMDB GOPRIVATE GONOPROXY GOINSECURE GOEXPERIMENT GOTMPDIR
[[ $("$GO" version) == 'go version go1.25.14 linux/amd64' ]]
cd "$WORK/source/gobgp-4.10.0"
git apply --check "$PATCH"
git apply "$PATCH"
# Patch failure is fatal; never silently build the upstream unpatched daemon.
GOPROXY=https://proxy.golang.org timeout 900 "$GO" mod download
GOPROXY=off timeout 120 "$GO" mod verify
GOPROXY=off timeout 1200 "$GO" build -p=2 -mod=readonly -trimpath -buildvcs=false \
  -ldflags '-buildid= -X github.com/osrg/gobgp/v4/internal/pkg/version.METADATA=hemlock-ibgp-ttl1' \
  -o "$WORK/gobgpd" ./cmd/gobgpd
[[ $("$WORK/gobgpd" --version) == 'gobgpd version 4.10.0+hemlock-ibgp-ttl1' ]]
mkdir -m 0700 "$OUTPUT"
install -m 0755 "$WORK/gobgpd" "$OUTPUT/gobgpd"
install -m 0644 LICENSE "$OUTPUT/LICENSE.GoBGP"
SOURCE_SHA="$SOURCE_SHA" GO_SHA="$GO_SHA" PATCH="$PATCH" OUTPUT="$OUTPUT" python3.13 - <<'PY'
import hashlib,json,os
from pathlib import Path
out=Path(os.environ['OUTPUT'])
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
report={'gobgp_version':'4.10.0+hemlock-ibgp-ttl1','go_version':'1.25.14','target':'linux/amd64',
        'gobgp_source_sha256':os.environ['SOURCE_SHA'],'go_archive_sha256':os.environ['GO_SHA'],
        'patch_sha256':sha(os.environ['PATCH']),'binary_sha256':sha(out/'gobgpd')}
(out/'build-report.json').write_text(json.dumps(report,indent=2)+'\n')
print('Verified GoBGP build SHA256:',report['binary_sha256'])
PY
