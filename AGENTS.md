## AI Coding Agent Project Instructions

Focus: Maintain a lean Dockerized ARK: Survival Ascended server image with a zero third‑party Python dependency control tool (`asa_ctrl`). Optimize for clarity, reproducibility, and minimal image growth.

### 1. Big Picture Architecture
* Runtime is a Docker image built from `Dockerfile`; its current `FROM` line is the source of truth for the base OS and Python version. Inspect it before making base-specific changes.
* Entry point: standalone Python runtime package `server_runtime` (`python -m server_runtime`) – handles timezone sync (`TZ`), optional debug sleep, permission fix (runs as root first, then drops to UID/GID 25000), SteamCMD validation, Proton install/version resolution, default admin password enforcement / start param fallback, dynamic mods injection, forced `-nosteam`, optional plugin loader, log streaming, and supervised server launch via Proton (with restart scheduler support).
* Control/utility layer: Python package `asa_ctrl` (mounted at `/usr/share/asa_ctrl`, executed via wrapper `/usr/local/bin/asa-ctrl`). Provides:
  * RCON execution (`rcon.py`) – auto-detects password & port through `AsaSettings`, i.e. discrete `ASA_*` variables, then `ASA_START_PARAMS`, then INI files.
  * Mod management (`mods.py`) – JSON database at `/home/gameserver/server-files/mods.json` enabling dynamic `-mods=` string injection (`asa-ctrl mods-string`).
  * Launch line ownership (`common/launch_config.py`) – `LaunchConfiguration` parses, overlays and renders the server launch line; the single owner of that contract. See `CONTEXT.md` for the vocabulary and `docs/adr/0001-*` for the design decision.
  * Config seam (`common/config.py`) – `AsaSettings` is the only place asa_ctrl reads the environment; launch-line questions delegate to `LaunchConfiguration`.
  * Restart scheduler (`core/restart_scheduler.py`) – cron-based warnings + supervisor signalling (`restart-scheduler` CLI) governed by server PID files + env.
  * Lightweight logging (`logging_config.py`) controlled by `ASA_LOG_LEVEL`.
* `docker-compose.yml` supplies environment (discrete `ASA_*` launch variables, `ENABLE_DEBUG`, cluster + ports) and named volumes (Steam, steamcmd, server-files, cluster-shared). `docker-compose.dev.yml` deliberately stays on the legacy `ASA_START_PARAMS` string so the backward-compatible path keeps being exercised.

### 2. Key Environment & Behavior Switches
* `ASA_START_PARAMS` – the *base* launch line; runtime merges dynamic mods, enforces `-nosteam`, and injects a default `ServerAdminPassword` (or a full default map payload) when absent.
* Discrete launch variables – `ASA_MAP`, `ASA_SESSION_NAME`, `ASA_PORT`, `ASA_RCON_PORT`, `ASA_RCON_ENABLED`, `ASA_SERVER_ADMIN_PASSWORD`, `ASA_SERVER_PASSWORD`, `ASA_SPECTATOR_PASSWORD`, `ASA_MAX_PLAYERS`, `ASA_CLUSTER_ID`, `ASA_CLUSTER_DIR`, `ASA_MODS`, `ASA_BATTLEYE`, plus the `ASA_EXTRA_QUERY_PARAMS` / `ASA_EXTRA_FLAGS` escape hatches. They overlay `ASA_START_PARAMS` entry by entry. Precedence: extras > named vars > `ASA_START_PARAMS` > defaults.
* `ENABLE_DEBUG=1` – container sleeps (no server launch) for interactive troubleshooting.
* `PROTON_VERSION` – pin GE-Proton; omitted → auto-detect GitHub latest → fallback default (`10-34`).
* `PROTON_SKIP_CHECKSUM=1` – bypass Proton archive hash verification (temporary / last resort).
* `PROTON_SKIP_PREFLIGHT=1` – skip the pre-launch check that the installed Proton build can load its host libraries. The check's verdict is cached per `ASA_IMAGE_VERSION` next to the Proton install, so the restart loop does not pay for the subprocess repeatedly.
* `ASA_VALIDATE=first|always|never` – how often SteamCMD checksums the installation. Defaults to `first` (initial install only); `always` restores the old behavior of validating on every supervised relaunch.
* `SERVER_RESTART_CRON` / `SERVER_RESTART_WARNINGS` / `SERVER_RESTART_DELAY` – enable built-in scheduler, warning cadence, and relaunch delay.
* `ASA_SHUTDOWN_SAVEWORLD_DELAY` / `ASA_SHUTDOWN_TIMEOUT` – graceful shutdown timing when stopping the container.
* `TZ` – optional timezone sync; updates `/etc/localtime` when running as root.
* `ASA_LOG_LEVEL` – affects all `asa_ctrl` logging.

### 3. Modification Guidelines
* Maintain zero external Python deps; tests & features must rely only on stdlib (image size + simplicity guarantee).
* When adding CLI subcommands: update `cli.py` (argparse), reuse `ExitCodes` in `constants.py`, raise custom errors from `errors.py` for consistent mapping, and export new public helpers in `__init__.py` if intended for programmatic use.
* When adding a launch setting: add one entry to `QUERY_ENV_OVERRIDES` or `FLAG_ENV_OVERRIDES` in `common/launch_config.py`. The launcher, the CLI and RCON discovery pick it up automatically – do not parse `ASA_START_PARAMS` anywhere else.
* When adding a runtime switch (not part of the launch line): add a field to `RuntimeSettings` in `server_runtime/constants.py` and read it from there rather than calling `os.environ` in the consuming module.
* `LaunchConfiguration.parse(line).render() == line` is the backward-compatibility guarantee for existing stacks. Keep parsing structure preserving; anything that reorders or drops unknown tokens breaks it.
* Preserve idempotent logging setup (`configure_logging()` can be safely called multiple times).
* Avoid changing hard-coded filesystem layout constants unless also adjusting `server_runtime/constants.py` (paths tightly coupled with container dirs & volume mounts).
* Restart scheduler is invoked via `asa-ctrl restart-scheduler` and relies on PID files + env wiring from the runtime supervisor; keep its interfaces stable.
* Concurrency: `ModDatabase` uses an `RLock`; keep state mutations inside the lock and persist via `_write_database()`.

### 4. Startup Runtime Critical Steps (in order)
1. (Root) Optional timezone configuration via `TZ`, ensure machine ID compatibility, then debug hold (sleep) if requested.
2. Permission normalization + privilege drop to UID/GID 25000.
3. Ensure SteamCMD is present.
4. Register supervisor PID and start restart scheduler when `SERVER_RESTART_CRON` is set.
5. Update app `2430930` server files via SteamCMD, validating according to `ASA_VALIDATE`.
6. Enforce `ServerAdminPassword` presence (append default or full default start params) before launch args.
7. Proton version resolution → download (per-architecture release assets) → checksum validation (unless skipped) → launchability preflight with fallback to `FALLBACK_PROTON_VERSION` → compat data prep.
8. Launch line resolution (`LaunchConfiguration.from_env`): `ASA_START_PARAMS` as base, discrete `ASA_*` variables overlaid, `mods.json` ids merged into `-mods=`, then force `-nosteam`. The result is written back to `ASA_START_PARAMS` for child processes.
9. Runtime prep (XDG paths + compat exports, raise the descriptor limit and report the Wine sync backend), plugin loader detection (zip starting with `AsaApi_` → unzip; choose `AsaApiLoader.exe`).
10. Start log tailer and launch via Proton wrapper under `compatibilitytools.d` (supervisor handles crash/USR1 restarts with configured delay).
Changing ordering can break cold start expectations; keep this sequence.

### 5. Testing & Local Dev
* Install dev tooling in a virtual environment with `python -m pip install -e ".[dev]"`, then run the complete suite with `python -m pytest -q`.
* After changing `pyproject.toml`, package layout, or console entry points, install the project non-editably in a clean environment, then run `python -I scripts/verify_installed_package.py`; source-tree tests alone do not validate the installed distribution.
* Build image locally: `docker build -t asa-linux-server:dev .`
* Compose up (example): `docker compose up -d` then follow logs `docker logs -f asa-server-1`.
* For iterative Python changes without rebuild, you must rebuild the image (no volume mount overlays are configured for source code).

### 6. Adding Features Safely (Examples)
* New RCON helper: implement in `rcon.py` (reuse `RconClient`), expose via wrapper function, surface in CLI with a subcommand; add targeted test in `tests/test_asa_ctrl.py` (keep it fast and filesystem-light using temp dirs & env overrides like `ASA_GAME_USER_SETTINGS_PATH`).
* New persistent metadata: extend `ModRecord` (provide defaults) → maintain backward compatibility in `from_dict` using `.get()`; bump schema only if strictly needed.

### 7. Common Pitfalls
* Do NOT introduce blocking network calls in CLI code paths that run every start (keep latency in `server_runtime` only where expected – Proton detection already optional/fallback).
* Avoid printing extraneous stdout in `mods-string` (consumer expects raw token only).
* Keep restart scheduler contract intact (env variables, PID files, `restart-scheduler` command) so scheduled restarts can signal the supervisor.
* Preserve automatic `ServerAdminPassword` fallback and `-nosteam` injection; downstream logic assumes these guarantees.
* Mods from `mods.json` are merged into a single `-mods=` flag; never append a second one.
* Changing exit codes breaks existing automation relying on numeric values (cron / scripts). Add new codes only at the end.
* Ensure any new environment variable feature has a sensible fallback so cold starts succeed with default `docker-compose.yml`.
* Native libraries GE-Proton dlopens are declared in `server_runtime/native_libs.py`; add new ones there **and** to the `Dockerfile` apt list, since CI smoke-tests the built image against that list.

### 8. Security / Stability Notes
* Container runs final process as non-root `gameserver` (UID/GID 25000); any new file operations before privilege drop must chown accordingly or occur after drop.
* Proton archive verification: keep checksum logic intact—modifying may weaken supply-chain assurances.
* Shutdown path triggers `saveworld` via RCON with configurable delays/timeouts; keep this graceful sequence intact.

### 9. Documentation Sync
* If modifying user-facing behavior (env vars, CLI commands, launch line construction), update `README.md` + `SETUP.md` (and FAQ if relevant) in the same PR to keep guidance accurate.
* If you introduce or sharpen a domain term, add it to `CONTEXT.md` in the same change. Record load-bearing architectural decisions as an ADR in `docs/adr/`.

Use these rules to stay aligned with the lean, dependency-free design and predictable container lifecycle.
