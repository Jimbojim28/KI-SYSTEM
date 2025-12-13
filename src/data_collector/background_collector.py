"""
Background Service für kontinuierliche Datensammlung

Sammelt verschiedene Sensortypen mit unterschiedlichen Strategien:

IMMER SPEICHERN (alle 5 Min):
- Temperatur (measure_temperature)
- Luftfeuchtigkeit (measure_humidity)
- Zieltemperatur (target_temperature)

NUR BEI ÄNDERUNG SPEICHERN:
- Bewegung (alarm_motion) - bei Status-Wechsel
- Lichter (onoff) - bei an/aus Wechsel
- Helligkeit (measure_luminance) - bei Änderung > 10 Lux
"""

import time
import threading
from datetime import datetime
from typing import Optional
from loguru import logger

from ..utils.database import Database
from .base_collector import SmartHomeCollector


class BackgroundDataCollector:
    """
    Sammelt kontinuierlich Daten von der Smart Home Platform
    und speichert sie in der Datenbank für ML-Training
    """

    def __init__(self, platform: SmartHomeCollector, database: Database,
                 interval_seconds: int = 300):
        """
        Args:
            platform: Smart Home Platform Collector
            database: Database Instanz
            interval_seconds: Sammel-Intervall in Sekunden (default: 5 Minuten)
        """
        self.platform = platform
        self.db = database
        self.interval = interval_seconds
        self.running = False
        self.thread: Optional[threading.Thread] = None

        # State tracking für Change Detection
        self.last_states = {}  # device_id -> {sensor_type -> value}

        logger.info(f"Background Collector initialized (interval: {interval_seconds}s)")

    def _has_changed(self, device_id: str, sensor_type: str, value: float, threshold: float = 0.01) -> bool:
        """
        Prüft ob sich ein Sensorwert geändert hat

        Args:
            device_id: Device ID
            sensor_type: Typ des Sensors
            value: Neuer Wert
            threshold: Schwellwert für signifikante Änderung

        Returns:
            True wenn Wert sich geändert hat oder neu ist
        """
        if device_id not in self.last_states:
            self.last_states[device_id] = {}

        last_value = self.last_states[device_id].get(sensor_type)

        # Erster Wert für diesen Sensor
        if last_value is None:
            self.last_states[device_id][sensor_type] = value
            return True

        # Prüfe auf signifikante Änderung
        changed = abs(value - last_value) >= threshold

        if changed:
            self.last_states[device_id][sensor_type] = value

        return changed

    def _collect_sensor_data(self):
        """Sammelt alle Sensor-Daten und speichert sie"""
        try:
            timestamp = datetime.now()

            # Hole alle Devices
            all_devices = self.platform.get_states()

            if not all_devices:
                logger.warning("No devices found")
                return

            collected_count = 0

            for device_id, state in all_devices.items():
                # Extrahiere relevante Daten
                attributes = state.get('attributes', {})
                capabilities = attributes.get('capabilities', {})

                # Speichere verschiedene Sensor-Typen

                # Temperatur
                if 'measure_temperature' in capabilities:
                    temp_value = capabilities['measure_temperature'].get('value')
                    if temp_value is not None:
                        self.db.insert_sensor_data(
                            timestamp=timestamp,
                            sensor_id=device_id,
                            sensor_type='temperature',
                            value=float(temp_value),
                            unit='°C',
                            metadata={'zone': attributes.get('zone'), 'name': attributes.get('friendly_name')}
                        )
                        collected_count += 1

                # Luftfeuchtigkeit
                if 'measure_humidity' in capabilities:
                    humid_value = capabilities['measure_humidity'].get('value')
                    if humid_value is not None:
                        self.db.insert_sensor_data(
                            timestamp=timestamp,
                            sensor_id=device_id,
                            sensor_type='humidity',
                            value=float(humid_value),
                            unit='%',
                            metadata={'zone': attributes.get('zone'), 'name': attributes.get('friendly_name')}
                        )
                        collected_count += 1

                # Helligkeit (nur bei signifikanter Änderung > 10 Lux)
                if 'measure_luminance' in capabilities:
                    lux_value = capabilities['measure_luminance'].get('value')
                    if lux_value is not None and self._has_changed(device_id, 'brightness', float(lux_value), threshold=10.0):
                        self.db.insert_sensor_data(
                            timestamp=timestamp,
                            sensor_id=device_id,
                            sensor_type='brightness',
                            value=float(lux_value),
                            unit='lux',
                            metadata={'zone': attributes.get('zone'), 'name': attributes.get('friendly_name')}
                        )
                        collected_count += 1

                # Bewegung (Binary Sensor - nur bei Änderung)
                # Unterstützt alarm_motion UND alarm_presence (Anwesenheitssensoren)
                motion_value = None
                if 'alarm_motion' in capabilities:
                    motion_value = capabilities['alarm_motion'].get('value')
                elif 'alarm_presence' in capabilities:
                    motion_value = capabilities['alarm_presence'].get('value')
                
                if motion_value is not None:
                    motion_float = 1.0 if motion_value else 0.0
                    if self._has_changed(device_id, 'motion', motion_float, threshold=0.1):
                        self.db.insert_sensor_data(
                            timestamp=timestamp,
                            sensor_id=device_id,
                            sensor_type='motion',
                            value=motion_float,
                            unit='binary',
                            metadata={'zone': attributes.get('zone'), 'name': attributes.get('friendly_name')}
                        )
                        collected_count += 1

                # Lichter (für ML-Training - nur bei Änderung)
                if 'onoff' in capabilities:
                    device_class = attributes.get('device_class', '').lower()
                    if device_class == 'light' or 'light' in device_id.lower():
                        light_state = capabilities['onoff'].get('value')
                        brightness = None

                        # Helligkeit wenn verfügbar
                        if 'dim' in capabilities:
                            brightness = capabilities['dim'].get('value', 0) * 255  # Homey: 0-1, Standard: 0-255

                        light_float = 1.0 if light_state else 0.0

                        # Speichere nur bei Änderung (on/off Wechsel)
                        if self._has_changed(device_id, 'light_state', light_float, threshold=0.1):
                            self.db.insert_sensor_data(
                                timestamp=timestamp,
                                sensor_id=device_id,
                                sensor_type='light_state',
                                value=light_float,
                                unit='binary',
                                metadata={
                                    'zone': attributes.get('zone'),
                                    'name': attributes.get('friendly_name'),
                                    'brightness': brightness
                                }
                            )
                            collected_count += 1

                # Heizung (für ML-Training)
                if 'target_temperature' in capabilities:
                    target_temp = capabilities['target_temperature'].get('value')
                    if target_temp is not None:
                        self.db.insert_sensor_data(
                            timestamp=timestamp,
                            sensor_id=device_id,
                            sensor_type='target_temperature',
                            value=float(target_temp),
                            unit='°C',
                            metadata={'zone': attributes.get('zone'), 'name': attributes.get('friendly_name')}
                        )
                        collected_count += 1

            logger.info(f"Collected {collected_count} sensor readings from {len(all_devices)} devices")

        except Exception as e:
            logger.error(f"Error collecting sensor data: {e}")

    def _collect_external_data(self):
        """Sammelt externe Daten (Wetter, Energie-Preise)"""
        try:
            timestamp = datetime.now()

            # Wetterdaten (falls verfügbar)
            if hasattr(self.platform, 'get_weather_data'):
                try:
                    weather = self.platform.get_weather_data()
                    if weather:
                        self.db.insert_external_data(
                            timestamp=timestamp,
                            data_type='weather',
                            data=weather
                        )
                        logger.debug("Weather data collected")
                except Exception as e:
                    logger.warning(f"Could not collect weather data: {e}")

            # Präsenz-Daten
            if hasattr(self.platform, 'get_presence_status'):
                try:
                    presence = self.platform.get_presence_status()
                    if presence:
                        self.db.insert_external_data(
                            timestamp=timestamp,
                            data_type='presence',
                            data=presence
                        )
                        logger.debug("Presence data collected")
                except Exception as e:
                    logger.warning(f"Could not collect presence data: {e}")

        except Exception as e:
            logger.error(f"Error collecting external data: {e}")

    def _run_loop(self):
        """Main collection loop"""
        logger.info("Background data collection started")

        while self.running:
            try:
                # Sammle Daten
                self._collect_sensor_data()
                self._collect_external_data()

                # Warte bis zum nächsten Intervall
                time.sleep(self.interval)

            except Exception as e:
                logger.error(f"Error in collection loop: {e}")
                time.sleep(60)  # Bei Fehler: 1 Minute warten

        logger.info("Background data collection stopped")

    def start(self):
        """Startet die Datensammlung im Hintergrund"""
        if self.running:
            logger.warning("Background collector already running")
            return

        self.running = True
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()

        logger.info("Background data collector started")

    def stop(self):
        """Stoppt die Datensammlung"""
        if not self.running:
            return

        self.running = False

        if self.thread:
            self.thread.join(timeout=10)

        logger.info("Background data collector stopped")

    def get_stats(self) -> dict:
        """Gibt Statistiken über gesammelte Daten zurück"""
        try:
            # Zähle Datensätze
            total_sensors = self.db.get_sensor_data_count()
            total_external = self.db.get_external_data_count()

            # Letzte Sammlung
            last_collection = self.db.get_latest_sensor_timestamp()

            return {
                'running': self.running,
                'interval': self.interval,
                'total_sensor_readings': total_sensors,
                'total_external_data': total_external,
                'last_collection': last_collection.isoformat() if last_collection else None
            }
        except Exception as e:
            logger.error(f"Error getting stats: {e}")
            return {
                'running': self.running,
                'error': str(e)
            }
