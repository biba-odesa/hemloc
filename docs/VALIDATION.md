# Release validation and limits

The release is checked on Debian 13 / CPython 3.13 using temporary databases and
isolated loopback services. No existing service, working rule or local production
configuration is changed by the release audit. All examples are documentation
values. Raw runtime reports, screenshots and databases are not shipped.

## Automated and browser checks

The unit/integration suite covers normalized duplicate guards under competing
writers, IPv4/IPv6 protection and cached coverage, all-source provenance, IRR
failures/proposals, roles/CSRF/password policy/session revocation, read-only slave
behavior, snapshot/journal races/replay/promotion, audit redaction, private login
history, proxy bypass and all six route State conditions.

Browser scripts exercise both themes, login and user cards, route sort/filter/
pagination/details, conflict forms/record links, Info translations/local protection
and errors. Real two-node HTTPS checks cover authenticated CA/SAN verification,
existing slave-security-outbox/master-journal facts, outage preservation and
restart catch-up. Live gRPC writes are opt-in and use only isolated GoBGP daemons.

## Build and packaging

The build uses a dedicated hash-pinned environment rather than arbitrary
packages installed in a development venv. Independent wheel/source archives and
patched GoBGP binaries are compared byte-for-byte. Static unit/config checks and
a fresh runtime installation are part of the release review. The source archive
includes templates, locks, units, docs, tools, tests and the TTL patch/license.
See BUILD.md for exact inputs and flags; no ready-made daemon binary is in Git.

## Limits to retain in deployment reviews

- Local GoBGP RIB/Adj-RIB-Out does not prove remote router acceptance or FIB state.
- Manual failover requires isolation of the old master. Role changes alone do not
  suppress stale GoBGP export before a full resynchronization.
- Configuration, certificates, sessions, protection cache and ownership state are
  local. A new node needs explicit local configuration/protection preparation.
- Pagination bounds payload/DOM, but JSON snapshot reading remains linear. Prefix
  indexes avoid all-pairs coverage work; this is not indexed network storage.
- Operators still need backup retention, disk monitoring, schema-upgrade review,
  certificate renewal and deployment-specific policy/security validation.
- A lab test result is not a guarantee for a new production topology. Start with
  announcements disabled; coordinate attributes/protection and validate each node.

The exact successful release commands/results are recorded in PLAN.md. Do not
reuse a lab configuration or point opt-in mutation tests at a working daemon.
