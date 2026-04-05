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
    "Aktuellen Status des Maehroboters abrufen (laeuft, laedt, wartet, Fehler).",
    {},
    async () => {
      const data = await kiRequest<unknown>("GET", "/api/garten/mower/status");
      return { content: [{ type: "text", text: JSON.stringify(data, null, 2) }] };
    }
  );

  server.tool(
    "ki_garden_mower_command",
    "Maehroboter steuern. command: 'start' (maehen), 'stop' (anhalten), 'home' (zur Station).",
    {
      command: z.enum(["start", "stop", "home"]).describe("Befehl fuer den Maehroboter"),
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
