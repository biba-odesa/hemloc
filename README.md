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

## Debian 13 installation (0.4.0+)

Canonical paths and identities: `/opt/hemlock` (code/venv), `/etc/hemlock`,
`/var/lib/hemlock`, user/group `hemlock`, `hemlock.service`, CLI/package `hemlock`.

- [Fresh master: step-by-step Russian guide](docs/DEPLOYMENT.md)
- [Fresh slave and secure pairing](docs/INSTALL_B.md)
- [Root installer](deploy/install-debian13.sh), with `--help` and read-only `--check`
- [Update, backup, rollback and manual role changes](docs/LIFECYCLE.md)
- [Existing pair: retain master, install slave afresh](docs/PAIR_UPGRADE_040.md)
- [Explicit existing-master path migration](docs/MIGRATION_LEGACY.md)

Install Git before cloning. Select an immutable published 0.4.0+ tag or full
commit, verify it, then run the installer with the role, unique node/peer IDs,
route owner, separately verified patched GoBGP binary and SHA256. The installer
refuses existing installations; it does not initialize data, generate secrets,
create an administrator, enable/start units or enable announcements. Prepare
TLS, peer parameters, protection and approved route attributes before startup.
Only the master creates the first administrator. Historical tags remain unchanged.

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
sudo /opt/hemlock/.venv/bin/hemlock --config /etc/hemlock/hemlock.ini user create operator --role admin
sudo /opt/hemlock/.venv/bin/hemlock --config /etc/hemlock/hemlock.ini user reset-password operator
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

Version **0.4.0** removes prior aliases and uses canonical names throughout.
Peer-header and cookie naming changes require a coordinated two-node migration;
a mixed 0.3.x/0.4.0 pair cannot replicate. Existing node IDs, route owners, secrets,
protection and data are preserved by the explicit migration procedure.
Synchronization is green only for fresh **In sync** with zero lag, otherwise red.

Hemlock 0.2.1 keeps current operational observations in process memory; see
[observation storage and rolling upgrades](docs/OBSERVATIONS.md).

Version 0.3.0 adds [resumable startup role transitions](docs/ROLE_TRANSITIONS.md).
A deliberate master-to-slave change resets active replicated data after backup
and fences routing until dedicated GoBGP cleanup is verified. Upgrade both nodes
before using this workflow; ordinary role-preserving restarts retain their data.

## Updating a canonical installation

Run `./update.sh --version TAG_OR_FULL_COMMIT` as root from its trusted Git checkout
for a fixed update, or `./update.sh` to fetch the latest main. FETCH_HEAD is used,
so origin/main is not required. The updater validates the current canonical
installation and unchanged role/node before stopping only hemlock.service. It
keeps a private SQLite backup and build staging directory. Failed updates stay
stopped for recovery, not an automatic launch of a partial package. GoBGP is not
restarted. Follow [LIFECYCLE.md](docs/LIFECYCLE.md); previous installations require
[MIGRATION_LEGACY.md](docs/MIGRATION_LEGACY.md) first.
