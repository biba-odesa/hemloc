# v0.1.0 release checkpoint

## Implementation and delivery

The existing application is retained: rules and transactional duplicate guards,
protection-aware coverage, paged/sorted Dashboard, private login history,
EN/RU/UK Info, authenticated snapshot/journal replication, CLI, owned-route gRPC
reconciliation and explicit withdrawal. Announcement behavior is unchanged.

The public delivery contains documentation-only infrastructure examples, MIT
license (biba-odesa), upstream GoBGP Apache-2.0 notice, hash-locked runtime/test/
build dependencies, configuration templates, systemd units, maintenance guides,
tests and the GoBGP 4.10.0 internal-peer TTL source patch. No daemon binary is
tracked. INSTALL_B.md uses repository cloning at v0.1.0; GoBGP is built separately.
Internal deployment inventories and working-rule reports are excluded. The
external-source checker requires explicit operator-selected targets.

## Verification completed for this release

- Debian 13 / CPython 3.13.5: unittest discovery with ResourceWarning errors,
  93 tests, 92 passed, one opt-in live GoBGP-write test skipped. It must only be
  enabled against an isolated daemon; this publication does not retest a working
  router or change live routes.
- Real Chromium: Info EN/RU/UK in dark/light themes, six sections, MTR/failover
  wording, English State keys, protection configuration/cache display, bounded
  filtering/pagination, empty results, timezone and mobile layout; no data writes.
- Two independent Python wheel/source builds and two independent patched GoBGP
  builds matched byte-for-byte. GoBGP source and Go 1.25.14 archives were verified
  against BUILD.md checksums; modules verified before offline compilation.
- Fresh isolated runtime venv: hash-checked dependency installation, release wheel
  installation, pip check and CLI help passed. The source archive contains the
  templates, units, locks, documentation, tests, tools and upstream patch/license.
- Systemd templates passed static verification. Local Markdown links resolve.
  Artifact checks found no runtime/private files in publication candidates.

## Publication safeguards and final gate

The original development history was reviewed in full, including removed files
and commit metadata. It contained private operational documents, so it is retained
only as a verified access-restricted local backup outside all outgoing refs.
The clean release continues the existing public initial commit; private commits
must not be ancestors. No force push or backup refs are allowed.

Before sending main and annotated v0.1.0, scan every final reachable object and
commit/tag message, including deployment-specific patterns and an in-memory
comparison with private credential/working-data markers. Recheck remote refs and
abort if they moved unexpectedly. Verify main and peeled tag after publication.
No private comparison values or raw reports belong in Git. PUBLICATION.md records
the repeatable procedure; the exact release identity is provided by the tag.

## Limits and next step

This release audit does not reconfigure or update any installed application,
GoBGP service, working database, account, rule or BGP session. Earlier isolated
replication/gRPC scenarios remain covered by their tools/tests; they are not a
claim that a new deployment is validated. External IRR/metadata reachability and
router acceptance depend on the installation and are not inferred from this audit.

Next operator stage: review INSTALL_B.md and prepare node-specific configuration,
certificates, replication trust and retained protection outside Git. Start a new
node with announcements=no and validate it independently before authorizing BGP.
Existing route withdrawal remains explicit; see OPERATIONS.md. No automatic
failover or remote-router acceptance guarantee is introduced.

## Second-node installation documentation checkpoint

The Russian INSTALL_B.md is now a self-contained operator runbook for the fixed
published v0.1.0 commit. It separates root/operator/CA/Junos actions, package proxy
from application proxy, root-only init-db from master-only account bootstrap,
verified TLS/token preparation, local-only gRPC, independent route ownership,
disabled peers and explicit announcement/router-policy gates. DEPLOYMENT.md now
installs Git before cloning and distinguishes master/slave initialization.

A site-specific companion and verification artifacts stay under ignored var/;
no operational identities, secret values or runtime configuration are public.
The retained protection-transfer gap in v0.1.0 is explicit. A standalone runbook
procedure exports only protection with a read-only SQLite snapshot and imports
through the existing Store API into an offline slave using monotonic union,
preserved success times, identity checks and the application lock. It is not
an invented built-in CLI command, nor a new automatic replication path. Operators
must review that temporary procedure before enabling a newly installed node.

Completed checks for this documentation stage:

- Bash syntax and embedded Python compilation; generated documentation-value INI
  accepted by the actual Config loader; generated all-disabled TOML accepted by
  real GoBGP --dry-run; one-peer edit leaves the other peers disabled.
- Protection transfer on temporary databases: unchanged source, union and replay,
  timestamp preservation, source/digest/schema/canonicalization/readiness checks,
  role/announcements/process-lock gates, snapshot preservation of local cache.
- Real loopback two-node HTTPS scenario: CA/SAN and auth rejection, snapshot and
  journal replay, read-only roles, outage/restart/catch-up, manual promotion and
  old-master state replacement. No existing daemon was used.
- Separate online backup/restore drill: rules/users/password verification/audit,
  history/cursor/protection/integrity and subsequent journal all preserved.
- Synthetic TLS: independent node key/CSR, explicit SAN/EKU/serial signing,
  CA verification and IP-SAN check. Systemd templates pass static verification.
- Independent wheel/source builds match. Archive member/content review excludes
  the private companion, transfer files, runtime artifacts and known operational
  patterns; Git ignores the complete local deployment directory.

Limits: no clean booted Debian VM/systemd deployment was available. System package
installation, real-node addresses/connectivity, service startup/reboot, production
CA certificate issuance and Junos changes are not executed acceptance results.
No second host was contacted. Existing services/configuration were not changed.
The release tag is unchanged; this documentation is a local follow-up commit only.
Next: operator reviews the private runbook, reserves the new owner, approves
protection transfer, prepares TLS/auth and both-direction HTTPS access, then
separately authorizes installation and later BGP activation on the new host.

## Local protection export checkpoint

An operator-authorized read-only export and access-restricted download copies
were prepared outside Git. The standalone exporter was tested again on temporary
databases, including incomplete protection readiness. It can faithfully export
that incomplete state; import still fails closed rather than manufacturing
successful ASN initialization. Details and checksums stay in the private runbook
and ignored local receipt. Working configuration and service identities were
verified unchanged. No working database writes, source queries to initialize
protection, second-host connection, commit or push were performed.

After operator initialization, a fresh read-only export passed strict readiness
and digest validation, plus actual import/replay into a temporary slave database.
Both configured protection identities now have successful initialization metadata.
The restricted download copy was replaced atomically and previous exports were
retained outside Git. Configuration and service identities remained unchanged.
Next: transfer the fresh export securely and import on the stopped new node with
matching configured protection; the real second node was not contacted here.

## Installation-feedback documentation checkpoint

Public and private runbooks now identify A as the CA signer for B, guard received
CSR signing with nonempty/openssl verification checks, and require CA/SAN/key
checks after certificate installation. Wrapped shell commands use explicit
continuations. Every INI edit requires root:hemlock 0640, service-user readability
and parsing checks because editors can replace a file and change its permissions.

The guides distinguish HTTP downloads from bgpq4 TCP/43, master-only blocked-ASN
refresh from both-node protection refresh, retained cache on IRR failure, and
IRR requirements after promotion. New protected ASNs require configuration
rereading and successful initialization before a usable fresh export. A slave
running announcements=yes with router-side per-neighbor DENY-ANY is an explicit
operator-selected validation scenario; documentation does not reset its mode.

Site-specific installation facts and the limits of independent verification
remain only in the ignored private runbook. No working configuration, replication
mechanism, TLS implementation, service or BGP behavior changes in this stage.

Checks for this follow-up: Bash/Python syntax in both runbooks; no wrapped inline
commands; actual documented TLS signing on temporary files (valid CSR succeeds,
empty and malformed CSR fail before certificate creation); CA/SAN/key checks,
including wrong SAN and mismatched-key detection. The documentation harness also
passes temporary protection transfer/replay/lock/readiness tests, Config loading,
GoBGP dry-run and single-peer edits. No working certificates were issued here.

## Future tasks (not implemented in v0.1.0)

- Native slave bootstrap command: verified protection-only export/import,
  monotonic cache/timestamp preservation, node/config checks and idempotent
  offline initialization. Do not copy working databases or invent readiness.
- Explicit self-signed peer enrollment: independently verify certificate identity,
  SAN/validity and out-of-band fingerprint, then persist the approved fingerprint
  with an explicit rotation process. Never implement trust through verify=False
  or silently accept a changed certificate. Current CA/TLS validation remains
  mandatory until a separately reviewed feature implements this workflow.
- Reduce manual installation actions: validated preflight and staged provisioning
  for proxy/network prerequisites, ownership/permissions, CSR/certificate checks,
  protection readiness and replication. Keep service/BGP activation as explicit
  operator gates; do not expose secrets in arguments or reports.


## Documentation publication checkpoint

Only public installation documentation and planning notes changed after v0.1.0;
the application source, dependency locks and deployed runtime are unchanged.
The local operational checkpoint is retained only in ignored private records,
not in outgoing public documentation. Current follow-up checks cover documentation
syntax/links, temporary protection/configuration scenarios and full-history
artifact/secret/site-pattern review. Private deployment instructions, runtime
data and migration lists remain excluded. Publish main only; retain the existing
v0.1.0 tag target. Production service changes are outside this publication.

Publication verification passed: 93 tests discovered, 92 passed and one opt-in
live-daemon test skipped; isolated documentation/protection/configuration checks
passed. All reachable history and metadata passed artifact, operational-pattern,
private-value and migration-data comparisons without reporting matched values.
No booted second VM, production-router acceptance or runtime update is claimed.

## Protection IRR diagnostics follow-up

Original v0.1.0 resolver/worker/unit sources were checked. A regression reproduces
the absence of protection failure logs in that tag. The source change preserves
safe family/exit/timeout/errno/error-category context and emits bounded journal
messages without raw subprocess text, credentials or tracebacks. Schedule/cache
semantics stay unchanged: one-hour persisted retry, 30-day success, monotonic cache
and error clearing only after successful refresh. Empty single-family responses
are tested with real bgpq4/loopback IRRD and accepted with a nonempty other family.

A standalone read-only diagnostic helper works with the original installed
resolver; site-specific copyable stdin commands/results stay in ignored var/.
It reports actual process status, selected unit properties and read-only retry
metadata. It does not enter the service sandbox or claim to reproduce a remote
host's failure. No second-host access, working DB/cache writes, service restart,
GoBGP/rule/config change or deployment is performed in this follow-up.
See IRR_DIAGNOSTICS.md for interpretation and verification limits.

Verification: 101 tests discovered, 100 passed, one opt-in GoBGP test skipped.
The no-log regression fails on an isolated export of v0.1.0 and passes after the
change. The probe works with unmodified v0.1.0 modules and real bgpq4 against a
loopback IRRD; a read-only invocation against the existing local installation
also succeeds. That local result does not establish the affected node's cause.

Next: operator runs the prepared probe on the affected node and reports its
redacted result. Determine the node-specific cause from that evidence. Deploy
the diagnostic logging only in a separately authorized update; do not clear
protection or its recorded error to manufacture success.

## History retention investigation and proposal

Read-only aggregate measurements and a site-specific summary were saved only in
ignored var/. No HTTP requests, working Store initialization, database writes,
deletion, VACUUM/checkpoint, service restart or second-node access was used.
Counts were cross-checked across action/result/date/category totals; logical
audit JSON bytes are distinguished from shared-table allocation and journal copies.

AUDIT_RETENTION.md proposes separate changes/security/auth lifetimes, a persisted
daily master job, dry-run-first CLI export/prune, default Changes History filtering
with SQL pagination and last-five-login exemptions. It explicitly requires a
versioned maintenance operation, snapshot/prune receipts, security outbox
acknowledgments/floor handling and mixed-version gates. Current append-only audit
deletion prohibition remains intact; no retention feature or CLI is implemented.
Journal lifecycle and file shrinkage are not misrepresented as audit deletion.

Next: review the proposed policy/protocol, implement and test on isolated nodes,
then present the exact live manifest and exclusions before authorizing any cleanup.
Forbidden actions must continue to create audit events throughout.

## History, retention and external notifications — implementation checkpoint

The preceding proposal is superseded by the implemented policy in
AUDIT_RETENTION.md. Defaults remain disabled; no installed node or working data
was changed, no working prune/notification was run, and no service was restarted.

Implemented:

- Three History tabs with legacy-preserving classification, SQL count/filter/order/
  limit and indexed category/time expressions. Guest can query only blocklist
  history; own-account login history remains separately authorized. Unicode search,
  actor/node/action/result/date filters and clamped pagination are retained.
- Master-only exact-plan audit maintenance, per-category 365/90/7-day cutoffs,
  fixed latest-five identity exemptions, private preview/export/prune CLI,
  short bounded transactions, serialized workers/CLI, persisted progress and daily
  Europe/Kyiv scheduling with DST and one startup catch-up. Unknown events stay.
- Typed audit_prune journal operations, persistent ID/digest receipts, schema-2
  snapshots after pruning, capability negotiation and rejection of legacy pulls
  after maintenance. Ordinary schema-1 operation remains compatible before prune.
  Configured peers must be current, compatible and have drained known security
  outboxes before cleanup. Receipts prevent replay/outbox/promotion resurrection.
- Security transport rows/sequence numbers remain physically retained. Status
  carries security generation/cursor acknowledgment; no pending facts are dropped.
  No journal truncation or automatic VACUUM. Backups/exports remain separate copies.
- Single-attempt external notification executable, exact UTF-8 subject/body stdin,
  bounded in-memory queue and 1–4 workers, no shell, retries or startup replay.
  Master commit-only bulk summaries, changed accepted ASN sets, local login limits
  and aggregated socket-IP suspicious access; no replicated notification duplicates.
  Failures are bounded audit/journal facts and never feed a notification loop.
- Commented configuration, credential-free handler, operations/upgrade/rollback
  limits, README and brief Info EN/RU/UK explanation.

Verification on isolated data:

- Full unittest run with ResourceWarning errors: 122 discovered, 121 passed; one
  opt-in live-target test skipped. Latest source hardening additionally rechecked
  retention/snapshot, CLI and notification suites. No production audit test events.
- Real two-node verified HTTPS test: snapshot before prune plus journal catch-up,
  duplicate replay, explicit rejection of legacy protocol after prune, network
  outage, application restart and catch-up. An intentional rejected protocol
  request creates an audit event and is replicated normally.
- Concurrent SQLite snapshot/prune read transaction; interrupted/rolled-back batch
  then resumed exact plan; advisory-lock exclusion; pending outbox preservation;
  promotion and former-master return with no pruned-ID resurrection; actual Store
  imported from tag v0.1.0 accepts pre-prune state and atomically rejects v2.
- Cutoff boundaries, unknown events, five logins across identities/nodes, disabled
  identity retention, UTC-second expiry vs Kyiv daily/DST slots, startup catch-up,
  rules/users/credential versions/sessions/protection/desired unchanged by prune.
- Real temporary executables: Unicode/quotes/multiline JSON, direct argv, one
  attempt for nonzero/timeout/missing executable, output secrecy, disabled mode,
  queue overflow, one/two-worker limits, aggregation threshold/cooldown, local
  slave alert with no master, bulk summary and unchanged-refresh suppression.
- Real Chromium: admin/guest History and API access, filtering/pagination/empty
  results/details, dark/light, own/slave account. Info EN/RU/UK dark/light retained
  its agreed layout and protection pagination; screenshots stay in ignored var/.
- Separate peer-free GoBGP 4.10.0 process: IPv4/IPv6 attributes, foreign ownership,
  repair, lost-call recovery, daemon restart, protection withdrawal and addressed
  deletion passed. No working daemon, peer or route was touched.

Limitations and next operator action:

- Not deployed. Update slave, then master to the same reviewed commit with both
  features disabled; verify capability/cursors/security ack. Only then enable
  notifications after a fake-handler check and review a real private prune preview
  before enabling master retention. Do not downgrade either node to v0.1.0 after
  pruning. Full commands and exact INI keys are in AUDIT_RETENTION.md.
- Retention pauses for an unavailable/incompatible/lagging configured peer.
  Transport outbox and journal payloads, receipts, backups and exports are not
  compacted. File shrinkage and deletion from old copies are not promised.
- Notification delivery is best effort and pending messages can be lost at process
  stop/crash. Aggregation tracks bounded recent source state and reports at-least
  counts; distributed-source eviction can reduce detection completeness.
- Promotion still requires operator isolation and a caught-up slave. No new
  guarantee is made for operations never replicated before a forced promotion or
  simultaneous restoration of obsolete backups without current receipts.
- Working-data deletion remains unauthorized in this checkpoint. Present the exact
  live manifest/counts/cutoffs/digest separately before any first working cleanup.
  Push and deployment are not performed.

## Pre-deployment sign-in, blue palette and independent IP batches

The preceding retention/notification implementation remains intact and undeployed.
No working node, config, database, audit, daemon or BGP session was modified.

Implemented:

- Initial HTML hides navigation/header/workspace; a dedicated sign-in card uses
  only local SVG/CSS. Startup requests only public boolean session status before
  any authenticated data. Logout immediately hides rows; session-required API
  failures or the 20-second session probe clear content and stop refresh. Native
  autocomplete, keyboard controls, dark preference and mobile layout remain.
- Blue light-theme variables use the agreed surfaces. Dark palette values remain.
  Stronger secondary navigation/input/disabled colors retain readable contrast:
  checked normal text >=4.5:1, input borders/focus >=3:1. Both themes, dialogs,
  coverage badges and mobile login were inspected in real Chromium.
- Multiline comma/newline manual input with one retained comment. Independent
  rule/audit/journal commits, SQLite duplicate constraints, exact per-item outcomes,
  common batch ID, explicit partial/interrupted responses and no implicit subnet
  expansion. Successful fields clear only after confirmed responses; non-applied
  input stays, including after a deliberately lost post-commit response.
- [web] batch_max_items=1000 (range 1..10000), request_max_bytes=2097152
  (16384..16777216). Whole over-limit requests fail before rule writes. Batch
  metadata calls are zero. Processing and coverage preview run in worker threads;
  preview uses the existing index and renders at most 25 rows.
- Successful changes stay in Blocklist changes with batch provenance. One bounded
  reason/count summary covers non-applied items in Errors & security. One originating
  master notification per batch with additions; none on duplicate-only retry or
  slave replay. Expected admin validation/protection errors remain audited but
  do not feed scanning alerts. Protected terminology and semantics are retained.

Verification:

- Full unittest: 131 discovered, 130 passed, one opt-in live-target test skipped.
  Targeted web/batch checks also cover final validation and preview refinements.
  Tests use separate DBs, no working audit mutations and no real Talk script.
- Concurrent/repeated IPv4/IPv6 batches, malformed/host-bit CIDR, protected ranges,
  existing/in-batch duplicates, body/count limits, unavailable metadata, partial
  storage failure and failure to persist the summary. Confirmed results remain
  explicit and data does not roll back across independently committed items.
- Category indexes migrate to the current classifier expression without changing
  audit documents; EXPLAIN verifies indexed filtering on shared and pending sources.
- Actual HTTPS pair: new batch API commits its valid subset, master/slave rule and
  audit state converge and the fake executable receives exactly one batch message.
  Existing snapshot/prune/journal/replay/outbox/outage/restart checks pass. Actual
  v0.1.0 Store compatibility and post-prune rejection remain covered by unit tests.
- Actual Chromium: anonymous initial view and request interception, keyboard Enter,
  autocomplete, both themes, mobile width, retained comment/input, duplicate retry,
  commit followed by deliberately dropped response, safe resend, coverage, logout,
  session expiry and stopped refresh. Info EN/RU/UK dark/light checks pass.
- Isolated peer-free GoBGP 4.10.0 lifecycle runner passes IPv4/IPv6 attributes,
  ownership, repair, lost-call recovery, restart, protection withdrawal and specific
  deletion. It uses its own config/ports; working GoBGP is not inspected or changed.
- Notification test timeout raised from 150ms to 2s to allow actual Python startup
  under concurrent browser load; the sleeping fixture still proves one timeout
  attempt, while success/nonzero fixtures must really execute. Runtime default
  remains 15s. No retry behavior was introduced.

Delivery: publish ordered existing IRR diagnostics, retention/notification and this
follow-up commit to origin/main after artifact, operational-pattern and complete
outgoing-history checks. Preserve v0.1.0 exactly. Deployment is not authorized here.
Next operator action is a separate B-then-A update at one fixed commit, both new
features disabled; validate capability/cursors/security acknowledgments before
notification enablement or exact real prune preview. New batch limits are optional
local [web] entries; defaults work without editing either node's INI. Retention
and notifications remain disabled unless explicitly enabled. See BATCH_INPUT.md
and AUDIT_RETENTION.md for protocol and transport-retention limits.

Publication verification: application commit a05bce77ab2236093a2a395455138156650cb2d8
was sent by ordinary fast-forward push to origin/main, including its preceding
IRR diagnostics and retention/notification commits. The remote main and local
HEAD matched after push. All eight reachable commits/158 unique blobs passed
artifact/secret/operational-pattern review with zero findings. The existing
annotated v0.1.0 object and its original peeled release target are unchanged.
This publication record is a documentation-only follow-up. Neither node has been
updated; the next action remains separately authorized B-then-A deployment with
retention and notifications disabled until the documented validation gates pass.


## Optional privileged HTTPS port in the service template

The tracked Hemlock unit documents two commented opt-in directives:
CapabilityBoundingSet=CAP_NET_BIND_SERVICE and
AmbientCapabilities=CAP_NET_BIND_SERVICE. Uncomment both after the existing empty
capability reset to bind ports below 1024 as the unprivileged service user.
NoNewPrivileges and the rest of the sandbox remain enabled; defaults grant no
capabilities. No sysctl, executable setcap, production unit or runtime changes are
made by this repository update. When changing the actual web port, the operator
must also update the other node's peer_url and verify replication independently.
Static unit verification covers both the default and uncommented opt-in variant.

## Hemlock name correction and synchronization color

Canonical distribution/package/CLI and all product-facing text are Hemlock 0.2.0.
Legacy imports are exact module aliases. Active paths, service/user, node IDs,
route owner, DB/protection, session cookie/theme preference and replication header
remain unchanged for the rolling upgrade. Canonical deploy templates are added;
legacy template filenames remain available. Immutable release history is retained.
See RENAMING.md for the compatibility boundary and old-distribution uninstall.

Synchronization text is green only for a fresh successful In sync / zero-lag
observation. Catching up, unknown/unavailable/stale, unconfigured and conflict are
red. Status text/lag remain visible in both themes; no replication logic changed.

Checks: 133 tests discovered, 132 passed and one opt-in live target skipped;
legacy/canonical import identity and both module launchers; old v0.1.0 Store
compatibility; full retention/outbox/snapshot replay suite; real two-node verified
HTTPS; actual pre-rename slave source rolling compatibility; Chromium corrected
login/title/sidebar/peer name and green/red cases in both themes; separate isolated
GoBGP lifecycle/IPv4/IPv6/ownership/protection check. Only test data is mutated.
A clean exported wheel and isolated installed launchers are checked before A is
updated. Source and rollback wheels exclude untracked/local runtime files.

Operator authorizes installing A and restarting only Hemlock, preserving the
active unit/drop-in and all local configuration. Prepare rollback and a SQLite
API backup, migrate Python distributions, verify canonical/legacy launchers,
HTTPS and replica status without creating a production login. GoBGP is untouched.
B is not contacted; provide a manual same-commit upgrade instruction after push.

### Deployment and publication checkpoint

Source commit de6fa1a0a7ade3e92096d4944744aaa66fda44b4 was built from a
clean tracked export and installed on the authorized existing master as Hemlock
0.2.0. The previous distribution was removed before installing the new one;
legacy CLI and import aliases are verified. A pre-update SQLite API backup and
previous-source rollback wheel are retained locally, outside the delivery.

Verified after deployment: existing service active, HTTPS validated with the
configured CA, corrected page title, replication fresh with matching history and
zero lag. Configuration/unit/drop-ins hashes and working GoBGP PID/start time
were unchanged; replicated documents, identity/cursor and protection were
unchanged during the stopped-service package replacement. Only the application
service was restarted. No production login/test event or rule was created.

Publication checks scan all reachable commits, not only the tree: 11 commits and
265 unique blobs before this checkpoint, zero secret/private-site findings.
Runtime files and local transfer/deployment instructions are excluded. No existing
release tag is moved. The final documentation commit is scanned again before a
normal main push. Next action: operator upgrades the second node using the same
source revision and the existing paths, then verifies the corrected name and
green In sync / zero lag. No feature/config changes are required by this update.

## Local external notification handler checkpoint

An operator-requested, site-local Talk adapter is installed outside the repository
and enabled on the existing master. It consumes only UTF-8 subject/body JSON on
stdin, uses a separate restricted credential file, verified HTTPS and explicit
proxy configuration, refuses redirects and makes one delivery attempt without
retries. Source copies and local test/deployment artifacts are excluded from Git.
No credentials or adapter implementation are added to the public delivery.

Six isolated checks cover Unicode/newlines, inert shell metacharacters, input
validation, single-attempt transport/OCS failures, redirects, explicit proxy and
missing private settings. Installed service-user access and equivalent systemd
sandbox execution are checked with mocked transport and sockets forbidden; no
real test message is sent. Only the application service is restarted to read its
configuration; HTTPS readiness and unchanged GoBGP process are verified.
Actual chat delivery is intentionally untested, per operator instruction. Next:
observe the first genuine event without generating production test events.

## Process-local observations checkpoint (0.2.1)

Implemented a fixed-key, locked RAM observation store with independent copies for
GoBGP RIB/export, reconciliation status, live peer/sync and worker diagnostics.
Store APIs route only these keys to memory; existing on-disk observation rows are
ignored, not removed. Web/presentation use the process cache. Cold startup and
restored old rows cannot claim Applied, Exported or healthy sync. Durable data,
protection, security acknowledgements/outbox, cursors, retention and snapshot
metadata remain in SQLite. Unchanged metadata/local values are not rewritten;
peer acknowledgement persistence occurs only when history/sequence changes.

CLI prune now obtains its own authenticated direct HTTPS peer observation before
the unchanged transactional protocol/cursor/outbox checks. No protocol/schema,
configuration, reconciliation/observation intervals or route behavior changes.
See OBSERVATIONS.md. Fixtures explicitly share a cache only when modeling one
application process. Reopened stores represent cold processes by default.

Checks so far: complete original suite plus new RAM/concurrency/SQL/restart tests;
separate CLI live-peer prune; real verified two-node HTTPS audit workflow;
current master with actual 0.2.0 source slave; browser UI in both themes.
Synthetic 50-cycle/664-route disk-backed comparison: physical writes reduced
62.03%, wall time 4.614 -> 3.511 seconds, CPU essentially unchanged. Active data
and the real notification handler are not used for mutations/tests.

Next: final full suite and isolated GoBGP recovery checks, clean source/rollback
wheels, secret/history scans, commit and authorized normal main push. Only after
successful push install the tested wheel on the existing master, restart only the
application, verify HTTPS/sync/unchanged GoBGP and document the exact result.
No deployment to the second node; provide manual same-commit commands.

Final development verification: 142 tests discovered, 141 passed, one opt-in live
unit skipped; isolated real GoBGP verification passed separately. The full
loopback HTTPS/two-daemon lab passed background reconciliation, slave protection
divergence, daemon restart recovery, auth/CA/SAN rejection, journal replay,
restart, promotion and old-master replacement without restarting GoBGP on failover.
The separate audit workflow, actual 0.2.0 slave rolling compatibility, and both-theme
browser checks passed. A clean wheel installed into a separate venv with the
runtime hash lock passes pip check, canonical/legacy CLI and complete web imports.
Previous 0.2.0 source rollback wheel is prepared locally. Publication/deployment
remain the next authorized actions; no active data was used in these tests.

### Verified master deployment and publication

Source commit bd9c30bbd0420801c62c83842e1b6a2d3abe2da3 was scanned (all
13 reachable commits/287 unique blobs, zero findings) and pushed normally before
installation. The final wheel was built from that committed archive and verified
in a separate locked-dependency venv. The authorized existing master now runs
0.2.1. A normal SQLite API backup and the previous 0.2.0 rollback wheel are kept
locally outside the delivery.

Verified: configured-CA HTTPS; fresh reconciliation status obtained from RAM over
the authenticated local status API; all desired routes confirmed. Existing rules,
users, metadata and protection were unchanged during stopped-service installation.
Config, unit/drop-ins, notification script/private settings and GoBGP process/RIB
were unchanged. Only the application service was restarted; no test login, rule,
notification or retention deletion was generated on the active installation.
Legacy SQLite observation rows were not updated by the new process.

A post-update 60-second passive sample recorded 18.42% of one CPU core, 76.12 MiB
RSS and 4.344 MiB physical writes; the last durable peer acknowledgement matched
history/cursor (zero lag), with no worker-error audit events in the window. This
shorter window is not a controlled comparison with the earlier five-minute sample;
the synthetic comparison above remains the reproducible measurement.

The second node is not changed. Next operator action: update its existing venv
from the same reviewed main history using a clean archive, preserve config/TLS/
owner/protection/notification settings, restart only the application and verify
fresh green In sync/zero lag plus current RIB/export observations. No new config
blocks or enabled features are required. Current/previous versions remain wire
compatible. Existing release tags are not moved.

## GitHub repository URL rename

Operator authorizes renaming the existing GitHub repository from hemlock to
hemlock and updating public links. Repository ID, main, annotated v0.1.0 object
and peeled release commit are checked before/after the in-place rename. A complete
verified local Git bundle and metadata/ref snapshot are retained outside Git.
The local origin points to https://github.com/biba-odesa/hemlock.git.

Public README/deployment/slave-install/publication links use the new URL. Clone
commands explicitly retain their destination directory, so later cd and installed
paths remain correct. RENAMING.md documents existing-clone origin updates without
runtime changes. The ignored local slave guide's repository URL is updated if
present; operational values and the local document remain excluded from delivery.

Verification: new/redirected remote refs match. A fresh bare clone of the
immutable release tag through the new URL resolves to its original peeled SHA.
All four changed clone commands have explicit unchanged destinations and pass
shell syntax validation. Staged content and complete history are scanned before
a normal main push. No application source, dependencies, active
paths, configs, DBs, node IDs, services or BGP sessions are changed. No deployment
or application restart is needed. The second node is not contacted; its operator
can update origin in its existing Git checkout independently.

## Startup role transitions — 0.3.0 development checkpoint

Implemented before normal worker startup: slave-to-master preserves data and
creates a fresh generation, archiving the previous journal instead of deleting
it. Master-to-slave persists a private external crash fence, explicitly drains
IPv4/IPv6 paths on the dedicated daemon, checkpoints/closes SQLite, moves the old
DB to a unique nonoverwriting backup, and installs an empty slave DB retaining
only local protection/cache schedule. Node/route-owner/config/TLS are unchanged.
Old rules/users/audit/sessions/outbox stay in backup and are not transferred.

A conservative read-only absence probe requires inactive/dead configured systemd
unit, zero PIDs, unrestricted host process visibility with no canonical daemon,
and refused loopback endpoints. Unknown gRPC or partial withdrawal fails closed.
Confirmed absence permits DB replacement with durable pending cleanup. Both
reconciliation and AddPath are fenced until recovery drains and verifies both
families empty. No daemon/peer lifecycle operation or root helper is introduced.
Direct Store activation cannot bypass demotion. Ordinary same-role restarts retain
data; ordinary offline slaves retain routes. Masters still reject foreign state.

Documented explicit rollback with transition status/checkpoint/reset-after-restore
commands, owner locking and exact backup validation. Added Info EN/RU/UK, version
0.3.0, optional [gobgp] gobgp_service_unit (default gobgp.service), artifact excludes,
and a short B-then-A update guide in docs/ROLE_TRANSITIONS.md. No wire-protocol or
dependency change. Both nodes must run this version before deliberate role changes;
do not downgrade while a transition fence is pending.

Verification on isolated data only:
- Full suite: 160 discovered, 159 passed, one opt-in live check skipped; real
  isolated GoBGP checks were run separately. CLI follow-up: all 10 passed.
- Crash injection after every persisted phase and both link/unlink boundaries;
  real child-process death during old/staging SQLite transactions and hot-journal
  recovery; busy WAL readers, free-space/permission/backup failures and resume.
- Real peer-free loopback GoBGP: IPv4/IPv6 addressed withdrawal (including other
  local ownership), empty-RIB verification, partial delete failure/resume,
  uncertain gRPC refusal, stopped daemon DB replacement and delayed recovery,
  cleanup before applying only the new slave snapshot. Daemon PID unchanged by
  migration; stopped-daemon evidence is injected from the harness's own process.
- Two loopback HTTPS nodes and separate test GoBGP daemons: replication, offline
  restart, promotion/new history, old-master startup demotion and replacement,
  protection divergence and daemon recovery. No production nodes contacted.
- Actual 0.2.1 slave + new master over verified HTTPS: partial batch journal,
  security outbox, retention-v2 replay and schema-2 snapshot remained compatible.
  This compatibility does not grant old versions the new demotion safeguards.
- Chromium Info EN/RU/UK in dark/light themes, mobile, dynamic local protection
  pagination and route State descriptions passed without production mutations.
- A wheel was built and installed into an isolated existing locked-dependency
  test venv; final package/import/artifact/history results are recorded below.

Production A/B, their configs, DBs, services, BGP and roles have not been changed.
No push or deployment is authorized for this stage. Next: review the local commit,
then separately authorize publication/update; preserve roles during B-then-A
upgrade and validate HTTPS/replication/protection/routes before any role switch.

Final package validation: isolated wheel install, pip check, isolated canonical/
legacy package and full web/transition imports passed (0.3.0). Staged artifact,
secret/operational-pattern and wheel-content scans found zero findings. No
runtime files or private deployment instructions are staged. Full reachable Git
history is scanned before/after the local public-identity commit; values are never
printed. Installation/push remain pending explicit future authorization.

## Runtime version footer

Added a quiet sidebar version immediately above Sign out. Authenticated /api/me
returns local installed hemlock distribution metadata, not checkout/Git data or a
JavaScript version constant. Optional PEP 610 VCS commit metadata is displayed in
a tooltip; ordinary wheels without embedded provenance omit the commit. Missing
installed metadata is explicitly unavailable, never inferred from source version.
Each node supplies its own response. Login/logout hides and clears the footer.

Verification: isolated API/metadata tests (17 passed plus the new guest-specific
API check), real Chromium EN/RU/UK dark/light sidebar positioning and metadata
agreement, signed-out hiding, mobile layout and existing Info checks. Dark/light
sidebar screenshots inspected. No production data, config, service or routes
changed. This UI-only patch retains package version 0.3.0 and does not move its
existing release tag. Operator authorizes a normal main push, not deployment.

## Operator-requested update.sh

Added executable root-level update.sh with the approved update sequence and
/opt/hemlock installation prefix. It fetches refs/heads/main, resolves FETCH_HEAD
(also works without origin/main), archives the exact fetched commit, builds a
wheel, stops only hemlock, takes a SQLite API backup, installs locked dependencies
and the wheel, checks the package, then starts/checks hemlock. Config/database paths
and the existing service name remain hemlock. Bash pipefail prevents an archive
failure from being hidden by tar. The script locates its own Git checkout.

Verified bash syntax and isolated command-stub success/build-failure/backup-failure
paths. A build failure does not stop the service; a backup failure does not proceed
or restart it. No real updater/systemctl/production command was run. An operator
must prepare the /opt/hemlock venv and matching systemd ExecStart before use;
moving a venv alone does not rewrite embedded shebangs. Active paths/configs and
services were not modified. This script follows main, not the immutable v0.3.0 tag.

## Authorized existing-master update to 0.3.0

Operator separately authorized updating the existing master after the slave's
successful manual update. Installed a wheel built from published commit 7795940
and verified first in an isolated venv. Existing installation paths were retained;
the new /opt/hemlock updater was not run against the legacy /opt/hemlock prefix.
Stopped/restarted only the application and made a normal private SQLite backup.

Verified installed runtime metadata 0.3.0, pip check, CA-validated HTTPS and served
version-footer assets; unchanged configured/saved master role, rules/users/local
protection during installation, config/unit/notification file digests, GoBGP PID
and both-family RIB. Fresh background state confirmed the complete desired set.
Live authenticated slave status matched generation/cursor with zero lag. No test
login, notification, rule mutation, role change, GoBGP control operation or path
migration was performed. Private backup paths and detailed results remain only
under ignored var/update-a-0.3.0 and the node's private data directory.

Next: operator can refresh the browser to see the local installed-version footer.
No additional config/role changes are required; deliberate failover remains a
separate operation using docs/ROLE_TRANSITIONS.md. This deployment checkpoint is
recorded locally; no additional publication is required for the installed source.

## Canonical Debian 13 installation — 0.4.0 checkpoint

Standardized package/CLI/user/group/unit and default paths on hemlock:
/opt/hemlock, /etc/hemlock, /var/lib/hemlock. Removed previous wrapper package,
console alias and duplicate deployment templates. Prior names occur only in the
explicit docs/MIGRATION_LEGACY.md procedure, not active defaults/examples. Local
ignored instructions and active installations were not rewritten. No old release
tag is moved. Version 0.4.0 has the canonical peer header/cookie/theme key: mixed
0.3.x/0.4.0 HTTP replication fails authentication, so migrate both nodes in a
coordinated window while preserving their roles/identities/ownership/protection.
Stored journal/schema-2/audit-prune-v2 formats remain unchanged. Explicit HTTPS
mixed-version tests verify rejection without state replacement/role change.

Added deploy/install-debian13.sh: root + Debian 13 + fixed tag/full SHA, explicit
role/node IDs/owner, independently verified GoBGP binary/SHA256 and optional
credential-free download proxy. Git is installed before clone, source is pinned,
venv dependencies use hash locks, code is root-owned/read-only to service UID,
config/data permissions are private. Existing paths/accounts/units refuse rather
than overwrite. HTTPS config remains deliberately incomplete, announcements=no,
next-hops/protected ASN/peers are not inferred. No DB/secrets/admin creation,
unit enable or daemon start. Offline roots install units without daemon-reload;
normal systemd hosts reload definitions only. Errors stop with a bounded message.
The real Debian os-release VERSION collision was found and fixed by using
RELEASE_REF, with a regression fixture containing the real-style VERSION field.

Updated update.sh for canonical installations only, including pre-stop installed
package/config/role/node checks and python -I -m hemlock maintenance calls (avoids
stale moved-venv shebangs). Fetch uses FETCH_HEAD, supports fixed --version or
latest main. Failures after stop do not start an incomplete installation. No path,
role or GoBGP migration is hidden in the updater.

Rewrote public master/slave installation, lifecycle and explicit legacy migration
instructions. Migration discovers the actual service/config first, creates a new
venv/user instead of moving venv, preserves own SQLite backup/local protection,
TLS/node ID/owner/replication settings, never copies another node's working DB,
and documents coordinated start/rollback and pending-fence refusal. Added the
standalone root-only protection_transfer tool (read-only export; validated,
locked offline slave monotonic union import); it is not a new replication channel.
Updated source packaging to include installer/updater, locks, units, public docs,
protection tool and TTL patch/license. The GoBGP build marker is canonical, with
the same 4.10.0 API and unchanged socket-TTL patch; existing GoBGP is not replaced.

Verification, entirely isolated:
- 172 discovered tests: 171 passed, one opt-in live test skipped. No ResourceWarning
  remains after explicitly closing the protection export's read-only connection.
- Bash syntax + ShellCheck 0.10.0 clean for both scripts; stub contracts cover
  master/slave/proxy/checksum/existing install and preflight/archive/build/backup
  failures, with no premature stop/start and no GoBGP control.
- Real apt/Git/venv/hash-locked pip installation in TWO separately bootstrapped,
  signed Debian 13 roots, master and slave. Used a fixed local Git snapshot via a
  test-only URL rewrite, not an unpublished GitHub ref. Installed 0.4.0 imports,
  pip check, CLI identity and service-user permissions passed. No DB, token, TLS
  key or administrator created, units not enabled, services not started; repeat
  installation refused. No host package install or host service state/config change.
- systemd-analyze verify passed against both installed root filesystems. This is
  chroot/mount+PID namespace validation, NOT a booted VM/systemd PID1 service test.
  Initial TLS/config/production-peer setup and real VM boot remain operator steps.
- Two independent Python/source and patched GoBGP builds matched. Real loopback
  iBGP TTL25 IPv4/IPv6 receiver attributes, owned-only export/import, web Adj-RIB-Out
  agreement, session recovery and withdrawals passed; fixed an outdated test tool
  to share the same process-local observations with its TestClient.
- Two actual loopback HTTPS processes with independent test daemons passed
  snapshot/journal, token/CA/SAN failures, slave read-only, outage/restart,
  protection divergence, promotion/demotion and daemon recovery. Real gRPC startup
  transition tests passed separately. EN/RU/UK dark/light/mobile browser checks
  passed; no real notification handler was called.
- Current-tree canonical naming scan found no prior spellings outside the explicit
  migration guide. Staged artifact/history/privacy scans run before publication.

Production A/B configs, DBs, roles, services and GoBGP were not migrated or updated.
Next: select the published full 0.4.0 commit (until a separately approved tag exists)
for fresh installation; review the coordinated migration guide before changing any
existing node. Standard rolling updates apply only within the canonical compatible
line. Both old release tags remain immutable; no production deployment is implied.


## Pair transition clarification: retain A, fresh B

Documentation-only follow-up before operator migration. Added PAIR_UPGRADE_040.md
with the actual selected workflow: preserve existing master data/protection and
GoBGP, install slave on clean Debian using the installer, transfer only adapted
local INI, its TLS/CA and replication secret. No old slave DB/WAL/sessions/outbox/
cursor/venv or separate protection cache transfer. The old slave must drain its
security outbox before removal; ordinary zero lag alone is insufficient. New
slave receives rules/users/ASN sets/shared audit by snapshot/journal. Protection
initializes independently; historical source networks, if needed, are explicitly
agreed in protected_prefixes of the transferred INI, otherwise slave announcements
remain disabled. The optional cache-transfer maintenance procedure is moved out
of INSTALL_B.md to PROTECTION_TRANSFER.md, not part of the chosen reinstall.

MIGRATION_LEGACY.md now explicitly applies its own-DB restore steps to A only.
Fresh installer is not an app-only reinstall on a host with existing GoBGP; it
refuses that case. Preserving GoBGP A does not imply zero interruption of the old
slave daemon when its OS is replaced. No duplicate IP/node identity on old/new B.

Explained synchronization outage from old B shutdown until both compatible
endpoints are running and new snapshot/journal catch-up finishes. Defined fresh
In sync/zero lag/history+cursor/last-success checks on both nodes and separate
protection readiness. Documented that changing the identity HTTP header was an
unnecessary compatibility break introduced by naming standardization, not a TLS,
security, storage or GoBGP requirement. No dual-header support is claimed or added.
No application/protocol/config/production operation is performed in this follow-up.

Verification: inspected actual PeerTransport sender and peer_auth receiver;
reviewed all changed public instructions for old-slave DB/cache transfer and
legacy path ambiguity, checked internal documentation links and Git diff. No
mutation tests needed for text-only changes. Next: publish the clarified docs;
operator review/provisioning/migration remain separate authorized actions.

## Explicit replication compatibility — 0.4.1 / protocol 3

Implemented a single independent replication_protocol_version=3, separate from
application 0.4.1, SQLite schema and audit-prune-v2 capability. Canonical node
identity header remains stable. Added a small TLS/token/node-authenticated
handshake and bounded process-local, node/version-bound 30-second exchange proofs.
Every status/snapshot/journal/security-outbox endpoint checks the negotiated
version/proof; client validates response proofs before remote state/ack commits.
No missing-version/old-format fallback. Data requests with obsolete query format
selectors are rejected. Mismatch/missing handshake cannot change roles, reset a
DB, apply remote cursors/acknowledgements or prune. Local data, protection,
security outbox, notifications and BGP remain independent of compatibility.

Polling retries handshake and automatically resumes journal or normal snapshot
recovery plus deduplicated outbox. Retention requires fresh confirmed compatibility
for a configured peer, including each subsequent deletion batch. Dashboard has
red Protocol version mismatch / Peer upgrade required with protocol/application
versions, preserving actual last-success time; auth and network errors remain
distinct. Same protocol with different app versions works. No new INI knob.

Updated public compatibility/install/lifecycle/retention/naming documentation.
Ordinary updates: slave B then master A, backup first, restart only Hemlock;
no slave reinstall/init-db and no GoBGP restart. Prior optional fresh-B workflow
remains an operator deployment decision, not a protocol requirement. If retention
is enabled on a legacy release, pause it before the first upgrade because legacy
code cannot retroactively enforce the new handshake. Resume only after both peers
are compatible, caught up and outbox drained. No production update performed.

Verification (isolated data/processes only):
- Final unittest run: 178 discovered, 177 passed, one opt-in integration test
  skipped; var/protocol-complete-suite.log. Six focused protocol tests include
  direct endpoint bypass attempts, absent/malformed/expired handshake proof,
  missing response proof, old peer without handshake/version, auth distinction,
  unchanged rules/users/cursors/acks/protection/transition state during mismatch,
  outbox accumulation/deduplication, expired-journal snapshot and blocked prune.
- Real CA-verified two-node HTTPS timer polling with two own peer-free GoBGP
  daemons passed B-first mismatch/A-upgrade resume, same protocol/different app
  versions, unchanged real IPv4/IPv6 RIB and daemon PIDs during pause, backlog
  delivery exactly once and Dashboard recovery; var/protocol-real-periodic.log.
  Protocol 4 is injected only in the isolated test to simulate a future peer;
  shipped application supports only protocol 3.
- Full two-process HTTPS/background lab passed CA/SAN/token failures, snapshot/
  journal, restart/outage retained data, slave read-only/protection divergence,
  daemon recovery, promotion and old-master replacement; no daemon restarts on
  role transitions; var/protocol-two-node-final.log. First preparation attempts
  stopped on missing noninteractive lab password / reused modified test config;
  fresh isolated fixture with in-memory generated password passed.
- Real HTTPS audit workflow passed prune/replay/snapshot/outage/restart, admin/
  guest API restrictions, pagination/search/details, both themes and one Unicode
  batch notification with no notification on replication;
  var/protocol-audit-workflow-checked.log. Updated obsolete test expectations for
  removed legacy snapshot format; explicit invalid-request fixture is isolated.
- Chromium Dashboard checks passed both themes, all unhealthy labels red and
  only In sync green, local/peer version text and old-peer explanation;
  var/protocol-dashboard-browser.log. Reviewed light-theme mismatch screenshot.
- Wheel 0.4.1 built; isolated wheel install reports application 0.4.1/protocol 3;
  development venv pip check passes. No dependency or GoBGP API changes.
- Git candidate artifact and changed-file sensitive-pattern checks passed;
  staged artifact scan passed for 33 files; full reachable history scan passed
  for 21 commits / 419 distinct blob-path pairs (no key/hash/artifact findings). Runtime
  logs/screenshots/fixture keys/DBs remain ignored under var, never staged.

Production A/B, their configs, DBs, services, roles, GoBGP and BGP sessions were
not changed. No host service operation or real notification handler was invoked.
Next: operator review and separately authorized publication; then B → A update
using a published fixed commit, verify automatic catch-up/outbox before retention.
No push is authorized for this task; existing release tags remain untouched.

## Fresh installer: automatic pinned GoBGP build

Operator-approved follow-up: fresh Debian 13 installation no longer requires a
manual GoBGP binary transfer. Default install downloads fixed upstream GoBGP
4.10.0 and Go 1.25.14 Linux amd64 archives over HTTPS, checks both pinned SHA256s
before extraction/execution, applies the existing TTL patch and builds the exact
4.10.0+hemlock-ibgp-ttl1 daemon. No latest/branch resolution, system Go, alternate
major API, unpatched fallback or existing-service migration. Optional prebuilt
binary+independent checksum input remains paired and explicitly checked.

New deploy/build-gobgp.sh bounds compile concurrency to two jobs, pins module
proxy/checksum verification, clears inherited Go/proxy bypass settings, supports
an explicit credential-free --proxy, builds offline after module download, checks
version and preserves binary/source/SDK/patch digests in an installed build report.
Temporary SDK/module/build caches are removed. Archive, patch, dependency or
compile failure aborts before Hemlock/GoBGP service users/configs are created;
partially installed source/venv may remain and must be inspected before retry.
No DB/admin/TLS/secret is generated, no service is enabled or started, announcements
remain disabled. Existing-install refusal and separate manual configuration/start
remain deliberate. apt now omits unnecessary translation indexes and has explicit
network timeouts/retries and fatal update errors. Linux amd64 only; preflight
requires 4 GiB in /var/tmp for default builds plus 1 GiB in /opt; 2 GiB RAM advised.

Verification:
- Full suite: 188 discovered, 187 passed and one opt-in live test skipped;
  var/installer-auto-full-tests.log. Installer contracts: default/prebuilt,
  slave/master/proxy, no binary needed for preflight, existing install, checksums,
  dependency/build failures and no premature users/configs/service control.
- Seven synthetic-archive builder tests cover fixed inputs, direct/proxy,
  checksum-before-source execution, download/patch/compile failures, no output
  overwrite, offline compile and digest/license report. Shell syntax and ShellCheck
  0.10.0 pass. Final combined script tests repeat after the final source edits.
- Actual fresh Debian 13 root filesystem from the prior signed minimal bootstrap,
  with private mount/PID namespace and no previous app/Go/GoBGP/users/configs:
  real apt packages, Git-before-clone, venv/hash-locked pip and real HTTPS downloads,
  checksum verification, TTL patch and Go compilation all passed. The selected
  fixed source was a local test Git snapshot via rootfs-only URL rewrite, not an
  unpublished GitHub ref. Explicit download proxy was used in the successful run.
  Initial direct apt attempts stalled on index/package fetch and were stopped
  only inside their test namespaces; no host package/service change occurred.
- Installed daemon SHA256 matches the separately reproduced release binary:
  9c990502689cfdd927f371382e64d877a3ef90f65130b76db64eee3bd619f154.
  Installed 0.4.1 web/package import, protocol 3, pip check, slave role, root-owned
  code, INI permissions/readability, disabled units, empty data directory and
  absence of keys/token/admin/real-peer config passed; repeat install refused.
  systemd-analyze --root verify passed for both units. Logs:
  var/installer-auto-results-verified.log and var/installer-auto-rootfs.log.
- This is NOT a booted VM with systemd PID1: actual operator config/TLS, initial
  service start and reboot on B remain separate steps. Installer success does not
  imply BGP/replication readiness; old A needs protocol-compatible update.
- README, master/slave instructions and build docs now use default automatic
  compilation, describe the optional binary path and report/license locations.
  Source distribution verification checks inclusion of both scripts/patch/license
  and exclusion of runtime/local deployment files. No binaries are added to Git.

Production A/B, services, configs, DBs, routes and roles remain untouched. Old B
backup is operator-managed and must not be removed. Unrelated pre-existing
untracked file is left untouched and excluded. Operator authorized publication;
next: finish staged privacy review, commit/push main without force or tag changes,
then operator fetches that fixed commit for the still-stopped fresh B installer.
After manual INI/TLS/protection/peer review, init-db as slave and start services;
never restore old slave DB or create an administrator on the slave. Update A
separately before expecting protocol-3 snapshot/journal synchronization.

## Operator-authorized master application update checkpoint

After the fresh slave installation, the operator authorized updating the existing
master application. Installed the published fixed source commit 72443a5 (0.4.1,
protocol 3), preserving its existing installation paths/account/unit name rather
than performing an unrequested filesystem migration. Only the application
ExecStart was adapted to the canonical CLI through a narrow systemd drop-in;
HTTPS bind capability remains in effect. Existing INI is byte-for-byte unchanged.

Before application stop: validated peer TLS/token/node identity and protocol-3
handshake, master role, no unfinished transition, SQLite integrity; prepared
private configuration/unit/venv rollback files and a SQLite backup using the
existing CLI after stopping the application. No plain copy of an open DB.
Installed the fixed wheel and hash-locked dependencies, pip check and package/
configuration/protocol checks passed, then started only the application.

Post-update verification: unchanged non-audit replicated documents, protection,
master generation and existing audit; successful CA-verified management HTTPS;
zero application restart failures; unchanged GoBGP PID, complete observed RIB and
peer states/establishment timestamps. Replication resumed automatically with
matching history/cursor, zero lag and drained slave security outbox. No human
login, test mutation, synthetic audit event or real notification test was created.
Private paths, deployment identity, working data/counts and rollback records stay
outside Git. The fresh slave remains announcements-disabled with peers disabled;
no remote configuration/service/BGP change was performed by this update.

Next: operator reviews fresh slave protection/readiness and separately authorizes
its BGP participation. Do not remove either private rollback archive yet. The
fresh-installer release tags and published source commit remain unchanged.


## README cleanup

Removed historical release announcements and the old one-off pair-reinstallation
links from README. Kept current installation/update/safety guidance and a compact
set of operational links; moved licensing back to the end. Detailed legacy
migration/reference documents and all published tags/history remain intact.
Checked README relative links and Git diff; no runtime tests needed for text-only
changes. No production operation.

## Node-owned TLS / release 0.5.0, protocol stays 3

Implemented explicit pinned mode alongside explicit legacy_ca migration mode
(default for existing INI without TLS section). Node-owned P-256 certificate/key
publication uses a private atomic identity directory; strict service ownership,
permissions, pair matching/format validation; startup/runtime expiration rotates
only after graceful HTTPS stop. The embedded launcher restarts HTTPS internally,
never GoBGP/systemd. Warn-once expiry and one-attempt rotation notifications use
the existing bounded handler; old notification events are not replayed.

Local atomic/locked trust and detailed TLS audit stay outside SQLite and all
replication payloads. Public bounded introduction precedes any credentials.
Actual peer data socket checks approved SHA256 SPKI before Authorization; mTLS
client DER comes from the Uvicorn HTTP/1.1 transport, never headers. Browser login
needs no client certificate. Existing token/node/protocol handshake still gates
all data endpoints. TLS failures never change role/DB/protection/routes. Readiness
for retention also requires current local pins. No new audit action is sent to
old protocol-3 peers; detailed TLS approval audit is strictly local.

Root tls self/peer/approve/trust/revoke bypass DB access and drop to the prepared
TLS directory owner. Admin web approval/revocation works on both roles with CSRF;
guest cannot mutate/read local TLS audit. Candidate refresh/race checking and
explicit revoke-before-replacement prevent silent re-pinning. Explicit stopped-
slave database reinitialize (dry-run default) preserves damaged files and local
trust, can resume an interrupted recovery, refuses identifiable master/fenced
transition, and never invokes GoBGP. Recoverable protection is retained; otherwise
its original corrupt source is archived and new announcements stay disabled.

New installer creates private TLS state directory; template defaults to pinned,
node cert/key under writable data path, no CA needed. Existing production config
remains legacy until an operator explicitly switches mode/paths after backup.
Runtime requirement cryptography 50.0.2 and hashed runtime/test locks updated.
Updated master/slave/operations/update/protocol docs, added TLS_TRUST.md and brief
Info EN/RU/UK guidance; no wire format/protocol-number change.

Verification so far: real two-node HTTPS/mTLS unit cases passed generation,
permissions/corrupt/partial/mismatched pair, no credentials before approval,
mutual approval/snapshot/replay, URL/key changes, candidate race, actual-socket
pin substitution, revoke, guest/admin/CSRF/slave, root CLI without users and with
corrupt DB, role transitions preserving pin, graceful expiration stop/restart.
Real CA legacy tool used fixed 0.4.1 source then new code and explicit pinned
transition; journal/history preserved and original CA keys/certs unchanged.
Chromium dark/light/mobile and real peer-free GoBGP lab passed UI approval/revoke,
catch-up and unchanged IPv4/IPv6 RIB/daemon PIDs. Initial mobile overflow and
asynchronous test waiting were corrected. All artifacts remain ignored under var.

Final verification:
- 210 discovered tests: 209 passed, one explicit opt-in integration test skipped;
  ResourceWarning treated as error. var/tls-release-final.log. The 22-case TLS
  suite additionally passed in isolation (var/tls-release-core.log), including
  direct one-sided mTLS/token bypass refusal, corrupted local trust never showing
  In sync, root CLI on an empty slave, periodic context pickup without restart,
  corrupt-DB recovery interruption/resume and single rotation notification/no replay.
- Verified legacy rolling path against actual fixed 0.4.1 source and its original
  installed metadata, then 0.5.0 legacy and explicit pinned transition. Original
  leaf and CA keys/certificates remain byte-identical, history/journal retained,
  protocol 3 throughout. var/tls-legacy-verified.log.
- Chromium dark/light/mobile real HTTPS peer approval/revoke/admin-slave/guest
  restrictions and automatic catch-up passed; actual peer-free GoBGP IPv4/IPv6 RIB
  and daemon PIDs unchanged. var/tls-browser-verified.log. Info EN/RU/UK both
  themes/mobile passed (var/tls-info-verified.log). Browser test trust is scoped
  only to the temporary test SPKIs, never a production verification bypass.
- Fresh signed Debian 13 minimal rootfs installation with real apt/Git/hash-locked
  pip and optional verified GoBGP input passed new cryptography dependencies,
  0.5.0/protocol-3 metadata, permissions, empty initial data and disabled units,
  repeat refusal and systemd-analyze static checks. Installed root CLI generated
  the pair as service UID, 0600, with no users/DB. Then actually installed
  unprivileged HTTPS started with pair/DB absent, generated both, answered verified
  HTTPS/SAN session/public intro, using its own peer-free GoBGP. No host systemd
  lifecycle operation. Logs var/tls-installer-results.log / tls-installed-https.log.
  This is chroot/namespace process validation, NOT a booted VM/PID1 reboot test.
- Independent wheel and normalized source-archive builds match. Package includes
  TLS transport/recovery/CLI/docs and excludes runtime/local deployment files.
  Normal generated sdist egg-info metadata is allowed only in the package, never
  Git. Hashed dependency install/pip check, shell syntax/ShellCheck and changed
  operational Markdown links pass. Staged artifact/privacy checks passed for 39
  files; pre-commit reachable history scan covered 25 commits / 449 unique blobs
  with zero findings. No push or tag is authorized.

Design/operational limits: TLS audit is local outside the common replicated audit;
2 MiB trust/audit capacity requires explicit operator archival rather than deletion.
CLI approval is picked up within 10 seconds (web immediately). Expiry waits up to
30 seconds for HTTP requests and for already-running background work, so complete
HTTPS restart duration depends on current operation timeouts/workload; it does not
force-kill transactions or control GoBGP. Manual pair replacement requires a
Hemlock-only restart. Self-signed browser trust is independent of replication pin.
Recovery retains protection only when readable; otherwise archived corrupt files
are retained and protection must initialize before announcements are allowed.

No working A/B config/key/DB/service/role/BGP changes, synthetic working audit,
real notification test, push or tag creation. Next: review this LOCAL release,
authorize publication separately, then B -> A in explicit legacy_ca with original
keys, followed by separate operator-selected pinned mode/paths and independent
approval on both nodes. Keep old keys/backups; check fresh sync/outbox before
resuming retention or changing announcements. Ordinary updates do not reinstall
slave or change identities. Final deployment remains outside this task.

## Operator-authorized first pinned-TLS deployment

Operator explicitly authorized publication of 4eb4c33 and updating the existing
master into pinned mode, accepting the temporary replication pause. Ordinary
push to origin/main completed, no tag change. Prepared private INI/unit/old-pair/
venv rollback archives and a stopped-application SQLite backup. Installed 0.5.0
from that fixed commit, changed only TLS options, created a service-owned private
state directory and retired the former active leaf pair into the private rollback
bundle. It is absent from its original paths; no irreversible key destruction.
CA signing material was not modified. Existing service/account/install/DB paths,
node identities, role, ownership marker, route/protection and notification/
retention policy settings were preserved.

Restarted only the application. Service generated its node-owned pair with correct
UID/mode 0600 and exposed verified HTTPS/SAN and bounded public introduction.
Read-only post-checks confirmed original non-audit documents/protection/history/
existing audit, SQLite integrity, byte-identical observed GoBGP RIB and unchanged
daemon PID plus peer establishment timestamps. No pin approval or false human
login was performed. No GoBGP lifecycle/configuration operation or remote SSH.
Detailed deployment identity, fingerprints, addresses, original config/keys and
rollback paths remain outside Git in private local deployment records.

The peer remains on its prior TLS configuration until the operator updates it;
replication is intentionally paused. Next operator step: run the canonical updater
on the slave, then explicitly select pinned mode and new service-owned pair paths,
retire its old leaf pair after backup, restart only its application and compare/
approve exact SPKI fingerprints independently on both consoles/web interfaces.
Removing old CA-mode files without changing mode/paths would prevent HTTPS startup.
Keep rollback material and verify fresh catch-up/outbox after mutual approval.
