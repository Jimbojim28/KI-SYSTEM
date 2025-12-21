#!/bin/bash
# Update-Script für KI-SYSTEM Server
# Führt alle notwendigen Schritte aus, um den Server zu aktualisieren

set -e  # Bei Fehler abbrechen

echo "=========================================="
echo "KI-SYSTEM Server Update"
echo "=========================================="
echo ""

# 1. Aktuellen Status prüfen
echo "📋 Schritt 1: Prüfe Git Status..."
git status
echo ""

# 2. Änderungen vom Remote Repository holen
echo "📥 Schritt 2: Hole Änderungen von GitHub..."
git pull origin main
echo ""

# 3. Prüfe ob luftentfeuchten_config.json aktualisiert wurde
echo "🔍 Schritt 3: Prüfe Konfigurationsdatei..."
if grep -q "frost_protection_temperature" data/luftentfeuchten_config.json; then
    echo "✅ frost_protection_temperature gefunden in luftentfeuchten_config.json"
else
    echo "❌ frost_protection_temperature NICHT gefunden!"
    echo "   Bitte prüfe data/luftentfeuchten_config.json manuell"
    exit 1
fi
echo ""

# 4. Starte Web-App neu (nutzt start.sh für stabile Startlogik)
echo "🚀 Schritt 4: Starte Web-App neu..."
./start.sh --restart --port=8080 || {
    echo "❌ Web-App läuft NICHT!"
    echo "   Prüfe logs/webapp.log für Fehler"
    exit 1
}
echo ""

# 5. Teste API-Endpunkt
echo "🧪 Schritt 5: Teste Bathroom API..."
sleep 3
RESPONSE=$(curl -s http://localhost:8080/api/luftentfeuchten/status)

if echo "$RESPONSE" | grep -q "enabled"; then
    echo "✅ API antwortet korrekt"

    # Prüfe ob neue Version läuft (mit frost_protection)
    if grep -q "Frost=" logs/web_app.log 2>/dev/null; then
        echo "✅ Neue Version mit Frostschutz-Funktion aktiv!"
    else
        echo "⚠️  API läuft, aber möglicherweise noch alte Version"
        echo "   Prüfe logs/web_app.log"
    fi
else
    echo "⚠️  API-Response ungewöhnlich:"
    echo "$RESPONSE" | head -5
fi
echo ""

echo "=========================================="
echo "✅ Update abgeschlossen!"
echo "=========================================="
echo ""
echo "Nächste Schritte:"
echo "1. Öffne http://192.168.12.198:8080/luftentfeuchten im Browser"
echo "2. Prüfe ob Sensordaten angezeigt werden"
echo "3. Bei Problemen: tail -f logs/web_app.log"
echo ""
