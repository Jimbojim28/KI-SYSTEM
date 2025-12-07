"""
Christmas Lighting API Blueprint

API-Endpunkte für die Weihnachtsbeleuchtungs-Steuerung
"""

from flask import Blueprint, jsonify, request
from loguru import logger
from pathlib import Path
import json

christmas_bp = Blueprint('christmas', __name__, url_prefix='/api/christmas')

# Globale Referenzen (werden in init_christmas_blueprint gesetzt)
_engine = None
_db = None
_config = None
_christmas_controller = None


def init_christmas_blueprint(engine, db, config, controller):
    """Initialisiere Blueprint mit Engine, Database und Config"""
    global _engine, _db, _config, _christmas_controller
    _engine = engine
    _db = db
    _config = config
    _christmas_controller = controller


@christmas_bp.route('/config', methods=['GET'])
def get_christmas_config():
    """Hole aktuelle Weihnachtsbeleuchtungs-Konfiguration"""
    try:
        if _christmas_controller:
            config = _christmas_controller.get_config()
        else:
            # Fallback: Direkt aus Datei lesen
            config_file = Path('data/christmas_config.json')
            if config_file.exists():
                with open(config_file, 'r') as f:
                    config = json.load(f)
            else:
                config = {
                    'enabled': False,
                    'on_time': '16:00',
                    'off_time': '23:00',
                    'use_sunset': False,
                    'start_date': '',
                    'end_date': '',
                    'devices': [],
                    'presence_only': False,
                    'weekend_extended': False,
                    'random_delay': True
                }
        
        return jsonify({
            'success': True,
            'config': config
        })
    except Exception as e:
        logger.error(f"Error getting christmas config: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@christmas_bp.route('/config', methods=['POST'])
def save_christmas_config():
    """Speichere Weihnachtsbeleuchtungs-Konfiguration"""
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({
                'success': False,
                'error': 'No data provided'
            }), 400
        
        # Validiere Eingaben
        config = {
            'enabled': data.get('enabled', False),
            'on_time': data.get('on_time', '16:00'),
            'off_time': data.get('off_time', '23:00'),
            'use_sunset': data.get('use_sunset', False),
            'start_date': data.get('start_date', ''),
            'end_date': data.get('end_date', ''),
            'devices': data.get('devices', []),
            'device_labels': data.get('device_labels', {}),
            'presence_only': data.get('presence_only', False),
            'weekend_extended': data.get('weekend_extended', False),
            'random_delay': data.get('random_delay', True)
        }
        
        if _christmas_controller:
            _christmas_controller.update_config(config)
        else:
            # Fallback: Direkt in Datei speichern
            config_file = Path('data/christmas_config.json')
            config_file.parent.mkdir(parents=True, exist_ok=True)
            with open(config_file, 'w') as f:
                json.dump(config, f, indent=2)
        
        logger.info(f"Christmas config saved: enabled={config['enabled']}, "
                   f"devices={len(config['devices'])}")
        
        return jsonify({
            'success': True,
            'message': 'Configuration saved'
        })
    except Exception as e:
        logger.error(f"Error saving christmas config: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@christmas_bp.route('/status', methods=['GET'])
def get_christmas_status():
    """Hole aktuellen Status der Weihnachtsbeleuchtung"""
    try:
        if _christmas_controller:
            status = _christmas_controller.get_status()
        else:
            status = {
                'enabled': False,
                'lights_on': False,
                'next_action': '--',
                'active_devices': 0,
                'last_action': None,
                'within_date_range': True
            }
        
        return jsonify({
            'success': True,
            'status': status
        })
    except Exception as e:
        logger.error(f"Error getting christmas status: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@christmas_bp.route('/test', methods=['POST'])
def test_christmas_lights():
    """Testet die Weihnachtslichter (manuell ein/aus)"""
    try:
        data = request.get_json() or {}
        # Unterstütze beide Formate: action='on'/'off' oder turn_on=true/false
        action = data.get('action', '')
        if action:
            turn_on = action.lower() == 'on'
        else:
            turn_on = data.get('turn_on', True)
        
        if _christmas_controller:
            affected = _christmas_controller.test_lights(turn_on)
            return jsonify({
                'success': True,
                'message': f"{'Eingeschaltet' if turn_on else 'Ausgeschaltet'}: {affected} Geräte",
                'affected': affected
            })
        else:
            return jsonify({
                'success': False,
                'error': 'Christmas controller not available'
            }), 503
    except Exception as e:
        logger.error(f"Error testing christmas lights: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@christmas_bp.route('/toggle-device', methods=['POST'])
def toggle_single_device():
    """Schaltet ein einzelnes Gerät ein oder aus"""
    try:
        data = request.get_json() or {}
        device_id = data.get('device_id')
        turn_on = data.get('turn_on', True)
        
        if not device_id:
            return jsonify({
                'success': False,
                'error': 'device_id required'
            }), 400
        
        if _engine and _engine.platform:
            if turn_on:
                _engine.platform.turn_on(device_id)
            else:
                _engine.platform.turn_off(device_id)
            
            return jsonify({
                'success': True,
                'device_id': device_id,
                'turned_on': turn_on
            })
        else:
            return jsonify({
                'success': False,
                'error': 'Platform not available'
            }), 503
            
    except Exception as e:
        logger.error(f"Error toggling device {data.get('device_id')}: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@christmas_bp.route('/devices', methods=['GET'])
def get_christmas_devices():
    """Hole verfügbare Geräte für Weihnachtsbeleuchtung"""
    try:
        devices = []
        christmas_zone_id = None
        christmas_zone_devices = []
        
        if not _engine:
            logger.warning("Engine not available for christmas devices")
            return jsonify({
                'success': True,
                'devices': [],
                'count': 0,
                'christmas_zone_id': None,
                'christmas_zone_devices': [],
                'warning': 'Engine not initialized'
            })
        
        if not _engine.platform:
            logger.warning("Platform not available for christmas devices")
            return jsonify({
                'success': True,
                'devices': [],
                'count': 0,
                'christmas_zone_id': None,
                'christmas_zone_devices': [],
                'warning': 'Platform not initialized'
            })
        
        # Hole Zonen (Räume) von Homey
        zones = {}
        if hasattr(_engine.platform, 'get_zones'):
            zones = _engine.platform.get_zones() or {}
            logger.debug(f"Retrieved {len(zones)} zones from platform")
        
        # Finde den "Weihnachtsbeleuchtung" Raum
        for zone_id, zone_data in zones.items():
            zone_name = zone_data.get('name', '').lower() if isinstance(zone_data, dict) else ''
            if 'weihnacht' in zone_name or 'christmas' in zone_name:
                christmas_zone_id = zone_id
                logger.debug(f"Found Christmas zone: {zone_data.get('name')} (ID: {zone_id})")
                break
        
        all_devices = _engine.platform.get_states() or []
        logger.debug(f"Retrieved {len(all_devices)} devices from platform")
        
        for device in all_devices:
            if not isinstance(device, dict):
                continue
            
            device_id = device.get('id', '')
            name = device.get('name', 'Unbekannt')
            zone = device.get('zone', '')
            
            # Filtere nur steuerbare Lichter/Steckdosen
            capabilities = device.get('capabilities', [])
            caps_obj = device.get('capabilitiesObj', {})
            
            # Prüfe ob Gerät steuerbar ist (onoff capability)
            is_controllable = (
                'onoff' in capabilities or 
                'onoff' in caps_obj or
                'switch' in name.lower() or
                'plug' in name.lower() or
                'steckdose' in name.lower()
            )
            
            # Filtere auf relevante Geräte
            device_class = device.get('class', '').lower()
            is_relevant = device_class in ['light', 'socket', 'outlet', 'plug', 'switch', '']
            
            # Markiere ob Gerät im Weihnachts-Raum ist
            is_in_christmas_zone = zone == christmas_zone_id if christmas_zone_id else False
            
            if is_controllable and is_relevant:
                # Prüfe aktuellen Zustand
                is_on = False
                if 'onoff' in caps_obj:
                    is_on = caps_obj['onoff'].get('value', False)
                
                device_info = {
                    'id': device_id,
                    'name': name,
                    'is_on': is_on,
                    'type': device_class or 'unknown',
                    'is_christmas_zone': is_in_christmas_zone
                }
                devices.append(device_info)
                
                if is_in_christmas_zone:
                    christmas_zone_devices.append(device_id)
        
        # Sortiere: Weihnachts-Raum-Geräte zuerst, dann alphabetisch
        devices.sort(key=lambda x: (not x.get('is_christmas_zone', False), x['name'].lower()))
        
        return jsonify({
            'success': True,
            'devices': devices,
            'count': len(devices),
            'christmas_zone_id': christmas_zone_id,
            'christmas_zone_devices': christmas_zone_devices
        })
    except Exception as e:
        logger.error(f"Error getting christmas devices: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@christmas_bp.route('/sync-zone', methods=['POST'])
def sync_christmas_zone():
    """Synchronisiere Geräte aus dem Homey-Raum 'Weihnachtsbeleuchtung' mit der Config"""
    try:
        christmas_zone_id = None
        christmas_devices = []
        
        # Prüfe ob Platform verfügbar ist
        if not _engine or not _engine.platform:
            return jsonify({
                'success': False,
                'error': 'Platform nicht verfügbar - Engine oder Platform nicht initialisiert'
            }), 503
        
        # Hole Zonen (Räume) von Homey
        zones = {}
        if hasattr(_engine.platform, 'get_zones'):
            zones = _engine.platform.get_zones() or {}
            logger.debug(f"Found {len(zones)} zones from Homey")
        else:
            logger.warning("Platform has no get_zones method")
        
        # Finde den "Weihnachtsbeleuchtung" Raum
        for zone_id, zone_data in zones.items():
            zone_name = zone_data.get('name', '').lower() if isinstance(zone_data, dict) else ''
            logger.debug(f"Checking zone: {zone_data.get('name', 'unknown')} (ID: {zone_id})")
            if 'weihnacht' in zone_name or 'christmas' in zone_name:
                christmas_zone_id = zone_id
                logger.info(f"Found Christmas zone: {zone_data.get('name')} (ID: {zone_id})")
                break
        
        if not christmas_zone_id:
            # Liste alle gefundenen Zonen für Debug
            zone_names = [z.get('name', 'unknown') if isinstance(z, dict) else str(z) for z in zones.values()]
            logger.warning(f"No Christmas zone found. Available zones: {zone_names}")
            return jsonify({
                'success': False,
                'error': f'Kein Raum "Weihnachtsbeleuchtung" in Homey gefunden. Verfügbare Räume: {", ".join(zone_names[:10])}'
            }), 404
        
        # Hole alle Geräte aus diesem Raum
        all_devices = _engine.platform.get_states() or []
        logger.debug(f"Total devices from platform: {len(all_devices)}")
        
        for device in all_devices:
            if not isinstance(device, dict):
                continue
            
            if device.get('zone') == christmas_zone_id:
                # Prüfe ob steuerbar
                capabilities = device.get('capabilities', [])
                caps_obj = device.get('capabilitiesObj', {})
                
                if 'onoff' in capabilities or 'onoff' in caps_obj:
                    device_id = device.get('id')
                    device_name = device.get('name', 'Unknown')
                    christmas_devices.append(device_id)
                    logger.debug(f"Added Christmas device: {device_name} (ID: {device_id})")
        
        logger.info(f"Found {len(christmas_devices)} devices in Christmas zone")
        
        # Aktualisiere Config - entweder über Controller oder direkt
        if _christmas_controller:
            config = _christmas_controller.get_config()
            config['devices'] = christmas_devices
            _christmas_controller.update_config(config)
            logger.info("Config updated via Christmas Controller")
        else:
            # Fallback: Direkt in Datei speichern (wenn Controller nicht verfügbar)
            config_file = Path('data/christmas_config.json')
            config = {}
            if config_file.exists():
                with open(config_file, 'r') as f:
                    config = json.load(f)
            
            config['devices'] = christmas_devices
            config_file.parent.mkdir(parents=True, exist_ok=True)
            with open(config_file, 'w') as f:
                json.dump(config, f, indent=2)
            logger.info("Config updated directly to file (Controller not available)")
        
        return jsonify({
            'success': True,
            'message': f'{len(christmas_devices)} Geräte aus Weihnachtsbeleuchtung-Raum synchronisiert',
            'devices': christmas_devices,
            'count': len(christmas_devices)
        })
        
    except Exception as e:
        logger.error(f"Error syncing christmas zone: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
