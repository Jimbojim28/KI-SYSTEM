import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";
import { kiRequest } from "../api-client.js";

export function registerDevicesTools(server: McpServer): void {
  server.tool(
    "ki_devices_list",
    "Alle Smart-Home-Geraete mit aktuellem Status, Typ und Plattform auflisten.",
    {},
    async () => {
      const data = await kiRequest<unknown>("GET", "/api/devices");
      return { content: [{ type: "text", text: JSON.stringify(data, null, 2) }] };
    }
  );

  server.tool(
    "ki_device_control",
    "Ein Smart-Home-Geraet steuern. device_id: Geraete-ID (aus ki_devices_list). action: 'on', 'off', oder 'set'. value: optionaler Wert fuer 'set' (z.B. Temperatur 21.5 oder Helligkeit 80).",
    {
      device_id: z.string().describe("Geraete-ID aus ki_devices_list"),
      action: z.enum(["on", "off", "set"]).describe("Aktion: on, off oder set"),
      value: z.union([z.string(), z.number()]).optional().describe("Wert fuer 'set' (optional)"),
    },
    async ({ device_id, action, value }) => {
      const body: Record<string, unknown> = { action };
      if (value !== undefined) body["value"] = value;
      const data = await kiRequest<unknown>("POST", `/api/devices/${device_id}/control`, body);
      return { content: [{ type: "text", text: JSON.stringify(data, null, 2) }] };
    }
  );
}
