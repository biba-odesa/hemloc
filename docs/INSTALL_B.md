# Install a second node from v0.1.0

This is a preparation guide. Deployment, system package installation and BGP
connections require operator approval. It contains documentation examples only
and does not identify any existing installation.

1. Clone the released sources on the second Debian 13 VM:

   ```bash
   git clone --branch v0.1.0 --single-branch https://github.com/biba-odesa/hemloc.git
   cd hemloc
   git describe --tags --exact-match
   ```

2. Follow [DEPLOYMENT.md](DEPLOYMENT.md) for accounts, dedicated venv, hash-locked
   dependencies and units. Do not copy source trees or live databases from another
   host. Build GoBGP separately using [BUILD.md](BUILD.md); its internal-peer TTL
   patch and exact v4.10.0 API are independent of the Python application.
3. Prepare local configuration with a unique node_id, role=slave, a separate
   database and owner marker, the master's verified HTTPS address and peer node ID.
   Coordinate protection ASNs/prefixes, retained protection cache, IRR settings,
   family route attributes and replication authentication/trust with the master.
4. Generate a distinct certificate/private key with SAN for this node. Install
   trusted CA material and the shared replication secret securely outside Git.
   Each node keeps its own addresses, configuration and keys. Never disable peer
   TLS validation or use proxy environment variables for replication.
5. Start with announcements=no and no production BGP peers. After approved startup,
   let the slave receive the validated snapshot and catch up through the journal.
   Do not create users or rules locally. Verify generation/cursor, rules, accepted
   ASN sets, users and audit; confirm local protection is initialized and retained.
6. Verify desired/excluded prefixes against the master's state. Local protection
   can exclude additional routes without deleting replicated source rules.
   Configure and validate BGP sessions/policies only in a separately approved step.
   Enabling announcements is another explicit operator decision.
7. Exercise outage/recovery and backup procedures before relying on the node.
   A slave never promotes automatically. For manual failover, isolate the old
   master first. When returning it, keep BGP isolated until full sync and route
   verification; changing its role alone does not stop its old GoBGP exports.

Check the exact v0.1.0 commit/tag against the release report before installation.
Never copy another node's local sessions, GoBGP state, configuration or private keys.
