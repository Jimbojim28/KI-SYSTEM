#!/bin/bash
# Restart-Script für KI Smart Home Web-Interface
# Stoppt den Server, räumt auf und startet neu

# Farben
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo "╔═══════════════════════════════════════════╗"
echo "║   KI Smart Home - Restart mit Cleanup   ║"
echo "╚═══════════════════════════════════════════╝"
echo ""

# Parse Argumente
CLEAN_CACHE=true  # Default: Cache löschen bei Restart
DEBUG_MODE=false
PORT=""

for arg in "$@"; do
    case $arg in
        --no-clean)
            CLEAN_CACHE=false
            ;;
        --debug|-d)
            DEBUG_MODE=true
            ;;
        --port=*)
            PORT="${arg#*=}"
            ;;
        --help|-h)
            echo "Restart-Script für KI Smart Home"
            echo ""
            echo "Stoppt den Server, räumt auf und startet neu."
            echo "Standard: Cache wird gelöscht (empfohlen nach Updates)"
            echo ""
            echo "Optionen:"
            echo "  --no-clean       Cache NICHT löschen"
            echo "  --debug / -d     Im Debug-Modus starten"
            echo "  --port=XXXX      Port festlegen"
            echo "  --help / -h      Diese Hilfe anzeigen"
            echo ""
            echo "Beispiele:"
            echo "  ./restart.sh               # Restart mit Cache-Löschung"
            echo "  ./restart.sh --no-clean    # Restart ohne Cache-Löschung"
            echo "  ./restart.sh --debug       # Restart im Debug-Modus"
            echo ""
            exit 0
            ;;
    esac
done

# Schritt 1: Server stoppen
echo -e "${BLUE}Schritt 1/3: Server stoppen${NC}"
if [[ "$CLEAN_CACHE" == true ]]; then
    ./stop.sh --clean
else
    ./stop.sh
fi

echo ""

# Schritt 2: Zusätzliches Cleanup (optional)
echo -e "${BLUE}Schritt 2/3: System-Cleanup${NC}"

# Prüfe auf verwaiste .pid Dateien
if ls data/*.pid 1> /dev/null 2>&1; then
    echo "   Entferne alte PID-Dateien..."
    rm -f data/*.pid
    echo -e "${GREEN}   ✓ PID-Dateien entfernt${NC}"
fi

# Prüfe auf .pyc Dateien (falls --clean nicht verwendet wurde)
if [[ "$CLEAN_CACHE" == false ]]; then
    PYC_COUNT=$(find . -type f -name "*.pyc" 2>/dev/null | wc -l | tr -d ' ')
    if [[ $PYC_COUNT -gt 0 ]]; then
        echo -e "${YELLOW}   ℹ️  $PYC_COUNT .pyc Dateien gefunden (verwende --clean zum Löschen)${NC}"
    fi
fi

echo -e "${GREEN}   ✓ Cleanup abgeschlossen${NC}"
echo ""

# Schritt 3: Server starten
echo -e "${BLUE}Schritt 3/3: Server starten${NC}"

START_ARGS=""
if [[ "$DEBUG_MODE" == true ]]; then
    START_ARGS="$START_ARGS --debug"
fi
if [[ -n "$PORT" ]]; then
    START_ARGS="$START_ARGS --port=$PORT"
fi

# Cache wird nicht explizit übergeben, da wir schon in stop.sh geräumt haben
./start.sh $START_ARGS

