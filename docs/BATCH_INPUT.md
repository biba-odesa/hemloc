# Sign-in and manual IP batches

This update is source-only until separately installed. It does not change route
attributes, GoBGP sessions, protection semantics or replication ownership.

## Interface

Anonymous visitors see only Hemlock, the sign-in form, a local decorative hemlock
SVG and the theme switch. Navigation, header, metrics and workspace are hidden in
the initial HTML as well as CSS. Startup checks only the public `/api/session`
boolean; protected requests start after authentication is confirmed. Password
manager username/current-password autocomplete and native keyboard controls remain.

Logout immediately hides the workspace. Session-required API responses hide it,
clear rendered rows and cancel refresh timers. While authenticated, a public
session probe every 20 seconds checks expiry/revocation on every screen; an idle
browser can therefore take up to 20 seconds to notice server-side expiry, subject
to browser background-tab timer throttling. No protected background refresh starts
when signed out. Server API authorization remains authoritative.

The light palette uses the agreed blue backgrounds through shared CSS variables.
Dark palette values are retained. Active navigation text and input borders use
stronger secondary contrast; normal text meets 4.5:1 in checked combinations,
input borders/focus meet 3:1. Dialogs, error messages and coverage badges use the
same blue surfaces. Screenshots and browser artifacts belong only in ignored var/.

## Adding a batch

Open Blocked IP list → Add IP network. Enter IPs/CIDRs separated by commas or line
breaks, optionally with one shared comment. Whitespace and empty separators are
ignored. Single IPv4/IPv6 addresses become /32 or /128. Host bits are rejected with
the canonical network suggestion; protection still forbids equality/more-specific
networks and permits covering aggregates. Overlaps are independent rules, not
merged. Coverage preview uses the existing index, counts all covered inputs and
renders at most 25 previews; saved rows retain the existing coverage badges.

Each new rule, its audit and journal operation commit atomically in its own
transaction. Duplicate constraints remain enforced by SQLite for concurrent
writers. Existing duplicates and repeats within a batch are skipped. Protected
and malformed inputs are invalid. One rejected input does not roll back others.
A storage/node failure stops further writes and returns the already confirmed
items plus explicitly unconfirmed/not-attempted items; there is no blanket success.

The form displays `Added: N · Skipped: N · Invalid: N`, any Unconfirmed count and
all non-applied items with reasons. Only confirmed additions leave the textarea.
Skipped/invalid/unconfirmed items and the comment remain. A network failure leaves
all input intact, even if the server committed before the response was lost.
Retry is safe: already committed items become existing duplicates.

## API and limits

```ini
[web]
# Reject the entire batch before rule writes if its element count exceeds this.
batch_max_items = 1000
# Maximum UTF-8 mutation HTTP body, including JSON framing and the comment.
request_max_bytes = 2097152
```

Supported ranges: 1–10000 items, 16384–16777216 bytes. Defaults need no local INI
changes. The body limit covers all mutation requests, including chunked input;
responses, snapshots and journal GETs keep their existing transport limits.
Oversized bodies return 413. Empty/over-count batches return 422 before any rule
write. Rejected requests are still audited. No existing settings are auto-edited.

`POST /api/rules/manual-batch` accepts the normal authenticated admin/master session
and CSRF token, JSON `{"value":"IP,CIDR\nIP","comment":"optional"}`. Processing is
in a synchronous FastAPI worker thread, outside the event loop. Batch metadata
requests are deliberately **zero**: reference origins stay unknown and metadata
availability/latency cannot prevent valid rule insertion. Single-rule API metadata
behavior is unchanged.

A completed response is HTTP 200 with `batch_id`, `status`, `added`, `skipped`,
`invalid`, `unconfirmed`, `error` and `items`. Status is `saved`, `partial`,
`no_changes` or `interrupted`. Every item includes original trimmed `input`,
`status`, `reason`, a fixed `code`, and normalized `prefix`/existing or new `rule_id`
when known. Codes: saved, existing_duplicate, batch_duplicate, protected,
invalid_cidr, infrastructure, not_attempted. An interrupted batch still uses a
structured 200 response so confirmed commits are not hidden by a generic HTTP
error. Inspect status/error and per-item outcomes, not just HTTP status.

`POST /api/coverage/batch` is a read-only session/CSRF-protected preview using the
same limits; it does not save rules. The original single-rule and atomic import
endpoints keep their previous contracts.

## Audit and notification

Successful additions are `rule.import` in Blocklist changes. The audit's after
context includes `batch_id`, author, comment and manual-rule provenance, while the
rule document and its replication schema stay unchanged. Batch is also shown in
expanded History fields; technical IDs are not added as a main-table column.

Skipped/invalid/interrupted inputs create one `rule.batch` summary in Errors &
security: batch ID, counts and an allowlisted reason histogram. No unbounded raw
input, request body or private exception text enters that summary. Expected admin
validation/protection failures do not feed the suspicious-access aggregator; ordinary audits
and anonymous/forbidden-action detection remain enabled.

With notifications enabled, the originating master emits one best-effort message
for the batch if at least one addition is confirmed, with counts, author/comment,
batch ID and at most 20 prefixes. No per-row messages, no notification when added
is zero, and no notification on slave replay/snapshot. Existing one-attempt,
bounded-queue and script-sandbox semantics remain in AUDIT_RETENTION.md.

## Update sequence

Update B first, then A to the same fixed reviewed commit. Keep retention and
notifications disabled throughout the rolling update. Confirm normal replication,
`audit-prune-v2` support and security cursor acknowledgments on both nodes.
Only after that test the external handler and review an exact real prune preview
before enabling the respective features. After first prune, an old v0.1.0 peer
cannot consume maintenance operations/schema-2 snapshots. The v0.1.0 tag is not
moved. Do not restart GoBGP or change announcements merely to update the UI.
