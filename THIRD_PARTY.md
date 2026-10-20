# Third-party notices

Hemloc code is distributed under MIT, copyright biba-odesa (LICENSE).
Third-party components retain their own licenses; this notice does not relicense
them. The package manager and source archives provide their complete notices.

- GoBGP v4.10.0: osrg/gobgp, Apache-2.0. The included source patch is accompanied
  by the unmodified upstream LICENSE in deploy/patches/LICENSE.GoBGP. GoBGP is a
  separate process and its binary is not part of ordinary Git.
- FastAPI, Starlette, Uvicorn, Pydantic, argon2-cffi and HTTPX: MIT distributions.
- grpcio / grpcio-tools, protobuf and Playwright have their own upstream notices
  (Apache/BSD families); retain wheel/package notices when redistributing them.
- bgpq4 is installed as a Debian package with its upstream/Debian copyright file.
- The Go toolchain and transitive Go modules retain their upstream BSD/other
  licenses. A binary redistribution must include the notices applicable to its
  exact module graph; the build uses upstream go.mod/go.sum and Go module checks.

Pinned dependency versions/hashes are in requirements*.lock and docs/VERSIONS.md.
No third-party daemon or SDK binary is vendored into this repository. Browser
assets use system fonts and local scripts/styles without CDN dependencies.
