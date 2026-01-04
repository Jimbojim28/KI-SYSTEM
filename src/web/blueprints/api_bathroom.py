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
    
    Liefert alle verfügbaren Sensoren von Home Assistant
    Filtert nach humidity und temperature Sensoren
    
    Response:
    {
        "humidity_sensors": [
            {"entity_id": "sensor.dusche_luftfeuchtigkeit", "name": "Dusche Luftfeuchtigkeit", "state": "52.99"},
            {"entity_id": "sensor.bathroom_humidity", "name": "Badezimmer Luftfeuchtigkeit", "state": "65.0"}
        ],
        "temperature_sensors": [
            {"entity_id": "sensor.dusche_temperatur", "name": "Dusche Temperatur", "state": "19.14"},
            {"entity_id": "sensor.bathroom_temperature", "name": "Badezimmer Temperatur", "state": "22.5"}
        ]
    }
    """
    try:
        humidity_sensors = []
        temperature_sensors = []
        
        # Versuche Sensoren von Home Assistant zu holen
        try:
            from src.data_collector.ha_collector import HomeAssistantCollector
            
            # Hole Config
            ha_url = None
            ha_token = None
            
            if _config:
                ha_url = _config.get('homeassistant', {}).get('url')
                ha_token = _config.get('homeassistant', {}).get('token')
            elif _engine and hasattr(_engine, 'config'):
                ha_url = _engine.config.get('homeassistant', {}).get('url')
                ha_token = _engine.config.get('homeassistant', {}).get('token')
            
            if ha_url and ha_token:
                logger.info(f"Fetching sensors from Home Assistant: {ha_url}")
                collector = HomeAssistantCollector(ha_url, ha_token)
                
                # Hole alle States (nicht nur IDs)
                all_states = collector._make_request("states")
                
                if not all_states:
                    logger.warning("No states returned from Home Assistant")
                    return jsonify({'humidity_sensors': [], 'temperature_sensors': []})
                
                logger.info(f"Found {len(all_states)} entities from Home Assistant")
                
                for state_data in all_states:
                    entity_id = state_data.get('entity_id', '')
                    
                    if not entity_id.startswith('sensor.'):
                        continue
                    
                    state = state_data.get('state', '')
                    attributes = state_data.get('attributes', {})
                    name = attributes.get('friendly_name', entity_id)
                    unit = attributes.get('unit_of_measurement', '')
                    device_class = attributes.get('device_class', '')
                    
                    # NUR Sensoren mit "dusche" im Namen anzeigen
                    has_dusche = (
                        'dusche' in entity_id.lower() or 
                        'dusche' in name.lower() or
                        'shower' in entity_id.lower() or
                        'shower' in name.lower()
                    )
                    
                    if not has_dusche:
                        continue
                    
                    # Überspringe Batterie-Sensoren und andere nicht relevante Sensoren
                    if any(word in entity_id.lower() for word in ['batterie', 'battery', 'druck', 'pressure']):
                        continue
                    if any(word in name.lower() for word in ['batterie', 'battery', 'druck', 'pressure']):
                        continue
                    
                    # Filtere nach Typ - mehrere Kriterien
                    is_humidity = (
                        (unit == '%' and device_class == 'humidity') or
                        'luftfeuchtigkeit' in entity_id.lower() or 
                        'humidity' in entity_id.lower()
                    )
                    
                    is_temperature = (
                        unit in ['°C', '°F'] or 
                        device_class == 'temperature' or
                        'temperatur' in entity_id.lower() or
                        'temperature' in entity_id.lower()
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
                
                logger.info(f"Filtered: {len(humidity_sensors)} humidity, {len(temperature_sensors)} temperature sensors")
            else:
                logger.warning("Home Assistant URL or token not configured")
        
        except Exception as e:
            logger.error(f"Error fetching HA entities: {e}", exc_info=True)
        
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
