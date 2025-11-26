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
    
    @ventilation_bp.route('/ventilation/recommendations', methods=['GET'])
    def get_recommendations():
        """Hole Lüftungsempfehlungen für alle Räume"""
        try:
            recommendations = []
            zones = _get_zones()
            
            if engine and hasattr(engine, 'ventilation_optimizer') and engine.ventilation_optimizer:
                for zone_id, zone_name in zones.items():
                    try:
                        rec = engine.ventilation_optimizer.get_recommendation(room_id=zone_id)
                        if rec:
                            rec['room_id'] = zone_id
                            rec['room_name'] = zone_name
                            recommendations.append(rec)
                    except Exception as e:
                        logger.debug(f"Could not get recommendation for {zone_id}: {e}")
            
            return jsonify({
                'success': True,
                'recommendations': recommendations,
                'count': len(recommendations)
            })
        except Exception as e:
            logger.error(f"Error getting recommendations: {e}")
            return jsonify({'error': str(e)}), 500

    @ventilation_bp.route('/ventilation/sensors', methods=['GET'])
    def get_sensors():
        """Hole alle verfügbaren Sensoren (Homey + HA)"""
        try:
            sensors = {'homey': [], 'homeassistant': []}
            
            # Homey Sensoren
            if engine and engine.platform:
                try:
                    devices = engine.platform.get_all_devices()
                    zones = _get_zones()
                    
                    if devices:
                        for device_id, device in devices.items():
                            capabilities = device.get('capabilities', [])
                            sensor_types = []
                            
                            if 'measure_temperature' in capabilities:
                                sensor_types.append('temperature')
                            if 'measure_humidity' in capabilities:
                                sensor_types.append('humidity')
                            if 'measure_co2' in capabilities:
                                sensor_types.append('co2')
                            
                            if sensor_types:
                                zone_id = device.get('zone')
                                sensors['homey'].append({
                                    'id': device_id,
                                    'name': device.get('name', device_id),
                                    'zone_id': zone_id,
                                    'zone_name': zones.get(zone_id, zone_id) if zone_id else None,
                                    'sensor_types': sensor_types
                                })
                except Exception as e:
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
                                
                                sensor_type = None
                                if '°C' in unit or 'temperature' in entity_id.lower():
                                    sensor_type = 'temperature'
                                elif '%' in unit and 'humidity' in entity_id.lower():
                                    sensor_type = 'humidity'
                                elif 'ppm' in unit or 'co2' in entity_id.lower():
                                    sensor_type = 'co2'
                                
                                if sensor_type:
                                    sensors['homeassistant'].append({
                                        'id': entity_id,
                                        'name': attributes.get('friendly_name', entity_id),
                                        'sensor_type': sensor_type,
                                        'unit': unit,
                                        'state': entity.get('state')
                                    })
                except Exception as e:
                    logger.error(f"Error getting HA sensors: {e}")
            
            return jsonify({'success': True, 'sensors': sensors})
        except Exception as e:
            logger.error(f"Error getting sensors: {e}")
            return jsonify({'error': str(e)}), 500

    @ventilation_bp.route('/ventilation/sensor-mapping', methods=['GET'])
    def get_sensor_mapping():
        """Hole aktuelle Sensor-Zuordnungen"""
        try:
            mapping = _load_sensor_mapping()
            zones = _get_zones()
            
            enriched_mapping = {}
            for room_id, sensors in mapping.items():
                enriched_mapping[room_id] = {
                    'room_name': zones.get(room_id, room_id),
                    'sensors': sensors
                }
            
            return jsonify({
                'success': True,
                'mapping': enriched_mapping,
                'zones': zones
            })
        except Exception as e:
            logger.error(f"Error getting sensor mapping: {e}")
            return jsonify({'error': str(e)}), 500

    @ventilation_bp.route('/ventilation/sensor-mapping', methods=['POST'])
    @validate_request({
        'room_id': Validators.device_id(required=True),
        'temperature_sensor': FieldValidator(required=False),
        'humidity_sensor': FieldValidator(required=False),
        'co2_sensor': FieldValidator(required=False)
    })
    def save_sensor_mapping():
        """Speichere Sensor-Zuordnung für einen Raum"""
        try:
            data = request.validated_data
            room_id = data['room_id']
            
            mapping = _load_sensor_mapping()
            mapping[room_id] = {
                'temperature_sensor': data.get('temperature_sensor'),
                'humidity_sensor': data.get('humidity_sensor'),
                'co2_sensor': data.get('co2_sensor'),
                'updated_at': datetime.now().isoformat()
            }
            
            if _save_sensor_mapping(mapping):
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
            mapping = _load_sensor_mapping()
            
            if room_id in mapping:
                del mapping[room_id]
                if _save_sensor_mapping(mapping):
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
