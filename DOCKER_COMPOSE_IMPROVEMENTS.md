# Docker Compose Verbesserungen - Technische Spezifikation

## Übersicht

Diese Spezifikation definiert konkrete Verbesserungen für die bestehende Docker Compose Konfiguration des ARK: Survival Ascended Linux Container Projekts. Ziel ist es, die Konfiguration modularer, wartbarer und produktionstauglicher zu gestalten.

## Aktuelle Probleme der bestehenden docker-compose.yml

### Identifizierte Schwachstellen:
1. **Monolithische Struktur** - Alles in einer Datei
2. **Fehlende Umgebungstrennung** - Keine dev/staging/prod Unterscheidung
3. **Hardcodierte Werte** - Ports und Konfiguration nicht flexibel
4. **Keine Backup-Strategien** - Fehlende Datensicherung
5. **Begrenzte Skalierbarkeit** - Schwierig mehrere Server zu verwalten
6. **Fehlende Monitoring** - Keine Observability
7. **Sicherheitslücken** - Keine Secrets Management
8. **Fehlende Health Checks** - Keine Container-Überwachung

## Neue modulare Compose-Struktur

### Datei-Organisation
```
docker-compose/
├── base/
│   ├── docker-compose.base.yml      # Basis-Services
│   ├── docker-compose.asa.yml       # ASA Server Definition
│   ├── docker-compose.webui.yml     # Web Interface
│   ├── docker-compose.monitoring.yml # Monitoring Stack
│   └── docker-compose.backup.yml    # Backup Services
├── environments/
│   ├── .env.dev                     # Development Umgebung
│   ├── .env.staging                 # Staging Umgebung
│   ├── .env.prod                    # Production Umgebung
│   └── .env.example                 # Template
├── overrides/
│   ├── docker-compose.dev.yml       # Development Overrides
│   ├── docker-compose.staging.yml   # Staging Overrides
│   └── docker-compose.prod.yml      # Production Overrides
├── configs/
│   ├── nginx/
│   │   ├── nginx.conf
│   │   ├── ssl.conf
│   │   └── sites/
│   ├── prometheus/
│   │   └── prometheus.yml
│   ├── grafana/
│   │   ├── provisioning/
│   │   └── dashboards/
│   └── logstash/
│       └── pipeline/
└── scripts/
    ├── deploy.sh                    # Deployment Script
    ├── backup.sh                    # Backup Script
    ├── restore.sh                   # Restore Script
    ├── scale.sh                     # Scaling Script
    └── health-check.sh              # Health Check Script
```

## Basis-Konfiguration (docker-compose.base.yml)

```yaml
version: "3.8"

# Gemeinsame Service-Definitionen
x-common-variables: &common-variables
  TZ: ${TIMEZONE:-Europe/Berlin}
  
x-restart-policy: &restart-policy
  restart: unless-stopped

x-logging: &default-logging
  logging:
    driver: "json-file"
    options:
      max-size: "10m"
      max-file: "3"

x-healthcheck: &default-healthcheck
  interval: 30s
  timeout: 10s
  retries: 3
  start_period: 40s

services:
  # Basis-Services die von anderen Services benötigt werden
  postgres:
    <<: [*restart-policy, *default-logging]
    image: postgres:${POSTGRES_VERSION:-14}-alpine
    environment:
      <<: *common-variables
      POSTGRES_DB: ${POSTGRES_DB:-asa_management}
      POSTGRES_USER: ${POSTGRES_USER:-asa_user}
      POSTGRES_PASSWORD_FILE: /run/secrets/postgres_password
    secrets:
      - postgres_password
    volumes:
      - postgres-data:/var/lib/postgresql/data
      - ./scripts/postgres-init:/docker-entrypoint-initdb.d:ro
    networks:
      - asa-backend
    healthcheck:
      <<: *default-healthcheck
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER:-asa_user}"]

  redis:
    <<: [*restart-policy, *default-logging]
    image: redis:${REDIS_VERSION:-7}-alpine
    environment:
      <<: *common-variables
    command: redis-server --appendonly yes --requirepass ${REDIS_PASSWORD}
    volumes:
      - redis-data:/data
    networks:
      - asa-backend
    healthcheck:
      <<: *default-healthcheck
      test: ["CMD", "redis-cli", "ping"]

secrets:
  postgres_password:
    file: ./secrets/postgres_password.txt
  redis_password:
    file: ./secrets/redis_password.txt
  jwt_secret:
    file: ./secrets/jwt_secret.txt

volumes:
  postgres-data:
    driver: local
  redis-data:
    driver: local

networks:
  asa-backend:
    driver: bridge
    internal: false
  asa-frontend:
    driver: bridge
    internal: false
```

## ASA Server Service (docker-compose.asa.yml)

```yaml
version: "3.8"

x-asa-common: &asa-common
  image: "mschnitzer/asa-linux-server:${ASA_IMAGE_TAG:-latest}"
  user: gameserver
  tty: true
  restart: unless-stopped
  logging:
    driver: "json-file"
    options:
      max-size: "50m"
      max-file: "5"
  environment:
    TZ: ${TIMEZONE:-Europe/Berlin}
    ENABLE_DEBUG: ${ASA_DEBUG:-0}
  volumes:
    - /etc/localtime:/etc/localtime:ro
  networks:
    - asa-backend
  healthcheck:
    test: ["CMD-SHELL", "pgrep -f ArkAscendedServer.exe || exit 1"]
    interval: 30s
    timeout: 10s
    retries: 3
    start_period: 300s

services:
  # Dynamische Server-Generierung basierend auf Umgebungsvariablen
  asa-server-1:
    <<: *asa-common
    container_name: asa-server-1
    hostname: asa-server-1
    entrypoint: "/usr/bin/start_server"
    environment:
      <<: *asa-common.environment
      ASA_START_PARAMS: ${ASA_SERVER_1_START_PARAMS:-TheIsland_WP?listen?Port=7777?RCONPort=27020?RCONEnabled=True -WinLiveMaxPlayers=50}
    ports:
      - "${ASA_SERVER_1_GAME_PORT:-7777}:${ASA_SERVER_1_GAME_PORT:-7777}/udp"
      - "${ASA_SERVER_1_RCON_PORT:-27020}:${ASA_SERVER_1_RCON_PORT:-27020}/tcp"
    depends_on:
      set-permissions-1:
        condition: service_completed_successfully
    volumes:
      - steam-1:/home/gameserver/Steam:rw
      - steamcmd-1:/home/gameserver/steamcmd:rw
      - server-files-1:/home/gameserver/server-files:rw
      - cluster-shared:/home/gameserver/cluster-shared:rw
      - /etc/localtime:/etc/localtime:ro
    labels:
      - "asa.server.id=1"
      - "asa.server.name=${ASA_SERVER_1_NAME:-Main Server}"
      - "asa.server.map=${ASA_SERVER_1_MAP:-TheIsland_WP}"

  set-permissions-1:
    image: "opensuse/leap:${OPENSUSE_VERSION:-15.6}"
    user: root
    entrypoint: "/bin/bash"
    command: >
      -c "
      chown -R 25000:25000 /steam /steamcmd /server-files /cluster-shared &&
      echo 'Permissions set successfully'
      "
    volumes:
      - steam-1:/steam:rw
      - steamcmd-1:/steamcmd:rw
      - server-files-1:/server-files:rw
      - cluster-shared:/cluster-shared:rw

  # Conditionaler zweiter Server
  asa-server-2:
    <<: *asa-common
    container_name: asa-server-2
    hostname: asa-server-2
    entrypoint: "/usr/bin/start_server"
    environment:
      <<: *asa-common.environment
      ASA_START_PARAMS: ${ASA_SERVER_2_START_PARAMS:-ScorchedEarth_WP?listen?Port=7778?RCONPort=27021?RCONEnabled=True -WinLiveMaxPlayers=50}
    ports:
      - "${ASA_SERVER_2_GAME_PORT:-7778}:${ASA_SERVER_2_GAME_PORT:-7778}/udp"
      - "${ASA_SERVER_2_RCON_PORT:-27021}:${ASA_SERVER_2_RCON_PORT:-27021}/tcp"
    depends_on:
      set-permissions-2:
        condition: service_completed_successfully
    volumes:
      - steam-2:/home/gameserver/Steam:rw
      - steamcmd-2:/home/gameserver/steamcmd:rw
      - server-files-2:/home/gameserver/server-files:rw
      - cluster-shared:/home/gameserver/cluster-shared:rw
      - /etc/localtime:/etc/localtime:ro
    profiles:
      - multi-server
    labels:
      - "asa.server.id=2"
      - "asa.server.name=${ASA_SERVER_2_NAME:-Secondary Server}"
      - "asa.server.map=${ASA_SERVER_2_MAP:-ScorchedEarth_WP}"

  set-permissions-2:
    image: "opensuse/leap:${OPENSUSE_VERSION:-15.6}"
    user: root
    entrypoint: "/bin/bash"
    command: >
      -c "
      chown -R 25000:25000 /steam /steamcmd /server-files /cluster-shared &&
      echo 'Permissions set successfully'
      "
    volumes:
      - steam-2:/steam:rw
      - steamcmd-2:/steamcmd:rw
      - server-files-2:/server-files:rw
      - cluster-shared:/cluster-shared:rw
    profiles:
      - multi-server

volumes:
  cluster-shared:
    driver: local
    driver_opts:
      type: none
      o: bind
      device: ${ASA_DATA_PATH:-/opt/asa-data}/cluster-shared
  steam-1:
    driver: local
    driver_opts:
      type: none
      o: bind
      device: ${ASA_DATA_PATH:-/opt/asa-data}/server-1/steam
  steamcmd-1:
    driver: local
    driver_opts:
      type: none
      o: bind
      device: ${ASA_DATA_PATH:-/opt/asa-data}/server-1/steamcmd
  server-files-1:
    driver: local
    driver_opts:
      type: none
      o: bind
      device: ${ASA_DATA_PATH:-/opt/asa-data}/server-1/server-files
  steam-2:
    driver: local
    driver_opts:
      type: none
      o: bind
      device: ${ASA_DATA_PATH:-/opt/asa-data}/server-2/steam
  steamcmd-2:
    driver: local
    driver_opts:
      type: none
      o: bind
      device: ${ASA_DATA_PATH:-/opt/asa-data}/server-2/steamcmd
  server-files-2:
    driver: local
    driver_opts:
      type: none
      o: bind
      device: ${ASA_DATA_PATH:-/opt/asa-data}/server-2/server-files
```

## Web UI Service (docker-compose.webui.yml)

```yaml
version: "3.8"

x-webui-common: &webui-common
  restart: unless-stopped
  logging:
    driver: "json-file"
    options:
      max-size: "10m"
      max-file: "3"
  environment:
    TZ: ${TIMEZONE:-Europe/Berlin}

services:
  asa-webui-backend:
    <<: *webui-common
    build:
      context: ./webui/backend
      dockerfile: Dockerfile
      args:
        NODE_VERSION: ${NODE_VERSION:-18}
    container_name: asa-webui-backend
    environment:
      <<: *webui-common.environment
      NODE_ENV: ${NODE_ENV:-production}
      DATABASE_URL: postgresql://${POSTGRES_USER:-asa_user}:${POSTGRES_PASSWORD}@postgres:5432/${POSTGRES_DB:-asa_management}
      REDIS_URL: redis://:${REDIS_PASSWORD}@redis:6379
      JWT_SECRET_FILE: /run/secrets/jwt_secret
      API_PORT: ${WEBUI_API_PORT:-3001}
      CORS_ORIGIN: ${WEBUI_CORS_ORIGIN:-http://localhost:3000}
    secrets:
      - jwt_secret
    volumes:
      - server-files-1:/app/server-data/server-1:ro
      - server-files-2:/app/server-data/server-2:ro
      - cluster-shared:/app/cluster-shared:rw
      - ./configs/webui:/app/config:ro
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    networks:
      - asa-backend
      - asa-frontend
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:3001/health"]
      interval: 30s
      timeout: 10s
      retries: 3
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.webui-api.rule=Host(`${WEBUI_DOMAIN:-localhost}`) && PathPrefix(`/api`)"
      - "traefik.http.services.webui-api.loadbalancer.server.port=3001"

  asa-webui-frontend:
    <<: *webui-common
    build:
      context: ./webui/frontend
      dockerfile: Dockerfile
      args:
        NODE_VERSION: ${NODE_VERSION:-18}
        REACT_APP_API_URL: ${WEBUI_API_URL:-http://localhost:3001}
    container_name: asa-webui-frontend
    environment:
      <<: *webui-common.environment
    depends_on:
      - asa-webui-backend
    networks:
      - asa-frontend
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:80/"]
      interval: 30s
      timeout: 10s
      retries: 3
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.webui.rule=Host(`${WEBUI_DOMAIN:-localhost}`)"
      - "traefik.http.services.webui.loadbalancer.server.port=80"

  nginx:
    <<: *webui-common
    image: nginx:${NGINX_VERSION:-alpine}
    container_name: asa-nginx
    ports:
      - "${WEBUI_HTTP_PORT:-80}:80"
      - "${WEBUI_HTTPS_PORT:-443}:443"
    volumes:
      - ./configs/nginx/nginx.conf:/etc/nginx/nginx.conf:ro
      - ./configs/nginx/sites:/etc/nginx/sites-enabled:ro
      - ./configs/nginx/ssl:/etc/ssl/certs:ro
      - nginx-cache:/var/cache/nginx
    depends_on:
      - asa-webui-frontend
      - asa-webui-backend
    networks:
      - asa-frontend
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:80/health"]
      interval: 30s
      timeout: 10s
      retries: 3

volumes:
  nginx-cache:
    driver: local
```

## Monitoring Stack (docker-compose.monitoring.yml)

```yaml
version: "3.8"

x-monitoring-common: &monitoring-common
  restart: unless-stopped
  logging:
    driver: "json-file"
    options:
      max-size: "10m"
      max-file: "3"

services:
  prometheus:
    <<: *monitoring-common
    image: prom/prometheus:${PROMETHEUS_VERSION:-latest}
    container_name: asa-prometheus
    command:
      - '--config.file=/etc/prometheus/prometheus.yml'
      - '--storage.tsdb.path=/prometheus'
      - '--web.console.libraries=/etc/prometheus/console_libraries'
      - '--web.console.templates=/etc/prometheus/consoles'
      - '--storage.tsdb.retention.time=200h'
      - '--web.enable-lifecycle'
    ports:
      - "${PROMETHEUS_PORT:-9090}:9090"
    volumes:
      - ./configs/prometheus:/etc/prometheus:ro
      - prometheus-data:/prometheus
    networks:
      - asa-backend
    healthcheck:
      test: ["CMD", "wget", "--no-verbose", "--tries=1", "--spider", "http://localhost:9090/"]
      interval: 30s
      timeout: 10s
      retries: 3

  grafana:
    <<: *monitoring-common
    image: grafana/grafana:${GRAFANA_VERSION:-latest}
    container_name: asa-grafana
    environment:
      - GF_SECURITY_ADMIN_USER=${GRAFANA_USER:-admin}
      - GF_SECURITY_ADMIN_PASSWORD=${GRAFANA_PASSWORD:-admin}
      - GF_USERS_ALLOW_SIGN_UP=false
    ports:
      - "${GRAFANA_PORT:-3001}:3000"
    volumes:
      - ./configs/grafana/provisioning:/etc/grafana/provisioning:ro
      - ./configs/grafana/dashboards:/var/lib/grafana/dashboards:ro
      - grafana-data:/var/lib/grafana
    depends_on:
      - prometheus
    networks:
      - asa-backend
    healthcheck:
      test: ["CMD-SHELL", "curl -f localhost:3000/api/health || exit 1"]
      interval: 30s
      timeout: 10s
      retries: 3

  node-exporter:
    <<: *monitoring-common
    image: prom/node-exporter:${NODE_EXPORTER_VERSION:-latest}
    container_name: asa-node-exporter
    command:
      - '--path.procfs=/host/proc'
      - '--path.rootfs=/rootfs'
      - '--path.sysfs=/host/sys'
      - '--collector.filesystem.mount-points-exclude=^/(sys|proc|dev|host|etc)($$|/)'
    ports:
      - "${NODE_EXPORTER_PORT:-9100}:9100"
    volumes:
      - /proc:/host/proc:ro
      - /sys:/host/sys:ro
      - /:/rootfs:ro
    networks:
      - asa-backend

  cadvisor:
    <<: *monitoring-common
    image: gcr.io/cadvisor/cadvisor:${CADVISOR_VERSION:-latest}
    container_name: asa-cadvisor
    ports:
      - "${CADVISOR_PORT:-8080}:8080"
    volumes:
      - /:/rootfs:ro
      - /var/run:/var/run:rw
      - /sys:/sys:ro
      - /var/lib/docker:/var/lib/docker:ro
      - /dev/disk/:/dev/disk:ro
    devices:
      - /dev/kmsg:/dev/kmsg
    networks:
      - asa-backend

  alertmanager:
    <<: *monitoring-common
    image: prom/alertmanager:${ALERTMANAGER_VERSION:-latest}
    container_name: asa-alertmanager
    command:
      - '--config.file=/etc/alertmanager/config.yml'
      - '--storage.path=/alertmanager'
    ports:
      - "${ALERTMANAGER_PORT:-9093}:9093"
    volumes:
      - ./configs/alertmanager:/etc/alertmanager:ro
      - alertmanager-data:/alertmanager
    depends_on:
      - prometheus
    networks:
      - asa-backend

volumes:
  prometheus-data:
    driver: local
  grafana-data:
    driver: local
  alertmanager-data:
    driver: local
```

## Backup Service (docker-compose.backup.yml)

```yaml
version: "3.8"

services:
  backup-manager:
    image: alpine:latest
    container_name: asa-backup-manager
    restart: "no"
    environment:
      - BACKUP_SCHEDULE=${BACKUP_SCHEDULE:-0 2 * * *}
      - BACKUP_RETENTION_DAYS=${BACKUP_RETENTION_DAYS:-7}
      - S3_BUCKET=${BACKUP_S3_BUCKET}
      - S3_ACCESS_KEY=${BACKUP_S3_ACCESS_KEY}
      - S3_SECRET_KEY=${BACKUP_S3_SECRET_KEY}
      - DISCORD_WEBHOOK=${BACKUP_DISCORD_WEBHOOK}
    volumes:
      - server-files-1:/backup/server-1:ro
      - server-files-2:/backup/server-2:ro
      - cluster-shared:/backup/cluster-shared:ro
      - postgres-data:/backup/postgres:ro
      - ./backups:/backup/local
      - ./scripts/backup.sh:/scripts/backup.sh:ro
    command: >
      sh -c "
      apk add --no-cache dcron curl postgresql-client aws-cli &&
      echo '${BACKUP_SCHEDULE} /scripts/backup.sh' | crontab - &&
      crond -f
      "
    depends_on:
      - postgres
    networks:
      - asa-backend
    profiles:
      - backup

  backup-restore:
    image: alpine:latest
    container_name: asa-backup-restore
    restart: "no"
    environment:
      - S3_BUCKET=${BACKUP_S3_BUCKET}
      - S3_ACCESS_KEY=${BACKUP_S3_ACCESS_KEY}
      - S3_SECRET_KEY=${BACKUP_S3_SECRET_KEY}
    volumes:
      - server-files-1:/restore/server-1:rw
      - server-files-2:/restore/server-2:rw
      - cluster-shared:/restore/cluster-shared:rw
      - postgres-data:/restore/postgres:rw
      - ./backups:/restore/local
      - ./scripts/restore.sh:/scripts/restore.sh:ro
    command: "tail -f /dev/null"
    depends_on:
      - postgres
    networks:
      - asa-backend
    profiles:
      - restore
```

## Umgebungsbasierte Konfiguration

### .env.prod (Production)
```bash
# Grundkonfiguration
COMPOSE_PROJECT_NAME=asa-prod
TIMEZONE=Europe/Berlin
ASA_DATA_PATH=/opt/asa-data

# ASA Server Konfiguration
ASA_IMAGE_TAG=latest
ASA_DEBUG=0

# Server 1 Konfiguration
ASA_SERVER_1_NAME=Production Island Server
ASA_SERVER_1_MAP=TheIsland_WP
ASA_SERVER_1_GAME_PORT=7777
ASA_SERVER_1_RCON_PORT=27020
ASA_SERVER_1_START_PARAMS=TheIsland_WP?listen?Port=7777?RCONPort=27020?RCONEnabled=True -WinLiveMaxPlayers=100 -clusterid=prod-cluster

# Database
POSTGRES_VERSION=14
POSTGRES_DB=asa_production
POSTGRES_USER=asa_user
# POSTGRES_PASSWORD wird aus Secret gelesen

# Redis
REDIS_VERSION=7
# REDIS_PASSWORD wird aus Secret gelesen

# Web UI
NODE_ENV=production
NODE_VERSION=18
WEBUI_DOMAIN=asa.yourdomain.com
WEBUI_HTTP_PORT=80
WEBUI_HTTPS_PORT=443
WEBUI_API_URL=https://asa.yourdomain.com/api
WEBUI_CORS_ORIGIN=https://asa.yourdomain.com

# Monitoring
PROMETHEUS_VERSION=latest
GRAFANA_VERSION=latest
GRAFANA_USER=admin
# GRAFANA_PASSWORD wird aus Secret gelesen
PROMETHEUS_PORT=9090
GRAFANA_PORT=3001

# Backup
BACKUP_SCHEDULE=0 2 * * *
BACKUP_RETENTION_DAYS=30
# S3 Credentials werden aus Secrets gelesen
```

### .env.dev (Development)
```bash
# Grundkonfiguration
COMPOSE_PROJECT_NAME=asa-dev
TIMEZONE=Europe/Berlin
ASA_DATA_PATH=/tmp/asa-dev-data

# ASA Server Konfiguration
ASA_IMAGE_TAG=development
ASA_DEBUG=1

# Server 1 Konfiguration (nur ein Server in dev)
ASA_SERVER_1_NAME=Development Server
ASA_SERVER_1_MAP=TheIsland_WP
ASA_SERVER_1_GAME_PORT=7777
ASA_SERVER_1_RCON_PORT=27020
ASA_SERVER_1_START_PARAMS=TheIsland_WP?listen?Port=7777?RCONPort=27020?RCONEnabled=True -WinLiveMaxPlayers=10

# Database
POSTGRES_VERSION=14
POSTGRES_DB=asa_development
POSTGRES_USER=dev_user

# Web UI
NODE_ENV=development
WEBUI_DOMAIN=localhost
WEBUI_HTTP_PORT=3000
WEBUI_HTTPS_PORT=3443
WEBUI_API_URL=http://localhost:3001
WEBUI_CORS_ORIGIN=http://localhost:3000

# Monitoring (reduzierte Ressourcen)
PROMETHEUS_PORT=9090
GRAFANA_PORT=3001
```

## Deployment-Skripte

### deploy.sh
```bash
#!/bin/bash

set -e

ENVIRONMENT=${1:-prod}
ACTION=${2:-up}

echo "Deploying ASA environment: $ENVIRONMENT"

# Environment validation
if [[ ! -f "environments/.env.$ENVIRONMENT" ]]; then
    echo "Error: Environment file not found: environments/.env.$ENVIRONMENT"
    exit 1
fi

# Load environment
export $(cat environments/.env.$ENVIRONMENT | grep -v '^#' | xargs)

# Erstelle notwendige Verzeichnisse
mkdir -p $ASA_DATA_PATH/{server-1,server-2}/{steam,steamcmd,server-files}
mkdir -p $ASA_DATA_PATH/cluster-shared
mkdir -p ./backups ./logs

# Setze Berechtigungen
sudo chown -R 25000:25000 $ASA_DATA_PATH

# Compose Files bestimmen
COMPOSE_FILES="-f docker-compose/base/docker-compose.base.yml"
COMPOSE_FILES="$COMPOSE_FILES -f docker-compose/base/docker-compose.asa.yml"

if [[ "$ENVIRONMENT" != "minimal" ]]; then
    COMPOSE_FILES="$COMPOSE_FILES -f docker-compose/base/docker-compose.webui.yml"
    COMPOSE_FILES="$COMPOSE_FILES -f docker-compose/base/docker-compose.monitoring.yml"
fi

# Environment-spezifische Overrides
if [[ -f "docker-compose/overrides/docker-compose.$ENVIRONMENT.yml" ]]; then
    COMPOSE_FILES="$COMPOSE_FILES -f docker-compose/overrides/docker-compose.$ENVIRONMENT.yml"
fi

# Backup in Production
if [[ "$ENVIRONMENT" == "prod" ]]; then
    COMPOSE_FILES="$COMPOSE_FILES -f docker-compose/base/docker-compose.backup.yml"
fi

case $ACTION in
    up)
        echo "Starting services..."
        docker-compose $COMPOSE_FILES --env-file environments/.env.$ENVIRONMENT up -d
        ;;
    down)
        echo "Stopping services..."
        docker-compose $COMPOSE_FILES --env-file environments/.env.$ENVIRONMENT down
        ;;
    restart)
        echo "Restarting services..."
        docker-compose $COMPOSE_FILES --env-file environments/.env.$ENVIRONMENT restart
        ;;
    logs)
        docker-compose $COMPOSE_FILES --env-file environments/.env.$ENVIRONMENT logs -f
        ;;
    *)
        echo "Usage: $0 <environment> <up|down|restart|logs>"
        exit 1
        ;;
esac

echo "Deployment completed: $ENVIRONMENT"
```

### scale.sh
```bash
#!/bin/bash

set -e

ENVIRONMENT=${1:-prod}
SERVERS=${2:-1}

echo "Scaling ASA to $SERVERS servers in $ENVIRONMENT environment"

# Environment validation
if [[ ! -f "environments/.env.$ENVIRONMENT" ]]; then
    echo "Error: Environment file not found"
    exit 1
fi

export $(cat environments/.env.$ENVIRONMENT | grep -v '^#' | xargs)

# Multi-Server Profile aktivieren wenn mehr als 1 Server
PROFILES=""
if [[ $SERVERS -gt 1 ]]; then
    PROFILES="--profile multi-server"
fi

# Compose command
COMPOSE_CMD="docker-compose -f docker-compose/base/docker-compose.base.yml -f docker-compose/base/docker-compose.asa.yml"

# Scale Services
$COMPOSE_CMD --env-file environments/.env.$ENVIRONMENT $PROFILES up -d --scale asa-server-1=1

if [[ $SERVERS -gt 1 ]]; then
    # Erstelle zusätzliche Server-Verzeichnisse
    for i in $(seq 2 $SERVERS); do
        mkdir -p $ASA_DATA_PATH/server-$i/{steam,steamcmd,server-files}
        sudo chown -R 25000:25000 $ASA_DATA_PATH/server-$i
    done
    
    # Aktiviere Server 2+ Profile
    $COMPOSE_CMD --env-file environments/.env.$ENVIRONMENT --profile multi-server up -d
fi

echo "Scaled to $SERVERS servers"
```

## Health Check und Monitoring

### health-check.sh
```bash
#!/bin/bash

ENVIRONMENT=${1:-prod}
export $(cat environments/.env.$ENVIRONMENT | grep -v '^#' | xargs)

echo "ASA Health Check Report - $(date)"
echo "=================================="

# Check Container Status
echo "Container Status:"
docker-compose -f docker-compose/base/docker-compose.base.yml \
               -f docker-compose/base/docker-compose.asa.yml \
               --env-file environments/.env.$ENVIRONMENT ps

# Check Server Connectivity
echo -e "\nServer Connectivity:"
for port in 7777 7778; do
    if nc -z -w5 localhost $port; then
        echo "✓ Game port $port is accessible"
    else
        echo "✗ Game port $port is not accessible"
    fi
done

# Check RCON
echo -e "\nRCON Status:"
for port in 27020 27021; do
    if nc -z -w5 localhost $port; then
        echo "✓ RCON port $port is accessible"
    else
        echo "✗ RCON port $port is not accessible"
    fi
done

# Check Web UI
echo -e "\nWeb UI Status:"
if curl -s -o /dev/null -w "%{http_code}" http://localhost:${WEBUI_HTTP_PORT:-80}/health | grep -q "200"; then
    echo "✓ Web UI is accessible"
else
    echo "✗ Web UI is not accessible"
fi

# Check Database
echo -e "\nDatabase Status:"
if docker exec asa-postgres pg_isready -U ${POSTGRES_USER} > /dev/null 2>&1; then
    echo "✓ PostgreSQL is healthy"
else
    echo "✗ PostgreSQL is not healthy"
fi

# Check Redis
echo -e "\nRedis Status:"
if docker exec asa-redis redis-cli ping > /dev/null 2>&1; then
    echo "✓ Redis is healthy"
else
    echo "✗ Redis is not healthy"
fi

# Resource Usage
echo -e "\nResource Usage:"
docker stats --no-stream --format "table {{.Container}}\t{{.CPUPerc}}\t{{.MemUsage}}"
```

## Vorteile der neuen Struktur

### 1. Modulare Architektur
- **Separation of Concerns**: Jeder Service hat seine eigene Definition
- **Wiederverwendbarkeit**: Base-Services können in verschiedenen Umgebungen genutzt werden
- **Wartbarkeit**: Änderungen an einem Service beeinflussen nicht die anderen

### 2. Umgebungsbasierte Konfiguration
- **Entwicklung vs. Production**: Separate Konfigurationen
- **Skalierbarkeit**: Einfaches Hinzufügen neuer Umgebungen
- **Sicherheit**: Secrets Management getrennt von Konfiguration

### 3. Automatisierung
- **Deployment Scripts**: Einheitliche Deployment-Prozesse
- **Health Checks**: Automatische Überwachung der Services
- **Backup-Strategien**: Automatisierte Datensicherung

### 4. Observability
- **Monitoring Stack**: Prometheus + Grafana Integration
- **Logging**: Strukturierte Log-Ausgabe
- **Alerting**: Benachrichtigungen bei Problemen

### 5. Sicherheit
- **Secrets Management**: Sensible Daten nicht in Konfigurationsdateien
- **Network Isolation**: Getrennte Netzwerke für Frontend/Backend
- **Container Security**: Non-root User und Least Privilege

Diese verbesserte Docker Compose Struktur bietet eine professionelle, skalierbare und wartbare Lösung für das Management von ARK: Survival Ascended Servern.