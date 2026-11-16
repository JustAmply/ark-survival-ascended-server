# Configuration diagnostics

Run these inside the configured container, using the gameserver user when
checking filesystem access:

```bash
docker exec --user 25000:25000 asa-server-1 asa-ctrl config check
docker exec --user 25000:25000 asa-server-1 asa-ctrl config check --json
docker exec --user 25000:25000 asa-server-1 asa-ctrl config show
docker exec --user 25000:25000 asa-server-1 asa-ctrl doctor --json
```

`config check` validates known ports, player limits, booleans, runtime timings,
update/validation modes and restart schedules. It uses the same launch-line
overlays and cron parser as the runtime, accepts unknown launch options and warns
when RCON is disabled or the default admin password would be used. Strict
password mode requires an explicitly configured password, including one in the
INI file; an explicit default password is accepted but still warns. UDP game/query port collisions are
errors; a UDP game port and TCP RCON port may share a number.

`config show` prints JSON containing known launch settings and redacted password
presence. Arbitrary extra values are omitted because they may contain other
secrets. This is the configured launch input before dynamic mod merging, not an
assertion about an already running server.

`doctor` adds directory and existing configuration-file access checks. It does
not create probe files, initialize a mod database, contact RCON, run SteamCMD or
start the server. Permission checks apply to the invoking user and cannot prove
that a later write will succeed (for example, a full disk or mount change can
still prevent writes). Run it after the container has initialized its volumes.

Checks return exit code `0` when there are no errors and `9` for configuration
errors. Warnings alone do not fail the command. JSON check output contains
`ok`, `errors` and `warnings`; invalid values and secret contents are not echoed.
