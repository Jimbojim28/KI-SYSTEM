# KI-System MCP Server — Implementierungsplan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Einen MCP-Server (TypeScript/Node 22) bauen, der OpenClaw vollen Lese- und Schreibzugriff auf das KI-Smart-Home-System über 25+ Tools gibt.

**Architecture:** MCP Streamable HTTP Transport auf Port 3001, liest/schreibt via `http://localhost:8080` (KI-System Flask API). Sieben Tool-Gruppen (status, heating, bathroom, devices, garden, lighting, ml) in separaten Dateien. PM2 für Dauerbetrieb auf dem Server.

**Tech Stack:** TypeScript, `@modelcontextprotocol/sdk`, `zod`, Node 22, PM2, `tsx` (dev)

---

## Datei-Übersicht

| Datei | Zweck |
|---|---|
| `mcp-server/package.json` | Dependencies, scripts |
| `mcp-server/tsconfig.json` | TypeScript-Konfiguration |
| `mcp-server/ecosystem.config.cjs` | PM2-Konfiguration |
| `mcp-server/src/server.ts` | MCP-Server-Instanz, HTTP-Transport, alle Tools registrieren |
| `mcp-server/src/api-client.ts` | Einzige Stelle mit `fetch` — alle Calls gegen localhost:8080 |
| `mcp-server/src/tools/status.ts` | ki_health, ki_status, ki_collectors_status |
| `mcp-server/src/tools/heating.ts` | ki_heating_get/set/insights/history/settings/windows |
| `mcp-server/src/tools/bathroom.ts` | ki_bathroom_status/sensor/weekly/alerts/predictions |
| `mcp-server/src/tools/devices.ts` | ki_devices_list, ki_device_control |
| `mcp-server/src/tools/garden.ts` | ki_garden_sensor/temp/mower_status/mower_command/history |
| `mcp-server/src/tools/lighting.ts` | ki_lighting_all/room_stats/forgotten_* |
| `mcp-server/src/tools/ml.ts` | ki_ml_status, ki_ml_predict |

---

## Task 1: Projektgerüst anlegen

**Files:**
- Create: `mcp-server/package.json`
- Create: `mcp-server/tsconfig.json`

- [ ] **Step 1: Verzeichnis anlegen und package.json erstellen**

```bash
cd /Users/shp-art/Documents/Github/KI-SYSTEM
mkdir -p mcp-server/src/tools
```

Datei `mcp-server/package.json` erstellen:

```json
{
  "name": "ki-system-mcp-server",
  "version": "1.0.0",
  "description": "MCP Server for KI Smart Home System",
  "type": "module",
  "main": "dist/server.js",
  "scripts": {
    "build": "tsc",
    "dev": "tsx src/server.ts",
    "start": "node dist/server.js"
  },
  "dependencies": {
    "@modelcontextprotocol/sdk": "^1.10.2",
    "zod": "^3.24.2"
  },
  "devDependencies": {
    "@types/node": "^22.0.0",
    "tsx": "^4.19.3",
    "typescript": "^5.8.3"
  }
}
```

- [ ] **Step 2: tsconfig.json erstellen**

Datei `mcp-server/tsconfig.json`:

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "NodeNext",
    "moduleResolution": "NodeNext",
    "outDir": "./dist",
    "rootDir": "./src",
    "strict": true,
    "esModuleInterop": true,
    "skipLibCheck": true,
    "declaration": true
  },
  "include": ["src/**/*"],
  "exclude": ["node_modules", "dist"]
}
```

- [ ] **Step 3: Dependencies installieren**

```bash
cd mcp-server
npm install
```

Erwartete Ausgabe: `added N packages` ohne Fehler.

- [ ] **Step 4: Commit**

```bash
cd /Users/shp-art/Documents/Github/KI-SYSTEM
git add mcp-server/package.json mcp-server/package-lock.json mcp-server/tsconfig.json
git commit -m "feat(mcp): add project scaffold"
```

---

## Task 2: api-client.ts — Shared Fetch-Wrapper

**Files:**
- Create: `mcp-server/src/api-client.ts`

- [ ] **Step 1: api-client.ts erstellen**

```typescript
// mcp-server/src/api-client.ts
const KI_API_URL = process.env.KI_API_URL ?? "http://localhost:8080";
const KI_API_TOKEN = process.env.KI_API_TOKEN;
const TIMEOUT_MS = 10_000;

export async function kiRequest<T>(
  method: "GET" | "POST" | "DELETE",
  path: string,
  body?: unknown
): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    Accept: "application/json",
  };
  if (KI_API_TOKEN) {
    headers["Authorization"] = `Bearer ${KI_API_TOKEN}`;
  }

  let response: Response;
  try {
    response = await fetch(`${KI_API_URL}${path}`, {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
      signal: controller.signal,
    });
  } catch (err) {
    throw new Error(
      `KI API unreachable at ${KI_API_URL}${path}: ${(err as Error).message}`
    );
  } finally {
    clearTimeout(timer);
  }

  if (!response.ok) {
    const text = await response.text().catch(() => "");
    throw new Error(`KI API error: ${response.status} ${response.statusText} — ${text}`);
  }

  return response.json() as Promise<T>;
}
```

- [ ] **Step 2: Schnelltest mit tsx**

```bash
cd mcp-server
node --input-type=module <<'EOF'
import { kiRequest } from './src/api-client.ts';
// Nur Syntax-Check, kein echter Call
console.log('api-client importiert OK');
EOF
```

Oder einfach per TypeScript-Check:
```bash
npx tsc --noEmit
```
Erwartete Ausgabe: keine Fehler.

- [ ] **Step 3: Commit**

```bash
cd /Users/shp-art/Documents/Github/KI-SYSTEM
git add mcp-server/src/api-client.ts
git commit -m "feat(mcp): add shared api-client with timeout and error handling"
```

---

## Task 3: tools/status.ts

**Files:**
- Create: `mcp-server/src/tools/status.ts`

- [ ] **Step 1: status.ts erstellen**

```typescript
// mcp-server/src/tools/status.ts
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { kiRequest } from "../api-client.js";

export function registerStatusTools(server: McpServer): void {
  server.tool(
    "ki_health",
    "Prüft ob das KI-Smart-Home-System läuft und erreichbar ist.",
    {},
    async () => {
      const data = await kiRequest<unknown>("GET", "/api/health");
      return { content: [{ type: "text", text: JSON.stringify(data, null, 2) }] };
    }
  );

  server.tool(
    "ki_status",
    "Detaillierter Systemstatus: Datenbank, Collectoren, Betriebsmodus (auto/learning/manual), letzte Entscheidungen.",
    {},
    async () => {
      const data = await kiRequest<unknown>("GET", "/api/status");
      return { content: [{ type: "text", text: JSON.stringify(data, null, 2) }] };
    }
  );

  server.tool(
    "ki_collectors_status",
    "Status aller Daten-Collectoren (Home Assistant, Homey, Wetter, Energiepreise).",
    {},
    async () => {
      const data = await kiRequest<unknown>("GET", "/api/collectors/status");
      return { content: [{ type: "text", text: JSON.stringify(data, null, 2) }] };
    }
  );
}
```

- [ ] **Step 2: TypeScript-Check**

```bash
cd mcp-server && npx tsc --noEmit
```
Erwartete Ausgabe: keine Fehler.

- [ ] **Step 3: Commit**

```bash
cd /Users/shp-art/Documents/Github/KI-SYSTEM
git add mcp-server/src/tools/status.ts
git commit -m "feat(mcp): add status tools (ki_health, ki_status, ki_collectors_status)"
```

---

## Task 4: tools/heating.ts

**Files:**
- Create: `mcp-server/src/tools/heating.ts`

- [ ] **Step 1: heating.ts erstellen**

```typescript
// mcp-server/src/tools/heating.ts
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";
import { kiRequest } from "../api-client.js";

export function registerHeatingTools(server: McpServer): void {
  server.tool(
    "ki_heating_get",
    "Aktuellen Heizungsmodus und Status abrufen.",
    {},
    async () => {
      const data = await kiRequest<unknown>("GET", "/api/heating/mode");
      return { content: [{ type: "text", text: JSON.stringify(data, null, 2) }] };
    }
  );

  server.tool(
    "ki_heating_set_mode",
    "Heizungsmodus setzen. mode: 'auto' (KI entscheidet), 'manual' (manuell), 'learning' (nur Daten sammeln).",
    { mode: z.enum(["auto", "manual", "learning"]).describe("Heizungsmodus") },
    async ({ mode }) => {
      const data = await kiRequest<unknown>("POST", "/api/heating/mode", { mode });
      return { content: [{ type: "text", text: JSON.stringify(data, null, 2) }] };
    }
  );

  server.tool(
    "ki_heating_insights",
    "ML-basierte Heizungsempfehlungen für alle Räume abrufen.",
    {},
    async () => {
      const data = await kiRequest<unknown>("GET", "/api/heating/insights");
      return { content: [{ type: "text", text: JSON.stringify(data, null, 2) }] };
    }
  );

  server.tool(
    "ki_heating_insights_rooms",
    "ML-basierte Heizungsempfehlungen pro Raum abrufen.",
    {},
    async () => {
      const data = await kiRequest<unknown>("GET", "/api/heating/insights/rooms");
      return { content: [{ type: "text", text: JSON.stringify(data, null, 2) }] };
    }
  );

  server.tool(
    "ki_heating_temperature_history",
    "Temperaturverlauf abrufen. room: optionaler Raumname, hours: Stunden zurück (Standard 24).",
    {
      room: z.string().optional().describe("Raumname (optional)"),
      hours: z.number().int().min(1).max(168).optional().describe("Stunden zurück, Standard 24"),
    },
    async ({ room, hours }) => {
      const params = new URLSearchParams();
      if (room) params.set("room", room);
      if (hours) params.set("hours", String(hours));
      const qs = params.toString() ? `?${params}` : "";
      const data = await kiRequest<unknown>("GET", `/api/heating/temperature-history${qs}`);
      return { content: [{ type: "text", text: JSON.stringify(data, null, 2) }] };
    }
  );

  server.tool(
    "ki_heating_statistics",
    "Heizungsstatistiken abrufen (Laufzeiten, Energieverbrauch, Effizienz).",
    {},
    async () => {
      const data = await kiRequest<unknown>("GET", "/api/heating/statistics");
      return { content: [{ type: "text", text: JSON.stringify(data, null, 2) }] };
    }
  );

  server.tool(
    "ki_heating_settings_get",
    "Heizungskonfiguration lesen (Temperaturgrenzen, Zeitpläne, Sensor-IDs).",
    {},
    async () => {
      const data = await kiRequest<unknown>("GET", "/api/heating/settings");
      return { content: [{ type: "text", text: JSON.stringify(data, null, 2) }] };
    }
  );

  server.tool(
    "ki_heating_settings_set",
    "Heizungskonfiguration schreiben. settings: Objekt mit den zu ändernden Feldern (nur geänderte Felder senden).",
    { settings: z.record(z.unknown()).describe("Zu ändernde Einstellungen als Objekt") },
    async ({ settings }) => {
      const data = await kiRequest<unknown>("POST", "/api/heating/settings", settings);
      return { content: [{ type: "text", text: JSON.stringify(data, null, 2) }] };
    }
  );

  server.tool(
    "ki_heating_windows_current",
    "Aktuelle Fensterzustände aller Räume abrufen (offen/geschlossen).",
    {},
    async () => {
      const data = await kiRequest<unknown>("GET", "/api/heating/windows/current");
      return { content: [{ type: "text", text: JSON.stringify(data, null, 2) }] };
    }
  );
}
```

- [ ] **Step 2: TypeScript-Check**

```bash
cd mcp-server && npx tsc --noEmit
```

- [ ] **Step 3: Commit**

```bash
cd /Users/shp-art/Documents/Github/KI-SYSTEM
git add mcp-server/src/tools/heating.ts
git commit -m "feat(mcp): add heating tools (get/set mode, insights, history, settings, windows)"
```

---

## Task 5: tools/bathroom.ts

**Files:**
- Create: `mcp-server/src/tools/bathroom.ts`

- [ ] **Step 1: bathroom.ts erstellen**

```typescript
// mcp-server/src/tools/bathroom.ts
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";
import { kiRequest } from "../api-client.js";

export function registerBathroomTools(server: McpServer): void {
  server.tool(
    "ki_bathroom_status",
    "Aktuellen Badezimmerstatus abrufen: Luftfeuchtigkeit, Energieverbrauch, aktive Events.",
    {},
    async () => {
      const data = await kiRequest<unknown>("GET", "/api/luftentfeuchten/energy-stats");
      return { content: [{ type: "text", text: JSON.stringify(data, null, 2) }] };
    }
  );

  server.tool(
    "ki_bathroom_sensor_timeseries",
    "Sensorverlauf des Badezimmers abrufen (Feuchtigkeit, Temperatur). hours: Stunden zurück (Standard 24).",
    {
      hours: z.number().int().min(1).max(168).optional().describe("Stunden zurück, Standard 24"),
    },
    async ({ hours }) => {
      const qs = hours ? `?hours=${hours}` : "";
      const data = await kiRequest<unknown>("GET", `/api/luftentfeuchten/sensor-timeseries${qs}`);
      return { content: [{ type: "text", text: JSON.stringify(data, null, 2) }] };
    }
  );

  server.tool(
    "ki_bathroom_weekly_overview",
    "Wochenübersicht des Badezimmers: Duschfrequenz, durchschnittliche Dauer, Feuchtigkeitsspitzen.",
    {},
    async () => {
      const data = await kiRequest<unknown>("GET", "/api/luftentfeuchten/weekly-overview");
      return { content: [{ type: "text", text: JSON.stringify(data, null, 2) }] };
    }
  );

  server.tool(
    "ki_bathroom_alerts",
    "Aktive Badezimmer-Warnungen abrufen (Schimmelgefahr, Feuchtigkeitsschwellwerte, Gerätefehler).",
    {},
    async () => {
      const data = await kiRequest<unknown>("GET", "/api/luftentfeuchten/alerts");
      return { content: [{ type: "text", text: JSON.stringify(data, null, 2) }] };
    }
  );

  server.tool(
    "ki_bathroom_predictions",
    "ML-basierte Duschzeitvorhersagen für die nächsten Stunden abrufen.",
    {},
    async () => {
      const data = await kiRequest<unknown>("GET", "/api/shower/predictions");
      return { content: [{ type: "text", text: JSON.stringify(data, null, 2) }] };
    }
  );

  server.tool(
    "ki_bathroom_next_shower",
    "Nächste vorhergesagte Duschzeit abrufen.",
    {},
    async () => {
      const data = await kiRequest<unknown>("GET", "/api/shower/next");
      return { content: [{ type: "text", text: JSON.stringify(data, null, 2) }] };
    }
  );
}
```

- [ ] **Step 2: TypeScript-Check**

```bash
cd mcp-server && npx tsc --noEmit
```

- [ ] **Step 3: Commit**

```bash
cd /Users/shp-art/Documents/Github/KI-SYSTEM
git add mcp-server/src/tools/bathroom.ts
git commit -m "feat(mcp): add bathroom tools (status, sensor, weekly, alerts, predictions)"
```

---

## Task 6: tools/devices.ts

**Files:**
- Create: `mcp-server/src/tools/devices.ts`

- [ ] **Step 1: devices.ts erstellen**

```typescript
// mcp-server/src/tools/devices.ts
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";
import { kiRequest } from "../api-client.js";

export function registerDevicesTools(server: McpServer): void {
  server.tool(
    "ki_devices_list",
    "Alle Smart-Home-Geräte mit aktuellem Status, Typ und Plattform auflisten.",
    {},
    async () => {
      const data = await kiRequest<unknown>("GET", "/api/devices");
      return { content: [{ type: "text", text: JSON.stringify(data, null, 2) }] };
    }
  );

  server.tool(
    "ki_device_control",
    "Ein Smart-Home-Gerät steuern. device_id: Geräte-ID (aus ki_devices_list). action: 'on', 'off', oder 'set'. value: optionaler Wert für 'set' (z.B. Temperatur 21.5 oder Helligkeit 80).",
    {
      device_id: z.string().describe("Geräte-ID aus ki_devices_list"),
      action: z.enum(["on", "off", "set"]).describe("Aktion: on, off oder set"),
      value: z.union([z.string(), z.number()]).optional().describe("Wert für 'set' (optional)"),
    },
    async ({ device_id, action, value }) => {
      const body: Record<string, unknown> = { action };
      if (value !== undefined) body["value"] = value;
      const data = await kiRequest<unknown>("POST", `/api/devices/${device_id}/control`, body);
      return { content: [{ type: "text", text: JSON.stringify(data, null, 2) }] };
    }
  );
}
```

- [ ] **Step 2: TypeScript-Check**

```bash
cd mcp-server && npx tsc --noEmit
```

- [ ] **Step 3: Commit**

```bash
cd /Users/shp-art/Documents/Github/KI-SYSTEM
git add mcp-server/src/tools/devices.ts
git commit -m "feat(mcp): add devices tools (list, control)"
```

---

## Task 7: tools/garden.ts

**Files:**
- Create: `mcp-server/src/tools/garden.ts`

- [ ] **Step 1: garden.ts erstellen**

```typescript
// mcp-server/src/tools/garden.ts
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";
import { kiRequest } from "../api-client.js";

export function registerGardenTools(server: McpServer): void {
  server.tool(
    "ki_garden_sensor",
    "Aktuelle Gartensensordaten abrufen (Bodenfeuchte, Temperatur, Helligkeit).",
    {},
    async () => {
      const data = await kiRequest<unknown>("GET", "/api/garten/sensor");
      return { content: [{ type: "text", text: JSON.stringify(data, null, 2) }] };
    }
  );

  server.tool(
    "ki_garden_avg_temp",
    "Durchschnittstemperatur im Garten abrufen.",
    {},
    async () => {
      const data = await kiRequest<unknown>("GET", "/api/garten/avg-temp");
      return { content: [{ type: "text", text: JSON.stringify(data, null, 2) }] };
    }
  );

  server.tool(
    "ki_garden_mower_status",
    "Aktuellen Status des Mähroboters abrufen (läuft, lädt, wartet, Fehler).",
    {},
    async () => {
      const data = await kiRequest<unknown>("GET", "/api/garten/mower/status");
      return { content: [{ type: "text", text: JSON.stringify(data, null, 2) }] };
    }
  );

  server.tool(
    "ki_garden_mower_command",
    "Mähroboter steuern. command: 'start' (mähen), 'stop' (anhalten), 'home' (zur Station).",
    {
      command: z.enum(["start", "stop", "home"]).describe("Befehl für den Mähroboter"),
    },
    async ({ command }) => {
      const data = await kiRequest<unknown>("POST", "/api/garten/mower/command", { command });
      return { content: [{ type: "text", text: JSON.stringify(data, null, 2) }] };
    }
  );

  server.tool(
    "ki_garden_history",
    "Historische Gartensensordaten abrufen.",
    {},
    async () => {
      const data = await kiRequest<unknown>("GET", "/api/garten/history");
      return { content: [{ type: "text", text: JSON.stringify(data, null, 2) }] };
    }
  );
}
```

- [ ] **Step 2: TypeScript-Check**

```bash
cd mcp-server && npx tsc --noEmit
```

- [ ] **Step 3: Commit**

```bash
cd /Users/shp-art/Documents/Github/KI-SYSTEM
git add mcp-server/src/tools/garden.ts
git commit -m "feat(mcp): add garden tools (sensor, avg-temp, mower status/command, history)"
```

---

## Task 8: tools/lighting.ts

**Files:**
- Create: `mcp-server/src/tools/lighting.ts`

- [ ] **Step 1: lighting.ts erstellen**

```typescript
// mcp-server/src/tools/lighting.ts
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { kiRequest } from "../api-client.js";

export function registerLightingTools(server: McpServer): void {
  server.tool(
    "ki_lighting_all",
    "Alle Lampen mit aktuellem Status (an/aus, Helligkeit, Raum) auflisten.",
    {},
    async () => {
      const data = await kiRequest<unknown>("GET", "/api/lighting/all-lights");
      return { content: [{ type: "text", text: JSON.stringify(data, null, 2) }] };
    }
  );

  server.tool(
    "ki_lighting_room_stats",
    "Beleuchtungsnutzungsstatistiken pro Raum abrufen (Einschaltdauer, häufige Zeiten).",
    {},
    async () => {
      const data = await kiRequest<unknown>("GET", "/api/lighting/room-stats");
      return { content: [{ type: "text", text: JSON.stringify(data, null, 2) }] };
    }
  );

  server.tool(
    "ki_lighting_forgotten_status",
    "Status des 'Vergessen-Modus' abrufen — erkennt vergessene Lichter und schaltet sie automatisch aus.",
    {},
    async () => {
      const data = await kiRequest<unknown>("GET", "/api/lighting/forgotten/status");
      return { content: [{ type: "text", text: JSON.stringify(data, null, 2) }] };
    }
  );

  server.tool(
    "ki_lighting_forgotten_start",
    "Vergessen-Modus starten: KI überwacht vergessene Lichter.",
    {},
    async () => {
      const data = await kiRequest<unknown>("POST", "/api/lighting/forgotten/start");
      return { content: [{ type: "text", text: JSON.stringify(data, null, 2) }] };
    }
  );

  server.tool(
    "ki_lighting_forgotten_stop",
    "Vergessen-Modus stoppen.",
    {},
    async () => {
      const data = await kiRequest<unknown>("POST", "/api/lighting/forgotten/stop");
      return { content: [{ type: "text", text: JSON.stringify(data, null, 2) }] };
    }
  );
}
```

- [ ] **Step 2: TypeScript-Check**

```bash
cd mcp-server && npx tsc --noEmit
```

- [ ] **Step 3: Commit**

```bash
cd /Users/shp-art/Documents/Github/KI-SYSTEM
git add mcp-server/src/tools/lighting.ts
git commit -m "feat(mcp): add lighting tools (all-lights, room-stats, forgotten mode)"
```

---

## Task 9: tools/ml.ts

**Files:**
- Create: `mcp-server/src/tools/ml.ts`

- [ ] **Step 1: ml.ts erstellen**

```typescript
// mcp-server/src/tools/ml.ts
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { kiRequest } from "../api-client.js";

export function registerMlTools(server: McpServer): void {
  server.tool(
    "ki_ml_status",
    "Status aller ML-Modelle abrufen (Beleuchtung, Heizung, Energie-Optimierer): trainiert, Genauigkeit, letzte Trainingszeit.",
    {},
    async () => {
      const data = await kiRequest<unknown>("GET", "/api/ml/status");
      return { content: [{ type: "text", text: JSON.stringify(data, null, 2) }] };
    }
  );

  server.tool(
    "ki_ml_predict",
    "Aktuelle ML-Vorhersagen abrufen: welche Lichter sollten an sein, welche Temperatur empfohlen wird.",
    {},
    async () => {
      const data = await kiRequest<unknown>("GET", "/api/predictions");
      return { content: [{ type: "text", text: JSON.stringify(data, null, 2) }] };
    }
  );
}
```

- [ ] **Step 2: TypeScript-Check**

```bash
cd mcp-server && npx tsc --noEmit
```

- [ ] **Step 3: Commit**

```bash
cd /Users/shp-art/Documents/Github/KI-SYSTEM
git add mcp-server/src/tools/ml.ts
git commit -m "feat(mcp): add ML tools (ki_ml_status, ki_ml_predict)"
```

---

## Task 10: server.ts — Hauptdatei

**Files:**
- Create: `mcp-server/src/server.ts`

- [ ] **Step 1: server.ts erstellen**

```typescript
// mcp-server/src/server.ts
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";
import { registerStatusTools } from "./tools/status.js";
import { registerHeatingTools } from "./tools/heating.js";
import { registerBathroomTools } from "./tools/bathroom.js";
import { registerDevicesTools } from "./tools/devices.js";
import { registerGardenTools } from "./tools/garden.js";
import { registerLightingTools } from "./tools/lighting.js";
import { registerMlTools } from "./tools/ml.js";

const PORT = parseInt(process.env.MCP_PORT ?? "3001", 10);

const server = new McpServer({
  name: "ki-system",
  version: "1.0.0",
});

registerStatusTools(server);
registerHeatingTools(server);
registerBathroomTools(server);
registerDevicesTools(server);
registerGardenTools(server);
registerLightingTools(server);
registerMlTools(server);

const transport = new StreamableHTTPServerTransport({
  port: PORT,
  path: "/mcp",
});

await server.connect(transport);
console.log(`KI-System MCP Server running on http://0.0.0.0:${PORT}/mcp`);
```

- [ ] **Step 2: TypeScript-Check und Build**

```bash
cd mcp-server
npx tsc --noEmit  # Syntax-Check
npm run build     # Kompiliert nach dist/
```

Erwartete Ausgabe: keine Fehler, `dist/server.js` und alle `dist/tools/*.js` vorhanden.

- [ ] **Step 3: Lokaler Smoke-Test (Mac, wenn KI-System läuft)**

```bash
cd mcp-server
KI_API_URL=http://192.168.12.198:8080 node dist/server.js
```

Erwartete Ausgabe: `KI-System MCP Server running on http://0.0.0.0:3001/mcp`

Mit Ctrl+C abbrechen.

- [ ] **Step 4: Commit**

```bash
cd /Users/shp-art/Documents/Github/KI-SYSTEM
git add mcp-server/src/server.ts mcp-server/dist/ 2>/dev/null || true
git add mcp-server/src/server.ts
git commit -m "feat(mcp): add main server entry point with all tools registered"
```

---

## Task 11: ecosystem.config.cjs — PM2-Konfiguration

**Files:**
- Create: `mcp-server/ecosystem.config.cjs`

- [ ] **Step 1: ecosystem.config.cjs erstellen**

```javascript
// mcp-server/ecosystem.config.cjs
module.exports = {
  apps: [
    {
      name: "ki-mcp-server",
      script: "dist/server.js",
      cwd: "/var/www/KI-SYSTEM/mcp-server",
      interpreter: "node",
      interpreter_args: "--experimental-vm-modules",
      env: {
        NODE_ENV: "production",
        KI_API_URL: "http://localhost:8080",
        MCP_PORT: "3001",
      },
      watch: false,
      autorestart: true,
      max_restarts: 10,
      min_uptime: "10s",
      log_date_format: "YYYY-MM-DD HH:mm:ss",
    },
  ],
};
```

- [ ] **Step 2: .gitignore für dist/ anlegen**

Datei `mcp-server/.gitignore` erstellen:

```
node_modules/
dist/
```

- [ ] **Step 3: Commit**

```bash
cd /Users/shp-art/Documents/Github/KI-SYSTEM
git add mcp-server/ecosystem.config.cjs mcp-server/.gitignore
git commit -m "feat(mcp): add PM2 ecosystem config"
```

---

## Task 12: Deployment auf den Server

**Voraussetzung:** Alle vorherigen Tasks abgeschlossen, `git push` erfolgt.

- [ ] **Step 1: Code auf Server ziehen**

```bash
ssh root@192.168.12.198 'cd /var/www/KI-SYSTEM && git pull'
```

Erwartete Ausgabe: `Updating ... Fast-forward`

- [ ] **Step 2: Dependencies installieren und bauen**

```bash
ssh root@192.168.12.198 'cd /var/www/KI-SYSTEM/mcp-server && npm install && npm run build'
```

Erwartete Ausgabe: `added N packages` + TypeScript-Build ohne Fehler.

- [ ] **Step 3: PM2-Prozess starten**

```bash
ssh root@192.168.12.198 'cd /var/www/KI-SYSTEM/mcp-server && pm2 start ecosystem.config.cjs && pm2 save'
```

Erwartete Ausgabe: PM2-Tabelle mit `ki-mcp-server` im Status `online`.

- [ ] **Step 4: Health-Check**

```bash
ssh root@192.168.12.198 'curl -s -X POST http://localhost:3001/mcp \
  -H "Content-Type: application/json" \
  -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"tools/list\"}" | python3 -m json.tool | head -30'
```

Erwartete Ausgabe: JSON mit `tools`-Array, mindestens `ki_health` enthalten.

- [ ] **Step 5: Commit + Push**

```bash
cd /Users/shp-art/Documents/Github/KI-SYSTEM
git push
```

---

## Task 13: OpenClaw konfigurieren

- [ ] **Step 1: openclaw.json auf dem Mac anpassen**

Datei `~/.openclaw/openclaw.json` bearbeiten und MCP-Eintrag hinzufügen:

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

Falls die Datei noch nicht existiert oder kein `agent`-Key vorhanden ist, die bestehende Struktur beibehalten und nur den `mcp`-Block ergänzen.

- [ ] **Step 2: OpenClaw Gateway neu starten**

```bash
openclaw gateway --restart
```

Oder wenn als Daemon: Gateway-Prozess neu starten (launchd/systemd).

- [ ] **Step 3: Tools in OpenClaw verifizieren**

Im Chat (z.B. Telegram/WhatsApp) fragen:

> "Was ist der aktuelle Status meines Smart-Home-Systems?"

OpenClaw sollte automatisch `ki_status` aufrufen und die Antwort des KI-Systems zurückgeben.

Alternativ mit MCP Inspector:

```bash
npx @modelcontextprotocol/inspector http://192.168.12.198:3001/mcp
```

Browsert sich zu `http://localhost:5173` — dort alle 25+ Tools sichtbar und manuell aufrufbar.

---

## Plan-Selbstprüfung

### Spec-Coverage
- [x] Status-Tools (ki_health, ki_status, ki_collectors_status) → Task 3
- [x] Heizung read+write (9 Tools) → Task 4
- [x] Badezimmer (6 Tools) → Task 5
- [x] Gerätesteuerung (2 Tools) → Task 6
- [x] Garten (5 Tools) → Task 7
- [x] Beleuchtung (5 Tools) → Task 8
- [x] ML (2 Tools) → Task 9
- [x] Hauptserver + Transport → Task 10
- [x] PM2-Deployment → Tasks 11+12
- [x] OpenClaw-Konfiguration → Task 13
- [x] Serverpfad `/var/www/KI-SYSTEM` (verifiziert) → Tasks 12+11

### Typ-Konsistenz
- `kiRequest<T>` in allen Tool-Dateien identisch importiert aus `../api-client.js`
- `McpServer` aus `@modelcontextprotocol/sdk/server/mcp.js` überall gleich
- `registerXxxTools(server: McpServer): void` — einheitliches Muster in tasks 3–9, in server.ts aufgerufen

### Keine Platzhalter
Alle Schritte enthalten vollständigen Code — keine TBDs.
