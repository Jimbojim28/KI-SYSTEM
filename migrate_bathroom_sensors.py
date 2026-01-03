#!/usr/bin/env python3
"""
Datenbank-Migration: Fügt Duschsensor-Felder zur bathroom_continuous_measurements Tabelle hinzu
Führe dieses Script aus um die Datenbank zu aktualisieren nach der Duschsensor-Erweiterung
"""

import sqlite3
from pathlib import Path
from loguru import logger

def migrate_database():
    """Fügt neue Spalten für Duschsensoren hinzu"""
    
    db_path = Path("data/ki_system.db")
    
    if not db_path.exists():
        logger.error(f"Database not found at {db_path}")
        return False
    
    try:
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        
        # Prüfe ob Spalten bereits existieren
        cursor.execute("PRAGMA table_info(bathroom_continuous_measurements)")
        columns = [col[1] for col in cursor.fetchall()]
        
        if 'shower_humidity' in columns and 'shower_temperature' in columns:
            logger.info("✓ Duschsensor-Spalten bereits vorhanden - keine Migration nötig")
            return True
        
        logger.info("Füge Duschsensor-Spalten zur bathroom_continuous_measurements Tabelle hinzu...")
        
        # Füge neue Spalten hinzu
        if 'shower_humidity' not in columns:
            cursor.execute("""
                ALTER TABLE bathroom_continuous_measurements 
                ADD COLUMN shower_humidity REAL
            """)
            logger.info("✓ Spalte 'shower_humidity' hinzugefügt")
        
        if 'shower_temperature' not in columns:
            cursor.execute("""
                ALTER TABLE bathroom_continuous_measurements 
                ADD COLUMN shower_temperature REAL
            """)
            logger.info("✓ Spalte 'shower_temperature' hinzugefügt")
        
        conn.commit()
        conn.close()
        
        logger.info("✓ Migration erfolgreich abgeschlossen!")
        return True
        
    except Exception as e:
        logger.error(f"❌ Fehler bei der Migration: {e}")
        return False

if __name__ == "__main__":
    logger.info("=== Datenbank-Migration: Duschsensor-Felder ===")
    success = migrate_database()
    
    if success:
        print("\n✅ Migration erfolgreich!")
        print("Die Datenbank unterstützt jetzt zusätzliche Duschsensor-Daten.")
    else:
        print("\n❌ Migration fehlgeschlagen!")
        print("Bitte prüfe die Logs für Details.")
