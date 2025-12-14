"""
Sensor Helper - Zentraler Zugriff auf Sensordaten

Bietet einfache Methoden zum Abfragen von:
- Motion-Sensoren (Bewegungserkennung)
- Window/Door-Sensoren (Fenster/Tür offen/geschlossen)
- Energiepreis-Daten
- Außenhelligkeit
"""

from typing import Optional, List, Dict
from loguru import logger
from datetime import datetime
import math


class SensorHelper:
    """Helper-Klasse für Sensor-Zugriffe"""

    def __init__(self, engine=None):
        """
        Args:
            engine: DecisionEngine Instanz für Zugriff auf Platform, Config, DB
        """
        self.engine = engine
        self.platform = engine.platform if engine else None
        self.config = engine.config if engine else None
        self.db = engine.db if engine else None

    def get_motion_detected(self, room_name: Optional[str] = None) -> bool:
        """
        Prüft ob Bewegung erkannt wurde

        Args:
            room_name: Optional - spezifischer Raum, sonst alle Motion-Sensoren

        Returns:
            True wenn Bewegung erkannt, sonst False
        """
        if not self.platform or not self.config:
            return False

        try:
            # Hole Motion-Sensoren aus Config
            motion_sensors = self.config.get('data_collection.sensors.motion', [])

            if not motion_sensors:
                logger.debug("No motion sensors configured")
                return False

            # Filter nach Raum-Name falls angegeben
            if room_name:
                motion_sensors = [
                    s for s in motion_sensors
                    if room_name.lower() in s.lower()
                ]

            # Prüfe jeden Motion-Sensor
            for sensor_id in motion_sensors:
                state = self.platform.get_state(sensor_id)
                if state:
                    sensor_state = str(state.get('state', '')).lower()

                    # Motion-Sensor kann verschiedene States haben
                    if sensor_state in ['on', 'detected', 'true', '1', 'motion']:
                        logger.debug(f"Motion detected: {sensor_id}")
                        return True

            return False

        except Exception as e:
            logger.warning(f"Error checking motion sensors: {e}")
            return False

    def get_window_open(self, room_name: Optional[str] = None) -> bool:
        """
        Prüft ob Fenster/Tür offen sind

        Args:
            room_name: Optional - spezifischer Raum, sonst alle Window-Sensoren

        Returns:
            True wenn ein Fenster/Tür offen ist, sonst False
        """
        if not self.platform or not self.config:
            return False

        try:
            # Hole Window/Door-Sensoren aus Config
            window_sensors = self.config.get('data_collection.sensors.window', [])
            door_sensors = self.config.get('data_collection.sensors.door', [])
            all_sensors = window_sensors + door_sensors

            if not all_sensors:
                logger.debug("No window/door sensors configured")
                return False

            # Filter nach Raum-Name falls angegeben
            if room_name:
                all_sensors = [
                    s for s in all_sensors
                    if room_name.lower() in s.lower()
                ]

            # Prüfe jeden Sensor
            for sensor_id in all_sensors:
                state = self.platform.get_state(sensor_id)
                if state:
                    sensor_state = str(state.get('state', '')).lower()

                    # Window/Door offen
                    if sensor_state in ['on', 'open', 'true', '1']:
                        logger.debug(f"Window/Door open: {sensor_id}")
                        return True

            return False

        except Exception as e:
            logger.warning(f"Error checking window/door sensors: {e}")
            return False

    def get_energy_price_level(self) -> int:
        """
        Holt das aktuelle Energiepreis-Level

        Returns:
            1 = günstig, 2 = mittel, 3 = teuer
        """
        if not self.db:
            return 2  # Default: mittel

        try:
            # Versuche aktuelle Energiepreise aus DB zu holen
            energy_data = self.db.get_latest_external_data('energy_price')

            if energy_data and 'data' in energy_data:
                data = energy_data.get('data', {})

                # Wenn direktes Level vorhanden
                if 'level' in data:
                    level = int(data['level'])
                    return max(1, min(3, level))  # Clamp to 1-3

                # Wenn Preis in EUR/kWh vorhanden, berechne Level
                if 'price' in data:
                    price = float(data['price'])

                    # Beispiel-Schwellwerte (können angepasst werden)
                    if price < 0.25:
                        return 1  # Günstig
                    elif price < 0.35:
                        return 2  # Mittel
                    else:
                        return 3  # Teuer

            # Fallback: Zeit-basierte Schätzung
            # (meist günstiger nachts, teurer abends)
            hour = datetime.now().hour
            if 0 <= hour < 6:  # Nachts
                return 1
            elif 17 <= hour < 21:  # Abends (Peak)
                return 3
            else:
                return 2

        except Exception as e:
            logger.warning(f"Error getting energy price level: {e}")
            return 2  # Default

    def get_outdoor_brightness(self) -> float:
        """
        Holt die Außenhelligkeit (Lux)

        Returns:
            Helligkeit in Lux (0-100000)
        """
        if not self.platform or not self.config:
            return self._estimate_brightness_from_time()

        try:
            # Versuche echten Outdoor-Brightness-Sensor
            light_sensors = self.config.get('data_collection.sensors.light', [])

            for sensor_id in light_sensors:
                # Suche nach Outdoor/Outside Sensoren
                if 'outdoor' in sensor_id.lower() or 'outside' in sensor_id.lower():
                    state = self.platform.get_state(sensor_id)
                    if state and 'state' in state:
                        try:
                            return float(state['state'])
                        except (ValueError, TypeError):
                            pass

            # Fallback: Von Wetterstation oder aus DB
            if self.db:
                weather_data = self.db.get_latest_external_data('weather')
                if weather_data and 'data' in weather_data:
                    data = weather_data['data']

                    # UV-Index oder Cloud-Cover kann als Proxy dienen
                    if 'clouds' in data:
                        clouds = float(data['clouds'])  # 0-100%
                        # Weniger Wolken = mehr Helligkeit
                        base_brightness = self._estimate_brightness_from_time()
                        return base_brightness * (1 - clouds / 200)  # Reduziere bei Wolken

            # Fallback: Schätzung basierend auf Tageszeit
            return self._estimate_brightness_from_time()

        except Exception as e:
            logger.warning(f"Error getting outdoor brightness: {e}")
            return self._estimate_brightness_from_time()

    def _estimate_brightness_from_time(self) -> float:
        """
        Schätzt Helligkeit basierend auf Tageszeit und Sonnenstand

        Returns:
            Geschätzte Helligkeit in Lux (grob)
        """
        now = datetime.now()
        hour = now.hour
        minute = now.minute
        time_decimal = hour + minute / 60.0

        # Sonnenaufgang ca. 6:00, Sonnenuntergang ca. 20:00 (grobe Schätzung)
        sunrise = 6.0
        sunset = 20.0
        noon = 13.0

        if time_decimal < sunrise or time_decimal > sunset:
            # Nacht: sehr dunkel
            return 10.0  # ~10 Lux (Mondlicht)

        elif sunrise <= time_decimal <= noon:
            # Morgens: ansteigend
            progress = (time_decimal - sunrise) / (noon - sunrise)
            # Sinus-Kurve für natürlicheren Verlauf
            return 10 + (50000 - 10) * math.sin(progress * math.pi / 2)

        else:  # noon < time_decimal <= sunset
            # Nachmittags/Abends: absteigend
            progress = (time_decimal - noon) / (sunset - noon)
            return 10 + (50000 - 10) * math.cos(progress * math.pi / 2)

    def get_presence_in_room(self, room_name: str) -> bool:
        """
        Detektiert Anwesenheit in einem spezifischen Raum

        Nutzt Motion-Sensoren oder dedizierte Presence-Sensoren

        Args:
            room_name: Name des Raums

        Returns:
            True wenn Anwesenheit erkannt
        """
        if not self.platform or not self.config:
            return False

        try:
            # 1. Prüfe Motion-Sensoren für den Raum
            if self.get_motion_detected(room_name):
                return True

            # 2. Prüfe dedizierte Presence-Sensoren
            presence_sensors = self.config.get('data_collection.sensors.presence', [])
            room_sensors = [
                s for s in presence_sensors
                if room_name.lower() in s.lower()
            ]

            for sensor_id in room_sensors:
                state = self.platform.get_state(sensor_id)
                if state:
                    sensor_state = str(state.get('state', '')).lower()
                    if sensor_state in ['on', 'home', 'present', 'true', '1']:
                        return True

            return False

        except Exception as e:
            logger.warning(f"Error detecting presence in {room_name}: {e}")
            return False

    def get_humidity(self, room_name: Optional[str] = None) -> Optional[float]:
        """
        Holt Luftfeuchtigkeit

        Args:
            room_name: Optional - spezifischer Raum

        Returns:
            Luftfeuchtigkeit in % oder None
        """
        if not self.platform or not self.config:
            return None

        try:
            # Suche nach Humidity-Sensoren
            humidity_sensors = self.config.get('data_collection.sensors.humidity', [])

            if room_name:
                # Filter nach Raum
                humidity_sensors = [
                    s for s in humidity_sensors
                    if room_name.lower() in s.lower()
                ]

            for sensor_id in humidity_sensors:
                state = self.platform.get_state(sensor_id)
                if state and 'state' in state:
                    try:
                        return float(state['state'])
                    except (ValueError, TypeError):
                        pass

            return None

        except Exception as e:
            logger.warning(f"Error getting humidity: {e}")
            return None


def get_bathroom_config() -> dict:
    """
    Lädt die Badezimmer-Konfiguration aus der zentralen Sensor-Zuordnung.
    Kombiniert Sensor-IDs aus ventilation_sensor_mapping.json mit
    Einstellungen aus luftentfeuchten_config.json.
    
    Returns:
        dict mit Sensor-IDs und Einstellungen: humidity_sensor_id, temperature_sensor_id, 
        dehumidifier_id, heater_id, door_sensor_id, motion_sensor_id, window_sensor_id,
        enabled, humidity_threshold_high, humidity_threshold_low, etc.
    """
    import json
    from pathlib import Path
    
    config = {}
    
    # 1. Lade Einstellungen aus alter Config (enabled, thresholds, etc.)
    old_config_file = Path('data/luftentfeuchten_config.json')
    if old_config_file.exists():
        try:
            with open(old_config_file, 'r') as f:
                config = json.load(f)
            logger.debug(f"Bathroom settings loaded from legacy file: {len(config)} settings")
        except Exception as e:
            logger.warning(f"Error loading legacy bathroom config: {e}")
    
    # 2. Überschreibe/ergänze Sensor-IDs aus zentraler Konfiguration
    mapping_file = Path('data/ventilation_sensor_mapping.json')
    if mapping_file.exists():
        try:
            with open(mapping_file, 'r') as f:
                mapping_data = json.load(f)
            
            # Suche Badezimmer-Konfiguration
            rooms = mapping_data.get('rooms', {})
            bathroom_config = rooms.get('badezimmer', {})
            
            if bathroom_config:
                # Überschreibe Sensor-IDs mit zentralen Werten (falls vorhanden)
                sensor_mapping = {
                    'humidity_sensor_id': bathroom_config.get('humidity'),
                    'temperature_sensor_id': bathroom_config.get('temperature'),
                    'dehumidifier_id': bathroom_config.get('dehumidifier'),
                    'heater_id': bathroom_config.get('heater'),
                    'door_sensor_id': bathroom_config.get('door_sensor'),
                    'motion_sensor_id': bathroom_config.get('motion_sensor'),
                    'window_sensor_id': bathroom_config.get('window_sensor'),
                }
                
                # Nur nicht-leere Werte übernehmen
                for key, value in sensor_mapping.items():
                    if value:
                        config[key] = value
                
                # Auch humidity_threshold_high/low aus zentraler Config übernehmen falls vorhanden
                if bathroom_config.get('humidity_threshold_high'):
                    config['humidity_threshold_high'] = bathroom_config['humidity_threshold_high']
                if bathroom_config.get('humidity_threshold_low'):
                    config['humidity_threshold_low'] = bathroom_config['humidity_threshold_low']
                
                logger.debug(f"Bathroom config merged with central mapping")
        except Exception as e:
            logger.warning(f"Error loading central bathroom config: {e}")
    
    if not config:
        logger.warning("No bathroom configuration found")
    
    return config
