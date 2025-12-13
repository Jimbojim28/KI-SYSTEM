# Changelog

Alle wichtigen Änderungen am Projekt werden hier dokumentiert.

## [1.0.0] - 2025-12-13

### Hinzugefügt
- **Zentralisierte Sensor-Verwaltung**
  - Neue Logik zur Zusammenführung von Sensoren aus Homey und Home Assistant
  - "Ignorieren"-Funktion für Sensoren in der Raumverwaltung (UI)
  - Vermeidung von doppelten Sensoren (z.B. wenn Homey Sensoren an HA weiterleitet)
- **Erweiterte Raumverwaltung**
  - Checkboxen zum Ignorieren von Fenstersensoren
  - Verbesserte Übersicht der zugeordneten Geräte
- **UI Verbesserungen**
  - Neue Sektion "Verfügbare Sensoren verwalten" im Raum-Edit-Modal
  - Konsistente Darstellung von ignorierten Geräten

### Geändert
- Refactoring der Sensor-Abfrage (`sensor_utils.py`) für bessere Wartbarkeit
- Optimierung der API-Endpunkte für Raum- und Sensordaten

## [0.9.5] - 2025-11-11

### Hinzugefügt
- **Frostschutz-Funktion für Badezimmer-Automation**
  - Bei offenem Fenster: Heizung wird auf 12°C Frostschutztemperatur gestellt (statt komplett deaktiviert)
  - Luftentfeuchter wird weiterhin deaktiviert für Energieeinsparung
  - Konfigurierbare Frostschutztemperatur (`frost_protection_temperature` in Config)
  - Verhindert Frostschäden an Rohren und Leitungen
  - Automatische Aktivierung basierend auf Fenstersensor-Status
- **Server Update Script** (`update_server.sh`)
  - Automatisiertes Deployment-Script für Produktions-Server
  - Führt `git pull`, stoppt/startet Web-App, testet APIs
  - Validiert Konfiguration und neue Version
  - Verbesserte Wartbarkeit und schnellere Updates

### Geändert
- **Badezimmer-Automation aktiviert** (enabled: true in Config)
- Verbesserte Energie-Effizienz: Intelligente Heizungssteuerung bei offenem Fenster
- Erweiterte Log-Ausgaben zeigen jetzt Target- und Frostschutztemperatur

### Behoben
- Badezimmer-Automation Sensor-Daten werden korrekt angezeigt
- Web-Interface zeigt Live-Status für Luftfeuchtigkeit und Temperatur
- Konfigurationsdateien werden bei Server-Updates korrekt aktualisiert

### Technisch
- `BathroomAutomation.__init__()`: Neuer Parameter `frost_protection_temp`
- `BathroomAutomation.process()`: Verbesserte Fenster-Logik in Zeilen 94-125
- `update_server.sh`: Production-ready Deployment-Script

---

## [0.9.0] - 2025-11-09

### Hinzugefügt
- **ML Auto-Trainer**: Automatisches Training der ML-Modelle täglich um 2:00 Uhr
  - Prüft automatisch ob genug Daten vorhanden sind (100 Lighting Events, 200 Temperature Readings, min. 3 Tage)
  - Trainiert Lighting Model und Temperature Model automatisch
  - Speichert Trainingshistorie in Datenbank
  - Verhindert doppeltes Training innerhalb 24 Stunden
- **ML Training Status Dashboard** in Settings
  - Live-Status für Lighting Model, Temperature Model und Auto-Trainer
  - Farbliche Status-Indikatoren (Gelb/Blau/Grün/Rot)
  - Daten-Fortschrittsanzeige (X / Required Events/Readings)
  - Manueller Training-Trigger Button
  - Training History Viewer mit Metriken
  - Konfigurierbare Trainingszeit
- **Kombinierte Automation-Seite** mit Tab-Navigation
  - Tab 1: Regeln & Szenen (moderner Regel-Builder)
  - Tab 2: Geräte & System (Geräte-Verwaltung, System-Automatisierungen)
  - Beide Funktionen unter einer URL vereint
- **Indoor-Sensor Konfiguration**
  - Auswahl welche Temperatur-Sensoren für Indoor-Durchschnitt verwendet werden
  - Auswahl welche Luftfeuchtigkeit-Sensoren verwendet werden
  - "Alle auswählen/abwählen" Buttons
  - Live-Anzeige der aktuellen Sensor-Werte
- **Background Data Collection**
  - Sammelt alle 5 Minuten Sensor-Daten
  - Berechnet Indoor-Durchschnittswerte aus ausgewählten Sensoren
  - Läuft automatisch im Hintergrund
- **Analytics Dashboard**
  - Zeitreihen-Visualisierung für Temperatur, Luftfeuchtigkeit, Energie
  - Geräte-Aktivitäts-Historie
  - Wetter-Daten Integration
  - Interaktive Charts mit Zeit-Filter (24h, 7d, 30d)
- **Bathroom Optimizer** (Background-Prozess)
  - Analysiert Badezimmer-Nutzungsmuster
  - Optimiert Heizung basierend auf Nutzungszeiten
  - Läuft täglich um 3:00 Uhr
- **Neue API Endpoints**
  - `/api/ml/status` - ML Training Status
  - `/api/ml/train` - Manuelles Training triggern
  - `/api/ml/training-history` - Trainingshistorie abrufen
  - `/api/sensors/config` - Sensor-Konfiguration
  - `/api/sensors/available` - Verfügbare Sensoren
  - `/api/analytics/timeseries` - Zeitreihen-Daten
  - `/api/analytics/device-activity` - Geräte-Aktivität

### Geändert
- Web-Interface: Moderne UI mit besserer Navigation
- Settings-Seite: Erweitert um ML-Training Sektion
- Automations-Seite: Vereint alte und neue Funktionen in Tabs

### Technisch
- `MLAutoTrainer` Background-Prozess in `src/background/ml_auto_trainer.py`
- `BackgroundDataCollector` in `src/background/data_collector.py`
- `BathroomOptimizer` in `src/background/bathroom_optimizer.py`
- JavaScript-Erweiterungen in `settings.js` für ML-Status
- Kombinierte `automations.html` mit Tab-System

---

## [1.1.0] - 2025-11-07

### Hinzugefügt
- **Multi-Platform Support**: Homey Pro Integration
- `HomeyCollector`: Native Homey Pro API Integration
- `PlatformFactory`: Factory Pattern für Plattform-Auswahl
- `SmartHomeCollector`: Abstraktes Interface für alle Plattformen
- Neue Dokumentation: `HOMEY_SETUP.md`, `PLATFORMS.md`, `FEATURES.md`

### Geändert
- **Energiepreis-Integration ist jetzt optional** (standardmäßig deaktiviert)
- Config: `platform.type` zur Auswahl zwischen Home Assistant und Homey
- Decision Engine: Nutzt jetzt Platform Factory statt direkte HA-Integration
- `test_connection()`: Zeigt jetzt "smart_home_platform" statt "home_assistant"
- Requirements: Optionale Dependencies klar markiert

### Entfernt
- Keine Breaking Changes

### Migration von v1.0.0

1. Update `config.yaml`:
```yaml
# Alt:
home_assistant:
  url: "..."
  token: "..."

# Neu (optional):
platform:
  type: "homeassistant"  # oder "homey"
home_assistant:
  url: "..."
  token: "..."
```

2. Energiepreise sind jetzt standardmäßig deaktiviert:
```yaml
external_data:
  energy_prices:
    enabled: false  # Auf true setzen wenn gewünscht
```

3. Keine Code-Änderungen nötig - voll abwärtskompatibel!

---

## [1.0.0] - 2025-11-07

### Erste Release

#### Features
- Machine Learning Beleuchtungssteuerung
- ML-basierte Temperaturregelung
- Home Assistant Integration
- Wetter-Integration (OpenWeatherMap)
- Energiepreis-Integration (aWATTar, Tibber)
- SQLite Datenbank für Historie
- Entscheidungs-Engine mit Safety-Checks
- CLI mit test, run, daemon, status, train Modi
- Systemd Service Support
- Logging mit loguru

#### Modelle
- Random Forest für Beleuchtung
- Gradient Boosting für Temperatur
- Energy Optimizer

#### Dokumentation
- README.md
- QUICK_START.md
- Setup-Script

---

## Versionsschema

Wir folgen [Semantic Versioning](https://semver.org/):
- MAJOR: Breaking Changes
- MINOR: Neue Features (abwärtskompatibel)
- PATCH: Bug Fixes
