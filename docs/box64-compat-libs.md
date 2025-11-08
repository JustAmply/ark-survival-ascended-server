# Box64 Proton Compatibility Libraries

ARM64 builds of the ASA container run the Windows dedicated server via Proton + Box64.
Proton still depends on legacy GnuTLS symbols (`_gnutls_ecdh_compute_key`) that were
removed in Debian **trixie** (libgnutls 3.8+).  To keep the host system on current
packages while satisfying Proton, we vendor a small set of **bookworm** (`3.7.x`)
libraries under `/usr/lib/box64-compat`.

## Package Inventory

| Package | Version (bookworm) |
|---------|--------------------|
| `libgnutls30` | `3.7.9-2+deb12u5` |
| `libidn2-0` | `2.3.3-1` |
| `libtasn1-6` | `4.19.0-2+deb12u1` |
| `libnettle8` | `3.8.1-2` |
| `libhogweed6` | `3.8.1-2` |
| `libgmp10` | `2:6.2.1+dfsg1-1.1` |
| `libp11-kit0` | `0.24.1-2` |
| `libunistring2` | `1.0-2` |
| `zlib1g` | `1:1.2.13.dfsg-1` |

During the Docker build the stage `proton-compat-libs` downloads the exact `.deb`
artifacts for **amd64** and **i386** via `apt-get download pkg:arch=version`, extracts
only the shared objects, and stores:

- `/usr/lib/box64-compat/x86_64-linux-gnu`
- `/usr/lib/box64-compat/i386-linux-gnu`
- `/usr/share/box64-compat/VERSIONS.txt`
- `/usr/share/box64-compat/SHA256SUMS`

The SHA file lists the checksum for every shipped library, and is regenerated automatically
during the build (`find … | sha256sum`).  This satisfies the requirement to document the
exact binary provenance of the vendored artifacts.

## Runtime Integration

`scripts/start_server.sh` injects the compat folders into `LD_LIBRARY_PATH` **only**
when the server runs under Box64.  Native amd64 runs remain untouched.  The log now shows:

```
[asa-start] Box64 compat libraries enabled (LD_LIBRARY_PATH=/usr/lib/box64-compat/...)
```

`tests/test_arm64_compat.sh` validates the shim by:

1. Checking both libgnutls builds export `_gnutls_ecdh_compute_key`.
2. (When Proton is installed) running a short `WINEDEBUG=+loaddll` invocation to ensure
   Proton loads `libgnutls.so.30` from the compat directory.

## Updating the Shim

1. Edit `Dockerfile`’s `pkg-versions` block with the new bookworm security versions.
2. Rebuild the image: `docker buildx build …`.
3. Verify `tests/test_arm64_compat.sh` passes and inspect
   `/usr/share/box64-compat/SHA256SUMS` for the new hashes.
4. Update this document if versions change.

## Removing the Shim

1. Delete the `proton-compat-libs` stage and the `COPY` statements in `Dockerfile`.
2. Remove `/usr/lib/box64-compat*`, `/usr/share/box64-compat/*`.
3. Drop the LD injection block in `scripts/start_server.sh`.
4. Trim the compat-specific tests from `tests/test_arm64_compat.sh`.

This restores the original behavior (but reintroduces the Proton crash on ARM64).
