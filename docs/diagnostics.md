# Check server readiness and configuration

## Is the world ready?

Run `docker compose ps` for the container health summary. For the current
startup or shutdown phase, consecutive failure count (when available) and RCON
readiness, use:

```bash
docker compose exec asa-server-1 asa-ctrl status --json
```

`ready` means the running server answered `ListPlayers` over RCON. If players
still cannot connect, check the [game port and server browser](../FAQ.md#server-is-not-visible).
For automation, `status` exits with 0 when ready and 10 otherwise.
`status --healthcheck` uses Docker's 0/1 exit codes.

The image checks every 30 seconds. Docker allows 30 minutes for initial
downloads and marks the container unhealthy after three consecutive failed
checks outside the startup allowance. Increase `healthcheck.start_period` in
Compose for slower hosts. The allowance applies to container startup. A health
change alone does not restart the server. If you deliberately disable RCON or
use debug hold, set `healthcheck: { disable: true }` on that service to turn
off the RCON-based probe.

## Are my settings valid?

Run these read-only checks against a running container. Use the game user's
UID and GID so access checks reflect the server's permissions.

```bash
docker compose exec --user 25000:25000 asa-server-1 asa-ctrl config check
docker compose exec --user 25000:25000 asa-server-1 asa-ctrl config show
docker compose exec --user 25000:25000 asa-server-1 asa-ctrl doctor
```

| Command | What it tells you |
| --- | --- |
| `config check` | Validates known ports, player limits, switches, timings, update modes and restart schedules. Warnings include disabled RCON and a missing or default admin password. Unknown launch options pass through. |
| `config show` | Shows known launch inputs as JSON before the runtime merges dynamic mods. Passwords are redacted and arbitrary extra values are omitted. |
| `doctor` | Adds checks that the game user can access the initialized volumes and existing configuration files. It leaves files untouched. |

For machine-readable check results, add `--json` to `config check` or `doctor`.
Both report `ok`, `errors` and `warnings`. Exit code 9 indicates a configuration
error. Warnings alone return 0.
