"""
API Blueprint für Lüftung/Ventilation
Enthält alle Endpoints für Lüftungsempfehlungen und Sensor-Zuordnungen
"""

from flask import Blueprint, jsonify, request
from loguru import logger
from pathlib import Path
import json
from datetime import datetime, timedelta
from typing import Dict, Any

from .validators import validate_request, Validators, FieldValidator

ventilation_bp = Blueprint('ventilation', __name__, url_prefix='/api')


def init_ventilation_blueprint(engine, db, config):
    """Initialisiert den Blueprint mit Engine, Database und Config Referenzen"""
    
    sensor_mapping_file = Path('data/ventilation_sensor_mapping.json')
    
    def _load_sensor_mapping() -> Dict[str, Any]:
        """Lade Sensor-Mapping aus Datei"""
        if sensor_mapping_file.exists():
            try:
                with open(sensor_mapping_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Error loading sensor mapping: {e}")
        return {}
    
    def _save_sensor_mapping(mapping: Dict[str, Any]) -> bool:
        """Speichere Sensor-Mapping in Datei"""
        try:
            sensor_mapping_file.parent.mkdir(parents=True, exist_ok=True)
            with open(sensor_mapping_file, 'w') as f:
                json.dump(mapping, f, indent=2)
            return True
        except Exception as e:
            logger.error(f"Error saving sensor mapping: {e}")
            return False
    
    def _get_zones() -> Dict[str, str]:
        """Hole Zonen/Räume aus Homey"""
        zones = {}
        if engine and engine.platform:
            try:
                zones = engine.platform.get_zones()
            except Exception as e:
                logger.debug(f"Could not get zones: {e}")
        return zones
    
    def _get_sensor_value(entity_id: str) -> float | None:
        """Hole den aktuellen Wert eines Sensors"""
        if not entity_id:
            return None
            
        try:
            if entity_id.startswith('homey:'):
                # Homey Sensor: homey:device_id:capability
                parts = entity_id.split(':')
                if len(parts) >= 3:
                    device_id = parts[1]
                    capability = f'measure_{parts[2]}'
                    
                    if engine and engine.platform:
                        devices = engine.platform.get_all_devices()
                        if devices and device_id in devices:
                            caps_obj = devices[device_id].get('capabilitiesObj', {})
                            if capability in caps_obj:
                                return caps_obj[capability].get('value')
            else:
                # Home Assistant Sensor
                if engine and hasattr(engine, 'platforms') and 'homeassistant' in engine.platforms:
                    ha_platform = engine.platforms['homeassistant']
                    ha_devices = ha_platform.get_all_devices()
                    if ha_devices and entity_id in ha_devices:
                        state = ha_devices[entity_id].get('state')
                        try:
                            return float(state)
                        except (ValueError, TypeError):
                            return None
        except Exception as e:
            logger.debug(f"Error getting sensor value for {entity_id}: {e}")
        return None
    
    @ventilation_bp.route('/ventilation/recommendations', methods=['GET'])
    def get_recommendations():
        """Hole Lüftungsempfehlungen für alle Räume basierend auf Sensor-Mapping"""
        try:
            # Lade Sensor-Mapping
            mapping_data = _load_sensor_mapping()
            room_mapping = mapping_data.get('rooms', {})
            outdoor_sensors = mapping_data.get('outdoor_sensors', {})
            
            # Hole Außentemperatur/-feuchtigkeit
            outdoor_temp = _get_sensor_value(outdoor_sensors.get('temperature'))
            outdoor_humidity = _get_sensor_value(outdoor_sensors.get('humidity'))
            
            rooms = []
            
            # Lade rooms.json für Raum-Infos
            rooms_file = Path('data/rooms.json')
            room_list = []
            if rooms_file.exists():
                try:
                    with open(rooms_file, 'r') as f:
                        room_list = json.load(f)
                except Exception as e:
                    logger.error(f"Error loading rooms.json: {e}")
            
            for room in room_list:
                room_id = room.get('id') or room.get('name', '').lower().replace(' ', '_')
                room_name = room.get('name', room_id)
                
                sensors = room_mapping.get(room_id, {})
                
                # Hole Sensor-Werte
                temperature = _get_sensor_value(sensors.get('temperature'))
                humidity = _get_sensor_value(sensors.get('humidity'))
                co2 = _get_sensor_value(sensors.get('co2'))
                
                # Generiere Empfehlung basierend auf den Werten
                recommendation = None
                
                if temperature is not None or humidity is not None or co2 is not None:
                    # CO2-basierte Empfehlung (höchste Priorität)
                    if co2 is not None and co2 > 1000:
                        if co2 > 2000:
                            recommendation = {
                                'action': 'Sofort lüften!',
                                'reason': f'CO₂-Wert kritisch hoch ({int(co2)} ppm). Frische Luft dringend erforderlich.',
                                'urgency': 'high'
                            }
                        elif co2 > 1400:
                            recommendation = {
                                'action': 'Lüften empfohlen',
                                'reason': f'CO₂-Wert erhöht ({int(co2)} ppm). Lüften verbessert die Luftqualität.',
                                'urgency': 'medium'
                            }
                        else:
                            recommendation = {
                                'action': 'Lüften sinnvoll',
                                'reason': f'CO₂-Wert leicht erhöht ({int(co2)} ppm).',
                                'urgency': 'low'
                            }
                    
                    # Luftfeuchtigkeit-basierte Empfehlung
                    elif humidity is not None:
                        if humidity > 70:
                            recommendation = {
                                'action': 'Lüften empfohlen',
                                'reason': f'Hohe Luftfeuchtigkeit ({humidity:.0f}%). Schimmelgefahr bei dauerhaft hoher Feuchtigkeit.',
                                'urgency': 'high' if humidity > 80 else 'medium'
                            }
                        elif humidity < 30:
                            recommendation = {
                                'action': 'Befeuchten empfohlen',
                                'reason': f'Niedrige Luftfeuchtigkeit ({humidity:.0f}%). Kann Atemwege reizen.',
                                'urgency': 'low'
                            }
                    
                    # Temperatur-basierte Empfehlung (wenn Außentemp bekannt)
                    elif temperature is not None and outdoor_temp is not None:
                        if temperature > 25 and outdoor_temp < temperature - 3:
                            recommendation = {
                                'action': 'Lüften zum Kühlen',
                                'reason': f'Innen {temperature:.1f}°C, außen {outdoor_temp:.1f}°C. Stoßlüften kann abkühlen.',
                                'urgency': 'low'
                            }
                
                room_data = {
                    'name': room_name,
                    'room_id': room_id,
                    'temperature': temperature,
                    'humidity': humidity,
                    'recommendation': recommendation
                }
                
                # CO2 nur hinzufügen wenn Sensor zugeordnet
                if sensors.get('co2'):
                    room_data['co2'] = co2
                
                # Außenwerte für ersten Raum (wird von UI oben angezeigt)
                if outdoor_temp is not None:
                    room_data['outdoor_temperature'] = outdoor_temp
                if outdoor_humidity is not None:
                    room_data['outdoor_humidity'] = outdoor_humidity
                
                rooms.append(room_data)
            
            return jsonify({
                'success': True,
                'rooms': rooms,
                'outdoor': {
                    'temperature': outdoor_temp,
                    'humidity': outdoor_humidity
                }
            })
        except Exception as e:
            logger.error(f"Error getting recommendations: {e}")
            return jsonify({'error': str(e)}), 500

    @ventilation_bp.route('/ventilation/sensors', methods=['GET'])
    def get_sensors():
        """Hole alle verfügbaren Sensoren (Homey + HA) - flaches Format mit Raum-Info"""
        try:
            sensors = []
            zones = _get_zones()
            
            # DEBUG: Log engine state
            import sys
            logger.warning(f"DEBUG get_sensors: engine={engine}, platform={engine.platform if engine else 'NO ENGINE'}")
            sys.stdout.write(f"DEBUG get_sensors: engine={engine}\n")
            sys.stdout.flush()
            
            # Homey Sensoren
            if engine and engine.platform:
                try:
                    devices = engine.platform.get_all_devices()
                    print(f"DEBUG: Got {len(devices) if devices else 0} devices from Homey, type={type(devices)}")
                    logger.info(f"Got {len(devices) if devices else 0} devices from Homey")
                    
                    # get_all_devices returns a List, not a Dict!
                    if devices and isinstance(devices, list):
                        co2_found = 0
                        for device in devices:
                            device_id = device.get('id', '')
                            # capabilities can be a list ['measure_temp'] OR dict with keys
                            capabilities_raw = device.get('capabilities', [])
                            capabilitiesObj = device.get('capabilitiesObj', {})
                            
                            # Build list of capability names from both sources
                            if isinstance(capabilities_raw, list):
                                cap_names = capabilities_raw
                            elif isinstance(capabilities_raw, dict):
                                cap_names = list(capabilities_raw.keys())
                            else:
                                cap_names = []
                            
                            # Also check capabilitiesObj keys
                            cap_names = list(set(cap_names) | set(capabilitiesObj.keys()))
                            
                            device_name = device.get('name', device_id)
                            zone_id = device.get('zone')
                            zone_name = zones.get(zone_id, 'Unbekannt') if zone_id else 'Unbekannt'
                            
                            if 'measure_temperature' in cap_names:
                                temp_value = capabilitiesObj.get('measure_temperature', {}).get('value')
                                sensors.append({
                                    'device_id': device_id,
                                    'name': device_name,
                                    'platform': 'homey',
                                    'room': zone_name,
                                    'type': 'temperature',
                                    'current_value': temp_value
                                })
                            
                            if 'measure_humidity' in cap_names:
                                humidity_value = capabilitiesObj.get('measure_humidity', {}).get('value')
                                sensors.append({
                                    'device_id': device_id,
                                    'name': device_name,
                                    'platform': 'homey',
                                    'room': zone_name,
                                    'type': 'humidity',
                                    'current_value': humidity_value
                                })
                            
                            if 'measure_co2' in cap_names:
                                co2_found += 1
                                co2_value = capabilitiesObj.get('measure_co2', {}).get('value')
                                print(f"DEBUG: Found CO2 sensor: {device_name} = {co2_value} ppm")
                                logger.info(f"Found CO2 sensor: {device_name} = {co2_value} ppm")
                                sensors.append({
                                    'device_id': device_id,
                                    'name': device_name,
                                    'platform': 'homey',
                                    'room': zone_name,
                                    'type': 'co2',
                                    'current_value': co2_value
                                })
                        print(f"DEBUG: Total CO2 sensors found: {co2_found}")
                        logger.info(f"Total CO2 sensors found: {co2_found}")
                except Exception as e:
                    print(f"DEBUG ERROR: {e}")
                    logger.error(f"Error getting Homey sensors: {e}")
            
            # Home Assistant Sensoren
            if engine and hasattr(engine, 'platforms') and 'homeassistant' in engine.platforms:
                try:
                    ha_platform = engine.platforms['homeassistant']
                    ha_devices = ha_platform.get_all_devices()
                    
                    if ha_devices:
                        for entity_id, entity in ha_devices.items():
                            if entity_id.startswith('sensor.'):
                                attributes = entity.get('attributes', {})
                                unit = attributes.get('unit_of_measurement', '')
                                friendly_name = attributes.get('friendly_name', entity_id)
                                state = entity.get('state')
                                
                                try:
                                    current_value = float(state) if state not in ['unavailable', 'unknown', None] else None
                                except (ValueError, TypeError):
                                    current_value = None
                                
                                sensor_type = None
                                if '°C' in unit or 'temperature' in entity_id.lower():
                                    sensor_type = 'temperature'
                                elif '%' in unit and 'humidity' in entity_id.lower():
                                    sensor_type = 'humidity'
                                elif 'ppm' in unit or 'co2' in entity_id.lower():
                                    sensor_type = 'co2'
                                
                                if sensor_type:
                                    sensors.append({
                                        'device_id': entity_id,
                                        'name': friendly_name,
                                        'platform': 'homeassistant',
                                        'room': 'Unbekannt',
                                        'type': sensor_type,
                                        'current_value': current_value
                                    })
                except Exception as e:
                    logger.error(f"Error getting HA sensors: {e}")
            
            return jsonify({'success': True, 'sensors': sensors, 'count': len(sensors)})
        except Exception as e:
            logger.error(f"Error getting sensors: {e}")
            return jsonify({'error': str(e)}), 500

    @ventilation_bp.route('/ventilation/sensor-mapping', methods=['GET'])
    def get_sensor_mapping():
        """Hole aktuelle Sensor-Zuordnungen"""
        try:
            data = _load_sensor_mapping()
            mapping = data.get('rooms', {})
            outdoor_sensors = data.get('outdoor_sensors', {'temperature': '', 'humidity': ''})
            zones = _get_zones()
            
            return jsonify({
                'success': True,
                'mapping': mapping,
                'outdoor_sensors': outdoor_sensors,
                'zones': zones
            })
        except Exception as e:
            logger.error(f"Error getting sensor mapping: {e}")
            return jsonify({'error': str(e)}), 500

    @ventilation_bp.route('/ventilation/sensor-mapping', methods=['POST'])
    def save_sensor_mapping():
        """Speichere Sensor-Zuordnung für alle Räume"""
        try:
            data = request.get_json()
            mapping = data.get('mapping', {})
            outdoor_sensors = data.get('outdoor_sensors', {'temperature': '', 'humidity': ''})
            
            save_data = {
                'rooms': mapping,
                'outdoor_sensors': outdoor_sensors,
                'updated_at': datetime.now().isoformat()
            }
            
            if _save_sensor_mapping(save_data):
                return jsonify({'success': True, 'message': 'Sensor-Zuordnung gespeichert'})
            else:
                return jsonify({'error': 'Fehler beim Speichern'}), 500
        except Exception as e:
            logger.error(f"Error saving sensor mapping: {e}")
            return jsonify({'error': str(e)}), 500

    @ventilation_bp.route('/ventilation/sensor-mapping/<room_id>', methods=['DELETE'])
    def delete_sensor_mapping(room_id: str):
        """Lösche Sensor-Zuordnung für einen Raum"""
        try:
            data = _load_sensor_mapping()
            rooms = data.get('rooms', {})
            
            if room_id in rooms:
                del rooms[room_id]
                data['rooms'] = rooms
                data['updated_at'] = datetime.now().isoformat()
                
                if _save_sensor_mapping(data):
                    return jsonify({'success': True, 'message': 'Zuordnung gelöscht'})
                else:
                    return jsonify({'error': 'Fehler beim Speichern'}), 500
            else:
                return jsonify({'error': 'Zuordnung nicht gefunden'}), 404
        except Exception as e:
            logger.error(f"Error deleting sensor mapping: {e}")
            return jsonify({'error': str(e)}), 500

    @ventilation_bp.route('/ventilation/history/<room_id>', methods=['GET'])
    def get_room_history(room_id: str):
        """Hole Verlaufsdaten für einen Raum"""
        try:
            hours = request.args.get('hours', 24, type=int)
            hours = min(max(hours, 1), 168)  # 1h - 1 Woche
            
            since = datetime.now() - timedelta(hours=hours)
            history = []
            
            if db:
                try:
                    cursor = db.execute('''
                        SELECT timestamp, temperature, humidity
                        FROM temperature_data
                        WHERE room_id = ?
                        AND timestamp >= ?
                        ORDER BY timestamp ASC
                    ''', (room_id, since.isoformat()))
                    
                    history = [
                        {'timestamp': row[0], 'temperature': row[1], 'humidity': row[2]}
                        for row in cursor.fetchall()
                    ]
                except Exception as e:
                    logger.error(f"Error querying history: {e}")
            
            zones = _get_zones()
            return jsonify({
                'success': True,
                'room_id': room_id,
                'room_name': zones.get(room_id, room_id),
                'history': history,
                'hours': hours
            })
        except Exception as e:
            logger.error(f"Error getting room history: {e}")
            return jsonify({'error': str(e)}), 500

    return ventilation_bp
