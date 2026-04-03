# Design: Ring Intercom Integration

**Datum**: 2026-04-03
**Status**: Approved
**Abhaengigkeiten**: `ring_doorbell` Python Library, Pushover API

## Zusammenfassung

Integration des Ring Intercom direkt ueber die `ring_doorbell` Python Library ins KI-SYSTEM. Klingel-Events empfangen, Tueroeffner steuern, Verbindung ueberwachen, Pushover-Benachrichtigungen bei Events und Fehlern.

## 1. Architektur

### Neue Dateien
| Datei | Zweck |
|------|-------|
| `src/data_collector/ring_collector.py` | Ring API Wrapper (Auth, Events, Tueroeffner, Health-Check) |
| `src/background/ring_monitor.py` | Hintergrundprozess: Polling, Token-Refresh, Event-Erkennung |
| `src/web/blueprints/ring.py` | Flask Blueprint: API-Endpoints + Dashboard-Seite |
| `src/web/templates/ring.html` | Dashboard-Seite fuer Ring Intercom |
| `data/ring_token.cache` | Persistenter Token-Cache (gitignored) |

### Aenderungen an bestehenden Dateien
| Datei | Aenderung |
|------|-----------|
| `config/config.yaml` | Neuer Abschnitt `ring:` + `pushover:` |
| `src/web/app.py` | Ring Blueprint registrieren |
| `src/background/collector_manager.py` | Ring-Monitor als Background-Task starten |
| `.gitignore` | `data/ring_token.cache` hinzufuegen |

### Datenfluss
```
Ring Cloud API <---> ring_collector.py <---> ring_monitor.py (Background)
                                              | Event erkannt
                                              v
                                         ring_events (DB)
                                              |
                                              v
                                      /api/ring/* (REST API)
                                              |
                                              v
                                        ring.html (Dashboard)
```

## 2. Ring Collector & Auth

### `ring_collector.py` — API Wrapper

**Auth-Flow:**
- Email/Passwort aus `config.yaml` (`ring.email`, `ring.password`)
- 2FA-Token: Beim ersten Start wird Token in `data/ring_token.cache` gespeichert
- Automatischer Token-Refresh alle 6 Stunden
- Bei Token-Fehler: Pushover-Alarm, Dashboard-Warnung, Retry mit exponentiellem Backoff

**Methoden:**
- `connect()` — Auth + Geraete-Discovery (Intercom finden)
- `get_health()` — Verbindung ok? Letztes Event? Token gueltig?
- `get_events(limit)` — Letzte N Events aus der DB
- `listen()` — Polling-Loop: Prueft alle X Sekunden auf neue Events
- `open_door()` — Tueroeffner ausloesen
- `_save_token()` / `_load_token()` — Token-Persistenz

**Event-Erkennung:**
- Pollt Ring API alle 10-30 Sekunden (konfigurierbar via `ring.poll_interval`)
- Vergleicht `last_event_id` um neue Events zu erkennen
- Neues Event → in `ring_events` DB schreiben + Health-Status aktualisieren

**Fehlerbehandlung:**
- Token abgelaufen → Auto-Refresh, bei 3x Failure → Pushover-Alarm + Dashboard-Warnung
- Ring API unreachable → Exponentieller Backoff, max 5 Min Wartezeit
- 2FA erforderlich → Pushover-Nachricht + Dashboard-Hinweis "2FA Token benoetigt"

## 3. Pushover-Benachrichtigungen

### Konfiguration
Neuer Abschnitt in `config.yaml`:
```yaml
pushover:
  user_key: "USER_KEY"
  app_key: "APP_KEY"
  enabled: true
```

### Benachrichtigungs-Typen
| Event | Nachricht | Prioritaet |
|-------|-----------|------------|
| Klingel-Event | "Jemand klingelt an der Tuer" | 0 (normal) |
| Auto-Tueroeffnung | "Tuer automatisch geoeffnet" | 0 (normal) |
| Token abgelaufen | "Ring Token abgelaufen - 2FA noetig" | 1 (hoch) |
| Verbindung verloren | "Ring API nicht erreichbar" | 1 (hoch) |
| Verbindung wiederhergestellt | "Ring Verbindung wiederhergestellt" | -1 (low) |

### Auto-Open Logik
```yaml
ring:
  auto_open:
    enabled: false
    schedules:
      - start: "08:00"
        end: "18:00"
        days: [1, 2, 3, 4, 5]  # Mo-Fr
      - start: "09:00"
        end: "20:00"
        days: [0, 6]           # Sa-So
```
- Innerhalb eines Zeitfensters: Tuer automatisch oeffnen nach Klingel-Event
- Ausserhalb: Nur Pushover-Benachrichtigung, kein Auto-Open
- Verzoegerung: 5 Sekunden nach Klingel-Event (konfigurierbar)

## 4. Datenbank

### Neue Tabelle `ring_events`
```sql
CREATE TABLE IF NOT EXISTS ring_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,        -- ding, motion, unlock, health_check
    ring_event_id TEXT,              -- Ring's eigene Event-ID (Dedup)
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    duration INTEGER,                -- Sekunden, falls zutreffend
    answered BOOLEAN DEFAULT FALSE,
    auto_opened BOOLEAN DEFAULT FALSE,
    metadata JSON                    -- Raw Event-Daten
);
```

## 5. API-Endpoints

### `/api/ring/*` Endpoints
| Endpoint | Methode | Beschreibung |
|----------|---------|--------------|
| `/api/ring/status` | GET | Verbindung, letztes Event, Health-Status |
| `/api/ring/events` | GET | Letzte N Events (paginiert, default 20) |
| `/api/ring/open` | POST | Tuer manuell oeffnen |
| `/api/ring/health` | GET | Detaillierter Health-Check (Token, API, letztes Poll) |
| `/api/ring/settings` | GET | Aktuelle Einstellungen abrufen |
| `/api/ring/settings` | POST | Einstellungen aktualisieren (auto_open, schedules) |
| `/api/ring/test-notification` | POST | Pushover Test-Nachricht senden |

### Dashboard-Seite `/ring`
- **Status-Karte**: Verbunden/Getrennt, letztes Event vor X Min
- **Klingel-Historie**: Letzte 20 Events als Tabelle
- **Tueroeffner-Button**: Gross, gruen, mit Bestaetigungs-Dialog
- **Einstellungen**: Auto-Open Toggle + Zeitfenster-Konfiguration + Pushover-Test
- **Auto-Refresh**: Alle 10 Sekunden per AJAX

## 6. Config.yaml Erweiterung

```yaml
ring:
  enabled: true
  email: "RING_EMAIL"
  password: "RING_PASSWORD"
  poll_interval: 15          # Sekunden zwischen Polls
  token_cache: "data/ring_token.cache"
  auto_open:
    enabled: false
    delay: 5                 # Sekunden nach Klingel-Event
    schedules:
      - start: "08:00"
        end: "18:00"
        days: [1, 2, 3, 4, 5]
pushover:
  enabled: true
  user_key: ""
  app_key: ""
```

## 7. Was sich NICHT aendert

- Bestehende Platform-Abstraktion (Homey/HA Collector)
- Bestehende Background-Prozesse
- Bestehende Datenbank-Tabellen
- Bestehende Web-Routen
- Ring Collector ist unabhaengig vom Platform-Interface (kein SmartHomeCollector-Interface)
