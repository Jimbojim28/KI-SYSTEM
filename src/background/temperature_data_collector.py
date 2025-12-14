"""
Background Service: Sammelt Temperaturdaten für ML-Training
Läuft kontinuierlich und sammelt alle Thermostat-Daten
"""

import time
from datetime import datetime
from threading import Thread
from loguru import logger
from typing import Dict, Optional

from src.utils.database import Database
from src.utils.sensor_helper import SensorHelper


class TemperatureDataCollector:
    """
    Sammelt Temperaturdaten für das TemperatureModel
    
    Erfasst:
    - Aktuelle und Zieltemperaturen aller Thermostate
    - Heizstatus (aktiv/inaktiv)
    - Außentemperatur
    - Fensterstatus
    - Anwesenheit
    - Energiepreis-Level
    """
    
    def __init__(self, db: Database | None = None, config: dict | None = None, engine=None):
        self.db = db or Database()
        self.config = config or {}
        self.engine = engine
        self.interval = self.config.get('data_collection', {}).get('temperature_interval', 60)  # 1 Minute
        self.running = False
        self.thread = None
        self.sensor_helper = SensorHelper(engine) if engine else None
        self.last_collection_time = None
        self.last_collection_success = None
        self.last_error = None
        self.total_measurements_collected = 0
        
        # Platform-spezifische Collector basierend auf platform.type
        self.collectors = []
        platform_type = self.config.get('platform', {}).get('type', '').lower()

        try:
            if platform_type == 'homey':
                from src.data_collector.homey_collector import HomeyCollector
                homey_config = self.config.get('homey', {})
                homey = HomeyCollector(
                    url=homey_config.get('url', ''),
                    token=homey_config.get('token', '')
                )
                self.collectors.append(('homey', homey))
                logger.info("Homey collector initialized for temperature data")
            elif platform_type == 'homeassistant':
                from src.data_collector.ha_collector import HomeAssistantCollector
                ha_config = self.config.get('homeassistant', {})
                ha = HomeAssistantCollector(
                    url=ha_config.get('url', ''),
                    token=ha_config.get('token', '')
                )
                self.collectors.append(('homeassistant', ha))
                logger.info("Home Assistant collector initialized for temperature data")
            else:
                logger.warning(f"Unknown or missing platform type: {platform_type}")
        except Exception as e:
            error_msg = str(e).encode('ascii', 'ignore').decode('ascii')
            logger.error(f"Could not initialize platform collector for temperature data: {error_msg}")
    
    def start(self):
        """Startet Background-Collection"""
        if self.running:
            logger.warning("TemperatureDataCollector already running")
            return
        
        if not self.collectors:
            logger.warning("No collectors available for temperature data collection")
            return
        
        self.running = True
        self.thread = Thread(target=self._collection_loop, daemon=True)
        self.thread.start()
        logger.info(f"TemperatureDataCollector started (interval: {self.interval}s)")
    
    def stop(self):
        """Stoppt Background-Collection"""
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
        logger.info("TemperatureDataCollector stopped")
    
    def _collection_loop(self):
        """Hauptloop für Datensammlung"""
        while self.running:
            try:
                self.last_collection_time = datetime.now()
                self._collect_temperature_data()
                self.last_collection_success = True
                self.last_error = None
            except Exception as e:
                error_msg = str(e).encode('ascii', 'ignore').decode('ascii')
                logger.error(f"Error in temperature data collection: {error_msg}")
                self.last_collection_success = False
                self.last_error = str(e).encode('ascii', 'ignore').decode('ascii') or str(e)[:100]
            
            time.sleep(self.interval)
    
    def _collect_temperature_data(self):
        """Sammelt Daten von allen Thermostaten"""
        outdoor_temp = self._get_outdoor_temperature()
        energy_level = self._get_energy_price_level()
        
        for platform_name, collector in self.collectors:
            try:
                devices = collector.get_all_devices()
                
                for device in devices:
                    # Nur Thermostate
                    if not self._is_thermostat(device):
                        continue
                    
                    device_id = device.get('id')
                    device_name = device.get('name', 'Unknown')

                    # Handle zone - can be string (ID) or dict
                    zone = device.get('zone')
                    if isinstance(zone, dict):
                        room_name = zone.get('name', 'Unknown')
                    elif isinstance(zone, str):
                        room_name = zone  # Zone ID
                    else:
                        room_name = 'Unknown'
                    
                    # Temperaturen
                    caps = device.get('capabilitiesObj', {})
                    current_temp = caps.get('measure_temperature', {}).get('value')
                    target_temp = caps.get('target_temperature', {}).get('value')
                    
                    if current_temp is None or target_temp is None:
                        continue
                    
                    # Heizstatus
                    heating_active = self._is_heating(device)
                    
                    # Fensterstatus für diesen Raum
                    window_open = self._check_window_status(room_name, devices)
                    
                    # Anwesenheit
                    presence = self.sensor_helper.get_presence_in_room(room_name) if self.sensor_helper and room_name else False
                    
                    # Humidity (falls verfügbar)
                    humidity = caps.get('measure_humidity', {}).get('value')
                    
                    # In DB speichern
                    self.db.add_continuous_measurement(
                        device_id=device_id,
                        device_name=device_name,
                        room_name=room_name,
                        current_temp=current_temp,
                        target_temp=target_temp,
                        outdoor_temp=outdoor_temp,
                        humidity=humidity,
                        heating_active=heating_active,
                        presence=presence,
                        window_open=window_open,
                        energy_price_level=energy_level
                    )
                    self.total_measurements_collected += 1
                    
                    logger.debug(f"Temperature data: {device_name} - {current_temp}°C / {target_temp}°C (heating: {heating_active})")
                
                # CO2-Sensoren separat sammeln
                self._collect_co2_data(devices, platform_name)
                
                # PM2.5 Feinstaub-Sensoren sammeln
                self._collect_pm25_data(devices, platform_name)
                    
            except Exception as e:
                error_msg = str(e).encode('ascii', 'ignore').decode('ascii')
                logger.error(f"Error collecting from {platform_name}: {error_msg}")
    
    def _is_thermostat(self, device: Dict) -> bool:
        """Prüft ob Gerät ein Thermostat ist"""
        device_class = device.get('class', '').lower()
        capabilities = device.get('capabilities', [])
        
        # Homey: class=thermostat
        if 'thermostat' in device_class or 'heater' in device_class:
            return True
        
        # Capability-basiert
        if 'target_temperature' in capabilities and 'measure_temperature' in capabilities:
            return True
        
        return False
    
    def _is_heating(self, device: Dict) -> bool:
        """Detektiert ob Gerät gerade heizt"""
        caps = device.get('capabilitiesObj', {})
        
        # Direkte Heizstatus-Capability
        heating_status = caps.get('heating', {}).get('value')
        if heating_status is not None:
            return bool(heating_status)
        
        # Indirekt: Wenn target > current + threshold
        current = caps.get('measure_temperature', {}).get('value')
        target = caps.get('target_temperature', {}).get('value')
        
        if current is not None and target is not None:
            return target > (current + 0.5)  # 0.5°C Hysterese
        
        return False
    
    def _check_window_status(self, room_name: str, all_devices: list) -> bool:
        """Prüft ob Fenster in diesem Raum offen ist"""
        for device in all_devices:
            # Handle zone - can be string (ID) or dict
            zone = device.get('zone')
            if isinstance(zone, dict):
                device_room = zone.get('name', '')
            elif isinstance(zone, str):
                device_room = zone  # Zone ID
            else:
                device_room = ''

            if device_room != room_name:
                continue
            
            device_class = device.get('class', '').lower()
            if 'sensor' in device_class or 'contactsensor' in device_class:
                caps = device.get('capabilitiesObj', {})
                alarm_contact = caps.get('alarm_contact', {}).get('value')
                
                # Homey: alarm_contact=True bedeutet Fenster offen
                if alarm_contact is True:
                    return True
        
        return False
    
    def _get_outdoor_temperature(self) -> Optional[float]:
        """Holt Außentemperatur"""
        try:
            # Versuche von Wetterstation oder DB
            if self.sensor_helper and self.sensor_helper.db:
                weather_data = self.sensor_helper.db.get_latest_external_data('weather')
                if weather_data and 'data' in weather_data:
                    data = weather_data['data']
                    temp = data.get('temperature') or data.get('temp')
                    if temp is not None:
                        return float(temp)

            # Fallback: Weather Collector direkt
            from src.data_collector.weather_collector import WeatherCollector
            weather = WeatherCollector(config=self.config)
            data = weather.get_current_weather()
            return data.get('temperature')
        except Exception as e:
            logger.debug(f"Could not get outdoor temperature: {e}")
            return None
    
    def _get_energy_price_level(self) -> int:
        """Holt Energiepreis-Level (1=niedrig, 2=mittel, 3=hoch)"""
        try:
            if self.sensor_helper:
                return self.sensor_helper.get_energy_price_level()

            # Fallback: Default mittel
            return 2
        except Exception as e:
            logger.debug(f"Could not get energy price level: {e}")
            return 2
    
    def get_stats(self) -> Dict:
        """Gibt Statistiken zurück"""
        return {
            'running': self.running,
            'interval': self.interval,
            'collectors_count': len(self.collectors),
            'total_measurements': self.db.get_continuous_measurements_count(),
            'last_collection': self.last_collection_time.isoformat() if self.last_collection_time else None,
            'last_success': self.last_collection_success,
            'last_error': self.last_error,
            'measurements_this_session': self.total_measurements_collected
        }
    
    def _collect_co2_data(self, devices: list, platform_name: str):
        """Sammelt CO2-Daten von allen Geräten mit measure_co2 Capability"""
        collected_count = 0
        
        for device in devices:
            try:
                caps = device.get('capabilitiesObj', {})
                co2_cap = caps.get('measure_co2', {})
                co2_value = co2_cap.get('value')
                
                if co2_value is None:
                    continue
                
                device_id = device.get('id', '')
                device_name = device.get('name', 'Unknown')
                
                # Room aus zone holen
                zone = device.get('zone')
                if isinstance(zone, dict):
                    room_name = zone.get('name', 'Unknown')
                elif isinstance(zone, str):
                    room_name = zone
                else:
                    room_name = 'Unknown'
                
                # CO2-Daten in sensor_data speichern (metadata als dict, nicht json)
                metadata = {
                    'device_name': device_name,
                    'room': room_name,
                    'platform': platform_name
                }
                
                self.db.insert_sensor_data(
                    sensor_id=device_id,
                    sensor_type='co2',
                    value=float(co2_value),
                    unit='ppm',
                    metadata=metadata
                )
                
                collected_count += 1
                logger.debug(f"CO2 data: {device_name} ({room_name}) - {co2_value} ppm")
                
            except Exception as e:
                error_msg = str(e).encode('ascii', 'ignore').decode('ascii')
                logger.error(f"Error collecting CO2 from {device.get('name', 'unknown')}: {error_msg}")
        
        if collected_count > 0:
            logger.info(f"Collected CO2 data from {collected_count} sensor(s)")
    
    def _collect_pm25_data(self, devices: list, platform_name: str):
        """Sammelt PM2.5 Feinstaub-Daten von allen Geräten mit measure_pm25 Capability"""
        collected_count = 0
        
        for device in devices:
            try:
                caps = device.get('capabilitiesObj', {})
                pm25_cap = caps.get('measure_pm25', {})
                pm25_value = pm25_cap.get('value')
                
                if pm25_value is None:
                    continue
                
                device_id = device.get('id', '')
                device_name = device.get('name', 'Unknown')
                
                # Room aus zone holen
                zone = device.get('zone')
                if isinstance(zone, dict):
                    room_name = zone.get('name', 'Unknown')
                elif isinstance(zone, str):
                    room_name = zone
                else:
                    room_name = 'Unknown'
                
                # PM2.5-Daten in sensor_data speichern
                metadata = {
                    'device_name': device_name,
                    'room': room_name,
                    'platform': platform_name
                }
                
                self.db.insert_sensor_data(
                    sensor_id=device_id,
                    sensor_type='pm25',
                    value=float(pm25_value),
                    unit='µg/m³',
                    metadata=metadata
                )
                
                collected_count += 1
                logger.debug(f"PM2.5 data: {device_name} ({room_name}) - {pm25_value} µg/m³")
                
            except Exception as e:
                error_msg = str(e).encode('ascii', 'ignore').decode('ascii')
                logger.error(f"Error collecting PM2.5 from {device.get('name', 'unknown')}: {error_msg}")
        
        if collected_count > 0:
            logger.info(f"Collected PM2.5 data from {collected_count} sensor(s)")


def start_temperature_collector(config: dict | None = None):
    """Convenience-Funktion zum Starten"""
    collector = TemperatureDataCollector(config=config)
    collector.start()
    return collector


if __name__ == '__main__':
    # Test
    from src.utils.config_loader import ConfigLoader
    
    config = ConfigLoader()
    collector = TemperatureDataCollector(config=config.config)
    
    print("Starting temperature data collector...")
    collector.start()
    
    try:
        while True:
            time.sleep(10)
            stats = collector.get_stats()
            print(f"Stats: {stats}")
    except KeyboardInterrupt:
        print("\nStopping...")
        collector.stop()
