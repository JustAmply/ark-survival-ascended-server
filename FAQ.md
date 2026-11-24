# Troubleshooting

From the directory containing your Compose file, check the service and its
latest logs. The examples use the supplied service name, `asa-server-1`.

```bash
docker compose ps -a
docker compose logs --tail=200 asa-server-1
```

## Server is not visible

1. If the container has exited or the logs show repeated launch attempts,
   start with [startup failures](#startup-fails-or-the-server-keeps-crashing).
   The log entry `Starting ASA dedicated server.` marks a launch attempt.
   With the default configuration, wait for the container to report `healthy`
   before looking for it in the game.
2. In the server browser select **Unofficial**, enable **Show Player Servers**
   and clear map and player filters. Search for your `ASA_SESSION_NAME`.
   If you let ARK generate a name, read it once the world has started:

   ```bash
   docker compose exec asa-server-1 grep '^SessionName=' /home/gameserver/server-files/ShooterGame/Saved/Config/WindowsServer/GameUserSettings.ini
   ```

   ![Show Player Servers in the Unofficial server browser](assets/show-player-servers.jpg)

3. If players still cannot find the session, try a direct connection as described below.

## Joining times out or the browser shows the wrong IP

Try `open YOUR_IP:7777` in the ARK console, using the server's address and game
port. For a home server, test the LAN address from the same network, then have
a player outside that network test the public address. If only the external
test fails, check where inbound UDP traffic stops along the path from the router
or cloud firewall to the Docker host. On a host with a VPN or several
interfaces, check which interface carries the replies. See [networking](SETUP.md#networking)
for the port mappings.

## Startup fails or the server keeps crashing

Read the first error in the failed launch attempt. The last lines may describe
the supervisor's retry. Match the symptom to the next check:

| What you see | What to check |
| --- | --- |
| SteamCMD reports write failures, or downloads stop | Run `df -h` on the filesystem holding Docker volumes. For permission errors, use the [filesystem diagnostics](docs/diagnostics.md). |
| The process exits abruptly while loading the world | Check available memory with `free -h` and the running container's usage with `docker stats --no-stream asa-server-1`. A result of `true` from `docker inspect asa-server-1 --format '{{.State.OOMKilled}}'` confirms that Docker recorded an out-of-memory kill. |
| SteamCMD finishes, but game files appear damaged | For one maintenance launch, set `ASA_VALIDATE: "always"` and ensure `ASA_UPDATE` permits an update. Apply the settings, check the validation log, then restore your usual settings. See [startup and Proton](SETUP.md#startup-and-proton). |
| Startup stops on a `mods.json` read or parse error | Follow [mod database recovery](docs/mod-safety.md) to preserve the world's enabled mods. |
| The logs warn about Wine's slow synchronization path | Check the container's descriptor limits in [resource tuning](SETUP.md#resource-tuning-and-debug-mode). |

## Proton reports a missing library

For an error such as `libvulkan.so.1: cannot open shared object file`, note the
selected Proton version in the logs. Pull the current container image with
`docker compose pull` and recreate the service with `docker compose up -d -t 300`.
If the error persists with an explicit `PROTON_VERSION` pin, check whether you
still need that build. The [Proton reference](SETUP.md#startup-and-proton)
explains automatic selection and fallback.

## ARM64 translation fails

For `Exec format error`, check the service's image tag and translation mode
against the [ARM64 settings](SETUP.md#arm64-experimental). Look for the first
FEX probe error. Increase `ASA_TRANSLATOR_PROBE_TIMEOUT` only if the log reports
a timeout. If the probe passes and ARK exits during launch, check the logged
Proton profile and the ARM64 retry behavior in the same guide.

## RCON commands fail

While the container is running, check the game's response from inside it:

```bash
docker compose exec asa-server-1 asa-ctrl status --json
```

If the internal check succeeds but your desktop RCON client cannot connect,
the default Compose setup publishes only the game port. Follow the
[SSH tunnel setup](SETUP.md#networking) for remote access.

- `rcon-disabled` means the running phase was reached with RCON disabled.
  Check `ASA_RCON_ENABLED` if you intended to use remote administration.
- For `not-ready`, check whether the world is still loading. If this persists,
  inspect the configured port and password source with the
  [configuration diagnostics](docs/diagnostics.md). A launch-line setting
  takes precedence over the corresponding INI setting.
- For `ready`, the in-container connection succeeded. If only an external
  client fails, check its credentials, TCP port mapping and firewall access.

## Configuration or mod changes have no effect

If you edited Compose or `.env`, recreate the container using the command in
[server configuration](SETUP.md#server-configuration). If a setting still has
an unexpected value, check the [order of overrides](SETUP.md#legacy-launch-strings-and-precedence).

If you changed a mod through `asa-ctrl mods`, restart the game to load the new
selection. For a mod that keeps returning, check both `ASA_MODS` and the list of
enabled database entries. See [mod management](SETUP.md#mods-and-custom-maps).

## Reporting an unresolved problem

Include the host OS and CPU architecture, Docker version, image tag or digest,
what changed, and the log excerpt around the first failure. Remove passwords
and other secrets from any logs or configuration you share. For unexpected
settings, include the redacted output of `asa-ctrl config show`.

[Search or report an issue](https://github.com/JustAmply/ark-survival-ascended-server/issues)
or [ask a setup question](https://github.com/JustAmply/ark-survival-ascended-server/discussions).
