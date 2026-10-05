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

## Launch environment

The environment a child process is started with
(`server_runtime.launch_env.LaunchEnvironment`), built as a value and handed to
`subprocess.Popen(env=...)`. The container's own environment is configuration
**input**: read once into [Runtime settings](#runtime-settings) and the
[Launch configuration](#launch-configuration), never written back to.

Two children need two different slices, which is what earns the seam:

- **`for_server`** — Steam compatibility paths, a writable `XDG_RUNTIME_DIR`,
  headless SDL defaults, the effective Proton profile, and the resolved launch
  line. The headless values are defaults: an operator who supplies their own
  keeps them.
- **`for_scheduler`** — the PID files the [Restart scheduler](#restart-scheduler)
  signals through, and its warning cadence.

The supervisor keeps the server's launch environment so that RCON discovery
during shutdown reads the same values the server itself was given.

Three environment writes remain deliberate and sit outside this module: `TZ`
(set before any child exists), the privilege-drop marker (`os.execvp` passes the
current environment), and the `PROTON_VERSION` export described under
[Proton selection](#proton-selection).

## Supervisor

The container-level process owner (`server_runtime.supervisor.ServerSupervisor`).
It registers PID files, starts the restart scheduler and the log streamer,
launches the server through Proton, and handles the graceful shutdown sequence
(`saveworld` over RCON, then SIGTERM, then SIGKILL).

A translated launch owns a process group as well as its prefix-specific Wine
session. Graceful shutdown waits for living group members, including children
whose wrapper already exited. Cleanup ends the Wine session before the next
launch so detached Wine processes cannot survive a restart or retain the
previous synchronisation profile. Native process supervision is unchanged.

## Proton selection

Which GE-Proton build the container runs and how it was arrived at
(`server_runtime.proton.ProtonSelection`) — a version plus an **origin**:

- **pinned** — the operator set `PROTON_VERSION`. Never silently swapped.
- **auto** — detected from the latest GitHub release carrying usable assets.
- **fallback** — an auto-detected build failed its preflight, so
  `FALLBACK_PROTON_VERSION` replaced it.

Resolving a selection can cost a GitHub round trip, a download and a preflight
subprocess, and the [Supervisor](#supervisor) relaunches in a loop — so the
selection is carried from one launch to the next as a value and passed back into
`prepare_proton`, rather than parked in the process environment. A pin always
outranks a carried selection; anything else is reused as is, which is what stops
the loop re-probing a build already rejected.

`PROTON_VERSION` is still exported after resolution for child processes that
inherit the supervisor's environment. Nothing reads it back. This does not
change Docker's configured environment: `docker exec ... env` retains the
operator's original value. The startup logs report the resolved selection.

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

## Execution context

The architecture and optional translation runner used for SteamCMD, Proton
preflight and server launch (`server_runtime.translation.ExecutionContext`).
Runtime settings supply its translator mode and probe timeout.
On native AMD64 the runner is empty. On ARM64, FEX executes x86 programs using
an extracted RootFS prepared by the separate image build stage. The supervisor
carries this immutable context across restarts. Probe completion, the effective
Proton profile and the early-crash count are supervisor state, separate from
the execution context. The profile is normalized from runtime settings and
applied when building the server launch environment; a retry may switch it to
`safe` without changing runtime settings or the container environment. Only
completed translated server runs participate in the experimental early-crash
policy.
