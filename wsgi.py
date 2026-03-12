"""
WSGI Entry Point für Gunicorn
Startet die KI-System Web-Anwendung
"""

import sys
import atexit
from pathlib import Path

# Füge src zum Python-Path hinzu
sys.path.insert(0, str(Path(__file__).parent))

from loguru import logger

# Logging konfigurieren (wird sonst nur in main.py gemacht, nicht für Gunicorn)
def _setup_logging():
    log_path = 'logs/ki_system.log'
    Path(log_path).parent.mkdir(parents=True, exist_ok=True)
    logger.remove()
    logger.add(
        sys.stderr,
        level="INFO",
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>"
    )
    logger.add(
        log_path,
        level="INFO",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {message}",
        rotation="10 MB",
        retention="7 days"
    )

_setup_logging()

from src.web.app import WebInterface

# Erstelle die Anwendung
logger.info("Initializing WebInterface for Gunicorn...")
smart_home = WebInterface()

# Flask app für Gunicorn
app = smart_home.app

# Starte Background Services sofort (nicht beim ersten Request)
logger.info("Starting background services for Gunicorn...")
smart_home.start_background_services()

# Registriere Cleanup bei Shutdown
def cleanup():
    """Stoppt alle Background Services beim Shutdown"""
    logger.info("Shutting down background services...")
    smart_home.stop_background_services()

atexit.register(cleanup)


if __name__ == "__main__":
    # Für direkten Start (Entwicklung)
    smart_home.run(host="0.0.0.0", port=8080, debug=True)
