# GoBGP patch provenance

The patch is against osrg/gobgp v4.10.0, pkg/server/fsm.go. It preserves TTL
security priority and the external-peer default while honoring an explicit
multihop TTL for internal peers. It does not change the v4 API.

Upstream: https://github.com/osrg/gobgp/tree/v4.10.0
Upstream license: Apache-2.0, reproduced without modification in LICENSE.GoBGP.
This license notice applies to the upstream GoBGP material, not to all of Hemloc.

The patch file is source, not a daemon binary. Verified archive/toolchain hashes
and deterministic rebuild instructions are in ../../docs/BUILD.md. Generated
binaries must stay outside ordinary Git and are not installed by the build tool.
