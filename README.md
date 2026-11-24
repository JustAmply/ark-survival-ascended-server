<p align="center">
  <img src="assets/logo.png" alt="ARK: Survival Ascended Linux Server logo" width="240">
</p>

# ARK: Survival Ascended Linux Server

Run a dedicated **ARK: Survival Ascended** server on Linux with Docker Compose.
Your friends can keep playing when you log off. The container installs the game,
checks for updates and saves your world in a Docker volume.

Choose a [map](SETUP.md#choose-a-map), add [CurseForge mods](SETUP.md#mods-and-custom-maps)
or [link worlds](SETUP.md#multi-server-clusters) so players can travel between them.

## Quick start

**You'll need** a Linux x86-64 host with Docker Compose. Budget roughly 13 GB
of RAM and 31 GB of disk for one server, plus room for updates, mods and backups.
For ARM64, use the [experimental image](SETUP.md#arm64-experimental).

### 1. Download the configuration

```bash
mkdir asa-server && cd asa-server
wget https://raw.githubusercontent.com/JustAmply/ark-survival-ascended-server/main/docker-compose.yml
wget https://raw.githubusercontent.com/JustAmply/ark-survival-ascended-server/main/.env.example
cp .env.example .env
```

### 2. Name your server

Set a private `ASA_SERVER_ADMIN_PASSWORD` in `.env`. In `docker-compose.yml`,
add a session name under `asa-server-1` → `environment`:

```yaml
      ASA_SESSION_NAME: "Our Weekend ARK"
```

Keep `ASA_MAP: TheIsland_WP` for **The Island** or choose another map.
For a private game, add `ASA_SERVER_PASSWORD` in the same section and share it with players.

### 3. Start and join

```bash
docker compose up -d
docker compose logs -f asa-server-1
```

The first start downloads the game. Press Ctrl+C to leave the logs and use
`docker compose ps` to check readiness. Once the server is healthy, open
**Unofficial** in ARK, enable **Show Player Servers** and search for your session name.

> [!TIP]
> For friends joining over the internet, allow **UDP 7777** through your firewall.
> Behind a home router, forward that port to the Docker host. [Connection help](FAQ.md#server-is-not-visible)

## After your first session

| Task | Command or guide |
| --- | --- |
| Stop and save | `docker compose stop -t 300` |
| Start again | `docker compose start` |
| Apply changed settings | `docker compose up -d -t 300` |
| Update the image | `docker compose pull`, then `docker compose up -d -t 300` |
| Change the daily 04:00 restart (Europe/Berlin) | [Restart schedule and player warnings](SETUP.md#restarts-and-shutdown) |
| Back up your world | [Backup and recovery](docs/backups.md) |

[Server administration](SETUP.md) | [Troubleshooting](FAQ.md) | [Development](docs/development.md)

## Support and credits

[Report a bug](https://github.com/JustAmply/ark-survival-ascended-server/issues) or
[ask a question](https://github.com/JustAmply/ark-survival-ascended-server/discussions).

Based on [mschnitzer's original image](https://github.com/mschnitzer/ark-survival-ascended-linux-container-image),
with [GE-Proton](https://github.com/GloriousEggroll/proton-ge-custom) and
[Linux installation guidance from cdp1337](https://github.com/cdp1337/ARKSurvivalAscended-Linux).
