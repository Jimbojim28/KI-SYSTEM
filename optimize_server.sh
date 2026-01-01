#!/bin/bash
# Optimierungs-Script für KI-System auf dem Server
# Führt Datenbank-Cleanup und -Optimierung durch

echo "🔧 KI-System Optimierung startet..."

cd /var/www/KI-SYSTEM || exit 1

# Aktiviere Virtual Environment
source venv/bin/activate

echo ""
echo "1️⃣ Datenbank-Status vor Optimierung:"
python3 check_database.py status 2>/dev/null || echo "Status-Check nicht verfügbar"

echo ""
echo "2️⃣ Lösche alte Daten (älter als 30 Tage)..."
python3 check_database.py cleanup 30

echo ""
echo "3️⃣ Optimiere Datenbank (VACUUM)..."
python3 check_database.py optimize

echo ""
echo "4️⃣ Datenbank-Status nach Optimierung:"
python3 check_database.py status 2>/dev/null || echo "Status-Check nicht verfügbar"

echo ""
echo "5️⃣ Installiere neue Dependencies (gunicorn, gevent)..."
pip install gunicorn==21.2.0 gevent==23.9.1 -q

echo ""
echo "6️⃣ Neustart des Servers mit Gunicorn..."
pm2 stop ki-smart-home 2>/dev/null || true
pm2 delete ki-smart-home 2>/dev/null || true
pm2 start ecosystem.config.js
pm2 save

echo ""
echo "✅ Optimierung abgeschlossen!"
echo ""
echo "📊 System-Status:"
pm2 status
echo ""
echo "💾 Speicher-Status:"
free -h
echo ""
echo "📝 Prüfe Logs mit: pm2 logs ki-smart-home"
