"""
Background Task: Automatisches ML-Training
Trainiert Lighting und Temperature Modelle sobald genug Daten vorhanden sind
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
                    """SELECT timestamp, device_id, new_state, brightness, 
                              motion_detected, ambient_light, time_of_day
                       FROM lighting_events 
                       ORDER BY timestamp DESC LIMIT 10000"""
                )
                for row in result:
                    light_states.append({
                        'timestamp': row['timestamp'],
                        'device_id': row['device_id'],
                        'state': 1 if row['new_state'] == 'on' else 0,
                        'brightness': row.get('brightness'),
                        'motion_detected': row.get('motion_detected'),
                        'ambient_light': row.get('ambient_light'),
                        'time_of_day': row.get('time_of_day')
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
                        'state': 1 if row.get('state_after') else 0
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
            X, y = model.prepare_training_data(sensor_data, light_states)

            if len(X) < 50:
                logger.warning(f"Not enough training samples after preparation: {len(X)}")
                self._update_progress(status='error', error=f'Zu wenig Samples nach Vorbereitung: {len(X)}')
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
            model.save_model(str(models_dir / 'lighting_model.pkl'))

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
            
            # Versuche zuerst die neue Tabelle
            try:
                result = self.db.execute(
                    """SELECT timestamp, sensor_type, value, room_id, outdoor_temp, 
                              humidity, target_temp, heating_active
                       FROM continuous_measurements 
                       WHERE sensor_type = 'temperature'
                       ORDER BY timestamp DESC LIMIT 20000"""
                )
                for row in result:
                    sensor_data.append({
                        'timestamp': row['timestamp'],
                        'sensor_id': row.get('room_id', 'unknown') + '_temperature',
                        'room_id': row.get('room_id'),
                        'value': row['value'],
                        'outdoor_temp': row.get('outdoor_temp'),
                        'humidity': row.get('humidity'),
                        'target_temp': row.get('target_temp'),
                        'heating_active': row.get('heating_active')
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
            X, y = model.prepare_training_data(sensor_data)

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
            model.save_model(str(models_dir / 'temperature_model.pkl'))

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
            'temperature_last_trained': None
        }

    def _save_status(self, status: Dict):
        """Speichert Trainingsstatus"""
        try:
            self.status_file.parent.mkdir(exist_ok=True)
            with open(self.status_file, 'w') as f:
                json.dump(status, f, indent=2)
        except Exception as e:
            logger.error(f"Could not save training status: {e}")

    def _save_training_metrics(self, model_name: str, metrics: Dict):
        """Speichert Trainingsmetriken in DB"""
        try:
            self.db.execute(
                "INSERT INTO training_history (timestamp, model_name, accuracy, samples_used, training_time) VALUES (?, ?, ?, ?, ?)",
                (
                    datetime.now().isoformat(),
                    model_name,
                    metrics.get('accuracy', metrics.get('r2_score', 0)),
                    metrics.get('samples_used', 0),
                    metrics.get('training_time', 0)
                )
            )
            logger.info(f"Training metrics saved for {model_name}")
        except Exception as e:
            logger.warning(f"Could not save training metrics: {e}")
