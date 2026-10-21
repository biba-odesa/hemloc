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
continuations. Every INI edit requires root:hemloc 0640, service-user readability
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
