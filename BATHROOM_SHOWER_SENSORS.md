# Badezimmer-Automatisierung: Duschsensor-Erweiterung

## Überblick

Diese Erweiterung fügt Unterstützung für zusätzliche Sensoren direkt an der Dusche hinzu, um die Duscherkennung zu verbessern und zwischen normalem Feuchtigkeitsanstieg und tatsächlichem Duschen zu unterscheiden.

## Features

### 1. **Zusätzliche Duschsensoren**
- Luftfeuchtigkeitssensor direkt an/in der Dusche
- Temperatursensor an der Dusche (optional)
- Schnellere Erkennung durch direktes Messen an der Quelle

### 2. **Verbesserte Duscherkennung**
- **Steigungsanalyse**: Erkennt schnelle Feuchtigkeitsanstiege (>2% pro Minute)
- **Priorisierte Erkennung**: Duschsensor hat höchste Priorität bei der Erkennung
- **Konfigurierbare Schwellwerte**: Anpassbare Rate-Threshold für verschiedene Umgebungen
- **Multi-Kriterien-Analyse**: Kombiniert Hauptsensor, Duschsensor, Bewegung und Zeit

### 3. **Web-Konfigurationsseite**
- Einfache Auswahl von Home Assistant Sensoren
- Live-Anzeige verfügbarer Sensoren mit aktuellen Werten
- Statistiken über Dusch-Events der letzten 30 Tage
- Anpassbare Erkennungsparameter

### 4. **ML-Training Optimierung**
- Erfasst zusätzliche Daten für besseres Training
- Unterscheidet Duschen von normaler Feuchtigkeitserhöhung
- Speichert Duschsensor-Daten für historische Analyse

## Installation

### 1. Datenbank-Migration

Führe die Migration aus, um die neuen Spalten zur Datenbank hinzuzufügen:

```bash
source venv/bin/activate
python migrate_bathroom_sensors.py
```

### 2. Konfiguration

Die Duschsensoren können auf zwei Arten konfiguriert werden:

#### Option A: Via Web-Interface (empfohlen)

1. Öffne http://localhost:8080
2. Gehe zu **⚙️ Konfiguration → 🚿 Badezimmer**
3. Wähle die Sensoren aus den Dropdowns
4. Passe die Erkennungseinstellungen an
5. Speichere die Konfiguration

#### Option B: Via config.yaml

Bearbeite `config/config.yaml`:

```yaml
collectors:
  bathroom:
    enabled: true
    interval: 60
    shower_sensors:
      humidity_sensor: sensor.dusche_luftfeuchtigkeit
      temperature_sensor: sensor.dusche_temperatur
      enable_rate_detection: true
      rate_threshold: 2.0  # %/Minute
```

### 3. Server neu starten

```bash
./restart_server.sh
```

## Verwendung

### Sensor-Anforderungen

**Dusch-Luftfeuchtigkeitssensor** (wichtig):
- Platzierung: Direkt an oder in der Dusche
- Typ: Home Assistant oder Homey Sensor
- Format: `sensor.dusche_luftfeuchtigkeit`

**Dusch-Temperatursensor** (optional):
- Unterstützt die Erkennung durch Temperaturanstiege
- Format: `sensor.dusche_temperatur`

### Funktionsweise

1. **Normale Erkennung**: Hauptsensor misst Raumluftfeuchtigkeit
2. **Verbesserte Erkennung**: Duschsensor erkennt schnellen Anstieg direkt an der Quelle
3. **Priorität**: Wenn Duschsensor schnellen Anstieg meldet (>2%/min), wird sofort Duschen erkannt
4. **Fallback**: Ohne Duschsensor funktioniert das System wie bisher

### Erkennungs-Logik

```
Duschen erkannt wenn:
1. Duschsensor: Schneller Anstieg (>rate_threshold) + Luftfeuchtigkeit >60%
   ODER
2. Hauptsensor: Hohe Luftfeuchtigkeit (>65%) + (schneller Anstieg ODER Bewegung)
   ODER
3. Hauptsensor: Sehr hohe Luftfeuchtigkeit (>70%)
   ODER
4. Hauptsensor: Schneller Anstieg + Bewegung + Luftfeuchtigkeit >60%
```

## Konfigurationsparameter

| Parameter | Standard | Beschreibung |
|-----------|----------|--------------|
| `humidity_sensor` | - | Entity ID des Dusch-Luftfeuchtigkeitssensors |
| `temperature_sensor` | - | Entity ID des Dusch-Temperatursensors (optional) |
| `enable_rate_detection` | `true` | Aktiviert schnelle Steigungserkennung |
| `rate_threshold` | `2.0` | Schwellwert in %/Minute für schnellen Anstieg |

## Statistiken

Das Web-Interface zeigt automatisch:
- Anzahl erkannter Duschen (letzte 30 Tage)
- Durchschnittliche Duschdauer
- Durchschnittlicher Feuchtigkeitsanstieg

## Vorteile

### Gegenüber einfacher Schwellwert-Erkennung:

✅ **Frühere Erkennung**: Duschsensor reagiert sofort, nicht erst wenn Raumfeuchtigkeit steigt
✅ **Weniger Fehlalarme**: Unterscheidet Duschen von Kochen, Wäschetrocknen, etc.
✅ **Präzisere Steuerung**: Luftentfeuchter startet schneller bei echtem Bedarf
✅ **Besseres ML-Training**: Mehr Daten für genauere Vorhersagen

### Praxisbeispiel:

**Ohne Duschsensor:**
```
09:00 - Dusche startet
09:02 - Raumluftfeuchtigkeit steigt langsam
09:05 - Schwellwert 70% erreicht → Luftentfeuchter startet
```

**Mit Duschsensor:**
```
09:00 - Dusche startet
09:01 - Duschsensor: +8% in 1 Min → Sofort erkannt! 🚿
09:01 - Luftentfeuchter startet
```

## Fehlerbehandlung

### Sensor nicht verfügbar
- System fällt automatisch auf Hauptsensor zurück
- Keine Fehler bei fehlenden/offline Sensoren

### Konfigurationsprobleme
- Überprüfe Entity IDs in Home Assistant
- Logs prüfen: `tail -f logs/webapp.log`
- Test: Manuelle Sensor-Abfrage in Home Assistant

## API-Endpunkte

```bash
# Aktuelle Konfiguration abrufen
GET /api/bathroom/sensors/config

# Konfiguration speichern
POST /api/bathroom/sensors/config
{
  "shower_sensors": {
    "humidity_sensor": "sensor.dusche_luftfeuchtigkeit",
    "temperature_sensor": "sensor.dusche_temperatur",
    "enable_rate_detection": true,
    "rate_threshold": 2.0
  }
}

# Verfügbare Sensoren auflisten
GET /api/bathroom/sensors/available

# Statistiken abrufen
GET /api/bathroom/stats
```

## Troubleshooting

**Problem**: Duschen wird nicht erkannt

**Lösung**:
1. Prüfe ob Sensoren Werte liefern
2. Reduziere `rate_threshold` (z.B. auf 1.5)
3. Überprüfe Sensor-Platzierung (näher an Dusche)

**Problem**: Zu viele Fehlalarme

**Lösung**:
1. Erhöhe `rate_threshold` (z.B. auf 3.0)
2. Prüfe ob Duschsensor zu nah an anderen Feuchtigkeitsquellen ist

## Changelog

### Version 1.0 (2026-01-03)
- ✨ Neue Web-Konfigurationsseite für Duschsensoren
- ✨ Steigungsanalyse für schnelle Erkennung
- ✨ Priorisierte Duschsensor-Erkennung
- ✨ Erweiterte Datenbank für Duschsensor-Daten
- ✨ Statistiken und Analytics im Dashboard
- 📝 Vollständige Dokumentation

## Nächste Schritte

- [ ] Automatisches Schwellwert-Tuning basierend auf historischen Daten
- [ ] Erkennung verschiedener Duschtypen (kurz/lang, warm/kalt)
- [ ] Vorhersage von Duschzeiten für proaktive Steuerung
- [ ] Integration mit anderen Raum-Automatisierungen

## Support

Bei Fragen oder Problemen:
1. Logs prüfen: `logs/webapp.log`
2. GitHub Issues: https://github.com/SHP-ART/KI-SYSTEM/issues
3. Datenbank-Status: Web-Interface → Einstellungen → Datenbank
