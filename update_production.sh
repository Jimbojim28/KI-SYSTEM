#!/bin/bash
# Production Server Update-Script für KI-SYSTEM
# Für Server mit PM2 (wie 192.168.12.198)

set -e  # Bei Fehler abbrechen

echo "=========================================="
echo "KI-SYSTEM Production Update"
echo "=========================================="
echo ""

# 1. Aktuellen Status prüfen
echo "📋 Schritt 1: Prüfe Git Status..."
git status
echo ""

# 2. Sichere wichtige Daten
echo "💾 Schritt 2: Backup Datenbank..."
if [ -f "data/ki_system.db" ]; then
    BACKUP_FILE="data/ki_system.db.backup_$(date +%Y%m%d_%H%M%S)"
    cp data/ki_system.db "$BACKUP_FILE"
    echo "✅ Backup erstellt: $BACKUP_FILE"
else
    echo "⚠️  Keine Datenbank gefunden"
fi
echo ""

# 3. Änderungen vom Remote Repository holen
echo "📥 Schritt 3: Hole Änderungen von GitHub..."
git pull origin main
echo ""

# 4. Lösche Python-Cache (WICHTIG!)
echo "🧹 Schritt 4: Lösche Python-Cache..."
echo "   Entferne .pyc Dateien..."
find . -type f -name "*.pyc" -delete 2>/dev/null || true
echo "   Entferne __pycache__ Verzeichnisse..."
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
echo "✅ Python-Cache gelöscht"
echo ""

# 5. Führe Migrationen aus (falls vorhanden)
echo "🔄 Schritt 5: Prüfe auf Datenbank-Migrationen..."
if [ -f "migrate_bathroom_sensors.py" ]; then
    echo "   Führe migrate_bathroom_sensors.py aus..."
    python3 migrate_bathroom_sensors.py || echo "⚠️  Migration bereits durchgeführt oder nicht nötig"
fi
echo ""

# 6. PM2 neu starten
echo "🚀 Schritt 6: Starte PM2 neu..."
if command -v pm2 &> /dev/null; then
    # Stoppe den Prozess
    pm2 stop ki-smart-home || echo "Prozess war nicht gestartet"
    
    # Warte kurz
    sleep 2
    
    # Starte mit --update-env um neue Umgebungsvariablen zu laden
    pm2 start ecosystem.config.js --update-env
    
    echo "✅ PM2 neugestartet"
else
    echo "❌ PM2 nicht gefunden! Verwende ./start.sh stattdessen"
    ./start.sh --restart
fi
echo ""

# 7. Warte auf Server-Start
echo "⏳ Warte 15 Sekunden auf Server-Start..."
sleep 15
echo ""

# 8. Teste API-Endpunkte
echo "🧪 Schritt 7: Teste API-Endpunkte..."

# Teste Bathroom API
echo "   Teste Bathroom Sensors API..."
RESPONSE=$(curl -s http://localhost:8080/api/bathroom/sensors/available 2>&1)
if echo "$RESPONSE" | grep -q "humidity_sensors\|temperature_sensors"; then
    echo "   ✅ Bathroom API funktioniert"
else
    echo "   ⚠️  Bathroom API: $RESPONSE" | head -3
fi

# Teste Haupt-API
echo "   Teste Luftentfeuchten API..."
RESPONSE=$(curl -s http://localhost:8080/api/luftentfeuchten/status 2>&1)
if echo "$RESPONSE" | grep -q "enabled"; then
    echo "   ✅ Luftentfeuchten API funktioniert"
else
    echo "   ⚠️  Luftentfeuchten API antwortet nicht wie erwartet"
fi
echo ""

# 9. PM2 Status anzeigen
echo "📊 Schritt 8: PM2 Status..."
if command -v pm2 &> /dev/null; then
    pm2 list | grep ki-smart
fi
echo ""

echo "=========================================="
echo "✅ Update abgeschlossen!"
echo "=========================================="
echo ""
echo "Wichtige Befehle:"
echo "  pm2 logs ki-smart-home         - Zeige Logs"
echo "  pm2 restart ki-smart-home      - Neustart"
echo "  pm2 monit                      - Monitoring"
echo ""
