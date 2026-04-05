import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { kiRequest } from "../api-client.js";

export function registerStatusTools(server: McpServer): void {
  server.tool(
    "ki_health",
    "Prueft ob das KI-Smart-Home-System laeuft und erreichbar ist.",
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
