# Reproducible release builds

Target: Debian 13, CPython 3.13, Linux amd64. Build artifacts stay under ignored
var/ and are never installed by this procedure. Build the application and GoBGP
separately; neither command starts a daemon, changes a service or contacts a BGP
peer. Reproduction is byte-for-byte within the pinned toolchain/target environment,
not a claim of identical output across arbitrary Python, zlib or CPU targets.

## Select a fixed source

Install Git before cloning (root: `apt-get install git python3.13-venv`). Clone
this repository into a build directory, select an independently verified published
0.4.0+ tag or full commit, and keep binaries under ignored var/:

```bash
git clone https://github.com/biba-odesa/hemlock.git hemlock
cd hemlock
RELEASE='<PUBLISHED_TAG_OR_FULL_COMMIT>'
git fetch origin "$RELEASE"
RELEASE=$(git rev-parse --verify 'FETCH_HEAD^{commit}')
git checkout --detach "$RELEASE"
```

## Python environment and artifacts

```bash
python3 -m venv var/build-venv
var/build-venv/bin/python -m pip install --require-hashes --only-binary=:all: -r requirements-build.lock
var/build-venv/bin/python tools/build_release.py --ref "$RELEASE" --output var/release-python
```

The tool requires setuptools 80.9.0 and wheel 0.45.1, exports the selected Git tree
twice to independent directories and compares wheels and normalized source
archives. SOURCE_DATE_EPOCH is the selected commit time. ZIP timestamps follow
that epoch; source tar ownership, timestamps, PAX metadata and gzip timestamps
are normalized. The source archive must contain config examples, systemd units,
locks, documentation, tools and the GoBGP patch. Wheel assets and dependency
metadata are packaged by setuptools. requirements.lock pins runtime dependencies;
requirements-test.lock additionally pins test tooling including its setuptools
dependency. pip check should pass in a fresh dedicated installation.

## Automatic fresh-install build

The fresh Debian installer now calls [build-gobgp.sh](../deploy/build-gobgp.sh)
automatically unless both prebuilt input flags are supplied. No system Go or
prior GoBGP installation is required. It uses the same pinned source/toolchain,
patch and build flags described below. Downloads verify SHA256 before extraction;
module downloads use sum.golang.org, compilation uses GOPROXY=off. Limit: Linux
amd64, two compile jobs, 4 GiB free build space, 2 GiB RAM recommended. Build
failure is fatal; no stock fallback, service start, DB or secrets are created.
The installer retains `/usr/local/share/hemlock/gobgp-build.json` and the upstream
Apache-2.0 license, then removes temporary SDK/module/build caches.

Standalone builder (requires curl, Git, tar, coreutils and Python 3.13):

```bash
bash deploy/build-gobgp.sh --output /ABS/NEW_OUTPUT_DIRECTORY
```

Use `--proxy http://HOST:PORT` explicitly if needed; environment proxies are
ignored. This command builds once. The separate release procedure below builds
twice and compares artifacts. The installer never downloads a moving latest v4.

## GoBGP with the explicit internal-peer TTL patch

The gRPC API is GoBGP 4.10.0 only. The patch honors configured multihop TTL for
internal peers while retaining TTL-security precedence and external default TTL.
The version string is 4.10.0+hemlock-ibgp-ttl1. Do not substitute a different major
API or assume an unpatched build has identical internal-peer socket behavior.

Download the pinned archives into an ignored directory and verify these SHA256s:

Use an explicit HTTPS_PROXY/http_proxy for downloads if required; the INI proxy
is not inherited by curl, pip, Git or Go. A transfer from a trusted builder must
include the independently obtained output SHA256 and build report.


| Input | URL | SHA256 |
| --- | --- | --- |
| GoBGP v4.10.0 source | https://codeload.github.com/osrg/gobgp/tar.gz/refs/tags/v4.10.0 | 27d8ef958100557344be98e459fa43a20d2a15b5ce943d2aed2772958a3bf397 |
| Go 1.25.14 linux-amd64 | https://go.dev/dl/go1.25.14.linux-amd64.tar.gz | a21ae5633a269bcd7e90cf767e48225633795e99d831742cbf3397064fee7712 |

```bash
mkdir -p var/downloads
curl --fail --location --output var/downloads/gobgp-v4.10.0-source.tar.gz \
  https://codeload.github.com/osrg/gobgp/tar.gz/refs/tags/v4.10.0
curl --fail --location --output var/downloads/go1.25.14.linux-amd64.tar.gz \
  https://go.dev/dl/go1.25.14.linux-amd64.tar.gz
printf '%s  %s\n' \
  27d8ef958100557344be98e459fa43a20d2a15b5ce943d2aed2772958a3bf397 var/downloads/gobgp-v4.10.0-source.tar.gz \
  a21ae5633a269bcd7e90cf767e48225633795e99d831742cbf3397064fee7712 var/downloads/go1.25.14.linux-amd64.tar.gz | sha256sum -c -
```

```bash
var/build-venv/bin/python tools/build_release.py \
  --ref "$RELEASE" --output var/release-full \
  --gobgp-source var/downloads/gobgp-v4.10.0-source.tar.gz \
  --go-archive var/downloads/go1.25.14.linux-amd64.tar.gz \
  --gomodcache var/gomod --gocache var/gocache --fetch-modules
```

--fetch-modules explicitly downloads dependencies through the Go module proxy
before the first build; omit it once the verified module cache is complete. Both
compilations then use GOPROXY=off, go.mod/go.sum, go mod verify, CGO_ENABLED=0,
GOOS=linux, GOARCH=amd64, GOTOOLCHAIN=local, -mod=readonly, -trimpath,
-buildvcs=false and an empty linker build ID. The patch is applied in independent
repositories and its two expected changes are checked. Disabling VCS embedding
avoids leaking a parent repository revision and removes checkout-path dependence.
The build report records the target version, epoch, input checksums and matching
output checksums. No binary is added to Git.

Before installing a newly built daemon, test its gRPC API and TTL behavior against
isolated loopback peers using documentation prefixes. Installation/replacement
and any daemon restart are separate operator actions. In particular, never replace
a running GoBGP binary just to update Hemlock or its rules. A second node follows
INSTALL_B.md for the application and this separate build procedure for GoBGP.

GoBGP's unmodified Apache-2.0 license accompanies the patch. Preserve its license
and the applicable transitive-module notices if redistributing a built binary;
THIRD_PARTY.md distinguishes those components from Hemlock's MIT license.

## Verified binary installation (fresh node only)

The builder does not install services. After both builds match, inspect
`var/release-full/build-report.json`, obtain the output digest independently,
and verify it again at the target:

```bash
GOBGP_SHA='<VERIFIED_OUTPUT_SHA256>'
printf '%s  %s\n' "$GOBGP_SHA" var/release-full/gobgpd-1 | sha256sum -c -
var/release-full/gobgpd-1 --version
```

Pass this verified executable and digest to install-debian13.sh. The installer
copies it to /usr/local/bin/gobgpd, installs gobgp.service and the upstream license,
but does not start it or create a real-peer configuration. Never replace an active
GoBGP during an application-only update. No prebuilt binary belongs in Git.
