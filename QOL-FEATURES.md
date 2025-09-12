# 🎮 Quality of Life Verbesserungen - Neue Features

Diese Sektion beschreibt die neuen Quality of Life (QoL) Verbesserungen, die zum ARK: Survival Ascended Linux Container Image hinzugefügt wurden.

## 🚀 Schnellstart mit Setup-Wizard

### Interaktiver Setup-Wizard
```bash
./setup-wizard.sh
```

Der Setup-Wizard bietet:
- ✅ **Automatische Voraussetzungsprüfung** (Docker, Berechtigungen, etc.)
- ✅ **Interaktive Konfiguration** mit Validierung
- ✅ **Port-Konflikterkennung** und -validierung
- ✅ **Sichere Passwort-Generierung**
- ✅ **Automatische Skript-Erstellung** für Verwaltung
- ✅ **Schnellreferenz-Generierung**

### Was wird automatisch erstellt:
- `docker-compose.yml` - Konfigurierte Container-Definition
- `GameUserSettings.ini.template` - Server-Konfiguration
- `server-status.sh` - Status-Überwachung
- `server-restart.sh` - Sicherer Server-Neustart
- `server-backup.sh` - Backup-Erstellung
- `QUICK_REFERENCE.md` - Personalisierte Schnellreferenz

## 🛠️ Erweiterte asa-ctrl Funktionen

### Neuer Status-Befehl
```bash
docker exec asa-server-1 asa-ctrl status          # Basis-Status
docker exec asa-server-1 asa-ctrl status --verbose # Detaillierter Status
```

Zeigt an:
- Server-Laufzustand und Uptime
- Speicherverbrauch und Performance
- Aktuelle Spielerzahl und Namen
- Kürzliche Log-Aktivitäten
- Konfigurationsdetails

### Neues Backup-System
```bash
# Backup erstellen
docker exec asa-server-1 asa-ctrl backup --create
docker exec asa-server-1 asa-ctrl backup --create --name "vor_mod_update"

# Backups auflisten
docker exec asa-server-1 asa-ctrl backup --list

# Backup wiederherstellen
docker exec asa-server-1 asa-ctrl backup --restore "backup_name"

# Alte Backups aufräumen
docker exec asa-server-1 asa-ctrl backup --cleanup --keep 5
```

Features:
- **Automatische Welt-Speicherung** vor Backup
- **Komprimierte Archive** mit Metadaten
- **Backup-Verifizierung** und Größenanzeige
- **Automatische Aufräumung** alter Backups
- **Wiederherstellungspunkte** vor Restore

## 📊 Health Check System

### Automatische Gesundheitsüberwachung
```bash
# Manueller Health Check
docker exec asa-server-1 health-check
```

Überwacht:
- **Server-Prozess-Status** und Laufzeit
- **Speicherverbrauch** mit Warnungen
- **Festplattenspeicher** und freier Platz
- **RCON-Konnektivität** und Antwortzeit
- **Server-Dateien-Integrität**
- **Netzwerk-Port-Bindung**
- **Proton-Installation** und -Konfiguration

### Docker Health Checks
Die `docker-compose.enhanced.yml` enthält automatische Health Checks:
```yaml
healthcheck:
  test: ["CMD-SHELL", "health-check"]
  interval: 30s
  timeout: 10s
  retries: 3
  start_period: 300s
```

## 🎯 Makefile-Integration

### Neue Management-Befehle
```bash
make setup              # Setup-Wizard ausführen
make start              # Server starten
make stop               # Server stoppen
make restart            # Server neu starten (mit Speicherung)
make status             # Server-Status anzeigen
make logs               # Logs verfolgen
make backup             # Backup erstellen
make list-backups       # Backups auflisten
make update             # Container-Image aktualisieren
```

### Praktische Shortcuts
```bash
make quick-backup name=vor_update      # Benanntes Backup
make restore-backup name=backup_name   # Backup wiederherstellen
make rcon cmd='listplayers'            # RCON-Befehl ausführen
make broadcast msg='Wartung in 5 Min'  # Nachricht senden
make players                           # Spielerliste anzeigen
make save                              # Welt speichern
```

## 📝 Verbesserte Logging und Monitoring

### Strukturierte Logs
```yaml
logging:
  driver: "json-file"
  options:
    max-size: "100m"
    max-file: "3"
```

### Resource Limits
```yaml
deploy:
  resources:
    limits:
      memory: 16G
    reservations:
      memory: 8G
```

### Restart Policies
```yaml
restart: unless-stopped
```

## 🔧 Erweiterte Docker Compose Features

### Enhanced Compose File
`docker-compose.enhanced.yml` bietet:
- **Health Checks** für automatische Überwachung
- **Resource Limits** für Stabilität
- **Structured Logging** mit Rotation
- **Backup Volumes** für Datensicherheit
- **Network Optimierungen**
- **Restart Policies** für Hochverfügbarkeit

### Backup Volumes
```yaml
volumes:
  backups-1:
    name: asa-server_backups-1
```

Automatisch gemountete Backup-Verzeichnisse für jeden Server.

## 📚 Verbesserte Dokumentation

### Neue Dokumentationsdateien
- `QUICK_START.md` - Schnellstart-Anleitung für Anfänger
- `TODO-IMPROVEMENTS.md` - Detaillierter Verbesserungsplan
- `QUICK_REFERENCE.md` - Vom Setup-Wizard generierte Referenz

### Strukturierte Problemlösung
- **Schritt-für-Schritt Guides** für häufige Probleme
- **Automatische Diagnose-Scripts**
- **Troubleshooting-Checklisten**

## 🎨 Benutzerfreundlichkeit

### Farbige Ausgaben
Alle Scripts verwenden Farben für bessere Lesbarkeit:
- 🟢 **Grün**: Erfolgreiche Operationen
- 🟡 **Gelb**: Warnungen und Hinweise
- 🔴 **Rot**: Fehler und kritische Probleme
- 🔵 **Blau**: Informative Nachrichten

### Intelligente Validierung
- **Port-Konflikterkennung** vor Server-Start
- **Passwort-Stärke-Prüfung** für Sicherheit
- **Eingabe-Validierung** mit hilfreichen Fehlermeldungen
- **Voraussetzungs-Checks** vor Installation

### Automatisierung
- **Ein-Befehl-Setup** für neue Installationen
- **Automatische Backup-Rotation** zur Speicherplatz-Verwaltung
- **Intelligente Updates** mit Rollback-Optionen
- **Batch-Operationen** für Multi-Server-Setups

## 🔄 Migration von bestehenden Installationen

### Für bestehende Nutzer:
1. **Backup erstellen** der aktuellen Installation
2. **Neue Files downloaden**: `git pull` oder manueller Download
3. **Setup-Wizard ausführen**: `./setup-wizard.sh`
4. **Konfiguration migrieren** falls gewünscht
5. **Enhanced Compose verwenden**: `cp docker-compose.enhanced.yml docker-compose.yml`

### Rückwärtskompatibilität
Alle neuen Features sind **vollständig rückwärtskompatibel**. Bestehende Installationen funktionieren weiterhin ohne Änderungen.

## 🚀 Nächste Verbesserungen

Siehe `TODO-IMPROVEMENTS.md` für geplante Features:
- **Web-Dashboard** für GUI-Management
- **Multi-Server-Management** für Cluster
- **Automatische Updates** mit Staging
- **Performance-Monitoring** mit Metriken
- **Discord-Integration** für Benachrichtigungen

---

**💡 Tipp**: Verwenden Sie `make help` für eine vollständige Liste aller verfügbaren Befehle!