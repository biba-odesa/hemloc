# Hemlock specification

## Scope and operating constraints

Hemlock manages IP-prefix blocking through a separately managed GoBGP daemon on Debian 13. A single unprivileged Python 3.13 process contains FastAPI, embedded single-worker Uvicorn, local web assets, SQLite, background replication/IRR/reconciliation tasks and a maintenance CLI. A process lock prevents multiple owners per database, even when launched through Uvicorn directly. nginx, Apache, Redis, Celery and external databases are unnecessary. System packages/services, production routers, host networking, firewall and SSH must not be changed automatically. Announcements default off. Publishing requires explicit operator authorization.

## Node configuration and lifecycle

Local INI defines unique node_id, master/slave role, peer URL, web binding, HTTPS certificate/key and CA, database, GoBGP address, separate v4/v6 attributes, IRR server/sources/utility/timeouts, protection and proxy settings. These are never replicated. There is no automatic promotion. Master accepts changes; slave is read-only at all web/API/CLI mutation entry points, including passwords/users/ASN refresh. Both independently calculate and reconcile their own desired routes. Peer/web/IRR failure never clears working rules.

Manual promotion: isolate old master first; set slave role to master and restart only Hemlock; keep GoBGP running. Promotion creates a fresh history identity, retaining accepted replicated data. Before returning old master, configure it as slave; it atomically adopts the new master's state without merging its old branch. Two reachable masters produce an explicit conflict and stop synchronization. A partition can conceal a second master; there is no quorum or fencing guarantee.

## Persistence and replication protocol

SQLite uses WAL, foreign keys, busy timeout, bounded transactions and durable commits. All master changes, their redacted audit record and journal entry commit together. Journal identity is (history UUID, monotonically increasing sequence), never sequence alone. Replicated entities: blocking rules, accepted and pending ASN sets and metadata, users with Argon2id hashes/credential version, shared immutable audit. Local entities: sessions/login limits, local config/role/TLS, protected prefix cache, sync cursor/status, route ownership and GoBGP observations.

Slave polls every 3 seconds by default. Authenticated replication always verifies TLS and bypasses proxy configuration/environment. On bootstrap, history mismatch, cursor ahead or journal retention gap, request a consistent snapshot with history+cursor from the same SQLite read transaction. Validate schema, entity types, counts, digest, sequence and constraints before installing. Install replicated tables and cursor in one transaction, retaining local tables and a prior SQLite online backup. Never copy an open SQLite file. Keep the old desired state until installation commits. Concurrent changes after the snapshot cursor are replayed from journal without a gap. Apply contiguous operations and cursor in one transaction; repeat delivery is a no-op; malformed batches roll back. Acknowledgment/status tracks the peer's applied cursor, separately from local storage and GoBGP application. Bounded journal retention may force a new snapshot.

## Rules and metadata

Separate ASN and manual-prefix editors. ASN rule: ASN, fetched name, arbitrary optional comment, author/time, accepted v4/v6 set, last-success, last-error and durable next-update date. Master fetches on create, every 30 days and on explicit refresh. bgpq4 and configured IRR are primary expansion source; timeout/nonzero/malformed/partial family errors preserve the full old set. Empty or excessive changes stage a proposal. Default excessive change: symmetric difference >50% of old set or >10000 prefixes, or result >100000 prefixes. For initial addition, result >100000 requires confirmation. Admin confirms exact proposal digest; a concurrent newer proposal invalidates the old confirmation. Pending empty updates are visible. No slave IRR fetch for replicated ASN rules.

Manual input accepts IPv4/v6 or CIDR; bare IP becomes /32 or /128. CIDR host bits are rejected with canonical network suggestion, never silently expanded. Optional reference origin metadata supports multiple ASNs and unknown ASN. Reference origins do not create ASN-wide blocking. Network metadata must describe the entire CIDR: a first-address lookup cannot assign an ASN to a broad network. IP metadata uses RIPEstat network-info for hosts; ASN names use RIPEstat as-overview. External metadata has timeouts, bounded cache and failure tolerance; manual insertion does not depend on metadata success. Sources and freshness are displayed/documented.

Desired routes are the exact union of accepted rule prefixes; no widening aggregation. Each route retains all source rule IDs. Removing one source leaves any route required by another. IP search enumerates every containing prefix and every matching source.

## Local protection

INI includes protected ASNs (example 64496), private v4 prefixes 10/8, 172.16/12, 192.168/16 and operator public v4/v6 prefixes. Protected ASN cannot be added as a blocked ASN. Protected ASN expansion runs locally on both nodes independently of replicated rules. Successful results only grow a durable local protected set; errors or smaller results never remove protection. Explicit operator procedure is required to reduce it. First boot with unresolved protected ASN is fail-closed for gRPC writes; populate successfully with announcements disabled first. A previous successful set remains protective across failures/restarts.

A candidate equal to or more specific than a protected prefix is prohibited. A less-specific candidate covering a protected prefix is allowed. For 192.0.2.0/24: /24, .128/25 and .1/32 are prohibited; 192.0.0.0/16 is allowed. Same semantics apply to public/private IPv4/IPv6. Check manual input, bulk imports, IRR output and final gRPC writes. Exclude prohibited ASN-derived routes with visible reasons, retaining valid routes. Slave preserves replicated source data and displays local exclusions. Protection changes withdraw now-prohibited owned routes.

## GoBGP reconciliation

Separate daemon controlled only through loopback gRPC, never shell commands for route changes. Pin one GoBGP major and validate bindings or a minimal wire-compatible projection against that exact tagged API; do not mix major schemas. v4 configuration example next-hop 192.0.2.254, local-pref 200, community 64512:666. IPv6 next-hop must be configured explicitly; absent value prevents IPv6 writes. Ownership must survive the crash window between gRPC success and database write: use a reserved persistent owner marker plus local injection checks, reconcile actual RIB, and address withdrawals by the observed NLRI, local source and stable path identifier. GoBGP 4.10.0 omits UUID from ListPath, so UUID presence must not be assumed. Require both the reserved marker and an owner-derived nonzero path ID; re-read ownership before withdrawal and never send a request without an explicit path. Owner marker is an operator-reserved namespace; do not claim unrelated routes sharing a prefix. Inspect all paths; add missing, correct attributes, withdraw extra owned routes. GoBGP restart triggers reinspection/reinjection. Do not infer downstream acceptance from local RIB or Adj-RIB-Out. Disabled mode permits desired-state inspection and performs zero route writes.

## Authentication and authorization

Users have admin or guest role and enabled flag. Argon2id per-password salt. Server-side random-token sessions store token digests locally, expiry and credential version. Cookies HttpOnly, SameSite=Strict, Secure under HTTPS; explicit initial HTTP mode uses non-Secure cookies and loopback binding by default. Require CSRF token for all browser mutations; enforce content type/origin, same-origin web assets, bounded inputs. Login throttling persists locally and ignores untrusted forwarded headers. Disabled user, password change/reset or role change invalidates sessions after replication by user version checks.

Admin mutates and manages users on master; guest views. Authenticated users may change own password on master. No users mutate on slave. Root CLI: `hemlock user list`, `hemlock user create LOGIN --role admin`, `hemlock user reset-password LOGIN`; new passwords prompted twice, never argv. CLI shares application transactions/audit/journal and SQLite concurrency rules with running server. No permanent recovery password. CLI-created files must remain accessible to service user without widening permission.

## UI, statuses and audit

English responsive light/dark interface; separate ASN, manual IP/subnet, observation, history and users sections, plus an Info view with EN/RU/UK texts only. Dates include timezone. Ordinary views contain human-readable tables/cards, never raw JSON or technical document IDs. Observation has no announcement-mode card; show configured peer-node status, last successful sync/lag and distinct unique actual IPv4/IPv6/Total with Pending/Failed/Excluded and Unknown/Stale states. Compact named BGP peer table shows status, uptime and per-family export. Route/proposal lists are paginated; expansion shows all sources, comments, attributes, local presence and each peer export. Searchable paginated tables, readable errors, escaped arbitrary comments. Distinguish saved, replicated and confirmed local GoBGP application; never show success before observed. Observation includes rules/comments/times, all-reason IP lookup, desired/source routes, local RIB, peer sessions and available per-peer export, both nodes' replication/data freshness and explicit unreachable/stale state. Configured/desired differs from applied. Audit records actor/time/node/action/object/redacted before-after/result, replicated and immutable through web. No credentials/hashes/tokens/keys enter audit or logs. Failed/denied mutations, login/logout and throttled attempts use allowlisted category-only security events with no raw request or exception text. Slave security facts are stored in a local append-only outbox with their own generation/cursor; master pulls authenticated batches, validates node/schema/allowed fields, appends them transactionally to the shared audit+journal and records the peer outbox cursor. This channel cannot carry rules, users or arbitrary before/after data. UI deduplicates local pending facts by immutable event ID. Shared state remains master-only; this is not branch merging.

## TLS, external access and proxy

Built-in Uvicorn HTTPS with local certificate/key paths, custom CA and SAN-bearing certificates. Document CA trust installation and certificate lifecycle; never commit keys. HTTP is an explicit bootstrap choice. HTTP external clients ignore environment proxies: use_proxy=no is direct; yes uses configured http/https and no_proxy. Example proxy http://proxy.example.invalid:3128; no_proxy localhost,127.0.0.1,::1,block-a,block-b. Replication and local gRPC always direct. IRR WHOIS uses TCP/43 directly, never HTTP proxy. External dependencies: IRR TCP/43, metadata HTTPS/443, peer HTTPS configured port, loopback gRPC/50051; BGP TCP/179 belongs solely to separately authorized GoBGP peer configuration.

## Delivery and acceptance

Supply Debian install/update/backup/restore, systemd units, annotated INI, TLS/SAN/CA instructions, failover/return and root admin recovery instructions, dependency/API version rationale and isolated two-node launch. Exclude secrets, DB/WAL/SHM/backups, venv and private keys from Git.

Tests must cover exact/subnet/supernet protection in both families, retained protection, overlapping reasons, IRR errors/empty/anomaly confirmation, guest/admin/slave authorization, auth version invalidation, replay/disconnect/restart, snapshot+journal race, promotion/history replacement, GoBGP restart/crash/attribute repair/ownership isolation/protection withdrawals, proxy on/off/direct replication, redacted audit. Real two-node HTTP/TLS and isolated GoBGP tests are required before readiness claim. Every stage ends with exact verified results, remaining limitations and next action in PLAN.md.

Password policy (web and CLI creation/change/reset): 6..1024 characters inclusive, at least one Unicode letter and one Unicode digit required; special characters allowed but optional; no mandatory upper/lowercase combination. Existing password hashes remain valid for login; the new policy applies only when setting a new password. Argon2id parameters, individual salts and persistent login throttling remain unchanged.

## Rule identity and current interface requirements

Normalized ASN/manual identities must be unique for new master writes at the
SQLite transaction level, including web, API and import. Preserve legacy duplicate
documents and startup; reject new duplicates with HTTP409 and an existing-record
link. ASN-derived and manual equal prefixes remain independent. Display indexed,
protection-aware covering/containing badges for all manual rules, deduplicating
source rule IDs. Dashboard-only summary cards, complete filtered pagination and
a pre-paint persistent top-right dark-default theme control are required. Exact
semantics and migration report: [RULES.md](RULES.md). Routing, protection and
replication decisions remain unchanged.

## Account history and ordered Dashboard refinement

Blocked IP list uses Add/Edit IP network with IP/CIDR; ASN forms use ASN only.
Manual provenance reads Blocked from IP networks list. Dashboard sorting of
Prefix/Source/Comment/Added precedes pagination on the entire filtered set;
numeric network order, case-insensitive displayed text and real timestamps use
stable ties. State help and Info EN/RU/UK explain the unchanged six route states.
Users exposes only an own-account card to guests and retains admin management.
Latest-five successful logins show time/socket IP/Node via the existing audit
channel; legacy IPs remain unknown, failures remain in audit, and session reads
never count as logins. Guest history privacy applies to all history/audit APIs.
On slave password changes remain prohibited; current password is required on
master. Peer history freshness must never be asserted beyond received events.
Exact constraints: [ACCOUNTS_UI.md](ACCOUNTS_UI.md).
