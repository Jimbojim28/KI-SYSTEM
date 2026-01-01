module.exports = {
  apps: [{
    name: 'ki-smart-home',
    script: './venv/bin/gunicorn',
    args: '-c gunicorn.conf.py wsgi:app',
    interpreter: 'none',  // Gunicorn ist bereits ein Python-Wrapper

    // Instances (Gunicorn managt eigene Worker, PM2 nur 1 Instanz)
    instances: 1,
    exec_mode: 'fork',

    // Auto-restart
    autorestart: true,
    watch: false,
    max_memory_restart: '800M',  // Erhöht für Gunicorn + Worker

    // Restart delay
    restart_delay: 4000,
    min_uptime: '30s',  // Erhöht, da Gunicorn länger zum Starten braucht
    max_restarts: 10,

    // Logs
    error_file: './logs/pm2-error.log',
    out_file: './logs/pm2-out.log',
    log_date_format: 'YYYY-MM-DD HH:mm:ss',
    merge_logs: true,

    // Environment
    env: {
      NODE_ENV: 'production',
      PYTHONUNBUFFERED: '1'
    },

    // Advanced
    listen_timeout: 30000,  // Erhöht für Gunicorn startup
    kill_timeout: 10000,    // Erhöht für graceful shutdown
    wait_ready: false,

    // Cron restart (täglich um 4:00 Uhr)
    cron_restart: '0 4 * * *'
  }]
};
