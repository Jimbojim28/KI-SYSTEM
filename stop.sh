#!/bin/bash
# Stop-Script für KI Smart Home Web-Interface

# Farben
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

PID_FILE="data/webapp.pid"

# Parse Argumente
CLEAN_CACHE=false

for arg in "$@"; do
    case $arg in
        --clean|-c)
            CLEAN_CACHE=true
            ;;
        --help|-h)
            echo "Stop-Script für KI Smart Home"
            echo ""
            echo "Optionen:"
            echo "  --clean / -c     Python-Cache löschen nach Stop"
            echo "  --help / -h      Diese Hilfe anzeigen"
            echo ""
            exit 0
            ;;
    esac
done

echo "╔═══════════════════════════════════════════╗"
echo "║   KI Smart Home - Web-Interface Stop    ║"
echo "╚═══════════════════════════════════════════╝"
echo ""

echo "🛑 Stoppe Web-Interface..."

# Methode 1: Via PID-Datei
if [[ -f "$PID_FILE" ]]; then
    PID=$(cat "$PID_FILE")
    if ps -p $PID > /dev/null 2>&1; then
        echo "Stoppe Prozess (PID: $PID)..."
        kill $PID 2>/dev/null || true
        sleep 2

        # Force kill falls noch läuft
        if ps -p $PID > /dev/null 2>&1; then
            echo "Force-Kill (PID: $PID)..."
            kill -9 $PID 2>/dev/null || true
        fi

        echo -e "${GREEN}✓ Prozess gestoppt${NC}"
    else
        echo -e "${YELLOW}⚠️  Prozess läuft nicht mehr (alte PID-Datei)${NC}"
    fi
    rm -f "$PID_FILE"
fi

# Methode 2: Alle Python main.py web Prozesse
echo "Suche nach laufenden Web-Interface Prozessen..."
PIDS=$(pgrep -f "python.*main.py.*web" 2>/dev/null || true)

if [[ -n "$PIDS" ]]; then
    echo "Gefundene Prozesse: $PIDS"
    pkill -f "python.*main.py.*web" 2>/dev/null || true
    sleep 1

    # Force kill falls noch läuft
    pkill -9 -f "python.*main.py.*web" 2>/dev/null || true

    echo -e "${GREEN}✓ Alle Web-Interface Prozesse gestoppt${NC}"
else
    echo -e "${YELLOW}⚠️  Keine laufenden Prozesse gefunden${NC}"
fi

# Prüfe Ports
for PORT in 5000 8080; do
    if lsof -Pi :$PORT -sTCP:LISTEN -t >/dev/null 2>&1; then
        PID=$(lsof -ti :$PORT)
        echo -e "${YELLOW}⚠️  Port $PORT noch belegt durch PID $PID${NC}"
        echo "Stoppe Prozess..."
        kill -9 $PID 2>/dev/null || true
    fi
done

echo ""
echo -e "${GREEN}✅ Web-Interface vollständig gestoppt${NC}"

# Lösche Python-Cache wenn gewünscht
if [[ "$CLEAN_CACHE" == true ]]; then
    echo ""
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
fi

# Lösche alte Log-Dateien (optional)
if [[ -f "logs/webapp.log" ]]; then
    LOG_SIZE=$(du -h "logs/webapp.log" 2>/dev/null | cut -f1)
    if [[ -n "$LOG_SIZE" ]]; then
        echo ""
        echo "📋 Log-Datei: $LOG_SIZE (logs/webapp.log)"
        
        # Wenn größer als 10MB, warnen
        LOG_SIZE_BYTES=$(stat -f%z "logs/webapp.log" 2>/dev/null || stat -c%s "logs/webapp.log" 2>/dev/null || echo 0)
        if [[ $LOG_SIZE_BYTES -gt 10485760 ]]; then
            echo -e "${YELLOW}⚠️  Log-Datei größer als 10MB!${NC}"
            echo "   Zum Leeren: echo > logs/webapp.log"
        fi
    fi
fi

echo ""
echo "💡 Zum Neustarten:"
echo "   ./start.sh              # Normal starten"
echo "   ./start.sh --clean      # Mit Cache-Löschung starten"
if [[ "$CLEAN_CACHE" == false ]]; then
    echo "   ./stop.sh --clean       # Stop mit Cache-Löschung"
fi
echo ""
