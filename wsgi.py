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
