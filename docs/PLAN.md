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
