# Web Interface - Technische Spezifikation

## Übersicht

Diese Spezifikation definiert die technische Umsetzung des Web Management Interfaces für ARK: Survival Ascended Server. Das Interface soll eine benutzerfreundliche grafische Oberfläche für alle Verwaltungsaufgaben bieten.

## Architektur

### System-Architektur
```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Web Browser   │◄──►│   Web UI        │◄──►│  ASA Server     │
│   (Frontend)    │    │   (Backend)     │    │  (Container)    │
└─────────────────┘    └─────────────────┘    └─────────────────┘
                              │                         │
                              ▼                         ▼
                       ┌─────────────────┐    ┌─────────────────┐
                       │   Database      │    │   File System   │
                       │   (Postgres)    │    │   (Volumes)     │
                       └─────────────────┘    └─────────────────┘
```

### Container-Architektur
```yaml
services:
  asa-webui:
    image: asa-webui:latest
    ports:
      - "3000:3000"
    environment:
      - NODE_ENV=production
      - DATABASE_URL=postgresql://user:pass@postgres:5432/asa_db
      - REDIS_URL=redis://redis:6379
    volumes:
      - server-files-1:/app/server-files:ro
      - cluster-shared:/app/cluster-shared:rw
    depends_on:
      - postgres
      - redis
      - asa-server-1
    networks:
      - asa-network

  postgres:
    image: postgres:14-alpine
    environment:
      - POSTGRES_DB=asa_management
      - POSTGRES_USER=asa_user
      - POSTGRES_PASSWORD=secure_password
    volumes:
      - postgres-data:/var/lib/postgresql/data
    networks:
      - asa-network

  redis:
    image: redis:7-alpine
    volumes:
      - redis-data:/data
    networks:
      - asa-network

  nginx:
    image: nginx:alpine
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx/nginx.conf:/etc/nginx/nginx.conf:ro
      - ./nginx/ssl:/etc/ssl/certs:ro
    depends_on:
      - asa-webui
    networks:
      - asa-network
```

## Backend Spezifikation

### Technologie-Stack
- **Runtime:** Node.js 18+ LTS
- **Framework:** Express.js 4.x
- **Database:** PostgreSQL 14+
- **Cache:** Redis 7+
- **ORM:** Sequelize oder Prisma
- **Authentication:** JWT + bcrypt
- **Real-time:** Socket.io
- **API Documentation:** Swagger/OpenAPI

### Projektstruktur
```
webui/
├── backend/
│   ├── src/
│   │   ├── controllers/
│   │   │   ├── serverController.js
│   │   │   ├── configController.js
│   │   │   ├── rconController.js
│   │   │   ├── userController.js
│   │   │   └── logController.js
│   │   ├── middleware/
│   │   │   ├── auth.js
│   │   │   ├── validation.js
│   │   │   ├── rateLimit.js
│   │   │   └── errorHandler.js
│   │   ├── models/
│   │   │   ├── User.js
│   │   │   ├── Server.js
│   │   │   ├── ConfigHistory.js
│   │   │   └── LogEntry.js
│   │   ├── routes/
│   │   │   ├── api/
│   │   │   │   ├── servers.js
│   │   │   │   ├── config.js
│   │   │   │   ├── rcon.js
│   │   │   │   ├── users.js
│   │   │   │   └── logs.js
│   │   │   └── index.js
│   │   ├── services/
│   │   │   ├── serverService.js
│   │   │   ├── configService.js
│   │   │   ├── rconService.js
│   │   │   ├── logService.js
│   │   │   └── backupService.js
│   │   ├── utils/
│   │   │   ├── asaCtrlWrapper.js
│   │   │   ├── fileWatcher.js
│   │   │   ├── configParser.js
│   │   │   └── logger.js
│   │   ├── config/
│   │   │   ├── database.js
│   │   │   ├── redis.js
│   │   │   └── app.js
│   │   └── app.js
│   ├── tests/
│   ├── package.json
│   └── Dockerfile
├── frontend/
└── docker-compose.webui.yml
```

### Core API Endpoints

#### Server Management
```javascript
// GET /api/servers
// Alle Server abrufen
{
  "servers": [
    {
      "id": "asa-server-1",
      "name": "Main Island Server",
      "status": "running",
      "map": "TheIsland_WP",
      "players": {
        "current": 15,
        "max": 50
      },
      "uptime": 86400,
      "performance": {
        "cpu": 45.2,
        "memory": 78.5,
        "disk": 34.1
      }
    }
  ]
}

// POST /api/servers/:id/start
// Server starten

// POST /api/servers/:id/stop
// Server stoppen

// POST /api/servers/:id/restart
// Server neustarten

// GET /api/servers/:id/status
// Aktueller Server-Status

// GET /api/servers/:id/players
// Aktuelle Spieler-Liste
```

#### Konfiguration Management
```javascript
// GET /api/config/:serverId/gameusersettings
// GameUserSettings.ini abrufen
{
  "content": "[ServerSettings]\nSessionName=My Server\n...",
  "lastModified": "2024-01-15T10:30:00Z",
  "version": "1.2.3"
}

// PUT /api/config/:serverId/gameusersettings
// GameUserSettings.ini aktualisieren
{
  "content": "[ServerSettings]\nSessionName=Updated Server\n...",
  "backup": true,
  "restart": false
}

// GET /api/config/:serverId/game
// Game.ini abrufen

// PUT /api/config/:serverId/game
// Game.ini aktualisieren

// GET /api/config/:serverId/history
// Konfigurationsverlauf abrufen
```

#### RCON Integration
```javascript
// POST /api/rcon/:serverId/execute
// RCON Kommando ausführen
{
  "command": "saveworld",
  "response": "World saved successfully",
  "timestamp": "2024-01-15T10:30:00Z"
}

// GET /api/rcon/:serverId/players
// Spieler via RCON abrufen

// POST /api/rcon/:serverId/broadcast
// Broadcast Message senden
{
  "message": "Server restart in 5 minutes",
  "type": "warning"
}

// POST /api/rcon/:serverId/kick
// Spieler kicken
{
  "playerId": "76561198012345678",
  "reason": "Violation of server rules"
}
```

#### Log Management
```javascript
// GET /api/logs/:serverId?level=info&limit=100&offset=0
// Server-Logs abrufen
{
  "logs": [
    {
      "timestamp": "2024-01-15T10:30:00Z",
      "level": "info",
      "message": "Player joined: TestPlayer",
      "source": "server"
    }
  ],
  "pagination": {
    "total": 5000,
    "page": 1,
    "limit": 100
  }
}

// GET /api/logs/:serverId/stream
// WebSocket für Live-Logs

// POST /api/logs/:serverId/export
// Log-Export erstellen
```

### Service-Klassen

#### Server Service
```javascript
class ServerService {
  async getServerStatus(serverId) {
    // Docker Container Status prüfen
    // Performance-Metriken sammeln
    // Spieler-Informationen abrufen
  }

  async startServer(serverId) {
    // docker compose start ausführen
    // Status-Updates via WebSocket senden
  }

  async stopServer(serverId, graceful = true) {
    // Spieler-Warnung senden (optional)
    // World speichern
    // Container stoppen
  }

  async restartServer(serverId, delay = 0) {
    // Ankündigung senden
    // Graceful restart durchführen
  }

  async getPlayerList(serverId) {
    // RCON Kommando für Spieler-Liste
    // Spieler-Informationen parsen
  }
}
```

#### Configuration Service
```javascript
class ConfigService {
  async getGameUserSettings(serverId) {
    // Datei aus Volume lesen
    // INI-Format parsen
    // Validation durchführen
  }

  async updateGameUserSettings(serverId, content, options = {}) {
    // Backup erstellen
    // Validierung durchführen
    // Datei schreiben
    // Server restart (optional)
    // Versionshistorie aktualisieren
  }

  async validateConfig(configType, content) {
    // Syntax-Validierung
    // Semantische Validierung
    // Warnung bei kritischen Änderungen
  }

  async createBackup(serverId, configType) {
    // Timestamped backup erstellen
    // Metadaten speichern
  }

  async restoreBackup(serverId, configType, backupId) {
    // Backup validieren
    // Wiederherstellen
    // Verlauf aktualisieren
  }
}
```

#### RCON Service
```javascript
class RconService {
  async executeCommand(serverId, command) {
    // Verbindung zu asa-ctrl herstellen
    // Kommando validieren
    // Ausführen und Response verarbeiten
    // Logging
  }

  async broadcastMessage(serverId, message, type = 'info') {
    // Formatierte Nachricht senden
    // Logging
  }

  async getOnlinePlayers(serverId) {
    // ListPlayers Kommando
    // Response parsen
    // Spieler-Objekte erstellen
  }

  async kickPlayer(serverId, playerId, reason) {
    // Kick-Kommando zusammenstellen
    // Ausführen
    // Logging
  }

  async banPlayer(serverId, playerId, reason, duration) {
    // Ban-Kommando
    // Ban-Liste aktualisieren
    // Logging
  }
}
```

### ASA-Ctrl Integration
```javascript
class AsaCtrlWrapper {
  constructor(containerId) {
    this.containerId = containerId;
  }

  async executeRcon(command) {
    // docker exec -t asa-server-1 asa-ctrl rcon --exec 'command'
    const result = await exec(`docker exec -t ${this.containerId} asa-ctrl rcon --exec '${command}'`);
    return this.parseRconResponse(result);
  }

  async getServerInfo() {
    // Verschiedene RCON-Kommandos für Server-Info
    const info = {};
    info.players = await this.executeRcon('ListPlayers');
    info.version = await this.executeRcon('GetGameVersion');
    return info;
  }

  parseRconResponse(rawOutput) {
    // RCON Response aufbereiten
    // Error-Handling
    // Structured Data zurückgeben
  }
}
```

## Frontend Spezifikation

### Technologie-Stack
- **Framework:** React 18+ mit TypeScript
- **State Management:** Redux Toolkit oder Zustand
- **UI Library:** Material-UI (MUI) oder Ant Design
- **Charts:** Chart.js oder Recharts
- **Real-time:** Socket.io-client
- **HTTP Client:** Axios
- **Forms:** React Hook Form
- **Code Editor:** Monaco Editor

### Komponenten-Struktur
```
frontend/src/
├── components/
│   ├── common/
│   │   ├── Header.tsx
│   │   ├── Sidebar.tsx
│   │   ├── LoadingSpinner.tsx
│   │   └── ErrorBoundary.tsx
│   ├── server/
│   │   ├── ServerCard.tsx
│   │   ├── ServerStatus.tsx
│   │   ├── PlayerList.tsx
│   │   └── PerformanceChart.tsx
│   ├── config/
│   │   ├── ConfigEditor.tsx
│   │   ├── ConfigHistory.tsx
│   │   └── ConfigValidator.tsx
│   ├── rcon/
│   │   ├── RconConsole.tsx
│   │   ├── CommandHistory.tsx
│   │   └── PlayerManagement.tsx
│   └── logs/
│       ├── LogViewer.tsx
│       ├── LogFilters.tsx
│       └── LogExport.tsx
├── pages/
│   ├── Dashboard.tsx
│   ├── ServerManagement.tsx
│   ├── Configuration.tsx
│   ├── RconInterface.tsx
│   ├── Logs.tsx
│   └── Settings.tsx
├── hooks/
│   ├── useServerStatus.ts
│   ├── useRealTimeUpdates.ts
│   ├── useConfigValidation.ts
│   └── useWebSocket.ts
├── services/
│   ├── api.ts
│   ├── websocket.ts
│   └── auth.ts
├── store/
│   ├── index.ts
│   ├── serverSlice.ts
│   ├── configSlice.ts
│   └── authSlice.ts
└── utils/
    ├── formatters.ts
    ├── validators.ts
    └── constants.ts
```

### Hauptkomponenten

#### Dashboard
```tsx
const Dashboard: React.FC = () => {
  const servers = useSelector(selectServers);
  const { data: metrics, isLoading } = useServerMetrics();

  return (
    <Grid container spacing={3}>
      <Grid item xs={12}>
        <ServerOverview servers={servers} />
      </Grid>
      <Grid item xs={12} md={6}>
        <PerformanceChart data={metrics} />
      </Grid>
      <Grid item xs={12} md={6}>
        <PlayerStatistics servers={servers} />
      </Grid>
      <Grid item xs={12}>
        <RecentActivity />
      </Grid>
    </Grid>
  );
};
```

#### Server Management
```tsx
const ServerManagement: React.FC = () => {
  const [selectedServer, setSelectedServer] = useState(null);
  const servers = useServerList();

  return (
    <Box>
      <ServerSelector 
        servers={servers}
        selected={selectedServer}
        onSelect={setSelectedServer}
      />
      {selectedServer && (
        <>
          <ServerControls serverId={selectedServer.id} />
          <PlayerList serverId={selectedServer.id} />
          <ServerMetrics serverId={selectedServer.id} />
        </>
      )}
    </Box>
  );
};
```

#### Configuration Editor
```tsx
const ConfigEditor: React.FC<{ serverId: string; configType: string }> = ({ serverId, configType }) => {
  const [content, setContent] = useState('');
  const [isValid, setIsValid] = useState(true);
  const { mutate: saveConfig, isLoading } = useSaveConfig();

  const handleSave = () => {
    saveConfig({
      serverId,
      configType,
      content,
      backup: true
    });
  };

  return (
    <Box>
      <ConfigToolbar onSave={handleSave} isValid={isValid} isLoading={isLoading} />
      <MonacoEditor
        language="ini"
        value={content}
        onChange={setContent}
        options={{
          minimap: { enabled: false },
          scrollBeyondLastLine: false,
          wordWrap: 'on'
        }}
      />
      <ConfigValidator content={content} onValidate={setIsValid} />
    </Box>
  );
};
```

#### RCON Console
```tsx
const RconConsole: React.FC<{ serverId: string }> = ({ serverId }) => {
  const [command, setCommand] = useState('');
  const [history, setHistory] = useState<string[]>([]);
  const { mutate: executeCommand } = useRconCommand();

  const handleExecute = () => {
    executeCommand({ serverId, command });
    setHistory(prev => [...prev, command]);
    setCommand('');
  };

  return (
    <Box>
      <RconOutput history={history} />
      <RconInput 
        value={command}
        onChange={setCommand}
        onExecute={handleExecute}
        suggestions={RCON_COMMANDS}
      />
      <CommandHistory history={history} onSelect={setCommand} />
    </Box>
  );
};
```

### Real-time Updates
```tsx
const useRealTimeUpdates = (serverId: string) => {
  const dispatch = useDispatch();
  
  useEffect(() => {
    const socket = io('/server-updates');
    
    socket.emit('subscribe', serverId);
    
    socket.on('status-update', (data) => {
      dispatch(updateServerStatus({ serverId, status: data }));
    });
    
    socket.on('player-joined', (player) => {
      dispatch(addPlayer({ serverId, player }));
    });
    
    socket.on('player-left', (playerId) => {
      dispatch(removePlayer({ serverId, playerId }));
    });
    
    socket.on('log-entry', (entry) => {
      dispatch(addLogEntry({ serverId, entry }));
    });
    
    return () => {
      socket.emit('unsubscribe', serverId);
      socket.disconnect();
    };
  }, [serverId, dispatch]);
};
```

## Deployment-Konfiguration

### Docker Images
```dockerfile
# Backend Dockerfile
FROM node:18-alpine

WORKDIR /app

COPY package*.json ./
RUN npm ci --only=production

COPY src/ ./src/
COPY config/ ./config/

EXPOSE 3000

CMD ["node", "src/app.js"]
```

```dockerfile
# Frontend Dockerfile
FROM node:18-alpine AS builder

WORKDIR /app
COPY package*.json ./
RUN npm ci

COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/nginx.conf

EXPOSE 80
```

### Docker Compose Integration
```yaml
# Erweiterte docker-compose.yml
version: "3.8"

services:
  # Bestehende ASA Server Services...
  
  asa-webui-backend:
    build: ./webui/backend
    environment:
      - NODE_ENV=production
      - DATABASE_URL=postgresql://asa_user:${DB_PASSWORD}@postgres:5432/asa_management
      - REDIS_URL=redis://redis:6379
      - JWT_SECRET=${JWT_SECRET}
    volumes:
      - server-files-1:/app/server-data:ro
      - cluster-shared:/app/cluster-shared:rw
    depends_on:
      - postgres
      - redis
    networks:
      - asa-network

  asa-webui-frontend:
    build: ./webui/frontend
    depends_on:
      - asa-webui-backend
    networks:
      - asa-network

  postgres:
    image: postgres:14-alpine
    environment:
      - POSTGRES_DB=asa_management
      - POSTGRES_USER=asa_user
      - POSTGRES_PASSWORD=${DB_PASSWORD}
    volumes:
      - postgres-data:/var/lib/postgresql/data
    networks:
      - asa-network

  redis:
    image: redis:7-alpine
    command: redis-server --appendonly yes
    volumes:
      - redis-data:/data
    networks:
      - asa-network

  nginx:
    image: nginx:alpine
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx/nginx.conf:/etc/nginx/nginx.conf:ro
      - ./nginx/ssl:/etc/ssl/certs:ro
    depends_on:
      - asa-webui-frontend
      - asa-webui-backend
    networks:
      - asa-network

volumes:
  postgres-data:
  redis-data:
  # Bestehende volumes...

networks:
  asa-network:
    # Bestehende network config...
```

### Nginx Configuration
```nginx
upstream backend {
    server asa-webui-backend:3000;
}

upstream frontend {
    server asa-webui-frontend:80;
}

server {
    listen 80;
    server_name _;

    # Frontend
    location / {
        proxy_pass http://frontend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    # API
    location /api/ {
        proxy_pass http://backend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }

    # WebSocket
    location /socket.io/ {
        proxy_pass http://backend;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

## Sicherheitsüberlegungen

### Authentication & Authorization
- JWT-basierte Authentifizierung
- Role-based Access Control (Admin, Moderator, Viewer)
- API Rate Limiting
- CORS-Konfiguration
- Input Validation und Sanitization

### Container Security
- Non-root User in Containern
- Read-only Filesysteme wo möglich
- Secret Management über Docker Secrets
- Network Isolation
- Regular Security Updates

### Data Protection
- Verschlüsselung von Passwörtern (bcrypt)
- HTTPS-Enforcement
- Sichere Cookie-Konfiguration
- SQL Injection Prevention
- XSS Protection

Dieses Web Interface bietet eine vollständige, moderne Lösung für das Management von ARK: Survival Ascended Servern mit Fokus auf Benutzerfreundlichkeit, Sicherheit und Skalierbarkeit.