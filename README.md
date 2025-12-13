# KI-System für Smart Home Automatisierung

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![Version](https://img.shields.io/badge/version-1.0.0-blue.svg)](https://github.com/dein-username/KI-SYSTEM/releases)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md)

Ein intelligentes Machine Learning-basiertes System zur automatischen Steuerung von Beleuchtung, Heizung und anderen Smart-Home-Geräten. Das System lernt aus deinem Verhalten und optimiert automatisch Energieverbrauch und Komfort.

**Version:** 1.0.0 | **Unterstützte Plattformen:** 🏠 Home Assistant · 🔷 Homey Pro

[Features](#features) · [Installation](#installation) · [Web-Dashboard](#web-dashboard) · [Dokumentation](#dokumentation) · [Contributing](CONTRIBUTING.md)

## 🆕 Was ist neu in Version 1.0.0?

- **🔧 Zentralisierte Sensor-Verwaltung**: Einfache Verwaltung von Sensoren aus Homey und Home Assistant an einem Ort.
- **👁️ Ignore-Funktion**: Sensoren und Fenster können nun explizit ignoriert werden, um Duplikate oder fehlerhafte Geräte auszublenden.
- **🏠 Verbesserte Raumverwaltung**: Neue UI-Optionen zur Feinjustierung der Raum-Konfiguration.
- **⚙️ Live-Konfiguration**: Einstellungen direkt im Web-Interface ändern (ohne YAML-Editing)
- **📊 Live Training Progress**: Echtzeit-Fortschrittsanzeige beim ML-Modell-Training mit Progress-Bar
- **🧹 Datenmanagement**: Trainingsdaten löschen und Modelle neu trainieren über Web-UI
- **🏠 Raumspezifische Heizpläne**: Optimierte Heizung pro Raum mit individuellen Insights und Lernparametern
- **🔧 Erweiterte Heizungssteuerung**:
  - Fenster-Heizungs-Integration (kein Heizen bei offenen Fenstern)
  - Monitoring-Modus für Datensammlung ohne aktive Steuerung
  - Live-Temperaturverlauf mit interaktiven Charts
  - Fenster-Statistiken mit Häufigkeit und Dauer-Analyse
  - KI-basierte Optimierungsvorschläge pro Raum
- **🌡️ Schimmelprävention**:
  - Automatische Taupunkt-Berechnung (Magnus-Formel)
  - Echtzeit-Schimmelrisiko-Bewertung (4 Stufen: NIEDRIG/MITTEL/HOCH/KRITISCH)
  - Intelligente Luftentfeuchter-Steuerung bei erkanntem Risiko
  - Kondensations-Warnung mit visueller Darstellung
- **🎯 Automatische ML-Datensammlung**:
  - Kontinuierliche Sammlung von Temperatur- und Beleuchtungsdaten
  - Background-Collector für Training Data (alle 15 Minuten)
  - Automatische Vorbereitung für ML-Modell-Training
  - Live-Anzeige des Datensammlungs-Status
- **🎨 Verbessertes UX**: Sofortiges Feedback bei allen Aktionen, keine "Coming Soon" Meldungen mehr

### Was ist neu in Version 0.8?

- **🌐 Web-Dashboard**: Komplett neues Web-Interface mit modernem Design
- **🚿 Badezimmer-Automatisierung**: Selbstlernendes System für intelligente Luftentfeuchter-Steuerung
- **📊 Analytics-Dashboards**: Interaktive Charts für Temperatur und Luftfeuchtigkeit
- **🤖 Automatische Optimierung**: Tägliche Schwellwert-Optimierung basierend auf historischen Daten
- **📈 Trend-Analyse**: Visualisierung von Mustern und Vorhersagen
- **🔄 Hintergrund-Datensammlung**: Automatisches Sensor-Logging alle 5 Minuten
- **🏠 Raum-Management**: Verbesserte Raum- und Geräteverwaltung
- **📱 Responsive Design**: Optimiert für Desktop, Tablet und Smartphone

## Features

### 🎯 Core Features

- **Machine Learning Steuerung**
  - Intelligente Beleuchtungssteuerung basierend auf Tageszeit, Helligkeit, Bewegung
  - Adaptive Temperaturregelung mit Wettervorhersage
  - Lernt aus deinem Verhalten und passt sich an
  - Automatische Datensammlung für kontinuierliches Training

- **Energieoptimierung**
  - Intelligente Heizungssteuerung mit raumspezifischer Optimierung
  - KI-basierte Vorschläge zur Energieeinsparung
  - Optional: Dynamische Strompreise (aWATTar, Tibber)
  - Energiespar-Empfehlungen in Echtzeit

### 🌐 Web-Dashboard

- **Modernes Web-Interface**
  - Echtzeit-Übersicht über alle Geräte und Sensoren
  - Interaktive Analytics-Dashboards mit Trend-Charts
  - Responsive Design für Desktop, Tablet und Mobile
  - Dunkles Theme für bessere Lesbarkeit

- **Live-Konfiguration (NEU in v0.9)**
  - Einstellungen direkt im Web-Interface ändern
  - Konfiguration ohne manuelles YAML-Editing
  - Sofortige Validierung und Speicherung
  - Unterstützt: Modus, Confidence-Schwellwerte, Intervalle

- **ML Training Management (NEU in v0.9)**
  - Live-Fortschrittsanzeige beim Training
  - Echtzeit-Status mit animierter Progress-Bar
  - Detaillierte Schritt-Anzeige (Daten laden, Training, Speichern)
  - Manuelle Modell-Neutrainierung per Knopfdruck
  - Training History mit Metriken
  - Datenmanagement (Trainingsdaten löschen)
  - **Automatische Datensammlung**: Kontinuierliches Sammeln von Trainings-Daten
  - **Live-Zähler**: Echtzeit-Anzeige der gesammelten Events und Messungen

- **Selbstlernendes Badezimmer-System**
  - Automatische Dusch-Erkennung
  - Intelligente Luftentfeuchter-Steuerung
  - **Schimmelprävention**: Automatische Taupunkt-Berechnung und Risiko-Bewertung
  - Analytics & Statistiken (Events, Dauer, Luftfeuchtigkeit)
  - Vorhersage der nächsten Duschzeit
  - Automatische Schwellwert-Optimierung (täglich um 3:00 Uhr)
  - Trendanalyse und Muster-Erkennung

- **Erweiterte Heizungssteuerung (NEU in v0.9)**
  - **Raumspezifische Heizpläne**: Jeder Raum lernt individuell (Aufheizrate, Abkühlrate, Thermische Masse)
  - **Monitoring-Modus**: Datensammlung ohne aktive Steuerung (Tado X behält die Kontrolle)
  - **Live-Temperaturverlauf**: Interaktive Charts mit Ist/Soll-Temperatur pro Raum
  - **Fenster-Integration**: Automatisches Heizen stoppen bei offenen Fenstern
  - **Fenster-Statistiken**: Häufigkeit, Dauer und Trends mit Bar-Charts
  - **KI-Insights pro Raum**: Personalisierte Optimierungsvorschläge für jeden Raum
  - **Schimmelprävention**: Taupunkt-Berechnung mit automatischer Luftentfeuchter-Steuerung
  - Intelligente Lüftungsempfehlungen (absolute Luftfeuchtigkeit)
  - Duschzeit-Vorhersage für präventives Aufheizen

- **Hintergrund-Datensammlung**
  - Automatisches Sammeln von Sensor-Daten alle 5 Minuten
  - **ML-Training-Daten**: Kontinuierliche Sammlung von Beleuchtungs-Events und Temperaturmessungen
  - **Background-Collector**: LightingDataCollector (60s) und TemperatureDataCollector (15min)
  - Langzeit-Analytics für Temperatur und Luftfeuchtigkeit
  - Persistente Speicherung in SQLite-Datenbank
  - Live-Status im Web-Interface

### 🏠 Multi-Platform Support

- **Home Assistant**: Volle Integration mit Home Assistant
- **Homey Pro**: Native Unterstützung für Homey Pro
- Einfacher Wechsel zwischen Plattformen
- Einheitliche API für beide Systeme

### 🔌 Externe Datenquellen (optional)

- Wettervorhersage (OpenWeatherMap) - empfohlen
- Dynamische Strompreise (aWATTar, Tibber) - optional, standardmäßig deaktiviert
- Anwesenheitserkennung

## Systemanforderungen

- **Betriebssystem**: Linux (getestet auf Ubuntu 22.04, Debian 11, Raspberry Pi OS)
- **Python**: 3.8 oder höher
- **Smart Home Platform** (eine davon):
  - **Home Assistant**: Version 2023.1 oder höher, ODER
  - **Homey Pro**: 2023 oder neuer (auch ältere Homey-Versionen unterstützt)
- **Speicher**: Mindestens 2GB RAM
- **Speicherplatz**: 500MB für System + Logs

## Installation

### 1. Repository klonen

```bash
git clone https://github.com/dein-username/KI-SYSTEM.git
cd KI-SYSTEM
```

### 2. Python Virtual Environment erstellen

```bash
python3 -m venv venv
source venv/bin/activate  # Auf Linux/Mac
```

### 3. Dependencies installieren

```bash
pip install -r requirements.txt
```

### 4. Konfiguration einrichten

```bash
# .env Datei erstellen
cp .env.example .env

# Bearbeite .env mit deinen Zugangsdaten
nano .env
```

#### Option A: Home Assistant

Trage folgende Daten ein:
- `PLATFORM_TYPE=homeassistant`
- `HA_URL`: URL deiner Home Assistant Instanz (z.B. `http://192.168.1.100:8123`)
- `HA_TOKEN`: Long-lived Access Token von Home Assistant

**Home Assistant Token erstellen:**

1. Öffne Home Assistant
2. Gehe zu deinem Profil (unten links)
3. Scrolle zu "Long-lived access tokens"
4. Klicke "Create Token"
5. Kopiere den Token und trage ihn in `.env` ein

#### Option B: Homey Pro

Trage folgende Daten ein:
- `PLATFORM_TYPE=homey`
- `HOMEY_URL=https://api.athom.com` (oder lokale IP)
- `HOMEY_TOKEN`: Bearer Token von Homey

**Homey Token erstellen:** Siehe [HOMEY_SETUP.md](HOMEY_SETUP.md) für Details

```bash
# Via Homey CLI
npm install -g athom-cli
athom login
athom user --bearer
```

### 5. Konfiguration anpassen

Bearbeite `config/config.yaml`:

```bash
nano config/config.yaml
```

Wichtige Einstellungen:
- `home_assistant.url`: Deine Home Assistant URL
- `data_collection.sensors`: Deine Sensor-Entity-IDs
- `models.energy_optimizer`: Komfort vs. Energiesparen

## 🔄 Updates & Daten-Persistenz

### Updates installieren (2 Optionen)

**Option 1: Über Web-Interface (Empfohlen ⭐)**

1. Öffne: `http://localhost:5000/settings` → Tab "System"
2. Klicke auf **"Nach Updates suchen"**
3. Falls Updates verfügbar: **"Update installieren"**
4. Fertig! System erstellt Backup und startet automatisch neu

**Option 2: Manuell via Terminal**

```bash
# Hole neueste Version vom Repository
git pull origin main

# Aktualisiere Dependencies (falls nötig)
pip install -r requirements.txt --upgrade

# Starte System neu
python3 main.py web
```

### ✅ Deine Daten bleiben erhalten!

**Alle wichtigen Dateien sind automatisch vor Updates geschützt** und werden nicht von Git überschrieben:

| Was bleibt erhalten | Speicherort |
|---------------------|-------------|
| 🗄️ **Datenbank** | `data/ki_system.db` |
| ⚙️ **Einstellungen** | `data/*.json` |
| 🧠 **Trainierte ML-Modelle** | `models/*.pkl` |
| 🔑 **Credentials** | `.env` |
| 📝 **Logs** | `logs/` |

**Zusätzlich beim Web-Update:**
- 🛡️ Automatisches Backup vor jedem Update (in `.backup/`)
- 📦 Backups werden 7 Tage aufbewahrt
- 🔄 Automatischer System-Neustart nach Update

**Kein manuelles Backup vor Updates nötig!** Siehe [PERSISTENCE.md](PERSISTENCE.md) für Details.

### Nach einem Update

```bash
# Web-App neu starten
python3 main.py web

# Logs prüfen
tail -f logs/ki_system.log

# Einstellungen überprüfen
open http://localhost:5000/settings
```

## Web-Dashboard

### Web-Interface starten

```bash
python main.py web --host 0.0.0.0 --port 8080
```

Das Web-Dashboard ist dann erreichbar unter:
- **Lokal**: http://localhost:8080
- **Im Netzwerk**: http://DEINE-IP:8080

### Dashboard-Features

**📊 Hauptseiten:**

- **Dashboard** (`/`) - Übersicht über Status, Vorhersagen, Wetter, Schimmelprävention
- **Analytics** (`/analytics`) - Temperatur- und Luftfeuchtigkeit-Trends
- **Heizung** (`/heating`) - Erweiterte Heizungssteuerung mit Raum-Insights und Fenster-Statistiken
- **Badezimmer** (`/luftentfeuchten`) - Intelligente Badezimmer-Automatisierung mit Schimmelprävention
- **Geräte** (`/devices`) - Alle verbundenen Geräte verwalten
- **Räume** (`/rooms`) - Raum-Management
- **Automatisierungen** (`/automations`) - Automatisierungs-Regeln
- **Einstellungen** (`/settings`) - System-Konfiguration mit Live-Updates

**🔥 Heizungssteuerung (NEU in v0.9):**

1. **Monitoring/Control-Modus**:
   - Monitoring: Nur Daten sammeln, Tado X behält Kontrolle
   - Control: KI steuert aktiv Thermostate

2. **Raumspezifisches Lernen**:
   - Automatisches Lernen der Aufheizrate (°C/h)
   - Berechnung der Abkühlrate
   - Thermische Masse pro Raum
   - Individuelle Optimierungsvorschläge

3. **Live-Visualisierungen**:
   - Temperaturverlauf mit Chart.js
   - Fenster-Statistiken (Häufigkeit, Dauer)
   - Heizaktivität pro Raum

4. **Fenster-Integration**:
   - Automatische Heizung stoppen bei offenen Fenstern
   - Statistiken über Fensteröffnungen
   - Energy-Loss-Berechnung

**🚿 Badezimmer-Automatisierung:**

1. **Konfiguration** (`/luftentfeuchten`):
   - Sensoren auswählen (Luftfeuchtigkeit, Temperatur)
   - Luftentfeuchter konfigurieren
   - Schwellwerte anpassen (High/Low Luftfeuchtigkeit)
   - **Schimmelprävention**: Echtzeit-Risikobewertung mit Taupunkt
   - System aktivieren/deaktivieren

2. **Analytics Dashboard** (`/bathroom/analytics`):
   - Echtzeit-Statistiken (Events, Durchschnittswerte)
   - **Schimmelrisiko-Anzeige**: 4 Stufen (NIEDRIG/MITTEL/HOCH/KRITISCH)
   - Trend-Charts (letzte 10 Events)
   - Häufigste Duschzeiten
   - Wochentags-Verteilung
   - Vorhersage der nächsten Duschzeit
   - Event-Historie

3. **Automatische Optimierung & Prävention**:
   - Läuft täglich um 3:00 Uhr
   - Optimiert Schwellwerte basierend auf historischen Daten
   - **Automatische Luftentfeuchter-Steuerung bei Schimmelrisiko**
   - Benötigt mindestens 3 Events für Optimierung

### API-Endpunkte

Das Web-Interface bietet auch eine REST-API:

```bash
# Status abrufen
curl http://localhost:8080/api/status

# Geräte auflisten
curl http://localhost:8080/api/devices

# Badezimmer-Analytics
curl http://localhost:8080/api/bathroom/analytics?days=30

# Badezimmer-Events
curl http://localhost:8080/api/bathroom/events?days=7&limit=50

# NEU in v0.9: Konfiguration verwalten
curl http://localhost:8080/api/config
curl -X POST http://localhost:8080/api/config/update \
  -H "Content-Type: application/json" \
  -d '{"decision_mode": "learning", "confidence_threshold": 0.8}'

# NEU in v0.9: ML Training
curl -X POST http://localhost:8080/api/ml/train \
  -H "Content-Type: application/json" \
  -d '{"model": "all"}'

# NEU in v0.9: Training Status (Live Progress)
curl http://localhost:8080/api/ml/train/status

# NEU in v0.9: ML Status & History
curl http://localhost:8080/api/ml/status
curl http://localhost:8080/api/ml/training-history

# NEU in v0.9: Daten löschen
curl -X DELETE http://localhost:8080/api/data/clear
curl -X DELETE http://localhost:8080/api/data/clear?days_back=30

# NEU in v0.9: Heizung & Fenster & Schimmelprävention
curl http://localhost:8080/api/heating/windows/charts?days=7
curl http://localhost:8080/api/heating/insights
curl http://localhost:8080/api/heating/temperature-history?days=7
curl http://localhost:8080/api/heating/mode  # GET/POST für Monitoring/Control Toggle
curl http://localhost:8080/api/humidity/alerts
curl http://localhost:8080/api/ventilation/recommendation
curl http://localhost:8080/api/shower/predictions
curl http://localhost:8080/api/room/learning/<room_name>

# NEU in v0.9: ML-Datensammlung Status
curl http://localhost:8080/api/ml/status  # Zeigt gesammelte Training-Daten
```

## Verwendung

### Verbindung testen

```bash
python main.py test
```

Dies prüft:
- Home Assistant Verbindung
- Wetter-API
- Energiepreis-API
- Datenbank

### Aktuellen Status anzeigen

```bash
python main.py status
```

Zeigt:
- Aktuelle Temperaturen
- Wetterbedingungen
- Strompreise
- Empfehlungen

### Einmaligen Zyklus ausführen

```bash
python main.py run
```

Führt einen Entscheidungs-Zyklus aus:
1. Sammelt Sensordaten
2. Trifft Entscheidungen
3. Führt Aktionen aus (wenn im Auto-Modus)

### Daemon-Modus (dauerhaft laufen lassen)

```bash
python main.py daemon --interval 300
```

Läuft dauerhaft und führt alle 300 Sekunden (5 Minuten) einen Zyklus aus.

### Als Systemd Service einrichten

Für automatischen Start beim Booten:

```bash
# Service-Datei erstellen
sudo nano /etc/systemd/system/ki-system.service
```

Inhalt:

```ini
[Unit]
Description=KI Smart Home System
After=network.target home-assistant.service

[Service]
Type=simple
User=dein-username
WorkingDirectory=/pfad/zum/KI-SYSTEM
ExecStart=/pfad/zum/KI-SYSTEM/venv/bin/python main.py daemon
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Service aktivieren:

```bash
sudo systemctl daemon-reload
sudo systemctl enable ki-system
sudo systemctl start ki-system

# Status prüfen
sudo systemctl status ki-system
```

## Konfiguration

### Modi

Das System hat 3 Modi:

- **`auto`**: Entscheidungen werden automatisch ausgeführt
- **`learning`**: System lernt, führt aber keine Aktionen aus
- **`manual`**: System macht Vorschläge, wartet aber auf Bestätigung

Einstellen in `config/config.yaml`:

```yaml
decision_engine:
  mode: "auto"  # oder "learning" oder "manual"
```

### Machine Learning Modelle

#### Beleuchtung

```yaml
models:
  lighting:
    type: "random_forest"  # oder "gradient_boosting"
    retrain_interval_hours: 24
    min_training_samples: 100
```

#### Heizung

```yaml
models:
  heating:
    type: "gradient_boosting"  # oder "random_forest"
    retrain_interval_hours: 24
    min_training_samples: 200
```

### Energieoptimierung

```yaml
models:
  energy_optimizer:
    target: "minimize_cost"  # oder "minimize_consumption", "balance"
    constraints:
      min_temperature: 18
      max_temperature: 23
      comfort_priority: 0.7  # 0 = max Einsparung, 1 = max Komfort
```

### Sicherheitsregeln

Definiere Regeln, die immer gelten:

```yaml
decision_engine:
  rules:
    - name: "no_heating_when_windows_open"
      condition: "window_sensor == open"
      action: "heating == off"

    - name: "presence_override"
      condition: "away_mode == true"
      action: "eco_mode == true"
```

## Training der ML-Modelle

### Automatische Datensammlung (NEU in v0.9)

Das System sammelt **automatisch** kontinuierlich Trainingsdaten:

- **Temperature Data**: Alle 15 Minuten (HeatingDataCollector)
- **Lighting Data**: Bei jedem Zustandswechsel (LightingDataCollector)

**Live-Status anzeigen:**
```bash
curl http://localhost:8080/api/ml/status
```

Zeigt:
- `temperature.data_count`: Anzahl der Temperaturmessungen (Ziel: 200)
- `lighting.data_count`: Anzahl der Beleuchtungs-Events (Ziel: 100)
- `days_of_data`: Wie lange Daten gesammelt werden
- `ready`: Ob genug Daten für Training vorhanden sind

### Manuelles Training

Nach einigen Tagen Datensammlung:

```bash
python main.py train
```

**Oder über Web-Interface:**
- Öffne `/settings`
- Gehe zum "ML Training" Tab
- Klicke "Training starten"
- Live-Fortschritt wird angezeigt

**Minimale Datenmengen:**
- Beleuchtung: 100+ Events (ca. 2-3 Tage)
- Heizung: 200+ Messungen (ca. 2 Tage bei 15min-Intervall)

**Automatisches Training:**
Das System trainiert auch automatisch neu (täglich um 2:00 Uhr), wenn genug neue Daten vorhanden sind.

## Externe APIs

### OpenWeatherMap (Wetter)

1. Registriere dich auf [openweathermap.org](https://openweathermap.org/)
2. Erstelle einen API Key (kostenlos für 60 calls/min)
3. Trage Key in `.env` ein: `WEATHER_API_KEY=dein_key`

### aWATTar (Strompreise)

- Keine Registrierung nötig
- Funktioniert automatisch für Deutschland und Österreich

### Tibber (Strompreise)

1. Tibber-Kunde werden
2. API Token holen: [developer.tibber.com](https://developer.tibber.com/)
3. In `.env` eintragen: `ENERGY_API_KEY=dein_token`

## Projektstruktur

```
KI-SYSTEM/
├── config/
│   └── config.yaml           # Hauptkonfiguration
├── src/
│   ├── background/           # Background-Services
│   │   ├── bathroom_data_collector.py
│   │   ├── bathroom_optimizer.py
│   │   ├── heating_data_collector.py
│   │   ├── window_data_collector.py
│   │   ├── lighting_data_collector.py    # NEU in v0.9
│   │   ├── temperature_data_collector.py # NEU in v0.9
│   │   ├── ml_auto_trainer.py
│   │   └── database_maintenance.py
│   ├── data_collector/       # Datensammler
│   │   ├── ha_collector.py   # Home Assistant
│   │   ├── homey_collector.py # Homey Pro
│   │   ├── weather_collector.py
│   │   └── energy_price_collector.py
│   ├── models/               # ML-Modelle
│   │   ├── lighting_model.py
│   │   ├── temperature_model.py
│   │   └── energy_optimizer.py
│   ├── decision_engine/      # Entscheidungs-Engine
│   │   ├── engine.py
│   │   ├── bathroom_automation.py    # Badezimmer-Logik mit Schimmelprävention
│   │   ├── bathroom_analyzer.py      # Analytics & Muster-Erkennung
│   │   ├── heating_optimizer.py      # Heizungs-Optimierung pro Raum
│   │   └── room_learning.py          # Raumspezifisches Lernen
│   ├── background/           # Hintergrund-Prozesse
│   │   ├── data_collector.py         # Auto. Datensammlung
│   │   └── bathroom_optimizer.py     # Tägliche Optimierung
│   ├── web/                  # Web-Interface (NEU in v0.8)
│   │   ├── app.py            # Flask Web-App
│   │   ├── templates/        # HTML Templates
│   │   │   ├── base.html
│   │   │   ├── dashboard.html
│   │   │   ├── bathroom.html
│   │   │   ├── bathroom_analytics.html
│   │   │   ├── analytics.html
│   │   │   └── ...
│   │   └── static/           # CSS/JS/Assets
│   │       ├── css/
│   │       │   └── style.css
│   │       └── js/
│   │           ├── main.js
│   │           ├── bathroom.js
│   │           ├── bathroom_analytics.js
│   │           └── ...
│   └── utils/                # Utilities
│       ├── config_loader.py
│       └── database.py       # SQLite mit Analytics-Support
├── data/
│   ├── ki_system.db          # SQLite Datenbank (erweitert)
│   ├── bathroom_config.json  # Badezimmer-Konfiguration
│   └── sensor_config.json    # Sensor-Whitelist
├── models/                   # Trainierte ML-Modelle
├── logs/                     # Log-Dateien
├── main.py                   # Hauptprogramm
├── requirements.txt          # Python Dependencies
└── README.md                 # Diese Datei
```

## Troubleshooting

### Home Assistant Verbindung fehlgeschlagen

```bash
# Prüfe Erreichbarkeit
curl -H "Authorization: Bearer DEIN_TOKEN" http://IP:8123/api/

# Prüfe Token in .env
cat .env | grep HA_TOKEN
```

### Keine Sensor-Daten

```bash
# Prüfe Entity-IDs in Home Assistant
# Öffne Home Assistant → Developer Tools → States
# Kopiere exakte Entity-IDs in config.yaml
```

### ML-Modell trainiert nicht

- Prüfe ob genug Daten vorhanden: `python main.py status`
- System muss mindestens 2-3 Tage Daten sammeln
- Prüfe Logs: `tail -f logs/ki_system.log`

### Hoher CPU/RAM Verbrauch

- Reduziere `data_collection.interval_seconds` in config.yaml
- Nutze `model_type: "random_forest"` statt "gradient_boosting"
- Aktiviere nicht tensorflow wenn nicht nötig

## FAQ

### Allgemein

**Q: Wie lange dauert es, bis das System lernt?**
A: Nach 2-3 Tagen hat das System genug Daten für erste Entscheidungen. Optimale Ergebnisse nach 1-2 Wochen.

**Q: Ist das System sicher?**
A: Ja, es gibt mehrere Safety-Checks:
- Temperatur-Grenzen (16-25°C)
- Keine extremen Änderungen
- Sicherheitsregeln (z.B. kein Heizen bei offenen Fenstern)

**Q: Kann ich das System auf Raspberry Pi laufen lassen?**
A: Ja! Raspberry Pi 3B+ oder höher empfohlen. Funktioniert auch auf Pi Zero 2W.

**Q: Werden meine Daten in die Cloud gesendet?**
A: Nein! Alle Daten bleiben lokal. Nur externe APIs (Wetter, Preise) werden abgerufen.

**Q: Kann ich eigene Regeln hinzufügen?**
A: Ja, in `config/config.yaml` unter `decision_engine.rules`

**Q: Funktioniert es ohne Home Assistant?**
A: Ja! Das System unterstützt auch Homey Pro. Du kannst zwischen beiden Plattformen wählen.

### Web-Dashboard

**Q: Wie greife ich auf das Web-Dashboard zu?**
A: Starte das Web-Interface mit `python main.py web --host 0.0.0.0 --port 8080` und öffne http://localhost:8080 im Browser.

**Q: Kann ich das Dashboard von meinem Smartphone aus nutzen?**
A: Ja! Das Dashboard ist responsive und funktioniert auf Desktop, Tablet und Smartphone.

**Q: Ist das Web-Dashboard passwortgeschützt?**
A: Aktuell noch nicht. Dies ist für zukünftige Versionen geplant. Nutze es nur in vertrauenswürdigen Netzwerken.

### Badezimmer-Automatisierung

**Q: Wann beginnt das System Daten zu sammeln?**
A: Sofort nach Aktivierung in `/bathroom`. Das System erkennt automatisch Duschen basierend auf Luftfeuchtigkeit-Anstiegen.

**Q: Warum zeigt Analytics "Fehler beim Laden der Daten"?**
A: Das System benötigt mindestens 1 Event (Dusch-Vorgang). Die Datensammlung startet automatisch nach der Konfiguration.

**Q: Wie oft optimiert das System die Schwellwerte?**
A: Täglich um 3:00 Uhr, sobald mindestens 3 Events erfasst wurden. Die Optimierung benötigt eine Konfidenz von mindestens 70%.

**Q: Kann ich die Optimierung manuell starten?**
A: Ja! Im Analytics-Dashboard (`/bathroom/analytics`) gibt es einen "Jetzt optimieren" Button.

**Q: Welche Sensoren werden benötigt?**
A: Mindestens:
- 1 Luftfeuchtigkeit-Sensor (für Dusch-Erkennung)
- 1 Temperatur-Sensor
- 1 Schaltbares Gerät (Luftentfeuchter)

Optional: Bewegungsmelder, Tür-Sensor für erweiterte Funktionen.

## Roadmap

### ✅ Implementiert (v0.9)

- [x] Home Assistant Support
- [x] Homey Pro Support
- [x] **Web-Dashboard für Visualisierung**
  - [x] Echtzeit-Status-Übersicht
  - [x] Interaktive Analytics-Charts
  - [x] Geräte-Verwaltung
  - [x] Raum-Management
  - [x] Automatisierungs-Konfiguration
  - [x] **Live-Konfiguration ohne YAML-Editing (v0.9)**
  - [x] **Live Training Progress mit Progress-Bar (v0.9)**
  - [x] **Datenmanagement über UI (v0.9)**
- [x] **Selbstlernendes Badezimmer-System**
  - [x] Dusch-Erkennung
  - [x] Automatische Luftentfeuchter-Steuerung
  - [x] Analytics & Event-Tracking
  - [x] Vorhersage-System
  - [x] Automatische Optimierung
- [x] **Intelligente Heizungssteuerung (v0.9)**
  - [x] Raumspezifische Heizpläne
  - [x] Fenster-Integration
  - [x] Schimmelprävention (Taupunkt-Berechnung)
  - [x] Intelligente Lüftungsempfehlungen
  - [x] Duschzeit-Vorhersage
  - [x] Interaktive Fenster-Statistiken
- [x] **Hintergrund-Datensammlung**
  - [x] Automatisches Sensor-Logging
  - [x] Langzeit-Analytics
  - [x] SQLite-Datenbank

### 🚀 Geplant

- [ ] Wetter-Forecast Integration für präventives Heizen
- [ ] Präsenz-Erkennung über Motion-Sensoren
- [ ] Smartphone-App (iOS/Android)
- [ ] MQTT-Support für direkte Geräte-Steuerung
- [ ] Mehr ML-Modelle
  - [ ] Jalousien-Steuerung
  - [ ] Waschmaschinen-Zeitplanung
- [ ] Voice-Control Integration (Alexa, Google Home)
- [ ] Multi-Home Support (mehrere Standorte)
- [ ] Zusätzliche Plattformen
  - [ ] OpenHAB Support
  - [ ] ioBroker Support
  - [ ] Node-RED Integration
- [ ] Erweiterte Features
  - [ ] Energieverbrauchs-Prognosen
  - [ ] Kostenoptimierung mit dynamischen Tarifen
  - [ ] Push-Benachrichtigungen
  - [ ] Backup & Restore-Funktion
  - [ ] Authentifizierung & User-Management

## Beitragen

Contributions sind willkommen! Bitte:
1. Fork das Repository
2. Erstelle einen Feature-Branch (`git checkout -b feature/AmazingFeature`)
3. Commit deine Änderungen (`git commit -m 'Add AmazingFeature'`)
4. Push zum Branch (`git push origin feature/AmazingFeature`)
5. Öffne einen Pull Request

## Lizenz

MIT License - siehe [LICENSE](LICENSE) Datei

## Support

- GitHub Issues: [Issues](https://github.com/dein-username/KI-SYSTEM/issues)
- Dokumentation: [Wiki](https://github.com/dein-username/KI-SYSTEM/wiki)

## Credits

Erstellt mit:
- [Home Assistant](https://www.home-assistant.io/)
- [scikit-learn](https://scikit-learn.org/)
- [OpenWeatherMap](https://openweathermap.org/)

---

**Hinweis**: Dies ist ein experimentelles Projekt. Nutze es auf eigene Verantwortung und prüfe alle Automatisierungen gründlich, bevor du sie in Produktion einsetzt.

---

## 🤝 Contributing

Beiträge sind willkommen! Siehe [CONTRIBUTING.md](CONTRIBUTING.md) für Details.

- 🐛 [Bug melden](.github/ISSUE_TEMPLATE/bug_report.yml)
- 💡 [Feature vorschlagen](.github/ISSUE_TEMPLATE/feature_request.yml)
- ❓ [Frage stellen](.github/ISSUE_TEMPLATE/question.yml)

## 📄 Lizenz

Dieses Projekt ist lizenziert unter der MIT License - siehe [LICENSE](LICENSE) für Details.

## 🙏 Acknowledgments

- [Home Assistant](https://www.home-assistant.io/) - Open Source Smart Home Platform
- [Homey](https://homey.app/) - Homey Pro Integration
- [scikit-learn](https://scikit-learn.org/) - Machine Learning Library
- Alle [Contributors](../../graphs/contributors) die geholfen haben!

## 📬 Kontakt & Support

- 📫 GitHub Issues für Bugs und Features
- 💬 GitHub Discussions für Fragen (falls aktiviert)
- ⭐ Gib dem Projekt einen Star wenn es dir gefällt!

---

<p align="center">
  Made with ❤️ für die Smart Home Community
</p>
