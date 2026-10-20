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
