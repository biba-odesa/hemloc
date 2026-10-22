# Canonical installation identity

Version 0.4.0 standardizes the application, package, CLI, service account/unit and
installation paths on **hemlock**. New installs use DEPLOYMENT.md or INSTALL_B.md.
Existing installations require the explicit [migration guide](MIGRATION_LEGACY.md),
not a directory move or running the fresh installer over active files.

Node IDs, route ownership, TLS and replicated history are operator identities;
they must remain stable during the name/path migration. Both peers must be
upgraded together because the canonical HTTP peer header changes in 0.4.0.
The repository remains https://github.com/biba-odesa/hemlock.git. Existing tags are
immutable; select a published canonical-release commit/tag for new installation.

From 0.4.1 onward, compatibility is an explicit independent protocol number;
application versions may differ. The canonical node header remains stable.
Ordinary updates use B then A without reinstalling the slave; see
[REPLICATION_PROTOCOL.md](REPLICATION_PROTOCOL.md). The historical header change
was unnecessary for renaming and is not a model for future releases.
