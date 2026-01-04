#!/bin/bash
# Start-Script für KI Smart Home Web-Interface
# Startet oder startet neu die Web-App

set -e

# Konfiguration
# Port 8080 statt 5000 wegen macOS AirPlay/AirTunes Konflikt
DEFAULT_PORT=8080
DEFAULT_HOST="0.0.0.0"
LOG_FILE="logs/webapp.log"
PID_FILE="data/webapp.pid"

# Farben für Output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo "╔═══════════════════════════════════════════╗"
echo "║   KI Smart Home - Web-Interface Start   ║"
echo "╚═══════════════════════════════════════════╝"
echo ""
echo "Optionen:"
echo "  --restart / -r     Neu starten (stoppt laufende Instanz)"
echo "  --clean / -c       Python-Cache löschen vor Start"
echo "  --debug / -d       Debug-Modus mit Auto-Reload"
echo "  --port=XXXX        Port festlegen (default: 8080)"
echo "  --host=X.X.X.X     Host festlegen (default: 0.0.0.0)"
echo ""

# Parse Argumente
PORT=$DEFAULT_PORT
HOST=$DEFAULT_HOST
FORCE_RESTART=false
DEBUG_MODE=false
CLEAN_CACHE=false

for arg in "$@"; do
    case $arg in
        --restart|-r)
            FORCE_RESTART=true
            ;;
        --debug|-d)
            DEBUG_MODE=true
            ;;
        --clean|-c)
            CLEAN_CACHE=true
            ;;
        --port=*)
            PORT="${arg#*=}"
            ;;
        --host=*)
            HOST="${arg#*=}"
            ;;
        *)
            # Versuche als Port zu interpretieren (nur Zahlen)
            if [[ "$arg" =~ ^[0-9]+$ ]]; then
                PORT=$arg
            fi
            ;;
    esac
done

# Prüfe ob Virtual Environment aktiviert ist
if [[ -z "$VIRTUAL_ENV" ]] && [[ -d "venv" ]]; then
    echo -e "${YELLOW}⚠️  Virtual Environment nicht aktiviert${NC}"
    echo "Aktiviere Virtual Environment..."
    source venv/bin/activate
    echo -e "${GREEN}✓ Virtual Environment aktiviert${NC}"
    echo ""
fi

# Erstelle logs/ Verzeichnis falls nicht vorhanden
mkdir -p logs
mkdir -p data

# Funktion: Lösche Python-Cache
clean_python_cache() {
    echo "🧹 Lösche Python-Cache..."
    
    # Zähle Dateien vor dem Löschen
    PYC_COUNT=$(find . -type f -name "*.pyc" 2>/dev/null | wc -l | tr -d ' ')
    CACHE_COUNT=$(find . -type d -name "__pycache__" 2>/dev/null | wc -l | tr -d ' ')
    
    if [[ $PYC_COUNT -gt 0 ]] || [[ $CACHE_COUNT -gt 0 ]]; then
        echo "   Gefunden: $PYC_COUNT .pyc Dateien, $CACHE_COUNT __pycache__ Verzeichnisse"
        
        # Lösche .pyc Dateien
        find . -type f -name "*.pyc" -delete 2>/dev/null || true
        
        # Lösche __pycache__ Verzeichnisse
        find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
        
        echo -e "${GREEN}✓ Python-Cache gelöscht${NC}"
    else
        echo "   Kein Cache gefunden (bereits sauber)"
    fi
    echo ""
}

# Funktion: Prüfe ob Port belegt ist
check_port() {
    if lsof -Pi :$1 -sTCP:LISTEN -t >/dev/null 2>&1; then
        return 0  # Port ist belegt
    else
        return 1  # Port ist frei
    fi
}

# Funktion: Stoppe laufende Instanz
stop_instance() {
    echo "🛑 Stoppe laufende Instanz..."

    # Versuche via PID-Datei zu stoppen
    if [[ -f "$PID_FILE" ]]; then
        OLD_PID=$(cat "$PID_FILE")
        if ps -p $OLD_PID > /dev/null 2>&1; then
            kill $OLD_PID 2>/dev/null || true
            sleep 2

            # Force kill falls noch läuft
            if ps -p $OLD_PID > /dev/null 2>&1; then
                kill -9 $OLD_PID 2>/dev/null || true
            fi
            echo -e "${GREEN}✓ Alte Instanz gestoppt (PID: $OLD_PID)${NC}"
        fi
        rm -f "$PID_FILE"
    fi

    # Stoppe alle Python-Prozesse die main.py web ausführen
    pkill -f "python.*main.py.*web" 2>/dev/null || true

    # Warte kurz
    sleep 1

    # Prüfe ob Port noch belegt
    if check_port $PORT; then
        echo -e "${YELLOW}⚠️  Port $PORT noch belegt, versuche Force-Kill...${NC}"
        # Finde Prozess der Port belegt und killen
        PID=$(lsof -ti :$PORT)
        if [[ -n "$PID" ]]; then
            kill -9 $PID 2>/dev/null || true
            sleep 1
        fi
    fi

    echo -e "${GREEN}✓ Cleanup abgeschlossen${NC}"
}

# Funktion: Starte Web-App
start_webapp() {
    echo ""
    echo "🚀 Starte Web-Interface..."
    echo "   Host: $HOST"
    echo "   Port: $PORT"
    echo "   Logs: $LOG_FILE"
    if [[ "$DEBUG_MODE" == true ]]; then
        echo -e "   ${YELLOW}Debug-Modus: AKTIV (Auto-Reload bei Code-Änderungen)${NC}"
    fi
    if [[ "$CLEAN_CACHE" == true ]]; then
        echo -e "   ${YELLOW}Cache: Wird vor Start gelöscht${NC}"
    fi
    echo ""

    # Lösche Cache wenn gewünscht
    if [[ "$CLEAN_CACHE" == true ]]; then
        clean_python_cache
    fi

    # Debug-Flag für Python
    DEBUG_FLAG=""
    if [[ "$DEBUG_MODE" == true ]]; then
        DEBUG_FLAG="--debug"
    fi

    # Starte im Hintergrund mit nohup
    nohup python3 main.py web --host $HOST --port $PORT $DEBUG_FLAG > "$LOG_FILE" 2>&1 &

    # Speichere PID
    NEW_PID=$!
    echo $NEW_PID > "$PID_FILE"

    # Warte auf Server-Start mit Fortschrittsanzeige
    echo -n "⏳ Warte auf Server-Start"
    MAX_WAIT=20
    WAITED=0
    
    while [ $WAITED -lt $MAX_WAIT ]; do
        if check_port $PORT; then
            echo "" # Neue Zeile nach Punkten
            break
        fi
        
        # Prüfe ob Prozess noch läuft
        if ! ps -p $NEW_PID > /dev/null 2>&1; then
            echo ""
            echo -e "${RED}❌ Prozess ist vorzeitig beendet!${NC}"
            echo ""
            echo "Letzte Log-Einträge:"
            tail -30 "$LOG_FILE"
            rm -f "$PID_FILE"
            return 1
        fi
        
        echo -n "."
        sleep 1
        WAITED=$((WAITED + 1))
    done

    # Prüfe ob erfolgreich gestartet
    if check_port $PORT; then
        PID=$(cat "$PID_FILE")
        echo -e "${GREEN}✅ Web-Interface erfolgreich gestartet!${NC}"
        echo "   Start-Zeit: ${WAITED}s"
        echo ""
        echo "╔═══════════════════════════════════════════╗"
        echo "║             Server läuft!                ║"
        echo "╚═══════════════════════════════════════════╝"
        echo ""
        echo -e "${BLUE}🌐 Web-Dashboard:${NC} http://localhost:$PORT"
        if [[ "$HOST" != "127.0.0.1" ]] && [[ "$HOST" != "localhost" ]]; then
            echo -e "${BLUE}🌍 Netzwerk:${NC} http://$HOST:$PORT"
        fi
        echo ""
        echo "📊 Status:"
        echo "   PID: $PID"
        echo "   Port: $PORT"
        echo "   Host: $HOST"
        if [[ "$DEBUG_MODE" == true ]]; then
            echo -e "   ${YELLOW}Debug: AKTIV (Auto-Reload)${NC}"
        fi
        echo ""
        echo "💡 Nützliche Befehle:"
        echo "   tail -f $LOG_FILE          # Logs live ansehen"
        echo "   ./start.sh --restart         # Neu starten"
        echo "   ./start.sh --clean           # Mit Cache-Löschung starten"
        echo "   ./start.sh --debug           # Mit Auto-Reload starten"
        echo "   ./stop.sh                    # Stoppen"
        echo "   ps -p $PID                   # Prozess-Status prüfen"
        echo ""
        return 0
    else
        echo -e "${RED}❌ Start fehlgeschlagen!${NC}"
        echo ""
        echo "Letzte Log-Einträge:"
        tail -20 "$LOG_FILE"
        echo ""
        echo -e "${YELLOW}💡 Tipps zur Fehlersuche:${NC}"
        echo "   1. Prüfe Logs: tail -f $LOG_FILE"
        echo "   2. Prüfe Python-Fehler: python3 main.py web"
        echo "   3. Prüfe Dependencies: pip install -r requirements.txt"
        echo "   4. Prüfe .env Datei: ls -la .env"
        echo ""
        rm -f "$PID_FILE"
        return 1
    fi
}

# Hauptlogik
echo "🔍 Prüfe aktuellen Status..."

# Lösche Cache bei --clean auch wenn Server nicht neu startet
if [[ "$CLEAN_CACHE" == true ]] && [[ "$FORCE_RESTART" == false ]]; then
    clean_python_cache
fi

if check_port $PORT; then
    PID=$(lsof -ti :$PORT)
    echo -e "${YELLOW}⚠️  Web-Interface läuft bereits!${NC}"
    echo "   PID: $PID"
    echo "   Port: $PORT"
    echo ""

    if [[ "$FORCE_RESTART" == true ]]; then
        echo "Option --restart erkannt, starte neu..."
        stop_instance
        start_webapp
    else
        echo "Optionen:"
        echo "   1. Neu starten: ./start.sh --restart"
        echo "   2. Stoppen: ./stop.sh"
        echo "   3. Status prüfen: lsof -i :$PORT"
        echo ""
        echo -e "${BLUE}🌐 Web-Dashboard:${NC} http://localhost:$PORT"
        echo ""

        # Frage ob neu starten
        read -p "Möchtest du neu starten? (j/n): " -n 1 -r
        echo ""
        if [[ $REPLY =~ ^[JjYy]$ ]]; then
            stop_instance
            start_webapp
        else
            echo "Vorgang abgebrochen."
            exit 0
        fi
    fi
else
    echo -e "${GREEN}✓ Port $PORT ist frei${NC}"
    start_webapp
fi
