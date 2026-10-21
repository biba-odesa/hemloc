# Publication policy and release audit

Public repository: https://github.com/biba-odesa/hemloc
Release branch: main. First annotated release tag: v0.1.0.

The initial public repository commit is preserved as the parent of the first
installation release. Private development history is not an ancestor of the
public release. Its local backup is ignored, access restricted and never part of
Git pushes or distribution packages. Never push backup refs, --all or --mirror
from an operator workspace. Publish explicit branch/tag refs without force.

## Outgoing-history checks

Run these against the actual final refs, not merely a clean working directory:

```bash
python3 tools/check_artifacts.py
python3 -m tools.check_history --report var/history-review.json
```

The history tool enumerates every reachable commit tree and unique blob, including
removed versions, and checks commit and annotated-tag messages. It detects private
keys, Argon2 password hashes, common provider/JWT tokens, credential URLs, runtime
paths/files, database signatures, binaries/archives and nonregular tree entries.
Only paths/categories/object IDs are reported; matched values are never printed.
A local ignored --operational-patterns file can add deployment-specific patterns.
Secret/history scanning is heuristic and requires manual review of examples and
metadata; it is not proof that every possible secret format can be detected.

The first-release audit also compares outgoing objects in memory with locally
held private values and working-data markers, without publishing those values or
adding them to the checker. Deployment inventories, internal operator/session
reports, real block-list/audit records and local configurations are excluded.
Examples use documentation IPv4/IPv6 ranges, reserved/documentation ASNs and
example.invalid/example.net names. External IRR/metadata services remain real
public dependencies; the source-check helper requires explicit operator targets.

## Supply and licenses

The distribution contains the application, local assets, pinned hash locks,
config templates, units, install/backup/failover/admin recovery documentation,
tests and the upstream-source TTL patch. Source-package content and independent
Python/Go builds are checked by build_release.py. Binaries, databases, caches,
private keys and backups stay outside ordinary Git. Hemlock is MIT licensed,
copyright biba-odesa. GoBGP and other components retain their notices.

## Publishing

Recheck remote refs immediately before sending. If the remote moved, stop and
review; do not force-overwrite it. Use existing GitHub authentication, never paste
credentials into issues/chat/config URLs. Create an annotated v0.1.0 only if that
name is unused, then push only main and that tag. Confirm both remote main and
peeled tag resolve to the recorded release commit. Installation uses git clone
at the tag; it does not copy source archives from an existing node.
