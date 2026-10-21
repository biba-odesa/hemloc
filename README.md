# Hemlock

Hemlock manages IP-address and network blocking through GoBGP on Debian 13.
It runs as one unprivileged Python application: FastAPI, embedded HTTPS Uvicorn,
SQLite, local web assets, background tasks and a maintenance CLI. No reverse
proxy, external database or task queue is required.

## Features

- ASN expansion through IRR/bgpq4, retained successful sets, scheduled refresh
  and explicit approval for empty or anomalous changes.
- IPv4/IPv6 manual rules, canonical validation, transactional duplicate guards,
  overlapping independent reasons and protection-aware coverage badges.
- Master/slave snapshots and journal replication over authenticated verified
  HTTPS, with manual promotion and no automatic branch merge.
- Local protection, owned-route gRPC reconciliation and safe disabled-announcement
  defaults. Existing routes remain when announcements=no; withdrawals are explicit.
- English Dashboard with sortable/paginated routes, provenance and local/export
  observations; Info in English, Russian and Ukrainian.
- Admin/guest authorization, Argon2id, server sessions, CSRF, throttling,
  current-password changes and private cross-node successful-login history.

A local RIB or export observation never proves acceptance by a remote router.
Application defaults and all shipped examples are for documentation/testing:
replace addresses, ASNs, protection and route attributes before deployment.

## Install from the release tag

```bash
git clone --branch v0.1.0 --single-branch https://github.com/biba-odesa/hemloc.git
cd hemloc
python3 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements.lock
.venv/bin/python -m pip install --require-hashes -r requirements-build.lock
.venv/bin/python -m pip install --no-build-isolation --no-deps .
.venv/bin/python -m pip check
.venv/bin/python -m hemloc --help
```

Install only after reviewing [Debian deployment](docs/DEPLOYMENT.md). Prepare
node-specific configuration, TLS, protection and GoBGP separately. Nothing here
automatically creates users, starts services or configures BGP neighbors. The
[second-node guide](docs/INSTALL_B.md) also clones this repository at v0.1.0.

## Build and verify

[BUILD.md](docs/BUILD.md) pins the Python build tools, GoBGP 4.10.0 source,
Go toolchain and TTL patch, and builds twice from independent Git exports.
GoBGP binaries are generated locally; they are never stored in ordinary Git.
Runtime and test requirements are pinned with hashes. For tests:

```bash
.venv/bin/python -m pip install --require-hashes -r requirements-test.lock
.venv/bin/python -W error::ResourceWarning -m unittest discover -s tests -v
.venv/bin/python tools/check_artifacts.py
.venv/bin/python -m tools.check_history
```

Browser tools additionally require a local Chromium executable. Live GoBGP tests
are opt-in and must target isolated loopback daemons. Integration and reproducible
build results are recorded in [VALIDATION.md](docs/VALIDATION.md), with limits in
[PLAN.md](docs/PLAN.md). Read these before enabling real announcements.

## Operations

- [Configuration/API baseline](docs/VERSIONS.md), [specification](docs/SPEC.md)
- [TLS, backup/restore, failover and owned-route withdrawal](docs/OPERATIONS.md)
- [Rule identity and coverage](docs/RULES.md), [interface](docs/UI.md)
- [State and private login history](docs/ACCOUNTS_UI.md), [Info](docs/INFO.md)
- [Publication checks and history policy](docs/PUBLICATION.md)

Passwords are 6–1024 characters, with at least one letter and one digit; symbols
are optional. Root maintenance uses interactive double entry, never passwords
in argv:

```bash
sudo /opt/hemloc/.venv/bin/hemloc --config /etc/hemloc/hemloc.ini user create operator --role admin
sudo /opt/hemloc/.venv/bin/hemloc --config /etc/hemloc/hemloc.ini user reset-password operator
```

## License

Hemlock is MIT licensed, copyright biba-odesa. See [LICENSE](LICENSE).
The GoBGP TTL patch includes upstream Apache-2.0 material; its license and
attribution remain in [deploy/patches](deploy/patches/README.md). Dependencies
retain their respective licenses; see [THIRD_PARTY.md](THIRD_PARTY.md).

History has separate Blocklist changes, Users & access, and Errors & security
views. Optional master-owned audit retention and best-effort external-script
notifications are disabled by default. See [audit operations](docs/AUDIT_RETENTION.md)
for the two-node upgrade gate, exact dry-run plans, latest-five-login protection,
transport-data limitations and script sandbox requirements. No working cleanup or
notification delivery is enabled by installing the source alone.

The sign-in screen keeps the workspace hidden until authentication. Blocked IP
list accepts comma/newline batches with independent commits and explicit partial
results; [batch input and limits](docs/BATCH_INPUT.md) documents retry, audit and
single-message notification behavior. The updated light theme uses blue surfaces;
the dark palette is retained.

The corrected name is **Hemlock** (Python package/CLI `hemlock`, version 0.2.0).
Existing active `hemloc` directories, user/service, CLI alias and wire identities
are retained for safe upgrades. See [compatible rename](docs/RENAMING.md); do not
mass-rename an existing deployment or use the historical v0.1.0 tag for this update.
Synchronization is green only for fresh **In sync** with zero lag, otherwise red.
