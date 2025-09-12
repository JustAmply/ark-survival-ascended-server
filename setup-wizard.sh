#!/bin/bash

# ARK: Survival Ascended Server Setup Wizard
# This script provides an interactive setup experience for new administrators

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Default values
DEFAULT_SERVER_NAME="ARK Server $(date +%s)"
DEFAULT_ADMIN_PASSWORD=""
DEFAULT_MAX_PLAYERS="50"
DEFAULT_GAME_PORT="7777"
DEFAULT_RCON_PORT="27020"
DEFAULT_MAP="TheIsland_WP"
DEFAULT_CLUSTER_ID="default"

# Available maps
declare -A MAPS=(
    ["1"]="TheIsland_WP|The Island"
    ["2"]="ScorchedEarth_WP|Scorched Earth"
    ["3"]="TheCenter_WP|The Center"
    ["4"]="Aberration_WP|Aberration"
    ["5"]="Extinction_WP|Extinction"
)

print_header() {
    echo -e "${BLUE}"
    echo "======================================================"
    echo "  ARK: Survival Ascended Server Setup Wizard"
    echo "======================================================"
    echo -e "${NC}"
    echo "This wizard will guide you through the initial setup"
    echo "of your ARK: Survival Ascended dedicated server."
    echo ""
}

print_step() {
    echo -e "${CYAN}=== $1 ===${NC}"
}

print_info() {
    echo -e "${BLUE}ℹ${NC} $1"
}

print_success() {
    echo -e "${GREEN}✓${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}⚠${NC} $1"
}

print_error() {
    echo -e "${RED}✗${NC} $1"
}

check_prerequisites() {
    print_step "Checking Prerequisites"
    
    # Check if running as root
    if [[ $EUID -eq 0 ]]; then
        print_error "This script should not be run as root for security reasons."
        print_info "Please run as a regular user who has docker permissions."
        exit 1
    fi
    
    # Check if docker is installed
    if ! command -v docker &> /dev/null; then
        print_error "Docker is not installed. Please install Docker first."
        print_info "Visit: https://docs.docker.com/engine/install/"
        exit 1
    fi
    
    # Check if docker compose is available
    if ! command -v "docker compose" &> /dev/null && ! command -v docker-compose &> /dev/null; then
        print_error "Docker Compose is not installed. Please install Docker Compose first."
        exit 1
    fi
    
    # Check if user can run docker commands
    if ! docker ps &> /dev/null; then
        print_error "Cannot run docker commands. Please ensure your user is in the docker group."
        print_info "Run: sudo usermod -aG docker \$USER && newgrp docker"
        exit 1
    fi
    
    print_success "All prerequisites met!"
    echo ""
}

get_user_input() {
    print_step "Server Configuration"
    
    # Server name
    echo -e "${YELLOW}Server Name:${NC}"
    echo "This is the name that will appear in the server browser."
    read -p "Enter server name (default: $DEFAULT_SERVER_NAME): " SERVER_NAME
    SERVER_NAME=${SERVER_NAME:-$DEFAULT_SERVER_NAME}
    
    # Admin password
    echo ""
    echo -e "${YELLOW}Admin Password:${NC}"
    echo "This password is used for server administration and RCON access."
    echo "Must be at least 8 characters long for security."
    while true; do
        read -s -p "Enter admin password: " ADMIN_PASSWORD
        echo ""
        if [[ ${#ADMIN_PASSWORD} -lt 8 ]]; then
            print_error "Password must be at least 8 characters long."
            continue
        fi
        read -s -p "Confirm admin password: " ADMIN_PASSWORD_CONFIRM
        echo ""
        if [[ "$ADMIN_PASSWORD" != "$ADMIN_PASSWORD_CONFIRM" ]]; then
            print_error "Passwords do not match."
            continue
        fi
        break
    done
    
    # Max players
    echo ""
    echo -e "${YELLOW}Maximum Players:${NC}"
    echo "Recommended: 10-70 players depending on your server hardware."
    while true; do
        read -p "Enter max players (default: $DEFAULT_MAX_PLAYERS): " MAX_PLAYERS
        MAX_PLAYERS=${MAX_PLAYERS:-$DEFAULT_MAX_PLAYERS}
        if [[ "$MAX_PLAYERS" =~ ^[0-9]+$ ]] && [ "$MAX_PLAYERS" -gt 0 ] && [ "$MAX_PLAYERS" -le 200 ]; then
            break
        else
            print_error "Please enter a valid number between 1 and 200."
        fi
    done
    
    # Map selection
    echo ""
    echo -e "${YELLOW}Map Selection:${NC}"
    echo "Choose which map your server should run:"
    for key in $(echo "${!MAPS[@]}" | tr ' ' '\n' | sort -n); do
        IFS='|' read -r map_id map_name <<< "${MAPS[$key]}"
        echo "  $key) $map_name"
    done
    
    while true; do
        read -p "Select map (1-5, default: 1): " MAP_CHOICE
        MAP_CHOICE=${MAP_CHOICE:-1}
        if [[ "$MAP_CHOICE" =~ ^[1-5]$ ]]; then
            IFS='|' read -r SELECTED_MAP map_display_name <<< "${MAPS[$MAP_CHOICE]}"
            break
        else
            print_error "Please enter a number between 1 and 5."
        fi
    done
    
    # Ports
    echo ""
    echo -e "${YELLOW}Port Configuration:${NC}"
    echo "Game port (UDP): Players connect to this port"
    while true; do
        read -p "Enter game port (default: $DEFAULT_GAME_PORT): " GAME_PORT
        GAME_PORT=${GAME_PORT:-$DEFAULT_GAME_PORT}
        if [[ "$GAME_PORT" =~ ^[0-9]+$ ]] && [ "$GAME_PORT" -ge 1024 ] && [ "$GAME_PORT" -le 65535 ]; then
            # Check if port is already in use
            if ss -tuln | grep -q ":$GAME_PORT "; then
                print_error "Port $GAME_PORT is already in use. Please choose another port."
                continue
            fi
            break
        else
            print_error "Please enter a valid port number between 1024 and 65535."
        fi
    done
    
    echo "RCON port (TCP): Used for remote server administration"
    while true; do
        read -p "Enter RCON port (default: $DEFAULT_RCON_PORT): " RCON_PORT
        RCON_PORT=${RCON_PORT:-$DEFAULT_RCON_PORT}
        if [[ "$RCON_PORT" =~ ^[0-9]+$ ]] && [ "$RCON_PORT" -ge 1024 ] && [ "$RCON_PORT" -le 65535 ] && [ "$RCON_PORT" != "$GAME_PORT" ]; then
            # Check if port is already in use
            if ss -tuln | grep -q ":$RCON_PORT "; then
                print_error "Port $RCON_PORT is already in use. Please choose another port."
                continue
            fi
            break
        else
            print_error "Please enter a valid port number between 1024 and 65535, different from the game port."
        fi
    done
    
    # Cluster configuration
    echo ""
    echo -e "${YELLOW}Cluster Configuration:${NC}"
    echo "Cluster ID allows players to transfer between servers with the same ID."
    read -p "Enter cluster ID (default: $DEFAULT_CLUSTER_ID): " CLUSTER_ID
    CLUSTER_ID=${CLUSTER_ID:-$DEFAULT_CLUSTER_ID}
    
    echo ""
}

check_ports() {
    print_step "Port Availability Check"
    
    if ss -tuln | grep -q ":$GAME_PORT "; then
        print_error "Game port $GAME_PORT is already in use!"
        return 1
    fi
    
    if ss -tuln | grep -q ":$RCON_PORT "; then
        print_error "RCON port $RCON_PORT is already in use!"
        return 1
    fi
    
    print_success "All ports are available!"
    echo ""
}

generate_password() {
    # Generate a secure random password if none provided
    if [[ -z "$ADMIN_PASSWORD" ]]; then
        ADMIN_PASSWORD=$(openssl rand -base64 12)
        print_warning "Generated admin password: $ADMIN_PASSWORD"
        print_warning "Please save this password securely!"
    fi
}

create_docker_compose() {
    print_step "Creating Docker Compose Configuration"
    
    local compose_file="docker-compose.yml"
    
    cat > "$compose_file" << EOF
version: "3.3"
services:
  asa-server-1:
    container_name: asa-server-1
    hostname: asa-server-1
    entrypoint: "/usr/bin/start_server"
    user: gameserver
    image: "mschnitzer/asa-linux-server:latest"
    tty: true
    environment:
      - ASA_START_PARAMS=${SELECTED_MAP}?listen?Port=${GAME_PORT}?RCONPort=${RCON_PORT}?RCONEnabled=True?SessionName="${SERVER_NAME}" -WinLiveMaxPlayers=${MAX_PLAYERS} -clusterid=${CLUSTER_ID} -ClusterDirOverride="/home/gameserver/cluster-shared"
      - ENABLE_DEBUG=0
    ports:
      # Game port for player connections through the server browser
      - 0.0.0.0:${GAME_PORT}:${GAME_PORT}/udp
      # RCON port for remote server administration
      - 0.0.0.0:${RCON_PORT}:${RCON_PORT}/tcp
    depends_on:
      - set-permissions-1
    volumes:
      - steam-1:/home/gameserver/Steam:rw
      - steamcmd-1:/home/gameserver/steamcmd:rw
      - server-files-1:/home/gameserver/server-files:rw
      - cluster-shared:/home/gameserver/cluster-shared:rw
      - /etc/localtime:/etc/localtime:ro
    networks:
      asa-network:
  set-permissions-1:
    entrypoint: "/bin/bash -c 'chown -R 25000:25000 /steam ; chown -R 25000:25000 /steamcmd ; chown -R 25000:25000 /server-files ; chown -R 25000:25000 /cluster-shared'"
    user: root
    image: "opensuse/leap"
    volumes:
      - steam-1:/steam:rw
      - steamcmd-1:/steamcmd:rw
      - server-files-1:/server-files:rw
      - cluster-shared:/cluster-shared:rw
volumes:
  cluster-shared:
  steam-1:
  steamcmd-1:
  server-files-1:
networks:
  asa-network:
    attachable: true
    driver: bridge
    driver_opts:
      com.docker.network.bridge.name: 'asanet'
EOF
    
    print_success "Docker Compose configuration created: $compose_file"
    echo ""
}

create_game_user_settings() {
    print_step "Creating Game Configuration"
    
    # Create the directory structure if it doesn't exist
    local config_dir="/var/lib/docker/volumes/asa-server_server-files-1/_data/ShooterGame/Saved/Config/WindowsServer"
    
    # Note: We can't create this file directly since the volume doesn't exist yet
    # Instead, we'll create a template that can be applied after the first run
    
    cat > "GameUserSettings.ini.template" << EOF
[ServerSettings]
SessionName=${SERVER_NAME}
ServerAdminPassword=${ADMIN_PASSWORD}
RCONEnabled=True
RCONPort=${RCON_PORT}
MaxPlayers=${MAX_PLAYERS}
ServerHardcore=False
GlobalVoiceChat=False
ProximityChat=False
NoTributeDownloads=False
AllowThirdPersonPlayer=True
AlwaysNotifyPlayerLeft=True
DontAlwaysNotifyPlayerJoined=False
ServerCrosshair=True
ServerForceNoHUD=False
ShowMapPlayerLocation=True
EnablePVPGamma=True
DisableStructureDecayPvE=False
AllowFlyerCarryPvE=True
MaxStructuresInRange=10500
ItemStackSizeMultiplier=1.0
StructureResistanceMultiplier=1.0
XPMultiplier=1.0
TamingSpeedMultiplier=1.0
HarvestAmountMultiplier=1.0
PlayerCharacterWaterDrainMultiplier=1.0
PlayerCharacterFoodDrainMultiplier=1.0
DinoCharacterFoodDrainMultiplier=1.0
PlayerCharacterStaminaDrainMultiplier=1.0
DinoCharacterStaminaDrainMultiplier=1.0
PlayerCharacterHealthRecoveryMultiplier=1.0
DinoCharacterHealthRecoveryMultiplier=1.0
DinoCountMultiplier=1.0
EOF

    print_success "Game configuration template created: GameUserSettings.ini.template"
    print_info "This will be applied after the first server start."
    echo ""
}

create_management_scripts() {
    print_step "Creating Management Scripts"
    
    # Server status script
    cat > "server-status.sh" << 'EOF'
#!/bin/bash
echo "=== ARK Server Status ==="
echo ""

if docker ps | grep -q "asa-server-1"; then
    echo "✓ Server container is running"
    
    # Get container stats
    echo ""
    echo "Container Statistics:"
    docker stats --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.NetIO}}\t{{.BlockIO}}" asa-server-1
    
    # Check if server is responding
    echo ""
    echo "Server Logs (last 10 lines):"
    docker logs --tail 10 asa-server-1
else
    echo "✗ Server container is not running"
fi
EOF
    
    # Server restart script
    cat > "server-restart.sh" << 'EOF'
#!/bin/bash
echo "Restarting ARK Server..."
echo "This will save the world and restart the server."
read -p "Are you sure you want to restart? (y/N): " confirm

if [[ $confirm == [yY] || $confirm == [yY][eE][sS] ]]; then
    echo "Saving world..."
    docker exec asa-server-1 asa-ctrl rcon --exec 'saveworld' 2>/dev/null || echo "RCON save failed (server might be starting)"
    
    echo "Restarting container..."
    docker restart asa-server-1
    
    echo "Server restart initiated. Check logs with: docker logs -f asa-server-1"
else
    echo "Restart cancelled."
fi
EOF
    
    # Server backup script
    cat > "server-backup.sh" << 'EOF'
#!/bin/bash
BACKUP_DIR="./backups"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_NAME="ark_backup_${TIMESTAMP}.tar.gz"

echo "Creating backup: $BACKUP_NAME"

# Create backup directory
mkdir -p "$BACKUP_DIR"

# Save the world first
echo "Saving world..."
docker exec asa-server-1 asa-ctrl rcon --exec 'saveworld' 2>/dev/null || echo "RCON save failed (server might be starting)"

# Wait a moment for save to complete
sleep 5

# Create backup of server files
echo "Creating backup archive..."
docker run --rm -v asa-server_server-files-1:/data -v $(pwd)/backups:/backup alpine tar czf /backup/"$BACKUP_NAME" -C /data .

echo "Backup created: $BACKUP_DIR/$BACKUP_NAME"

# Clean old backups (keep last 5)
echo "Cleaning old backups (keeping last 5)..."
cd "$BACKUP_DIR"
ls -t ark_backup_*.tar.gz | tail -n +6 | xargs -r rm --
echo "Backup complete!"
EOF
    
    chmod +x server-status.sh server-restart.sh server-backup.sh
    
    print_success "Management scripts created:"
    print_info "  ./server-status.sh  - Check server status and stats"
    print_info "  ./server-restart.sh - Restart the server safely"
    print_info "  ./server-backup.sh  - Create a backup of server data"
    echo ""
}

create_quick_reference() {
    print_step "Creating Quick Reference Guide"
    
    cat > "QUICK_REFERENCE.md" << EOF
# ARK Server Quick Reference

## Server Information
- **Server Name**: $SERVER_NAME
- **Map**: $map_display_name
- **Max Players**: $MAX_PLAYERS
- **Game Port**: $GAME_PORT (UDP)
- **RCON Port**: $RCON_PORT (TCP)
- **Cluster ID**: $CLUSTER_ID

## Common Commands

### Start/Stop Server
\`\`\`bash
# Start server
docker compose up -d

# Stop server
docker compose stop

# Restart server
./server-restart.sh
\`\`\`

### Server Management
\`\`\`bash
# Check server status
./server-status.sh

# View server logs
docker logs -f asa-server-1

# Execute RCON commands
docker exec asa-server-1 asa-ctrl rcon --exec 'COMMAND'

# Create backup
./server-backup.sh
\`\`\`

### Common RCON Commands
\`\`\`bash
# Save world
docker exec asa-server-1 asa-ctrl rcon --exec 'saveworld'

# List players
docker exec asa-server-1 asa-ctrl rcon --exec 'listplayers'

# Broadcast message
docker exec asa-server-1 asa-ctrl rcon --exec 'broadcast Hello everyone!'

# Kick player
docker exec asa-server-1 asa-ctrl rcon --exec 'kickplayer PLAYERNAME'
\`\`\`

## File Locations
- **Server Files**: \`/var/lib/docker/volumes/asa-server_server-files-1/_data/\`
- **Configuration**: \`/var/lib/docker/volumes/asa-server_server-files-1/_data/ShooterGame/Saved/Config/WindowsServer/\`
- **Save Games**: \`/var/lib/docker/volumes/asa-server_server-files-1/_data/ShooterGame/Saved/SavedArks/\`

## Configuration Files
- **GameUserSettings.ini**: Main server configuration
- **Game.ini**: Advanced game settings (create if needed)

## Port Forwarding
If running behind a router/firewall, forward these ports:
- **$GAME_PORT/UDP** - Game port for player connections
- **$RCON_PORT/TCP** - RCON port for administration (optional)

## Troubleshooting
1. **Server not visible in browser**: Wait 5-10 minutes, check "Unofficial" servers
2. **Connection timeout**: Check port forwarding and firewall
3. **High CPU usage**: Check mod compatibility, reduce max players
4. **Server crashes**: Check logs with \`docker logs asa-server-1\`

For more help, visit: https://github.com/mschnitzer/ark-survival-ascended-linux-container-image
EOF
    
    print_success "Quick reference guide created: QUICK_REFERENCE.md"
    echo ""
}

show_summary() {
    print_step "Setup Summary"
    
    echo -e "${GREEN}Server Configuration:${NC}"
    echo "  Server Name: $SERVER_NAME"
    echo "  Map: $map_display_name"
    echo "  Max Players: $MAX_PLAYERS"
    echo "  Game Port: $GAME_PORT (UDP)"
    echo "  RCON Port: $RCON_PORT (TCP)"
    echo "  Cluster ID: $CLUSTER_ID"
    echo ""
    
    echo -e "${YELLOW}Files Created:${NC}"
    echo "  ✓ docker-compose.yml"
    echo "  ✓ GameUserSettings.ini.template"
    echo "  ✓ server-status.sh"
    echo "  ✓ server-restart.sh"
    echo "  ✓ server-backup.sh"
    echo "  ✓ QUICK_REFERENCE.md"
    echo ""
    
    echo -e "${BLUE}Next Steps:${NC}"
    echo "1. Start your server:"
    echo "   ${CYAN}docker compose up -d${NC}"
    echo ""
    echo "2. Monitor the initial setup (this may take 10-20 minutes):"
    echo "   ${CYAN}docker logs -f asa-server-1${NC}"
    echo ""
    echo "3. After first startup, apply the game configuration:"
    echo "   ${CYAN}sudo cp GameUserSettings.ini.template /var/lib/docker/volumes/asa-server_server-files-1/_data/ShooterGame/Saved/Config/WindowsServer/GameUserSettings.ini${NC}"
    echo ""
    echo "4. Restart the server to apply configuration:"
    echo "   ${CYAN}./server-restart.sh${NC}"
    echo ""
    echo "5. Check server status:"
    echo "   ${CYAN}./server-status.sh${NC}"
    echo ""
    
    print_warning "IMPORTANT: Save your admin password securely!"
    print_warning "Admin Password: $ADMIN_PASSWORD"
    echo ""
    
    print_info "For detailed help, see QUICK_REFERENCE.md"
    print_success "Setup complete! Happy gaming! 🎮"
}

# Main execution
main() {
    print_header
    check_prerequisites
    get_user_input
    check_ports || exit 1
    create_docker_compose
    create_game_user_settings
    create_management_scripts
    create_quick_reference
    show_summary
}

# Run main function
main "$@"