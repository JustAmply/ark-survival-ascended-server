# Troubleshooting

For installation and ordinary administration, use the [setup guide](SETUP.md).
Start with `docker compose logs --tail=200 asa-server-1` and check whether the
failure occurs during download, Proton preparation or game startup.

## Server is not visible

1. Check that game startup has completed. `Starting ASA dedicated server.`
   marks the launch attempt, not readiness for players.
2. Select **Unofficial**, enable **Show Player Servers** and clear map/player
   filters in the game browser.
3. Search for your configured `ASA_SESSION_NAME`. If you did not set one, use
   the [setup guide's name lookup](SETUP.md#installation).
4. Check the [game port mapping and firewall rules](SETUP.md#networking).

If `GameUserSettings.ini` does not exist yet, inspect startup logs for download
or launch failures before waiting longer. A missing file alone does not prove
that the server is still starting normally.

## Joining times out or the browser shows the wrong IP

Check the game port's UDP mapping, host/cloud firewall and router forwarding.
If you changed `ASA_PORT`, update all three. To test direct connection, use
`open YOUR_IP:7777` in the game console, substituting your actual address and
configured port.

On hosts with several interfaces, VPNs or NAT layers, verify that inbound
traffic reaches the Docker host and replies use the expected interface.
Docker port publishing does not configure the router or cloud security group.
See [networking](SETUP.md#networking).

## Startup fails or the server keeps crashing

Read the error immediately before the exit, then inspect host resources:

```bash
docker compose logs --tail=200 asa-server-1
docker stats --no-stream asa-server-1
```

On a Linux host, `df -h` and `free -h` help check disk and memory. An OOM-killed
container can be identified with:

```bash
docker inspect asa-server-1 --format '{{.State.OOMKilled}}'
```

If game files appear damaged, run once with `ASA_VALIDATE: "always"`, apply
with `docker compose up -d -t 300`, then return to `first` after repair.
For high CPU usage, check the logged Wine synchronization backend and
[resource settings](SETUP.md#resource-tuning-and-debug-mode) before changing the
host OS. To hold startup for inspection, use [debug mode](SETUP.md#resource-tuning-and-debug-mode).

## Proton reports a missing library

A message such as `libvulkan.so.1: cannot open shared object file` indicates
that the selected Proton build cannot load a library from the image. Update
and recreate the container:

```bash
docker compose pull
docker compose up -d -t 300
```

Automatic Proton selection can fall back after a failed preflight. An
explicit `PROTON_VERSION` pin stays fixed and fails if it cannot run. Check
that pin and the logged version; the [Proton reference](SETUP.md#startup-and-proton)
explains the settings and cached check.

## ARM64 translation fails

For `Exec format error`, check that the service uses the ARM64 experimental
image and `ASA_TRANSLATOR_MODE` is `auto` or `fex`. Inspect the translation
probe's error in the startup logs; an x86 program needs a working FEX runner.

If the logs specifically report a **probe timeout**, increase
`ASA_TRANSLATOR_PROBE_TIMEOUT` for the host. If translated Proton/server runs
crash early, try `ASA_PROTON_PROFILE: "safe"`; this disables esync/fsync but
does not repair a missing translation path. Apply changes with
`docker compose up -d -t 300`.

ARM64 translation checks do not establish full game compatibility. See
[ARM64 setup](SETUP.md#arm64-experimental) for its support boundary.

## RCON commands fail

Check `ASA_RCON_ENABLED`, `ASA_RCON_PORT` and `ASA_SERVER_ADMIN_PASSWORD` in the
running service's configuration and confirm that the game has started.
The [launch-setting precedence](SETUP.md#legacy-launch-strings-and-precedence)
also applies to RCON discovery: changing the INI cannot override a value set in
the launch configuration. Apply Compose or `.env` changes with
`docker compose up -d -t 300`.

If RCON works inside the container but not remotely, check the TCP port mapping
and firewall. See [RCON commands](SETUP.md#rcon) for an in-container example.

## Configuration or mod changes have no effect

`docker compose restart` preserves the container's configured environment.
After editing Compose or `.env`, run `docker compose up -d -t 300`.
Changes made through `asa-ctrl mods` need a server restart. A mod still present
in `ASA_MODS` remains enabled after removing its database entry. See
[mod management](SETUP.md#mods-and-custom-maps).

## Reporting an unresolved problem

Search [GitHub Issues](https://github.com/JustAmply/ark-survival-ascended-server/issues)
for the error first. In a new report, include host OS/architecture, Docker
version, image tag or digest, relevant logs and what changed before the failure.
Include Compose configuration with passwords and other secrets removed.
Use [GitHub Discussions](https://github.com/JustAmply/ark-survival-ascended-server/discussions)
for general setup questions. Preserve persistent volumes while investigating;
[storage and backups](SETUP.md#storage-and-backups) explains what they contain.
