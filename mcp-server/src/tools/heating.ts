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
    "ML-basierte Heizungsempfehlungen fuer alle Raeume abrufen.",
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
    "Temperaturverlauf abrufen. room: optionaler Raumname, hours: Stunden zurueck (Standard 24).",
    {
      room: z.string().optional().describe("Raumname (optional)"),
      hours: z.number().int().min(1).max(168).optional().describe("Stunden zurueck, Standard 24"),
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
    "Heizungskonfiguration lesen (Temperaturgrenzen, Zeitplaene, Sensor-IDs).",
    {},
    async () => {
      const data = await kiRequest<unknown>("GET", "/api/heating/settings");
      return { content: [{ type: "text", text: JSON.stringify(data, null, 2) }] };
    }
  );

  server.tool(
    "ki_heating_settings_set",
    "Heizungskonfiguration schreiben. settings: Objekt mit den zu aendernden Feldern (nur geaenderte Felder senden).",
    { settings: z.record(z.unknown()).describe("Zu aendernde Einstellungen als Objekt") },
    async ({ settings }) => {
      const data = await kiRequest<unknown>("POST", "/api/heating/settings", settings);
      return { content: [{ type: "text", text: JSON.stringify(data, null, 2) }] };
    }
  );

  server.tool(
    "ki_heating_windows_current",
    "Aktuelle Fensterzustaende aller Raeume abrufen (offen/geschlossen).",
    {},
    async () => {
      const data = await kiRequest<unknown>("GET", "/api/heating/windows/current");
      return { content: [{ type: "text", text: JSON.stringify(data, null, 2) }] };
    }
  );
}
