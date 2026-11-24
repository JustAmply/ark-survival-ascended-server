# Development and verification

Read [AGENTS.md](../AGENTS.md) before editing. Keep Python runtime code
dependency-free. For terminology and design decisions, see the [domain model](../CONTEXT.md),
[launch configuration ADR](adr/0001-discrete-environment-configuration.md) and
[ARM64 ADR](adr/0002-isolated-arm64-translation.md).

## Python development

Use Python **3.15.x**. From the repository root:

```bash
python3.15 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
python -m pytest -q
```

On PowerShell, use your Python 3.15 executable and activate with
`.venv\Scripts\Activate.ps1`. Linux CI covers POSIX-only tests.

### Installed distribution

After changing packaging, layout or entry points, check a clean non-editable
install in a fresh shell:

```bash
python3.15 -m venv .tmp/package-check
source .tmp/package-check/bin/activate
python -m pip install .
python -I scripts/verify_installed_package.py
```

On PowerShell, activate with `.tmp\package-check\Scripts\Activate.ps1`.

## Local image checks

Rebuild after source changes. Run these checks from the repository root in Bash
using disposable containers:

```bash
docker build -t asa-linux-server:smoke .
docker run --rm --entrypoint python asa-linux-server:smoke -c 'from server_runtime.native_libs import main; raise SystemExit(main())'
docker run --rm --entrypoint /usr/local/bin/asa-ctrl asa-linux-server:smoke --help

docker run --rm --user 25000:25000 --entrypoint python \
  --mount "type=bind,src=${PWD}/scripts/verify_runtime_lifecycle.py,dst=/tmp/verify_runtime_lifecycle.py,readonly" \
  asa-linux-server:smoke /tmp/verify_runtime_lifecycle.py

docker run --rm --user 25000:25000 --entrypoint python \
  --mount "type=bind,src=${PWD}/scripts/verify_translated_lifecycle.py,dst=/tmp/verify_translated_lifecycle.py,readonly" \
  asa-linux-server:smoke /tmp/verify_translated_lifecycle.py --native-fixture
```

The lifecycle fixture substitutes SteamCMD, Proton and ARK to test RCON,
restart and shutdown. The native fixture checks child-process cleanup.

To check maintenance stops, restored backup data and retention using disposable
volumes, run:

```bash
python scripts/verify_backup_lifecycle.py --image asa-linux-server:smoke
```

For backups of a deployment, see [backup and recovery](backups.md).

### Native ARM64 translation

Build on ARM64 with QEMU/binfmt for the x86 guest RootFS stage. Run the
acceptance check using native ARM64 FEX without QEMU handling x86 binaries.

```bash
docker build --platform linux/arm64 -t asa-linux-server:arm64-smoke .
docker run --rm --user 25000:25000 --entrypoint python \
  --mount "type=bind,src=${PWD}/scripts/verify_arm64_translation.py,dst=/tmp/verify_arm64_translation.py,readonly" \
  --mount "type=bind,src=${PWD}/scripts/verify_translated_lifecycle.py,dst=/tmp/verify_translated_lifecycle.py,readonly" \
  asa-linux-server:arm64-smoke /tmp/verify_arm64_translation.py
```

This checks SteamCMD, Windows execution through Proton and translated process
cleanup. Append `--proton-version auto` to test release selection and fallback.
Actual ARK startup and saves require a separate game test.

## Continuous integration

The [change classifier](../scripts/ci_changes.py) skips Python and Docker for
documentation-only changes and runs Python for test-only changes. Runtime
changes, release tags and weekly refreshes run the full checks.

The [workflow](../.github/workflows/test-and-build.yml) publishes preview images
for ready PRs from this repository after smoke checks pass. Fork, draft and
Dependabot PRs validate without publishing. The weekly ARM64 build also
refreshes base images, bypasses the build cache and tests automatic Proton selection.
