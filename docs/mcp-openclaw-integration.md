# OpenClaw + KI-System MCP Integration

## Uebersicht

Der KI-System MCP Server gibt OpenClaw vollen Lese- und Schreibzugriff auf dein Smart-Home-System ueber 25+ Tools. Die Kommunikation laeuft ueber das MCP-Protokoll (Streamable HTTP) auf Port 3003.

## Server-Details

| Eigenschaft | Wert |
|---|---|
| URL | `http://192.168.12.198:3003/mcp` |
| Protokoll | MCP Streamable HTTP |
| PM2-Prozess | `ki-mcp-server` |
| Quellcode | `/var/www/KI-SYSTEM/mcp-server/` |

## Schritt 1: OpenClaw konfigurieren

Die MCP-Server-Konfiguration erfolgt in der OpenClaw-Konfigurationsdatei.

### Variante A: openclaw.json

Falls du eine `openclaw.json` nutzt, fuege den `mcp`-Block hinzu:

```json
{
  "mcp": {
    "servers": {
      "ki-system": {
        "url": "http://192.168.12.198:3003/mcp"
      }
    }
  }
}
```

Falls die Datei bereits existiert, den `ki-system`-Eintrag im bestehenden `mcp.servers`-Objekt ergaenzen.

### Variante B: Claude Desktop (claude_desktop_config.json)

Falls du Claude Desktop statt OpenClaw nutzt:

```json
{
  "mcpServers": {
    "ki-system": {
      "url": "http://192.168.12.198:3003/mcp"
    }
  }
}
```

Pfad: `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS)

## Schritt 2: Gateway/Client neu starten

Nach der Konfigurationsaenderung den entsprechenden Prozess neu starten:

```bash
# OpenClaw Gateway
openclaw gateway --restart

# Oder bei Claude Desktop: App beenden und neu oeffnen
```

## Schritt 3: Verifikation

### MCP Inspector (empfohlen)

Der MCP Inspector ist ein Web-UI zum Testen von MCP-Servern:

```bash
npx @modelcontextprotocol/inspector http://192.168.12.198:3003/mcp
```

Oeffnet `http://localhost:6274` im Browser. Dort siehst du alle registrierten Tools und kannst sie manuell aufrufen.

### Manueller curl-Test

```bash
curl -X POST http://192.168.12.198:3003/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}'
```

Erwartet: JSON-Antwort mit Server-Info.

### Chat-Test

Im OpenClaw-Chat (Telegram/WhatsApp/Web):

> "Wie ist der aktuelle Status meines Smart-Home-Systems?"

OpenClaw sollte automatisch `ki_status` aufrufen.

## Verfuegbare Tools (25+)

### Status (3 Tools)
| Tool | Beschreibung |
|---|---|
| `ki_health` | System erreichbar? |
| `ki_status` | Detaillierter Systemstatus |
| `ki_collectors_status` | Status aller Daten-Collectoren |

### Heizung (9 Tools)
| Tool | Beschreibung |
|---|---|
| `ki_heating_get` | Aktuellen Heizungsmodus abrufen |
| `ki_heating_set_mode` | Modus setzen (auto/manual/learning) |
| `ki_heating_insights` | ML-Heizungsempfehlungen |
| `ki_heating_insights_rooms` | Empfehlungen pro Raum |
| `ki_heating_temperature_history` | Temperaturverlauf |
| `ki_heating_statistics` | Statistiken (Laufzeit, Energie) |
| `ki_heating_settings_get` | Konfiguration lesen |
| `ki_heating_settings_set` | Konfiguration schreiben |
| `ki_heating_windows_current` | Fensterzustaende |

### Badezimmer (6 Tools)
| Tool | Beschreibung |
|---|---|
| `ki_bathroom_status` | Feuchtigkeit, Energieverbrauch |
| `ki_bathroom_sensor_timeseries` | Sensorverlauf |
| `ki_bathroom_weekly_overview` | Wochenuebersicht |
| `ki_bathroom_alerts` | Warnungen |
| `ki_bathroom_predictions` | Duschzeit-Vorhersagen |
| `ki_bathroom_next_shower` | Naechste Duschzeit |

### Geraete (2 Tools)
| Tool | Beschreibung |
|---|---|
| `ki_devices_list` | Alle Geraete auflisten |
| `ki_device_control` | Geraet steuern (on/off/set) |

### Garten (5 Tools)
| Tool | Beschreibung |
|---|---|
| `ki_garden_sensor` | Gartensensordaten |
| `ki_garden_avg_temp` | Durchschnittstemperatur |
| `ki_garden_mower_status` | Maehroboter-Status |
| `ki_garden_mower_command` | Maehroboter steuern (start/stop/home) |
| `ki_garden_history` | Historische Daten |

### Beleuchtung (5 Tools)
| Tool | Beschreibung |
|---|---|
| `ki_lighting_all` | Alle Lampen + Status |
| `ki_lighting_room_stats` | Nutzungsstatistiken pro Raum |
| `ki_lighting_forgotten_status` | Vergessen-Modus Status |
| `ki_lighting_forgotten_start` | Vergessen-Modus starten |
| `ki_lighting_forgotten_stop` | Vergessen-Modus stoppen |

### ML (2 Tools)
| Tool | Beschreibung |
|---|---|
| `ki_ml_status` | ML-Modell-Status |
| `ki_ml_predict` | Aktuelle ML-Vorhersagen |

## Beispiel-Prompts fuer OpenClaw

### Status & Ueberwachung
- "Ist mein Smart-Home-System online?"
- "Zeige mir den aktuellen Systemstatus"
- "Welche Collectoren sind aktiv?"

### Heizung
- "Welche Temperatur wird im Wohnzimmer empfohlen?"
- "Stelle die Heizung auf manuellen Modus"
- "Zeige den Temperaturverlauf der letzten 48 Stunden"
- "Sind irgendwo Fenster offen?"
- "Aendere die minimale Temperatur auf 18 Grad"

### Badezimmer
- "Wie hoch ist die Luftfeuchtigkeit im Bad?"
- "Wann wird die naechste Dusche vorhergesagt?"
- "Gibt es Badezimmer-Warnungen?"
- "Zeige die Sensorwerte der letzten 12 Stunden"

### Geraete
- "Liste alle Smart-Home-Geraete auf"
- "Schalte das Licht im Wohnzimmer an"
- "Setze die Temperatur im Schlafzimmer auf 21 Grad"

### Garten
- "Wie ist der Gartenboden?"
- "Was macht der Maehroboter?"
- "Schick den Maehroboter nach Hause"

### Beleuchtung
- "Welche Lampen sind noch an?"
- "Starte den Vergessen-Modus"
- "Wie lange war das Licht im Buero heute an?"

### ML & Vorhersagen
- "Wie gut sind die ML-Modelle trainiert?"
- "Was sagt die KI voraus?"

## Wartung

### Server neustarten
```bash
ssh root@192.168.12.198 'pm2 restart ki-mcp-server'
```

### Logs ansehen
```bash
ssh root@192.168.12.198 'pm2 logs ki-mcp-server --lines 50'
```

### Nach Code-Aenderungen deployen
```bash
# Lokal
git push

# Auf dem Server
ssh root@192.168.12.198 'cd /var/www/KI-SYSTEM && git pull && cd mcp-server && npm run build && pm2 restart ki-mcp-server'
```

### Status pruefen
```bash
ssh root@192.168.12.198 'pm2 status ki-mcp-server'
```

## Architektur

```
OpenClaw/Claude Desktop
       |
       | MCP (Streamable HTTP)
       v
  MCP Server (:3003)
       |
       | HTTP REST
       v
  KI-System Flask API (:8080)
       |
       v
  Home Assistant / Homey Pro
```

Der MCP Server ist eine duenne Schicht, die MCP-Aufrufe in HTTP-Requests an die bestaehende Flask-API uebersetzt. Alle Geschaeftslogik bleibt im Python-Backend.
