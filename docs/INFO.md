# Info content and local protection display

The agreed Ukrainian text is the source for EN/RU/UK. Info has six sections:
purpose; ASN and IP networks list; MTR validation; master/slave; protection; and
one six-row State table. Ordered promotion/return steps, optional comments,
multiple reasons, MTR caveats, backup restoration and later slave provisioning
are retained. State keys stay English. No configuration file path is embedded.
The previous long per-State sections and disabled-announcement section are removed
from Info. Dashboard State help is unchanged; full operational announcements=no
and withdraw-owned procedures remain in OPERATIONS.md.

## Reconciliation with actual resynchronization code

Store.install_snapshot validates schema/identities/digest, creates an online
SQLite backup through sqlite3.Connection.backup, then replaces documents/journal
and clears browser sessions in a SQLite transaction. History/sequence/master ID
are updated atomically. Local protection/cache and operational local state are
not removed; the local INI is not replicated or edited. Replicator catches up via
the existing journal after the snapshot. No business-rule branch merge occurs.
An isolated test checks a nonempty divergent old branch in the backup, replacement
with master documents, integrity_check, local configuration and protection retention.

**Startup behavior from 0.3.0:** promotion retains shared/local data and creates a
new generation, archiving the old journal. Demotion now runs before ordinary
workers: a durable external fence, addressed dedicated-daemon withdrawal/empty-RIB
verification, a closed checkpointed original-file backup and fresh slave DB with
only local protection carried over. Confirmed daemon absence leaves cleanup
pending; uncertain gRPC/failed deletion does not certify success. No old rules or
browser sessions are retained in the active DB. Ordinary slave restarts retain
data. Info EN/RU/UK describes these distinctions; ROLE_TRANSITIONS.md documents
recovery, absence evidence, permissions and rollback. Keeping BGP isolated until
current synchronization/route checks is still an operator responsibility. No
network isolation, production deployment or live routing action is performed by
this development update.

## Dynamic read-only protection

Authenticated GET /api/info/protection returns summary counts and node ID. The
asns/prefixes list modes support q, page_number and size (up to 100). Info renders
collapsed lists with 25-row localized pagers and filters. Protected ASN identity
comes from loaded local configuration; last-success metadata comes from the
retained cache. Obsolete ASN success keys do not falsely label an unconfigured
ASN as protected. Prefixes are the deduplicated union of configuration and cache,
with both origins shown for equal entries. Sorting is numeric by IP network.
No local configuration secrets, tokens, keys or sessions are exposed. This read
model neither refreshes IRR nor changes protection or routes.

## Verification

92 tests discovered: 91 passed, one opt-in live GoBGP-write test intentionally
skipped. Info-specific tests verify authentication/guest access, bounded/filtered/
empty/clamped pages, configuration/cache union and origins, numeric IPv4/IPv6,
ASN metadata and obsolete-key exclusion, no writes from successful reads, plus
snapshot backup/replacement/local preservation against real SQLite.

Real Chromium reviewed EN/RU/UK in both dark/light themes, six sections, both
ordered four-step lists, MTR text, BGP-isolation clarification, the single six-row
State table, absence of old announcements/path content, actual-node protection,
collapsed lists, page boundaries/filter/empty state, source labels, timezone and
mobile table layout. Screenshots are ignored artifacts in var/info-release.
All mutation checks use separate temporary databases and background-free loopback
servers; no working login, IRR refresh or GoBGP adapter is used for UI tests.

```bash
.venv/bin/python -W error::ResourceWarning -m unittest discover -s tests -v
.venv/bin/python tools/check_info_ui.py --directory var/info-new-run
```
