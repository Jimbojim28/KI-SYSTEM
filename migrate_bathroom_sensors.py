#!/usr/bin/env python3
"""
Datenbank-Migration: Fügt Duschsensor-Felder zur bathroom_continuous_measurements Tabelle hinzu
Führe dieses Script aus um die Datenbank zu aktualisieren nach der Duschsensor-Erweiterung
"""

import sqlite3
from pathlib import Path

def migrate_database():
    """Fügt neue Spalten für Duschsensoren hinzu"""
    
    db_path = Path("data/ki_system.db")
    
    if not db_path.exists():
        print(f"❌ Database not found at {db_path}")
        return False
    
    try:
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        
        # Prüfe ob Spalten bereits existieren
        cursor.execute("PRAGMA table_info(bathroom_continuous_measurements)")
        columns = [col[1] for col in cursor.fetchall()]
        
        if 'shower_humidity' in columns and 'shower_temperature' in columns:
            print("✓ Duschsensor-Spalten bereits vorhanden - keine Migration nötig")
            return True
        
        print("Füge Duschsensor-Spalten zur bathroom_continuous_measurements Tabelle hinzu...")
        
        # Füge neue Spalten hinzu
        if 'shower_humidity' not in columns:
            cursor.execute("""
                ALTER TABLE bathroom_continuous_measurements 
                ADD COLUMN shower_humidity REAL
            """)
            print("✓ Spalte 'shower_humidity' hinzugefügt")
        
        if 'shower_temperature' not in columns:
            cursor.execute("""
                ALTER TABLE bathroom_continuous_measurements 
                ADD COLUMN shower_temperature REAL
            """)
            print("✓ Spalte 'shower_temperature' hinzugefügt")
        
        conn.commit()
        conn.close()
        
        print("✓ Migration erfolgreich abgeschlossen!")
        return True
        
    except Exception as e:
        print(f"❌ Fehler bei der Migration: {e}")
        return False

if __name__ == "__main__":
    print("=== Datenbank-Migration: Duschsensor-Felder ===")
    success = migrate_database()
    
    if success:
        print("\n✅ Migration erfolgreich!")
        print("Die Datenbank unterstützt jetzt zusätzliche Duschsensor-Daten.")
    else:
        print("\n❌ Migration fehlgeschlagen!")
        print("Bitte prüfe die Logs für Details.")
