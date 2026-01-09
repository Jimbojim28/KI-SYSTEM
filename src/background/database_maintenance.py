"""
Automatische Datenbank-Wartung
Läuft täglich um 5:00 Uhr und optimiert die Datenbank
"""

import schedule
import time
import threading
from datetime import datetime
from loguru import logger
from src.utils.database import Database


class DatabaseMaintenanceJob:
    """Automatische Datenbank-Wartung"""
    
    def __init__(self, run_time: str = None, retention_days: int = 90, run_hour: int = 5):
        """
        Args:
            run_time: Uhrzeit für tägliche Wartung (HH:MM Format) - legacy parameter
            retention_days: Wie viele Tage Daten behalten werden sollen
            run_hour: Stunde für tägliche Wartung (0-23)
        """
        # Support both old and new parameter style
        if run_time:
            self.run_time = run_time
        else:
            self.run_time = f"{run_hour:02d}:00"

        self.retention_days = retention_days
        self.db = Database()
        self._stop_event = threading.Event()
        self._thread = None

        # Lade letzten Wartungslauf aus der Datenbank
        self.last_run = None
        self.last_cleanup = None
        self.last_vacuum = None
        try:
            status = self.db.get_system_status('last_maintenance_run')
            if status and status.get('value'):
                self.last_run = datetime.fromisoformat(status['value'])
                logger.info(f"Loaded last maintenance run from database: {self.last_run}")

            cleanup_status = self.db.get_system_status('last_maintenance_cleanup')
            if cleanup_status and cleanup_status.get('value'):
                self.last_cleanup = datetime.fromisoformat(cleanup_status['value'])

            vacuum_status = self.db.get_system_status('last_maintenance_vacuum')
            if vacuum_status and vacuum_status.get('value'):
                self.last_vacuum = datetime.fromisoformat(vacuum_status['value'])
        except Exception as e:
            logger.warning(f"Could not load last maintenance run from database: {e}")
            self.last_run = None
            self.last_cleanup = None
            self.last_vacuum = None
        
    def run_maintenance(self):
        """Führt Datenbank-Wartung aus"""
        logger.info("🔧 Starting database maintenance...")
        
        try:
            # Hole aktuelle Stats
            stats_before = self.db.get_database_stats()
            logger.info(f"Database size before: {stats_before['size_mb']} MB")
            logger.info(f"Total rows in large tables: {sum(t['row_count'] for t in stats_before['large_tables'])}")
            
            # Lösche alte Daten (Retention Policy) - ZUERST, damit optimize effektiver ist
            logger.info(f"🗑️ Cleaning old data (retention: {self.retention_days} days)...")
            self.db.cleanup_old_data(days=self.retention_days)
            
            # Optimiere Datenbank (VACUUM etc.)
            result = self.db.optimize(enable_auto_vacuum=True)
            
            if 'error' in result:
                logger.error(f"❌ Maintenance failed: {result['error']}")
                return False
            
            # Hole Stats nach Wartung
            stats_after = self.db.get_database_stats()
            
            logger.info("✅ Database maintenance completed:")
            logger.info(f"   Size: {stats_before['size_mb']} MB → {stats_after['size_mb']} MB")
            logger.info(f"   Saved: {result.get('saved_mb', 0)} MB")
            logger.info(f"   Duration: {result.get('duration_seconds', 0):.2f}s")
            logger.info(f"   Operations: {len(result.get('operations', []))}")

            # Speichere Wartungslauf-Zeitstempel in Datenbank
            now = datetime.now()
            self.last_run = now
            self.last_cleanup = now
            self.last_vacuum = now

            try:
                self.db.set_system_status('last_maintenance_run', now.isoformat())
                self.db.set_system_status('last_maintenance_cleanup', now.isoformat())
                self.db.set_system_status('last_maintenance_vacuum', now.isoformat())
                logger.info(f"Saved maintenance timestamp to database: {now.isoformat()}")
            except Exception as e:
                logger.warning(f"Could not save maintenance timestamp to database: {e}")

            return True
            
        except Exception as e:
            logger.error(f"❌ Error during maintenance: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def _run_scheduler(self):
        """Background thread für Scheduler"""
        while not self._stop_event.is_set():
            schedule.run_pending()
            self._stop_event.wait(60)  # Prüfe jede Minute
    
    def start(self):
        """Startet den Wartungs-Scheduler (non-blocking)"""
        logger.info(f"📅 Database maintenance scheduled daily at {self.run_time} (retention: {self.retention_days} days)")
        
        # Schedule tägliche Wartung
        schedule.every().day.at(self.run_time).do(self.run_maintenance)
        
        # Starte Background-Thread
        self._thread = threading.Thread(target=self._run_scheduler, daemon=True)
        self._thread.start()
    
    def stop(self):
        """Stoppt den Wartungs-Scheduler"""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("Database maintenance scheduler stopped")
    
    def get_status(self) -> dict:
        """Gibt den aktuellen Status des Maintenance-Jobs zurück"""
        return {
            'running': self._thread is not None and self._thread.is_alive(),
            'last_cleanup': self.last_cleanup.isoformat() if self.last_cleanup else None,
            'last_vacuum': self.last_vacuum.isoformat() if self.last_vacuum else None,
            'retention_days': self.retention_days,
            'run_hour': int(self.run_time.split(':')[0])
        }


if __name__ == "__main__":
    # Kann als eigenständiger Prozess gestartet werden
    job = DatabaseMaintenanceJob(run_time="05:00")
    job.start()
