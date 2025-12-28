#!/bin/bash
# Update-Script für KI-System
# Lädt die neueste Version von GitHub und startet neu

set -e

# Verzögerung für Web-Interface Response (damit fetch() nicht abbricht)
if [ "$1" = "--delay" ]; then
    echo "⏳ Warte 2 Sekunden auf Web-Response..."
    sleep 2
fi

echo "╔═══════════════════════════════════════════╗"
echo "║   KI Smart Home System - Update          ║"
echo "╚═══════════════════════════════════════════╝"
echo ""

# Prüfe ob Git-Repository vorhanden
if [ ! -d ".git" ]; then
    echo "❌ FEHLER: Kein Git-Repository gefunden!"
    echo "Bitte führe 'git init' und 'git remote add origin <URL>' aus."
    exit 1
fi

# Zeige aktuelle Version
echo "📌 Aktuelle Version:"
git log -1 --oneline
echo ""

# Prüfe auf ungespeicherte Änderungen (alle Code- und Config-Dateien)
if git diff --quiet HEAD -- '*.py' '*.html' '*.css' '*.js' '*.sh' '*.md' '*.yaml' '*.yml' 'requirements.txt'; then
    echo "✓ Keine Code-Änderungen gefunden"
else
    echo "⚠️  Warnung: Ungespeicherte Code-Änderungen gefunden!"
    echo ""
    echo "Geänderte Dateien:"
    git diff --name-only HEAD -- '*.py' '*.html' '*.css' '*.js' '*.sh' '*.md' '*.yaml' '*.yml' 'requirements.txt' | head -10
    echo ""
    
    # Wenn nicht interaktiv (z.B. von Web-Interface), automatisch überschreiben
    if [ ! -t 0 ]; then
        echo "  ℹ️  Nicht-interaktiver Modus: Änderungen werden zurückgesetzt"
        git checkout -- '*.py' '*.html' '*.css' '*.js' '*.sh' '*.yaml' '*.yml' 2>/dev/null || true
        git checkout -- 'config/' 2>/dev/null || true
    else
        echo "Diese werden überschrieben. Fortfahren? (j/n)"
        read -r response
        if [[ ! "$response" =~ ^[Jj]$ ]]; then
            echo "Update abgebrochen."
            exit 0
        fi
        git checkout -- '*.py' '*.html' '*.css' '*.js' '*.sh' '*.yaml' '*.yml' 2>/dev/null || true
        git checkout -- 'config/' 2>/dev/null || true
    fi
fi

# Hinweis: Daten sind durch .gitignore geschützt
echo ""
echo "🔒 Datenschutz-Status:"
echo "  ✓ Datenbank (data/*.db) - Geschützt durch .gitignore"
echo "  ✓ Konfigurationen (data/*.json) - Geschützt durch .gitignore"
echo "  ✓ ML-Modelle (models/*.pkl) - Geschützt durch .gitignore"
echo "  ✓ Credentials (.env) - Geschützt durch .gitignore"
echo "  ✓ config.yaml (API-Keys) - Geschützt durch .gitignore"
echo ""
echo "  ℹ️  Diese Dateien werden von Git NICHT überschrieben!"

# Zusätzliches Sicherheits-Backup (nur zur Sicherheit)
echo ""
echo "📦 Erstelle zusätzliches Sicherheits-Backup..."
BACKUP_DIR=".backup/$(date +%Y%m%d_%H%M%S)"
mkdir -p "$BACKUP_DIR"
if [ -f ".env" ]; then
    cp .env "$BACKUP_DIR/.env" 2>/dev/null || true
    echo "  ✓ .env gesichert"
fi
if [ -f "config/config.yaml" ]; then
    mkdir -p "$BACKUP_DIR/config"
    cp config/config.yaml "$BACKUP_DIR/config/config.yaml" 2>/dev/null || true
    echo "  ✓ config/config.yaml gesichert"
fi
if [ -d "data" ]; then
    cp -r data "$BACKUP_DIR/data" 2>/dev/null || true
    echo "  ✓ data/ gesichert"
fi
if [ -d "models" ]; then
    cp -r models "$BACKUP_DIR/models" 2>/dev/null || true
    echo "  ✓ models/ gesichert"
fi
echo "  💾 Backup gespeichert in: $BACKUP_DIR"

# Hole Updates von GitHub
echo ""
echo "📥 Lade Updates von GitHub..."
git fetch origin

# Zeige verfügbare Updates
COMMITS_BEHIND=$(git rev-list HEAD..origin/main --count 2>/dev/null || echo "0")
if [ "$COMMITS_BEHIND" -eq 0 ]; then
    echo "✓ System ist bereits auf dem neuesten Stand!"
    rm -rf .backup
    exit 0
fi

echo "📊 $COMMITS_BEHIND neue(s) Update(s) verfügbar:"
git log HEAD..origin/main --oneline --no-merges | head -5
echo ""

# Pull Updates
echo "⬇️  Installiere Updates..."

# WICHTIG: Sichere Benutzerdaten VOR dem Reset
echo "  📂 Sichere Benutzerdaten..."
USER_DATA_BACKUP="/tmp/ki_system_userdata_$$"
mkdir -p "$USER_DATA_BACKUP"
[ -f "data/ha_entities.json" ] && cp data/ha_entities.json "$USER_DATA_BACKUP/" 2>/dev/null
[ -f "data/presence_history.json" ] && cp data/presence_history.json "$USER_DATA_BACKUP/" 2>/dev/null
[ -f "data/automations.json" ] && cp data/automations.json "$USER_DATA_BACKUP/" 2>/dev/null
[ -f "data/rooms.json" ] && cp data/rooms.json "$USER_DATA_BACKUP/" 2>/dev/null
[ -f "data/sensor_config.json" ] && cp data/sensor_config.json "$USER_DATA_BACKUP/" 2>/dev/null

# Reset lokale Änderungen vor dem Pull (außer data/, models/, .env)
git reset --hard HEAD 2>&1 || echo "⚠️ git reset fehlgeschlagen"
git clean -fd --exclude=data --exclude=models --exclude=.env --exclude=logs --exclude=.backup --exclude=config/config.yaml 2>&1 || echo "⚠️ git clean fehlgeschlagen"

# Jetzt Pull durchführen
if ! git pull origin main 2>&1; then
    echo "❌ git pull fehlgeschlagen!"
    echo "Versuche alternativen Ansatz..."
    git fetch origin main
    git reset --hard origin/main
fi

# Stelle Benutzerdaten wieder her
echo "  📂 Stelle Benutzerdaten wieder her..."
[ -f "$USER_DATA_BACKUP/ha_entities.json" ] && cp "$USER_DATA_BACKUP/ha_entities.json" data/ 2>/dev/null && echo "    ✓ ha_entities.json wiederhergestellt"
[ -f "$USER_DATA_BACKUP/presence_history.json" ] && cp "$USER_DATA_BACKUP/presence_history.json" data/ 2>/dev/null && echo "    ✓ presence_history.json wiederhergestellt"
[ -f "$USER_DATA_BACKUP/automations.json" ] && cp "$USER_DATA_BACKUP/automations.json" data/ 2>/dev/null && echo "    ✓ automations.json wiederhergestellt"
[ -f "$USER_DATA_BACKUP/rooms.json" ] && cp "$USER_DATA_BACKUP/rooms.json" data/ 2>/dev/null && echo "    ✓ rooms.json wiederhergestellt"
[ -f "$USER_DATA_BACKUP/sensor_config.json" ] && cp "$USER_DATA_BACKUP/sensor_config.json" data/ 2>/dev/null && echo "    ✓ sensor_config.json wiederhergestellt"
rm -rf "$USER_DATA_BACKUP"

# Aktiviere Virtual Environment falls vorhanden
if [ -d "venv" ]; then
    echo ""
    echo "🔧 Aktiviere Virtual Environment..."
    source venv/bin/activate
fi

# Update Dependencies
echo ""
echo "📦 Aktualisiere Python-Pakete..."
set +e
pip install --upgrade pip -q
PIP_STATUS=$?
pip install -r requirements.txt -q
REQ_STATUS=$?
set -e
if [ $PIP_STATUS -ne 0 ] || [ $REQ_STATUS -ne 0 ]; then
    echo "⚠️  Abhängigkeits-Update fehlgeschlagen, fahre mit Neustart fort."
else
    echo "✓ Dependencies aktualisiert"
fi

# Neue Version anzeigen
echo ""
echo "✅ Update erfolgreich installiert!"
echo ""
echo "📌 Neue Version:"
git log -1 --oneline
echo ""

# Aufräumen (alte Backups behalten, nur temporäre löschen)
echo "🧹 Bereinige alte Backups (älter als 7 Tage)..."
find .backup -type d -mtime +7 -exec rm -rf {} + 2>/dev/null || true
echo "✓ Backups der letzten 7 Tage bleiben erhalten"
echo ""

# Informiere über Neustart
echo "╔═══════════════════════════════════════════╗"
echo "║  Update abgeschlossen!                   ║"
echo "╚═══════════════════════════════════════════╝"
echo ""

# Prüfe ob PM2 installiert ist
if command -v pm2 &> /dev/null; then
    echo "🔄 Starte System mit PM2 neu..."

    # Prüfe ob App in PM2 läuft
    if pm2 list | grep -q "ki-smart-home"; then
        # Stoppe zuerst und gib Port frei
        echo "   Stoppe ki-smart-home..."
        pm2 stop ki-smart-home 2>/dev/null || true
        sleep 2
        
        # Beende alle Prozesse auf Port 8080 (funktioniert auf Linux und macOS)
        echo "   Gebe Port 8080 frei..."
        if command -v fuser &> /dev/null; then
            fuser -k 8080/tcp 2>/dev/null || true
        fi
        # lsof funktioniert auf macOS und Linux
        kill $(lsof -ti:8080) 2>/dev/null || true
        sleep 3
        
        # Lösche alten PM2 Prozess und starte frisch
        echo "   Starte ki-smart-home..."
        pm2 delete ki-smart-home 2>/dev/null || true
        sleep 1
        pm2 start ecosystem.config.js
        pm2 save
        
        # Warte auf Start und prüfe
        sleep 5
        if lsof -ti:8080 > /dev/null 2>&1; then
            echo "✓ System mit PM2 neu gestartet!"
        else
            echo "⚠️  Port 8080 nicht aktiv, versuche erneut..."
            pm2 restart ki-smart-home 2>/dev/null || pm2 start ecosystem.config.js
            sleep 3
        fi
    else
        # Stoppe alte Instanz falls vorhanden
        pkill -f "python.*main.py.*web" || true
        kill $(lsof -ti:8080) 2>/dev/null || true
        sleep 3

        # Starte mit PM2
        pm2 start ecosystem.config.js
        pm2 save
        echo "✓ System mit PM2 gestartet!"
    fi

    echo ""
    echo "📊 PM2 Status:"
    pm2 list
    echo ""
    echo "💡 Nützliche PM2 Befehle:"
    echo "   pm2 logs ki-smart-home     # Logs anzeigen"
    echo "   pm2 monit                  # Monitoring"
    echo "   pm2 restart ki-smart-home  # Nur dieses System neu starten"
    echo "   pm2 stop ki-smart-home     # Nur dieses System stoppen"
    echo ""
    echo "⚠️  Hinweis: Nur 'ki-smart-home' wird neu gestartet, nicht andere PM2-Prozesse!"

    # Setze CURRENT_PORT für spätere Ausgabe
    CURRENT_PORT=$(pm2 jlist | grep -o '"pm_exec_path":"[^"]*web"' | wc -l | xargs -I {} echo 8080)
else
    echo "Das System wird in 3 Sekunden neu gestartet..."
    sleep 3

    # Erkenne aktuellen Port
    echo "🔍 Erkenne aktuellen Port..."
    CURRENT_PORT=$(lsof -ti :8080 2>/dev/null | head -1 | xargs -I {} lsof -Pan -p {} -i 2>/dev/null | grep LISTEN | awk '{print $9}' | cut -d':' -f2 | head -1)
    if [ -z "$CURRENT_PORT" ]; then
        CURRENT_PORT=8080
        echo "  ℹ️  Kein laufender Port gefunden, verwende Standard: $CURRENT_PORT"
    else
        echo "  ✓ Erkannter Port: $CURRENT_PORT"
    fi

    # Finde und stoppe laufende Instanz
    echo "🔄 Stoppe laufende Instanz..."
    pkill -f "python.*main.py.*web" 2>/dev/null || true
    kill $(lsof -ti:$CURRENT_PORT) 2>/dev/null || true
    sleep 3

    # Starte neu mit dem gleichen Port (nutzt start.sh für stabile Startlogik)
    echo "🚀 Starte System neu auf Port $CURRENT_PORT..."
    ./start.sh --restart --port=$CURRENT_PORT || {
        echo "⚠️  System konnte nicht automatisch gestartet werden."
        echo "Bitte manuell starten mit: ./start.sh --port=$CURRENT_PORT"
    }
fi

echo ""
# Zeige korrekten Port an (verwende CURRENT_PORT falls gesetzt, sonst 8080)
DISPLAY_PORT=${CURRENT_PORT:-8080}
echo "🌐 Web-Dashboard: http://localhost:$DISPLAY_PORT"
echo ""
echo "✨ Update erfolgreich abgeschlossen!"
