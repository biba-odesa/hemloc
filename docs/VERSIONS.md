# Dependency and API baseline

Development target: Debian 13, CPython 3.13, system SQLite (3.46.1). Runtime requirements.lock and requirements-test.lock pin all resolved dependencies with hashes. Installation with --require-hashes and pip check passed on this VM. Build backend is pinned in pyproject.toml; test tools include Playwright 1.64.0, pexpect 4.9.0 and grpcio-tools 1.78.0. Lockfiles were generated with pip-tools 7.6.2. Do not silently update major versions.

| Component | Selected version | Purpose |
|---|---|---|
| FastAPI | 0.135.1 | HTTP API, requires Pydantic >=2.7 and Starlette >=0.46 |
| Starlette | 0.52.1 | ASGI sessions/cookies/static responses foundation |
| Pydantic | 2.12.5 | API request validation |
| Uvicorn | 0.42.0 | Embedded single-worker ASGI server, no standard extras |
| argon2-cffi | 25.1.0 | Argon2id passwords |
| grpcio | 1.78.0 | Loopback GoBGP transport |
| protobuf | 6.33.5 | Minimal v4 message descriptors |
| HTTPX | 0.28.1 | Optional ASGI/integration tests only |
| setuptools | 80.9.0 | Package building |
| GoBGP | **4.10.0 only** | Separate gobgpd service, `/api.GoBgpService/*` |
| bgpq4 | **1.12-1**, Debian 13 package | IRR WHOIS prefix expansion |

No production compatibility with GoBGP 3.x is claimed. API enum numbering and service names changed in v4. The adapter defines a minimal protobuf **projection** of the 4.10.0 schema, uses protobuf-native parsing/serialization (not a handwritten protobuf codec), and requests binary NLRI/path attributes. Binary BGP unicast attribute generation/parsing is owned by Hemlock and tested separately. Unknown protobuf fields remain private and are never serialized into observation/audit; peer auth_password fields are not projected. Static source review confirmed Family AFI/SAFI values and binary-path fallback against the pinned common.proto/pkg/apiutil/util.go. Verified against compiled official descriptors: 16 projected messages, 39 fields and four RPC signatures. Real 4.10.0 add/list/delete, IPv6 MP_REACH, attributes, same-NLRI ownership isolation and daemon recovery tests pass. ListPeer and nonempty Adj-RIB-Out were additionally checked with an isolated IPv4-transport iBGP session carrying IPv4 and IPv6 routes; receiver attributes/export, withdrawal and peer restart passed. Exact TableLookupPrefix queries avoid a full RIB scan before each write. Pinning the service name makes a v3 daemon fail rather than use a mismatched API.

Ownership: reserve large community `64512:100:1` on block-a, `64512:100:2` on block-b, or configure an operator-controlled namespace. It is an ownership tag, not authentication. GoBGP 4.10.0 returns an AddPath UUID but omits UUID from ListPath. Hemlock derives a stable nonzero uint32 path identifier from SHA256 of the configured owner tuple, sets it on AddPath and requires that identifier, the ownership community and an absent neighbor/source address before claiming a local path. DeletePath always contains a freshly observed explicit path; the daemon matches its NLRI/source/path ID. It never sends an empty deletion or assumes UUID availability. This addresses the crash window without relying on a local post-gRPC UUID save. A real same-NLRI/different-owner test proves withdrawal preserves the other local path. Keep the tag stable across restarts/failovers; do not share it with other injectors. Foreign local-prefix collisions cause an error before insertion. Learned paths are never withdrawn. Strip the internal marker in a separately reviewed export policy if needed; configuring router peers/policies is outside automatic installation.

bgpq4 uses -p -4/-6 -F FORMAT -h SERVER -S SOURCES ASNUMBER, where FORMAT is the Python string "%n/%l\n" with an actual newline in the argv value, with an argv list, no shell and no aggregation flags. Both family invocations must succeed; otherwise the full previous working set remains. Real 1.12 tests with a loopback IRRD fixture cover v4/v6, private ASN, empty and malformed responses. -p is required for private ASN; a literal backslash+n is not a newline in this utility version. Bounded stderr is inspected for ERROR:/FATAL: even when the utility exits zero; diagnostic text is never logged or exposed. Sources and utility selection are local INI settings; do not substitute bgpq3 without adapter/fixture verification.

Upstream references:

- [FastAPI 0.135.1 metadata](https://pypi.org/pypi/fastapi/0.135.1/json)
- [Starlette 0.52.1](https://pypi.org/project/starlette/0.52.1/), [Pydantic 2.12.5](https://pypi.org/project/pydantic/2.12.5/)
- [Uvicorn 0.42.0](https://pypi.org/project/uvicorn/0.42.0/), [Argon2 25.1.0](https://pypi.org/project/argon2-cffi/25.1.0/)
- [grpcio 1.78.0](https://pypi.org/project/grpcio/1.78.0/), [protobuf 6.33.5](https://pypi.org/project/protobuf/6.33.5/)
- [GoBGP 4.10.0 release](https://github.com/osrg/gobgp/releases/tag/v4.10.0)
- [Pinned GoBGP API](https://github.com/osrg/gobgp/tree/v4.10.0/proto/api)
- [Debian 13 bgpq4 package](https://packages.debian.org/trixie/bgpq4), [bgpq4 options](https://github.com/bgp/bgpq4/blob/master/README.md)

Additional pinned implementation references: [Family wire values](https://github.com/osrg/gobgp/blob/v4.10.0/proto/api/common.proto), [binary NLRI/attribute handling](https://github.com/osrg/gobgp/blob/v4.10.0/pkg/apiutil/util.go). Source review is not a substitute for a daemon integration test.

The optional TTL build uses **4.10.0+hemloc-ibgp-ttl1**, the same v4.10.0 API with a minimal FSM socket-TTL patch for explicitly configured iBGP TTL. The stock binary ignores multihop-ttl for internal peers. Exact patch, source/toolchain checksums and independent reproducible build instructions: [BUILD.md](BUILD.md). Do not silently replace this build with unpatched upstream when a nondefault internal-peer TTL is required.

Read-only UI update projects Peer.timers / Timers.state / TimersState.uptime (google.protobuf.Timestamp) for observed session uptime. AddPath/DeletePath fields and all control behavior are unchanged.

Release builds use the hash-locked requirements-build.lock in a dedicated venv.
Do not use --no-build-isolation with an unverified development backend version.

Hemlock 0.2.1 changes local observation storage only; dependencies, GoBGP API,
replication protocol and persisted-state schema remain unchanged.

Hemlock 0.3.0 adds startup role transitions and a private sidecar fence. Runtime
dependencies, GoBGP v4 API and replication wire protocol stay unchanged. Local
SQLite archives old promotion journals; deploy both nodes before role changes.
