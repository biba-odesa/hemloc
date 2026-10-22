# Startup role transitions — 0.3.0

This version must be installed on both nodes before deliberately changing roles.
An operator selects and isolates the authoritative master. There is no automatic
promotion, demotion, winner selection or branch merge. Never run two writable
masters with production BGP connectivity. A network partition cannot prove the
absence of another master. Reachable master/master peers report a role conflict;
masters refuse incoming snapshots/journal. Normal master/master and slave/slave
restarts keep their database. A normal slave continues using saved data when its
master is unavailable.

## Slave to master

Startup retains rules, users, audit, local protection and pending security facts.
The existing transactional promotion creates a new history UUID and active
sequence namespace. Rather than delete the previous active journal, it is renamed
to a unique `journal_history_<UUID>` table and recorded in `journal_generations`.
It remains local and in database backups; it is not merged or replayed as the new
history. Pending local auth/security facts are published by the existing promotion
logic. Repeated master starts do not create another generation. No GoBGP lifecycle
operation is performed.

## Master to slave

Changing INI role alone takes effect on the next application startup. Before
ordinary background tasks or web startup, compare saved node identity/role with
the loaded local config. A direct Store activation cannot silently demote a DB.

1. Persist a service-owned 0600 `<database>.role-transition.json` fence in the
   database directory. It contains a unique transition ID, paths, phase, preserved
   local protection/cache schedule, checksums and cleanup requirement. It is never
   replicated, exported through the web, or committed to Git. Existing writes via
   Store transactions are fenced; stop other maintenance/SQLite clients too.
2. On the **dedicated Hemlock GoBGP**, discover global RIB paths for IPv4 and IPv6.
   Delete discovered local paths individually using explicit observed protobuf
   paths, including paths with a different/missing owner. Verify both-family RIB
   is empty. A nonlocal/ambiguous path, partial delete, inspection failure or
   nonempty final result cannot certify cleanup. No empty/global DeletePath call,
   peer reset, daemon stop/start/restart or policy edit is sent.
3. Check free space and permissions, truncate/checkpoint WAL, switch the detached
   old file to DELETE journal mode under SQLite's lock and close the connection.
   Busy readers/writers or remaining WAL/SHM stop progress. The closed old file is
   moved without overwrite to `<database>.backup-<UTC timestamp>-<UUID>`. The
   recoverable hard-link/unlink move retains the same inode, not a copy of an open
   SQLite file. Source checksum and directory fsync guard resume.
4. Create a private staging SQLite DB with the same local node ID and role=slave.
   Only `protection` and `protection_schedule` are carried over. Old rules, users,
   audit, sessions, journals, outbox and peer cursors are retained only in backup.
   The fresh slave has no master history/cursor yet and accepts a normal validated
   snapshot/journal from its configured master. Its security outbox is a new local
   generation; old browser sessions cannot survive.
5. Checkpoint/close the staging DB and install it without overwrite. Config,
   TLS, replication secret, node ID and route-owner identity are not modified.
   Protection is still the union of local config and the retained accumulated
   cache; unavailable IRR does not remove it. Protected ASN readiness still gates
   normal additions.

The phases are `prepared`, `drain_attempted`, `checkpointed`, `backed_up`,
`new_ready`, `db_ready`, `complete`. Each state write uses a unique private temp
file, file fsync, atomic replace and directory fsync. Failed operations do not
start the old data's workers. Power loss before/after each stage, including between
link and unlink, is resumable using the same unique backup. A completed transition
is not repeated at restart. A pending transition with config role changed back to
master blocks startup until the documented restore/reset procedure is completed.
Do not delete the fence or copy an old DB over it to bypass these checks.

Files must be regular, owned by the service UID and mode 0600; the parent must be
writable/searchable. The conservative free-space check reserves the current DB
size + WAL size + 16 MiB. Check again before checkpoint. An I/O/space/permission
failure prevents activation; restore space/permissions and restart the application
to resume. Backups are never overwritten. Protect the marker/backups as carefully
as the DB, as they contain private network metadata. Existing SQLite sidecars must
not be manually removed while any client is using the database.

## Absent versus unreachable GoBGP

A gRPC exception, timeout, refused port, stale cache or empty cached RIB **alone**
is not evidence that the daemon is stopped. A separate read-only probe requires
all of:

- `systemctl show` on the configured `[gobgp] gobgp_service_unit` (default
  `gobgp.service`) succeeds with loaded / inactive / dead / MainPID=0 / ControlPID=0;
- an unrestricted readable host `/proc` view, PID 1 named systemd/init, and no
  independently started canonical `gobgpd` process;
- every resolved loopback endpoint refuses TCP connection. Accepted connections,
  timeouts, permission errors and unreachable addresses are not absence.

This is evidence about the configured dedicated daemon on the standard Debian
systemd host. Custom launchers/names, missing unit, process-namespace restrictions,
hidepid, unreadable process table, failed/auto-restarting units or status-probe
errors leave the state **unknown**. Read-only systemd status requires no sudo,
root helper, control permission or sandbox relaxation. The application invokes
only `systemctl show`, never service state changes. All route operations remain
through local gRPC. The detector does not promise to discover arbitrary hidden or
misconfigured alternative daemons.

If absence is confirmed, DB replacement proceeds but remains `db_ready` with
`cleanup_required=true`, and web/API shows cleanup pending/unavailable. Snapshot
synchronization may proceed. Reconciliation first retries the pending dedicated
drain; it cannot apply even the new desired set before a fresh empty-RIB check.
`GoBGP.add` independently checks the fence immediately before additions. The fence
survives restart and lives outside the replaced DB. After gRPC recovers, stale
paths are withdrawn before current slave routes are applied. Pending cleanup
suppresses Applied/blocked-success counters even if an observed old path matches.

If gRPC is uncertain or withdrawal fails during the initial transition, startup
fails with the fence intact and old DB inactive. Inspect application logs and
`transition status`; fix the cause and restart only Hemlock. If recovery is pending
on an already installed fresh slave, the web remains available and routes stay
fenced while retries continue. There is no claim that any remote router accepted
a withdrawal merely because the local RIB is empty.

**Dedicated-daemon exception:** startup master→slave is an explicit cleanup action
selected by the role change, including when `announcements=no`. In all ordinary
operation, announcements=no still performs no route writes and retains existing
paths; `routes withdraw-owned` still withdraws only owned paths. Outside a pending
startup transition, ownership restrictions are unchanged.

## Inspection and offline rollback

Run CLI as root using the installed venv/config. It drops to the database/state
owner and does not gain service-control privileges:

```bash
/opt/hemloc/.venv/bin/hemloc --config /etc/hemloc/hemloc.ini transition status
```

Rollback returns data to the time of the old backup. First select one authoritative
master and isolate BGP/other master as required; the app does not perform network
isolation. Stop Hemlock and all other SQLite/maintenance clients. Set local
role=master in INI, retaining node ID/owner/TLS/auth configuration. Do not downgrade
to a version that ignores the fence while cleanup is pending.

The following are **operator commands**, never automatically executed by the app.
Replace DATABASE/BACKUP with the exact status output's local paths. Preserve the
current DB and sidecars together before placing a closed backup. Do not delete or
reuse current WAL/SHM alongside the restored file. The backup created by this
transition is checkpointed, closed and has no sidecars.

```bash
systemctl stop hemloc
# Set role=master in the local INI; recheck root:hemloc 0640 after editing.
DATABASE=/var/lib/hemloc/hemloc.sqlite
BACKUP=/var/lib/hemloc/hemloc.sqlite.backup-UTC_TIMESTAMP-TRANSITION_UUID
if test -e "$DATABASE"; then
  /opt/hemloc/.venv/bin/hemloc --config /etc/hemloc/hemloc.ini \
    transition checkpoint --execute
fi
SAVED=$(mktemp -d "${DATABASE}.before-restore.XXXXXX")
chown hemloc:hemloc "$SAVED"
for FILE in "$DATABASE" "$DATABASE-wal" "$DATABASE-shm" "$DATABASE-journal"; do
  if test -e "$FILE"; then
    mv -n -- "$FILE" "$SAVED/"
  fi
done
install -o hemloc -g hemloc -m 0600 "$BACKUP" "$DATABASE"
/opt/hemloc/.venv/bin/hemloc --config /etc/hemloc/hemloc.ini \
  transition reset-after-restore "$BACKUP"
/opt/hemloc/.venv/bin/hemloc --config /etc/hemloc/hemloc.ini \
  transition reset-after-restore "$BACKUP" --execute
systemctl start hemloc
```

Stop if any command fails. Checkpoint/close all clients **before** moving files.
Never reuse SAVED or overwrite an existing recovery file. The first reset command
is a dry-run. The reset requires the owner lock (application stopped), configured
master role, matching saved node identity/master role, no WAL/SHM on either file,
and byte-for-byte equality of the restored DB and selected backup. It modifies
only the external fence to `restored`, not the DB. No merge or automatic choice of
authoritative history occurs. Review HTTPS, generation/cursors, protection and
local/peer routes before restoring BGP connectivity. If no backup was created yet,
repair the failure and resume demotion rather than deleting the marker.

## Short A/B update procedure (prepare only)

Do not run against production until this local commit has been reviewed and
published or a verified wheel has been separately transferred. Update slave B,
then master A, keeping their existing roles throughout the update. Do not copy
configs/databases between nodes. Verify ordinary restarts preserve history,
cursors, protection and BGP. Change roles only after both run this version.

On each node use its actual Git source checkout (the installed /opt/hemloc may be
only a venv/source copy), root shell, and a fixed approved commit:

```bash
cd SOURCE_CHECKOUT
git status --short
# Stop for unexpected tracked changes. Configure this shell's download proxy if needed.
git fetch origin main
STAGE=$(mktemp -d /var/tmp/hemlock-update.XXXXXX)
git archive APPROVED_COMMIT | tar -x -C "$STAGE"
/opt/hemloc/.venv/bin/python -m pip install --require-hashes \
  -r "$STAGE/requirements-build.lock"
/opt/hemloc/.venv/bin/python -m pip wheel --no-deps --no-build-isolation \
  --wheel-dir "$STAGE/wheels" "$STAGE"
systemctl stop hemloc
/opt/hemloc/.venv/bin/hemloc --config /etc/hemloc/hemloc.ini backup \
  "/var/lib/hemloc/before-0.3.0-$(date +%Y%m%d-%H%M%S).sqlite"
/opt/hemloc/.venv/bin/python -m pip install --no-deps --force-reinstall \
  "$STAGE/wheels/hemlock-0.3.0-py3-none-any.whl"
/opt/hemloc/.venv/bin/python -m pip check
/opt/hemloc/.venv/bin/python -I -c \
  'import hemlock; print(hemlock.__version__); assert hemlock.__version__ == "0.3.0"'
systemctl start hemloc
systemctl is-active hemloc
```

Prepare the previous source wheel and normal SQLite backup before replacing the
package. Keep the existing HTTPS port capability override and local Talk handler.
No feature is enabled by this update. No daemon restart or network change is
required. Review the optional read-only `gobgp_service_unit` default if your daemon
has a different unit name. A global reset/drain is never a normal restart action;
it requires detecting saved master → configured slave or resuming its marker.
