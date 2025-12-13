import json
import re
import logging
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)

def get_open_info(db, device_id):
    """
    Gibt (minutes_open, open_since_timestamp) zurück.
    """
    if not db: return 0, None
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
        
        first_open = None
        if last_closed:
            cursor.execute('''
                SELECT MIN(timestamp) FROM window_observations
                WHERE device_id = ? AND is_open = 1 AND timestamp > ?
            ''', (device_id, last_closed[0]))
            first_open = cursor.fetchone()
        else:
            cursor.execute('''
                SELECT MIN(timestamp) FROM window_observations
                WHERE device_id = ? AND is_open = 1
            ''', (device_id,))
            first_open = cursor.fetchone()
            
        if first_open and first_open[0]:
            try:
                open_ts_str = first_open[0]
                open_ts = datetime.fromisoformat(open_ts_str)
                now = datetime.now()
                diff = now - open_ts
                minutes = int(diff.total_seconds() / 60)
                return minutes, open_ts_str
            except:
                return 0, None
    except Exception as e:
        logger.debug(f"Could not get open_since for {device_id}: {e}")
    return 0, None

def get_all_windows(engine, db, include_ignored=False):
    """
    Zentrale Funktion zum Abrufen aller Fenster (Homey + HA).
    Gibt eine Liste von Dictionaries zurück.
    
    :param include_ignored: Wenn True, werden auch ignorierte Fenster zurückgegeben (mit 'ignored': True)
    """
    windows = []
    
    # Lade Kalibrierungsdaten und Ignorierte Fenster
    rooms_file = Path('data/rooms.json')
    calibrations = {}
    ignored_windows = []
    try:
        if rooms_file.exists():
            with open(rooms_file, 'r') as f:
                rooms_data = json.load(f)
            calibrations = rooms_data.get('window_calibration', {})
            ignored_windows = rooms_data.get('ignored_windows', [])
    except Exception as e:
        logger.error(f"Error loading room calibration: {e}")

    # Helper check
    def is_ignored(dev_id):
        return dev_id in ignored_windows

    # === 1. Homey Fenster ===
    if hasattr(engine, 'platform'):
        try:
            devices = []
            if hasattr(engine.platform, '_device_cache'):
                engine.platform._refresh_device_cache()
                devices = list(engine.platform._device_cache.values()) if isinstance(
                    engine.platform._device_cache, dict) else []
            elif hasattr(engine.platform, 'get_states'):
                states = engine.platform.get_states() or {}
                devices = list(states.values()) if isinstance(states, dict) else states
        
            # Hole Zone-Namen
            zone_names = {}
            if hasattr(engine.platform, 'get_zones'):
                zones = engine.platform.get_zones() or {}
                zone_names = {z.get('id'): z.get('name', 'Unbekannt') for z in zones.values()} if isinstance(zones, dict) else {}
            
            for device in devices:
                name = device.get('name', '').lower()
                if 'fenster' in name or 'window' in name:
                    caps = device.get('capabilitiesObj', {})
                    zone_id = device.get('zone', '')
                    room_name = zone_names.get(zone_id, 'Unbekannt')
                    
                    # Fallback: Raum aus Gerätenamen
                    if not room_name or room_name == 'Unbekannt':
                        if 'fenster' in name:
                            room_name = device.get('name', '').replace(' Fenster', '').replace(' fenster', '').strip()
                        room_name = re.sub(r'\s+\d+$', '', room_name).strip()

                    # Status
                    is_open = False
                    if 'alarm_contact' in caps:
                        is_open = bool(caps['alarm_contact'].get('value', False))
                    
                    # Tilt
                    tilt_value = None
                    if 'tilt' in caps:
                        tilt_value = caps['tilt'].get('value', 0)
                    
                    # Kalibrierung
                    calibration = calibrations.get(zone_id, {
                        'closed_angle': 0,
                        'tilted_min': 5,
                        'tilted_max': 45
                    })
                    
                    # Zustand bestimmen
                    state = 'closed'
                    if not is_open:
                        state = 'closed'
                    elif tilt_value is not None:
                        closed_angle = calibration.get('closed_angle', 0)
                        tilted_min = calibration.get('tilted_min', 5)
                        tilted_max = 45 # Fix auf 45°
                        diff = abs(tilt_value - closed_angle)
                        
                        if diff >= tilted_min and diff <= tilted_max:
                            state = 'tilted'
                        else:
                            state = 'open'
                    else:
                        state = 'open'
                    
                    # Dauer
                    minutes_open = 0
                    open_since = None
                    if is_open:
                        minutes_open, open_since = get_open_info(db, device.get('id'))

                    dev_id = device.get('id')
                    ignored = is_ignored(dev_id)
                    
                    if not ignored or include_ignored:
                        windows.append({
                            'device_id': dev_id,
                            'device_name': device.get('name'),
                            'room_name': room_name,
                            'zone_id': zone_id,
                            'is_open': is_open,
                            'state': state,
                            'tilt': tilt_value,
                            'minutes_open': minutes_open,
                            'open_since': open_since,
                            'source': 'homey',
                            'ignored': ignored,
                            'state_label': {
                                'closed': '🟢 Geschlossen',
                                'tilted': '🟡 Gekippt',
                                'open': '🔴 Offen'
                            }.get(state, state)
                        })
        except Exception as e:
            logger.error(f"Error getting Homey windows: {e}")

    # === 2. Home Assistant Fenster ===
    try:
        ha_mapping_file = Path('config/ha_window_mapping.json')
        if ha_mapping_file.exists():
            with open(ha_mapping_file, 'r') as f:
                ha_data = json.load(f)
            
            from src.web.blueprints.api_ha_entities import get_ha_collector
            ha_collector = get_ha_collector()
            
            if ha_collector:
                for mapping in ha_data.get('mappings', {}).values():
                    if mapping.get('type', 'window') == 'window':
                        entities = mapping.get('entities', {})
                        entity_id = entities.get('contact')
                        if not entity_id:
                            continue
                            
                        room_name = mapping.get('room')
                        device_name = mapping.get('name', entity_id)
                        
                        # Get state from HA
                        ha_state = ha_collector.get_state(entity_id)
                        if ha_state:
                            state_val = ha_state.get('state')
                            is_open = state_val == 'on'
                            
                            # Tilt
                            tilt_value = None
                            tilt_entity_id = entities.get('rotation')
                            if tilt_entity_id:
                                tilt_state = ha_collector.get_state(tilt_entity_id)
                                if tilt_state:
                                    try:
                                        tilt_value = float(tilt_state.get('state'))
                                    except (ValueError, TypeError):
                                        pass
                            
                            # Zustand
                            state = 'closed'
                            if not is_open:
                                state = 'closed'
                            elif tilt_value is not None:
                                closed_angle = 0
                                tilted_min = 5
                                tilted_max = 45
                                diff = abs(tilt_value - closed_angle)
                                
                                if diff >= tilted_min and diff <= tilted_max:
                                    state = 'tilted'
                                else:
                                    state = 'open'
                            else:
                                state = 'open' if is_open else 'closed'
                            
                            # Dauer
                            minutes_open = 0
                            open_since = None
                            if is_open:
                                minutes_open, open_since = get_open_info(db, entity_id)
                            
                            ignored = is_ignored(entity_id)
                            
                            if not ignored or include_ignored:
                                windows.append({
                                    'device_id': entity_id,
                                    'device_name': device_name,
                                    'room_name': room_name,
                                    'zone_id': None,
                                    'is_open': is_open,
                                    'state': state,
                                    'tilt': tilt_value,
                                    'minutes_open': minutes_open,
                                    'open_since': open_since,
                                    'source': 'ha',
                                    'ignored': ignored,
                                    'state_label': {
                                        'closed': '🟢 Geschlossen',
                                        'tilted': '🟡 Gekippt',
                                        'open': '🔴 Offen'
                                    }.get(state, state)
                                })
    except Exception as e:
        logger.error(f"Error getting HA windows: {e}")

    # === FALLBACK: Aus Datenbank wenn keine Live-Daten ===
    if not windows and db:
        try:
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
                
                state = 'open' if is_open else 'closed'
                
                ignored = is_ignored(device_id)
                
                if not ignored or include_ignored:
                    windows.append({
                        'device_id': device_id,
                        'device_name': device_name,
                        'room_name': room_name or 'Unbekannt',
                        'zone_id': None,
                        'is_open': is_open,
                        'state': state,
                        'tilt': None,
                        'minutes_open': 0,
                        'open_since': None,
                        'source': 'database',
                        'ignored': ignored,
                        'state_label': {
                            'closed': '🟢 Geschlossen',
                            'tilted': '🟡 Gekippt',
                            'open': '🔴 Offen'
                        }.get(state, state)
                    })
        except Exception as e:
            logger.error(f"Error getting DB fallback windows: {e}")
        
    return windows
