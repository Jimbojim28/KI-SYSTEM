# Update-System für KI-SYSTEM

## Übersicht

Es gibt zwei Update-Scripts für unterschiedliche Umgebungen:

### 1. `update_production.sh` - Für Produktions-Server mit PM2
**Empfohlen für:** 192.168.12.198 (Produktions-Server)

```bash
cd /var/www/KI-SYSTEM
./update_production.sh
```

**Was macht es:**
- ✅ Erstellt automatisch Datenbank-Backup
- ✅ Holt neuesten Code von GitHub (`git pull`)
- ✅ **Löscht Python-Cache** (.pyc und __pycache__) - verhindert alte Code-Probleme
- ✅ Führt Datenbank-Migrationen automatisch aus
- ✅ Startet PM2 mit `--update-env` neu (lädt neue Umgebungsvariablen)
- ✅ Testet API-Endpunkte nach Update
- ✅ Zeigt PM2-Status an

### 2. `update_server.sh` - Für Entwicklung/Systeme ohne PM2
**Empfohlen für:** Lokale Entwicklung, Test-Server

```bash
./update_server.sh
```

**Was macht es:**
- ✅ Holt neuesten Code von GitHub
- ✅ **Löscht Python-Cache** (.pyc und __pycache__)
- ✅ Startet Server mit `./start.sh` neu
- ✅ Testet API-Endpunkte

## Warum Python-Cache löschen?

**Problem:** Python erstellt `.pyc`-Dateien (compiled bytecode) und `__pycache__`-Verzeichnisse. Nach `git pull` kann Gunicorn/Python alten gecachten Code laden statt des neuen Codes.

**Lösung:** Beide Scripts löschen automatisch:
```bash
find . -type f -name "*.pyc" -delete
find . -type d -name "__pycache__" -exec rm -rf {} +
```

**Alternative:** `PYTHONDONTWRITEBYTECODE=1` in `ecosystem.config.js` verhindert `.pyc`-Erstellung (bereits aktiv).

## Manuelles Update (falls Scripts nicht funktionieren)

```bash
# 1. Code aktualisieren
git pull origin main

# 2. Python-Cache löschen (WICHTIG!)
find . -type f -name "*.pyc" -delete
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null

# 3. Datenbank-Migrationen (falls vorhanden)
python3 migrate_bathroom_sensors.py

# 4a. Mit PM2 (Produktions-Server)
pm2 stop ki-smart-home
pm2 start ecosystem.config.js --update-env

# 4b. Ohne PM2 (Entwicklung)
./start.sh --restart
```

## Häufige Probleme

### Problem: API-Endpunkt gibt 404 nach Update
**Ursache:** Python-Cache nicht gelöscht - alter Code im Speicher

**Lösung:**
```bash
pm2 stop ki-smart-home
find . -name "*.pyc" -delete
find . -type d -name "__pycache__" -exec rm -rf {} +
pm2 start ecosystem.config.js --update-env
```

### Problem: Server startet nicht nach Update
**Lösung:** Logs prüfen
```bash
# PM2-Logs
pm2 logs ki-smart-home --lines 50

# Gunicorn-Logs
tail -50 logs/gunicorn-error.log

# App-Logs
tail -50 logs/web_app.log
```

### Problem: Neue Blueprints werden nicht geladen
**Ursache:** `__pycache__` in `src/web/blueprints/` nicht gelöscht

**Lösung:**
```bash
rm -rf src/web/blueprints/__pycache__
pm2 restart ki-smart-home
```

## Best Practices

1. **Vor jedem Update:** Prüfe PM2-Status
   ```bash
   pm2 list
   ```

2. **Nach jedem Update:** Prüfe Logs für Fehler
   ```bash
   pm2 logs ki-smart-home --lines 20 --nostream
   ```

3. **Bei kritischen Updates:** Erstelle manuell Backup
   ```bash
   cp data/ki_system.db data/ki_system.db.backup_manual_$(date +%Y%m%d_%H%M%S)
   ```

4. **Produktions-Updates:** Immer `update_production.sh` verwenden!

## Automatisierung

### Cron-Job für automatische Updates (optional)
```bash
# Täglich um 3:00 Uhr
0 3 * * * cd /var/www/KI-SYSTEM && ./update_production.sh >> logs/auto-update.log 2>&1
```

**Vorsicht:** Nur bei stabilen Releases empfohlen!

## Rollback bei Problemen

```bash
# 1. Git auf vorherige Version zurücksetzen
git log --oneline -10  # Zeige letzte 10 Commits
git reset --hard <commit-hash>

# 2. Cache löschen
find . -name "*.pyc" -delete
find . -type d -name "__pycache__" -exec rm -rf {} +

# 3. Neustart
pm2 restart ki-smart-home

# 4. Datenbank wiederherstellen (falls nötig)
cp data/ki_system.db.backup_XXXXXX data/ki_system.db
```

## Zusammenfassung

✅ **Immer Python-Cache nach Update löschen**  
✅ **Für Produktions-Server: `update_production.sh`**  
✅ **Nach Update: Logs prüfen**  
✅ **Bei Problemen: Cache löschen und neu starten**
