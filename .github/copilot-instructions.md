## AI Coding Agent Project Instructions

Focus: Maintain a lean Dockerized ARK: Survival Ascended server image with a zero third‑party Python dependency control tool (`asa_ctrl`). Optimize for clarity, reproducibility, and minimal image growth.

### 1. Big Picture Architecture
* Runtime is a Docker image (`Dockerfile`) based on `ubuntu:24.04` with only core OS + Python stdlib.
* Entry point: `scripts/start_server.sh` (installed as `/usr/bin/start_server.sh`) – orchestrates permission fix (runs as root first, then drops to UID/GID 25000), SteamCMD validation, Proton install/version resolution, dynamic mods injection, optional plugin loader, and final server launch via Proton.
* Control/utility layer: Python package `asa_ctrl` (mounted at `/usr/share/asa_ctrl`, executed via wrapper `/usr/local/bin/asa-ctrl`). Provides:
  * RCON execution (`rcon.py`) – auto-detects password & port from `ASA_START_PARAMS` or INI files.
  * Mod management (`mods.py`) – JSON database at `/home/gameserver/server-files/mods.json` enabling dynamic `-mods=` string injection (`asa-ctrl mods-string`).
  * Config parsing (`config.py`) for start params + INI helpers; start params env var is `ASA_START_PARAMS`.
  * Lightweight logging (`logging_config.py`) controlled by `ASA_LOG_LEVEL`.
* `docker-compose.yml` supplies environment (`ASA_START_PARAMS`, `ENABLE_DEBUG`, cluster + ports) and named volumes (Steam, steamcmd, server-files, cluster-shared).

### 2. Key Environment & Behavior Switches
* `ASA_START_PARAMS` – authoritative launch flags; start script appends dynamic mods (don’t pre-expand yourself).
* `ENABLE_DEBUG=1` – container sleeps (no server launch) for interactive troubleshooting.
* `PROTON_VERSION` – pin GE-Proton; omitted → auto-detect GitHub latest → fallback default (`8-21`).
* `PROTON_SKIP_CHECKSUM=1` – bypass Proton archive hash verification (temporary / last resort).
* `ASA_LOG_LEVEL` – affects all `asa_ctrl` logging.

### 3. Modification Guidelines
* Maintain zero external Python deps; tests & features must rely only on stdlib (image size + simplicity guarantee).
* When adding CLI subcommands: update `cli.py` (argparse), reuse `ExitCodes` in `constants.py`, raise custom errors from `errors.py` for consistent mapping, and export new public helpers in `__init__.py` if intended for programmatic use.
* Preserve idempotent logging setup (`configure_logging()` can be safely called multiple times).
* Avoid changing hard-coded filesystem layout constants unless also adjusting `start_server.sh` (paths tightly coupled with container dirs & volume mounts).
* Concurrency: `ModDatabase` uses an `RLock`; keep state mutations inside the lock and persist via `_write_database()`.

### 4. Start Script Critical Steps (in order)
1. Debug hold → permission normalization + privilege drop.
2. SteamCMD present & validate app `2430930`.
3. Proton version resolution + download + checksum (fail fast unless skipped).
4. Mod string injection (`asa-ctrl mods-string`) appended to `ASA_START_PARAMS`.
5. Plugin loader detection (zip starting with `AsaApi_` → unzip; choose `AsaApiLoader.exe`).
6. Launch via Proton wrapper path under `compatibilitytools.d`.
Changing ordering can break cold start expectations; keep this sequence.

### 5. Testing & Local Dev
* Run tests (pure stdlib): `python -m tests.test_asa_ctrl` (Windows: `py -m tests.test_asa_ctrl`).
* Build image locally: `docker build -t asa-linux-server:dev .`
* Compose up (example): `docker compose up -d` then follow logs `docker logs -f asa-server-1`.
* For iterative Python changes without rebuild, you must rebuild the image (no volume mount overlays are configured for source code).

### 6. Adding Features Safely (Examples)
* New RCON helper: implement in `rcon.py` (reuse `RconClient`), expose via wrapper function, surface in CLI with a subcommand; add targeted test in `tests/test_asa_ctrl.py` (keep it fast and filesystem-light using temp dirs & env overrides like `ASA_GAME_USER_SETTINGS_PATH`).
* New persistent metadata: extend `ModRecord` (provide defaults) → maintain backward compatibility in `from_dict` using `.get()`; bump schema only if strictly needed.

### 7. Common Pitfalls
* Do NOT introduce blocking network calls in CLI code paths that run every start (keep latency in `start_server.sh` only where expected – Proton detection already optional/fallback).
* Avoid printing extraneous stdout in `mods-string` (consumer expects raw token only).
* Changing exit codes breaks existing automation relying on numeric values (cron / scripts). Add new codes only at the end.
* Ensure any new environment variable feature has a sensible fallback so cold starts succeed with default `docker-compose.yml`.

### 8. Security / Stability Notes
* Container runs final process as non-root `gameserver` (UID/GID 25000); any new file operations before privilege drop must chown accordingly or occur after drop.
* Proton archive verification: keep checksum logic intact—modifying may weaken supply-chain assurances.

### 9. Documentation Sync
* If modifying user-facing behavior (env vars, CLI commands, start param construction), update `README.md` + `SETUP.md` (and FAQ if relevant) in the same PR to keep guidance accurate.

Use these rules to stay aligned with the lean, dependency-free design and predictable container lifecycle.