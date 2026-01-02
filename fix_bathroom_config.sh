#!/bin/bash
# Fix Badezimmer-Automatisierung auf produktivem Server
# Aktiviert den Bathroom Collector in der config.yaml

echo "================================================"
echo "Badezimmer-Automatisierung Reparatur"
echo "================================================"
echo ""

SERVER_IP="192.168.12.198"
SERVER_USER="sven"  # Anpassen falls anderer Benutzer
SERVER_PATH="/home/sven/KI-SYSTEM"  # Anpassen falls anderer Pfad

echo "Ziel-Server: $SERVER_IP"
echo "Pfad: $SERVER_PATH"
echo ""

# Prüfe ob SSH verfügbar ist
if command -v ssh &> /dev/null; then
    echo "📡 Versuche Config per SSH zu ändern..."
    
    # Aktiviere bathroom collector in config.yaml
    ssh "$SERVER_USER@$SERVER_IP" "cd $SERVER_PATH && \
        sed -i 's/bathroom:/bathroom:/; s/enabled: false/enabled: true/; s/interval: 60  # Sekunden (1 Minute) - wenn aktiviert/interval: 60  # Sekunden (1 Minute)/' config/config.yaml && \
        echo '✅ Config geändert' && \
        ./restart_server.sh && \
        echo '✅ Server neu gestartet'"
    
    if [ $? -eq 0 ]; then
        echo ""
        echo "✅ Erfolgreich! Badezimmer-Automatisierung aktiviert."
        echo ""
        echo "Teste in 10 Sekunden..."
        sleep 10
        
        curl -s "http://$SERVER_IP:8080/api/luftentfeuchten/status" | python3 -m json.tool
        
        exit 0
    else
        echo "❌ SSH fehlgeschlagen"
    fi
else
    echo "⚠️  SSH nicht verfügbar"
fi

echo ""
echo "================================================"
echo "Alternative: Manuelle Änderung"
echo "================================================"
echo ""
echo "1. Verbinde dich zum Server:"
echo "   ssh $SERVER_USER@$SERVER_IP"
echo ""
echo "2. Bearbeite die Config:"
echo "   cd $SERVER_PATH"
echo "   nano config/config.yaml"
echo ""
echo "3. Ändere diese Zeile:"
echo "   bathroom:"
echo "     enabled: false  →  enabled: true"
echo ""
echo "4. Speichern (Ctrl+O, Enter, Ctrl+X)"
echo ""
echo "5. Server neu starten:"
echo "   ./restart_server.sh"
echo ""
echo "6. Status prüfen:"
echo "   curl http://localhost:8080/api/luftentfeuchten/status"
echo ""
