# 🚀 ARK: Survival Ascended - Quick Start Guide

**Neu hier? Starten Sie in 5 Minuten mit dem Setup-Wizard!**

## Schnellstart für Anfänger

### Option 1: Setup-Wizard (Empfohlen) 🎯

```bash
# 1. Repository herunterladen
git clone https://github.com/mschnitzer/ark-survival-ascended-linux-container-image.git
cd ark-survival-ascended-linux-container-image

# 2. Setup-Wizard ausführen
./setup-wizard.sh

# 3. Server starten (wird vom Wizard erklärt)
docker compose up -d

# 4. Logs verfolgen
docker logs -f asa-server-1
```

Der Setup-Wizard führt Sie durch:
- ✅ Automatische Voraussetzungsprüfung
- ✅ Interaktive Server-Konfiguration
- ✅ Port-Konflikterkennung
- ✅ Automatische Passwort-Generierung
- ✅ Erstellung von Verwaltungsskripten
- ✅ Schnellreferenz-Guide

### Option 2: Manuelle Einrichtung (Für Erfahrene)

Folgen Sie der [detaillierten Anleitung im README.md](./README.md).

## Nach der Installation

### Server-Verwaltung (Neue QoL-Features) 🛠️

```bash
# Server-Status prüfen (NEU!)
docker exec asa-server-1 asa-ctrl status
docker exec asa-server-1 asa-ctrl status --verbose

# Backup erstellen (NEU!)
docker exec asa-server-1 asa-ctrl backup --create
docker exec asa-server-1 asa-ctrl backup --create --name "vor_mod_update"

# Backups auflisten (NEU!)
docker exec asa-server-1 asa-ctrl backup --list

# Backup wiederherstellen (NEU!)
docker exec asa-server-1 asa-ctrl backup --restore "backup_name"

# Alte Backups aufräumen (NEU!)
docker exec asa-server-1 asa-ctrl backup --cleanup --keep 5
```

### Praktische Verwaltungsskripte

Der Setup-Wizard erstellt automatisch diese Hilfsskripte:

```bash
# Server-Status und Performance anzeigen
./server-status.sh

# Server sicher neustarten (mit Warnung an Spieler)
./server-restart.sh

# Backup erstellen
./server-backup.sh
```

### Häufige Befehle

```bash
# Server starten/stoppen
docker compose up -d        # Starten
docker compose stop         # Stoppen
docker compose restart      # Neustarten

# RCON-Befehle
docker exec asa-server-1 asa-ctrl rcon --exec 'saveworld'
docker exec asa-server-1 asa-ctrl rcon --exec 'listplayers'
docker exec asa-server-1 asa-ctrl rcon --exec 'broadcast Hallo alle!'

# Logs anzeigen
docker logs -f asa-server-1
```

## 🎮 Erstes Mal spielen

1. **Server finden**: Suchen Sie in ARK im "Unofficial" Bereich nach Ihrem Server-Namen
2. **Wartezeit**: Der erste Start kann 10-20 Minuten dauern
3. **Verbindung**: Falls Sie den Server nicht finden, warten Sie weitere 5 Minuten

## 🚨 Problemlösung

### Server nicht im Browser sichtbar?
- ✅ Warten Sie 5-10 Minuten nach dem Start
- ✅ Suchen Sie in "Unofficial" Servern
- ✅ Klicken Sie auf "Show player server settings"
- ✅ Prüfen Sie Ihre Firewall/Port-Weiterleitung

### Verbindung fehlgeschlagen?
```bash
# Status prüfen
./server-status.sh

# Logs kontrollieren
docker logs asa-server-1

# Port-Test (von außerhalb)
telnet IHR_SERVER_IP 7777
```

### Performance-Probleme?
```bash
# Ressourcenverbrauch prüfen
docker exec asa-server-1 asa-ctrl status

# Aktuelle Spieler anzeigen
docker exec asa-server-1 asa-ctrl rcon --exec 'listplayers'
```

## 📁 Wichtige Dateien und Ordner

```
/var/lib/docker/volumes/asa-server_server-files-1/_data/
├── ShooterGame/Saved/Config/WindowsServer/
│   ├── GameUserSettings.ini  # Haupt-Konfiguration
│   └── Game.ini             # Erweiterte Einstellungen
├── ShooterGame/Saved/SavedArks/  # Spielstände
└── ShooterGame/Binaries/Win64/   # Server-Programme
```

## 🔧 Erweiterte Konfiguration

### Mods hinzufügen
```yaml
# In docker-compose.yml
environment:
  - ASA_START_PARAMS=TheIsland_WP?listen?Port=7777?RCONPort=27020?RCONEnabled=True -WinLiveMaxPlayers=50 -mods=12345,67891
```

### Zweiten Server einrichten
Entkommentieren Sie den `asa-server-2` Abschnitt in `docker-compose.yml` und führen Sie aus:
```bash
docker compose up -d
```

### Automatische Neustarts
```bash
# Crontab bearbeiten
crontab -e

# Täglicher Neustart um 4:00 Uhr hinzufügen
0 4 * * * cd /pfad/zu/ihrem/server && ./server-restart.sh
```

## 🔒 Sicherheit

- 🔐 Verwenden Sie starke Passwörter (mindestens 8 Zeichen)
- 🛡️ Öffnen Sie nur notwendige Ports (7777/UDP, 27020/TCP optional)
- 💾 Erstellen Sie regelmäßige Backups
- 🔄 Halten Sie den Container aktuell

## 📞 Hilfe und Support

- 📖 **Vollständige Dokumentation**: [README.md](./README.md)
- 🏗️ **Verbesserungsplan**: [TODO-IMPROVEMENTS.md](./TODO-IMPROVEMENTS.md)
- 🐛 **Probleme melden**: [GitHub Issues](https://github.com/mschnitzer/ark-survival-ascended-linux-container-image/issues)

## ⚡ Performance-Tipps

### Empfohlene Hardware (pro Server)
- **RAM**: 13+ GB
- **CPU**: 4+ Kerne
- **Storage**: 31+ GB SSD
- **Netzwerk**: Stabile Verbindung mit geringer Latenz

### Optimierungseinstellungen
```ini
# In GameUserSettings.ini für bessere Performance
[ServerSettings]
DinoCountMultiplier=0.8          # Weniger Dinosaurier
HarvestAmountMultiplier=2.0      # Mehr Ressourcen pro Sammlung
TamingSpeedMultiplier=3.0        # Schnelleres Zähmen
XPMultiplier=2.0                 # Schnelleres Leveln
```

---

**🎉 Viel Spaß mit Ihrem ARK: Survival Ascended Server!**

*Erstellt mit dem verbesserten Container-Image - für ein besseres Server-Management-Erlebnis.*