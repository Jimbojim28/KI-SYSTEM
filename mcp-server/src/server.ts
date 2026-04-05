import http from "node:http";
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
const MCP_PATH = "/mcp";

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
  sessionIdGenerator: undefined,
});

await server.connect(transport);

const httpServer = http.createServer(async (req, res) => {
  if (req.url?.startsWith(MCP_PATH)) {
    await transport.handleRequest(req, res);
  } else {
    res.writeHead(404).end("Not found");
  }
});

httpServer.listen(PORT, () => {
  console.log(`KI-System MCP Server running on http://0.0.0.0:${PORT}${MCP_PATH}`);
});
