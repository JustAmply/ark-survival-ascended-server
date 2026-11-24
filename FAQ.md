# Troubleshooting

Start in the directory with your Compose file:

```bash
docker compose ps -a
docker compose logs --tail=200 asa-server-1
```

## Server is not visible

1. Run `docker compose ps -a`. With the default settings, wait for `healthy`. For repeated restarts, check [startup failures](#startup-fails-or-the-server-keeps-crashing).
2. Select **Unofficial → Show Player Servers**, clear map and player filters, then search for your session name.
3. Try a [direct connection](#joining-times-out-or-the-browser-shows-the-wrong-ip).

<details>
<summary>Find the generated session name and browser filter</summary>

If you left `ASA_SESSION_NAME` unset, read the name after the world loads:

```bash
docker compose exec asa-server-1 grep '^SessionName=' /home/gameserver/server-files/ShooterGame/Saved/Config/WindowsServer/GameUserSettings.ini
```

![Show Player Servers in the Unofficial server browser](assets/show-player-servers.jpg)

</details>

## Joining times out or the browser shows the wrong IP

In the ARK console, try `open YOUR_IP:7777` with your game port. For a home
server, try the LAN address locally and the public address from outside. If
only the public address fails, check UDP forwarding and firewall rules. With a
VPN or multiple interfaces, check the return route. [Network setup](SETUP.md#networking)

## Startup fails or the server keeps crashing

Find the **first error** in the failed launch attempt.

| Symptom | Next check |
| --- | --- |
| SteamCMD cannot write or finish downloading | Check free disk space on the Docker volume filesystem with `df -h`, then [check permissions](docs/diagnostics.md). |
| The world exits while loading | Run `docker inspect asa-server-1 --format '{{.State.OOMKilled}}'`. A result of `true` confirms an out-of-memory kill. Check RAM with `free -h`. |
| Suspected game file damage | For one launch, set `ASA_VALIDATE: "always"` with updates enabled. Restore your settings after [validation](SETUP.md#startup-and-proton). |
| Invalid or unreadable `mods.json` | Follow [mod database recovery](docs/mod-safety.md). |
| Wine warns about slow synchronization | Check [file descriptor limits](SETUP.md#resource-tuning-and-debug-mode). |

## Proton reports a missing library

For errors such as `libvulkan.so.1: cannot open shared object file`, update the
image with `docker compose pull`, then run `docker compose up -d -t 300`.
If the error persists, check your [Proton version pin](SETUP.md#startup-and-proton).

## ARM64 translation fails

For `Exec format error`, check the [ARM64 image tag and translation mode](SETUP.md#arm64-experimental).
Increase `ASA_TRANSLATOR_PROBE_TIMEOUT` only for probe timeouts. If the probe
passes, check the Proton profile logged for the failing launch.

## RCON commands fail

Run `docker compose exec asa-server-1 asa-ctrl status --json`:

| Result | Next step |
| --- | --- |
| `rcon-disabled` | Check `ASA_RCON_ENABLED`. |
| `not-ready` | Let the world load, then [check the configured port and password source](docs/diagnostics.md). |
| `ready` | Internal RCON works. For a remote desktop client, check credentials and the [SSH tunnel](SETUP.md#networking). |

**Command delivery unconfirmed:** check the game state before sending the
command again. It may already have run.

## Configuration or mod changes have no effect

- **Edited Compose or `.env`?** [Recreate the container](SETUP.md#server-configuration). If a value is still unexpected, check the [override order](SETUP.md#legacy-launch-strings-and-precedence).
- **Edited mods with `asa-ctrl`?** Restart the game. If a mod returns, check both `ASA_MODS` and the [enabled database entries](SETUP.md#mods-and-custom-maps).

## Reporting an unresolved problem

[Report an issue](https://github.com/JustAmply/ark-survival-ascended-server/issues)
with the host OS and CPU, Docker version, image tag or digest, recent changes
and logs around the first error. Remove secrets before sharing. For unexpected
settings, include `asa-ctrl config show` (passwords redacted). For setup questions,
use [Discussions](https://github.com/JustAmply/ark-survival-ascended-server/discussions).
