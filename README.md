# ARK: Survival Ascended Linux Server

🦕 **Easy-to-use Docker container for running ARK: Survival Ascended dedicated servers on Linux**

This project provides a streamlined way to host ARK: Survival Ascended servers using Docker, with powerful management tools and full cluster support.

## 🚀 Quick Start

Get your ARK server running in minutes:

```bash
# 1. Create server directory and download config
mkdir asa-server && cd asa-server
wget https://raw.githubusercontent.com/JustAmply/ark-survival-ascended-server/main/docker-compose.yml

# 2. Start your server
docker compose up -d

# 3. Follow the logs to see progress
docker logs -f asa-server-1
```

Your server will be discoverable in the "Unofficial" server browser once setup is complete (~5-10 minutes).

## ✨ Key Features

- **🐳 Docker-based**: Simple deployment with Docker Compose
- **🔧 Easy Management**: Built-in RCON commands and server control
- **🎮 Mod Support**: Simple mod management via console
- **🌐 Cluster Ready**: Multi-server setups with character/dino transfer
- **🔄 Auto-Updates**: Automatic game updates on container restart
- **📊 Monitoring**: Debug mode and comprehensive logging
- **🔌 Plugin Support**: ServerAPI plugin loader integration

## 📋 System Requirements

- **RAM**: ~13 GB per server instance
- **Storage**: ~31 GB (server files only)
- **OS**: Linux with Docker support
- **Tested on**: Ubuntu 24.04, Debian 12, Docker Desktop on Windows

## 🎯 Main Use Cases

### Single Server Setup
Perfect for small communities or testing:
- Easy one-command deployment
- Built-in RCON management
- Automatic updates

### Multi-Server Clusters  
Great for larger communities:
- Character and dino transfer between servers
- Shared cluster storage
- Independent server configuration

### Mod Servers
Ideal for modded gameplay:
- Dynamic mod management
- CurseForge mod support
- Custom map support

## 🔧 Basic Configuration

After starting your server, you can customize it by editing the `docker-compose.yml` file:

```yaml
environment:
  # Change map, ports, and player limit
  - ASA_START_PARAMS=TheIsland_WP?listen?Port=7777?RCONPort=27020?RCONEnabled=True -WinLiveMaxPlayers=50
```

### Popular Configuration Changes

- **Change map**: Replace `TheIsland_WP` with `ScorchedEarth_WP`, `TheCenter_WP`, etc.
- **Change ports**: Modify `Port=7777` and `RCONPort=27020`
- **Player limit**: Adjust `-WinLiveMaxPlayers=50`

## 🎮 Server Management

### Add Mods

Simple modify the `ASA_START_PARAMS` in the `docker-compose.yml` to include mods `-mods=12345,67891`:
```yaml
- ASA_START_PARAMS=TheIsland_WP?listen?Port=7777?RCONPort=27020?RCONEnabled=True -WinLiveMaxPlayers=50 -mods=12345,67891
```

Changing this list requires editing the compose file and recreating/restarting the container.

Or use the dynamic method:
```bash
# Enable mods dynamically (no container restart needed for config)
docker exec asa-server-1 asa-ctrl mods enable 12345
docker exec asa-server-1 asa-ctrl mods enable 67891

# List enabled mods
docker exec asa-server-1 asa-ctrl mods list --enabled-only

# Restart to download mods
docker restart asa-server-1
```

Mixing both methods is safe: statically defined mods are merged with dynamically enabled ones (duplicates are ignored by the game server).

### RCON Commands
```bash
# Save the world
docker exec asa-server-1 asa-ctrl rcon --exec 'saveworld'

# Broadcast message
docker exec asa-server-1 asa-ctrl rcon --exec 'serverchat Hello players!'

# Kick player
docker exec asa-server-1 asa-ctrl rcon --exec 'kickplayer PlayerName'
```

### Daily Restarts
Set up automatic restarts with updates:
```bash
# Add to crontab (crontab -e)
0 4 * * * docker restart asa-server-1
```

## 🏗️ Project History

This project is a **complete rewrite** of the original ARK server management tools. Here's the story:

### From Ruby to Python

Originally, I worked with Ruby-based server management tools for ARK, but I wasn't satisfied with their complexity and overhead. The Ruby implementation had several pain points:

- Unknown language for me, hard to read and maintain
- Complicated build system using KIWI-NG
- Multiple scattered modules
- Heavy dependencies and bloat (old project was ~500MB in comparison to ~170MB for this Python version - savings of 2/3 of the image size!)

### The Rewrite Decision

I decided to completely rewrite everything from scratch in **Python** to create a better, more maintainable solution.

### What's Better in Version 2.0

- **🐍 Python-powered**: Cleaner, more maintainable codebase
- **📦 Zero dependencies**: Uses only Python standard library
- **🏗️ Simplified builds**: Standard Docker builds instead of complex KIWI-NG
- **🧩 Modular design**: Single script with clear functions
- **⚡ Same functionality**: All features preserved while improving maintainability

## 📖 Documentation

- **[📋 Setup Guide](SETUP.md)** - Detailed installation, configuration, and administration instructions
- **[❓ FAQ & Troubleshooting](FAQ.md)** - Common issues, solutions, and troubleshooting steps

## 📞 Support

- **🐛 Found a bug?** [Open an issue](https://github.com/JustAmply/ark-survival-ascended-server/issues)
- **💡 Have a feature request?** [Start a discussion](https://github.com/JustAmply/ark-survival-ascended-server/discussions)
- **📚 Need help?** Check the [Setup Guide](SETUP.md) or [FAQ](FAQ.md)

## 🙏 Credits

- **mschnitzer** - [Original Ruby implementation of ARK Linux server image](https://github.com/mschnitzer/ark-survival-ascended-linux-container-image)
- **GloriousEggroll** - [GE-Proton for running Windows ARK binaries on Linux](https://github.com/GloriousEggroll/proton-ge-custom)
- **cdp1337** - [Linux ARK installation guidance](https://github.com/cdp1337/ARKSurvivalAscended-Linux)
