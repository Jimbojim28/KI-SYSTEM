"""
Automatische Datenbank-Wartung
Läuft täglich um 5:00 Uhr und optimiert die Datenbank
"""

import schedule
import time
from datetime import datetime
from loguru import logger
from src.utils.database import Database


class DatabaseMaintenanceJob:
    """Automatische Datenbank-Wartung"""
    
    def __init__(self, run_time: str = "05:00"):
        """
        Args:
            run_time: Uhrzeit für tägliche Wartung (HH:MM Format)
        """
        self.run_time = run_time
        self.db = Database()
        self.last_run = None
        
    def run_maintenance(self):
        """Führt Datenbank-Wartung aus"""
        logger.info("🔧 Starting database maintenance...")
        
        try:
            # Hole aktuelle Stats
            stats_before = self.db.get_database_stats()
            logger.info(f"Database size before: {stats_before['size_mb']} MB")
            logger.info(f"Total rows in large tables: {sum(t['row_count'] for t in stats_before['large_tables'])}")
            
            # Optimiere Datenbank
            result = self.db.optimize(enable_auto_vacuum=True)
            
            if 'error' in result:
                logger.error(f"❌ Maintenance failed: {result['error']}")
                return False
            
            # Lösche alte Daten (Retention Policy)
            logger.info("🗑️ Cleaning old data (retention policy)...")
            self.db.cleanup_old_data(days=90)  # 90 Tage behalten
            
            # Hole Stats nach Wartung
            stats_after = self.db.get_database_stats()
            
            logger.info("✅ Database maintenance completed:")
            logger.info(f"   Size: {stats_before['size_mb']} MB → {stats_after['size_mb']} MB")
            logger.info(f"   Saved: {result.get('saved_mb', 0)} MB")
            logger.info(f"   Duration: {result.get('duration_seconds', 0):.2f}s")
            logger.info(f"   Operations: {len(result.get('operations', []))}")
            
            self.last_run = datetime.now()
            return True
            
        except Exception as e:
            logger.error(f"❌ Error during maintenance: {e}")
            return False
    
    def start(self):
        """Startet den Wartungs-Scheduler"""
        logger.info(f"📅 Database maintenance scheduled daily at {self.run_time}")
        
        # Schedule tägliche Wartung
        schedule.every().day.at(self.run_time).do(self.run_maintenance)
        
        # Haupt-Loop
        while True:
            schedule.run_pending()
            time.sleep(60)  # Prüfe jede Minute


if __name__ == "__main__":
    # Kann als eigenständiger Prozess gestartet werden
    job = DatabaseMaintenanceJob(run_time="05:00")
    job.start()
