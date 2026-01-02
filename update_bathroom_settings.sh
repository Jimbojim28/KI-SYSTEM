#!/bin/bash
# Aktualisiere Server mit neuer Badezimmer-Collector-Funktion in Settings

echo "================================================"
echo "🔄 Server Update - Badezimmer-Collector Settings"
echo "================================================"
echo ""

SERVER_IP="192.168.12.198"
SERVER_URL="http://$SERVER_IP:8080"

echo "1️⃣ Triggere Git Pull auf Server..."
curl -s -X POST "$SERVER_URL/api/system/update" | python3 -m json.tool
echo ""

echo "Warte 15 Sekunden bis Update abgeschlossen ist..."
sleep 15
echo ""

echo "2️⃣ Server startet neu..."
curl -s -X POST "$SERVER_URL/api/system/restart" | python3 -m json.tool
echo ""

echo "Warte 10 Sekunden bis Server neu gestartet ist..."
sleep 10
echo ""

echo "3️⃣ Teste ob Server läuft..."
STATUS=$(curl -s "$SERVER_URL/api/health" | python3 -c "import sys, json; print(json.load(sys.stdin).get('status', 'error'))" 2>/dev/null)

if [ "$STATUS" = "ok" ]; then
    echo "✅ Server läuft!"
    echo ""
    echo "================================================"
    echo "✅ Update erfolgreich!"
    echo "================================================"
    echo ""
    echo "📋 Nächste Schritte:"
    echo ""
    echo "1. Öffne die Settings-Seite:"
    echo "   $SERVER_URL/settings"
    echo ""
    echo "2. Scrolle zu 'Datensammlung'"
    echo ""
    echo "3. Aktiviere die Checkbox '🚿 Badezimmer Daten'"
    echo ""
    echo "4. Klicke auf 'Datensammlung speichern'"
    echo ""
    echo "5. Der Server startet automatisch neu!"
    echo ""
    echo "6. Nach dem Neustart läuft die Badezimmer-Automatisierung"
    echo ""
else
    echo "❌ Server antwortet nicht! Bitte manuell prüfen."
    exit 1
fi
