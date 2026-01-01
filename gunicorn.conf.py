# Gunicorn configuration file for KI-System
# https://docs.gunicorn.org/en/stable/settings.html

import multiprocessing

# Server socket
bind = "0.0.0.0:8080"
backlog = 2048

# Worker processes
# Für Server mit 2GB RAM: nur 1 Worker mit gevent für Async-Parallelität
workers = 1  # Reduziert auf 1 Worker wegen begrenztem RAM
worker_class = "gevent"  # Async worker für bessere Parallelität ohne extra RAM
worker_connections = 50  # Max gleichzeitige Verbindungen pro Worker

# Timeouts
timeout = 120  # Worker timeout (für lange DB-Queries)
graceful_timeout = 30  # Zeit für graceful shutdown
keepalive = 5  # Keep-alive Verbindungen

# Restart workers periodisch um Memory Leaks zu vermeiden
max_requests = 500  # Reduziert für bessere Memory-Verwaltung
max_requests_jitter = 50

# Logging
accesslog = "logs/gunicorn-access.log"
errorlog = "logs/gunicorn-error.log"
loglevel = "info"
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'

# Process naming
proc_name = "ki-smart-home"

# Server mechanics
daemon = False
pidfile = None
umask = 0
user = None
group = None
tmp_upload_dir = None

# Hooks für Startup/Shutdown
def on_starting(server):
    """Called just before the master process is initialized."""
    pass

def on_exit(server):
    """Called just before exiting Gunicorn."""
    pass

def worker_exit(server, worker):
    """Called when a worker exits."""
    pass
