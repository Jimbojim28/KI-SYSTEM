"""Datenbankmanagement für historische Daten"""

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Any, Optional
import json
from loguru import logger


class Database:
    """SQLite Datenbank für Sensor- und Entscheidungsdaten"""

    def __init__(self, db_path: str = "data/ki_system.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = None
        self._init_database()
        self._run_migrations()

    def _init_database(self):
        """Erstellt die Datenbank-Tabellen"""
        conn = self._get_connection()
        cursor = conn.cursor()

        # Sensor-Daten Tabelle
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sensor_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME NOT NULL,
                sensor_id TEXT NOT NULL,
                sensor_type TEXT NOT NULL,
                value REAL,
                unit TEXT,
                metadata TEXT
            )
        """)

        # Externe Daten (Wetter, Strompreise)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS external_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME NOT NULL,
                data_type TEXT NOT NULL,
                data TEXT NOT NULL
            )
        """)

        # Entscheidungen und Aktionen
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME NOT NULL,
                device_id TEXT NOT NULL,
                decision_type TEXT NOT NULL,
                action TEXT NOT NULL,
                confidence REAL,
                model_version TEXT,
                executed BOOLEAN DEFAULT 0,
                result TEXT
            )
        """)

        # Trainings-Historie
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS training_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME NOT NULL,
                model_name TEXT NOT NULL,
                model_type TEXT NOT NULL,
                metrics TEXT,
                model_path TEXT
            )
        """)

        # Badezimmer Automatisierung - Events
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS bathroom_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                start_time DATETIME NOT NULL,
                end_time DATETIME,
                duration_minutes REAL,
                peak_humidity REAL,
                avg_humidity REAL,
                start_humidity REAL,
                end_humidity REAL,
                avg_temperature REAL,
                motion_detected BOOLEAN,
                door_closed BOOLEAN,
                dehumidifier_runtime_minutes REAL,
                event_type TEXT DEFAULT 'shower',
                day_of_week INTEGER,
                hour_of_day INTEGER
            )
        """)

        # Badezimmer - Detaillierte Messungen während Events
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS bathroom_measurements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id INTEGER,
                timestamp DATETIME NOT NULL,
                humidity REAL,
                temperature REAL,
                motion BOOLEAN,
                dehumidifier_on BOOLEAN,
                FOREIGN KEY (event_id) REFERENCES bathroom_events(id)
            )
        """)

        # Badezimmer - Geräte-Aktionen
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS bathroom_device_actions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME NOT NULL,
                event_id INTEGER,
                device_type TEXT NOT NULL,
                device_id TEXT NOT NULL,
                action TEXT NOT NULL,
                reason TEXT,
                humidity_at_action REAL,
                temperature_at_action REAL,
                FOREIGN KEY (event_id) REFERENCES bathroom_events(id)
            )
        """)

        # Badezimmer - Gelernte Parameter
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS bathroom_learned_parameters (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME NOT NULL,
                parameter_name TEXT NOT NULL,
                parameter_value REAL NOT NULL,
                confidence REAL,
                samples_used INTEGER,
                reason TEXT
            )
        """)

        # Badezimmer - Kontinuierliche Messungen (alle 60s)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS bathroom_continuous_measurements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME NOT NULL,
                humidity REAL,
                temperature REAL
            )
        """)

        # === ML TRAINING DATEN ===
        
        # Lighting Events für LightingModel
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS lighting_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME NOT NULL,
                device_id TEXT NOT NULL,
                device_name TEXT,
                room_name TEXT,
                state TEXT NOT NULL,
                brightness INTEGER,
                hour_of_day INTEGER,
                day_of_week INTEGER,
                is_weekend BOOLEAN,
                outdoor_light REAL,
                presence BOOLEAN,
                motion_detected BOOLEAN
            )
        """)

        # Temperature Readings für TemperatureModel
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS continuous_measurements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME NOT NULL,
                device_id TEXT NOT NULL,
                device_name TEXT,
                room_name TEXT,
                current_temperature REAL,
                target_temperature REAL,
                outdoor_temperature REAL,
                humidity REAL,
                heating_active BOOLEAN,
                presence BOOLEAN,
                window_open BOOLEAN,
                hour_of_day INTEGER,
                day_of_week INTEGER,
                is_weekend BOOLEAN,
                energy_price_level INTEGER
            )
        """)

        # Automatisierungs-Trigger (für neue Automation UI)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS automation_triggers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                rule_name TEXT NOT NULL,
                trigger_time DATETIME NOT NULL,
                action TEXT NOT NULL
            )
        """)

        # === HEIZUNGS-OPTIMIERUNG TABELLEN ===

        # Heizungs-Beobachtungen (kontinuierliche Aufzeichnung)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS heating_observations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME NOT NULL,
                device_id TEXT NOT NULL,
                room_name TEXT,
                current_temperature REAL,
                target_temperature REAL,
                outdoor_temperature REAL,
                is_heating BOOLEAN,
                presence_detected BOOLEAN,
                window_open BOOLEAN,
                energy_price_level INTEGER,
                humidity REAL,
                power_percentage REAL,
                hour_of_day INTEGER,
                day_of_week INTEGER,
                is_weekend BOOLEAN
            )
        """)

        # KI-generierte Heizungs-Insights
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS heating_insights (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME NOT NULL,
                insight_type TEXT NOT NULL,
                device_id TEXT,
                room_name TEXT,
                recommendation TEXT NOT NULL,
                potential_saving_percent REAL,
                potential_saving_eur REAL,
                confidence REAL,
                samples_used INTEGER,
                priority TEXT DEFAULT 'medium'
            )
        """)

        # Optimierte Heizpläne
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS heating_schedules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME NOT NULL,
                device_id TEXT NOT NULL,
                room_name TEXT,
                schedule_type TEXT NOT NULL,
                day_of_week INTEGER,
                hour INTEGER,
                recommended_temperature REAL,
                reason TEXT,
                confidence REAL,
                samples_used INTEGER
            )
        """)

        # === RAUMSPEZIFISCHES LERNEN FÜR HEIZUNG ===

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS heating_room_learning (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                room_name TEXT NOT NULL,
                device_id TEXT,
                timestamp DATETIME NOT NULL,
                parameter_name TEXT NOT NULL,
                parameter_value REAL NOT NULL,
                confidence REAL,
                samples_used INTEGER,
                notes TEXT,
                UNIQUE(room_name, parameter_name, timestamp)
            )
        """)

        # === SCHIMMEL-PRÄVENTION & LUFTFEUCHTIGKEIT ===

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS humidity_alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME NOT NULL,
                room_name TEXT NOT NULL,
                alert_type TEXT NOT NULL,
                humidity REAL,
                temperature REAL,
                dewpoint REAL,
                condensation_risk BOOLEAN,
                severity TEXT,
                recommendation TEXT,
                acknowledged BOOLEAN DEFAULT 0
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ventilation_recommendations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME NOT NULL,
                room_name TEXT,
                indoor_temp REAL,
                indoor_humidity REAL,
                outdoor_temp REAL,
                outdoor_humidity REAL,
                is_beneficial BOOLEAN,
                absolute_humidity_diff REAL,
                recommended_duration_minutes INTEGER,
                recommendation_text TEXT
            )
        """)

        # === VORHERSAGE-SYSTEM ===

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS shower_predictions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME NOT NULL,
                predicted_time DATETIME NOT NULL,
                confidence REAL,
                typical_hour INTEGER,
                typical_weekday INTEGER,
                pattern_strength REAL,
                samples_used INTEGER
            )
        """)

        # === SYSTEM STATUS ===

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS system_status (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key TEXT UNIQUE NOT NULL,
                value TEXT,
                timestamp DATETIME NOT NULL
            )
        """)

        # Ring Events
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS ring_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                ring_event_id TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                duration INTEGER,
                answered BOOLEAN DEFAULT FALSE,
                auto_opened BOOLEAN DEFAULT FALSE,
                metadata TEXT
            )
        ''')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_ring_events_timestamp ON ring_events(timestamp)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_ring_events_ring_id ON ring_events(ring_event_id)')

        # Erstelle Indizes für bessere Performance
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_sensor_timestamp
            ON sensor_data(timestamp, sensor_id)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_decisions_timestamp
            ON decisions(timestamp, device_id)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_bathroom_events_time
            ON bathroom_events(start_time, end_time)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_bathroom_measurements_event
            ON bathroom_measurements(event_id, timestamp)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_lighting_events_time
            ON lighting_events(timestamp, device_id)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_continuous_measurements_time
            ON continuous_measurements(timestamp, device_id)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_heating_observations_time
            ON heating_observations(timestamp, device_id)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_heating_insights_time
            ON heating_insights(timestamp, device_id)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_heating_schedules_device
            ON heating_schedules(device_id, day_of_week, hour)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_room_learning_room
            ON heating_room_learning(room_name, parameter_name, timestamp)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_humidity_alerts_time
            ON humidity_alerts(timestamp, room_name, acknowledged)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_ventilation_recs_time
            ON ventilation_recommendations(timestamp, room_name)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_shower_predictions_time
            ON shower_predictions(predicted_time, confidence)
        """)

        conn.commit()
        logger.info(f"Database initialized at {self.db_path}")

    def _run_migrations(self):
        """Führt ausstehende Datenbank-Migrationen aus"""
        try:
            from src.utils.migrations import MigrationManager

            migrator = MigrationManager(str(self.db_path))
            applied_count = migrator.run_migrations()

            if applied_count > 0:
                logger.info(f"Applied {applied_count} database migration(s)")

        except Exception as e:
            logger.error(f"Error running database migrations: {e}")
            # Nicht fatal - System kann ohne Migrationen weiterlaufen

    def _get_connection(self) -> sqlite3.Connection:
        """Gibt eine Datenbankverbindung zurück"""
        if self.connection is None:
            self.connection = sqlite3.connect(
                self.db_path,
                detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES,
                check_same_thread=False,  # Erlaubt Multi-Threading für Flask
                timeout=30.0  # Erhöhtes Timeout für parallele Zugriffe
            )
            self.connection.row_factory = sqlite3.Row
            
            # === PERFORMANCE OPTIMIERUNGEN ===
            # Write-Ahead Logging (WAL) für bessere Parallelität
            self.connection.execute('PRAGMA journal_mode=WAL')
            # NORMAL sync ist ein guter Kompromiss zwischen Speed und Sicherheit
            self.connection.execute('PRAGMA synchronous=NORMAL')
            # Erhöhtes Timeout für parallele Zugriffe
            self.connection.execute('PRAGMA busy_timeout=30000')
            # Cache-Größe erhöhen (negative Zahl = KB, 32MB Cache)
            self.connection.execute('PRAGMA cache_size=-32000')
            # Memory-mapped I/O für schnellere Lesezugriffe (64MB)
            self.connection.execute('PRAGMA mmap_size=67108864')
            # Temp-Store im Memory
            self.connection.execute('PRAGMA temp_store=MEMORY')
        return self.connection

    def execute(self, query: str, params: tuple = None) -> List[Dict]:
        """
        Führt eine SQL-Query aus und gibt Ergebnisse als Liste von Dictionaries zurück

        Args:
            query: SQL Query String
            params: Optionale Parameter für prepared statements

        Returns:
            Liste von Dictionaries mit den Ergebnissen
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        if params:
            cursor.execute(query, params)
        else:
            cursor.execute(query)

        # Konvertiere sqlite3.Row Objekte zu Dictionaries
        results = []
        for row in cursor.fetchall():
            results.append(dict(row))

        return results

    def insert_sensor_data(self, sensor_id: str, sensor_type: str,
                          value: float, unit: str = None,
                          metadata: Dict = None, timestamp: datetime = None):
        """Fügt Sensordaten hinzu"""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO sensor_data
            (timestamp, sensor_id, sensor_type, value, unit, metadata)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            timestamp or datetime.now(),
            sensor_id,
            sensor_type,
            value,
            unit,
            json.dumps(metadata) if metadata else None
        ))

        conn.commit()

    def insert_external_data(self, data_type: str, data: Dict, timestamp: datetime = None):
        """Fügt externe Daten hinzu (Wetter, Strompreise)"""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO external_data (timestamp, data_type, data)
            VALUES (?, ?, ?)
        """, (timestamp or datetime.now(), data_type, json.dumps(data)))

        conn.commit()

    def get_sensor_data_count(self) -> int:
        """Gibt die Gesamtanzahl der Sensor-Datensätze zurück"""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) as count FROM sensor_data")
        return cursor.fetchone()['count']

    def get_external_data_count(self) -> int:
        """Gibt die Gesamtanzahl der externen Datensätze zurück"""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) as count FROM external_data")
        return cursor.fetchone()['count']

    def get_latest_external_data(self, data_type: str) -> Optional[Dict]:
        """Holt die neuesten externen Daten eines bestimmten Typs

        Args:
            data_type: Typ der Daten (z.B. 'energy_price', 'weather')

        Returns:
            Dictionary mit den neuesten Daten oder None
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT timestamp, data FROM external_data
            WHERE data_type = ?
            ORDER BY timestamp DESC
            LIMIT 1
        """, (data_type,))

        result = cursor.fetchone()
        if result:
            return {
                'timestamp': result['timestamp'],
                'data': json.loads(result['data']) if isinstance(result['data'], str) else result['data']
            }
        return None

    def get_latest_sensor_timestamp(self) -> Optional[datetime]:
        """Gibt den Zeitstempel der letzten Sensor-Messung zurück"""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT MAX(timestamp) as latest FROM sensor_data")
        result = cursor.fetchone()
        if result and result['latest']:
            return datetime.fromisoformat(result['latest'])
        return None

    def insert_decision(self, device_id: str, decision_type: str,
                       action: str, confidence: float,
                       model_version: str = None):
        """Speichert eine Entscheidung"""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO decisions
            (timestamp, device_id, decision_type, action, confidence, model_version)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            datetime.now(),
            device_id,
            decision_type,
            action,
            confidence,
            model_version
        ))

        conn.commit()
        return cursor.lastrowid

    def update_decision_result(self, decision_id: int, executed: bool, result: str = None):
        """Aktualisiert das Ergebnis einer Entscheidung"""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE decisions
            SET executed = ?, result = ?
            WHERE id = ?
        """, (executed, result, decision_id))

        conn.commit()

    def get_sensor_data(self, sensor_id: str = None,
                       sensor_type: str = None,
                       hours_back: int = 24,
                       limit: int = None) -> List[Dict]:
        """Holt Sensordaten der letzten X Stunden"""
        conn = self._get_connection()
        cursor = conn.cursor()

        start_time = datetime.now() - timedelta(hours=hours_back)

        query = "SELECT * FROM sensor_data WHERE timestamp >= ?"
        params = [start_time]

        if sensor_id:
            query += " AND sensor_id = ?"
            params.append(sensor_id)

        if sensor_type:
            query += " AND sensor_type = ?"
            params.append(sensor_type)

        query += " ORDER BY timestamp DESC"

        if limit:
            query += f" LIMIT {limit}"

        cursor.execute(query, params)

        results = []
        for row in cursor.fetchall():
            result = dict(row)
            # Parse metadata JSON
            if result.get('metadata'):
                try:
                    result['metadata'] = json.loads(result['metadata'])
                except (json.JSONDecodeError, TypeError) as e:
                    logger.debug(f"Failed to parse metadata JSON: {e}")
                    result['metadata'] = None
            results.append(result)

        return results

    def get_sensor_data_aggregated(self, sensor_type: str,
                                   hours_back: int = 24,
                                   interval_minutes: int = 60) -> List[Dict]:
        """
        Holt aggregierte Sensordaten (Durchschnitt pro Intervall)
        Nützlich für Graphen
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        start_time = datetime.now() - timedelta(hours=hours_back)

        # SQLite nutzt strftime für Gruppierung
        query = """
            SELECT
                strftime('%Y-%m-%d %H:00:00', timestamp) as interval_time,
                AVG(value) as avg_value,
                MIN(value) as min_value,
                MAX(value) as max_value,
                COUNT(*) as sample_count
            FROM sensor_data
            WHERE timestamp >= ? AND sensor_type = ?
            GROUP BY interval_time
            ORDER BY interval_time ASC
        """

        cursor.execute(query, (start_time, sensor_type))

        return [dict(row) for row in cursor.fetchall()]

    def get_training_data(self, hours_back: int = 168) -> Dict[str, List[Dict]]:
        """
        Holt Trainingsdaten für ML-Modelle
        Standard: 168 Stunden = 1 Woche
        """
        sensor_data = self.get_sensor_data(hours_back=hours_back)

        # Gruppiere nach Sensor-Typ
        grouped_data = {}
        for record in sensor_data:
            sensor_type = record['sensor_type']
            if sensor_type not in grouped_data:
                grouped_data[sensor_type] = []
            grouped_data[sensor_type].append(record)

        return grouped_data

    def insert_training_history(self, model_name: str, model_type: str,
                               metrics: Dict, model_path: str):
        """Speichert Trainings-Historie"""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO training_history
            (timestamp, model_name, model_type, metrics, model_path)
            VALUES (?, ?, ?, ?, ?)
        """, (
            datetime.now(),
            model_name,
            model_type,
            json.dumps(metrics),
            model_path
        ))

        conn.commit()

    def cleanup_old_data(self, retention_days: int = 90, days: int = None):
        """Löscht alte Daten basierend auf Retention-Policy

        Args:
            retention_days: Anzahl der Tage, die Daten aufbewahrt werden sollen (Standard: 90)
            days: Alias für retention_days (für Kompatibilität)

        Returns:
            Dict mit Anzahl der gelöschten Zeilen pro Tabelle
        """
        # Support both parameter names
        if days is not None:
            retention_days = days
            
        conn = self._get_connection()
        cursor = conn.cursor()

        cutoff_date = datetime.now() - timedelta(days=retention_days)
        deleted_counts = {}

        logger.info(f"🗑️ Cleaning data older than {retention_days} days (cutoff: {cutoff_date})")

        # Alte Sensor-Daten löschen
        try:
            cursor.execute("DELETE FROM sensor_data WHERE timestamp < ?", (cutoff_date,))
            deleted_counts['sensor_data'] = cursor.rowcount
        except Exception as e:
            logger.warning(f"Error cleaning sensor_data: {e}")

        # Alte externe Daten löschen
        try:
            cursor.execute("DELETE FROM external_data WHERE timestamp < ?", (cutoff_date,))
            deleted_counts['external_data'] = cursor.rowcount
        except Exception as e:
            logger.warning(f"Error cleaning external_data: {e}")

        # Alte Entscheidungen löschen
        try:
            cursor.execute("DELETE FROM decisions WHERE timestamp < ?", (cutoff_date,))
            deleted_counts['decisions'] = cursor.rowcount
        except Exception as e:
            logger.warning(f"Error cleaning decisions: {e}")

        # ===== WICHTIG: Fehlende Tabellen hinzugefügt =====
        
        # Alte Window-Beobachtungen löschen (GROSSE TABELLE!)
        try:
            cursor.execute("DELETE FROM window_observations WHERE timestamp < ?", (cutoff_date,))
            deleted_counts['window_observations'] = cursor.rowcount
        except Exception as e:
            logger.warning(f"Error cleaning window_observations: {e}")

        # Alte kontinuierliche Messungen löschen (GROSSE TABELLE!)
        try:
            cursor.execute("DELETE FROM continuous_measurements WHERE timestamp < ?", (cutoff_date,))
            deleted_counts['continuous_measurements'] = cursor.rowcount
        except Exception as e:
            logger.warning(f"Error cleaning continuous_measurements: {e}")

        # Alte Lighting-Events löschen (GROSSE TABELLE!)
        try:
            cursor.execute("DELETE FROM lighting_events WHERE timestamp < ?", (cutoff_date,))
            deleted_counts['lighting_events'] = cursor.rowcount
        except Exception as e:
            logger.warning(f"Error cleaning lighting_events: {e}")

        # Alte Presence-Daten löschen
        try:
            cursor.execute("DELETE FROM presence_data WHERE timestamp < ?", (cutoff_date,))
            deleted_counts['presence_data'] = cursor.rowcount
        except Exception as e:
            logger.warning(f"Error cleaning presence_data: {e}")

        # Alte Temperature-Observations löschen
        try:
            cursor.execute("DELETE FROM temperature_observations WHERE timestamp < ?", (cutoff_date,))
            deleted_counts['temperature_observations'] = cursor.rowcount
        except Exception as e:
            logger.warning(f"Error cleaning temperature_observations: {e}")

        # ===== Ende neue Tabellen =====

        # Alte Badezimmer-Events löschen (behalte mehr Daten für Muster-Erkennung)
        bathroom_retention = max(retention_days, 180)  # Mind. 6 Monate
        bathroom_cutoff = datetime.now() - timedelta(days=bathroom_retention)
        try:
            cursor.execute("DELETE FROM bathroom_events WHERE start_time < ?", (bathroom_cutoff,))
            deleted_counts['bathroom_events'] = cursor.rowcount
        except Exception as e:
            logger.warning(f"Error cleaning bathroom_events: {e}")

        # Alte Badezimmer-Messungen löschen (nur behalten wenn Event noch existiert)
        try:
            cursor.execute("""
                DELETE FROM bathroom_measurements
                WHERE event_id NOT IN (SELECT id FROM bathroom_events)
            """)
            deleted_counts['bathroom_measurements'] = cursor.rowcount
        except Exception as e:
            logger.warning(f"Error cleaning bathroom_measurements: {e}")

        # Alte Badezimmer-Aktionen löschen
        try:
            cursor.execute("DELETE FROM bathroom_device_actions WHERE timestamp < ?", (bathroom_cutoff,))
            deleted_counts['bathroom_device_actions'] = cursor.rowcount
        except Exception as e:
            logger.warning(f"Error cleaning bathroom_device_actions: {e}")

        # Alte kontinuierliche Badezimmer-Messungen löschen (normale Retention)
        try:
            cursor.execute("DELETE FROM bathroom_continuous_measurements WHERE timestamp < ?", (cutoff_date,))
            deleted_counts['bathroom_continuous_measurements'] = cursor.rowcount
        except Exception as e:
            logger.warning(f"Error cleaning bathroom_continuous_measurements: {e}")

        # Alte Heizungs-Beobachtungen löschen
        try:
            cursor.execute("DELETE FROM heating_observations WHERE timestamp < ?", (cutoff_date,))
            deleted_counts['heating_observations'] = cursor.rowcount
        except Exception as e:
            logger.warning(f"Error cleaning heating_observations: {e}")

        # Alte Heizungs-Insights löschen (nur die ältesten, behalte mind. 30 Tage)
        insights_retention = max(retention_days, 30)
        insights_cutoff = datetime.now() - timedelta(days=insights_retention)
        try:
            cursor.execute("DELETE FROM heating_insights WHERE timestamp < ?", (insights_cutoff,))
            deleted_counts['heating_insights'] = cursor.rowcount
        except Exception as e:
            logger.warning(f"Error cleaning heating_insights: {e}")

        conn.commit()

        total_deleted = sum(deleted_counts.values())
        logger.info(f"✅ Cleaned up {total_deleted} rows older than {retention_days} days")
        for table, count in sorted(deleted_counts.items(), key=lambda x: x[1], reverse=True):
            if count > 0:
                logger.info(f"   {table}: {count:,} rows deleted")

        return deleted_counts

    def clear_all_training_data(self, days_back: int = None) -> Dict[str, int]:
        """
        Löscht ALLE Trainingsdaten (oder nur Daten älter als X Tage)
        WARNUNG: Diese Aktion kann nicht rückgängig gemacht werden!

        Args:
            days_back: Wenn angegeben, lösche nur Daten älter als X Tage.
                      Wenn None, lösche ALLE Daten.

        Returns:
            Dict mit Anzahl der gelöschten Zeilen pro Tabelle
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        deleted_counts = {}

        if days_back is not None:
            cutoff_date = datetime.now() - timedelta(days=days_back)
            logger.warning(f"Clearing training data older than {days_back} days (before {cutoff_date})")
        else:
            cutoff_date = None
            logger.warning("Clearing ALL training data - this cannot be undone!")

        # Definiere Tabellen die geleert werden sollen
        tables_with_timestamp = [
            'sensor_data',
            'external_data',
            'decisions',
            'bathroom_events',
            'bathroom_measurements',
            'bathroom_device_actions',
            'bathroom_continuous_measurements',
            'heating_observations',
            'heating_insights',
            'heating_schedules',
            'humidity_alerts',
            'ventilation_recommendations',
            'shower_predictions'
        ]

        for table in tables_with_timestamp:
            if cutoff_date:
                # Lösche nur alte Daten
                timestamp_col = 'start_time' if table == 'bathroom_events' else 'timestamp'
                cursor.execute(f"DELETE FROM {table} WHERE {timestamp_col} < ?", (cutoff_date,))
            else:
                # Lösche ALLE Daten
                cursor.execute(f"DELETE FROM {table}")

            deleted_counts[table] = cursor.rowcount

        # Behalte IMMER system_status und learned_parameters (kritische Config-Daten)
        # Diese werden NICHT gelöscht, auch nicht bei "clear all"

        conn.commit()

        total_deleted = sum(deleted_counts.values())
        logger.warning(f"Cleared {total_deleted} rows of training data: {deleted_counts}")

        return deleted_counts

    def vacuum_database(self):
        """Optimiert die Datenbank durch VACUUM (gibt Speicher frei und reorganisiert)"""
        conn = self._get_connection()

        # VACUUM kann nicht in einer Transaktion laufen
        conn.isolation_level = None
        cursor = conn.cursor()

        logger.info("Running VACUUM on database...")
        cursor.execute("VACUUM")

        conn.isolation_level = ''
        logger.info("Database VACUUM completed")

    def get_database_size(self) -> Dict[str, Any]:
        """Gibt Informationen über die Datenbankgröße zurück

        Returns:
            Dict mit Dateigröße, Anzahl Zeilen pro Tabelle, etc.
        """
        import os

        # Dateigröße in MB
        file_size_bytes = os.path.getsize(self.db_path)
        file_size_mb = file_size_bytes / (1024 * 1024)

        conn = self._get_connection()
        cursor = conn.cursor()

        # Zähle Zeilen in jeder Tabelle
        tables = [
            'sensor_data',
            'external_data',
            'decisions',
            'training_history',
            'bathroom_events',
            'bathroom_measurements',
            'bathroom_device_actions',
            'bathroom_learned_parameters',
            'bathroom_continuous_measurements',
            'heating_observations',
            'heating_insights',
            'heating_schedules'
        ]

        table_counts = {}
        for table in tables:
            try:
                cursor.execute(f"SELECT COUNT(*) FROM {table}")
                count = cursor.fetchone()[0]
                table_counts[table] = count
            except sqlite3.OperationalError:
                # Tabelle existiert nicht
                table_counts[table] = 0

        # Ältester und neuester Eintrag
        cursor.execute("""
            SELECT MIN(timestamp), MAX(timestamp)
            FROM sensor_data
        """)
        oldest, newest = cursor.fetchone()

        return {
            'file_size_mb': round(file_size_mb, 2),
            'file_size_bytes': file_size_bytes,
            'total_rows': sum(table_counts.values()),
            'table_counts': table_counts,
            'oldest_data': oldest,
            'newest_data': newest,
            'file_path': str(self.db_path)
        }

    # === BADEZIMMER AUTOMATISIERUNG - METHODEN ===

    def start_bathroom_event(self, humidity: float, temperature: float,
                            motion: bool, door_closed: bool,
                            shower_start_humidity: float = None,
                            detected_by_shower_sensor: bool = False) -> int:
        """Startet ein neues Badezimmer-Event (z.B. Duschen)"""
        conn = self._get_connection()
        cursor = conn.cursor()

        now = datetime.now()

        cursor.execute("""
            INSERT INTO bathroom_events
            (start_time, start_humidity, avg_temperature, motion_detected,
             door_closed, day_of_week, hour_of_day, event_type,
             shower_start_humidity, detected_by_shower_sensor)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'shower', ?, ?)
        """, (
            now,
            humidity,
            temperature,
            motion,
            door_closed,
            now.weekday(),  # 0=Monday, 6=Sunday
            now.hour,
            shower_start_humidity,
            detected_by_shower_sensor
        ))

        conn.commit()
        return cursor.lastrowid

    def end_bathroom_event(self, event_id: int, humidity: float,
                          dehumidifier_runtime: float = None):
        """Beendet ein Badezimmer-Event und berechnet Statistiken"""
        conn = self._get_connection()
        cursor = conn.cursor()

        # Hole Event-Daten
        cursor.execute("SELECT * FROM bathroom_events WHERE id = ?", (event_id,))
        event = cursor.fetchone()

        if not event:
            logger.warning(f"Event {event_id} nicht gefunden")
            return

        start_time = datetime.fromisoformat(event['start_time'])
        end_time = datetime.now()
        duration_minutes = (end_time - start_time).seconds / 60

        # Hole Messungen für dieses Event
        cursor.execute("""
            SELECT AVG(humidity) as avg_hum, MAX(humidity) as peak_hum
            FROM bathroom_measurements
            WHERE event_id = ?
        """, (event_id,))

        stats = cursor.fetchone()
        avg_humidity = stats['avg_hum'] if stats['avg_hum'] else event['start_humidity']
        peak_humidity = stats['peak_hum'] if stats['peak_hum'] else event['start_humidity']

        # Update Event
        cursor.execute("""
            UPDATE bathroom_events
            SET end_time = ?,
                duration_minutes = ?,
                end_humidity = ?,
                avg_humidity = ?,
                peak_humidity = ?,
                dehumidifier_runtime_minutes = ?
            WHERE id = ?
        """, (
            end_time,
            duration_minutes,
            humidity,
            avg_humidity,
            peak_humidity,
            dehumidifier_runtime,
            event_id
        ))

        conn.commit()
        logger.info(f"Event {event_id} beendet: {duration_minutes:.1f} Min, Peak: {peak_humidity:.1f}%")

    def add_bathroom_measurement(self, event_id: int, humidity: float,
                                temperature: float, motion: bool,
                                dehumidifier_on: bool):
        """Fügt eine Messung während eines Events hinzu"""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO bathroom_measurements
            (event_id, timestamp, humidity, temperature, motion, dehumidifier_on)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            event_id,
            datetime.now(),
            humidity,
            temperature,
            motion,
            dehumidifier_on
        ))

        conn.commit()

    def add_bathroom_continuous_measurement(self, humidity: float = None,
                                           temperature: float = None,
                                           shower_humidity: float = None,
                                           shower_temperature: float = None):
        """
        Fügt eine kontinuierliche Badezimmer-Messung hinzu (alle 60s)
        Unabhängig von Events - für Langzeit-Analyse
        Neu: Unterstützt auch Duschsensor-Werte für verbesserte Analyse
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        # Prüfe ob Tabelle die neuen Spalten hat (für Abwärtskompatibilität)
        try:
            cursor.execute("""
                INSERT INTO bathroom_continuous_measurements
                (timestamp, humidity, temperature, shower_humidity, shower_temperature)
                VALUES (?, ?, ?, ?, ?)
            """, (
                datetime.now(),
                humidity,
                temperature,
                shower_humidity,
                shower_temperature
            ))
        except Exception as e:
            # Fallback: Alte Struktur ohne Duschsensor-Felder
            cursor.execute("""
                INSERT INTO bathroom_continuous_measurements
                (timestamp, humidity, temperature)
                VALUES (?, ?, ?)
            """, (
                datetime.now(),
                humidity,
                temperature
            ))

        conn.commit()

    def add_bathroom_device_action(self, device_type: str, device_id: str,
                                   action: str, reason: str,
                                   humidity: float, temperature: float,
                                   event_id: int = None):
        """Speichert eine Geräte-Aktion"""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO bathroom_device_actions
            (timestamp, event_id, device_type, device_id, action, reason,
             humidity_at_action, temperature_at_action)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            datetime.now(),
            event_id,
            device_type,
            device_id,
            action,
            reason,
            humidity,
            temperature
        ))

        conn.commit()

    def get_last_device_action_time(self, device_id: str, action: str) -> Optional[datetime]:
        """Gibt den Zeitpunkt der letzten aufgezeichneten Aktion für ein Gerät zurück.
        Wird genutzt um dehumidifier_start_time nach Neustarts wiederherzustellen."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT timestamp FROM bathroom_device_actions
            WHERE device_id = ? AND action = ?
            ORDER BY timestamp DESC LIMIT 1
        """, (device_id, action))
        row = cursor.fetchone()
        if row:
            try:
                return datetime.fromisoformat(row[0])
            except (ValueError, TypeError):
                return None
        return None

    def save_learned_parameter(self, parameter_name: str, value: float,
                              confidence: float, samples_used: int, reason: str):
        """Speichert einen gelernten Parameter"""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO bathroom_learned_parameters
            (timestamp, parameter_name, parameter_value, confidence, samples_used, reason)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            datetime.now(),
            parameter_name,
            value,
            confidence,
            samples_used,
            reason
        ))

        conn.commit()
        logger.info(f"Learned parameter: {parameter_name}={value:.2f} (confidence: {confidence:.2f})")

    def get_learned_parameter(self, parameter_name: str,
                             min_confidence: float = 0.7) -> Optional[float]:
        """Holt den neuesten gelernten Parameter-Wert"""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT parameter_value, confidence
            FROM bathroom_learned_parameters
            WHERE parameter_name = ? AND confidence >= ?
            ORDER BY timestamp DESC
            LIMIT 1
        """, (parameter_name, min_confidence))

        result = cursor.fetchone()
        return result['parameter_value'] if result else None

    def get_learned_parameter_details(self, parameter_name: str,
                                      min_confidence: float = 0.7) -> Optional[Dict]:
        """Holt Details des neuesten gelernten Parameters (inkl. Confidence, Samples)"""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT parameter_value, confidence, samples_used, timestamp, reason
            FROM bathroom_learned_parameters
            WHERE parameter_name = ? AND confidence >= ?
            ORDER BY timestamp DESC
            LIMIT 1
        """, (parameter_name, min_confidence))

        result = cursor.fetchone()
        if result:
            return {
                'value': result['parameter_value'],
                'confidence': result['confidence'],
                'samples_used': result['samples_used'],
                'timestamp': result['timestamp'],
                'reason': result['reason']
            }
        return None

    def reset_learned_parameters(self) -> int:
        """Löscht alle gelernten Parameter (Reset auf manuelle Werte)"""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("DELETE FROM bathroom_learned_parameters")
        deleted_count = cursor.rowcount

        conn.commit()
        logger.info(f"Reset learned parameters: {deleted_count} entries deleted")
        return deleted_count

    def get_bathroom_events(self, days_back: int = 30, limit: int = None) -> List[Dict]:
        """Holt Badezimmer-Events der letzten X Tage"""
        conn = self._get_connection()
        cursor = conn.cursor()

        start_time = datetime.now() - timedelta(days=days_back)

        query = """
            SELECT * FROM bathroom_events
            WHERE start_time >= ?
            ORDER BY start_time DESC
        """

        if limit:
            query += f" LIMIT {limit}"

        cursor.execute(query, (start_time,))

        return [dict(row) for row in cursor.fetchall()]

    def get_sensor_data_timeseries(self, sensor_id: str, hours_back: int = 6) -> List[Dict]:
        """Holt Zeitreihen-Daten für einen Sensor"""
        conn = self._get_connection()
        cursor = conn.cursor()

        start_time = datetime.now() - timedelta(hours=hours_back)

        cursor.execute("""
            SELECT timestamp, value, unit
            FROM sensor_data
            WHERE sensor_id = ? AND timestamp >= ?
            ORDER BY timestamp ASC
        """, (sensor_id, start_time))

        return [dict(row) for row in cursor.fetchall()]

    def get_bathroom_humidity_timeseries(self, hours_back: int = 6) -> List[Dict]:
        """Holt kontinuierliche Luftfeuchtigkeitsdaten aus bathroom_continuous_measurements

        Diese Methode ist speziell für die Live-Anzeige von Badezimmer-Luftfeuchtigkeit gedacht
        und nutzt die kontinuierlichen Messungen (alle 60s), nicht die sensor_data Tabelle.
        
        Returns: Liste mit dicts: [{'timestamp': ..., 'value': ..., 'unit': '%', 'shower_value': ...}, ...]
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        start_time = datetime.now() - timedelta(hours=hours_back)

        cursor.execute("""
            SELECT
                timestamp,
                humidity as value,
                '%' as unit,
                shower_humidity as shower_value
            FROM bathroom_continuous_measurements
            WHERE timestamp >= ?
              AND humidity IS NOT NULL
            ORDER BY timestamp ASC
        """, (start_time,))

        return [dict(row) for row in cursor.fetchall()]

    def create_manual_bathroom_event(self, start_time: datetime, end_time: datetime,
                                     peak_humidity: float, notes: str = None) -> int:
        """Erstellt ein manuelles Badezimmer-Event (z.B. nachträglich eingetragen)"""
        conn = self._get_connection()
        cursor = conn.cursor()

        duration_minutes = (end_time - start_time).total_seconds() / 60

        cursor.execute("""
            INSERT INTO bathroom_events
            (start_time, end_time, duration_minutes, peak_humidity,
             start_humidity, avg_humidity, day_of_week, hour_of_day, event_type)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'manual')
        """, (
            start_time,
            end_time,
            duration_minutes,
            peak_humidity,
            peak_humidity - 10,  # Schätzung
            peak_humidity - 5,   # Schätzung
            start_time.weekday(),
            start_time.hour,
        ))

        conn.commit()
        event_id = cursor.lastrowid
        logger.info(f"Manual bathroom event created: {event_id} at {start_time}")
        return event_id

    def get_bathroom_statistics(self, days_back: int = 30) -> Dict:
        """Berechnet Statistiken für Badezimmer-Automatisierung"""
        conn = self._get_connection()
        cursor = conn.cursor()

        start_time = datetime.now() - timedelta(days=days_back)

        # Event-Statistiken (nur gültige Events mit sinnvollen Werten)
        cursor.execute("""
            SELECT
                COUNT(*) as event_count,
                AVG(duration_minutes) as avg_duration,
                AVG(peak_humidity) as avg_peak_humidity,
                AVG(dehumidifier_runtime_minutes) as avg_dehumidifier_runtime
            FROM bathroom_events
            WHERE start_time >= ? 
                AND end_time IS NOT NULL
                AND duration_minutes > 0
                AND (peak_humidity IS NULL OR peak_humidity >= 0)
        """, (start_time,))

        event_stats = dict(cursor.fetchone())

        # Häufigste Duschzeiten (nach Stunde)
        cursor.execute("""
            SELECT
                hour_of_day,
                COUNT(*) as count
            FROM bathroom_events
            WHERE start_time >= ?
            GROUP BY hour_of_day
            ORDER BY count DESC
            LIMIT 5
        """, (start_time,))

        peak_hours = [dict(row) for row in cursor.fetchall()]

        # Wochentags-Verteilung
        cursor.execute("""
            SELECT
                day_of_week,
                COUNT(*) as count
            FROM bathroom_events
            WHERE start_time >= ?
            GROUP BY day_of_week
            ORDER BY day_of_week
        """, (start_time,))

        weekday_distribution = [dict(row) for row in cursor.fetchall()]

        return {
            'event_stats': event_stats,
            'peak_hours': peak_hours,
            'weekday_distribution': weekday_distribution,
            'period_days': days_back
        }

    def get_bathroom_energy_stats(self, days_back: int = 30,
                                   dehumidifier_wattage: float = 400.0,
                                   heater_wattage: float = 0.0,
                                   energy_price_per_kwh: float = 0.30) -> Dict:
        """
        Berechnet Energie-Statistiken für Badezimmer-Automatisierung

        Args:
            days_back: Zeitraum in Tagen
            dehumidifier_wattage: Leistung des Luftentfeuchters in Watt (Standard: 400W)
            heater_wattage: Wird nicht verwendet (Zentralheizung nicht messbar)
            energy_price_per_kwh: Strompreis pro kWh in EUR (Standard: 0.30€)
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        start_time = datetime.now() - timedelta(days=days_back)

        # Gesamte Laufzeit des Luftentfeuchters
        cursor.execute("""
            SELECT
                SUM(dehumidifier_runtime_minutes) as total_runtime_minutes,
                COUNT(*) as event_count
            FROM bathroom_events
            WHERE start_time >= ? AND dehumidifier_runtime_minutes IS NOT NULL
        """, (start_time,))

        result = cursor.fetchone()
        total_runtime_minutes = result['total_runtime_minutes'] or 0.0
        event_count = result['event_count'] or 0

        # Umrechnung in Stunden
        total_runtime_hours = total_runtime_minutes / 60.0

        # Energieverbrauch berechnen (nur Luftentfeuchter)
        dehumidifier_kwh = (total_runtime_hours * dehumidifier_wattage) / 1000.0
        dehumidifier_cost = dehumidifier_kwh * energy_price_per_kwh

        # Hinweis: Heizungskosten werden NICHT berechnet, da:
        # 1. Bei Zentralheizung nicht direkt messbar
        # 2. Temperaturanpassung im Bad hat minimalen Einfluss auf Gesamtverbrauch
        # 3. Nur der Luftentfeuchter hat einen messbaren, direkten Stromverbrauch

        # Gesamtkosten (nur Luftentfeuchter)
        total_kwh = dehumidifier_kwh
        total_cost = dehumidifier_cost

        # Vergleich: Wenn Luftentfeuchter immer an wäre (24/7)
        hours_in_period = days_back * 24
        always_on_kwh = (hours_in_period * dehumidifier_wattage) / 1000.0
        always_on_cost = always_on_kwh * energy_price_per_kwh

        # Ersparnis
        savings_kwh = always_on_kwh - dehumidifier_kwh
        savings_cost = always_on_cost - dehumidifier_cost
        savings_percent = (savings_kwh / always_on_kwh * 100) if always_on_kwh > 0 else 0

        # Durchschnitt pro Event
        avg_runtime_per_event = total_runtime_minutes / event_count if event_count > 0 else 0
        avg_cost_per_event = total_cost / event_count if event_count > 0 else 0

        return {
            'period_days': days_back,
            'event_count': event_count,
            'dehumidifier': {
                'runtime_hours': round(total_runtime_hours, 1),
                'runtime_minutes': round(total_runtime_minutes, 0),
                'kwh': round(dehumidifier_kwh, 2),
                'cost_eur': round(dehumidifier_cost, 2),
                'wattage': dehumidifier_wattage
            },
            'total': {
                'kwh': round(total_kwh, 2),
                'cost_eur': round(total_cost, 2)
            },
            'comparison_always_on': {
                'kwh': round(always_on_kwh, 1),
                'cost_eur': round(always_on_cost, 2),
                'savings_kwh': round(savings_kwh, 1),
                'savings_cost_eur': round(savings_cost, 2),
                'savings_percent': round(savings_percent, 1)
            },
            'per_event': {
                'avg_runtime_minutes': round(avg_runtime_per_event, 1),
                'avg_cost_eur': round(avg_cost_per_event, 3)
            },
            'energy_price_per_kwh': energy_price_per_kwh,
            'note': 'Nur Luftentfeuchter-Verbrauch. Heizungskosten (Zentralheizung) nicht einberechnet.'
        }

    # === HEIZUNGS-OPTIMIERUNG METHODEN ===

    def add_heating_observation(self, device_id: str, room_name: str = None,
                               current_temp: float = None, target_temp: float = None,
                               outdoor_temp: float = None, is_heating: bool = False,
                               presence: bool = None, window_open: bool = None,
                               energy_level: int = 2, humidity: float = None,
                               power_percentage: float = None):
        """
        Fügt eine Heizungs-Beobachtung hinzu (vereinheitlichte Methode)

        Args:
            device_id: ID des Heizgeräts (erforderlich)
            room_name: Name des Raums (optional)
            current_temp: Aktuelle Temperatur (optional)
            target_temp: Ziel-Temperatur (optional)
            outdoor_temp: Außentemperatur (optional)
            is_heating: Ob aktuell geheizt wird (default: False)
            presence: Anwesenheit erkannt (optional)
            window_open: Fenster offen (optional)
            energy_level: Energiepreis-Level 1-3 (default: 2)
            humidity: Luftfeuchtigkeit (optional)
            power_percentage: Leistung in % (optional)

        Returns:
            ID der eingefügten Zeile
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        now = datetime.now()

        cursor.execute("""
            INSERT INTO heating_observations
            (timestamp, device_id, room_name, current_temperature, target_temperature,
             outdoor_temperature, is_heating, humidity, power_percentage, hour_of_day, day_of_week)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            now,
            device_id,
            room_name,
            current_temp,
            target_temp,
            outdoor_temp,
            1 if is_heating else 0,
            humidity,
            power_percentage,
            now.hour,
            now.weekday()
        ))

        conn.commit()
        return cursor.lastrowid

    def add_heating_insight(self, insight_type: str, recommendation: str,
                           device_id: str = None, room_name: str = None,
                           saving_percent: float = None, saving_eur: float = None,
                           confidence: float = 0.7, samples: int = 0,
                           priority: str = 'medium'):
        """Speichert einen KI-generierten Insight/Vorschlag"""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO heating_insights
            (timestamp, insight_type, device_id, room_name, recommendation,
             potential_saving_percent, potential_saving_eur, confidence,
             samples_used, priority)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            datetime.now(),
            insight_type,
            device_id,
            room_name,
            recommendation,
            saving_percent,
            saving_eur,
            confidence,
            samples,
            priority
        ))

        conn.commit()
        logger.info(f"Heating insight: {insight_type} - {recommendation}")

    def get_latest_heating_insights(self, days_back: int = 7,
                                    min_confidence: float = 0.6,
                                    limit: int = 10) -> List[Dict]:
        """Holt die neuesten Heizungs-Insights"""
        conn = self._get_connection()
        cursor = conn.cursor()

        start_time = datetime.now() - timedelta(days=days_back)

        cursor.execute("""
            SELECT * FROM heating_insights
            WHERE timestamp >= ? AND confidence >= ?
            ORDER BY timestamp DESC, priority DESC
            LIMIT ?
        """, (start_time, min_confidence, limit))

        return [dict(row) for row in cursor.fetchall()]

    def save_heating_schedule(self, device_id: str, room_name: str,
                             schedule_type: str, day_of_week: int, hour: int,
                             recommended_temp: float, reason: str,
                             confidence: float, samples: int):
        """Speichert einen optimierten Heizplan"""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO heating_schedules
            (timestamp, device_id, room_name, schedule_type, day_of_week,
             hour, recommended_temperature, reason, confidence, samples_used)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            datetime.now(),
            device_id,
            room_name,
            schedule_type,
            day_of_week,
            hour,
            recommended_temp,
            reason,
            confidence,
            samples
        ))

        conn.commit()

    def get_heating_schedule(self, device_id: str = None,
                            min_confidence: float = 0.7) -> List[Dict]:
        """Holt den optimierten Heizplan für ein Gerät"""
        conn = self._get_connection()
        cursor = conn.cursor()

        if device_id:
            cursor.execute("""
                SELECT * FROM heating_schedules
                WHERE device_id = ? AND confidence >= ?
                ORDER BY day_of_week, hour
            """, (device_id, min_confidence))
        else:
            cursor.execute("""
                SELECT * FROM heating_schedules
                WHERE confidence >= ?
                ORDER BY device_id, day_of_week, hour
            """, (min_confidence,))

        return [dict(row) for row in cursor.fetchall()]

    def get_heating_observations(self, days_back: int = 7, device_id: str = None,
                                 room_name: str = None) -> List[Dict]:
        """Holt Heizungsbeobachtungen für Analytics"""
        conn = self._get_connection()
        cursor = conn.cursor()

        start_time = datetime.now() - timedelta(days=days_back)

        query = """
            SELECT
                timestamp,
                device_id,
                room_name,
                current_temperature as current_temp,
                target_temperature as target_temp,
                is_heating,
                outdoor_temperature as outdoor_temp,
                humidity,
                hour_of_day,
                day_of_week,
                power_percentage
            FROM heating_observations
            WHERE timestamp >= ?
        """

        params = [start_time]

        if device_id:
            query += " AND device_id = ?"
            params.append(device_id)

        if room_name:
            query += " AND room_name = ?"
            params.append(room_name)

        query += " ORDER BY timestamp ASC"

        cursor.execute(query, params)

        return [dict(row) for row in cursor.fetchall()]

    def get_heating_statistics(self, days_back: int = 30) -> Dict:
        """Berechnet Heizungs-Statistiken"""
        conn = self._get_connection()
        cursor = conn.cursor()

        start_time = datetime.now() - timedelta(days=days_back)

        # Gesamt-Statistiken
        cursor.execute("""
            SELECT
                COUNT(*) as total_observations,
                SUM(CASE WHEN is_heating = 1 THEN 1 ELSE 0 END) as heating_count,
                AVG(current_temperature) as avg_temp,
                AVG(target_temperature) as avg_target,
                AVG(outdoor_temperature) as avg_outdoor
            FROM heating_observations
            WHERE timestamp >= ?
        """, (start_time,))

        stats = dict(cursor.fetchone())

        # Raum-Statistiken
        cursor.execute("""
            SELECT
                room_name,
                COUNT(*) as observations,
                AVG(current_temperature) as avg_temp,
                AVG(target_temperature) as avg_target,
                SUM(CASE WHEN is_heating = 1 THEN 1 ELSE 0 END) as heating_count
            FROM heating_observations
            WHERE timestamp >= ? AND room_name IS NOT NULL
            GROUP BY room_name
        """, (start_time,))

        stats['room_stats'] = [dict(row) for row in cursor.fetchall()]

        return stats

    def cleanup_heating_observations(self, retention_days: int = 90) -> int:
        """Löscht alte Heizungsbeobachtungen"""
        conn = self._get_connection()
        cursor = conn.cursor()

        cutoff_date = datetime.now() - timedelta(days=retention_days)

        cursor.execute("""
            DELETE FROM heating_observations
            WHERE timestamp < ?
        """, (cutoff_date,))

        deleted_count = cursor.rowcount
        conn.commit()

        logger.info(f"Deleted {deleted_count} old heating observations (older than {retention_days} days)")
        return deleted_count

    # ===== Window Observations Methods =====

    def add_window_observation(self, device_id: str, device_name: str = None,
                                room_name: str = None, is_open: bool = False,
                                contact_alarm: bool = False, tilt_angle: float = None,
                                window_state: str = None):
        """Fügt eine Fenster-Beobachtung hinzu (alle 60s für Heizungsoptimierung)
        
        Args:
            device_id: Geräte-ID
            device_name: Gerätename
            room_name: Raum-Name
            is_open: True wenn Fenster offen (auch gekippt gilt als offen)
            contact_alarm: Kontaktalarm-Status
            tilt_angle: Neigungswinkel in Grad (falls Tilt-Sensor vorhanden)
            window_state: Fensterzustand: 'closed', 'tilted', 'open'
        """
        from datetime import datetime

        conn = self._get_connection()
        cursor = conn.cursor()
        
        # Prüfe ob die neuen Spalten existieren
        cursor.execute("PRAGMA table_info(window_observations)")
        columns = [col[1] for col in cursor.fetchall()]
        
        if 'tilt_angle' not in columns:
            # Füge neue Spalten hinzu
            cursor.execute("ALTER TABLE window_observations ADD COLUMN tilt_angle REAL")
            cursor.execute("ALTER TABLE window_observations ADD COLUMN window_state TEXT DEFAULT 'unknown'")
            conn.commit()
            logger.info("Added tilt_angle and window_state columns to window_observations")

        cursor.execute("""
            INSERT INTO window_observations
            (timestamp, device_id, device_name, room_name, is_open, contact_alarm, tilt_angle, window_state)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            datetime.now(),
            device_id,
            device_name,
            room_name,
            1 if is_open else 0,
            1 if contact_alarm else 0,
            tilt_angle,
            window_state or 'unknown'
        ))

        conn.commit()
        return cursor.lastrowid

    def get_current_open_windows(self) -> List[Dict]:
        """Holt alle aktuell geöffneten Fenster mit Dauer"""
        conn = self._get_connection()
        cursor = conn.cursor()

        # Nutze die View für effiziente Abfrage
        cursor.execute("""
            SELECT
                device_id,
                device_name,
                room_name,
                opened_at,
                last_seen,
                minutes_open
            FROM v_current_open_windows
            ORDER BY minutes_open DESC
        """)

        return [dict(row) for row in cursor.fetchall()]

    def get_all_windows_latest_status(self) -> List[Dict]:
        """Holt den letzten bekannten Status aller Fenster (filtert Türen/Sensoren)"""
        conn = self._get_connection()
        cursor = conn.cursor()

        # Hole die letzte Beobachtung pro Fenster
        # Filtere nur echte Fenster (entferne Türen, Temperatursensoren, etc.)
        cursor.execute("""
            WITH latest_obs AS (
                SELECT
                    device_id,
                    device_name,
                    room_name,
                    is_open,
                    contact_alarm,
                    timestamp,
                    ROW_NUMBER() OVER (PARTITION BY device_id ORDER BY timestamp DESC) as rn
                FROM window_observations
                WHERE (
                    LOWER(device_name) LIKE '%fenster%'
                    OR LOWER(device_name) LIKE '%window%'
                )
                AND NOT (
                    LOWER(device_name) LIKE '%tür%'
                    OR LOWER(device_name) LIKE '%door%'
                    OR LOWER(device_name) LIKE '%temperatur%'
                    OR LOWER(device_name) LIKE '%temperature%'
                    OR LOWER(device_name) LIKE '%gruppe%'
                    OR LOWER(device_name) LIKE '%group%'
                )
            )
            SELECT
                device_id,
                device_name,
                room_name,
                is_open,
                contact_alarm,
                timestamp
            FROM latest_obs
            WHERE rn = 1
            ORDER BY device_name ASC
        """)

        return [dict(row) for row in cursor.fetchall()]

    def get_window_observations(self, hours_back: int = 24, device_id: str = None,
                                room_name: str = None) -> List[Dict]:
        """Holt Fenster-Beobachtungen für Analytics"""
        conn = self._get_connection()
        cursor = conn.cursor()

        start_time = datetime.now() - timedelta(hours=hours_back)

        query = """
            SELECT
                timestamp,
                device_id,
                device_name,
                room_name,
                is_open,
                contact_alarm
            FROM window_observations
            WHERE timestamp >= ?
        """

        params = [start_time]

        if device_id:
            query += " AND device_id = ?"
            params.append(device_id)

        if room_name:
            query += " AND room_name = ?"
            params.append(room_name)

        query += " ORDER BY timestamp ASC"

        cursor.execute(query, params)

        return [dict(row) for row in cursor.fetchall()]

    def get_window_open_statistics(self, days_back: int = 7) -> Dict:
        """Berechnet Statistiken über offene Fenster (für Heizungsoptimierung)"""
        conn = self._get_connection()
        cursor = conn.cursor()

        start_time = datetime.now() - timedelta(days=days_back)

        # Pro Raum: wie oft und wie lange waren Fenster offen
        cursor.execute("""
            WITH window_sessions AS (
                SELECT
                    device_id,
                    device_name,
                    room_name,
                    timestamp,
                    is_open,
                    LAG(is_open, 1, 0) OVER (PARTITION BY device_id ORDER BY timestamp) as prev_open
                FROM window_observations
                WHERE timestamp >= ?
            ),
            open_events AS (
                SELECT
                    device_id,
                    device_name,
                    room_name,
                    timestamp as opened_at,
                    LEAD(timestamp) OVER (PARTITION BY device_id ORDER BY timestamp) as closed_at
                FROM window_sessions
                WHERE is_open = 1 AND prev_open = 0
            )
            SELECT
                room_name,
                device_name,
                COUNT(*) as open_count,
                AVG(CAST((julianday(closed_at) - julianday(opened_at)) * 24 * 60 AS INTEGER)) as avg_duration_minutes,
                MAX(CAST((julianday(closed_at) - julianday(opened_at)) * 24 * 60 AS INTEGER)) as max_duration_minutes,
                SUM(CAST((julianday(closed_at) - julianday(opened_at)) * 24 * 60 AS INTEGER)) as total_minutes_open
            FROM open_events
            WHERE closed_at IS NOT NULL
            GROUP BY room_name, device_name
            ORDER BY total_minutes_open DESC
        """, (start_time,))

        stats = {
            'by_room': [dict(row) for row in cursor.fetchall()],
            'period_days': days_back
        }

        return stats

    def get_window_statistics_for_charts(self, days_back: int = 7) -> Dict:
        """
        Berechnet Fenster-Statistiken speziell für Chart-Visualisierungen

        Returns:
            Dict mit:
            - duration_by_window: Liste mit {device_name, room_name, total_hours, total_minutes}
            - frequency_by_window: Liste mit {device_name, room_name, open_count}
            - daily_trends: Liste mit {date, total_opens, total_hours}
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        start_time = datetime.now() - timedelta(days=days_back)

        # Lade Raum-Zuordnungen aus rooms.json
        import json
        from pathlib import Path
        room_assignments = {}
        room_names_map = {}

        rooms_file = Path('data/rooms.json')
        if rooms_file.exists():
            try:
                with open(rooms_file, 'r') as f:
                    rooms_data = json.load(f)
                    room_assignments = rooms_data.get('assignments', {})
                    # Erstelle mapping von room_id zu room_name
                    for room in rooms_data.get('rooms', []):
                        room_names_map[room['id']] = room['name']
            except Exception as e:
                logger.warning(f"Could not load room assignments: {e}")

        # 1. Öffnungszeiten pro Fenster (für Balkendiagramm)
        cursor.execute("""
            WITH window_sessions AS (
                SELECT
                    device_id,
                    device_name,
                    room_name,
                    timestamp,
                    is_open,
                    LAG(is_open, 1, 0) OVER (PARTITION BY device_id ORDER BY timestamp) as prev_open
                FROM window_observations
                WHERE timestamp >= ?
                    AND device_id IS NOT NULL
            ),
            open_events AS (
                SELECT
                    device_id,
                    device_name,
                    room_name,
                    timestamp as opened_at,
                    LEAD(timestamp) OVER (PARTITION BY device_id ORDER BY timestamp) as closed_at
                FROM window_sessions
                WHERE is_open = 1 AND prev_open = 0
            )
            SELECT
                device_id,
                device_name,
                room_name,
                CAST(SUM(CAST((julianday(COALESCE(closed_at, datetime('now'))) - julianday(opened_at)) * 24 * 60 AS INTEGER)) AS REAL) as total_minutes
            FROM open_events
            GROUP BY device_id, device_name, room_name
            ORDER BY total_minutes DESC
        """, (start_time,))

        duration_data = []
        for row in cursor.fetchall():
            total_minutes = row['total_minutes'] or 0
            device_id = row['device_id']

            # Hole Raumnamen aus room_assignments
            room_name = row['room_name'] or 'Unbekannt'
            if device_id in room_assignments:
                room_id = room_assignments[device_id]
                room_name = room_names_map.get(room_id, room_name)

            duration_data.append({
                'device_name': row['device_name'],
                'room_name': room_name,
                'total_hours': round(total_minutes / 60, 1),
                'total_minutes': round(total_minutes, 0)
            })

        # 2. Öffnungshäufigkeit pro Fenster (für Balkendiagramm)
        cursor.execute("""
            WITH window_sessions AS (
                SELECT
                    device_id,
                    device_name,
                    room_name,
                    timestamp,
                    is_open,
                    LAG(is_open, 1, 0) OVER (PARTITION BY device_id ORDER BY timestamp) as prev_open
                FROM window_observations
                WHERE timestamp >= ?
                    AND device_id IS NOT NULL
            )
            SELECT
                device_id,
                device_name,
                room_name,
                COUNT(*) as open_count
            FROM window_sessions
            WHERE is_open = 1 AND prev_open = 0
            GROUP BY device_id, device_name, room_name
            ORDER BY open_count DESC
        """, (start_time,))

        frequency_data = []
        for row in cursor.fetchall():
            device_id = row['device_id']

            # Hole Raumnamen aus room_assignments
            room_name = row['room_name'] or 'Unbekannt'
            if device_id in room_assignments:
                room_id = room_assignments[device_id]
                room_name = room_names_map.get(room_id, room_name)

            frequency_data.append({
                'device_name': row['device_name'],
                'room_name': room_name,
                'open_count': row['open_count']
            })

        # 3. Tägliche Trends (für Linien-/Balkendiagramm)
        cursor.execute("""
            WITH window_sessions AS (
                SELECT
                    device_id,
                    timestamp,
                    is_open,
                    LAG(is_open, 1, 0) OVER (PARTITION BY device_id ORDER BY timestamp) as prev_open,
                    LEAD(timestamp) OVER (PARTITION BY device_id ORDER BY timestamp) as next_timestamp
                FROM window_observations
                WHERE timestamp >= ?
            ),
            daily_opens AS (
                SELECT
                    DATE(timestamp) as date,
                    COUNT(*) as open_count,
                    SUM(CAST((julianday(COALESCE(next_timestamp, datetime('now'))) - julianday(timestamp)) * 24 * 60 AS INTEGER)) as total_minutes
                FROM window_sessions
                WHERE is_open = 1 AND prev_open = 0
                GROUP BY DATE(timestamp)
            )
            SELECT
                date,
                open_count,
                CAST(total_minutes AS REAL) / 60 as total_hours
            FROM daily_opens
            ORDER BY date ASC
        """, (start_time,))

        daily_trends = []
        for row in cursor.fetchall():
            daily_trends.append({
                'date': row['date'],
                'open_count': row['open_count'],
                'total_hours': round(row['total_hours'] or 0, 1)
            })

        return {
            'duration_by_window': duration_data,
            'frequency_by_window': frequency_data,
            'daily_trends': daily_trends,
            'period_days': days_back,
            'start_date': start_time.strftime('%Y-%m-%d'),
            'end_date': datetime.now().strftime('%Y-%m-%d')
        }

    def cleanup_window_observations(self, retention_days: int = 90) -> int:
        """Löscht alte Fenster-Beobachtungen"""
        conn = self._get_connection()
        cursor = conn.cursor()

        cutoff_date = datetime.now() - timedelta(days=retention_days)

        cursor.execute("""
            DELETE FROM window_observations
            WHERE timestamp < ?
        """, (cutoff_date,))

        deleted_count = cursor.rowcount
        conn.commit()

        logger.info(f"Deleted {deleted_count} old window observations (older than {retention_days} days)")
        return deleted_count

    # ===== Ventilation Events Methods (Lüftungszyklen) =====

    def start_ventilation_event(self, device_id: str, device_name: str = None,
                                 room_name: str = None, temp_start: float = None,
                                 humidity_start: float = None, co2_start: int = None,
                                 outdoor_temp: float = None, outdoor_humidity: float = None,
                                 window_state: str = 'open') -> int:
        """Startet ein neues Lüftungs-Event (Fenster wurde geöffnet)
        
        Args:
            window_state: 'tilted' (gekippt) oder 'open' (weit offen)
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        now = datetime.now()
        
        # Bestimme Jahreszeit
        month = now.month
        if month in [12, 1, 2]:
            season = 'winter'
        elif month in [3, 4, 5]:
            season = 'spring'
        elif month in [6, 7, 8]:
            season = 'summer'
        else:
            season = 'autumn'
        
        # Bestimme Tageszeit
        hour = now.hour
        if 6 <= hour < 12:
            time_of_day = 'morning'
        elif 12 <= hour < 17:
            time_of_day = 'afternoon'
        elif 17 <= hour < 21:
            time_of_day = 'evening'
        else:
            time_of_day = 'night'
        
        weekday = now.weekday()

        # Lösche altes aktives Event für dieses Gerät (falls vorhanden)
        cursor.execute("DELETE FROM active_ventilations WHERE device_id = ?", (device_id,))

        # Füge window_state Spalte hinzu falls nicht vorhanden
        try:
            cursor.execute("ALTER TABLE active_ventilations ADD COLUMN window_state TEXT DEFAULT 'open'")
            conn.commit()
        except:
            pass  # Spalte existiert bereits

        # Erstelle neues aktives Event
        cursor.execute("""
            INSERT INTO active_ventilations
            (device_id, device_name, room_name, opened_at, temp_start, humidity_start, 
             co2_start, outdoor_temp, outdoor_humidity, last_check, window_state)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (device_id, device_name, room_name, now, temp_start, humidity_start,
              co2_start, outdoor_temp, outdoor_humidity, now, window_state))

        conn.commit()
        logger.debug(f"Started ventilation event for {device_name} in {room_name} (state: {window_state})")
        return cursor.lastrowid

    def end_ventilation_event(self, device_id: str, temp_end: float = None,
                               humidity_end: float = None, co2_end: int = None) -> Optional[int]:
        """Beendet ein Lüftungs-Event (Fenster wurde geschlossen)"""
        conn = self._get_connection()
        cursor = conn.cursor()

        # Hole aktives Event
        cursor.execute("""
            SELECT * FROM active_ventilations WHERE device_id = ?
        """, (device_id,))
        
        active = cursor.fetchone()
        if not active:
            logger.debug(f"No active ventilation found for device {device_id}")
            return None

        active = dict(active)
        now = datetime.now()
        opened_at = datetime.fromisoformat(active['opened_at']) if isinstance(active['opened_at'], str) else active['opened_at']
        duration_minutes = int((now - opened_at).total_seconds() / 60)

        # Berechne Änderungen
        temp_change = None
        humidity_change = None
        co2_change = None

        if temp_end is not None and active['temp_start'] is not None:
            temp_change = temp_end - active['temp_start']
        if humidity_end is not None and active['humidity_start'] is not None:
            humidity_change = humidity_end - active['humidity_start']
        if co2_end is not None and active['co2_start'] is not None:
            co2_change = co2_end - active['co2_start']

        # Bestimme Jahreszeit und Tageszeit
        month = opened_at.month
        if month in [12, 1, 2]:
            season = 'winter'
        elif month in [3, 4, 5]:
            season = 'spring'
        elif month in [6, 7, 8]:
            season = 'summer'
        else:
            season = 'autumn'
        
        hour = opened_at.hour
        if 6 <= hour < 12:
            time_of_day = 'morning'
        elif 12 <= hour < 17:
            time_of_day = 'afternoon'
        elif 17 <= hour < 21:
            time_of_day = 'evening'
        else:
            time_of_day = 'night'
        
        weekday = opened_at.weekday()

        # Berechne Effektivitäts-Score (für ML-Training)
        effectiveness = self._calculate_ventilation_effectiveness(
            duration_minutes, temp_change, co2_change, humidity_change, active['outdoor_temp']
        )

        # Hole window_state aus aktivem Event
        window_state = active.get('window_state', 'open')

        # Füge window_state Spalte zu ventilation_events hinzu falls nicht vorhanden
        # Schema-Migration: neue Spalten hinzufügen falls nicht vorhanden
        for alter_sql in [
            "ALTER TABLE ventilation_events ADD COLUMN window_state TEXT DEFAULT 'open'",
            "ALTER TABLE ventilation_events ADD COLUMN ventilation_type TEXT DEFAULT 'normal'",
            "ALTER TABLE ventilation_events ADD COLUMN co2_min_during INTEGER",
            "ALTER TABLE ventilation_events ADD COLUMN co2_max_during INTEGER",
            "ALTER TABLE ventilation_events ADD COLUMN temp_min_during REAL",
        ]:
            try:
                cursor.execute(alter_sql)
                conn.commit()
            except Exception:
                pass  # Spalte existiert bereits

        # Nachtlüften-Klassifizierung
        ventilation_type = self._classify_ventilation_type(
            opened_at=opened_at,
            closed_at=now,
            duration_minutes=duration_minutes,
            co2_start=active.get('co2_start'),
            co2_end=co2_end,
            co2_min_during=active.get('co2_min_during'),
            co2_max_during=active.get('co2_max_during'),
            temp_start=active.get('temp_start'),
            temp_end=temp_end,
            temp_min_during=active.get('temp_min_during'),
        )

        # Speichere in ventilation_events
        cursor.execute("""
            INSERT INTO ventilation_events
            (device_id, device_name, room_name, opened_at, closed_at, duration_minutes,
             temp_start, humidity_start, co2_start, temp_end, humidity_end, co2_end,
             temp_change, humidity_change, co2_change, outdoor_temp, outdoor_humidity,
             season, time_of_day, weekday, effectiveness_score, was_optimal, window_state,
             ventilation_type, co2_min_during, co2_max_during, temp_min_during)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            device_id, active['device_name'], active['room_name'],
            active['opened_at'], now, duration_minutes,
            active['temp_start'], active['humidity_start'], active['co2_start'],
            temp_end, humidity_end, co2_end,
            temp_change, humidity_change, co2_change,
            active['outdoor_temp'], active['outdoor_humidity'],
            season, time_of_day, weekday,
            effectiveness, effectiveness > 0.6 if effectiveness else None,
            window_state, ventilation_type,
            active.get('co2_min_during'), active.get('co2_max_during'),
            active.get('temp_min_during'),
        ))

        event_id = cursor.lastrowid

        # Lösche aktives Event
        cursor.execute("DELETE FROM active_ventilations WHERE device_id = ?", (device_id,))
        
        conn.commit()
        logger.info(f"Ended ventilation event for {active['device_name']}: {duration_minutes}min "
                   f"({window_state}, type={ventilation_type}), temp_change={temp_change}, co2_change={co2_change}")
        return event_id

    def _classify_ventilation_type(self, opened_at: datetime, closed_at: datetime,
                                     duration_minutes: int,
                                     co2_start: Optional[int], co2_end: Optional[int],
                                     co2_min_during: Optional[int], co2_max_during: Optional[int],
                                     temp_start: Optional[float], temp_end: Optional[float],
                                     temp_min_during: Optional[float]) -> str:
        """Klassifiziert den Typ eines Lüftungs-Events.

        Typen:
        - night_ventilation : Nachtlüften (Fenster nachts auf, ≥2h, bis morgens,
                              CO2 stabil, Temp nicht zu stark gesunken)
        - power_ventilation : Stoßlüften (kurz + weit offen, starke CO2-Reduktion)
        - quick_vent        : Kurzlüften (< 15 min)
        - normal            : Normales Lüften
        """
        if duration_minutes is None:
            return 'normal'

        hour_start = opened_at.hour
        hour_end = closed_at.hour

        # Nachtzeitraum: 21:00–06:00
        is_night_start = hour_start >= 21 or hour_start < 6
        # Morgenabschluss: 05:00–11:00
        is_morning_end = 5 <= hour_end < 11

        # --- Nachtlüften ---
        if is_night_start and duration_minutes >= 180 and is_morning_end:
            # CO2-Stabilität: maximaler Anstieg während der Öffnung < 200 ppm
            co2_stable = True
            if co2_start is not None and co2_max_during is not None:
                co2_rise = co2_max_during - co2_start
                co2_stable = co2_rise < 200  # Wenig Anstieg = Frischluft kommt rein
            elif co2_start is not None and co2_end is not None:
                co2_stable = (co2_end - co2_start) < 200

            # Temperaturstabilität: Raumtemperatur soll nicht mehr als 5 °C sinken
            temp_stable = True
            ref_temp = temp_start if temp_start is not None else temp_end
            min_temp = temp_min_during if temp_min_during is not None else temp_end
            if ref_temp is not None and min_temp is not None:
                temp_drop = ref_temp - min_temp
                temp_stable = temp_drop < 5.0

            if co2_stable and temp_stable:
                return 'night_ventilation'

        # --- Stoßlüften (kurz und effektiv) ---
        if duration_minutes <= 20:
            # CO2 muss deutlich gesunken sein
            if co2_start is not None and co2_end is not None and (co2_start - co2_end) > 150:
                return 'power_ventilation'
            return 'quick_vent'

        return 'normal'

    def update_active_ventilation_readings(self, device_id: str, co2: Optional[int],
                                            temp: Optional[float]) -> None:
        """Aktualisiert Min/Max-CO2 und Min-Temp für ein laufendes Lüftungs-Event.

        Wird vom Window-Kollektor periodisch aufgerufen, um den Verlauf während
        eines offenen Fensters zu tracken (für Nachtlüften-Klassifizierung).
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        # Schema-Migration: Spalten hinzufügen falls nicht vorhanden
        for alter_sql in [
            "ALTER TABLE active_ventilations ADD COLUMN co2_min_during INTEGER",
            "ALTER TABLE active_ventilations ADD COLUMN co2_max_during INTEGER",
            "ALTER TABLE active_ventilations ADD COLUMN temp_min_during REAL",
        ]:
            try:
                cursor.execute(alter_sql)
                conn.commit()
            except Exception:
                pass

        now = datetime.now()
        # Hole aktuellen Stand
        cursor.execute(
            "SELECT co2_min_during, co2_max_during, temp_min_during FROM active_ventilations WHERE device_id = ?",
            (device_id,)
        )
        row = cursor.fetchone()
        if row is None:
            return

        row = dict(row)
        new_co2_min = row['co2_min_during']
        new_co2_max = row['co2_max_during']
        new_temp_min = row['temp_min_during']

        if co2 is not None:
            new_co2_min = co2 if new_co2_min is None else min(new_co2_min, co2)
            new_co2_max = co2 if new_co2_max is None else max(new_co2_max, co2)
        if temp is not None:
            new_temp_min = temp if new_temp_min is None else min(new_temp_min, temp)

        cursor.execute("""
            UPDATE active_ventilations
            SET co2_min_during = ?, co2_max_during = ?, temp_min_during = ?, last_check = ?
            WHERE device_id = ?
        """, (new_co2_min, new_co2_max, new_temp_min, now, device_id))
        conn.commit()

    def _calculate_ventilation_effectiveness(self, duration: int, temp_change: float,
                                             co2_change: int, humidity_change: float,
                                             outdoor_temp: float) -> Optional[float]:
        """Berechnet einen Effektivitäts-Score für die Lüftung (0-1)
        
        Die Effektivität basiert primär auf:
        1. CO2-Reduktion (wichtigster Faktor - Luftqualität)
        2. Luftaustausch-Effizienz (CO2-Reduktion pro Minute)
        3. Feuchtigkeit-Reduktion (wichtig gegen Schimmel)
        4. Temperatur-Management (sekundär, abhängig von Jahreszeit)
        """
        if duration is None or duration < 1:
            return None
        
        score = 0.0
        weights = 0.0
        
        # === CO2-Reduktion (Gewicht: 40%) - wichtigster Faktor ===
        if co2_change is not None:
            # CO2 sinkt = negatives change = gut
            if co2_change < -400:
                score += 1.0 * 0.40
            elif co2_change < -250:
                score += 0.85 * 0.40
            elif co2_change < -150:
                score += 0.65 * 0.40
            elif co2_change < -50:
                score += 0.40 * 0.40
            else:
                score += 0.15 * 0.40
            weights += 0.40
            
            # === Bonus: CO2-Reduktion pro Minute (Effizienz) ===
            # Bei offenem Fenster sollte CO2 schneller sinken als bei gekipptem
            co2_per_minute = abs(co2_change) / max(duration, 1)
            if co2_per_minute > 30:  # Sehr schneller Luftaustausch
                score += 0.10  # Bonus für Effizienz
            elif co2_per_minute > 15:
                score += 0.05
        
        # === Luftfeuchtigkeit-Änderung (Gewicht: 30%) - wichtig gegen Schimmel ===
        if humidity_change is not None:
            if humidity_change < -15:  # Starke Reduktion
                score += 1.0 * 0.30
            elif humidity_change < -10:
                score += 0.85 * 0.30
            elif humidity_change < -5:
                score += 0.65 * 0.30
            elif humidity_change < 0:
                score += 0.45 * 0.30
            else:
                score += 0.25 * 0.30
            weights += 0.30
        
        # === Temperatur-Management (Gewicht: 30%) ===
        if temp_change is not None and outdoor_temp is not None:
            if outdoor_temp < 10:  # Kalte Jahreszeit
                # Wenig Temperaturverlust ist gut, ABER nur wenn auch Luftaustausch stattfand
                # Bei sehr wenig CO2-Änderung war der Luftaustausch zu gering
                co2_ok = co2_change is None or co2_change < -50
                
                if co2_ok:
                    if temp_change > -1:  # Kaum Wärmeverlust
                        score += 1.0 * 0.30
                    elif temp_change > -2:
                        score += 0.80 * 0.30
                    elif temp_change > -4:
                        score += 0.55 * 0.30
                    else:
                        score += 0.25 * 0.30
                else:
                    # CO2 kaum gesunken = schlechter Luftaustausch
                    # Wenig Temperaturverlust ist dann NICHT gut
                    score += 0.20 * 0.30
            else:  # Warme Jahreszeit
                if temp_change < 0:  # Abkühlung ist gut
                    score += 0.80 * 0.30
                else:
                    score += 0.50 * 0.30
            weights += 0.30
        
        # Normalisiere Score
        if weights > 0:
            final_score = score / weights
            # Beschränke auf 0-1 (wegen möglicher Boni)
            return min(1.0, max(0.0, final_score))
        
        return None

    def get_active_ventilations(self) -> List[Dict]:
        """Holt alle aktiven Lüftungen (offene Fenster)"""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT 
                device_id, device_name, room_name, opened_at,
                temp_start, humidity_start, co2_start,
                outdoor_temp, outdoor_humidity,
                CAST((julianday('now') - julianday(opened_at)) * 24 * 60 AS INTEGER) as minutes_open
            FROM active_ventilations
            ORDER BY opened_at ASC
        """)

        return [dict(row) for row in cursor.fetchall()]

    def get_ventilation_events(self, room_name: str = None, days_back: int = 7,
                                limit: int = 100) -> List[Dict]:
        """Holt abgeschlossene Lüftungs-Events"""
        conn = self._get_connection()
        cursor = conn.cursor()

        query = """
            SELECT *
            FROM ventilation_events
            WHERE closed_at IS NOT NULL
              AND opened_at >= datetime('now', ?)
        """
        params = [f'-{days_back} days']

        if room_name:
            query += " AND room_name = ?"
            params.append(room_name)

        query += " ORDER BY opened_at DESC LIMIT ?"
        params.append(limit)

        cursor.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]

    def get_ventilation_stats_by_room(self, days_back: int = 7) -> List[Dict]:
        """Holt Lüftungsstatistiken pro Raum"""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                room_name,
                COUNT(*) as total_events,
                ROUND(AVG(duration_minutes), 1) as avg_duration,
                ROUND(SUM(duration_minutes), 0) as total_duration,
                ROUND(AVG(temp_change), 2) as avg_temp_change,
                ROUND(AVG(humidity_change), 2) as avg_humidity_change,
                ROUND(AVG(co2_change), 0) as avg_co2_change,
                ROUND(AVG(outdoor_temp), 1) as avg_outdoor_temp,
                ROUND(AVG(effectiveness_score), 2) as avg_effectiveness,
                MAX(opened_at) as last_ventilation
            FROM ventilation_events
            WHERE closed_at IS NOT NULL
              AND opened_at >= datetime('now', ?)
            GROUP BY room_name
            ORDER BY total_events DESC
        """, (f'-{days_back} days',))

        return [dict(row) for row in cursor.fetchall()]

    def get_ventilation_learning_by_state(self, room_name: str = None, days_back: int = 30) -> List[Dict]:
        """Holt Lüftungs-Lernstatistiken gruppiert nach Fensterzustand (gekippt vs offen)"""
        conn = self._get_connection()
        cursor = conn.cursor()

        query = """
            SELECT
                room_name,
                COALESCE(window_state, 'open') as window_state,
                COUNT(*) as sample_count,
                ROUND(AVG(duration_minutes), 1) as avg_duration,
                ROUND(MIN(duration_minutes), 0) as min_duration,
                ROUND(MAX(duration_minutes), 0) as max_duration,
                ROUND(AVG(temp_change), 2) as avg_temp_change,
                ROUND(AVG(humidity_change), 2) as avg_humidity_change,
                ROUND(AVG(co2_change), 0) as avg_co2_change,
                ROUND(AVG(outdoor_temp), 1) as avg_outdoor_temp,
                ROUND(AVG(effectiveness_score), 2) as avg_effectiveness,
                -- Zeit bis CO2 unter 600ppm (wenn Start > 600)
                ROUND(AVG(CASE 
                    WHEN co2_start > 600 AND co2_end <= 600 THEN duration_minutes 
                    ELSE NULL 
                END), 1) as avg_time_to_good_co2,
                -- Zeit bis Temperatur um 1°C sinkt
                ROUND(AVG(CASE 
                    WHEN temp_change <= -1 THEN duration_minutes 
                    ELSE NULL 
                END), 1) as avg_time_to_1c_drop,
                -- Effektivitäts-Rate (% der Lüftungen die effektiv waren)
                ROUND(100.0 * SUM(CASE WHEN effectiveness_score > 0.6 THEN 1 ELSE 0 END) / COUNT(*), 1) as effectiveness_rate
            FROM ventilation_events
            WHERE closed_at IS NOT NULL
              AND opened_at >= datetime('now', ?)
              AND duration_minutes > 0
              AND duration_minutes < 120
        """
        params = [f'-{days_back} days']

        if room_name:
            query += " AND room_name = ?"
            params.append(room_name)

        query += " GROUP BY room_name, COALESCE(window_state, 'open') ORDER BY room_name, window_state"

        cursor.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]

    def get_optimal_ventilation_by_state(self, outdoor_temp: float, window_state: str = 'open', 
                                          room_name: str = None) -> Optional[Dict]:
        """Berechnet optimale Lüftungsdauer basierend auf Fensterzustand und Außentemperatur"""
        conn = self._get_connection()
        cursor = conn.cursor()

        query = """
            SELECT
                ROUND(AVG(duration_minutes), 0) as recommended_duration,
                ROUND(AVG(temp_change), 2) as expected_temp_change,
                ROUND(AVG(co2_change), 0) as expected_co2_change,
                ROUND(AVG(humidity_change), 2) as expected_humidity_change,
                COUNT(*) as sample_count,
                ROUND(AVG(effectiveness_score), 2) as avg_effectiveness
            FROM ventilation_events
            WHERE closed_at IS NOT NULL
              AND COALESCE(window_state, 'open') = ?
              AND outdoor_temp BETWEEN ? AND ?
              AND duration_minutes > 0
              AND duration_minutes < 120
              AND effectiveness_score > 0.5
        """
        params = [window_state, outdoor_temp - 5, outdoor_temp + 5]

        if room_name:
            query += " AND room_name = ?"
            params.append(room_name)

        cursor.execute(query, params)
        row = cursor.fetchone()
        
        if row and row['sample_count'] and row['sample_count'] >= 3:
            return dict(row)
        return None

    def get_ventilation_ml_training_data(self, min_samples: int = 10) -> List[Dict]:
        """Holt Trainingsdaten für ML-Modell (optimale Lüftungsdauer)"""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                room_name,
                outdoor_temp,
                duration_minutes,
                temp_start,
                temp_change,
                co2_start,
                co2_change,
                humidity_start,
                humidity_change,
                season,
                time_of_day,
                weekday,
                effectiveness_score,
                was_optimal
            FROM ventilation_events
            WHERE closed_at IS NOT NULL
              AND duration_minutes IS NOT NULL
              AND duration_minutes > 0
              AND duration_minutes < 120  -- Max 2 Stunden
              AND outdoor_temp IS NOT NULL
        """)

        return [dict(row) for row in cursor.fetchall()]

    def get_optimal_ventilation_duration(self, outdoor_temp: float, room_name: str = None) -> Optional[Dict]:
        """Berechnet optimale Lüftungsdauer basierend auf historischen Daten"""
        conn = self._get_connection()
        cursor = conn.cursor()

        # Suche ähnliche Bedingungen (Außentemperatur ±3°C)
        query = """
            SELECT
                ROUND(AVG(duration_minutes), 0) as recommended_duration,
                ROUND(AVG(temp_change), 2) as expected_temp_change,
                ROUND(AVG(co2_change), 0) as expected_co2_change,
                COUNT(*) as sample_count,
                ROUND(AVG(effectiveness_score), 2) as avg_effectiveness
            FROM ventilation_events
            WHERE closed_at IS NOT NULL
              AND outdoor_temp BETWEEN ? AND ?
              AND effectiveness_score > 0.5
              AND duration_minutes > 2
              AND duration_minutes < 60
        """
        params = [outdoor_temp - 3, outdoor_temp + 3]

        if room_name:
            query += " AND room_name = ?"
            params.append(room_name)

        cursor.execute(query, params)
        result = cursor.fetchone()

        if result and result['sample_count'] >= 5:
            return dict(result)
        return None

    def get_ventilation_effectiveness_by_outdoor_temp(self) -> Dict[str, Dict]:
        """Holt Lüftungseffektivität gruppiert nach Außentemperatur-Bereichen"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # Definiere Temperaturbereiche und berechne Statistiken für jeden
        temp_ranges = {
            '<5°C': (-50, 5),
            '5-10°C': (5, 10),
            '10-15°C': (10, 15),
            '15-20°C': (15, 20),
            '>20°C': (20, 50)
        }
        
        result = {}
        
        for range_name, (min_temp, max_temp) in temp_ranges.items():
            cursor.execute("""
                SELECT
                    COUNT(*) as event_count,
                    ROUND(AVG(duration_minutes), 0) as avg_duration,
                    ROUND(AVG(effectiveness_score), 2) as avg_effectiveness,
                    ROUND(AVG(temp_change), 2) as avg_temp_change,
                    ROUND(AVG(co2_change), 0) as avg_co2_change
                FROM ventilation_events
                WHERE closed_at IS NOT NULL
                  AND outdoor_temp >= ? AND outdoor_temp < ?
                  AND duration_minutes > 0
            """, (min_temp, max_temp))
            
            row = cursor.fetchone()
            if row and row['event_count'] > 0:
                result[range_name] = {
                    'event_count': row['event_count'],
                    'avg_duration': row['avg_duration'],
                    'avg_effectiveness': row['avg_effectiveness'],
                    'avg_temp_change': row['avg_temp_change'],
                    'avg_co2_change': row['avg_co2_change']
                }
        
        return result

    # ===== Raumspezifisches Lernen Methoden =====

    def save_room_learning_parameter(self, room_name: str, parameter_name: str,
                                      value: float, confidence: float = 0.7,
                                      samples: int = 0, notes: str = None):
        """Speichert gelernten Parameter für einen Raum"""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO heating_room_learning
            (room_name, timestamp, parameter_name, parameter_value, confidence, samples_used, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (room_name, datetime.now(), parameter_name, value, confidence, samples, notes))

        conn.commit()
        logger.info(f"Saved room learning: {room_name} - {parameter_name}={value}")

    def get_room_learning_parameter(self, room_name: str, parameter_name: str,
                                     min_confidence: float = 0.6) -> Optional[float]:
        """Holt gelernten Parameter für einen Raum"""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT parameter_value
            FROM heating_room_learning
            WHERE room_name = ? AND parameter_name = ? AND confidence >= ?
            ORDER BY timestamp DESC
            LIMIT 1
        """, (room_name, parameter_name, min_confidence))

        result = cursor.fetchone()
        return result['parameter_value'] if result else None

    # ===== Luftfeuchtigkeit & Schimmel-Prävention Methoden =====

    def add_humidity_alert(self, room_name: str, alert_type: str, humidity: float,
                          temperature: float, dewpoint: float, condensation_risk: bool,
                          severity: str, recommendation: str):
        """Fügt Luftfeuchtigkeit/Schimmel-Warnung hinzu"""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO humidity_alerts
            (timestamp, room_name, alert_type, humidity, temperature, dewpoint,
             condensation_risk, severity, recommendation)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (datetime.now(), room_name, alert_type, humidity, temperature,
              dewpoint, condensation_risk, severity, recommendation))

        conn.commit()
        logger.warning(f"Humidity alert: {room_name} - {alert_type} ({severity})")

    def get_active_humidity_alerts(self, room_name: str = None,
                                   hours_back: int = 24) -> List[Dict]:
        """Holt aktive Luftfeuchtigkeit-Warnungen"""
        conn = self._get_connection()
        cursor = conn.cursor()

        start_time = datetime.now() - timedelta(hours=hours_back)

        query = """
            SELECT * FROM humidity_alerts
            WHERE timestamp >= ? AND acknowledged = 0
        """
        params = [start_time]

        if room_name:
            query += " AND room_name = ?"
            params.append(room_name)

        query += " ORDER BY timestamp DESC"

        cursor.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]

    def acknowledge_humidity_alert(self, alert_id: int):
        """Markiert eine Warnung als bestätigt"""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE humidity_alerts
            SET acknowledged = 1
            WHERE id = ?
        """, (alert_id,))

        conn.commit()

    def add_ventilation_recommendation(self, room_name: str, indoor_temp: float,
                                       indoor_humidity: float, outdoor_temp: float,
                                       outdoor_humidity: float, is_beneficial: bool,
                                       abs_humidity_diff: float, duration_minutes: int,
                                       recommendation: str):
        """Fügt Lüftungsempfehlung hinzu"""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO ventilation_recommendations
            (timestamp, room_name, indoor_temp, indoor_humidity, outdoor_temp,
             outdoor_humidity, is_beneficial, absolute_humidity_diff,
             recommended_duration_minutes, recommendation_text)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (datetime.now(), room_name, indoor_temp, indoor_humidity, outdoor_temp,
              outdoor_humidity, is_beneficial, abs_humidity_diff, duration_minutes,
              recommendation))

        conn.commit()

    def get_latest_ventilation_recommendation(self, room_name: str = None) -> Optional[Dict]:
        """Holt die neueste Lüftungsempfehlung"""
        conn = self._get_connection()
        cursor = conn.cursor()

        query = """
            SELECT * FROM ventilation_recommendations
            WHERE 1=1
        """
        params = []

        if room_name:
            query += " AND room_name = ?"
            params.append(room_name)

        query += " ORDER BY timestamp DESC LIMIT 1"

        cursor.execute(query, params)
        result = cursor.fetchone()
        return dict(result) if result else None

    # ===== Dusch-Vorhersage Methoden =====

    def save_shower_prediction(self, predicted_time: datetime, confidence: float,
                               typical_hour: int, typical_weekday: int,
                               pattern_strength: float, samples: int):
        """Speichert Dusch-Vorhersage"""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO shower_predictions
            (timestamp, predicted_time, confidence, typical_hour, typical_weekday,
             pattern_strength, samples_used)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (datetime.now(), predicted_time, confidence, typical_hour, typical_weekday,
              pattern_strength, samples))

        conn.commit()

    def get_next_shower_prediction(self, min_confidence: float = 0.6) -> Optional[Dict]:
        """Holt die nächste Dusch-Vorhersage"""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT * FROM shower_predictions
            WHERE predicted_time > ? AND confidence >= ?
            ORDER BY predicted_time ASC
            LIMIT 1
        """, (datetime.now(), min_confidence))

        result = cursor.fetchone()
        return dict(result) if result else None

    def get_shower_predictions_today(self) -> List[Dict]:
        """Holt alle Vorhersagen für heute"""
        conn = self._get_connection()
        cursor = conn.cursor()

        today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start + timedelta(days=1)

        cursor.execute("""
            SELECT * FROM shower_predictions
            WHERE predicted_time BETWEEN ? AND ?
            ORDER BY predicted_time ASC
        """, (today_start, today_end))

        return [dict(row) for row in cursor.fetchall()]

    # === SYSTEM STATUS METHODEN ===

    def set_system_status(self, key: str, value: str):
        """Setzt einen System-Status-Wert (z.B. last_ml_training_run)"""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT OR REPLACE INTO system_status (key, value, timestamp)
            VALUES (?, ?, ?)
        """, (key, value, datetime.now()))

        conn.commit()

    def get_system_status(self, key: str) -> Optional[Dict]:
        """Holt einen System-Status-Wert"""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT key, value, timestamp FROM system_status
            WHERE key = ?
        """, (key,))

        result = cursor.fetchone()
        return dict(result) if result else None

    # === ML TRAINING DATA COLLECTION ===

    def add_lighting_event(self, device_id: str, device_name: str, room_name: str,
                          state: str, brightness: int = None, outdoor_light: float = None,
                          presence: bool = False, motion_detected: bool = False):
        """Fügt ein Beleuchtungs-Event für ML-Training hinzu"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        now = datetime.now()
        
        cursor.execute("""
            INSERT INTO lighting_events
            (timestamp, device_id, device_name, room_name, state, brightness,
             hour_of_day, day_of_week, is_weekend, outdoor_light, presence, motion_detected)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            now, device_id, device_name, room_name, state, brightness,
            now.hour, now.weekday(), now.weekday() >= 5,
            outdoor_light, presence, motion_detected
        ))
        
        conn.commit()
        logger.debug(f"Lighting event saved: {device_name} ({room_name}) -> {state}")

    def add_continuous_measurement(self, device_id: str, device_name: str, room_name: str,
                                  current_temp: float, target_temp: float,
                                  outdoor_temp: float = None, humidity: float = None,
                                  heating_active: bool = False, presence: bool = False,
                                  window_open: bool = False, energy_price_level: int = 2):
        """Fügt eine kontinuierliche Temperaturmessung für ML-Training hinzu"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        now = datetime.now()
        
        cursor.execute("""
            INSERT INTO continuous_measurements
            (timestamp, device_id, device_name, room_name, current_temperature, target_temperature,
             outdoor_temperature, humidity, heating_active, presence, window_open,
             hour_of_day, day_of_week, is_weekend, energy_price_level)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            now, device_id, device_name, room_name, current_temp, target_temp,
            outdoor_temp, humidity, heating_active, presence, window_open,
            now.hour, now.weekday(), now.weekday() >= 5, energy_price_level
        ))
        
        conn.commit()
        logger.debug(f"Temperature measurement saved: {device_name} ({room_name}) {current_temp}°C")

    def get_lighting_events_count(self) -> int:
        """Gibt Anzahl der Lighting Events zurück"""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM lighting_events")
        return cursor.fetchone()[0]

    def get_continuous_measurements_count(self) -> int:
        """Gibt Anzahl der Temperaturmessungen zurück"""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM continuous_measurements")
        return cursor.fetchone()[0]

    def get_lighting_events(self, days_back: int = 30, limit: int = None) -> List[Dict]:
        """Holt Lighting Events für ML-Training"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        query = """
            SELECT * FROM lighting_events
            WHERE timestamp >= ?
            ORDER BY timestamp DESC
        """
        
        if limit:
            query += f" LIMIT {limit}"
        
        cursor.execute(query, (datetime.now() - timedelta(days=days_back),))
        return [dict(row) for row in cursor.fetchall()]

    def get_continuous_measurements(self, days_back: int = 30, limit: int = None) -> List[Dict]:
        """Holt Temperaturmessungen für ML-Training"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        query = """
            SELECT * FROM continuous_measurements
            WHERE timestamp >= ?
            ORDER BY timestamp DESC
        """
        
        if limit:
            query += f" LIMIT {limit}"
        
        cursor.execute(query, (datetime.now() - timedelta(days=days_back),))
        return [dict(row) for row in cursor.fetchall()]

    def close(self):
        """Schließt die Datenbankverbindung"""
        if self.connection:
            self.connection.close()
            self.connection = None

    def __del__(self):
        """Destructor - schließt Verbindung"""
        self.close()

    def __enter__(self):
        """Context manager entry - returns self for use in 'with' statements"""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - ensures connection is closed"""
        self.close()
        return False  # Don't suppress exceptions

    def optimize(self, enable_auto_vacuum: bool = True) -> Dict[str, Any]:
        """
        Optimiert die Datenbank für bessere Performance
        
        Args:
            enable_auto_vacuum: Auto-Vacuum aktivieren (empfohlen)
            
        Returns:
            Dict mit Optimierungs-Statistiken
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        stats = {
            'start_time': datetime.now(),
            'size_before_mb': 0,
            'size_after_mb': 0,
            'operations': []
        }
        
        try:
            # Größe vor Optimierung
            size_before = self.db_path.stat().st_size
            stats['size_before_mb'] = round(size_before / 1024 / 1024, 2)
            logger.info(f"Database size before optimization: {stats['size_before_mb']} MB")
            
            # 1. Optimiere Cache für bessere Performance
            logger.info("Optimizing cache settings...")
            cursor.execute("PRAGMA cache_size = 10000")  # ~40MB Cache
            stats['operations'].append('Cache size increased to 10000 pages (~40MB)')
            
            # 2. Journal Mode auf WAL für bessere Concurrent Performance
            cursor.execute("PRAGMA journal_mode")
            current_mode = cursor.fetchone()[0]
            if current_mode != 'wal':
                logger.info("Switching to WAL mode...")
                cursor.execute("PRAGMA journal_mode=WAL")
                stats['operations'].append('Journal mode set to WAL (Write-Ahead Logging)')
            
            # 3. Auto-Vacuum aktivieren (verhindert Fragmentierung)
            if enable_auto_vacuum:
                cursor.execute("PRAGMA auto_vacuum")
                current_autovac = cursor.fetchone()[0]
                if current_autovac == 0:
                    logger.info("Enabling auto-vacuum (requires VACUUM)...")
                    cursor.execute("PRAGMA auto_vacuum = INCREMENTAL")
                    stats['operations'].append('Auto-vacuum enabled (INCREMENTAL)')
            
            # 4. VACUUM - Komprimiert Datenbank und entfernt Fragmentierung
            logger.info("Running VACUUM (this may take a moment)...")
            cursor.execute("VACUUM")
            stats['operations'].append('VACUUM completed (removed fragmentation)')
            
            # 5. ANALYZE - Aktualisiert Statistiken für Query Optimizer
            logger.info("Running ANALYZE...")
            cursor.execute("ANALYZE")
            stats['operations'].append('ANALYZE completed (updated query planner statistics)')
            
            # 6. Synchronous Mode optimieren
            cursor.execute("PRAGMA synchronous = NORMAL")
            stats['operations'].append('Synchronous mode set to NORMAL (faster writes, still safe)')
            
            # 7. Temp Store in Memory
            cursor.execute("PRAGMA temp_store = MEMORY")
            stats['operations'].append('Temp store set to MEMORY (faster temporary operations)')
            
            conn.commit()
            
            # Größe nach Optimierung
            size_after = self.db_path.stat().st_size
            stats['size_after_mb'] = round(size_after / 1024 / 1024, 2)
            stats['saved_mb'] = round((size_before - size_after) / 1024 / 1024, 2)
            stats['end_time'] = datetime.now()
            stats['duration_seconds'] = (stats['end_time'] - stats['start_time']).total_seconds()
            
            logger.info(f"Database optimization completed:")
            logger.info(f"  Size before: {stats['size_before_mb']} MB")
            logger.info(f"  Size after:  {stats['size_after_mb']} MB")  
            logger.info(f"  Saved:       {stats['saved_mb']} MB")
            logger.info(f"  Duration:    {stats['duration_seconds']:.2f}s")
            
            return stats
            
        except Exception as e:
            logger.error(f"Error during database optimization: {e}")
            stats['error'] = str(e)
            return stats
    
    def get_database_stats(self) -> Dict[str, Any]:
        """Liefert Statistiken über die Datenbank"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        stats = {}
        
        # Datenbankgröße
        stats['size_mb'] = round(self.db_path.stat().st_size / 1024 / 1024, 2)
        
        # Anzahl Tabellen
        cursor.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
        stats['table_count'] = cursor.fetchone()[0]
        
        # Anzahl Indizes
        cursor.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='index' AND sql IS NOT NULL")
        stats['index_count'] = cursor.fetchone()[0]
        
        # Pragma-Einstellungen
        cursor.execute("PRAGMA page_size")
        stats['page_size'] = cursor.fetchone()[0]
        
        cursor.execute("PRAGMA cache_size")
        stats['cache_size'] = cursor.fetchone()[0]
        stats['cache_mb'] = round((stats['cache_size'] * stats['page_size']) / 1024 / 1024, 2)
        
        cursor.execute("PRAGMA journal_mode")
        stats['journal_mode'] = cursor.fetchone()[0]
        
        cursor.execute("PRAGMA auto_vacuum")
        auto_vac = cursor.fetchone()[0]
        stats['auto_vacuum'] = {0: 'NONE', 1: 'FULL', 2: 'INCREMENTAL'}.get(auto_vac, 'UNKNOWN')
        
        cursor.execute("PRAGMA synchronous")
        sync = cursor.fetchone()[0]
        stats['synchronous'] = {0: 'OFF', 1: 'NORMAL', 2: 'FULL', 3: 'EXTRA'}.get(sync, 'UNKNOWN')
        
        # Größte Tabellen - ALLE Tabellen mit timestamp-Spalte
        large_tables = []
        all_tables = [
            'sensor_data', 'window_observations', 'continuous_measurements',
            'heating_observations', 'lighting_events', 'presence_data',
            'temperature_observations', 'external_data', 'decisions',
            'bathroom_events', 'bathroom_measurements', 'bathroom_device_actions',
            'bathroom_continuous_measurements', 'heating_insights', 'heating_schedules',
            'humidity_alerts', 'ventilation_recommendations', 'shower_predictions'
        ]
        for table in all_tables:
            try:
                cursor.execute(f"SELECT COUNT(*) FROM {table}")
                count = cursor.fetchone()[0]
                if count > 0:
                    large_tables.append({'name': table, 'row_count': count})
            except:
                pass
        
        stats['large_tables'] = sorted(large_tables, key=lambda x: x['row_count'], reverse=True)
        
        # Gesamtanzahl Zeilen
        stats['total_rows'] = sum(t['row_count'] for t in large_tables)
        
        return stats
