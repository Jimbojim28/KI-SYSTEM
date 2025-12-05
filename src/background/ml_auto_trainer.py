"""
Background Task: Automatisches ML-Training
Trainiert Lighting, Temperature und Forgotten Light Modelle sobald genug Daten vorhanden sind
"""

import threading
import time
import json
from pathlib import Path
from datetime import datetime, timedelta
from loguru import logger
from typing import Dict, Optional

from src.utils.database import Database
from src.models.lighting_model import LightingModel
from src.models.temperature_model import TemperatureModel
from src.models.forgotten_light_model import ForgottenLightModel
from src.models.model_version_manager import ModelVersionManager


class MLAutoTrainer:
    """
    Background-Prozess für automatisches ML-Training

    - Läuft täglich um 2:00 Uhr
    - Prüft ob genug Trainingsdaten vorhanden sind
    - Trainiert Modelle automatisch
    - Speichert Trainingshistorie
    """

    # Minimale Daten-Anforderungen
    MIN_LIGHTING_SAMPLES = 100      # Mindestens 100 Licht-Events
    MIN_TEMPERATURE_SAMPLES = 200   # Mindestens 200 Temperatur-Readings
    MIN_FORGOTTEN_LIGHT_SAMPLES = 50  # Mindestens 50 Licht-Sessions für Forgotten Light
    MIN_DAYS_DATA = 3               # Mindestens 3 Tage Daten

    def __init__(self, run_at_hour: int = 2):
        """
        Args:
            run_at_hour: Uhrzeit für tägliche Ausführung (default: 2 = 2:00 Uhr)
        """
        self.run_at_hour = run_at_hour
        self.running = False
        self.thread = None
        self.last_run = None
        self.db = Database()
        self.status_file = Path('data/ml_training_status.json')

        # Model Version Manager für Versioning & Rollback
        self.version_manager = ModelVersionManager(models_dir='models')

        # Progress Tracking für Live-Updates
        self.training_progress = {
            'status': 'idle',  # idle, training, completed, error
            'model': None,     # 'lighting', 'temperature', or None
            'progress': 0,     # 0-100
            'step': '',        # Aktueller Schritt
            'started_at': None,
            'completed_at': None,
            'error': None
        }

    def start(self):
        """Startet den Background-Prozess"""
        if self.running:
            logger.warning("MLAutoTrainer is already running")
            return

        self.running = True
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()
        logger.info(f"MLAutoTrainer started (runs daily at {self.run_at_hour}:00)")

    def stop(self):
        """Stoppt den Background-Prozess"""
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
        logger.info("MLAutoTrainer stopped")

    def get_training_progress(self) -> Dict:
        """
        Gibt aktuellen Training-Progress zurück (für API)

        Returns:
            Dict mit Status, Progress, Step, etc.
        """
        return self.training_progress.copy()

    def _update_progress(self, status: str = None, model: str = None,
                        progress: int = None, step: str = None, error: str = None):
        """
        Aktualisiert den Training-Progress

        Args:
            status: idle, training, completed, error
            model: lighting, temperature, oder None
            progress: 0-100
            step: Beschreibung des aktuellen Schritts
            error: Fehlermeldung falls status=error
        """
        if status is not None:
            self.training_progress['status'] = status
        if model is not None:
            self.training_progress['model'] = model
        if progress is not None:
            self.training_progress['progress'] = progress
        if step is not None:
            self.training_progress['step'] = step
        if error is not None:
            self.training_progress['error'] = error

        # Timestamps
        if status == 'training' and self.training_progress['started_at'] is None:
            self.training_progress['started_at'] = datetime.now().isoformat()
        if status in ['completed', 'error']:
            self.training_progress['completed_at'] = datetime.now().isoformat()

    def _run_loop(self):
        """Haupt-Loop des Background-Prozesses"""
        while self.running:
            try:
                # Prüfe ob es Zeit für Training ist
                if self._should_run_now():
                    logger.info("🤖 Starting automatic ML training check...")
                    self._check_and_train()
                    self.last_run = datetime.now()

                # Warte 1 Stunde bevor nächster Check
                time.sleep(3600)

            except Exception as e:
                logger.error(f"Error in MLAutoTrainer loop: {e}")
                time.sleep(60)  # Bei Fehler 1 Minute warten

    def _should_run_now(self) -> bool:
        """
        Prüft ob jetzt trainiert werden soll

        Returns:
            True wenn es Zeit ist zu trainieren
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

    def _check_and_train(self):
        """Prüft Daten und trainiert Modelle falls möglich"""

        # Lade aktuellen Status
        status = self._load_status()

        # Prüfe Lighting Model
        if self._should_train_lighting(status):
            logger.info("[TRAIN] Sufficient data for Lighting Model - starting training...")
            success = self._train_lighting_model()
            if success:
                status['lighting_last_trained'] = datetime.now().isoformat()
                status['lighting_trained'] = True
                logger.success("[OK] Lighting Model trained successfully!")
                self._update_progress(status='completed')
            else:
                logger.warning("[FAILED] Lighting Model training failed")

        # Prüfe Temperature Model
        if self._should_train_temperature(status):
            logger.info("[TRAIN] Sufficient data for Temperature Model - starting training...")
            success = self._train_temperature_model()
            if success:
                status['temperature_last_trained'] = datetime.now().isoformat()
                status['temperature_trained'] = True
                logger.success("[OK] Temperature Model trained successfully!")
                self._update_progress(status='completed')
            else:
                logger.warning("[FAILED] Temperature Model training failed")

        # Prüfe Forgotten Light Model
        if self._should_train_forgotten_light(status):
            logger.info("[TRAIN] Sufficient data for Forgotten Light Model - starting training...")
            success = self._train_forgotten_light_model()
            if success:
                status['forgotten_light_last_trained'] = datetime.now().isoformat()
                status['forgotten_light_trained'] = True
                logger.success("[OK] Forgotten Light Model trained successfully!")
                self._update_progress(status='completed')
            else:
                logger.warning("[FAILED] Forgotten Light Model training failed")

        # Speichere Status
        self._save_status(status)

        # Reset zu idle nach einiger Zeit (5 Sekunden)
        time.sleep(5)
        if self.training_progress['status'] == 'completed':
            self._update_progress(status='idle', model=None, progress=0, step='')

    def _should_train_lighting(self, status: Dict) -> bool:
        """
        Prüft ob Lighting Model trainiert werden soll

        Args:
            status: Aktueller Trainingsstatus

        Returns:
            True wenn Training sinnvoll ist
        """
        # Bereits vor weniger als 24 Stunden trainiert?
        last_trained = status.get('lighting_last_trained')
        if last_trained:
            last_trained_dt = datetime.fromisoformat(last_trained)
            if datetime.now() - last_trained_dt < timedelta(hours=24):
                return False

        # Prüfe ob genug Daten vorhanden
        try:
            # Zähle Licht-Events aus NEUER lighting_events Tabelle
            light_events = 0
            try:
                result = self.db.execute("SELECT COUNT(*) as count FROM lighting_events")
                light_events = result[0]['count'] if result else 0
            except Exception:
                # Fallback auf alte decisions Tabelle
                result = self.db.execute(
                    "SELECT COUNT(*) as count FROM decisions WHERE device_id LIKE '%light%' OR device_id LIKE '%lamp%'"
                )
                light_events = result[0]['count'] if result else 0

            # Prüfe Datenzeitraum aus neuer Tabelle
            days_of_data = 0
            try:
                result = self.db.execute("SELECT MIN(timestamp) as first_reading FROM lighting_events")
                if result and result[0]['first_reading']:
                    first_reading = datetime.fromisoformat(result[0]['first_reading'])
                    days_of_data = (datetime.now() - first_reading).days
            except Exception:
                result = self.db.execute("SELECT MIN(timestamp) as first_reading FROM sensor_data")
                if result and result[0]['first_reading']:
                    first_reading = datetime.fromisoformat(result[0]['first_reading'])
                    days_of_data = (datetime.now() - first_reading).days

            logger.info(f"Lighting data check: {light_events} events, {days_of_data} days")

            # Training möglich?
            return (light_events >= self.MIN_LIGHTING_SAMPLES and
                   days_of_data >= self.MIN_DAYS_DATA)

        except Exception as e:
            logger.error(f"Error checking lighting data: {e}")
            return False

    def _should_train_temperature(self, status: Dict) -> bool:
        """
        Prüft ob Temperature Model trainiert werden soll

        Args:
            status: Aktueller Trainingsstatus

        Returns:
            True wenn Training sinnvoll ist
        """
        # Bereits vor weniger als 24 Stunden trainiert?
        last_trained = status.get('temperature_last_trained')
        if last_trained:
            last_trained_dt = datetime.fromisoformat(last_trained)
            if datetime.now() - last_trained_dt < timedelta(hours=24):
                return False

        # Prüfe ob genug Daten vorhanden
        try:
            # Zähle Temperatur-Readings aus NEUER continuous_measurements Tabelle
            temp_readings = 0
            try:
                result = self.db.execute(
                    "SELECT COUNT(*) as count FROM continuous_measurements WHERE sensor_type = 'temperature'"
                )
                temp_readings = result[0]['count'] if result else 0
            except Exception:
                # Fallback auf alte sensor_data Tabelle
                result = self.db.execute(
                    "SELECT COUNT(*) as count FROM sensor_data WHERE sensor_id LIKE '%temp%' OR sensor_id LIKE '%temperature%'"
                )
                temp_readings = result[0]['count'] if result else 0

            # Prüfe Datenzeitraum
            days_of_data = 0
            try:
                result = self.db.execute(
                    "SELECT MIN(timestamp) as first_reading FROM continuous_measurements"
                )
                if result and result[0]['first_reading']:
                    first_reading = datetime.fromisoformat(result[0]['first_reading'])
                    days_of_data = (datetime.now() - first_reading).days
            except Exception:
                result = self.db.execute("SELECT MIN(timestamp) as first_reading FROM sensor_data")
                if result and result[0]['first_reading']:
                    first_reading = datetime.fromisoformat(result[0]['first_reading'])
                    days_of_data = (datetime.now() - first_reading).days

            logger.info(f"Temperature data check: {temp_readings} readings, {days_of_data} days")

            # Training möglich?
            return (temp_readings >= self.MIN_TEMPERATURE_SAMPLES and
                   days_of_data >= self.MIN_DAYS_DATA)

        except Exception as e:
            logger.error(f"Error checking temperature data: {e}")
            return False

    def _train_lighting_model(self) -> bool:
        """
        Trainiert das Lighting Model

        Returns:
            True bei Erfolg
        """
        try:
            self._update_progress(status='training', model='lighting', progress=0, step='Initialisierung...')

            # Hole Trainingsdaten aus der NEUEN lighting_events Tabelle
            self._update_progress(progress=10, step='Lade Licht-Events aus Datenbank...')
            light_states = []
            
            # Versuche zuerst die neue Tabelle
            try:
                result = self.db.execute(
                    """SELECT timestamp, device_id, device_name, room_name, state, brightness, 
                              hour_of_day, day_of_week, is_weekend, outdoor_light, 
                              presence, motion_detected
                       FROM lighting_events 
                       ORDER BY timestamp DESC LIMIT 10000"""
                )
                for row in result:
                    light_states.append({
                        'timestamp': row['timestamp'],
                        'device_id': row['device_id'],
                        'device_name': row.get('device_name'),
                        'room_name': row.get('room_name'),
                        'state': row['state'],  # 'on' oder 'off'
                        'brightness': row.get('brightness') or 0,
                        'hour_of_day': row.get('hour_of_day') or 0,
                        'day_of_week': row.get('day_of_week') or 0,
                        'is_weekend': 1 if row.get('is_weekend') else 0,
                        'outdoor_light': row.get('outdoor_light') or 0,
                        'presence': 1 if row.get('presence') else 0,
                        'motion_detected': 1 if row.get('motion_detected') else 0
                    })
                logger.info(f"Loaded {len(light_states)} events from lighting_events table")
            except Exception as e:
                logger.warning(f"Could not load from lighting_events: {e}, trying decisions table")
                # Fallback auf alte decisions Tabelle
                result = self.db.execute(
                    "SELECT timestamp, device_id, action, state_before, state_after FROM decisions WHERE device_id LIKE '%light%' ORDER BY timestamp DESC LIMIT 5000"
                )
                for row in result:
                    light_states.append({
                        'timestamp': row['timestamp'],
                        'device_id': row['device_id'],
                        'action': row['action'],
                        'state': 'on' if row.get('state_after') else 'off'
                    })

            if len(light_states) < self.MIN_LIGHTING_SAMPLES:
                logger.warning(f"Not enough light events: {len(light_states)} < {self.MIN_LIGHTING_SAMPLES}")
                self._update_progress(status='error', error=f'Nicht genug Daten: {len(light_states)} Events (benötigt: {self.MIN_LIGHTING_SAMPLES})')
                return False

            # Hole Sensor-Kontext aus continuous_measurements
            self._update_progress(progress=25, step='Lade Sensor-Kontext...')
            sensor_data = []
            try:
                result = self.db.execute(
                    """SELECT timestamp, sensor_type, value, room_id
                       FROM continuous_measurements 
                       ORDER BY timestamp DESC LIMIT 20000"""
                )
                for row in result:
                    sensor_data.append({
                        'timestamp': row['timestamp'],
                        'sensor_id': row.get('room_id', '') + '_' + row['sensor_type'],
                        'sensor_type': row['sensor_type'],
                        'value': row['value']
                    })
            except Exception as e:
                logger.warning(f"Could not load continuous_measurements: {e}, trying sensor_data")
                # Fallback
                result = self.db.execute(
                    "SELECT timestamp, sensor_id, value FROM sensor_data ORDER BY timestamp DESC LIMIT 10000"
                )
                for row in result:
                    sensor_data.append({
                        'timestamp': row['timestamp'],
                        'sensor_id': row['sensor_id'],
                        'value': row['value']
                    })

            # Erstelle und trainiere Modell
            self._update_progress(progress=40, step='Bereite Trainingsdaten vor...')
            model = LightingModel(model_type="random_forest")
            
            # Die lighting_events Tabelle hat alle nötigen Daten direkt
            # (state, brightness, hour_of_day, etc.)
            if light_states and 'state' in light_states[0]:
                logger.info("Using direct training data preparation (lighting_events has all data)")
                X, y = model.prepare_training_data_direct(light_states)
            else:
                # Fallback: Merge mit sensor_data
                logger.info("Using merged training data preparation")
                X, y = model.prepare_training_data(sensor_data, light_states)

            if len(X) < 50:
                logger.warning(f"Not enough training samples after preparation: {len(X)}")
                self._update_progress(status='error', error=f'Zu wenig Samples nach Vorbereitung: {len(X)}. Prüfe ob die Daten korrekt gesammelt werden.')
                return False

            self._update_progress(progress=50, step=f'Trainiere Modell mit {len(X)} Samples...')
            metrics = model.train(X, y)

            # === MODEL VERSIONING & QUALITY CHECK ===

            # 1. Backup des aktuellen Modells (falls vorhanden)
            self._update_progress(progress=70, step='Erstelle Backup des alten Modells...')
            self.version_manager.backup_current_model('lighting_model')

            # 2. Vergleiche mit vorheriger Version
            self._update_progress(progress=75, step='Vergleiche mit vorheriger Version...')
            comparison = self.version_manager.compare_with_previous('lighting_model', metrics)

            logger.info(f"Model comparison: {comparison['recommendation']}")
            logger.info(f"Improved: {comparison['improved']}, "
                       f"Better metrics: {comparison.get('improved_metrics', 0)}, "
                       f"Worse metrics: {comparison.get('worse_metrics', 0)}")

            # 3. Speichere neues Modell
            self._update_progress(progress=80, step='Speichere trainiertes Modell...')
            models_dir = Path('models')
            models_dir.mkdir(exist_ok=True)
            model.save(str(models_dir / 'lighting_model.pkl'))

            # 4. Registriere neue Version
            self._update_progress(progress=85, step='Registriere Model-Version...')
            version_notes = f"Accuracy: {metrics.get('accuracy', 0):.3f}, Samples: {len(X)}"
            if not comparison['improved']:
                version_notes += " [Performance-Warnung]"

            self.version_manager.register_model(
                model_name='lighting_model',
                metrics=metrics,
                notes=version_notes
            )

            # 5. Speichere Metriken in DB
            self._update_progress(progress=90, step='Speichere Metriken...')
            self._save_training_metrics('lighting', metrics)

            # 6. Cleanup alte Versionen
            self._update_progress(progress=95, step='Cleanup alte Versionen...')
            self.version_manager.cleanup_old_versions('lighting_model', keep_last_n=5)

            logger.info(f"Lighting Model trained with accuracy: {metrics.get('accuracy', 0):.2f}")
            if not comparison['improved']:
                logger.warning(f"⚠️ New model may be worse than previous version!")

            self._update_progress(progress=100, step='Lighting Model erfolgreich trainiert!')
            return True

        except Exception as e:
            logger.error(f"Error training lighting model: {e}")
            import traceback
            logger.error(traceback.format_exc())
            self._update_progress(status='error', error=str(e))
            return False

    def _train_temperature_model(self) -> bool:
        """
        Trainiert das Temperature Model

        Returns:
            True bei Erfolg
        """
        try:
            self._update_progress(status='training', model='temperature', progress=0, step='Initialisierung...')

            # Hole Trainingsdaten aus der NEUEN continuous_measurements Tabelle
            self._update_progress(progress=10, step='Lade Temperaturdaten aus Datenbank...')
            sensor_data = []
            
            # Versuche zuerst die neue Tabelle (mit den tatsächlichen Spaltennamen)
            try:
                result = self.db.execute(
                    """SELECT timestamp, device_id, device_name, room_name,
                              current_temperature, target_temperature, outdoor_temperature,
                              humidity, heating_active, presence, window_open,
                              hour_of_day, day_of_week, is_weekend, energy_price_level
                       FROM continuous_measurements 
                       ORDER BY timestamp DESC LIMIT 20000"""
                )
                for row in result:
                    sensor_data.append({
                        'timestamp': row['timestamp'],
                        'device_id': row.get('device_id'),
                        'device_name': row.get('device_name'),
                        'room_name': row.get('room_name'),
                        'current_temperature': row.get('current_temperature'),
                        'target_temperature': row.get('target_temperature'),
                        'outdoor_temperature': row.get('outdoor_temperature'),
                        'humidity': row.get('humidity'),
                        'heating_active': 1 if row.get('heating_active') else 0,
                        'presence': 1 if row.get('presence') else 0,
                        'window_open': 1 if row.get('window_open') else 0,
                        'hour_of_day': row.get('hour_of_day') or 0,
                        'day_of_week': row.get('day_of_week') or 0,
                        'is_weekend': 1 if row.get('is_weekend') else 0,
                        'energy_price_level': row.get('energy_price_level') or 2
                    })
                logger.info(f"Loaded {len(sensor_data)} readings from continuous_measurements table")
            except Exception as e:
                logger.warning(f"Could not load from continuous_measurements: {e}, trying sensor_data")
                # Fallback auf alte sensor_data Tabelle
                result = self.db.execute(
                    "SELECT timestamp, sensor_id, value FROM sensor_data WHERE sensor_id LIKE '%temp%' ORDER BY timestamp DESC LIMIT 10000"
                )
                for row in result:
                    sensor_data.append({
                        'timestamp': row['timestamp'],
                        'sensor_id': row['sensor_id'],
                        'value': row['value']
                    })

            if len(sensor_data) < self.MIN_TEMPERATURE_SAMPLES:
                logger.warning(f"Not enough temperature readings: {len(sensor_data)} < {self.MIN_TEMPERATURE_SAMPLES}")
                self._update_progress(status='error', error=f'Nicht genug Daten: {len(sensor_data)} Readings (benötigt: {self.MIN_TEMPERATURE_SAMPLES})')
                return False

            # Erstelle und trainiere Modell
            self._update_progress(progress=30, step='Bereite Trainingsdaten vor...')
            model = TemperatureModel(model_type="gradient_boosting")
            
            # Die continuous_measurements Tabelle hat alle nötigen Daten direkt
            # (current_temperature, target_temperature, etc.)
            if sensor_data and 'current_temperature' in sensor_data[0]:
                logger.info("Using prepare_training_data_direct for continuous_measurements format")
                X, y = model.prepare_training_data_direct(sensor_data)
            else:
                # Legacy: versuche trotzdem die direkte Methode
                logger.info("Using prepare_training_data_direct (legacy fallback)")
                X, y = model.prepare_training_data_direct(sensor_data)

            if len(X) < 50:
                logger.warning(f"Not enough training samples after preparation: {len(X)}")
                self._update_progress(status='error', error=f'Zu wenig Samples nach Vorbereitung: {len(X)}')
                return False

            self._update_progress(progress=50, step=f'Trainiere Modell mit {len(X)} Samples...')
            metrics = model.train(X, y)

            # === MODEL VERSIONING & QUALITY CHECK ===

            # 1. Backup des aktuellen Modells (falls vorhanden)
            self._update_progress(progress=70, step='Erstelle Backup des alten Modells...')
            self.version_manager.backup_current_model('temperature_model')

            # 2. Vergleiche mit vorheriger Version
            self._update_progress(progress=75, step='Vergleiche mit vorheriger Version...')
            comparison = self.version_manager.compare_with_previous('temperature_model', metrics)

            logger.info(f"Model comparison: {comparison['recommendation']}")
            logger.info(f"Improved: {comparison['improved']}, "
                       f"Better metrics: {comparison.get('improved_metrics', 0)}, "
                       f"Worse metrics: {comparison.get('worse_metrics', 0)}")

            # 3. Speichere neues Modell
            self._update_progress(progress=80, step='Speichere trainiertes Modell...')
            models_dir = Path('models')
            models_dir.mkdir(exist_ok=True)
            model.save(str(models_dir / 'temperature_model.pkl'))

            # 4. Registriere neue Version
            self._update_progress(progress=85, step='Registriere Model-Version...')
            version_notes = f"R²: {metrics.get('r2_score', 0):.3f}, MAE: {metrics.get('mae', 0):.2f}, Samples: {len(X)}"
            if not comparison['improved']:
                version_notes += " [Performance-Warnung]"

            self.version_manager.register_model(
                model_name='temperature_model',
                metrics=metrics,
                notes=version_notes
            )

            # 5. Speichere Metriken in DB
            self._update_progress(progress=90, step='Speichere Metriken...')
            self._save_training_metrics('temperature', metrics)

            # 6. Cleanup alte Versionen
            self._update_progress(progress=95, step='Cleanup alte Versionen...')
            self.version_manager.cleanup_old_versions('temperature_model', keep_last_n=5)

            logger.info(f"Temperature Model trained with R²: {metrics.get('r2_score', 0):.2f}, MAE: {metrics.get('mae', 0):.2f}")
            if not comparison['improved']:
                logger.warning(f"⚠️ New model may be worse than previous version!")

            self._update_progress(progress=100, step='Temperature Model erfolgreich trainiert!')
            return True

        except Exception as e:
            logger.error(f"Error training temperature model: {e}")
            import traceback
            logger.error(traceback.format_exc())
            self._update_progress(status='error', error=str(e))
            return False

    def _should_train_forgotten_light(self, status: Dict) -> bool:
        """
        Prüft ob Forgotten Light Model trainiert werden soll

        Args:
            status: Aktueller Trainingsstatus

        Returns:
            True wenn Training sinnvoll ist
        """
        # Bereits vor weniger als 24 Stunden trainiert?
        last_trained = status.get('forgotten_light_last_trained')
        if last_trained:
            last_trained_dt = datetime.fromisoformat(last_trained)
            if datetime.now() - last_trained_dt < timedelta(hours=24):
                return False

        # Prüfe ob genug Daten vorhanden
        try:
            # Zähle Licht-Sessions (ON->OFF Paare) aus lighting_events
            # Wir brauchen genug "Sessions" um Muster zu lernen
            result = self.db.execute("""
                SELECT COUNT(*) as count FROM (
                    SELECT device_id, 
                           SUM(CASE WHEN state = 'on' THEN 1 ELSE 0 END) as on_count,
                           SUM(CASE WHEN state = 'off' THEN 1 ELSE 0 END) as off_count
                    FROM lighting_events
                    GROUP BY device_id
                    HAVING on_count > 0 AND off_count > 0
                )
            """)
            sessions_count = result[0]['count'] if result else 0

            # Zähle auch die absolute Anzahl an Events
            result = self.db.execute("SELECT COUNT(*) as count FROM lighting_events")
            total_events = result[0]['count'] if result else 0

            # Prüfe Datenzeitraum
            days_of_data = 0
            result = self.db.execute("SELECT MIN(timestamp) as first_reading FROM lighting_events")
            if result and result[0]['first_reading']:
                first_reading = datetime.fromisoformat(result[0]['first_reading'])
                days_of_data = (datetime.now() - first_reading).days

            logger.info(f"Forgotten Light data check: {sessions_count} device sessions, {total_events} total events, {days_of_data} days")

            # Training möglich? Brauchen mindestens 50 Sessions und 100 Events
            return (sessions_count >= 5 and 
                   total_events >= self.MIN_FORGOTTEN_LIGHT_SAMPLES and
                   days_of_data >= self.MIN_DAYS_DATA)

        except Exception as e:
            logger.error(f"Error checking forgotten light data: {e}")
            return False

    def _train_forgotten_light_model(self) -> bool:
        """
        Trainiert das Forgotten Light Model

        Returns:
            True bei Erfolg
        """
        try:
            self._update_progress(status='training', model='forgotten_light', progress=0, step='Initialisierung...')

            # Erstelle Modell
            self._update_progress(progress=10, step='Erstelle Forgotten Light Model...')
            model = ForgottenLightModel(model_type="gradient_boosting")

            # Lerne Raum-Muster
            self._update_progress(progress=20, step='Lerne Raum-Muster...')
            model.learn_room_patterns(self.db)

            # Bereite Trainingsdaten vor
            self._update_progress(progress=30, step='Bereite Trainingsdaten vor...')
            X, y = model.prepare_training_data(self.db)

            if len(X) < 30:
                logger.warning(f"Not enough training samples for Forgotten Light: {len(X)}")
                self._update_progress(status='error', error=f'Zu wenig Samples: {len(X)} (benötigt: 30)')
                return False

            # Trainiere Modell (WICHTIG: benannte Parameter verwenden!)
            self._update_progress(progress=50, step=f'Trainiere Modell mit {len(X)} Samples...')
            metrics = model.train(X=X, y=y)

            if not metrics.get('accuracy'):
                logger.warning("Forgotten Light Model training returned no accuracy metric")
                self._update_progress(status='error', error='Training fehlgeschlagen - keine Metriken')
                return False

            # === MODEL VERSIONING & QUALITY CHECK ===

            # 1. Backup des aktuellen Modells (falls vorhanden)
            self._update_progress(progress=70, step='Erstelle Backup des alten Modells...')
            self.version_manager.backup_current_model('forgotten_light_model')

            # 2. Vergleiche mit vorheriger Version
            self._update_progress(progress=75, step='Vergleiche mit vorheriger Version...')
            comparison = self.version_manager.compare_with_previous('forgotten_light_model', metrics)

            logger.info(f"Forgotten Light Model comparison: {comparison['recommendation']}")

            # 3. Speichere neues Modell
            self._update_progress(progress=80, step='Speichere trainiertes Modell...')
            models_dir = Path('models')
            models_dir.mkdir(exist_ok=True)
            model.save(str(models_dir / 'forgotten_light_model.pkl'))

            # 4. Registriere neue Version
            self._update_progress(progress=85, step='Registriere Model-Version...')
            version_notes = f"Accuracy: {metrics.get('accuracy', 0):.3f}, Precision: {metrics.get('precision', 0):.3f}, Samples: {len(X)}"
            if not comparison['improved']:
                version_notes += " [Performance-Warnung]"

            self.version_manager.register_model(
                model_name='forgotten_light_model',
                metrics=metrics,
                notes=version_notes
            )

            # 5. Speichere Metriken in DB
            self._update_progress(progress=90, step='Speichere Metriken...')
            self._save_training_metrics('forgotten_light', metrics)

            # 6. Cleanup alte Versionen
            self._update_progress(progress=95, step='Cleanup alte Versionen...')
            self.version_manager.cleanup_old_versions('forgotten_light_model', keep_last_n=5)

            logger.info(f"Forgotten Light Model trained with accuracy: {metrics.get('accuracy', 0):.2f}, precision: {metrics.get('precision', 0):.2f}")
            if not comparison['improved']:
                logger.warning(f"⚠️ New Forgotten Light model may be worse than previous version!")

            # 7. Status speichern
            status = self._load_status()
            status['forgotten_light_trained'] = True
            status['forgotten_light_last_trained'] = datetime.now().isoformat()
            self._save_status(status)

            self._update_progress(progress=100, step='Forgotten Light Model erfolgreich trainiert!')
            return True

        except Exception as e:
            logger.error(f"Error training forgotten light model: {e}")
            import traceback
            logger.error(traceback.format_exc())
            self._update_progress(status='error', error=str(e))
            return False

    def _load_status(self) -> Dict:
        """Lädt aktuellen Trainingsstatus"""
        if self.status_file.exists():
            try:
                with open(self.status_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Could not load training status: {e}")

        return {
            'lighting_trained': False,
            'lighting_last_trained': None,
            'temperature_trained': False,
            'temperature_last_trained': None,
            'forgotten_light_trained': False,
            'forgotten_light_last_trained': None
        }

    def _save_status(self, status: Dict):
        """Speichert Trainingsstatus"""
        try:
            self.status_file.parent.mkdir(exist_ok=True)
            with open(self.status_file, 'w') as f:
                json.dump(status, f, indent=2)
        except Exception as e:
            logger.error(f"Could not save training status: {e}")


    def _save_training_metrics(self, model_name: str, metrics: Dict, model_type: str = 'gradient_boosting'):
        """Speichert Trainingsmetriken in DB"""
        try:
            import json
            self.db.execute(
                "INSERT INTO training_history (timestamp, model_name, model_type, metrics, model_path) VALUES (?, ?, ?, ?, ?)",
                (
                    datetime.now().isoformat(),
                    model_name,
                    model_type,
                    json.dumps(metrics),
                    f"models/{model_name}_model.pkl"
                )
            )
            logger.info(f"Training metrics saved for {model_name}")
        except Exception as e:
            logger.warning(f"Could not save training metrics: {e}")

