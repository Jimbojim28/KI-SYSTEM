"""
Heating Data Collector - Kontinuierliche Heizungsdaten-Sammlung

Sammelt jede Minute Daten von allen Heizgeräten für Analytics:
- Aktuelle/Zieltemperatur
- Heizstatus
- Außentemperatur
- Luftfeuchtigkeit
"""

import threading
import time
from datetime import datetime
from typing import Optional
from loguru import logger
from src.utils.database import Database
from src.utils.sensor_helper import SensorHelper


class HeatingDataCollector:
    """Sammelt kontinuierlich Heizungsdaten für Analytics"""

    def __init__(self, engine=None, interval_seconds: int = 60):  # 1 Minute = 60 Sekunden
        """
        Args:
            engine: DecisionEngine Instanz für Zugriff auf Platform
            interval_seconds: Sammel-Intervall in Sekunden (default: 60 = 1 Min)
        """
        self.engine = engine
        self.interval_seconds = interval_seconds
        self.running = False
        self.thread = None
        self.last_collection = None
        self.db = Database()
        self.sensor_helper = SensorHelper(engine) if engine else None

        logger.info(f"Heating Data Collector initialized ({interval_seconds}s interval)")

    def start(self):
        """Startet die kontinuierliche Datensammlung"""
        if self.running:
            logger.warning("Heating Data Collector is already running")
            return

        self.running = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        logger.info(f"Heating Data Collector started (collects every {self.interval_seconds}s)")

    def stop(self):
        """Stoppt die kontinuierliche Datensammlung"""
        if not self.running:
            return

        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
        logger.info("Heating Data Collector stopped")

    def _run(self):
        """Haupt-Loop für kontinuierliche Datensammlung"""
        while self.running:
            try:
                self._collect_data()
                self.last_collection = datetime.now()
            except Exception as e:
                logger.error(f"Error in heating data collection: {e}")

            # Warte bis zum nächsten Intervall
            time.sleep(self.interval_seconds)

    def _collect_data(self):
        """Sammelt aktuelle Heizungsdaten von allen Geräten"""
        if not self.engine or not self.engine.platform:
            logger.debug("No engine/platform available for heating data collection")
            return

        try:
            # Hole alle Heizgeräte
            all_states = self.engine.platform.get_states()
            heating_devices = []

            # Konvertiere Dictionary zu Liste (falls nötig)
            devices_list = list(all_states.values()) if isinstance(all_states, dict) else all_states

            # Filtere nach Thermostaten und Heizgeräten
            for device in devices_list:
                # Skip wenn device kein Dictionary ist
                if not isinstance(device, dict):
                    continue

                device_type = device.get('class', '').lower()
                domain = device.get('domain', '').lower()
                capabilities = device.get('capabilitiesObj', {})
                # Fallback: prüfe auch attributes.capabilities
                if not capabilities:
                    capabilities = device.get('attributes', {}).get('capabilities', {})

                # Prüfe ob es ein Thermostat oder Heizgerät ist
                # Nur Geräte MIT Zieltemperatur (controllable thermostats) oder explizitem Typ
                if ('thermostat' in device_type or
                    'heater' in device_type or
                    domain == 'climate' or  # Homey climate devices
                    'target_temperature' in capabilities):
                    heating_devices.append(device)

            if not heating_devices:
                logger.debug("No heating devices found for data collection")
                return

            # Hole Außentemperatur einmal für alle Geräte
            outdoor_temp = self._get_outdoor_temperature()

            # Sammle Daten von jedem Heizgerät
            collected_count = 0
            for device in heating_devices:
                try:
                    observation_id = self._collect_device_data(device, outdoor_temp)
                    if observation_id:
                        collected_count += 1
                except Exception as e:
                    logger.error(f"Error collecting data from device {device.get('id')}: {e}")

            logger.debug(f"Collected heating data from {collected_count}/{len(heating_devices)} devices")

        except Exception as e:
            logger.error(f"Error in heating data collection: {e}")

    def _collect_device_data(self, device: dict, outdoor_temp: Optional[float]) -> Optional[int]:
        """Sammelt Daten von einem einzelnen Heizgerät"""
        device_id = device.get('id') or device.get('entity_id')
        if not device_id:
            return None

        # Extrahiere Daten (unterstützt beide Formate)
        capabilities = device.get('capabilitiesObj', {})
        if not capabilities:
            capabilities = device.get('attributes', {}).get('capabilities', {})

        # Aktuelle Temperatur
        current_temp = None
        if 'measure_temperature' in capabilities:
            temp_cap = capabilities['measure_temperature']
            current_temp = temp_cap.get('value')

        # Zieltemperatur
        target_temp = None
        if 'target_temperature' in capabilities:
            target_cap = capabilities['target_temperature']
            target_temp = target_cap.get('value')

        # Heizstatus (ist das Gerät gerade am Heizen?)
        is_heating = False
        if 'onoff' in capabilities:
            is_heating = capabilities['onoff'].get('value', False)

        # Alternativ: prüfe ob target > current (typisch für Thermostate)
        if not is_heating and current_temp and target_temp:
            # Wenn Zieltemp > aktuelle Temp + 0.5°C => vermutlich am Heizen
            is_heating = target_temp > (current_temp + 0.5)

        # Luftfeuchtigkeit (optional)
        humidity = None
        if 'measure_humidity' in capabilities:
            humidity = capabilities['measure_humidity'].get('value')

        # Raum-Name aus Zone
        room_name = None
        zone_id = device.get('zone') or device.get('attributes', {}).get('zone')
        if zone_id and hasattr(self.engine, 'platform'):
            # Versuche Raum-Name zu holen
            try:
                zones = self.engine.platform.get_zones()
                # get_zones() gibt ein Dict zurück: {zone_id: zone_data, ...}
                if isinstance(zones, dict):
                    zone_data = zones.get(zone_id)
                    if zone_data:
                        room_name = zone_data.get('name')
                else:
                    # Fallback für Listen-Format
                    for zone in zones:
                        if isinstance(zone, dict) and zone.get('id') == zone_id:
                            room_name = zone.get('name')
                            break
            except (AttributeError, KeyError, TypeError) as e:
                logger.debug(f"Could not fetch zone name for zone_id {zone_id}: {e}")

        # Speichere in Datenbank (beide Tabellen für Analytics und ML)
        observation_id = self.db.add_heating_observation(
            device_id=device_id,
            room_name=room_name,
            current_temp=current_temp,
            target_temp=target_temp,
            is_heating=is_heating,
            outdoor_temp=outdoor_temp,
            humidity=humidity,
            power_percentage=None  # Könnte später von capable_dim oder measure_power kommen
        )

        # Zusätzlich: Speichere für ML-Training in continuous_measurements
        if current_temp is not None and target_temp is not None:
            device_name = device.get('name', 'Unknown')
            # Hole zusätzliche Sensor-Daten
            presence = self.sensor_helper.get_presence_in_room(room_name) if self.sensor_helper and room_name else False
            window_open = self.sensor_helper.get_window_open(room_name) if self.sensor_helper and room_name else False
            energy_level = self.sensor_helper.get_energy_price_level() if self.sensor_helper else 2

            self.db.add_continuous_measurement(
                device_id=device_id,
                device_name=device_name,
                room_name=room_name or 'Unknown',
                current_temp=current_temp,
                target_temp=target_temp,
                outdoor_temp=outdoor_temp or 20.0,  # Fallback
                humidity=humidity,
                heating_active=is_heating,
                presence=presence,
                window_open=window_open,
                energy_price_level=energy_level
            )
            logger.debug(f"Saved ML training data for {device_name}")

        return observation_id

    def _get_outdoor_temperature(self) -> Optional[float]:
        """Holt die aktuelle Außentemperatur"""
        try:
            # Versuche aus external_data (Weather-Collector)
            weather_data = self.db.get_latest_external_data('weather')
            if weather_data:
                data = weather_data.get('data', {})
                outdoor_temp = data.get('temperature') or data.get('temp')
                if outdoor_temp is not None:
                    return float(outdoor_temp)

            # Fallback: Suche nach Outdoor-Sensor in Geräten
            if self.engine and self.engine.platform:
                all_states = self.engine.platform.get_states()
                for device in all_states:
                    device_name = device.get('name', '').lower()
                    if 'outdoor' in device_name or 'außen' in device_name or 'outside' in device_name:
                        caps = device.get('capabilitiesObj', {})
                        if 'measure_temperature' in caps:
                            temp = caps['measure_temperature'].get('value')
                            if temp is not None:
                                return float(temp)

        except Exception as e:
            logger.debug(f"Could not get outdoor temperature: {e}")

        return None

    def get_status(self) -> dict:
        """Gibt den aktuellen Status des Collectors zurück"""
        return {
            'running': self.running,
            'interval_seconds': self.interval_seconds,
            'last_collection': self.last_collection.isoformat() if self.last_collection else None
        }
