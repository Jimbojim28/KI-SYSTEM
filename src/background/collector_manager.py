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
from .database_maintenance import DatabaseMaintenanceJob
from .presence_leave_notifier import PresenceLeaveNotifier

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
            try:
                self.collectors['heating'] = HeatingDataCollector(
                    engine=None,
                    interval_seconds=interval
                )
                logger.info(f"Heating collector initialized (interval: {interval}s)")
            except Exception as e:
                logger.error(f"Failed to initialize heating collector: {e}")

        # 2. Beleuchtungs-Daten Collector
        if get_config_value('collectors.lighting.enabled', True):
            try:
                # LightingDataCollector liest interval aus config
                self.collectors['lighting'] = LightingDataCollector(
                    db=None,
                    config=self.config.config if hasattr(self.config, 'config') else {},
                    engine=None
                )
                logger.info(f"Lighting collector initialized")
            except Exception as e:
                logger.error(f"Failed to initialize lighting collector: {e}")

        # 3. Fenster-Daten Collector
        if get_config_value('collectors.windows.enabled', True):
            interval = get_config_value('collectors.windows.interval', 60)
            try:
                self.collectors['windows'] = WindowDataCollector(
                    engine=None,
                    interval_seconds=interval
                )
                logger.info(f"Window collector initialized (interval: {interval}s)")
            except Exception as e:
                logger.error(f"Failed to initialize window collector: {e}")

        # 4. Temperatur-Daten Collector
        if get_config_value('collectors.temperature.enabled', True):
            try:
                # TemperatureDataCollector liest interval aus config
                self.collectors['temperature'] = TemperatureDataCollector(
                    db=None,
                    config=self.config.config if hasattr(self.config, 'config') else {},
                    engine=None
                )
                logger.info(f"Temperature collector initialized")
            except Exception as e:
                logger.error(f"Failed to initialize temperature collector: {e}")

        # 5. Badezimmer-Daten Collector
        if get_config_value('collectors.bathroom.enabled', False):
            interval = get_config_value('collectors.bathroom.interval', 60)
            try:
                self.collectors['bathroom'] = BathroomDataCollector(
                    engine=None,
                    interval_seconds=interval
                )
                logger.info(f"Bathroom collector initialized (interval: {interval}s)")
            except Exception as e:
                logger.warning(f"Bathroom collector not available: {e}")

        # 6. ML Auto-Trainer (täglich)
        if get_config_value('ml_auto_trainer.enabled', True):
            training_hour = get_config_value('ml_auto_trainer.training_hour', 2)
            try:
                self.collectors['ml_trainer'] = MLAutoTrainer(
                    run_at_hour=training_hour
                )
                logger.info(f"ML Auto-Trainer initialized (hour: {training_hour}:00)")
            except Exception as e:
                logger.warning(f"ML Auto-Trainer not available: {e}")

        # 7. Badezimmer-Optimizer (täglich)
        if get_config_value('bathroom_optimizer.enabled', False):
            optimization_hour = get_config_value('bathroom_optimizer.optimization_hour', 3)
            try:
                self.collectors['bathroom_optimizer'] = BathroomOptimizer(
                    run_at_hour=optimization_hour
                )
                logger.info(f"Bathroom Optimizer initialized (hour: {optimization_hour}:00)")
            except Exception as e:
                logger.warning(f"Bathroom Optimizer not available: {e}")

        # 8. Database Maintenance (täglich)
        if get_config_value('database_maintenance.enabled', True):
            cleanup_hour = get_config_value('database_maintenance.cleanup_hour', 4)
            retention_days = get_config_value('database_maintenance.retention_days', 90)
            try:
                self.collectors['db_maintenance'] = DatabaseMaintenanceJob(
                    run_hour=cleanup_hour,
                    retention_days=retention_days
                )
                logger.info(f"Database Maintenance initialized (hour: {cleanup_hour}:00, retention: {retention_days} days)")
            except Exception as e:
                logger.warning(f"Database Maintenance not available: {e}")
        
        # 9. Presence Leave Notifier - Benachrichtigung wenn alle gehen
        if get_config_value('presence_leave_notification.enabled', True):
            interval = get_config_value('presence_leave_notification.check_interval', 30)
            try:
                self.collectors['presence_leave'] = PresenceLeaveNotifier(
                    check_interval=interval
                )
                logger.info(f"Presence Leave Notifier initialized (interval: {interval}s)")
            except Exception as e:
                logger.warning(f"Presence Leave Notifier not available: {e}")

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
                # Prüfe ob Collector start() Methode hat (kontinuierlich)
                if hasattr(collector, 'start') and hasattr(collector, 'stop'):
                    # Collector hat eigene Thread-Verwaltung (z.B. TemperatureDataCollector)
                    if not getattr(collector, 'running', False):
                        collector.start()
                    
                    # Warte solange der Collector läuft
                    while not self.stop_event.is_set() and getattr(collector, 'running', False):
                        self.stop_event.wait(timeout=10)
                    
                    # Stoppe Collector beim Beenden
                    if hasattr(collector, 'stop'):
                        collector.stop()
                    break
                    
                # Collector hat run() Methode (einmaliger Durchlauf pro Intervall)
                elif hasattr(collector, 'run'):
                    collector.run()
                    
                # Collector hat collect() Methode (Legacy)
                elif hasattr(collector, 'collect'):
                    collector.collect()
                else:
                    logger.error(f"Collector {name} has no compatible run/start/collect method")
                    break

                # Warte auf nächsten Zyklus oder Stop-Signal
                # Nutze Collector-Intervall falls vorhanden
                interval = 60  # Default
                if hasattr(collector, 'interval'):
                    interval = collector.interval
                elif hasattr(collector, 'interval_seconds'):
                    interval = collector.interval_seconds
                elif hasattr(collector, 'check_interval'):
                    interval = collector.check_interval
                    
                self.stop_event.wait(timeout=interval)

            except Exception as e:
                error_msg = str(e).encode('ascii', 'ignore').decode('ascii')
                logger.error(f"Error in collector {name}: {error_msg}")
                # Bei Fehler: kurz warten und dann neu versuchen
                self.stop_event.wait(timeout=30)

        logger.info(f"Collector thread stopped: {name}")

    def stop_all(self):
        """Stoppt alle Collectors"""
        if not self.running:
            logger.warning("CollectorManager not running")
            return

        logger.info("Stopping all collectors...")
        self.stop_event.set()
        self.running = False

        # Stoppe zuerst alle Collectors mit stop() Methode
        for name, collector in self.collectors.items():
            if hasattr(collector, 'stop') and hasattr(collector, 'running'):
                try:
                    if collector.running:
                        logger.debug(f"Stopping collector: {name}")
                        collector.stop()
                except Exception as e:
                    logger.error(f"Error stopping collector {name}: {e}")

        # Warte auf alle Threads (max 30 Sekunden)
        for name, thread in self.collector_threads.items():
            try:
                thread.join(timeout=30)
                if thread.is_alive():
                    logger.warning(f"Collector {name} did not stop gracefully")
                else:
                    logger.info(f"Stopped collector: {name}")
            except Exception as e:
                logger.error(f"Error joining thread {name}: {e}")

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
            'collectors': {},
            'summary': {
                'total': len(self.collectors),
                'alive': 0,
                'dead': 0
            }
        }

        for name, collector in self.collectors.items():
            collector_status = {
                'thread_alive': False,
                'collector_running': False,
                'has_stats': False
            }
            
            # Thread-Status
            if name in self.collector_threads:
                thread = self.collector_threads[name]
                collector_status['thread_alive'] = thread.is_alive()
                collector_status['thread_name'] = thread.name
            
            # Collector-interner Status
            if hasattr(collector, 'running'):
                collector_status['collector_running'] = collector.running
            
            # Zusätzliche Stats falls verfügbar
            if hasattr(collector, 'get_stats'):
                try:
                    collector_status['stats'] = collector.get_stats()
                    collector_status['has_stats'] = True
                except Exception as e:
                    logger.debug(f"Could not get stats for {name}: {e}")
            
            # Zähle alive/dead
            is_alive = collector_status['thread_alive'] or collector_status['collector_running']
            if is_alive:
                status['summary']['alive'] += 1
            else:
                status['summary']['dead'] += 1
            
            status['collectors'][name] = collector_status

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
