# Setup and administration

For your first server, follow the [quick start](README.md#quick-start).
For an existing server, jump to [maps](#choose-a-map), [mods](#mods-and-custom-maps),
[backups](#storage-and-backups), [networking](#networking) or [restarts](#restarts-and-shutdown).

## Server configuration

Edit the service's `environment` in `docker-compose.yml`. Run
`docker compose up -d -t 300` to apply Compose or `.env` changes.

### Choose a map

Set one world per service, e.g. `ASA_MAP: Ragnarok_WP`. Each map loads its own
save. [Back up your world](docs/backups.md) before switching.

| Official map | What to expect | `ASA_MAP` |
| --- | --- | --- |
| The Island | Tropical beaches and snowy peaks | `TheIsland_WP` |
| Scorched Earth | Desert heat and sandstorms | `ScorchedEarth_WP` |
| The Center | Oceans, floating islands and caverns | `TheCenter_WP` |
| Aberration | Underground climbing, gliding and radiation | `Aberration_WP` |
| Extinction | Ruined city, wasteland and biome domes | `Extinction_WP` |
| Ragnarok | Viking ruins, highlands and desert | `Ragnarok_WP` |
| Valguero | White cliffs, valleys and an underground biome | `Valguero_WP` |
| Genesis Part 1 | Missions across five simulated biomes | `Genesis_WP` |
| Astraeos (paid DLC) | Greek mythology, islands and coastal exploration | `Astraeos_WP` |
| Lost Colony (paid DLC) | Frozen wilderness around Arat Prime | `LostColony_WP` |

See also [custom maps](#mods-and-custom-maps) and [multi-map clusters](#multi-server-clusters).

### Launch settings

| Setting | Purpose | Default or Compose value |
| --- | --- | --- |
| `ASA_MAP` | World | `TheIsland_WP` |
| `ASA_SESSION_NAME` | Server browser name | Game-generated |
| `ASA_PORT` / `ASA_RCON_PORT` | Game (UDP) / admin (TCP) port | `7777` / `27020` |
| `ASA_RCON_ENABLED` | Remote console, readiness check and shutdown save | `True` |
| `ASA_SERVER_ADMIN_PASSWORD` | RCON and admin access | Required by Compose (legacy fallback: `changeme`) |
| `ASA_SERVER_PASSWORD` / `ASA_SPECTATOR_PASSWORD` | Join / spectator password | Unset |
| `ASA_MAX_PLAYERS` | Player slots | Compose sets `50` |
| `ASA_CLUSTER_ID` / `ASA_CLUSTER_DIR` | Transfer group and shared directory | Compose sets `default` and `/home/gameserver/cluster-shared` |
| `ASA_MODS` | Comma-separated CurseForge IDs | Unset |
| `ASA_BATTLEYE` | Set to `false` to disable BattlEye | Unset |

For mounted secrets and strict admin-password checks, see [password files](docs/secrets.md).

For other ARK options, use `ASA_EXTRA_QUERY_PARAMS` (e.g.
`AllowFlyerCarry=True?ForceRespawnDinos=True`) or `ASA_EXTRA_FLAGS`
(e.g. `-servergamelog -NoTransferFromFiltering`).

### Legacy launch strings and precedence

Existing `ASA_START_PARAMS` strings work as the base launch line. Named
`ASA_*` variables override matching entries, then `ASA_EXTRA_QUERY_PARAMS` and
`ASA_EXTRA_FLAGS` take precedence. Unknown options are preserved and the
runtime enforces `-nosteam`. [Inspect the resolved settings](docs/diagnostics.md).

## Storage and backups

| Volume | Container path | Contents |
| --- | --- | --- |
| `server-files-1` | `/home/gameserver/server-files` | Game files, saves, configuration, `mods.json` and Proton compatibility data |
| `steam-1` | `/home/gameserver/Steam` | Installed Proton builds |
| `steamcmd-1` | `/home/gameserver/steamcmd` | SteamCMD installation |
| `cluster-shared` | `/home/gameserver/cluster-shared` | Shared character and creature transfer data |

Game INIs live in `ShooterGame/Saved/Config/WindowsServer` inside
`server-files-1`. To locate host mounts, run
`docker inspect asa-server-1 --format '{{json .Mounts}}'`.

> [!WARNING]
> `docker compose down -v` deletes the volumes holding your saves.
> [Back up and restore a world](docs/backups.md).

## Networking

**Players use UDP 7777.** Allow it through host/cloud firewalls and forward it
to the Docker host on a home router. If you change `ASA_PORT`, update the
Compose mapping and firewall rules too.

**RCON uses TCP 27020 inside Docker.** Health checks, shutdown saves and
[local admin commands](#rcon) work with the default unpublished port.

<details>
<summary>Connect a remote RCON client over SSH</summary>

RCON transmits the admin password in cleartext. Bind the port to loopback
under the service's existing `ports` list:

```yaml
- "127.0.0.1:27020:27020/tcp"
```

If you changed `ASA_RCON_PORT`, replace the rightmost port. Apply with
`docker compose up -d -t 300`, then run this on your workstation:

```sh
ssh -N -L 127.0.0.1:27020:127.0.0.1:27020 user@docker-host
```

Keep the tunnel open and connect to `127.0.0.1:27020` with your admin password.

</details>

## Server management

[Start, stop or update](README.md#after-your-first-session) | [Check readiness and configuration](docs/diagnostics.md)

### Mods and custom maps

Set `ASA_MODS: "12345,67891"` in Compose, or manage CurseForge IDs from the CLI.
To enable a mod and load it on restart:

```bash
docker compose exec asa-server-1 asa-ctrl mods enable 12345
docker compose exec asa-server-1 asa-ctrl mods list --enabled-only
docker compose restart -t 300 asa-server-1
```

`mods disable` keeps the entry for later, `mods remove` deletes it and
`mods list` shows all entries. Both Compose and database IDs load, so remove
an ID from both if enabled in both. [Recover a damaged database](docs/mod-safety.md).

For a custom map, enable its mod ID and set `ASA_MAP` to the author's level
name. Recreate the service to apply the changes.

### ServerAPI plugins

Place the loader's `AsaApi_*.zip` in `ShooterGame/Binaries/Win64/` in the
server-files volume. On launch the runtime extracts and removes the ZIP and
starts `AsaApiLoader.exe` if present. Follow each plugin's installation guide.

### RCON

```bash
docker compose exec asa-server-1 asa-ctrl rcon --exec 'saveworld'
docker compose exec asa-server-1 asa-ctrl rcon --exec 'serverchat Hello players!'
```

The CLI discovers the port and password from launch settings or
`GameUserSettings.ini`. A pause over 50 ms between response packets can
truncate long output. [Troubleshoot RCON](FAQ.md#rcon-commands-fail).

## Multi-server clusters

1. Uncomment the second service **and its volume declarations** in Compose.
2. Choose its map, distinct game/RCON ports and separate game, Steam and SteamCMD volumes.
3. Use the same `ASA_CLUSTER_ID`, `ASA_CLUSTER_DIR` and `cluster-shared` volume on all members.
4. Run `docker compose up -d -t 300` and open each server's UDP game port.

## Restarts and shutdown

On shutdown the supervisor allows 15 seconds for the RCON save request. If it
may have reached the game, the supervisor waits the configured save delay
before stopping the process.

| Variable | Default | Purpose |
| --- | --- | --- |
| `ASA_SHUTDOWN_SAVEWORLD_DELAY` | `15` | Seconds allowed for saving after the RCON attempt |
| `ASA_SHUTDOWN_TIMEOUT` | `180` | Seconds after signalling the server process before forced cleanup |
| `SERVER_RESTART_DELAY` | `15` | Seconds before relaunch |

Keep Compose's `stop_grace_period: 300s` and command-line `-t 300` long enough
for saving and shutdown. To schedule a restart, use five-field cron in the
container's `TZ` timezone:

```yaml
environment:
  SERVER_RESTART_CRON: "0 4 * * *"
  SERVER_RESTART_WARNINGS: "30,5,1"
```

The example restarts at 04:00 with chat warnings 30, 5 and 1 minute beforehand.
Remove `SERVER_RESTART_CRON` to disable scheduled restarts.

### Crash recovery

After preparation errors or runs under 120 seconds, retries back off from
`SERVER_RESTART_DELAY` to `ASA_RESTART_MAX_DELAY` (default 300 seconds).
`ASA_RESTART_MAX_FAILURES` defaults to five consecutive failures. `0`
allows unlimited retries. Scheduled restarts and longer runs reset the count.
[ARM64](#arm64-experimental) can stop earlier.

## Startup and Proton

### Game updates and validation

SteamCMD installs a missing server automatically. Select the update and
checksum schedules independently:

| Setting | Default | Alternatives |
| --- | --- | --- |
| `ASA_UPDATE` | `always`: every launch | `startup`: once per container process. `manual`: install only if missing. |
| `ASA_VALIDATE` | `first`: checksum initial install | `always`: checksum every install or update. `never`: skip checksums. |

To update in manual mode, set `startup`, recreate the service, then restore
`manual` and reapply. Full validation reads every file and can slow startup.

### Proton version and verification

Automatic selection falls back to the known Proton baseline if selection or
preflight fails. A failed explicit pin stops startup.

| Variable | Purpose |
| --- | --- |
| `PROTON_VERSION` | Pin a build, for example `10-34`; omit for automatic selection |
| `PROTON_SKIP_CHECKSUM` | `1` bypasses archive verification; use only as a temporary last resort |
| `PROTON_SKIP_PREFLIGHT` | `1` skips the host-library launch check |

For missing libraries, see [Proton troubleshooting](FAQ.md#proton-reports-a-missing-library).

## ARM64 experimental

Use `ghcr.io/justamply/asa-linux-server:arm64-experimental` or
`:<version>-arm64-experimental`. Verify startup, saving and sustained play on
your host. FEX runs without privileged mode or a `/dev/fuse` mount.

| Variable | Default | Purpose |
| --- | --- | --- |
| `ASA_TRANSLATOR_MODE` | `auto` | Select FEX on ARM64; `fex` requires it explicitly, `none` disables translation |
| `ASA_TRANSLATOR_PROBE_TIMEOUT` | `120` | Seconds allowed for the startup translation probe |
| `ASA_PROTON_PROFILE` | `balanced` | `safe` disables esync/fsync |

Two translated runs under 120 seconds switch retries to `safe`. An early exit
on `safe` stops the supervisor. Preparation errors do not trigger this switch.
[ARM64 troubleshooting](FAQ.md#arm64-translation-fails) | [Translation design](docs/adr/0002-isolated-arm64-translation.md)

## Resource tuning and debug mode

- **Logs:** Set `ASA_LOG_LEVEL` (default `INFO`).
- **Resources:** Measure with `docker stats asa-server-1` before tuning memory
  or swap. If Wine reports a slow synchronization backend, check the Compose
  soft and hard `nofile` limits (both `524288`).
- **Debug shell:** Set `ENABLE_DEBUG: "1"`, recreate the service and run
  `docker compose exec asa-server-1 bash`. Set it back to `"0"` and recreate
  to launch the game.
