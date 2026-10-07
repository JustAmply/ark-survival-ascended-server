# Development and verification

The application has no third-party Python runtime dependencies. The Dockerfile
defines the image's Python and OS versions. Read [AGENTS.md](../AGENTS.md) before
editing, [CONTEXT.md](../CONTEXT.md) for contract ownership, and the ADRs for
[launch configuration](adr/0001-discrete-environment-configuration.md) and
[ARM64 translation](adr/0002-isolated-arm64-translation.md).
For running a published image, use [SETUP.md](../SETUP.md).

## Python development

From a repository checkout, create a virtual environment and install the project:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
python -m pytest -q
```

On Windows PowerShell, activate with `.venv\Scripts\Activate.ps1` instead.
Editable installation registers `asa-ctrl` and makes source edits available
immediately. Start with the tests relevant to the change, then run the complete
suite. POSIX-only cases skip on Windows; Linux CI exercises them.

### Installed distribution

After changing packaging, package layout or console entry points, verify a
non-editable installation in a separate clean environment. In a fresh shell:

```bash
python -m venv .tmp/package-check
source .tmp/package-check/bin/activate
python -m pip install .
python -I scripts/verify_installed_package.py
```

On PowerShell, activate with `.tmp\package-check\Scripts\Activate.ps1`.
Isolated mode prevents imports from the working directory. A clean non-editable
install checks the distribution's subpackages and console command independently
of the source-tree tests.

## Local image checks

The following commands use a Bash shell from the repository root. They use
disposable containers and do not mount an existing server's data. Rebuild after
source changes; the Compose files do not overlay Python source into the image.

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

The runtime lifecycle check exercises RCON, scheduler warnings, restart, save
delay and shutdown for discrete settings and the legacy launch string. It
replaces SteamCMD, Proton and ARK at their external interfaces. The native
fixture check verifies translated process-group cleanup using Linux Python
children; it does not establish FEX or Proton compatibility.

### Native ARM64 translation

On a native ARM64 host, use a Docker builder with AMD64 emulation (QEMU/binfmt)
for the x86 guest RootFS stage; CI configures this through `setup-qemu`.
The acceptance checks themselves must run through native ARM64 FEX, without
QEMU handling x86 binaries at runtime. Build and run:

```bash
docker build --platform linux/arm64 -t asa-linux-server:arm64-smoke .
docker run --rm --user 25000:25000 --entrypoint python \
  --mount "type=bind,src=${PWD}/scripts/verify_arm64_translation.py,dst=/tmp/verify_arm64_translation.py,readonly" \
  --mount "type=bind,src=${PWD}/scripts/verify_translated_lifecycle.py,dst=/tmp/verify_translated_lifecycle.py,readonly" \
  asa-linux-server:arm64-smoke /tmp/verify_arm64_translation.py
```

This downloads SteamCMD and checksum-verified Proton, checks real Windows
execution through FEX, and tests translated restart/shutdown with descendant
cleanup. It uses a pinned Proton baseline; add `--proton-version auto` after
the script path to test default release selection and its preflight fallback.
These checks do not install ARK or prove game saving and sustained operation.
An emulated image build also does not prove native ARM64 runtime behavior.

## Continuous integration

[The workflow](../.github/workflows/test-and-build.yml) selects checks through
[ci_changes.py](../scripts/ci_changes.py): documentation-only changes skip Python
and Docker; test-only changes run Python checks; runtime, image, metadata,
workflow and unrecognized changes run all checks. Release tags and the weekly
refresh always run all checks. The main job reports a status even when checks
are skipped.

Image publication follows successful smoke checks. ARM64 runs on a native
runner, with QEMU used only to build its x86 guest RootFS. Its weekly check also
tests automatic Proton selection. Ordinary ARM64 builds refresh the FEX runtime
stage; the weekly refresh pulls base images and rebuilds all stages without
cache. See [ADR 0002](adr/0002-isolated-arm64-translation.md) for the rolling
package policy and reproducibility tradeoff.

Draft, fork and Dependabot PRs validate without publishing images. Ready PRs
from this repository publish preview tags. Obsolete PR runs are cancelled;
main and tag runs finish in sequence. The workflow is the source of truth for
job limits, tags and individual smoke-check steps.
