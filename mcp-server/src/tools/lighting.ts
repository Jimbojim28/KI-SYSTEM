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
    "Beleuchtungsnutzungsstatistiken pro Raum abrufen (Einschaltdauer, haeufige Zeiten).",
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
    "Vergessen-Modus starten: KI ueberwacht vergessene Lichter.",
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
