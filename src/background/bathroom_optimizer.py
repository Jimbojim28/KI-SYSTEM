"""
Background Task: Automatische Optimierung der Badezimmer-Parameter
Läuft täglich und optimiert Schwellwerte basierend auf gelernten Daten
"""

import threading
import time
import json
from pathlib import Path
from datetime import datetime
from loguru import logger
from src.decision_engine.bathroom_automation import BathroomAutomation


class BathroomOptimizer:
    """
    Background-Prozess für automatische Optimierung

    - Läuft täglich um 3:00 Uhr
    - Optimiert Schwellwerte wenn genug Daten vorhanden
    - Speichert Ergebnisse in Config
    """

    def __init__(self, interval_hours: int = 24, run_at_hour: int = 3):
        """
        Args:
            interval_hours: Intervall in Stunden (default: 24 = täglich)
            run_at_hour: Uhrzeit für tägliche Ausführung (default: 3 = 3:00 Uhr)
        """
        self.interval_hours = interval_hours
        self.run_at_hour = run_at_hour
        self.running = False
        self.thread = None
        self.last_run = None

    def start(self):
        """Startet den Background-Prozess"""
        if self.running:
            logger.warning("BathroomOptimizer is already running")
            return

        self.running = True
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()
        logger.info(f"BathroomOptimizer started (runs daily at {self.run_at_hour}:00)")

    def stop(self):
        """Stoppt den Background-Prozess"""
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
        logger.info("BathroomOptimizer stopped")

    def _run_loop(self):
        """Haupt-Loop des Background-Prozesses"""
        while self.running:
            try:
                # Prüfe ob es Zeit für Optimierung ist
                if self._should_run_now():
                    logger.info("🤖 Starting automatic optimization...")
                    self._run_optimization()
                    self.last_run = datetime.now()

                # Warte 1 Stunde bevor nächster Check
                time.sleep(3600)

            except Exception as e:
                logger.error(f"Error in BathroomOptimizer loop: {e}")
                time.sleep(60)  # Bei Fehler 1 Minute warten

    def _should_run_now(self) -> bool:
        """
        Prüft ob jetzt optimiert werden soll

        Returns:
            True wenn es Zeit ist zu optimieren
        """
        now = datetime.now()

        # Prüfe ob bereits heute gelaufen
        if self.last_run:
            if self.last_run.date() == now.date():
                return False

        # Prüfe ob es die richtige Stunde ist
        if now.hour == self.run_at_hour:
            return True

        return False

    def _run_optimization(self):
        """Führt die Optimierung durch"""
        try:
            from src.utils.sensor_helper import get_bathroom_config
            
            # Lade Config aus zentraler Zuordnung
            config = get_bathroom_config()
            
            if not config:
                logger.warning("No bathroom config found, skipping optimization")
                return

            # Prüfe ob enabled
            if not config.get('enabled', False):
                logger.info("Bathroom automation disabled, skipping optimization")
                return

            # Initialisiere mit Learning enabled
            bathroom = BathroomAutomation(config, enable_learning=True)

            # Führe Optimierung durch
            result = bathroom.optimize_parameters(
                days_back=30,
                min_confidence=0.7
            )

            if not result:
                logger.info("Optimization skipped (not enough data or disabled)")
                return

            if result.get('success'):
                # Update Config mit neuen Werten
                config['humidity_threshold_high'] = result['new_values']['humidity_high']
                config['humidity_threshold_low'] = result['new_values']['humidity_low']

                with open(self.config_file, 'w') as f:
                    json.dump(config, f, indent=2)

                logger.info(
                    f"✨ Automatic optimization successful! "
                    f"High: {result['old_values']['humidity_high']}% → {result['new_values']['humidity_high']}%, "
                    f"Low: {result['old_values']['humidity_low']}% → {result['new_values']['humidity_low']}% "
                    f"(Confidence: {result['confidence']:.2f}, Events: {result['based_on_events']})"
                )
            else:
                logger.info(f"Optimization not applied: {result.get('reason', 'Unknown reason')}")

        except Exception as e:
            logger.error(f"Error during automatic optimization: {e}")

    def force_run(self):
        """Erzwingt sofortige Optimierung (für manuellen Aufruf)"""
        logger.info("🤖 Forcing optimization run...")
        self._run_optimization()

    def get_status(self) -> dict:
        """
        Gibt Status des Optimizers zurück

        Returns:
            Dict mit Status-Informationen
        """
        return {
            'running': self.running,
            'last_run': self.last_run.isoformat() if self.last_run else None,
            'interval_hours': self.interval_hours,
            'run_at_hour': self.run_at_hour,
            'next_run_estimate': self._estimate_next_run()
        }

    def _estimate_next_run(self) -> str:
        """Schätzt wann die nächste Optimierung läuft"""
        now = datetime.now()

        # Nächster Run ist um run_at_hour Uhr
        next_run = now.replace(hour=self.run_at_hour, minute=0, second=0, microsecond=0)

        # Wenn heute schon vorbei, dann morgen
        if next_run <= now:
            from datetime import timedelta
            next_run += timedelta(days=1)

        return next_run.isoformat()
