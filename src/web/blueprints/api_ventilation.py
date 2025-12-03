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
    
    def _generate_ventilation_summary(tilted: dict, open_rec: dict, outdoor_temp: float) -> dict:
        """Generiert eine Zusammenfassung der Lüftungsempfehlungen"""
        summary = {
            'recommendation': '',
            'tilted_info': None,
            'open_info': None,
            'temp_warning': None
        }
        
        # Warnung bei extremen Temperaturen
        if outdoor_temp is not None:
            if outdoor_temp < 0:
                summary['temp_warning'] = '❄️ Sehr kalt! Nur kurz lüften empfohlen.'
            elif outdoor_temp < 5:
                summary['temp_warning'] = '🥶 Kalt - Stoßlüften (kurz, weit offen) bevorzugen.'
            elif outdoor_temp > 28:
                summary['temp_warning'] = '🌡️ Sehr warm! Morgens oder abends lüften.'
        
        if tilted and tilted.get('sample_count', 0) >= 3:
            duration = tilted.get('recommended_duration', 0)
            temp_change = tilted.get('expected_temp_change', 0)
            co2_change = tilted.get('expected_co2_change', 0)
            summary['tilted_info'] = {
                'duration_minutes': duration,
                'temp_change': temp_change,
                'co2_change': co2_change,
                'description': f"🪟 Gekippt: {duration} Min. → {abs(co2_change):.0f} ppm CO₂ weniger, {abs(temp_change):.1f}°C kühler"
            }
        
        if open_rec and open_rec.get('sample_count', 0) >= 3:
            duration = open_rec.get('recommended_duration', 0)
            temp_change = open_rec.get('expected_temp_change', 0)
            co2_change = open_rec.get('expected_co2_change', 0)
            summary['open_info'] = {
                'duration_minutes': duration,
                'temp_change': temp_change,
                'co2_change': co2_change,
                'description': f"🚪 Weit offen: {duration} Min. → {abs(co2_change):.0f} ppm CO₂ weniger, {abs(temp_change):.1f}°C kühler"
            }
        
        # Generiere Empfehlung
        if summary['tilted_info'] and summary['open_info']:
            tilted_eff = tilted.get('avg_effectiveness', 0) or 0
            open_eff = open_rec.get('avg_effectiveness', 0) or 0
            
            if outdoor_temp and outdoor_temp < 5:
                summary['recommendation'] = '🌬️ Bei Kälte: Kurzes Stoßlüften (weit offen) ist effektiver als langes Kipplüften.'
            elif tilted_eff > open_eff:
                summary['recommendation'] = '💡 Gekipptes Fenster ist hier oft effektiver - weniger Wärmeverlust bei gutem Luftaustausch.'
            else:
                summary['recommendation'] = '💡 Stoßlüften (weit offen) ist schneller - ideal wenn Frischluft dringend benötigt wird.'
        elif summary['tilted_info']:
            summary['recommendation'] = '📊 Nur Daten für Kipplüftung vorhanden.'
        elif summary['open_info']:
            summary['recommendation'] = '📊 Nur Daten für Stoßlüftung vorhanden.'
        else:
            summary['recommendation'] = '📊 Noch keine Lüftungsdaten gesammelt - lüften Sie weiter!'
        
        return summary
    
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
            
            # Hole Außensensor-Konfiguration und -Werte
            outdoor = None
            try:
                mapping_data = _load_sensor_mapping()
                outdoor_sensors = mapping_data.get('outdoor_sensors', {})
                
                outdoor_temp = None
                outdoor_humidity = None
                
                # Hole Werte aus konfigurierten Sensoren
                if outdoor_sensors.get('temperature'):
                    outdoor_temp = _get_sensor_value(outdoor_sensors.get('temperature'))
                if outdoor_sensors.get('humidity'):
                    outdoor_humidity = _get_sensor_value(outdoor_sensors.get('humidity'))
                
                # Fallback: Suche nach Sensoren mit "Außen" im Namen
                if outdoor_temp is None:
                    for s in sensors:
                        if s['type'] == 'temperature' and s['current_value'] is not None:
                            name_lower = s['name'].lower()
                            if 'außen' in name_lower or 'outdoor' in name_lower or 'aussen' in name_lower:
                                outdoor_temp = s['current_value']
                                break
                
                if outdoor_humidity is None:
                    for s in sensors:
                        if s['type'] == 'humidity' and s['current_value'] is not None:
                            name_lower = s['name'].lower()
                            if 'außen' in name_lower or 'outdoor' in name_lower or 'aussen' in name_lower:
                                outdoor_humidity = s['current_value']
                                break
                
                if outdoor_temp is not None or outdoor_humidity is not None:
                    outdoor = {
                        'temperature': outdoor_temp,
                        'humidity': outdoor_humidity
                    }
            except Exception as e:
                logger.error(f"Error getting outdoor data: {e}")
            
            return jsonify({'success': True, 'sensors': sensors, 'count': len(sensors), 'outdoor': outdoor})
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

    # ===== Ventilation Events API =====

    @ventilation_bp.route('/ventilation/windows/active', methods=['GET'])
    def get_active_ventilations():
        """API: Aktuelle offene Fenster mit Lüftungsdauer"""
        try:
            active = db.get_active_ventilations() if db else []
            
            # Bereichere mit aktuellen Klimadaten falls möglich
            for vent in active:
                room_name = vent.get('room_name')
                if room_name:
                    # Hole aktuelle Sensordaten für diesen Raum
                    sensors = _get_all_sensors()
                    room_sensors = [s for s in sensors if s.get('room') == room_name]
                    
                    for sensor in room_sensors:
                        if sensor['type'] == 'temperature' and vent.get('temp_current') is None:
                            vent['temp_current'] = sensor.get('current_value')
                        elif sensor['type'] == 'co2' and vent.get('co2_current') is None:
                            vent['co2_current'] = sensor.get('current_value')
                        elif sensor['type'] == 'humidity' and vent.get('humidity_current') is None:
                            vent['humidity_current'] = sensor.get('current_value')
            
            return jsonify({
                'success': True,
                'active_ventilations': active,
                'count': len(active)
            })
        except Exception as e:
            logger.error(f"Error getting active ventilations: {e}")
            return jsonify({'error': str(e)}), 500

    @ventilation_bp.route('/ventilation/events', methods=['GET'])
    def get_ventilation_events():
        """API: Abgeschlossene Lüftungs-Events mit Statistiken"""
        try:
            room_name = request.args.get('room')
            days = request.args.get('days', 7, type=int)
            days = min(max(days, 1), 30)  # 1-30 Tage
            
            events = db.get_ventilation_events(room_name=room_name, days_back=days) if db else []
            
            return jsonify({
                'success': True,
                'events': events,
                'count': len(events),
                'room_name': room_name,
                'days': days
            })
        except Exception as e:
            logger.error(f"Error getting ventilation events: {e}")
            return jsonify({'error': str(e)}), 500

    @ventilation_bp.route('/ventilation/stats', methods=['GET'])
    def get_ventilation_stats():
        """API: Lüftungsstatistiken pro Raum"""
        try:
            days = request.args.get('days', 7, type=int)
            days = min(max(days, 1), 30)
            
            stats = db.get_ventilation_stats_by_room(days_back=days) if db else []
            
            return jsonify({
                'success': True,
                'stats': stats,
                'days': days
            })
        except Exception as e:
            logger.error(f"Error getting ventilation stats: {e}")
            return jsonify({'error': str(e)}), 500

    @ventilation_bp.route('/ventilation/learning-by-state', methods=['GET'])
    def get_ventilation_learning_by_state():
        """API: Lüftungs-Lernstatistiken nach Fensterzustand (gekippt vs offen)"""
        try:
            room_name = request.args.get('room')
            days = request.args.get('days', 30, type=int)
            days = min(max(days, 1), 90)
            
            learning_data = db.get_ventilation_learning_by_state(room_name=room_name, days_back=days) if db else []
            
            # Gruppiere nach Raum für einfachere Darstellung
            by_room = {}
            for item in learning_data:
                room = item.get('room_name', 'Unbekannt')
                if room not in by_room:
                    by_room[room] = {'tilted': None, 'open': None}
                
                state = item.get('window_state', 'open')
                by_room[room][state] = item
            
            return jsonify({
                'success': True,
                'learning_data': learning_data,
                'by_room': by_room,
                'days': days,
                'explanation': {
                    'tilted': 'Fenster gekippt - langsamer Luftaustausch, weniger Wärmeverlust',
                    'open': 'Fenster weit offen - schneller Luftaustausch, mehr Wärmeverlust'
                }
            })
        except Exception as e:
            logger.error(f"Error getting ventilation learning by state: {e}")
            return jsonify({'error': str(e)}), 500

    @ventilation_bp.route('/ventilation/optimal-by-state', methods=['GET'])
    def get_optimal_by_state():
        """API: Optimale Lüftungsdauer basierend auf Fensterzustand und Außentemperatur"""
        try:
            outdoor_temp = request.args.get('outdoor_temp', type=float)
            window_state = request.args.get('state', 'open')
            room_name = request.args.get('room')
            
            # Falls keine Außentemp angegeben, versuche sie zu ermitteln
            if outdoor_temp is None:
                mapping = _load_sensor_mapping()
                outdoor = mapping.get('outdoor_sensors', {})
                sensors = _get_all_sensors()
                
                for sensor in sensors:
                    if sensor.get('id') == outdoor.get('temperature'):
                        outdoor_temp = sensor.get('value')
                        break
            
            if outdoor_temp is None:
                return jsonify({
                    'success': False,
                    'error': 'Keine Außentemperatur verfügbar'
                }), 400
            
            # Hole Empfehlungen für beide Zustände
            tilted_recommendation = db.get_optimal_ventilation_by_state(
                outdoor_temp=outdoor_temp, 
                window_state='tilted',
                room_name=room_name
            ) if db else None
            
            open_recommendation = db.get_optimal_ventilation_by_state(
                outdoor_temp=outdoor_temp, 
                window_state='open',
                room_name=room_name
            ) if db else None
            
            return jsonify({
                'success': True,
                'outdoor_temp': outdoor_temp,
                'room': room_name,
                'recommendations': {
                    'tilted': tilted_recommendation,
                    'open': open_recommendation
                },
                'summary': _generate_ventilation_summary(tilted_recommendation, open_recommendation, outdoor_temp)
            })
        except Exception as e:
            logger.error(f"Error getting optimal ventilation by state: {e}")
            return jsonify({'error': str(e)}), 500

    @ventilation_bp.route('/ventilation/recommendation/duration', methods=['GET'])
    def get_optimal_duration():
        """API: Empfohlene Lüftungsdauer basierend auf ML-Daten"""
        try:
            # Hole aktuelle Außentemperatur
            outdoor_temp = request.args.get('outdoor_temp', type=float)
            room_name = request.args.get('room')
            
            # Falls keine Außentemp angegeben, versuche sie zu ermitteln
            if outdoor_temp is None:
                mapping = _load_sensor_mapping()
                outdoor = mapping.get('outdoor_sensors', {})
                sensors = _get_all_sensors()
                
                for sensor in sensors:
                    if sensor.get('device_id') == outdoor.get('temperature'):
                        outdoor_temp = sensor.get('current_value')
                        break
            
            if outdoor_temp is None:
                return jsonify({
                    'success': False,
                    'error': 'Keine Außentemperatur verfügbar'
                }), 400
            
            recommendation = db.get_optimal_ventilation_duration(
                outdoor_temp=outdoor_temp,
                room_name=room_name
            ) if db else None
            
            if recommendation:
                return jsonify({
                    'success': True,
                    'outdoor_temp': outdoor_temp,
                    'room_name': room_name,
                    'recommendation': {
                        'duration_minutes': recommendation['recommended_duration'],
                        'expected_temp_change': recommendation['expected_temp_change'],
                        'expected_co2_change': recommendation['expected_co2_change'],
                        'confidence': recommendation['avg_effectiveness'],
                        'sample_count': recommendation['sample_count']
                    }
                })
            else:
                # Fallback: Einfache Empfehlung basierend auf Außentemperatur
                if outdoor_temp < 0:
                    duration = 5
                elif outdoor_temp < 10:
                    duration = 10
                elif outdoor_temp < 20:
                    duration = 15
                else:
                    duration = 20
                
                return jsonify({
                    'success': True,
                    'outdoor_temp': outdoor_temp,
                    'room_name': room_name,
                    'recommendation': {
                        'duration_minutes': duration,
                        'expected_temp_change': None,
                        'expected_co2_change': None,
                        'confidence': None,
                        'sample_count': 0,
                        'is_fallback': True,
                        'message': 'Basierend auf Standardwerten (noch keine ML-Daten)'
                    }
                })
        except Exception as e:
            logger.error(f"Error getting optimal duration: {e}")
            return jsonify({'error': str(e)}), 500

    @ventilation_bp.route('/ventilation/ml/training-data', methods=['GET'])
    def get_ml_training_data():
        """API: ML-Trainingsdaten für Lüftungsoptimierung"""
        try:
            data = db.get_ventilation_ml_training_data() if db else []
            
            return jsonify({
                'success': True,
                'training_data': data,
                'sample_count': len(data),
                'ready_for_training': len(data) >= 50
            })
        except Exception as e:
            logger.error(f"Error getting ML training data: {e}")
            return jsonify({'error': str(e)}), 500

    # ==================== NEUE FENSTER-ENDPUNKTE ====================

    @ventilation_bp.route('/ventilation/window-status', methods=['GET'])
    def get_window_status():
        """API: Aktueller LIVE-Status aller Fenster direkt von Homey"""
        try:
            import re
            windows = []
            
            # === LIVE-STATUS direkt von Homey abrufen ===
            if engine and engine.platform:
                try:
                    # Hole alle Geräte frisch von Homey
                    all_devices = []
                    if hasattr(engine.platform, '_device_cache'):
                        engine.platform._refresh_device_cache()
                        cache = engine.platform._device_cache
                        if isinstance(cache, dict):
                            all_devices = list(cache.values())
                        elif isinstance(cache, list):
                            all_devices = cache
                    else:
                        states = engine.platform.get_states()
                        if isinstance(states, list):
                            all_devices = states
                    
                    # Hole Zonen-Mapping
                    zones = {}
                    try:
                        zone_list = engine.platform.get_zones() or []
                        zones = {z.get('id'): z.get('name') for z in zone_list}
                    except:
                        pass
                    
                    # Filtere nach Fenstern (keine Türen)
                    for device in all_devices:
                        if not isinstance(device, dict):
                            continue
                        
                        device_name = device.get('name', '').lower()
                        capabilities = device.get('capabilitiesObj', {})
                        
                        # Nur Fenster, keine Türen
                        is_door = ('door' in device_name or 'tür' in device_name or 
                                  'tur' in device_name or 'türe' in device_name)
                        is_window = ('window' in device_name or 'fenster' in device_name)
                        
                        if not is_door and is_window and 'alarm_contact' in capabilities:
                            device_id = device.get('id')
                            device_display_name = device.get('name', 'Unbekannt')
                            
                            # LIVE-Status direkt von Homey
                            contact_open = bool(capabilities['alarm_contact'].get('value', False))
                            
                            # Hole Tilt-Winkel (falls vorhanden)
                            tilt_value = None
                            if 'tilt' in capabilities:
                                tilt_value = capabilities['tilt'].get('value')
                            
                            # Raum aus Zone
                            room_name = None
                            zone_id = device.get('zone')
                            if zone_id and zone_id in zones:
                                room_name = zones[zone_id]
                            
                            # Fallback: Raum aus Gerätenamen extrahieren
                            if not room_name:
                                name_lower = device_display_name.lower()
                                if 'fenster' in name_lower:
                                    room_name = device_display_name.replace(' Fenster', '').replace(' fenster', '').strip()
                                else:
                                    room_name = device_display_name
                                
                                # Entferne Nummerierung (z.B. "Wohnzimmer 2" -> "Wohnzimmer")
                                if room_name:
                                    room_name = re.sub(r'\s+\d+$', '', room_name).strip()
                            
                            # Lade Fenster-Kalibrierung für diesen Raum
                            calibration = {'closed_angle': 0, 'tilted_min': 5, 'tilted_max': 45}
                            try:
                                rooms_file = Path('data/rooms.json')
                                if rooms_file.exists():
                                    with open(rooms_file, 'r') as f:
                                        rooms_data = json.load(f)
                                    calibrations = rooms_data.get('window_calibration', {})
                                    if zone_id and zone_id in calibrations:
                                        calibration = calibrations[zone_id]
                            except:
                                pass
                            
                            # Bestimme Fensterzustand (closed/tilted/open)
                            window_state = 'closed'
                            is_open = False
                            
                            if not contact_open:
                                # Kontakt geschlossen = Fenster zu
                                window_state = 'closed'
                                is_open = False
                            elif tilt_value is not None:
                                # Kontakt offen + Tilt vorhanden
                                tilted_min = calibration.get('tilted_min', 5)
                                tilted_max = calibration.get('tilted_max', 45)
                                
                                if tilt_value >= tilted_min and tilt_value <= tilted_max:
                                    window_state = 'tilted'
                                    is_open = True
                                else:
                                    window_state = 'open'
                                    is_open = True
                            else:
                                # Kontakt offen, kein Tilt-Sensor
                                window_state = 'open'
                                is_open = True
                            
                            # Wenn Fenster offen ist, hole open_since aus DB
                            open_since = None
                            if is_open and db:
                                try:
                                    conn = db._get_connection()
                                    cursor = conn.cursor()
                                    
                                    # Finde den letzten Zustandswechsel
                                    cursor.execute('''
                                        SELECT timestamp FROM window_observations
                                        WHERE device_id = ? AND is_open = 0
                                        ORDER BY timestamp DESC
                                        LIMIT 1
                                    ''', (device_id,))
                                    last_closed = cursor.fetchone()
                                    
                                    if last_closed:
                                        cursor.execute('''
                                            SELECT MIN(timestamp) FROM window_observations
                                            WHERE device_id = ? AND is_open = 1 AND timestamp > ?
                                        ''', (device_id, last_closed[0]))
                                        first_open = cursor.fetchone()
                                        if first_open and first_open[0]:
                                            open_since = first_open[0]
                                    else:
                                        cursor.execute('''
                                            SELECT MIN(timestamp) FROM window_observations
                                            WHERE device_id = ? AND is_open = 1
                                        ''', (device_id,))
                                        first_open = cursor.fetchone()
                                        if first_open and first_open[0]:
                                            open_since = first_open[0]
                                except Exception as e:
                                    logger.debug(f"Could not get open_since for {device_id}: {e}")
                            
                            # State Labels
                            state_labels = {
                                'closed': '🟢 Geschlossen',
                                'tilted': '🟡 Gekippt',
                                'open': '🔴 Offen'
                            }
                            
                            windows.append({
                                'device_id': device_id,
                                'name': device_display_name,
                                'room': room_name or 'Unbekannt',
                                'is_open': is_open,
                                'window_state': window_state,
                                'state_label': state_labels.get(window_state, window_state),
                                'tilt': tilt_value,
                                'open_since': open_since,
                                'source': 'live'  # Markiere als Live-Daten
                            })
                    
                    logger.debug(f"Got live window status for {len(windows)} windows")
                    
                except Exception as e:
                    logger.warning(f"Could not get live window status from Homey: {e}")
            
            # === FALLBACK: Aus Datenbank wenn keine Live-Daten ===
            if not windows and db:
                logger.info("Falling back to database for window status")
                conn = db._get_connection()
                cursor = conn.cursor()
                
                cursor.execute('''
                    SELECT wo.device_id, wo.device_name, wo.room_name, wo.is_open, wo.timestamp
                    FROM window_observations wo
                    INNER JOIN (
                        SELECT device_id, MAX(timestamp) as max_ts
                        FROM window_observations
                        GROUP BY device_id
                    ) latest ON wo.device_id = latest.device_id AND wo.timestamp = latest.max_ts
                    ORDER BY wo.room_name, wo.device_name
                ''')
                
                for row in cursor.fetchall():
                    device_id = row[0]
                    device_name = row[1] or row[0]
                    db_room_name = row[2]
                    is_open = bool(row[3])
                    
                    room_name = None
                    if device_name:
                        name_lower = device_name.lower()
                        if 'fenster' in name_lower:
                            room_name = device_name.replace(' Fenster', '').replace(' fenster', '').strip()
                        else:
                            room_name = device_name
                        
                        if room_name:
                            room_name = re.sub(r'\s+\d+$', '', room_name).strip()
                    
                    if db_room_name and db_room_name.strip() and db_room_name not in ('Unbekannt', 'None', 'null'):
                        room_name = db_room_name
                    
                    windows.append({
                        'device_id': device_id,
                        'name': device_name,
                        'room': room_name or 'Unbekannt',
                        'is_open': is_open,
                        'open_since': None,
                        'source': 'database'  # Markiere als DB-Daten
                    })
            
            return jsonify({
                'success': True,
                'windows': windows,
                'count': len(windows)
            })
            
        except Exception as e:
            logger.error(f"Error getting window status: {e}")
            return jsonify({'error': str(e)}), 500

    @ventilation_bp.route('/ventilation/window-events', methods=['GET'])
    def get_window_events():
        """API: Lüftungsereignisse für Frontend"""
        try:
            room = request.args.get('room')
            device_id = request.args.get('device_id')
            hours = int(request.args.get('hours', 168))  # Default: 1 Woche
            days_back = max(1, hours // 24)  # Konvertiere Stunden zu Tagen
            
            events = db.get_ventilation_events(room_name=room, days_back=days_back) if db else []
            
            # Filter nach device_id wenn angegeben
            if device_id and events:
                events = [e for e in events if e.get('device_id') == device_id or e.get('device_name') == device_id]
            
            return jsonify({
                'success': True,
                'events': events,
                'count': len(events),
                'hours': hours
            })
            
        except Exception as e:
            logger.error(f"Error getting window events: {e}")
            return jsonify({'error': str(e)}), 500

    @ventilation_bp.route('/ventilation/history', methods=['GET'])
    def get_ventilation_history():
        """API: Detaillierte Lüftungshistorie mit Klimadaten"""
        try:
            days = int(request.args.get('days', 7))
            room = request.args.get('room')
            
            if not db:
                return jsonify({'success': False, 'error': 'Database not available'}), 500
            
            # Hole alle abgeschlossenen Lüftungsereignisse
            query = """
                SELECT 
                    id,
                    device_name,
                    room_name,
                    opened_at,
                    closed_at,
                    duration_minutes,
                    temp_start,
                    temp_end,
                    temp_change,
                    humidity_start,
                    humidity_end,
                    humidity_change,
                    co2_start,
                    co2_end,
                    co2_change,
                    outdoor_temp,
                    outdoor_humidity,
                    season,
                    time_of_day,
                    effectiveness_score
                FROM ventilation_events
                WHERE closed_at IS NOT NULL
                    AND opened_at >= datetime('now', ?)
            """
            params = [f'-{days} days']
            
            if room:
                query += " AND room_name = ?"
                params.append(room)
            
            query += " ORDER BY opened_at DESC LIMIT 100"
            
            rows = db.execute(query, tuple(params))
            
            events = []
            for row in rows:
                # Berechne Zeit bis CO2 unter 600 ppm
                co2_recovery_time = None
                co2_start = row.get('co2_start')
                co2_end = row.get('co2_end')
                duration = row.get('duration_minutes') or 0
                
                if co2_start and co2_end:
                    if co2_start > 600 and co2_end <= 600:
                        # CO2 ist unter 600 gefallen - berechne geschätzte Zeit
                        if co2_start > co2_end and duration > 0:
                            co2_reduction_rate = (co2_start - co2_end) / duration  # ppm pro Minute
                            if co2_reduction_rate > 0:
                                co2_to_600 = co2_start - 600
                                co2_recovery_time = round(co2_to_600 / co2_reduction_rate)
                    elif co2_end > 600:
                        # CO2 ist noch über 600
                        co2_recovery_time = -1  # Signalisiert "nicht erreicht"
                
                events.append({
                    'id': row.get('id'),
                    'device_name': row.get('device_name'),
                    'room_name': row.get('room_name'),
                    'opened_at': row.get('opened_at'),
                    'closed_at': row.get('closed_at'),
                    'duration_minutes': row.get('duration_minutes'),
                    'temp_start': row.get('temp_start'),
                    'temp_end': row.get('temp_end'),
                    'temp_change': row.get('temp_change'),
                    'humidity_start': row.get('humidity_start'),
                    'humidity_end': row.get('humidity_end'),
                    'humidity_change': row.get('humidity_change'),
                    'co2_start': co2_start,
                    'co2_end': co2_end,
                    'co2_change': row.get('co2_change'),
                    'outdoor_temp': row.get('outdoor_temp'),
                    'outdoor_humidity': row.get('outdoor_humidity'),
                    'season': row.get('season'),
                    'time_of_day': row.get('time_of_day'),
                    'effectiveness_score': row.get('effectiveness_score'),
                    'co2_recovery_time': co2_recovery_time
                })
            
            # Berechne Statistiken
            stats = {
                'total_events': len(events),
                'avg_duration': 0,
                'avg_temp_change': 0,
                'avg_humidity_change': 0,
                'avg_co2_change': 0,
                'co2_below_600_count': 0,
                'avg_co2_recovery_time': 0
            }
            
            if events:
                durations = [e['duration_minutes'] for e in events if e['duration_minutes']]
                temp_changes = [e['temp_change'] for e in events if e['temp_change'] is not None]
                humidity_changes = [e['humidity_change'] for e in events if e['humidity_change'] is not None]
                co2_changes = [e['co2_change'] for e in events if e['co2_change'] is not None]
                co2_recovery_times = [e['co2_recovery_time'] for e in events if e['co2_recovery_time'] and e['co2_recovery_time'] > 0]
                
                stats['avg_duration'] = round(sum(durations) / len(durations), 1) if durations else 0
                stats['avg_temp_change'] = round(sum(temp_changes) / len(temp_changes), 2) if temp_changes else 0
                stats['avg_humidity_change'] = round(sum(humidity_changes) / len(humidity_changes), 1) if humidity_changes else 0
                stats['avg_co2_change'] = round(sum(co2_changes) / len(co2_changes), 0) if co2_changes else 0
                stats['co2_below_600_count'] = sum(1 for e in events if e['co2_end'] and e['co2_end'] <= 600)
                stats['avg_co2_recovery_time'] = round(sum(co2_recovery_times) / len(co2_recovery_times), 1) if co2_recovery_times else 0
            
            # Hole alle Räume für Filter
            rooms_query = "SELECT DISTINCT room_name FROM ventilation_events WHERE room_name IS NOT NULL ORDER BY room_name"
            rooms_result = db.execute(rooms_query)
            rooms = [r['room_name'] for r in rooms_result]
            
            return jsonify({
                'success': True,
                'events': events,
                'stats': stats,
                'rooms': rooms,
                'days': days
            })
            
        except Exception as e:
            logger.error(f"Error getting ventilation history: {e}")
            import traceback
            traceback.print_exc()
            return jsonify({'error': str(e)}), 500

    @ventilation_bp.route('/ventilation/effectiveness', methods=['GET'])
    def get_ventilation_effectiveness():
        """API: Effektivitätsdaten für KI-Empfehlungen"""
        try:
            if not db:
                return jsonify({'success': False, 'error': 'Database not available'}), 500
            
            effectiveness = db.get_ventilation_effectiveness_by_outdoor_temp()
            
            return jsonify({
                'success': True,
                'effectiveness': effectiveness
            })
            
        except Exception as e:
            logger.error(f"Error getting effectiveness: {e}")
            return jsonify({'error': str(e)}), 500

    return ventilation_bp

