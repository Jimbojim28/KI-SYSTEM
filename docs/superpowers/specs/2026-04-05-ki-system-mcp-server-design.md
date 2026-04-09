# KI-System MCP Server — Design-Spezifikation

**Datum:** 2026-04-05  
**Status:** Genehmigt  

---

## Ziel

Einen MCP-Server (Model Context Protocol) bereitstellen, der OpenClaw (oder anderen MCP-Clients) vollen Lese- und Schreibzugriff auf das KI-Smart-Home-System gibt. OpenClaw kann damit per natürlicher Sprache den Heizungsmodus setzen, Sensordaten abfragen, Geräte steuern und vieles mehr.

---

## Systemarchitektur

```
OpenClaw (Mac, ~/.openclaw/openclaw.json)
  ↕  HTTP/SSE (MCP Streamable HTTP Transport, Port 3001)
MCP-Server (192.168.12.198:3001, TypeScript/Node 22)
  ↕  HTTP REST (localhost:8080)
KI-SYSTEM Flask API (192.168.12.198:8080)
  ↕  SQLite / Home Assistant / Homey
```

Der MCP-Server legt sich **zwischen** OpenClaw und die KI-System-API. Er übersetzt MCP-Tool-Calls in HTTP-Requests an `localhost:8080` und liefert strukturierte Antworten zurück.

Transport: **Streamable HTTP** (MCP 2025-03 Standard) — kein STDIO, weil der Server im Netzwerk erreichbar sein muss.

---

## Dateistruktur

```
mcp-server/
  src/
    server.ts             # Einstiegspunkt: MCP-Server-Instanz, HTTP-Transport, Port
    api-client.ts         # Shared fetch-Wrapper: alle Calls gegen localhost:8080
    tools/
      status.ts           # ki_health, ki_status, ki_collectors_status
      heating.ts          # ki_heating_get, ki_heating_set_mode, ki_heating_insights,
                          # ki_heating_temperature_history, ki_heating_settings_get,
                          # ki_heating_settings_set, ki_heating_windows_current
      bathroom.ts         # ki_bathroom_status, ki_bathroom_sensor_timeseries,
                          # ki_bathroom_weekly_overview, ki_bathroom_alerts,
                          # ki_bathroom_predictions
      devices.ts          # ki_devices_list, ki_device_control
      garden.ts           # ki_garden_sensor, ki_garden_mower_status,
                          # ki_garden_mower_command
      lighting.ts         # ki_lighting_all, ki_lighting_forgotten_status,
                          # ki_lighting_room_stats
      ml.ts               # ki_ml_status, ki_ml_predict
  package.json
  tsconfig.json
  ecosystem.config.cjs    # PM2-Konfiguration
```

**Bewusste Entscheidung:** Jede Domäne bekommt eine eigene Datei in `tools/`. `server.ts` importiert und registriert alle Tools. `api-client.ts` ist die einzige Stelle mit `fetch`-Logik.

---

## MCP-Tools (vollständige Liste)

### Status-Gruppe (`tools/status.ts`)

| Tool-Name | Methode | Endpunkt | Beschreibung |
|---|---|---|---|
| `ki_health` | GET | `/api/health` | System-Health-Check (ok/error) |
| `ki_status` | GET | `/api/status` | Detaillierter Systemstatus (DB, Collectoren, Mode) |
| `ki_collectors_status` | GET | `/api/collectors/status` | Status aller Daten-Collectoren |

### Heizung-Gruppe (`tools/heating.ts`)

| Tool-Name | Methode | Endpunkt | Beschreibung |
|---|---|---|---|
| `ki_heating_get` | GET | `/api/heating/mode` | Aktueller Heizungsmodus + Info |
| `ki_heating_set_mode` | POST | `/api/heating/mode` | Modus setzen (auto/manual/learning) |
| `ki_heating_insights` | GET | `/api/heating/insights` | ML-basierte Heizungsempfehlungen |
| `ki_heating_insights_rooms` | GET | `/api/heating/insights/rooms` | Einblicke pro Raum |
| `ki_heating_temperature_history` | GET | `/api/heating/temperature-history` | Temperaturverlauf (Query: room, hours) |
| `ki_heating_statistics` | GET | `/api/heating/statistics` | Heizungsstatistiken |
| `ki_heating_settings_get` | GET | `/api/heating/settings` | Heizungskonfiguration lesen |
| `ki_heating_settings_set` | POST | `/api/heating/settings` | Heizungskonfiguration schreiben |
| `ki_heating_windows_current` | GET | `/api/heating/windows/current` | Aktuelle Fensterzustände |

### Badezimmer-Gruppe (`tools/bathroom.ts`)

| Tool-Name | Methode | Endpunkt | Beschreibung |
|---|---|---|---|
| `ki_bathroom_status` | GET | `/api/luftentfeuchten/energy-stats` | Aktueller Badezimmerstatus inkl. Energieverbrauch |
| `ki_bathroom_sensor_timeseries` | GET | `/api/luftentfeuchten/sensor-timeseries` | Sensorverlauf (Feuchtigkeit, Temp) — Query: hours |
| `ki_bathroom_weekly_overview` | GET | `/api/luftentfeuchten/weekly-overview` | Wochenübersicht |
| `ki_bathroom_alerts` | GET | `/api/luftentfeuchten/alerts` | Aktive Warnungen (Schimmelgefahr etc.) |
| `ki_bathroom_predictions` | GET | `/api/shower/predictions` | Duschzeitvorhersage (ML) |
| `ki_bathroom_next_shower` | GET | `/api/shower/next` | Nächste vorhergesagte Duschzeit |

### Geräte-Gruppe (`tools/devices.ts`)

| Tool-Name | Methode | Endpunkt | Beschreibung |
|---|---|---|---|
| `ki_devices_list` | GET | `/api/devices` | Alle Geräte mit Status |
| `ki_device_control` | POST | `/api/devices/{device_id}/control` | Gerät steuern (on/off/value) |

### Garten-Gruppe (`tools/garden.ts`)

| Tool-Name | Methode | Endpunkt | Beschreibung |
|---|---|---|---|
| `ki_garden_sensor` | GET | `/api/garten/sensor` | Aktuelle Gartensensordaten |
| `ki_garden_avg_temp` | GET | `/api/garten/avg-temp` | Durchschnittstemperatur Garten |
| `ki_garden_mower_status` | GET | `/api/garten/mower/status` | Mähroboter-Status |
| `ki_garden_mower_command` | POST | `/api/garten/mower/command` | Mähroboter steuern (start/stop/home) |
| `ki_garden_history` | GET | `/api/garten/history` | Garten-Sensordaten Verlauf |

### Beleuchtung-Gruppe (`tools/lighting.ts`)

| Tool-Name | Methode | Endpunkt | Beschreibung |
|---|---|---|---|
| `ki_lighting_all` | GET | `/api/lighting/all-lights` | Alle Lampen + Status |
| `ki_lighting_room_stats` | GET | `/api/lighting/room-stats` | Nutzungsstatistiken pro Raum |
| `ki_lighting_forgotten_status` | GET | `/api/lighting/forgotten/status` | "Vergessen-Modus"-Status |
| `ki_lighting_forgotten_start` | POST | `/api/lighting/forgotten/start` | Vergessen-Modus starten |
| `ki_lighting_forgotten_stop` | POST | `/api/lighting/forgotten/stop` | Vergessen-Modus stoppen |

### ML-Gruppe (`tools/ml.ts`)

| Tool-Name | Methode | Endpunkt | Beschreibung |
|---|---|---|---|
| `ki_ml_status` | GET | `/api/ml/status` | Status aller ML-Modelle |
| `ki_ml_predict` | GET | `/api/predictions` | Aktuelle ML-Vorhersagen |

---

## api-client.ts — Schnittstelle

```typescript
// Alle Tool-Dateien importieren nur diese Funktion
export async function kiRequest<T>(
  method: "GET" | "POST" | "DELETE",
  path: string,
  body?: unknown
): Promise<T>
```

- Base URL: `http://localhost:8080` (konfigurierbar via `KI_API_URL` env-Variable)
- Timeout: 10 Sekunden
- Bei HTTP-Fehler: Wirft `Error` mit Status und Body — MCP gibt das als Tool-Error zurück
- Kein Auth: KI-System läuft lokal, kein Token nötig (optional via `KI_API_TOKEN` env-Variable für künftige Nutzung)

---

## server.ts — Aufbau

```typescript
const server = new McpServer({ name: "ki-system", version: "1.0.0" });

// Tools registrieren
registerStatusTools(server);
registerHeatingTools(server);
registerBathroomTools(server);
registerDevicesTools(server);
registerGardenTools(server);
registerLightingTools(server);
registerMlTools(server);

// Streamable HTTP Transport
const transport = new StreamableHTTPServerTransport({ port: 3001 });
await server.connect(transport);
```

---

## PM2-Konfiguration (`ecosystem.config.cjs`)

```javascript
module.exports = {
  apps: [{
    name: "ki-mcp-server",
    script: "dist/server.js",
    cwd: "/root/KI-SYSTEM/mcp-server",
    env: {
      KI_API_URL: "http://localhost:8080",
      MCP_PORT: "3001",
      NODE_ENV: "production"
    },
    watch: false,
    autorestart: true
  }]
};
```

---

## OpenClaw-Konfiguration (nach Deployment)

Eintrag in `~/.openclaw/openclaw.json` auf dem Mac:

```json
{
  "mcp": {
    "servers": {
      "ki-system": {
        "url": "http://192.168.12.198:3001/mcp"
      }
    }
  }
}
```

---

## Build-Prozess

```bash
cd mcp-server
npm install
npm run build   # tsc → dist/
pm2 start ecosystem.config.cjs
pm2 save
```

### package.json Scripts

```json
{
  "scripts": {
    "build": "tsc",
    "dev": "tsx src/server.ts",
    "start": "node dist/server.js"
  }
}
```

---

## Fehlerbehandlung

- Netzwerkfehler zu `localhost:8080`: Tool gibt `isError: true` + Fehlermeldung zurück — OpenClaw sieht den Fehler im Chat
- Unbekannte Tool-Parameter: Zod-Validierung im MCP-SDK wirft vor dem API-Call
- KI-System gibt 4xx/5xx: `kiRequest` wirft `Error("KI API error: 404 - Not Found")` — wird als Tool-Error weitergeleitet

---

## Testplan

1. **Unit:** `api-client.ts` mit gemocktem `fetch` — prüft Timeout, Error-Handling, Method-Weiterleitung
2. **Integration:** Echte Calls gegen `localhost:8080` in CI-ähnlichem Umfeld (nur wenn Server läuft)
3. **Manuell:** `npx @modelcontextprotocol/inspector http://192.168.12.198:3001/mcp` — zeigt alle Tools und erlaubt manuelles Aufrufen

---

## Nicht im Scope

- Authentifizierung/Autorisierung (lokales Netzwerk, kein Bedarf)
- Caching (KI-System ist schnell genug)
- MCP Resources oder Prompts (nur Tools)
- Webhook-Push von KI-System zu OpenClaw (separates Feature)
