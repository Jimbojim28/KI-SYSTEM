import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

def get_all_sensors(engine, include_ignored=False):
    """
    Zentrale Funktion zum Abrufen aller Sensoren (Temperatur, Feuchtigkeit, CO2) von Homey und HA.
    
    :param engine: Die Application Engine (für Zugriff auf Homey/HA)
    :param include_ignored: Wenn True, werden auch ignorierte Sensoren zurückgegeben (mit 'ignored': True)
    :return: Liste von Sensor-Dictionaries
    """
    sensors = []
    
    # Lade Ignorierte Sensoren
    rooms_file = Path('data/rooms.json')
    ignored_sensors = []
    try:
        if rooms_file.exists():
            with open(rooms_file, 'r') as f:
                rooms_data = json.load(f)
            ignored_sensors = rooms_data.get('ignored_sensors', [])
    except Exception as e:
        logger.error(f"Error loading ignored sensors: {e}")

    def is_ignored(dev_id):
        return dev_id in ignored_sensors

    # === 1. Homey Sensoren ===
    if engine and hasattr(engine, 'platform') and engine.platform:
        try:
            # Wir versuchen verschiedene Wege, an die Geräte zu kommen
            devices = []
            states = {}
            
            if hasattr(engine.platform, 'get_all_devices'):
                devices = engine.platform.get_all_devices()
            
            if hasattr(engine.platform, 'get_states'):
                states = engine.platform.get_states() or {}

            # Fallback wenn get_all_devices leer ist aber states da sind
            if not devices and states:
                # Versuche Devices aus States zu rekonstruieren
                pass 

            # Zone-ID zu Name Mapping
            zones = {}
            if hasattr(engine.platform, 'get_zones'):
                zones = engine.platform.get_zones() or {}
            
            zone_names = {}
            for zone_id, zone_data in zones.items():
                zone_names[zone_id] = zone_data.get('name', zone_id)
            
            # Device-ID zu Zone Mapping
            device_zones = {}
            for device in devices:
                device_id = device.get('id')
                zone_id = device.get('zone')
                if device_id and zone_id:
                    device_zones[device_id] = zone_id

            # Iteriere über States (da dort die aktuellen Werte sind)
            for device_id, state in states.items():
                if not state:
                    continue
                
                # Prüfe Ignore
                ignored = is_ignored(device_id)
                if ignored and not include_ignored:
                    continue

                attrs = state.get('attributes', {})
                caps = attrs.get('capabilities', {})
                friendly_name = attrs.get('friendly_name', device_id)
                
                # Hole Zone-ID und Namen
                zone_id = device_zones.get(device_id) or attrs.get('zone')
                if not zone_id:
                    # Versuche Zone aus Device-Liste zu holen falls nicht in State
                    pass
                
                room_name = zone_names.get(zone_id, 'Unbekannt')
                
                # Temperatursensor
                if 'measure_temperature' in caps:
                    sensors.append({
                        'device_id': device_id,
                        'name': friendly_name,
                        'room': room_name,
                        'zone_id': zone_id,
                        'type': 'temperature',
                        'platform': 'homey',
                        'current_value': caps['measure_temperature'].get('value'),
                        'ignored': ignored
                    })
                
                # Feuchtigkeitssensor
                if 'measure_humidity' in caps:
                    sensors.append({
                        'device_id': device_id,
                        'name': friendly_name,
                        'room': room_name,
                        'zone_id': zone_id,
                        'type': 'humidity',
                        'platform': 'homey',
                        'current_value': caps['measure_humidity'].get('value'),
                        'ignored': ignored
                    })
                
                # CO2-Sensor
                if 'measure_co2' in caps:
                    sensors.append({
                        'device_id': device_id,
                        'name': friendly_name,
                        'room': room_name,
                        'zone_id': zone_id,
                        'type': 'co2',
                        'platform': 'homey',
                        'current_value': caps['measure_co2'].get('value'),
                        'ignored': ignored
                    })
                    
        except Exception as e:
            logger.error(f"Error getting Homey sensors: {e}")

    # === 2. Home Assistant Sensoren ===
    if engine and hasattr(engine, 'platforms') and 'homeassistant' in engine.platforms:
        try:
            ha_platform = engine.platforms['homeassistant']
            ha_states = ha_platform.get_states()
            
            for entity_id, state in ha_states.items():
                if not state:
                    continue
                
                # Prüfe Ignore
                ignored = is_ignored(entity_id)
                if ignored and not include_ignored:
                    continue
                
                attrs = state.get('attributes', {})
                device_class = attrs.get('device_class', '')
                unit = attrs.get('unit_of_measurement', '')
                friendly_name = attrs.get('friendly_name', entity_id)
                area = attrs.get('area', 'Unbekannt')
                
                # Temperatursensor
                if device_class == 'temperature' or unit in ['°C', '°F', 'C', 'F']:
                    try:
                        value = float(state.get('state', 0))
                        sensors.append({
                            'device_id': entity_id,
                            'name': friendly_name,
                            'room': area,
                            'zone_id': None,
                            'type': 'temperature',
                            'platform': 'ha',
                            'current_value': value,
                            'ignored': ignored
                        })
                    except (ValueError, TypeError):
                        pass
                
                # Feuchtigkeitssensor
                elif device_class == 'humidity' or unit == '%':
                    try:
                        value = float(state.get('state', 0))
                        sensors.append({
                            'device_id': entity_id,
                            'name': friendly_name,
                            'room': area,
                            'zone_id': None,
                            'type': 'humidity',
                            'platform': 'ha',
                            'current_value': value,
                            'ignored': ignored
                        })
                    except (ValueError, TypeError):
                        pass
                
                # CO2-Sensor
                elif device_class == 'carbon_dioxide' or unit in ['ppm', 'PPM']:
                    try:
                        value = float(state.get('state', 0))
                        sensors.append({
                            'device_id': entity_id,
                            'name': friendly_name,
                            'room': area,
                            'zone_id': None,
                            'type': 'co2',
                            'platform': 'ha',
                            'current_value': value,
                            'ignored': ignored
                        })
                    except (ValueError, TypeError):
                        pass
                        
        except Exception as e:
            logger.error(f"Error getting HA sensors: {e}")
            
    return sensors
