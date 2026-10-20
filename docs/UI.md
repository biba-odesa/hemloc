# Interface and read-only presentation

The operational interface is English. Dates use the browser's timezone and show
both the UTC offset and timezone name. Only Info has EN/RU/UK language controls;
changing Info language does not change the rest of the interface.

Dashboard has two summary cards: the configured peer node's status and Blocked
prefixes. There is no announcement-mode card. The announcements setting and
routing semantics are unchanged. The peer heading uses peer_node_id (hemloc-b
is displayed as Hemloc-B); B therefore displays Hemloc-A when configured that
way. Not configured, unavailable, stale, catching up and in-sync are distinct.
Last successful sync is retained separately from failed attempts as local
telemetry only. It does not change polling, journal application or failover.

Blocked IPv4/IPv6/Total count unique desired prefixes actually observed locally
with the correct Hemloc owner, local origin and expected attributes. Duplicate
rules/paths do not increase counts. Required counts remain separate. Missing
paths/attribute repair are Pending, known reconciliation failures or missing
next-hop are Failed, and protection exclusions count unique prefixes. Pending
also includes owned paths waiting for withdrawal. Unknown/stale RIB yields
Unknown application counts, never a fabricated zero or success. Protection
initialization/refresh errors appear only when present; the permanent successful
protection and local-RIB disclaimer paragraphs are removed from Dashboard.

The BGP table has Peer, Status, Uptime, IPv4 advertised and IPv6 advertised.
Peer uses description with address fallback. Disabled is distinct from Idle or
Active. Uptime is read from GoBGP's existing timers.state.uptime timestamp via
the same pinned v4 API. Unestablished/error/stale/truncated export observations
show Unknown/Stale counts. An established peer with a fresh complete empty
Adj-RIB-Out legitimately shows zero. Counters are unique exported prefixes.

Route pages show Prefix, Source, Comment, Added and State. Expand a prefix to
see every source/comment, required and observed attributes, local-RIB presence
and per-peer export. ASN sources show AS<number> — name; manual sources show
Blocked from IP networks list. IP search returns all containing networks and all reasons, with Matches
found / No matches. Search type switches between IP and prefix/source/comment
text. Main and per-rule prefix/proposal lists are paginated; full prefix sets
are not embedded into the DOM. Open details and row states can refresh without
closing expanded rows. History uses named actions and field-level Before/After,
not raw JSON or technical document IDs. User comments remain escaped text.

New authenticated read-only endpoints:

- `/api/dashboard`: compact counters, peer-node health and BGP sessions.
- `/api/routes`: bounded page of route/source summaries, optional text/IP search.
- `/api/route-detail?prefix=...`: details of one selected prefix.
- `/api/rule-cards`: paginated rule summaries without full prefix arrays.
- `/api/rules/{id}/prefixes`: paginated accepted/proposed prefix set.
- `/api/history`: paginated human-readable audit fields.

Existing APIs remain compatible. None of these read models writes working
rules/users or performs BGP operations. The same shared authorization and
mutation services remain in place. GoBGP projection now has 16 messages / 39
fields / four RPCs; only read-side timer fields were added, verified against
upstream v4.10.0 descriptors. No AddPath/DeletePath/reconciliation/protection
logic or GoBGP policy/config/session management changed.

Verification on isolated databases:

```bash
.venv/bin/python -W error::ResourceWarning -m unittest discover -s tests -v
.venv/bin/python tools/check_ui_redesign.py --directory var/ui-new-run
.venv/bin/python tools/check_browser.py --directory var/browser-new-run
.venv/bin/python tools/check_password_ui.py
```

The original redesign suite discovered 76 tests: 75 passed and the explicitly opt-in live GoBGP
write test was skipped. It was intentionally not enabled for this UI update.
Browser checks passed in both themes, including expanded multi-source ASN/manual
rows, IP match/no-match/validation errors, pagination (25 route rows), escaped
HTML, no JSON panels/IDs in history, stale/unknown/disabled sessions, all three
Info languages and mobile viewport. Screenshots were inspected and stay under
ignored var/ui-redesign-delivery. No production test users or rules were added.

Limit: pagination bounds responses/DOM, but SQLite JSON rule snapshots and route
matching still do linear in-memory work. A 100k interactive browser benchmark
and indexed prefix storage are separate future work. No router acceptance is
inferred from local export. Info explains that distinction; OPERATIONS.md documents explicit owned
withdrawal when announcements=no.

Rule identity, coverage badges, current pagination/theme behavior and the
non-destructive legacy migration are documented in [RULES.md](RULES.md).

Latest validation: 84 discovered, 83 passed, one opt-in GoBGP-write test skipped;
check_rules_ui and updated check_ui_redesign pass in real Chromium. Deployment
results are recorded in VALIDATION.md.

Current form/provenance labels, server-side ordering, exact State definitions and
private cross-node login history: [ACCOUNTS_UI.md](ACCOUNTS_UI.md). Users is now
available to guests for their own account; admin management remains restricted.

Info now follows the agreed Ukrainian content and matching EN/RU translations,
with a compact State table and dynamic local protection. Exact content/code audit,
including the old-master BGP isolation clarification: [INFO.md](INFO.md). Long
State definitions remain in operational/developer documentation and Dashboard
help; the disabled-announcement section is no longer part of Info.
