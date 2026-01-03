"""
Background Task: Kontinuierliche Badezimmer-Datensammlung
- Sammelt alle 60 Sekunden Temperatur und Luftfeuchtigkeit
- Unabhängig von Dusch-Events
- Ermöglicht detaillierte Langzeit-Analyse
"""

import threading
import time
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional
from loguru import logger
from src.utils.database import Database
from src.decision_engine.bathroom_automation import BathroomAutomation


class BathroomDataCollector:
    """
    Background-Prozess für kontinuierliche Badezimmer-Datensammlung

    - Sammelt alle 60 Sekunden Temperatur & Luftfeuchtigkeit
    - Speichert in separater Tabelle für Langzeit-Analyse
    - Läuft unabhängig von Event-Erkennung
    """

    def __init__(self, engine=None, interval_seconds: int = 60):
        """
        Args:
            engine: DecisionEngine Instanz (optional)
            interval_seconds: Intervall für Datensammlung in Sekunden (default: 60)
        """
        self.engine = engine
        self.interval_seconds = interval_seconds
        self.running = False
        self.thread = None
        self.last_collection = None
        self._last_config_load = None
        self.db = Database()
        self.config = None
        self.automation: Optional[BathroomAutomation] = None
        self._config_hash = None

        # Lade Badezimmer-Konfiguration
        self._load_config()

    def _load_config(self):
        """Lädt die Badezimmer-Konfiguration aus zentraler Sensor-Zuordnung"""
        try:
            from src.utils.sensor_helper import get_bathroom_config
            
            self.config = get_bathroom_config()
            
            if self.config:
                config_hash = hash(json.dumps(self.config, sort_keys=True))
                if config_hash != self._config_hash:
                    self._config_hash = config_hash
                    self._initialize_automation()

                logger.debug("Bathroom config loaded from central mapping for data collector")
            else:
                logger.warning("No bathroom config found - data collector will wait for configuration")

            self._last_config_load = datetime.now()
        except Exception as e:
            logger.error(f"Error loading bathroom config: {e}")

    def _initialize_automation(self):
        """Erstellt oder deaktiviert die Badezimmer-Automationsinstanz basierend auf der Config"""
        if not self.config or not self.config.get('enabled', False):
            if self.automation:
                logger.info("Bathroom automation disabled via config - stopping automation controller")
            self.automation = None
            return

        try:
            self.automation = BathroomAutomation(self.config, enable_learning=True)
            logger.info("Bathroom automation instance initialized for data collector")
        except Exception as e:
            logger.error(f"Failed to initialize bathroom automation: {e}")
            self.automation = None

    def start(self):
        """Startet den Background-Prozess"""
        if self.running:
            logger.warning("BathroomDataCollector is already running")
            return

        self.running = True
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()
        logger.info(f"BathroomDataCollector started (collects every {self.interval_seconds}s)")

    def stop(self):
        """Stoppt den Background-Prozess"""
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
        logger.info("BathroomDataCollector stopped")

    def _run_loop(self):
        """Haupt-Loop des Background-Prozesses"""
        while self.running:
            try:
                # Reload config alle 5 Minuten (falls geändert)
                if self._should_reload_config():
                    self._load_config()

                # Datensammlung
                if self._should_collect_now():
                    self._collect_data()
                    self.last_collection = datetime.now()

                # Warte interval_seconds Sekunden
                time.sleep(self.interval_seconds)

            except Exception as e:
                logger.error(f"Error in BathroomDataCollector loop: {e}")
                time.sleep(self.interval_seconds)

    def _should_collect_now(self) -> bool:
        """Prüft ob jetzt Daten gesammelt werden sollen"""
        if not self.last_collection:
            return True

        seconds_since_last = (datetime.now() - self.last_collection).seconds
        return seconds_since_last >= self.interval_seconds

    def _should_reload_config(self) -> bool:
        """Prüft ob Config neu geladen werden soll (alle 5 Minuten)"""
        if not self._last_config_load:
            return False

        minutes_since_last = (datetime.now() - self._last_config_load).seconds / 60
        return minutes_since_last >= 5

    def _collect_data(self):
        """Sammelt aktuelle Badezimmer-Daten"""
        try:
            # Prüfe ob Konfiguration vorhanden
            if not self.config:
                logger.debug("No bathroom config - skipping data collection")
                return

            if not self.engine or not self.engine.platform:
                logger.debug("No engine/platform available for data collection")
                return

            # Hole Sensor-Werte
            humidity_sensor_id = self.config.get('humidity_sensor_id')
            temp_sensor_id = self.config.get('temperature_sensor_id')

            if not humidity_sensor_id and not temp_sensor_id:
                logger.debug("No sensors configured - skipping data collection")
                return

            humidity = None
            temperature = None

            # Luftfeuchtigkeit
            if humidity_sensor_id:
                state = self.engine.platform.get_state(humidity_sensor_id)
                if state:
                    humidity = self.engine._extract_humidity_value(state)

            # Temperatur
            if temp_sensor_id:
                state = self.engine.platform.get_state(temp_sensor_id)
                if state:
                    temperature = self.engine._extract_temperature_value(state)

            # === DUSCHSENSOR-DATEN (falls konfiguriert) ===
            shower_humidity = None
            shower_temperature = None
            
            shower_humidity_sensor = self.config.get('shower_humidity_sensor')
            shower_temp_sensor = self.config.get('shower_temperature_sensor')
            
            if shower_humidity_sensor:
                try:
                    if shower_humidity_sensor.startswith('sensor.'):
                        # Home Assistant Sensor
                        platform = self.engine.platforms.get('homeassistant') if hasattr(self.engine, 'platforms') else self.engine.platform
                        if platform:
                            state = platform.get_state(shower_humidity_sensor)
                            if state:
                                value = state.get('state')
                                if value and value not in ['unknown', 'unavailable']:
                                    shower_humidity = float(value)
                                    logger.debug(f"Read shower humidity from HA: {shower_humidity}%")
                    else:
                        # Homey Sensor
                        state = self.engine.platform.get_state(shower_humidity_sensor)
                        if state:
                            shower_humidity = self.engine._extract_humidity_value(state)
                            logger.debug(f"Read shower humidity from Homey: {shower_humidity}%")
                except Exception as e:
                    logger.debug(f"Error reading shower humidity sensor: {e}")
            
            if shower_temp_sensor:
                try:
                    if shower_temp_sensor.startswith('sensor.'):
                        # Home Assistant Sensor
                        platform = self.engine.platforms.get('homeassistant') if hasattr(self.engine, 'platforms') else self.engine.platform
                        if platform:
                            state = platform.get_state(shower_temp_sensor)
                            if state:
                                value = state.get('state')
                                if value and value not in ['unknown', 'unavailable']:
                                    shower_temperature = float(value)
                                    logger.debug(f"Read shower temperature from HA: {shower_temperature}°C")
                    else:
                        # Homey Sensor
                        state = self.engine.platform.get_state(shower_temp_sensor)
                        if state:
                            shower_temperature = self.engine._extract_temperature_value(state)
                            logger.debug(f"Read shower temperature from Homey: {shower_temperature}°C")
                except Exception as e:
                    logger.debug(f"Error reading shower temperature sensor: {e}")

            # Speichere nur wenn mindestens ein Wert vorhanden
            if humidity is not None or temperature is not None:
                self.db.add_bathroom_continuous_measurement(
                    humidity=humidity,
                    temperature=temperature,
                    shower_humidity=shower_humidity,
                    shower_temperature=shower_temperature
                )
                logger.debug(f"Collected bathroom data: Humidity={humidity}%, Temp={temperature}°C, Shower: {shower_humidity}%/{shower_temperature}°C")

                # Führe direkt die Badezimmer-Automation aus, sobald valide Daten vorliegen
                if self.config.get('enabled', False):
                    logger.debug(f"Running automation with humidity={humidity}%, temp={temperature}°C")
                    self._run_automation(
                        humidity=humidity,
                        temperature=temperature
                    )
                else:
                    logger.debug("Bathroom automation disabled in config")
            else:
                logger.debug("No sensor values available")

        except Exception as e:
            logger.error(f"Error collecting bathroom data: {e}")

    def _run_automation(self, humidity: Optional[float], temperature: Optional[float]):
        """Startet die Badezimmer-Automationslogik und führt resultierende Aktionen aus"""
        if not self.automation:
            logger.warning("Bathroom automation not initialized - skipping automation run")
            return

        if not self.engine or not self.engine.platform:
            logger.warning("No platform available for bathroom automation")
            return

        try:
            current_state: Dict = {
                'timestamp': datetime.now().isoformat(),
                'humidity': humidity,
                'temperature': temperature
            }

            logger.debug(f"Running bathroom automation: humidity={humidity}%, temperature={temperature}°C")
            
            actions = self.automation.process(self.engine.platform, current_state)

            if not actions:
                logger.debug("No bathroom automation actions needed")
                return

            logger.info(f"Bathroom automation generated {len(actions)} action(s)")
            
            executed = 0
            for action in actions:
                if self._execute_action(action):
                    executed += 1

            logger.info(f"Bathroom automation executed {executed}/{len(actions)} action(s)")

        except Exception as e:
            logger.error(f"Error running bathroom automation: {e}")

    def _execute_action(self, action: Dict) -> bool:
        """Führt eine einzelne Automation-Aktion physisch aus"""
        if not self.engine or not self.engine.platform:
            return False

        platform = self.engine.platform
        device_id = action.get('device_id')
        action_type = action.get('action')

        if not device_id or not action_type:
            logger.warning(f"Invalid bathroom action payload: {action}")
            return False

        try:
            if action_type == 'turn_on':
                success = platform.turn_on(device_id)
            elif action_type == 'turn_off':
                success = platform.turn_off(device_id)
            elif action_type == 'set_temperature':
                temperature = action.get('temperature')
                if temperature is None:
                    logger.warning(f"Missing temperature for set_temperature action on {device_id}")
                    return False
                success = platform.set_temperature(device_id, temperature)
            else:
                logger.warning(f"Unsupported bathroom action type: {action_type}")
                return False

            if success:
                logger.info(f"Bathroom automation: {action_type} executed on {device_id}")
            else:
                logger.error(f"Bathroom automation failed: {action_type} on {device_id}")

            return success
        except Exception as e:
            logger.error(f"Error executing bathroom action {action_type} on {device_id}: {e}")
            return False

    def get_status(self) -> dict:
        """Gibt den aktuellen Status zurück"""
        return {
            'running': self.running,
            'last_collection': self.last_collection.isoformat() if self.last_collection else None,
            'interval_seconds': self.interval_seconds,
            'config_loaded': self.config is not None,
            'humidity_sensor': self.config.get('humidity_sensor_id') if self.config else None,
            'temperature_sensor': self.config.get('temperature_sensor_id') if self.config else None,
            'automation_active': bool(self.automation) if self.config else False
        }
