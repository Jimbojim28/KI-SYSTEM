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
