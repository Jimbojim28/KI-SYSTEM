#!/bin/bash
# Install-Paket.sh - Installiert alle Dependencies aus requirements.txt
# Einfaches Skript zur Installation aller Python-Pakete

set -e  # Stoppe bei Fehlern

echo "╔═══════════════════════════════════════════╗"
echo "║   KI-System - Paket-Installation         ║"
echo "╚═══════════════════════════════════════════╝"
echo ""

# ===== PRÜFE PYTHON =====
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 nicht gefunden!"
    echo "Bitte installiere Python 3.8 oder höher: https://www.python.org/downloads/"
    exit 1
fi

python_version=$(python3 --version 2>&1 | awk '{print $2}')
echo "✓ Python Version: $python_version"

# ===== PRÜFE PIP =====
if ! python3 -m pip --version &> /dev/null; then
    echo "⚠️  pip nicht gefunden - versuche pip zu installieren..."
    python3 -m ensurepip --upgrade 2>/dev/null || {
        echo "❌ pip konnte nicht installiert werden"
        echo "Bitte installiere pip manuell:"
        echo "  macOS/Linux: python3 -m ensurepip --upgrade"
        echo "  Ubuntu/Debian: sudo apt-get install python3-pip"
        exit 1
    }
    echo "✓ pip installiert"
else
    echo "✓ pip verfügbar"
fi

# ===== PRÜFE REQUIREMENTS.TXT =====
if [ ! -f "requirements.txt" ]; then
    echo "❌ requirements.txt nicht gefunden!"
    echo "Bitte führe dieses Skript im Projektverzeichnis aus."
    exit 1
fi
echo "✓ requirements.txt gefunden"

# ===== VIRTUAL ENVIRONMENT (OPTIONAL) =====
USE_VENV=false
if [ -d "venv" ]; then
    echo ""
    echo "📦 Virtual Environment gefunden"
    read -p "Virtual Environment verwenden? (j/n) [Standard: j]: " use_venv
    use_venv=${use_venv:-j}
    
    if [[ "$use_venv" =~ ^[Jj]$ ]]; then
        USE_VENV=true
        if [ -f "venv/bin/activate" ]; then
            echo "🔧 Aktiviere Virtual Environment..."
            source venv/bin/activate
            echo "✓ Virtual Environment aktiviert"
        else
            echo "⚠️  venv/bin/activate nicht gefunden - erstelle Virtual Environment neu..."
            rm -rf venv
            python3 -m venv venv
            source venv/bin/activate
            echo "✓ Virtual Environment neu erstellt und aktiviert"
        fi
    fi
else
    echo ""
    read -p "Virtual Environment erstellen? (j/n) [Standard: j]: " create_venv
    create_venv=${create_venv:-j}
    
    if [[ "$create_venv" =~ ^[Jj]$ ]]; then
        echo "📦 Erstelle Virtual Environment..."
        python3 -m venv venv
        source venv/bin/activate
        echo "✓ Virtual Environment erstellt und aktiviert"
        USE_VENV=true
    fi
fi

# ===== UPGRADE PIP =====
echo ""
echo "⬆️  Aktualisiere pip..."
python3 -m pip install --upgrade pip -q
echo "✓ pip aktualisiert"

# ===== INSTALLIERE DEPENDENCIES =====
echo ""
echo "📦 Installiere Pakete aus requirements.txt..."
echo "   (Dies kann einige Minuten dauern...)"
echo ""

if python3 -m pip install -r requirements.txt; then
    echo ""
    echo "✓ Alle Pakete erfolgreich installiert!"
else
    echo ""
    echo "❌ Fehler beim Installieren der Pakete!"
    echo ""
    echo "Mögliche Lösungen:"
    echo "  1. Prüfe deine Internetverbindung"
    echo "  2. Prüfe ob alle Pakete in requirements.txt korrekt sind"
    echo "  3. Versuche es mit: pip install --upgrade pip"
    exit 1
fi

# ===== ZUSAMMENFASSUNG =====
echo ""
echo "╔═══════════════════════════════════════════╗"
echo "║   Installation erfolgreich abgeschlossen!║"
echo "╚═══════════════════════════════════════════╝"
echo ""

if [ "$USE_VENV" = true ]; then
    echo "📝 WICHTIG: Virtual Environment ist aktiv"
    echo ""
    echo "   Um das Virtual Environment später zu aktivieren:"
    echo "   source venv/bin/activate"
    echo ""
fi

echo "📋 Installierte Pakete:"
python3 -m pip list | grep -E "(loguru|flask|scikit-learn|numpy|pandas|astral)" || true

echo ""
echo "✅ Fertig! Du kannst jetzt das System starten."
echo ""

