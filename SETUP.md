# 🚀 ARK: Survival Ascended Server Setup Guide

Your complete guide to getting an amazing ARK server up and running! This covers everything from basic setup to advanced cluster configurations.

## 📋 What You'll Need

### 💻 System Requirements
- **RAM**: ~13 GB per server (more = better performance!)
- **Storage**: ~31 GB for server files + space for saves
- **OS**: Any Linux with Docker support
- **Tested on**: Ubuntu 24.04, Debian 12

**⚠️ Avoid Ubuntu 22.04** - Known issues cause high CPU usage and server startup failures.

### 🐳 Prerequisites
- Docker and Docker Compose installed on your system
- Basic command line knowledge
- Root access for initial setup

## 🎯 Quick Setup

### 📥 Download & Start

1. **Create your server directory:**
   ```bash
   mkdir asa-server && cd asa-server
   wget https://raw.githubusercontent.com/JustAmply/ark-survival-ascended-server/main/docker-compose.yml
   ```

2. **Launch your server:**
   ```bash
   docker compose up -d
   ```

   **Tip:** The container already passes `-nosteam` in `ASA_START_PARAMS` (also required if you roll your own launch line) to avoid the startup `Error 3` where Steam refuses to fire up inside the container.

3. **Watch it come to life:**
   ```bash
   docker logs -f asa-server-1
   ```
   
   *Press `Ctrl+C` to exit logs (server keeps running)*

### 🎉 First Launch

Your server will automatically:
- ✅ Download Steam & Proton compatibility layer
- ✅ Download ARK server files (~31GB)
- ✅ Generate a random server name
- ✅ Start accepting connections in ~5-10 minutes

Startup is fully automatic through the container's Python runtime entrypoint; no manual startup command is required.

### 🔍 Find Your Server

Once you see `"Starting the ARK: Survival Ascended dedicated server..."` in the logs, check your server name:

```bash
docker exec asa-server-1 cat server-files/ShooterGame/Saved/Config/WindowsServer/GameUserSettings.ini | grep SessionName
```

This shows something like `SessionName=ARK #334850`. Search for that number in the **Unofficial** server browser!

![Server browser with "Show Player Servers"](assets/show-player-servers.jpg)

## ⚙️ Server Configuration

### 🎮 Customize Your Server

Edit your `docker-compose.yml` file to customize:

```yaml
environment:
  - ASA_START_PARAMS=TheIsland_WP?listen?Port=7777?RCONPort=27020?RCONEnabled=True -WinLiveMaxPlayers=50
```

**Popular Changes:**
- **🗺️ Change map**: Replace `TheIsland_WP` with `ScorchedEarth_WP`, `TheCenter_WP`, `Aberration_WP`, `Extinction_WP`
- **🔢 Change ports**: Modify `Port=7777` and `RCONPort=27020`
- **👥 Player limit**: Adjust `-WinLiveMaxPlayers=50`
- **🕒 Timezone**: Set `TZ=Europe/Berlin` (or your region) so server logs follow your local time (default: `UTC`)

### 📂 File Locations

Your server files are stored in Docker volumes:
- **Server files**: `/var/lib/docker/volumes/asa-server_server-files-1/_data/`
- **Config files**: `/var/lib/docker/volumes/asa-server_server-files-1/_data/ShooterGame/Saved/Config/WindowsServer/`

## 🌐 Port Configuration

### 🏠 Home Setup (Router)
Forward these ports in your router:
- **7777/UDP** - Game port (required)
- **27020/TCP** - RCON port (optional)

### ☁️ Cloud Setup
No port forwarding needed! Docker handles this automatically.

## 🎛️ Server Management

### 🔄 Basic Operations
```bash
# Start/Stop/Restart
docker compose start asa-server-1
docker compose stop asa-server-1
docker compose restart asa-server-1

# View logs
docker logs -f asa-server-1

# Update server (auto-downloads game updates)
docker restart asa-server-1
```

### 🎮 Mod Management

**🚀 Dynamic Method (Recommended):**
```bash
# Enable mods
docker exec asa-server-1 asa-ctrl mods enable 12345
docker exec asa-server-1 asa-ctrl mods enable 67891

# List enabled mods
docker exec asa-server-1 asa-ctrl mods list --enabled-only

# Remove mods that are no longer needed (purges the database entry)
docker exec asa-server-1 asa-ctrl mods remove 12345

# Restart to download mods
docker restart asa-server-1
```

**⚡ Static Method:**
Add `-mods=12345,67891` to your `ASA_START_PARAMS` in `docker-compose.yml`.

### 🗺️ Custom Maps
1. Find the mod ID on CurseForge
2. Enable the map mod: `docker exec asa-server-1 asa-ctrl mods enable MOD_ID`
3. Change map name in `ASA_START_PARAMS`: `MapName_WP?listen...`
4. Restart server

### 🎯 RCON Commands
```bash
# Save world
docker exec asa-server-1 asa-ctrl rcon --exec 'saveworld'

# Broadcast message
docker exec asa-server-1 asa-ctrl rcon --exec 'serverchat Hello players!'

# Kick player
docker exec asa-server-1 asa-ctrl rcon --exec 'kickplayer PlayerName'
```

## 🔗 Multi-Server Clusters

Want multiple servers where players can transfer characters and dinos?

1. **Uncomment the second server** in your `docker-compose.yml`
2. **Start both servers**: `docker compose up -d`
3. **Different cluster ID**: Change `-clusterid=default` to something unique like `-clusterid=MySecretCluster`

Each additional server gets its own ports (7778, 7779, etc.) and storage volumes.

## ⏰ Shutdown Behavior

Stopping the container (e.g., `docker stop`) triggers a `saveworld` via RCON before the server process receives `SIGTERM`. You can fine-tune the shutdown grace period with optional variables:

- `ASA_SHUTDOWN_SAVEWORLD_DELAY=15` – wait time (seconds) after saving before signalling shutdown
- `ASA_SHUTDOWN_TIMEOUT=180` – graceful shutdown timeout (seconds) before the process is force-killed

## 🔁 Scheduled Restarts

Enable automated maintenance windows with the built-in scheduler:

```yaml
environment:
  - SERVER_RESTART_CRON=0 4 * * *
```

The cron expression follows the standard five-field format (`minute hour day month weekday`). When active, the container:

1. Sends chat warnings 30, 5 and 1 minute before the restart
2. Executes `saveworld` and waits for the configured grace period
3. Restarts the server process automatically (the container keeps running)

Customize the warning cadence with `SERVER_RESTART_WARNINGS=60,15,5,1` (comma-separated minutes) and adjust the relaunch delay with `SERVER_RESTART_DELAY=15` (seconds to wait before booting again). Omit `SERVER_RESTART_CRON` to disable the scheduler entirely.

## 🍷 GE-Proton Compatibility Layer

The container downloads the GE-Proton build that runs the Windows server binary. By default it picks the latest release that publishes assets for your architecture.

| Variable | Purpose |
| --- | --- |
| `PROTON_VERSION` | Pin a specific build, for example `10-34`. Omit it to auto-detect. |
| `PROTON_SKIP_CHECKSUM` | Set to `1` to bypass archive hash verification (last resort). |
| `PROTON_SKIP_PREFLIGHT` | Set to `1` to skip the startup check described below. |

Before each launch the runtime starts the downloaded Proton launcher once to confirm the container can actually load the host libraries it needs. If an auto-detected build fails that check, the missing library is logged by name and the runtime falls back to a known good GE-Proton version instead of restarting in a loop:

```
ERROR | GE-Proton11-5 cannot start: shared library 'libvulkan.so.1' is missing from this container.
WARNING | Falling back to known good GE-Proton10-34; set PROTON_VERSION to override.
```

Seeing this means the image should be updated (`docker compose pull`). A `PROTON_VERSION` you pinned yourself is never swapped silently — startup fails with the same message so the pin stays meaningful.

## 🔧 Debug Mode

For troubleshooting, enable debug mode:

1. Change `ENABLE_DEBUG=0` to `ENABLE_DEBUG=1` in `docker-compose.yml`
2. Restart: `docker compose up -d`
3. Access shell: `docker exec -ti asa-server-1 bash`

## 📖 Need More Help?

- **🐛 Found a bug?** [Open an issue](https://github.com/JustAmply/ark-survival-ascended-server/issues)
- **❓ Common problems?** Check the [FAQ](FAQ.md)
- **💬 Questions?** [Start a discussion](https://github.com/JustAmply/ark-survival-ascended-server/discussions)
