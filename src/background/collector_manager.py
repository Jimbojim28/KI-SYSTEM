"""
Collector Manager - Orchestriert alle Background Data Collectors
Zentrales Management für kontinuierliche Datensammlung
"""

import threading
import time
from typing import Dict, List, Optional
from datetime import datetime
from loguru import logger

from .heating_data_collector import HeatingDataCollector
from .lighting_data_collector import LightingDataCollector
from .window_data_collector import WindowDataCollector
from .temperature_data_collector import TemperatureDataCollector
from .bathroom_data_collector import BathroomDataCollector
from .bathroom_optimizer import BathroomOptimizer
from .ml_auto_trainer import MLAutoTrainer
from .database_maintenance import DatabaseMaintenance

from ..utils.config_loader import ConfigLoader
from ..utils.config_manager import get_config_value, get_config_section


class CollectorManager:
    """
    Verwaltet alle Background Collectors

    Features:
    - Start/Stop aller Collectors
    - Health Monitoring
    - Automatisches Restart bei Fehlern
    - Konfigurierbare Intervalle
    """

    def __init__(self, config_path: str = None):
        """
        Args:
            config_path: Pfad zur config.yaml (optional)
        """
        self.config = ConfigLoader(config_path)
        self.collectors: Dict[str, object] = {}
        self.collector_threads: Dict[str, threading.Thread] = {}
        self.running = False
        self.stop_event = threading.Event()

        # Initialisiere alle Collectors basierend auf Konfiguration
        self._initialize_collectors()

        logger.info(f"CollectorManager initialized with {len(self.collectors)} collectors")

    def _initialize_collectors(self):
        """Initialisiert alle aktivierten Collectors"""

        # 1. Heizungs-Daten Collector
        if get_config_value('collectors.heating.enabled', True):
            interval = get_config_value('collectors.heating.interval', 60)
            self.collectors['heating'] = HeatingDataCollector(
                config_path=None,
                interval=interval
            )
            logger.info(f"Heating collector initialized (interval: {interval}s)")

        # 2. Beleuchtungs-Daten Collector
        if get_config_value('collectors.lighting.enabled', True):
            interval = get_config_value('collectors.lighting.interval', 60)
            self.collectors['lighting'] = LightingDataCollector(
                config_path=None,
                interval=interval
            )
            logger.info(f"Lighting collector initialized (interval: {interval}s)")

        # 3. Fenster-Daten Collector
        if get_config_value('collectors.windows.enabled', True):
            interval = get_config_value('collectors.windows.interval', 60)
            self.collectors['windows'] = WindowDataCollector(
                config_path=None,
                interval=interval
            )
            logger.info(f"Window collector initialized (interval: {interval}s)")

        # 4. Temperatur-Daten Collector
        if get_config_value('collectors.temperature.enabled', True):
            interval = get_config_value('collectors.temperature.interval', 60)
            self.collectors['temperature'] = TemperatureDataCollector(
                config_path=None,
                interval=interval
            )
            logger.info(f"Temperature collector initialized (interval: {interval}s)")

        # 5. Badezimmer-Daten Collector
        if get_config_value('collectors.bathroom.enabled', False):
            interval = get_config_value('collectors.bathroom.interval', 60)
            try:
                self.collectors['bathroom'] = BathroomDataCollector(
                    config_path=None,
                    interval=interval
                )
                logger.info(f"Bathroom collector initialized (interval: {interval}s)")
            except Exception as e:
                logger.warning(f"Bathroom collector not available: {e}")

        # 6. ML Auto-Trainer (täglich)
        if get_config_value('ml_auto_trainer.enabled', True):
            training_time = get_config_value('ml_auto_trainer.training_time', '03:00')
            try:
                self.collectors['ml_trainer'] = MLAutoTrainer(
                    config_path=None,
                    training_time=training_time
                )
                logger.info(f"ML Auto-Trainer initialized (time: {training_time})")
            except Exception as e:
                logger.warning(f"ML Auto-Trainer not available: {e}")

        # 7. Badezimmer-Optimizer (täglich)
        if get_config_value('bathroom_optimizer.enabled', False):
            optimization_time = get_config_value('bathroom_optimizer.optimization_time', '03:30')
            try:
                self.collectors['bathroom_optimizer'] = BathroomOptimizer(
                    config_path=None,
                    optimization_time=optimization_time
                )
                logger.info(f"Bathroom Optimizer initialized (time: {optimization_time})")
            except Exception as e:
                logger.warning(f"Bathroom Optimizer not available: {e}")

        # 8. Database Maintenance (täglich)
        if get_config_value('database_maintenance.enabled', True):
            cleanup_time = get_config_value('database_maintenance.cleanup_time', '04:00')
            retention_days = get_config_value('database_maintenance.retention_days', 90)
            try:
                self.collectors['db_maintenance'] = DatabaseMaintenance(
                    config_path=None,
                    cleanup_time=cleanup_time,
                    retention_days=retention_days
                )
                logger.info(f"Database Maintenance initialized (time: {cleanup_time}, retention: {retention_days} days)")
            except Exception as e:
                logger.warning(f"Database Maintenance not available: {e}")

    def start_all(self):
        """Startet alle Collectors"""
        if self.running:
            logger.warning("CollectorManager already running")
            return

        logger.info("Starting all collectors...")
        self.running = True
        self.stop_event.clear()

        for name, collector in self.collectors.items():
            try:
                # Starte Collector in separatem Thread
                thread = threading.Thread(
                    target=self._run_collector,
                    args=(name, collector),
                    name=f"Collector-{name}",
                    daemon=True
                )
                thread.start()
                self.collector_threads[name] = thread
                logger.info(f"Started collector: {name}")
            except Exception as e:
                logger.error(f"Failed to start collector {name}: {e}")

        logger.info(f"All collectors started ({len(self.collector_threads)} threads)")

    def _run_collector(self, name: str, collector: object):
        """
        Führt einen Collector in einer Schleife aus

        Args:
            name: Name des Collectors
            collector: Collector-Instanz
        """
        logger.info(f"Collector thread started: {name}")

        while not self.stop_event.is_set():
            try:
                # Rufe die run() Methode des Collectors auf
                if hasattr(collector, 'run'):
                    collector.run()
                elif hasattr(collector, 'collect'):
                    collector.collect()
                else:
                    logger.error(f"Collector {name} has no run() or collect() method")
                    break

                # Warte auf nächsten Zyklus oder Stop-Signal
                # Nutze Collector-Intervall falls vorhanden
                if hasattr(collector, 'interval'):
                    self.stop_event.wait(timeout=collector.interval)
                else:
                    self.stop_event.wait(timeout=60)  # Default 60s

            except Exception as e:
                logger.error(f"Error in collector {name}: {e}")
                # Bei Fehler: kurz warten und dann neu versuchen
                self.stop_event.wait(timeout=10)

        logger.info(f"Collector thread stopped: {name}")

    def stop_all(self):
        """Stoppt alle Collectors"""
        if not self.running:
            logger.warning("CollectorManager not running")
            return

        logger.info("Stopping all collectors...")
        self.stop_event.set()
        self.running = False

        # Warte auf alle Threads (max 30 Sekunden)
        for name, thread in self.collector_threads.items():
            thread.join(timeout=30)
            if thread.is_alive():
                logger.warning(f"Collector {name} did not stop gracefully")
            else:
                logger.info(f"Stopped collector: {name}")

        self.collector_threads.clear()
        logger.info("All collectors stopped")

    def get_status(self) -> Dict:
        """
        Holt Status aller Collectors

        Returns:
            Dict mit Status-Informationen
        """
        status = {
            'running': self.running,
            'timestamp': datetime.now().isoformat(),
            'collectors': {}
        }

        for name, thread in self.collector_threads.items():
            status['collectors'][name] = {
                'alive': thread.is_alive(),
                'thread_name': thread.name
            }

        # Füge nicht-aktive Collectors hinzu
        for name in self.collectors.keys():
            if name not in status['collectors']:
                status['collectors'][name] = {
                    'alive': False,
                    'thread_name': None
                }

        return status

    def restart_collector(self, name: str) -> bool:
        """
        Startet einen einzelnen Collector neu

        Args:
            name: Name des Collectors

        Returns:
            True wenn erfolgreich
        """
        if name not in self.collectors:
            logger.error(f"Collector {name} not found")
            return False

        logger.info(f"Restarting collector: {name}")

        # Stoppe existierenden Thread
        if name in self.collector_threads:
            thread = self.collector_threads[name]
            # Thread wird automatisch stoppen wenn stop_event gesetzt ist
            # Aber wir können nicht einzelne Threads stoppen
            logger.warning("Individual collector restart not fully implemented - use stop_all/start_all")
            return False

        # TODO: Implementiere besseres einzelnes Thread-Management
        return True

    def __enter__(self):
        """Context Manager - Start"""
        self.start_all()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context Manager - Stop"""
        self.stop_all()
        return False  # Propagate exceptions


# CLI für direktes Starten
if __name__ == '__main__':
    import argparse
    import signal

    parser = argparse.ArgumentParser(description='Background Data Collector Manager')
    parser.add_argument('--config', type=str, help='Path to config file')
    args = parser.parse_args()

    # Signal Handler für sauberes Beenden
    def signal_handler(sig, frame):
        logger.info("Received stop signal")
        manager.stop_all()
        exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Starte Manager
    manager = CollectorManager(config_path=args.config)

    logger.info("Starting CollectorManager...")
    manager.start_all()

    # Status ausgeben
    time.sleep(2)
    status = manager.get_status()
    logger.info(f"Status: {status}")

    # Laufe bis Signal empfangen wird
    logger.info("CollectorManager running. Press Ctrl+C to stop.")
    try:
        while True:
            time.sleep(60)
            # Optional: Status-Updates ausgeben
            status = manager.get_status()
            alive_count = sum(1 for c in status['collectors'].values() if c['alive'])
            logger.info(f"Collectors alive: {alive_count}/{len(status['collectors'])}")
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received")
        manager.stop_all()
