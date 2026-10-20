# Hemloc development rules

- Scope is this project. Inspect the directory before edits; never change other projects.
- Target Debian 13 / Python 3.13; one unprivileged FastAPI/Uvicorn process owns background tasks per SQLite database.
- Default announcements are disabled. Real route writes require explicit operator configuration and initialized protection.
- Never connect to production routers, install/start services, or change network/firewall/SSH without explicit operator authorization.
- Tests use isolated temporary databases, loopback services and documentation prefixes. Never mutate working data during tests.
- Never restart GoBGP on a rule change. Touch only demonstrably owned paths; no blanket withdrawals.
- Master-only writes use the shared service layer. Data, audit and journal commit atomically. Slaves never merge divergent branches.
- Protection prohibits equality and more-specific candidates, allows covering aggregates, and retains cached data on upstream failures.
- Empty or anomalous ASN updates require confirmation of the exact proposed set. Preserve working data on source/network failures.
- Keep Argon2id, CSRF, session-version revocation and login throttling. Never log credentials, keys, tokens or password hashes.
- Configuration, sessions, protection cache and GoBGP state stay local. Replication verifies TLS and bypasses proxies.
- English code comments and local web assets only; safely escape untrusted text.
- Never commit runtime artifacts, local configuration, credentials or deployment inventories. Scan all outgoing history before publishing.
- Run meaningful tests, update docs/PLAN.md and report limitations. No push without explicit operator authorization.
