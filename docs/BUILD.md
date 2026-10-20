# Reproducible release builds

Target: Debian 13, CPython 3.13, Linux amd64. Build artifacts stay under ignored
var/ and are never installed by this procedure. Build the application and GoBGP
separately; neither command starts a daemon, changes a service or contacts a BGP
peer. Reproduction is byte-for-byte within the pinned toolchain/target environment,
not a claim of identical output across arbitrary Python, zlib or CPU targets.

## Python environment and artifacts

```bash
python3 -m venv var/build-venv
var/build-venv/bin/python -m pip install --require-hashes --only-binary=:all: -r requirements-build.lock
var/build-venv/bin/python tools/build_release.py --ref v0.1.0 --output var/release-python
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

## GoBGP with the explicit internal-peer TTL patch

The gRPC API is GoBGP 4.10.0 only. The patch honors configured multihop TTL for
internal peers while retaining TTL-security precedence and external default TTL.
The version string is 4.10.0+hemloc-ibgp-ttl1. Do not substitute a different major
API or assume an unpatched build has identical internal-peer socket behavior.

Download the pinned archives into an ignored directory and verify these SHA256s:

| Input | URL | SHA256 |
| --- | --- | --- |
| GoBGP v4.10.0 source | https://codeload.github.com/osrg/gobgp/tar.gz/refs/tags/v4.10.0 | 27d8ef958100557344be98e459fa43a20d2a15b5ce943d2aed2772958a3bf397 |
| Go 1.25.14 linux-amd64 | https://go.dev/dl/go1.25.14.linux-amd64.tar.gz | a21ae5633a269bcd7e90cf767e48225633795e99d831742cbf3397064fee7712 |

```bash
var/build-venv/bin/python tools/build_release.py \
  --ref v0.1.0 --output var/release-full \
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
a running GoBGP binary just to update Hemloc or its rules. A second node follows
INSTALL_B.md for the application and this separate build procedure for GoBGP.

GoBGP's unmodified Apache-2.0 license accompanies the patch. Preserve its license
and the applicable transitive-module notices if redistributing a built binary;
THIRD_PARTY.md distinguishes those components from Hemloc's MIT license.
