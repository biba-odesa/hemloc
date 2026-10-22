# Process-local observations (Hemlock 0.2.1)

Current GoBGP RIB, peers/Adj-RIB-Out, reconciliation results, peer reachability,
synchronization diagnostics and worker errors are held in the application process's
RAM. No tmpfs, mount, new dependency or configuration key is required. The cache
keeps only the latest value for each fixed observation key. Access is protected by
a lock; readers and writers receive independent snapshots rather than shared
mutable dictionaries. The one-process background-task ownership rule is unchanged.

These observations are not replicated or written into SQLite. Historical local
rows left by an older version are ignored, including after backup restoration;
they are not automatically deleted. Existing backups can still contain these old
rows. Restarting the application starts with an empty cache. Until a successful
GoBGP observation, routes/RIB/export remain Unknown rather than Applied/Exported.
The existing 45-second RIB freshness threshold and real errors still apply. Sync
cannot be green until the current process has successfully contacted its peer.
The existing 3-second reconciliation and 15-second BGP observation intervals are
unchanged. Every reconciliation still queries actual GoBGP; protection, ownership,
attributes, additions/withdrawals and restart recovery behavior are unchanged.

## Durable state

SQLite remains authoritative for rules, users/credential versions, audit,
sessions/login limits, history and journal cursor, local protection/cache refresh
schedule, security outbox and cursor/generation acknowledgements, retention plans,
progress and schedule, snapshot backup metadata, and the replication journal.
Nothing here weakens synchronous=FULL, prunes the journal or runs VACUUM.

The last acknowledged peer history/sequence stays durable. Its `at` field now
means the time that acknowledgement last changed; current contact/freshness comes
from the RAM peer observation. Equal acknowledgement/local values and unchanged
metadata are not rewritten. Real changes still use the existing transactions.

A separately invoked maintenance CLI cannot read the running process's RAM.
Before `audit prune --execute`, the CLI therefore probes the configured peer's
status directly, using authenticated, CA-validated HTTPS and no proxy, and checks
identity. The existing protocol/caught-up/pending-outbox checks still gate the
transaction. Unavailable/incompatible/lagging peers block deletion. Preview and
export do not require the observation cache or a peer probe. Persistent cursors
are not reset to work around an empty cache. Manual route drain still queries
actual GoBGP and requires the application to be stopped.

## Upgrade and rollback

There is no wire-protocol/schema bump or config migration. Upgrade either node to
the same reviewed commit; rolling 0.2.0/0.2.1 operation is tested. Existing
retention/notifications/announcement settings and the local notification handler
must be retained. No configuration feature is enabled by this update. Keep the
existing paths/service name, TLS capability override and route-owner identity.

Build the wheel from a clean `git archive` of the approved commit, install build
requirements from requirements-build.lock if needed, and prepare a wheel of the
previous source revision before replacement. Stop only the application, create a
normal CLI SQLite backup, install the new wheel in its existing venv, run pip
check and verify the installed version with `python -I`. Start only the same
application service and verify HTTPS and fresh zero-lag replication. Never run
init-db or create a new administrator on the slave. Do not restart GoBGP.
Version 0.4.0 uses the canonical installation and peer header. The historical
rolling checks below describe the observation-cache change, not compatibility of
0.4.0 with previous HTTP endpoints. Follow MIGRATION_LEGACY.md for existing nodes;
use LIFECYCLE.md for subsequent compatible canonical updates. On installation
failure use the reviewed rollback plan, not an automatic database replacement.

## Verification and limits

Unit/integration checks cover no SQLite access during observation get/set,
independent concurrent snapshots, cold startup/backup and ignored old rows,
Unknown/Stale/error/recovery, preserved durable acknowledgements, restart/replay,
protection, outbox/promotion and CLI live-peer cleanup gating. Real loopback HTTPS
checks exercise snapshot/prune/journal/outage/restart and a mixed-version pair;
browser fixtures cover both themes. All mutations use isolated data and fake
notification executables; the active Talk handler is never invoked by tests.

`python -m tools.check_observation_cache --cycles 50 --directory var` compares
baseline commit 00dea5b and new code on temporary synthetic disk-backed databases
with 664 routes. On this VM the initial run recorded 34,521,088 versus 13,107,200
physical write bytes (62.03% less), 4.614 versus 3.511 seconds wall time, and
3.462 versus 3.444 seconds CPU. It is an accelerated synthetic loop, not a daily
production forecast. The remaining writes include SQLite/filesystem overhead and
durable metadata. On tmpfs `/proc/self/io` physical writes may be zero; logical
write counters are also reported. Cache memory grows with the current RIB/export
size and concurrent readers, not observation history. This change is primarily a
disk-write reduction, not the separate parsed-network/protection-index CPU cache.
