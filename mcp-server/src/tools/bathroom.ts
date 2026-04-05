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
    "Sensorverlauf des Badezimmers abrufen (Feuchtigkeit, Temperatur). hours: Stunden zurueck (Standard 24).",
    {
      hours: z.number().int().min(1).max(168).optional().describe("Stunden zurueck, Standard 24"),
    },
    async ({ hours }) => {
      const qs = hours ? `?hours=${hours}` : "";
      const data = await kiRequest<unknown>("GET", `/api/luftentfeuchten/sensor-timeseries${qs}`);
      return { content: [{ type: "text", text: JSON.stringify(data, null, 2) }] };
    }
  );

  server.tool(
    "ki_bathroom_weekly_overview",
    "Wochenuebersicht des Badezimmers: Duschfrequenz, durchschnittliche Dauer, Feuchtigkeitsspitzen.",
    {},
    async () => {
      const data = await kiRequest<unknown>("GET", "/api/luftentfeuchten/weekly-overview");
      return { content: [{ type: "text", text: JSON.stringify(data, null, 2) }] };
    }
  );

  server.tool(
    "ki_bathroom_alerts",
    "Aktive Badezimmer-Warnungen abrufen (Schimmelgefahr, Feuchtigkeitsschwellwerte, Geraetefehler).",
    {},
    async () => {
      const data = await kiRequest<unknown>("GET", "/api/luftentfeuchten/alerts");
      return { content: [{ type: "text", text: JSON.stringify(data, null, 2) }] };
    }
  );

  server.tool(
    "ki_bathroom_predictions",
    "ML-basierte Duschzeitvorhersagen fuer die naechsten Stunden abrufen.",
    {},
    async () => {
      const data = await kiRequest<unknown>("GET", "/api/shower/predictions");
      return { content: [{ type: "text", text: JSON.stringify(data, null, 2) }] };
    }
  );

  server.tool(
    "ki_bathroom_next_shower",
    "Naechste vorhergesagte Duschzeit abrufen.",
    {},
    async () => {
      const data = await kiRequest<unknown>("GET", "/api/shower/next");
      return { content: [{ type: "text", text: JSON.stringify(data, null, 2) }] };
    }
  );
}
