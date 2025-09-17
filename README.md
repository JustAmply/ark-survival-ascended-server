# ARK: Survival Ascended Linux Server - Enterprise Edition

🦕 **Enterprise-grade Docker container for running ARK: Survival Ascended dedicated servers on Linux**

This project provides a streamlined way to host ARK: Survival Ascended servers using Docker, with powerful management tools, full cluster support, and comprehensive enterprise features for production environments.

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

### 🎯 **Core Features**
- **🐳 Docker-based**: Simple deployment with Docker Compose
- **🔧 Easy Management**: Built-in RCON commands and server control
- **🎮 Mod Support**: Simple mod management via console
- **🌐 Cluster Ready**: Multi-server setups with character/dino transfer
- **🔄 Auto-Updates**: Automatic game updates on container restart
- **📊 Monitoring**: Debug mode and comprehensive logging
- **🔌 Plugin Support**: ServerAPI plugin loader integration

### 🏢 **Enterprise Features** *(NEW in v3.0)*
- **⚙️ Configuration Management**: Environment-based config with validation and centralized updates
- **🛡️ Security & Access Control**: IP-based RCON access, rate limiting, input validation, and audit logging
- **📊 Monitoring & Observability**: Real-time health checks, metrics collection, and alerting capabilities
- **🌐 REST API**: Full management API with 10+ endpoints and web dashboard
- **🖥️ Web Dashboard**: Beautiful HTML5 interface with real-time monitoring and RCON console
- **🔄 Backup & Recovery**: Automated backups with compression, retention policies, and point-in-time recovery
- **🚀 Enterprise Deployment**: Production-ready Docker Compose and Kubernetes configurations
- **📈 Performance Monitoring**: System metrics, resource optimization, and performance alerts

## 🏢 Enterprise Features

### 🌐 **Web Management Dashboard**

Access the enterprise web dashboard for real-time server management:

```bash
# Enable the API server
docker exec asa-server-1 asa-ctrl enterprise config update --field api_enabled --value true

# Access dashboard at http://localhost:8080/dashboard
```

Features:
- **Real-time monitoring**: Server status, health checks, and system metrics
- **Interactive RCON console**: Execute commands directly from the web interface
- **Quick actions**: Health checks, metrics collection, mod management
- **Auto-refresh**: Live updates every 30 seconds

### 🔒 **Security & Access Control**

```bash
# Configure IP-based RCON access control
docker exec asa-server-1 asa-ctrl enterprise config update --field allowed_rcon_ips --value '["192.168.1.0/24"]'

# Enable rate limiting
docker exec asa-server-1 asa-ctrl enterprise config update --field enable_rcon_rate_limiting --value true

# Check security status
docker exec asa-server-1 asa-ctrl enterprise security check-access --ip 192.168.1.100
```

### 📊 **Monitoring & Health Checks**

```bash
# Run comprehensive health check
docker exec asa-server-1 asa-ctrl enterprise health

# Collect system metrics
docker exec asa-server-1 asa-ctrl enterprise metrics

# View audit logs
docker exec asa-server-1 asa-ctrl enterprise audit log --type security_event --details '{"test": "event"}'
```

### 🔄 **Backup & Recovery**

```bash
# Create manual backup
docker exec asa-server-1 asa-ctrl enterprise backup create --type full --description "Before update"

# List all backups
docker exec asa-server-1 asa-ctrl enterprise backup list

# Restore from backup
docker exec asa-server-1 asa-ctrl enterprise backup restore --name backup_20241201_120000 --type config

# Automated backups (configured via environment variables)
docker exec asa-server-1 asa-ctrl enterprise config update --field auto_backup_enabled --value true
```

### 🚀 **REST API Integration**

The enterprise edition includes a full REST API for integration with external systems:

```bash
# Get server status
curl http://localhost:8080/api/v1/status

# Execute RCON command
curl -X POST http://localhost:8080/api/v1/rcon \
  -H "Content-Type: application/json" \
  -d '{"command": "listplayers"}'

# Manage mods
curl -X POST http://localhost:8080/api/v1/mods \
  -H "Content-Type: application/json" \
  -d '{"action": "enable", "mod_id": "12345"}'
```

### 📈 **Enterprise Deployment**

For production environments, use the enterprise Docker Compose configuration:

```bash
# Download enterprise configuration
wget https://raw.githubusercontent.com/JustAmply/ark-survival-ascended-server/main/docker-compose.enterprise.yml

# Deploy with monitoring
docker compose -f docker-compose.enterprise.yml --profile monitoring up -d

# Or deploy to Kubernetes
kubectl apply -f https://raw.githubusercontent.com/JustAmply/ark-survival-ascended-server/main/k8s-enterprise.yaml
```

## 📋 System Requirements

### **Community Edition**

### **Community Edition**
- **RAM**: ~13 GB per server instance
- **Storage**: ~31 GB (server files only)
- **OS**: Linux with Docker support
- **Tested on**: Ubuntu 24.04, Debian 12, Docker Desktop on Windows

### **Enterprise Edition**
- **RAM**: ~16 GB per server instance (additional 3 GB for enterprise features)
- **Storage**: ~50 GB (server files + enterprise data, backups, logs)
- **CPU**: 4+ cores recommended for optimal performance
- **OS**: Ubuntu 24.04 LTS or Debian 12 (production environments)
- **Network**: High-bandwidth connection for API and monitoring features

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

Before starting your server, you can customize it by editing the `docker-compose.yml` file:

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
# Enable mods dynamically (container restart needed for activation)
docker exec asa-server-1 asa-ctrl mods enable 12345
docker exec asa-server-1 asa-ctrl mods enable 67891

# List enabled mods
docker exec asa-server-1 asa-ctrl mods list --enabled-only

# Restart to download and activate mods
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
Schedule automatic restarts with updates directly inside the container by setting `SERVER_RESTART_CRON` in your `docker-compose.yml`:
```yaml
environment:
  - SERVER_RESTART_CRON=0 4 * * *  # Restart daily at 04:00 (default)
```
The bundled cron helper triggers a graceful shutdown (saveworld + SIGTERM) and the entrypoint restarts the server automatically.

## 🏗️ Project History

This project is a **complete rewrite** of the original ARK server management tools. Here's the story:

### From Ruby to Python

Originally, I worked with Ruby-based server management tools for ARK, but I wasn't satisfied with their complexity and overhead. The Ruby implementation had several pain points:

- Unknown language for me, hard to read and maintain
- Complicated build system using KIWI-NG
- Multiple scattered modules
- Heavy dependencies and bloat (old project was 563MB in comparison to ~200MB for this Python version - savings of 2/3 of the image size!)

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
- **[🏢 Enterprise Deployment Guide](ENTERPRISE.md)** - Production deployment, security, monitoring, and enterprise features

## 🛠️ Development

Set up a local development environment with an editable installation so that CLI changes are reflected immediately:

```bash
git clone https://github.com/JustAmply/ark-survival-ascended-server.git
cd ark-survival-ascended-server
pip install -e .
```

This registers the `asa-ctrl` command on your PATH while allowing you to modify the source code in-place.

## 📞 Support

- **🐛 Found a bug?** [Open an issue](https://github.com/JustAmply/ark-survival-ascended-server/issues)
- **💡 Have a feature request?** [Start a discussion](https://github.com/JustAmply/ark-survival-ascended-server/discussions)
- **📚 Need help?** Check the [Setup Guide](SETUP.md) or [FAQ](FAQ.md)

## 🙏 Credits

- **mschnitzer** - [Original Ruby implementation of ARK Linux server image](https://github.com/mschnitzer/ark-survival-ascended-linux-container-image)
- **GloriousEggroll** - [GE-Proton for running Windows ARK binaries on Linux](https://github.com/GloriousEggroll/proton-ge-custom)
- **cdp1337** - [Linux ARK installation guidance](https://github.com/cdp1337/ARKSurvivalAscended-Linux)
