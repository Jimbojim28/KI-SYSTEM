"""
API Blueprint für Badezimmer-Sensor Konfiguration
Ermöglicht die Konfiguration zusätzlicher Sensoren für verbesserte Duscherkennung
"""

from flask import Blueprint, jsonify, request
from loguru import logger
from typing import Optional
import yaml
import os

bathroom_bp = Blueprint('bathroom', __name__, url_prefix='/api/bathroom')

# Globale Referenzen
_engine = None
_db = None
_config = None


def init_bathroom_blueprint(engine, db, config):
    """Initialisiert den Blueprint mit Engine, Database und Config Referenzen"""
    global _engine, _db, _config
    _engine = engine
    _db = db
    _config = config
    logger.debug("Bathroom Blueprint initialized")


@bathroom_bp.route('/sensors/config', methods=['GET'])
def get_sensor_config():
    """
    GET /api/bathroom/sensors/config
    
    Liefert die aktuelle Konfiguration der Badezimmer-Sensoren
    
    Response:
    {
        "shower_sensors": {
            "humidity_sensor": "sensor.dusche_luftfeuchtigkeit",
            "temperature_sensor": "sensor.dusche_temperatur",
            "enable_rate_detection": true,
            "rate_threshold": 2.0
        },
        "main_sensors": {
            "humidity_sensor": "sensor.bathroom_humidity",
            "temperature_sensor": "sensor.bathroom_temperature"
        }
    }
    """
    try:
        # Lade aktuelle Config aus YAML
        config_path = 'config/config.yaml'
        with open(config_path, 'r', encoding='utf-8') as f:
            config_data = yaml.safe_load(f)
        
        bathroom_config = config_data.get('collectors', {}).get('bathroom', {})
        shower_sensors = bathroom_config.get('shower_sensors', {})
        
        # Hole auch Hauptsensoren aus der Badezimmer-Automatisierung
        main_sensors = {}
        try:
            if _engine and hasattr(_engine, 'bathroom_automation') and _engine.bathroom_automation:
                ba_config = _engine.bathroom_automation.config
                main_sensors = {
                    'humidity_sensor': ba_config.get('humidity_sensor_id', ''),
                    'temperature_sensor': ba_config.get('temperature_sensor_id', ''),
                    'dehumidifier_id': ba_config.get('dehumidifier_id', ''),
                    'heater_id': ba_config.get('heater_id', ''),
                    'motion_sensor_id': ba_config.get('motion_sensor_id', ''),
                    'door_sensor_id': ba_config.get('door_sensor_id', ''),
                    'window_sensor_id': ba_config.get('window_sensor_id', '')
                }
        except Exception as e:
            logger.warning(f"Could not load main sensors from engine: {e}")
        
        return jsonify({
            'shower_sensors': {
                'humidity_sensor': shower_sensors.get('humidity_sensor', ''),
                'temperature_sensor': shower_sensors.get('temperature_sensor', ''),
                'enable_rate_detection': shower_sensors.get('enable_rate_detection', True),
                'rate_threshold': shower_sensors.get('rate_threshold', 2.0)
            },
            'main_sensors': main_sensors
        })
    
    except Exception as e:
        logger.error(f"Error reading bathroom sensor config: {e}")
        return jsonify({'error': str(e)}), 500


@bathroom_bp.route('/sensors/config', methods=['POST'])
def update_sensor_config():
    """
    POST /api/bathroom/sensors/config
    
    Aktualisiert die Badezimmer-Sensor Konfiguration
    
    Request Body:
    {
        "shower_sensors": {
            "humidity_sensor": "sensor.dusche_luftfeuchtigkeit",
            "temperature_sensor": "sensor.dusche_temperatur",
            "enable_rate_detection": true,
            "rate_threshold": 2.0
        }
    }
    
    Response:
    {
        "success": true,
        "message": "Configuration updated"
    }
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        
        shower_sensors = data.get('shower_sensors', {})
        
        # Lade aktuelle Config
        config_path = 'config/config.yaml'
        with open(config_path, 'r', encoding='utf-8') as f:
            config_data = yaml.safe_load(f)
        
        # Update shower_sensors
        if 'collectors' not in config_data:
            config_data['collectors'] = {}
        if 'bathroom' not in config_data['collectors']:
            config_data['collectors']['bathroom'] = {'enabled': True, 'interval': 60}
        
        config_data['collectors']['bathroom']['shower_sensors'] = {
            'humidity_sensor': shower_sensors.get('humidity_sensor', ''),
            'temperature_sensor': shower_sensors.get('temperature_sensor', ''),
            'enable_rate_detection': shower_sensors.get('enable_rate_detection', True),
            'rate_threshold': float(shower_sensors.get('rate_threshold', 2.0))
        }
        
        # Schreibe Config zurück
        with open(config_path, 'w', encoding='utf-8') as f:
            yaml.dump(config_data, f, default_flow_style=False, allow_unicode=True)
        
        logger.info(f"Bathroom sensor config updated: {shower_sensors}")
        
        return jsonify({
            'success': True,
            'message': 'Konfiguration erfolgreich aktualisiert. Bitte Server neu starten für volle Wirkung.'
        })
    
    except Exception as e:
        logger.error(f"Error updating bathroom sensor config: {e}")
        return jsonify({'error': str(e)}), 500


@bathroom_bp.route('/sensors/available', methods=['GET'])
def get_available_sensors():
    """
    GET /api/bathroom/sensors/available
    
    Liefert alle verfügbaren Feuchtigkeits- und Temperatursensoren
    Unterstützt sowohl Home Assistant als auch Homey Pro
    Zeigt ALLE Sensoren (nicht nur mit "Dusche" im Namen)
    """
    try:
        humidity_sensors = []
        temperature_sensors = []
        
        # Plattform-Typ ermitteln
        platform_type = None
        if _config:
            platform_type = _config.get('platform', {}).get('type') or _config.get('platform.type')
        if not platform_type and _engine:
            try:
                platform_type = _engine.config.get('platform.type') or _engine.config.get('platform', {}).get('type')
            except Exception:
                pass
        
        # Versuche Sensoren über die aktive Engine-Plattform zu holen
        if _engine and hasattr(_engine, 'platform') and _engine.platform:
            try:
                devices = _engine.platform.get_all_devices()
                if devices:
                    logger.info(f"Fetching sensors via engine platform ({platform_type}): {len(devices)} devices")
                    for device in devices:
                        if not isinstance(device, dict):
                            continue
                        
                        device_id = device.get('id', '')
                        name = device.get('name', device_id)
                        caps = device.get('capabilities', [])
                        if isinstance(caps, dict):
                            caps = list(caps.keys())
                        caps_obj = device.get('capabilitiesObj', {}) or {}
                        
                        # Feuchtigkeitssensor (Homey: measure_humidity, HA: humidity device_class)
                        if 'measure_humidity' in caps or device.get('attributes', {}).get('device_class') == 'humidity':
                            current_val = None
                            if caps_obj.get('measure_humidity'):
                                current_val = caps_obj['measure_humidity'].get('value')
                            elif 'measure_humidity' in caps:
                                state = _engine.platform.get_state(device_id)
                                if state:
                                    try:
                                        current_val = float(state.get('state', 0))
                                    except (ValueError, TypeError):
                                        pass
                            humidity_sensors.append({
                                'entity_id': device_id,
                                'name': name,
                                'state': str(current_val) if current_val is not None else 'N/A',
                                'unit': '%',
                                'zone': device.get('zoneName', '')
                            })
                        
                        # Temperatursensor (Homey: measure_temperature)
                        if 'measure_temperature' in caps or device.get('attributes', {}).get('device_class') == 'temperature':
                            current_val = None
                            if caps_obj.get('measure_temperature'):
                                current_val = caps_obj['measure_temperature'].get('value')
                            temperature_sensors.append({
                                'entity_id': device_id,
                                'name': name,
                                'state': str(current_val) if current_val is not None else 'N/A',
                                'unit': '°C',
                                'zone': device.get('zoneName', '')
                            })
                    
                    logger.info(f"Found via platform: {len(humidity_sensors)} humidity, {len(temperature_sensors)} temperature sensors")
            except Exception as e:
                logger.warning(f"Could not fetch sensors via engine platform: {e}")
        
        # Fallback: Home Assistant direkt abfragen (falls Plattform HA ist oder Engine nicht verfügbar)
        if not humidity_sensors and not temperature_sensors:
            try:
                from src.data_collector.ha_collector import HomeAssistantCollector
                
                ha_url = None
                ha_token = None
                
                if _config:
                    ha_url = _config.get('homeassistant', {}).get('url')
                    ha_token = _config.get('homeassistant', {}).get('token')
                elif _engine and hasattr(_engine, 'config'):
                    ha_url = _engine.config.get('homeassistant', {}).get('url')
                    ha_token = _engine.config.get('homeassistant', {}).get('token')
                
                if ha_url and ha_token:
                    logger.info(f"Fallback: Fetching sensors from Home Assistant: {ha_url}")
                    collector = HomeAssistantCollector(ha_url, ha_token)
                    all_states = collector._make_request("states")
                    
                    if all_states:
                        for state_data in all_states:
                            entity_id = state_data.get('entity_id', '')
                            if not entity_id.startswith('sensor.'):
                                continue
                            
                            state = state_data.get('state', '')
                            attributes = state_data.get('attributes', {})
                            name = attributes.get('friendly_name', entity_id)
                            unit = attributes.get('unit_of_measurement', '')
                            device_class = attributes.get('device_class', '')
                            
                            # Überspringe Batterie/Druck-Sensoren
                            skip_words = ['battery', 'batterie', 'druck', 'pressure', 'signal', 'rssi']
                            if any(w in entity_id.lower() or w in name.lower() for w in skip_words):
                                continue
                            
                            is_humidity = (
                                device_class == 'humidity' or
                                (unit == '%' and ('humid' in entity_id.lower() or 'feucht' in entity_id.lower() or 'humid' in name.lower() or 'feucht' in name.lower()))
                            )
                            is_temperature = (
                                device_class == 'temperature' or
                                unit in ['°C', '°F'] or
                                'temperatur' in entity_id.lower() or 'temperature' in entity_id.lower()
                            )
                            
                            if is_humidity:
                                humidity_sensors.append({
                                    'entity_id': entity_id,
                                    'name': name,
                                    'state': state,
                                    'unit': unit or '%'
                                })
                            elif is_temperature:
                                temperature_sensors.append({
                                    'entity_id': entity_id,
                                    'name': name,
                                    'state': state,
                                    'unit': unit or '°C'
                                })
            except Exception as e:
                logger.error(f"HA fallback sensor fetch failed: {e}", exc_info=True)
        
        # Sortiere nach Name
        humidity_sensors.sort(key=lambda x: x['name'])
        temperature_sensors.sort(key=lambda x: x['name'])
        
        logger.info(f"Total available sensors: {len(humidity_sensors)} humidity, {len(temperature_sensors)} temperature")
        
        return jsonify({
            'humidity_sensors': humidity_sensors,
            'temperature_sensors': temperature_sensors
        })
    
    except Exception as e:
        logger.error(f"Error getting available sensors: {e}")
        return jsonify({'error': str(e)}), 500


@bathroom_bp.route('/stats', methods=['GET'])
def get_bathroom_stats():
    """
    GET /api/bathroom/stats
    
    Liefert Statistiken zur Duscherkennung
    
    Response:
    {
        "total_showers": 45,
        "avg_duration_minutes": 12.5,
        "avg_humidity_increase": 25.3,
        "avg_rate_per_minute": 3.8
    }
    """
    try:
        if not _db:
            return jsonify({'error': 'Database not available'}), 500
        
        # Hole Statistiken aus der Datenbank
        query = """
            SELECT 
                COUNT(*) as total_showers,
                AVG((julianday(end_time) - julianday(start_time)) * 24 * 60) as avg_duration_minutes,
                AVG(peak_humidity - start_humidity) as avg_humidity_increase
            FROM bathroom_events
            WHERE end_time IS NOT NULL
                AND datetime(start_time) > datetime('now', '-30 days')
        """
        
        result = _db.execute(query)
        
        if result and len(result) > 0:
            row = result[0]
            # Handle both dict and tuple results
            if isinstance(row, dict):
                total = row.get('total_showers', 0)
                avg_duration = row.get('avg_duration_minutes', 0)
                avg_increase = row.get('avg_humidity_increase', 0)
            else:
                total = row[0]
                avg_duration = row[1]
                avg_increase = row[2]
            
            return jsonify({
                'total_showers': int(total or 0),
                'avg_duration_minutes': round(float(avg_duration or 0), 1),
                'avg_humidity_increase': round(float(avg_increase or 0), 1),
                'period_days': 30
            })
        else:
            return jsonify({
                'total_showers': 0,
                'avg_duration_minutes': 0,
                'avg_humidity_increase': 0,
                'period_days': 30
            })
    
    except Exception as e:
        logger.error(f"Error getting bathroom stats: {e}")
        return jsonify({'error': str(e)}), 500


@bathroom_bp.route('/humidity-history', methods=['GET'])
def get_humidity_history():
    """
    GET /api/bathroom/humidity-history?hours=24
    
    Liefert historische Luftfeuchtigkeitsdaten für beide Sensoren
    
    Query Parameters:
    - hours: Zeitraum in Stunden (12, 24, 48) - default: 24
    
    Response:
    {
        "main_sensor": {
            "entity_id": "sensor.bathroom_humidity",
            "name": "Badezimmer Luftfeuchtigkeit",
            "data": [
                {"timestamp": "2026-01-03T20:00:00", "humidity": 65.2},
                {"timestamp": "2026-01-03T20:15:00", "humidity": 66.1}
            ]
        },
        "shower_sensor": {
            "entity_id": "sensor.dusche_luftfeuchtigkeit",
            "name": "Dusche Luftfeuchtigkeit",
            "data": [
                {"timestamp": "2026-01-03T20:00:00", "humidity": 52.8},
                {"timestamp": "2026-01-03T20:15:00", "humidity": 53.5}
            ]
        },
        "hours": 24
    }
    """
    try:
        hours = int(request.args.get('hours', 24))
        if hours not in [12, 24, 48]:
            hours = 24
        
        if not _db:
            return jsonify({'error': 'Database not available'}), 500
        
        # Hole Sensor-Konfiguration
        config_data = {}
        if _config:
            config_data = _config.get('collectors', {}).get('bathroom', {})
        
        main_sensor_id = config_data.get('humidity_sensor', 'sensor.bathroom_humidity')
        shower_config = config_data.get('shower_sensors', {})
        shower_sensor_id = shower_config.get('humidity_sensor', '')
        
        # Hole Daten aus der Datenbank
        query = """
            SELECT timestamp, humidity, temperature, shower_humidity
            FROM bathroom_continuous_measurements
            WHERE datetime(timestamp) > datetime('now', '-' || ? || ' hours')
            ORDER BY timestamp ASC
        """
        
        result = _db.execute(query, (hours,))
        
        main_data = []
        shower_data = []
        
        if result:
            for row in result:
                # Datenbank gibt Dicts zurück
                timestamp = row.get('timestamp') if isinstance(row, dict) else row[0]
                main_humidity = row.get('humidity') if isinstance(row, dict) else row[1]
                shower_humidity = row.get('shower_humidity') if isinstance(row, dict) else (row[3] if len(row) > 3 else None)
                
                if main_humidity is not None:
                    main_data.append({
                        'timestamp': timestamp,
                        'humidity': round(float(main_humidity), 1)
                    })
                
                if shower_humidity is not None:
                    shower_data.append({
                        'timestamp': timestamp,
                        'humidity': round(float(shower_humidity), 1)
                    })
        
        response = {
            'main_sensor': {
                'entity_id': main_sensor_id,
                'name': 'Badezimmer Luftfeuchtigkeit',
                'data': main_data
            },
            'hours': hours
        }
        
        # Nur Duschsensor hinzufügen wenn konfiguriert
        if shower_sensor_id:
            response['shower_sensor'] = {
                'entity_id': shower_sensor_id,
                'name': 'Dusche Luftfeuchtigkeit',
                'data': shower_data
            }
        
        return jsonify(response)
    
    except Exception as e:
        logger.error(f"Error getting humidity history: {e}")
        return jsonify({'error': str(e)}), 500
