# Dashboard ordering, State and account login history

The manual rule section is Blocked IP list. Its forms are Add IP network /
Edit IP network, with IP/CIDR. ASN forms are Add ASN / Edit ASN, with ASN.
Editing still changes comments, not the rule identity. Single addresses,
IPv4/IPv6, normalization, duplicate guards and host-bit validation are unchanged.
Manual provenance is displayed as Blocked from IP networks list on Dashboard,
IP search and rule/route details. Internal rule kinds and replicated rule schema
are unchanged.

## Route sorting

Dashboard Prefix / Source / Comment / Added headers are keyboard-accessible
buttons with arrows and aria-sort on their column headers. A click toggles
ascending/descending and resets the page to one. API /api/routes accepts sort
(prefix, source, comment, added) and direction (asc, desc). The entire filtered
set is ordered before pagination. Prefix compares family, integer network address
and prefix length. Source and Comment compare the primary displayed source/comment
with Unicode casefold; blank comments use the displayed dash. Added compares the
minimum source-rule timestamp, as displayed in that row. Canonical numeric prefix
order is the stable tie-breaker for equal values in either direction. Multiple
source reasons remain available in expanded details. Refresh and periodic updates
retain the selected ordering and pass it back to the server.

## Exact route State semantics

The API keys remain unchanged. UI badges clarify Applied locally, Pending locally
and Application failed. State help is available at the column header and all six
definitions are on Info in EN/RU/UK. This is route State, not BGP session status or
per-peer export status. The following checks run in priority order:

| API State | Exact condition |
| --- | --- |
| Excluded by protection | The source prefix is absent from the desired union after local prefix/ASN protection checks. This wins even if old local observations still contain a path. |
| Stale | The prefix is desired, and a timestamped local RIB observation exists but its age exceeds 45 seconds. This takes precedence over a newer failed observation when both apply. |
| Unknown | The prefix is desired, observations are not stale, but there is no timestamped RIB observation, or worker:observation has an error with an attempt timestamp newer than the RIB timestamp. |
| Applied | Desired, observations fresh (age at most 45 seconds, no newer failed observation), and at least one local path matches the Hemlock owner, local origin, configured family next-hop, local preference and the exact regular-community list. A matching path wins over a stored reconciliation error. |
| Failed | Desired and freshly observed, no matching local path, and either local bgp.error is nonempty or the family's next-hop is not configured. The stored bgp.error is not aged out by this function and can affect multiple unmatched prefixes. This does not mean every prefix had its own failed RPC. |
| Pending | Desired and freshly observed, no matching local path, no stored reconciliation error, and a configured next-hop. It can also occur with announcements=no; it is not a successful application or a promise that an operation is running. |

An IRR fetch error alone does not set route State to Failed. It is shown on the
ASN rule and the last accepted prefix set is retained. Local path presence in
details is separate from ownership/attribute matching. Export is observed per
peer separately. None of these values proves remote router acceptance or FIB
installation. Unknown/Stale never render an Applied badge.

## Users and history

Users is available to guests and admins. Everyone has an own-account card with
login, role, Change password and the latest five successful login events. Guests
have no account-management table; admins retain it and get Login history beside
Edit. On a slave the history is readable but Change password is disabled and the
configured master node is identified. A master self-password change still verifies
the current password, preserves the user's role and invalidates old sessions.

GET /api/login-history defaults to the authenticated user; an admin may pass login
for another account. A guest cannot request another login. Other users' auth.login
events are also filtered from guest /api/audit and /api/history responses, including
Before/After IP data, so the older audit APIs do not bypass this boundary. Admin
audit remains complete, including failed login attempts. The five-entry account
history includes only action=auth.login, result=success. Page/session reads and
logout are not logins. Empty histories are explicit.

New successful events include only canonical client_ip in their existing after
field. It comes from the socket request.client.host. The embedded Uvicorn already
uses proxy_headers=False; X-Forwarded-For and Forwarded are ignored. Historical
successful events without an address display Unknown (not recorded); no inferred
IP or synthetic audit entry is created. Both IP families are supported. Dates use
the existing browser UTC offset and timezone format. Node is the original event
node, not the viewing node.

There is no second history replication mechanism: master audit/journal and the
existing constrained slave security outbox deliver the same event IDs. Master
ingest now allows exactly client_ip on successful session login facts, rejects
other extra payloads, and keeps replay/cursor semantics. Shared/local pending events
are deduplicated by ID before selecting the latest five. Partial SQLite indexes
bound the per-account query; full audit sets are not returned to the browser.
Peer status/last successful sync and an explicit may-lag notice accompany results;
a successful data-cursor check is not proof that all remote logins were received.
Upgrade the master before a slave uses the new IP context: an older master rejects
nonempty peer security context. Legacy events remain valid and are never rewritten.

## Verified in isolated environments

```bash
.venv/bin/python -W error::ResourceWarning -m unittest discover -s tests -v
.venv/bin/python tools/check_accounts_ui.py --directory var/accounts-ui-new-run
.venv/bin/python tools/check_login_replication.py
.venv/bin/python tools/check_password_ui.py
```

90 tests discovered: 89 passed, one opt-in live GoBGP write test intentionally
skipped. Coverage includes numeric IPv4/IPv6/mask sorting across pages, filtered
casefold and stable ties, timestamps, invalid sort inputs, all six route states
and the exact 45-second boundary, successful-only last-five history, legacy unknown
IP, both nodes, replay/snapshot/restart deduplication, privacy on all three history
APIs, socket IP/header spoofing, no-login-on-session-read, current-password checks
and slave write denial.

Real Chromium checks both themes, labels/add/edit forms, sortable headers/arrows,
page resets, filtering, Refresh persistence, provenance/details, State help and
Info languages, own guest/admin cards, admin history/empty state, direct guest
history denial, IPv4/IPv6/Node/timezone, current-password form and disabled slave
password action. Screenshots are ignored runtime artifacts. The separate two-node
HTTPS FastAPI drill verifies CA/IP SAN and authenticated peer transport, actual
master journal + slave local-audit delivery, replay, preserved data/unavailable
status during disconnect and restart catch-up. No GoBGP adapter or working data is
used by these mutation tests.
