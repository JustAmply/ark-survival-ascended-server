# Check server readiness and configuration

## Is the world ready?

```bash
docker compose ps
docker compose exec asa-server-1 asa-ctrl status --json
```

`status` shows the runtime phase and RCON readiness. **Ready** means ARK answered `ListPlayers`. If players still cannot join, check [server visibility and networking](../FAQ.md#server-is-not-visible).

<details>
<summary>Healthcheck timing and exit codes</summary>

Docker probes every 30 seconds and marks the container unhealthy after three consecutive failures outside the initial 30-minute startup allowance. Extend `healthcheck.start_period` for slow downloads. An unhealthy status alone leaves the container running.

For debug hold or disabled RCON, set `healthcheck: { disable: true }` on the service. For automation, `status` returns 0 when ready and 10 otherwise. `status --healthcheck` returns 0 or 1.

</details>

## Are my settings valid?

Run checks in the container as the game user. Replace `doctor` with either configuration command below.

```bash
docker compose exec --user 25000:25000 asa-server-1 asa-ctrl doctor
```

| Command | What it checks or shows |
| --- | --- |
| `config check` | Known settings, including ports, player limits, update modes, restart schedules and password warnings. Unknown launch options pass through. |
| `config show` | Launch settings before dynamic mods are merged. JSON output redacts passwords and omits arbitrary extra values. |
| `doctor` | Configuration plus read-only access checks on initialized volumes and existing configuration files. |

For scripts, `config check --json` and `doctor --json` report `ok`, `errors` and `warnings`. Errors return exit code 9. Warnings alone return 0.
