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
- **🎮 Mod Support**: Dynamic mod management without container restarts
- **🌐 Cluster Ready**: Multi-server setups with character/dino transfer
- **🔄 Auto-Updates**: Automatic game updates on container restart
- **📊 Monitoring**: Debug mode and comprehensive logging
- **🔌 Plugin Support**: ServerAPI plugin loader integration

## 🏗️ Project History

This project is a **complete rewrite** of the original ARK server management tools. Here's the story:

### From Ruby to Python

Originally, I worked with Ruby-based server management tools for ARK, but I wasn't satisfied with their complexity and maintenance overhead. The Ruby implementation had several pain points:

- Complex dependency management with gems
- Complicated build system using KIWI-NG
- Multiple scattered modules
- OpenSUSE-based images with compatibility issues

### The Rewrite Decision

I decided to completely rewrite everything from scratch in **Python** to create a better, more maintainable solution. This wasn't just a port - it was a ground-up redesign with modern best practices.

### What's Better in Version 2.0

- **🐍 Python-powered**: Cleaner, more maintainable codebase
- **📦 Zero dependencies**: Uses only Python standard library
- **🏗️ Simplified builds**: Standard Docker builds instead of complex KIWI-NG
- **🧹 Unified codebase**: Single Python package (`asa_ctrl`) replaces multiple Ruby modules
- **🐧 Ubuntu-based**: Better compatibility and package management
- **⚡ Same functionality**: All features preserved while improving maintainability

## 📋 System Requirements

- **RAM**: ~13 GB per server instance
- **Storage**: ~31 GB (server files only)
- **OS**: Linux with Docker support
- **Tested on**: Ubuntu 24.04, Debian 12, openSUSE Leap 15.6

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
```bash
# Enable mods dynamically (no container restart needed for config)
docker exec asa-server-1 asa-ctrl mods enable 12345
docker exec asa-server-1 asa-ctrl mods enable 67891

# List enabled mods
docker exec asa-server-1 asa-ctrl mods list --enabled-only

# Restart to download mods
docker restart asa-server-1
```

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

## 🔗 Need More Details?

This README provides a quick overview to get you started. For comprehensive documentation including:

- **Detailed installation steps** for different Linux distributions
- **Advanced configuration** options
- **Troubleshooting guides** for common issues
- **Port forwarding** setup
- **Plugin installation** instructions
- **Cluster configuration** details

👉 **See the [detailed documentation](README.original.md)** for complete setup instructions.

## 📞 Support

- **🐛 Found a bug?** [Open an issue](https://github.com/JustAmply/ark-survival-ascended-server/issues)
- **💡 Have a feature request?** [Start a discussion](https://github.com/JustAmply/ark-survival-ascended-server/discussions)
- **📚 Need help?** Check the [original detailed README](README.original.md)

## 🙏 Credits

- **Glorious Eggroll** - GE-Proton for running Windows ARK binaries on Linux
- **cdp1337** - Linux ARK installation guidance  
- **tesfabpel** - Ruby RCON implementation reference

---

*Made with ❤️ by JustAmply - Because the original Ruby tools weren't good enough* 😉