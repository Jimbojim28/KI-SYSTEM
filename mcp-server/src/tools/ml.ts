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
