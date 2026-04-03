"""Wetter-Daten Sammler"""

import requests
from typing import Dict, Optional
from loguru import logger
from datetime import datetime


class WeatherCollector:
    """Sammelt Wetterdaten von verschiedenen APIs"""

    def __init__(self, api_key: str = None, location: str = "Berlin, DE"):
        self.api_key = api_key
        self.location = location

    def get_openweathermap_data(self) -> Optional[Dict]:
        """
        Holt Wetterdaten von OpenWeatherMap
        Kostenlos bis 60 calls/minute
        API Key: https://openweathermap.org/api
        """
        if not self.api_key:
            logger.warning("No weather API key provided")
            return None

        try:
            url = "https://api.openweathermap.org/data/2.5/weather"
            params = {
                'q': self.location,
                'appid': self.api_key,
                'units': 'metric',
                'lang': 'de'
            }

            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()

            # Strukturiere die relevanten Daten
            return {
                'timestamp': datetime.now().isoformat(),
                'temperature': data['main']['temp'],
                'feels_like': data['main']['feels_like'],
                'humidity': data['main']['humidity'],
                'pressure': data['main']['pressure'],
                'weather_condition': data['weather'][0]['main'],
                'weather_description': data['weather'][0]['description'],
                'clouds': data['clouds']['all'],
                'wind_speed': data['wind']['speed'],
                'sunrise': datetime.fromtimestamp(data['sys']['sunrise']).isoformat(),
                'sunset': datetime.fromtimestamp(data['sys']['sunset']).isoformat(),
            }

        except requests.exceptions.RequestException as e:
            logger.error(f"Weather API error: {e}")
            return None

    def get_forecast(self) -> Optional[Dict]:
        """
        Holt 5-Tage Wettervorhersage
        """
        if not self.api_key:
            return None

        try:
            url = "https://api.openweathermap.org/data/2.5/forecast"
            params = {
                'q': self.location,
                'appid': self.api_key,
                'units': 'metric',
                'lang': 'de'
            }

            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()

            # Parse 5-Tage Vorhersage (40 Eintraege a 3h)
            forecasts = []
            for item in data['list'][:40]:  # 40 * 3h = 5 Tage
                forecasts.append({
                    'timestamp': item['dt_txt'],
                    'temperature': item['main']['temp'],
                    'weather': item['weather'][0]['main'],
                    'rain_probability': item.get('pop', 0) * 100,  # Probability of precipitation
                    'wind_speed': item.get('wind', {}).get('speed')  # m/s
                })

            return {
                'timestamp': datetime.now().isoformat(),
                'forecasts': forecasts
            }

        except requests.exceptions.RequestException as e:
            logger.error(f"Forecast API error: {e}")
            return None

    def get_homey_weather(self, homey_collector) -> Optional[Dict]:
        """
        Nutzt Wetterdaten direkt von Homey
        Sammelt Temperatur/Luftfeuchtigkeit von Sensoren + DWD Warnungen
        """
        try:
            if hasattr(homey_collector, 'get_weather_data'):
                weather = homey_collector.get_weather_data()
                if weather:
                    logger.info("Weather data from Homey sensors")
                    return weather

        except Exception as e:
            logger.error(f"Error getting weather from Homey: {e}")

        return None

    def get_home_assistant_weather(self, ha_collector) -> Optional[Dict]:
        """
        Alternative: Nutzt Wetterdaten direkt von Home Assistant
        (falls dort bereits eine Wetterintegration konfiguriert ist)
        """
        try:
            # Home Assistant hat oft eine weather.* Entity
            weather_entities = ha_collector.get_all_entities(domain='weather')

            if not weather_entities:
                logger.warning("No weather entities found in Home Assistant")
                return None

            # Nimm die erste Weather-Entity
            weather_entity = weather_entities[0]
            state = ha_collector.get_state(weather_entity)

            if state:
                attrs = state['attributes']
                return {
                    'timestamp': datetime.now().isoformat(),
                    'temperature': attrs.get('temperature'),
                    'humidity': attrs.get('humidity'),
                    'pressure': attrs.get('pressure'),
                    'wind_speed': attrs.get('wind_speed'),
                    'weather_condition': state['state'],
                    'forecast': attrs.get('forecast', [])
                }

        except Exception as e:
            logger.error(f"Error getting weather from Home Assistant: {e}")

        return None

    def get_weather_data(self, platform_collector=None) -> Optional[Dict]:
        """
        Hauptmethode - holt OUTDOOR-Wetterdaten
        NUR von konfigurierten Außensensoren!
        Ergänzt fehlende Details (Wind, Druck, Gefühlt) von OpenWeatherMap.
        """
        # NUR konfigurierte Außensensoren nutzen!
        weather = self.get_configured_outdoor_sensors(platform_collector)
        if weather:
            logger.info(f"Weather data from configured outdoor sensors: {weather.get('temperature')}°C")
            # Ergänze fehlende Details von OpenWeatherMap (Wind, Luftdruck, Gefühlt, Bewölkung)
            if self.api_key:
                owm = self.get_openweathermap_data()
                if owm:
                    # Sensor-Temperatur/Feuchte behalten, Details von OWM übernehmen
                    weather.setdefault('feels_like', owm.get('feels_like'))
                    weather.setdefault('wind_speed', owm.get('wind_speed'))
                    weather.setdefault('pressure', owm.get('pressure'))
                    weather.setdefault('clouds', owm.get('clouds'))
                    if weather.get('weather_condition') == 'unknown':
                        weather['weather_condition'] = owm.get('weather_condition', 'unknown')
                    if not weather.get('weather_description') or weather.get('weather_description', '').startswith('Daten von'):
                        weather['weather_description'] = owm.get('weather_description', '')
                    logger.info(f"Weather details enriched from OpenWeatherMap: wind={owm.get('wind_speed')}m/s, pressure={owm.get('pressure')}hPa")
            return weather

        logger.warning("No configured outdoor sensors found - no weather data available")
        return None
    
    def get_configured_outdoor_sensors(self, platform_collector) -> Optional[Dict]:
        """
        Holt Außentemperatur/Luftfeuchtigkeit von konfigurierten Sensoren
        aus ventilation_sensor_mapping.json -> outdoor_sensors
        
        Unterstützt:
        - Home Assistant Entity-IDs (sensor.xxx)
        - Homey Device-IDs
        """
        import json
        import yaml
        from pathlib import Path
        
        try:
            mapping_file = Path('data/ventilation_sensor_mapping.json')
            if not mapping_file.exists():
                logger.warning("No sensor mapping file found")
                return None
            
            with open(mapping_file, 'r') as f:
                mapping = json.load(f)
            
            outdoor_sensors = mapping.get('outdoor_sensors', {})
            temp_sensor_id = outdoor_sensors.get('temperature')
            humidity_sensor_id = outdoor_sensors.get('humidity')
            
            logger.debug(f"Configured outdoor sensors: temp={temp_sensor_id}, humidity={humidity_sensor_id}")
            
            # Wenn keine Außensensoren konfiguriert sind, return None
            if not temp_sensor_id and not humidity_sensor_id:
                logger.warning("No outdoor sensors configured in mapping")
                return None
            
            temperature = None
            humidity = None
            
            # Prüfe ob es Home Assistant Entity-IDs sind (Format: sensor.xxx, weather.xxx, etc.)
            is_ha_temp_sensor = temp_sensor_id and '.' in temp_sensor_id and temp_sensor_id.split('.')[0] in ['sensor', 'weather', 'climate']
            is_ha_humidity_sensor = humidity_sensor_id and '.' in humidity_sensor_id and humidity_sensor_id.split('.')[0] in ['sensor', 'weather', 'climate']
            
            # Hole Home Assistant Sensoren direkt
            if is_ha_temp_sensor or is_ha_humidity_sensor:
                logger.debug("Detected Home Assistant entity IDs - querying HA directly")
                
                # Lade HA Konfiguration
                config_file = Path('config/config.yaml')
                if not config_file.exists():
                    logger.error("Config file not found")
                    return None
                    
                with open(config_file, 'r') as f:
                    config = yaml.safe_load(f)
                
                # Versuche verschiedene Config-Strukturen
                ha_config = config.get('integrations', {}).get('home_assistant', {})
                if not ha_config.get('url'):
                    ha_config = config.get('homeassistant', {})
                
                ha_url = ha_config.get('url')
                ha_token = ha_config.get('token')
                
                if not ha_url or not ha_token:
                    logger.error("Home Assistant URL or token not configured")
                    return None
                
                # Erstelle HA Collector
                from src.data_collector.ha_collector import HomeAssistantCollector
                ha_collector = HomeAssistantCollector(url=ha_url, token=ha_token)
                
                # Hole Temperatur
                if is_ha_temp_sensor and temp_sensor_id:
                    state = ha_collector.get_state(temp_sensor_id)
                    if state:
                        try:
                            temp_val = float(state.get('state', 'unknown'))
                            if -50 <= temp_val <= 60:
                                temperature = temp_val
                                logger.info(f"Outdoor temp from HA sensor {temp_sensor_id}: {temperature}°C")
                        except (ValueError, TypeError):
                            logger.warning(f"Invalid temperature value from {temp_sensor_id}: {state.get('state')}")
                
                # Hole Feuchtigkeit
                if is_ha_humidity_sensor and humidity_sensor_id:
                    state = ha_collector.get_state(humidity_sensor_id)
                    if state:
                        try:
                            hum_val = float(state.get('state', 'unknown'))
                            if 0 <= hum_val <= 100:
                                humidity = hum_val
                                logger.info(f"Outdoor humidity from HA sensor {humidity_sensor_id}: {humidity}%")
                        except (ValueError, TypeError):
                            logger.warning(f"Invalid humidity value from {humidity_sensor_id}: {state.get('state')}")
                
                # Wenn HA Sensoren gefunden, return
                if temperature is not None:
                    return {
                        'timestamp': datetime.now().isoformat(),
                        'source': 'configured_ha_outdoor_sensors',
                        'temperature': temperature,
                        'humidity': humidity,
                        'weather_condition': 'unknown',
                        'weather_description': 'Daten von konfiguriertem Home Assistant Außensensor'
                    }
            
            # Fallback: Homey Sensoren (wenn platform_collector verfügbar und keine HA IDs)
            if platform_collector and not is_ha_temp_sensor:
                logger.debug("Trying Homey sensors...")
                
                # Hole ALLE Geräte
                devices = None
                if hasattr(platform_collector, 'get_all_devices'):
                    devices = platform_collector.get_all_devices()
                elif hasattr(platform_collector, '_make_request'):
                    devices = platform_collector._make_request("/api/manager/devices/device")
                
                if devices:
                    if isinstance(devices, list):
                        devices_by_id = {d.get('id'): d for d in devices if isinstance(d, dict)}
                    else:
                        devices_by_id = devices
                    
                    # Suche Temperatur-Sensor
                    if temp_sensor_id and temp_sensor_id in devices_by_id:
                        device = devices_by_id[temp_sensor_id]
                        caps = device.get('capabilitiesObj', {})
                        if 'measure_temperature' in caps:
                            temp_val = caps['measure_temperature'].get('value')
                            if temp_val is not None and -50 <= temp_val <= 60:
                                temperature = temp_val
                                logger.info(f"Outdoor temp from Homey {device.get('name')}: {temperature}°C")
                    
                    # Suche Feuchtigkeits-Sensor
                    if humidity_sensor_id and humidity_sensor_id in devices_by_id:
                        device = devices_by_id[humidity_sensor_id]
                        caps = device.get('capabilitiesObj', {})
                        if 'measure_humidity' in caps:
                            hum_val = caps['measure_humidity'].get('value')
                            if hum_val is not None and 0 <= hum_val <= 100:
                                humidity = hum_val
                                logger.info(f"Outdoor humidity from Homey {device.get('name')}: {humidity}%")
                    
                    if temperature is not None:
                        return {
                            'timestamp': datetime.now().isoformat(),
                            'source': 'configured_homey_outdoor_sensors',
                            'temperature': temperature,
                            'humidity': humidity,
                            'weather_condition': 'unknown',
                            'weather_description': 'Daten von konfiguriertem Homey Außensensor'
                        }
            
            logger.warning(f"Could not get temperature from configured sensors")
            return None
            
        except Exception as e:
            logger.error(f"Error getting configured outdoor sensors: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return None
