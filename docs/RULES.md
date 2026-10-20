# Rule identity, coverage and presentation

ASN inputs `AS123` and `123` have one integer identity. Manual IPv4/IPv6
addresses normalize to /32 or /128, and network spelling normalizes through
strict IP parsing. Host bits still cause a validation error with the canonical
network suggestion. Identity is separate for ASN and manual rules: a manual
prefix equal to an ASN expansion is a valid independent reason.

SQLite installs a partial expression lookup index and BEFORE INSERT/UPDATE
triggers. Master writes cannot create another rule with the same kind and
normalized identity, including concurrent connections and identity changes.
The shared transactional Store used by web/API/import/services (and maintenance
CLI consumers) translates the constraint to Conflict. Data/audit/journal remain
atomic. The existing CLI manages users and maintenance; no separate rule-writing
CLI bypass is introduced. Failed attempts produce redacted conflict audit.

API duplicates return HTTP 409 with a readable error and existing_rule_id.
The form retains its input and offers Open existing record. An import containing
new duplicates is rejected atomically; no link is offered to a rolled-back row.

## Legacy duplicates

No documents are deleted, merged or rewritten by migration. A nonunique lookup
index allows startup with old duplicates; triggers prohibit new duplicates while
allowing comment/IRR updates of unchanged identities. An explicitly removed
last duplicate releases its identity. Slave snapshot/journal application retains
historical source documents without creating a divergent state; local writes
remain prohibited. Promotion activates the same master trigger checks. The
replicated schema/envelope is unchanged.

Existing deployments can contain legacy duplicates. Inspect them locally with
comments/authors before any removal; never include that report in a public
repository. Migration preserves all such records and prevents new duplicates.
The isolated migration tests check unchanged documents, startup, continued
editing and rejection of another duplicate.

## Coverage

Manual rules show amber Covered by AS<number> and muted blue Covered by <prefix>
and Contains N blocks badges. Equality counts as coverage, containment is strict,
the own record is excluded, and Contains deduplicates source rule IDs across all
prefixes of an ASN. Both coverage directions can appear together. Intersections
remain allowed and independent; no automatic merging or aggregation occurs.

Only accepted prefixes passing local protection contribute. Failed IRR refreshes
retain the successful set; pending proposals do not contribute. These badges
refer to blocking rules and never prove remote router installation. The manual
form previews the same coverage before saving. Badge expansion loads related
rules/comments/authors with bounded pagination and Open record links.

A per-service prefix index is cached by history/sequence and local protection.
Prefix-length maps find covering networks in at most 33/129 ancestor lookups;
sorted address ranges find descendants in O(log P + K), where K is the matching
range size. Construction sorts P unique accepted prefixes once per revision.
There is no per-page all-pairs pass. Rule changes, accepted ASN refreshes,
replication snapshots/journal and local protection changes invalidate the cache.
Visible manual badges refresh every 20 seconds and after local mutations. SQLite
JSON snapshot loading still does linear work; this is not a storage redesign.

## Pagination and themes

Dashboard replaces Observation; old #observation links remain accepted. The two
status cards appear only on Dashboard. The old provenance subtitle is removed.
All main, accepted/proposal and related-rule pagers show Page X of Y, Showing
A–B of N, First / Previous / Next / Last. Totals count filtered results server-side;
pages clamp after deletion, changed filters reset to the first page, and empty
results show No results with navigation disabled. Full sets are not sent to the
browser for counting.

The local blocking theme.js runs before CSS/paint: dark is the default regardless
of OS, and an explicit saved light/dark choice wins. The small top-right square
button shows the next action (sun/light or moon/dark), with tooltip, aria-label,
focus and normal keyboard activation. No external icons/assets are loaded.

## Verification

```bash
.venv/bin/python -W error::ResourceWarning -m unittest discover -s tests -v
.venv/bin/python tools/check_rules_ui.py --directory var/rules-ui-new-run
.venv/bin/python tools/check_ui_redesign.py --directory var/redesign-new-run
```

Mutation tests use temporary databases and background-free loopback web instances
with no GoBGP adapter. They cover normalized duplicates, concurrent writers,
atomic import, SQL UPDATE/REPLACE guards, legacy startup and replication,
coverage/invalidation/protection in both families, page boundaries/filter/empty
and delete-last behavior, form conflicts/links/preview, both themes/persistence/
keyboard/mobile, Dashboard-only cards and old navigation links. Live GoBGP write
tests are intentionally excluded from this UI/rule-validation change.
