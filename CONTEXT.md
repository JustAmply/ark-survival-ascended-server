# Domain Model

Shared vocabulary for this repository. Use these terms in code, commits, issues
and documentation; if a concept needs a new name, add it here in the same change.

## Launch line

The argument string handed to `ArkAscendedServer.exe`. It has three parts:

```
TheIsland_WP?listen?Port=7777?RCONPort=27020 -WinLiveMaxPlayers=50 -nosteam
\__________/ \____________________________/  \_________________________/
  map name           query segment                     flags
```

- **Map name** — the leading token, e.g. `TheIsland_WP`, `Ragnarok_WP`.
- **Query segment** — `?`-separated entries attached to the map token. An entry
  is either `Key=Value` or a bare switch such as `listen`.
- **Flag** — a whitespace-separated `-Key=Value` or bare `-Key` token following
  the map token.

## Launch configuration

The structured, order-preserving model of a launch line
(`asa_ctrl.common.launch_config.LaunchConfiguration`). It owns the whole launch
line contract: parsing, lookups, mutation, and rendering back to a string.

Parsing is **structure preserving** — unknown tokens are carried through
verbatim and key order is never rearranged — so `parse(line).render() == line`.
Backward compatibility for existing stacks rests on that identity.

## Overlay

The set of discrete `ASA_*` environment variables (`ASA_MAP`, `ASA_RCON_PORT`,
`ASA_SERVER_ADMIN_PASSWORD`, …) applied on top of a base launch line. The legacy
`ASA_START_PARAMS` string is the base; each discrete variable replaces the
matching entry **in place**. When no discrete variable is set there is no
overlay and the base is rendered back untouched.

`ASA_EXTRA_QUERY_PARAMS` and `ASA_EXTRA_FLAGS` are the **escape hatches**: raw
text merged in after the named variables, so they can override them.

## Runtime settings

The container's non-launch-line configuration contract
(`server_runtime.constants.RuntimeSettings`) — debug hold, restart schedule,
shutdown timings, Proton pinning, log level, timezone. Every runtime switch the
image understands is a field on it, resolvable from any mapping.

## Supervisor

The container-level process owner (`server_runtime.supervisor.ServerSupervisor`).
It registers PID files, starts the restart scheduler and the log streamer,
launches the server through Proton, and handles the graceful shutdown sequence
(`saveworld` over RCON, then SIGTERM, then SIGKILL).

## Wine synchronisation backend

How Wine implements Windows synchronisation objects for the server process
(`server_runtime.wine_sync`): *fsync* (`futex_waitv`, Linux 5.16+), *esync* (one
file descriptor per object) or the slow in-process *server* path. ASA runs
several hundred Wine threads, so the backend dominates its CPU cost. The runtime
raises the soft descriptor limit to the hard limit before launch so esync stays
available, and logs the resulting backend.

## Validation cadence

How often SteamCMD is asked to checksum the whole installation (`ASA_VALIDATE`,
`RuntimeSettings.validate_mode`). Validation reads every installed file, so the
default `first` pays that cost only for the initial install; the [Supervisor](#supervisor)
relaunch loop otherwise runs a plain `app_update`.

## Restart scheduler

The cron-driven companion process (`asa-ctrl restart-scheduler`). It announces
upcoming restarts over RCON and signals the supervisor with `SIGUSR1` when the
restart window is reached. It communicates with the supervisor through PID files
(`ASA_SUPERVISOR_PID_FILE`, `ASA_SERVER_PID_FILE`), never directly.

## Mod database

The JSON file at `/home/gameserver/server-files/mods.json` holding
`ModRecord` entries. Enabled mod ids are merged into the launch line's single
`-mods=` flag at startup.
