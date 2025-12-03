"""
API Blueprint für Abwesenheits-Automatisierung
Pushover-Benachrichtigungen beim Verlassen mit Licht- und Fensterstatus
"""

from flask import Blueprint, jsonify, request
from loguru import logger
from pathlib import Path
import yaml
import requests
from datetime import datetime

absence_bp = Blueprint('absence', __name__, url_prefix='/api/automations')


def init_absence_blueprint(engine, db, config):
    """Initialisiert den Absence Blueprint"""
    
    def _get_absence_config() -> dict:
        """Lade Abwesenheits-Konfiguration"""
        config_path = Path('config/config.yaml')
        if config_path.exists():
            with open(config_path, 'r') as f:
                full_config = yaml.safe_load(f) or {}
                return full_config.get('absence', {})
        return {}
    
    def _save_absence_config(absence_config: dict):
        """Speichere Abwesenheits-Konfiguration"""
        config_path = Path('config/config.yaml')
        
        if config_path.exists():
            with open(config_path, 'r') as f:
                full_config = yaml.safe_load(f) or {}
        else:
            full_config = {}
        
        full_config['absence'] = absence_config
        
        config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(config_path, 'w') as f:
            yaml.dump(full_config, f, default_flow_style=False, allow_unicode=True)
    
    def _get_pushover_credentials() -> tuple:
        """Hole Pushover-Credentials aus Config oder Absence-Config"""
        # Zuerst Absence-spezifische Config
        absence_config = _get_absence_config()
        api_key = absence_config.get('pushover_api_key', '')
        user_key = absence_config.get('pushover_user_key', '')
        
        # Falls nicht gesetzt, versuche globale Notification Config
        if not api_key or not user_key:
            config_path = Path('config/config.yaml')
            if config_path.exists():
                with open(config_path, 'r') as f:
                    full_config = yaml.safe_load(f) or {}
                    notifications = full_config.get('notifications', {})
                    pushover = notifications.get('pushover', {})
                    if not api_key:
                        api_key = pushover.get('api_token', '')
                    if not user_key:
                        user_key = pushover.get('user_key', '')
        
        return api_key, user_key
    
    def _get_homey_config() -> tuple:
        """Hole Homey URL und Token aus Config"""
        config_path = Path('config/config.yaml')
        if config_path.exists():
            with open(config_path, 'r') as f:
                full_config = yaml.safe_load(f) or {}
                homey = full_config.get('homey', {})
                return homey.get('url', ''), homey.get('token', '')
        return '', ''
    
    def _get_device_types() -> dict:
        """Hole device_types Konfiguration aus rooms.json"""
        import json
        rooms_path = Path('data/rooms.json')
        if rooms_path.exists():
            with open(rooms_path, 'r') as f:
                rooms_data = json.load(f)
                return rooms_data.get('device_types', {})
        return {}
    
    def _get_all_lights() -> list:
        """Hole alle Lichter und deren Status (berücksichtigt device_types Ausschlüsse)"""
        lights = []
        
        try:
            from src.data_collector.homey_collector import HomeyCollector
            
            homey_url, homey_token = _get_homey_config()
            device_types = _get_device_types()
            
            if homey_url and homey_token:
                collector = HomeyCollector(homey_url, homey_token)
                devices = collector.get_all_devices()
                
                for device in devices:
                    device_id = device.get('id', '')
                    device_class = device.get('class', '').lower()
                    caps = device.get('capabilities', [])
                    
                    # Prüfe ob Gerät in device_types als "device" markiert ist (= ausschließen)
                    configured_type = device_types.get(device_id)
                    if configured_type == 'device':
                        # Explizit als "kein Licht" markiert - überspringen
                        continue
                    
                    # Prüfe ob es ein Licht ist (class=light oder hat dim capability)
                    # oder explizit als "light" konfiguriert
                    is_light = (
                        configured_type == 'light' or
                        device_class == 'light' or 
                        ('onoff' in caps and 'dim' in caps)
                    )
                    
                    if is_light:
                        cap_values = device.get('capabilitiesObj', {})
                        is_on = cap_values.get('onoff', {}).get('value', False)
                        
                        zone = device.get('zone', {})
                        room_name = zone.get('name', '') if isinstance(zone, dict) else ''
                        
                        lights.append({
                            'id': device_id,
                            'name': device.get('name', 'Unbekannt'),
                            'on': is_on,
                            'room': room_name
                        })
            else:
                logger.warning("Homey config not found for absence lights check")
                        
        except Exception as e:
            logger.error(f"Error getting lights: {e}")
        
        return lights
    
    def _get_all_windows() -> list:
        """Hole alle Fenster und deren Status"""
        windows = []
        
        try:
            from src.data_collector.homey_collector import HomeyCollector
            
            homey_url, homey_token = _get_homey_config()
            
            if homey_url and homey_token:
                collector = HomeyCollector(homey_url, homey_token)
                devices = collector.get_all_devices()
                
                for device in devices:
                    caps = device.get('capabilities', [])
                    
                    # Prüfe ob es ein Fenster/Kontaktsensor ist
                    if 'alarm_contact' in caps:
                        cap_values = device.get('capabilitiesObj', {})
                        contact_open = cap_values.get('alarm_contact', {}).get('value', False)
                        tilt_angle = cap_values.get('measure_tilt', {}).get('value')
                        
                        # Bestimme Fensterstatus
                        if not contact_open:
                            state = 'closed'
                        else:
                            # Kontakt offen - prüfe Winkel
                            if tilt_angle is not None:
                                if 5 <= tilt_angle <= 45:
                                    state = 'tilted'
                                else:
                                    state = 'open'
                            else:
                                state = 'open'
                        
                        zone = device.get('zone', {})
                        room_name = zone.get('name', '') if isinstance(zone, dict) else ''
                        
                        windows.append({
                            'id': device.get('id', ''),
                            'name': device.get('name', 'Unbekannt'),
                            'state': state,
                            'tilt_angle': tilt_angle,
                            'room': room_name
                        })
            else:
                logger.warning("Homey config not found for absence windows check")
                        
        except Exception as e:
            logger.error(f"Error getting windows: {e}")
        
        return windows
    
    def _send_pushover_notification(title: str, message: str, api_key: str, user_key: str) -> bool:
        """Sende Pushover-Benachrichtigung"""
        try:
            response = requests.post(
                'https://api.pushover.net/1/messages.json',
                data={
                    'token': api_key,
                    'user': user_key,
                    'title': title,
                    'message': message,
                    'html': 1,
                    'priority': 0
                },
                timeout=30
            )
            
            if response.status_code == 200:
                logger.info(f"Absence notification sent successfully")
                return True
            else:
                logger.error(f"Pushover error: {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"Error sending Pushover notification: {e}")
            return False
    
    def _build_absence_message(lights: list, windows: list) -> tuple:
        """Erstelle Abwesenheits-Nachricht für Pushover"""
        now = datetime.now().strftime('%H:%M')
        
        lights_on = [l for l in lights if l.get('on')]
        windows_open = [w for w in windows if w.get('state') == 'open']
        windows_tilted = [w for w in windows if w.get('state') == 'tilted']
        
        title = f"🏠 Abwesenheit geprüft ({now})"
        
        message_parts = []
        
        # Lichter
        if lights_on:
            lights_str = ', '.join([l['name'] for l in lights_on[:5]])
            if len(lights_on) > 5:
                lights_str += f" (+{len(lights_on)-5} weitere)"
            message_parts.append(f"<b>💡 Lichter AN ({len(lights_on)}):</b>\n{lights_str}")
        else:
            message_parts.append("✅ <b>Alle Lichter aus</b>")
        
        # Fenster
        if windows_open:
            windows_str = ', '.join([w['name'] for w in windows_open[:5]])
            if len(windows_open) > 5:
                windows_str += f" (+{len(windows_open)-5} weitere)"
            message_parts.append(f"<b>🔴 Fenster OFFEN ({len(windows_open)}):</b>\n{windows_str}")
        
        if windows_tilted:
            windows_str = ', '.join([w['name'] for w in windows_tilted[:5]])
            if len(windows_tilted) > 5:
                windows_str += f" (+{len(windows_tilted)-5} weitere)"
            message_parts.append(f"<b>🟡 Fenster GEKIPPT ({len(windows_tilted)}):</b>\n{windows_str}")
        
        if not windows_open and not windows_tilted:
            message_parts.append("✅ <b>Alle Fenster geschlossen</b>")
        
        # Status-Zusammenfassung
        if not lights_on and not windows_open:
            message_parts.append("\n✨ <b>Alles bereit zum Verlassen!</b>")
        
        message = '\n\n'.join(message_parts)
        
        return title, message
    
    @absence_bp.route('/absence-settings', methods=['GET'])
    def get_absence_settings():
        """Hole Abwesenheits-Einstellungen"""
        try:
            config = _get_absence_config()
            
            # Maskiere API-Keys
            safe_config = {
                'enabled': config.get('enabled', False),
                'pushover_api_key': '***' if config.get('pushover_api_key') else '',
                'pushover_user_key': '***' if config.get('pushover_user_key') else '',
                'has_credentials': bool(config.get('pushover_api_key') and config.get('pushover_user_key'))
            }
            
            return jsonify({'success': True, 'settings': safe_config})
            
        except Exception as e:
            logger.error(f"Error getting absence settings: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500
    
    @absence_bp.route('/absence-settings', methods=['POST'])
    def save_absence_settings():
        """Speichere Abwesenheits-Einstellungen"""
        try:
            data = request.get_json()
            
            # Lade existierende Config
            config = _get_absence_config()
            
            # Update nur wenn Werte gesendet wurden (nicht maskiert)
            config['enabled'] = data.get('enabled', False)
            
            if data.get('pushover_api_key') and data['pushover_api_key'] != '***':
                config['pushover_api_key'] = data['pushover_api_key']
            
            if data.get('pushover_user_key') and data['pushover_user_key'] != '***':
                config['pushover_user_key'] = data['pushover_user_key']
            
            _save_absence_config(config)
            
            return jsonify({'success': True})
            
        except Exception as e:
            logger.error(f"Error saving absence settings: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500
    
    @absence_bp.route('/absence-status', methods=['GET'])
    def get_absence_status():
        """Hole aktuellen Status für Abwesenheits-Preview"""
        try:
            lights = _get_all_lights()
            windows = _get_all_windows()
            
            return jsonify({
                'success': True,
                'lights': lights,
                'windows': windows,
                'timestamp': datetime.now().isoformat()
            })
            
        except Exception as e:
            logger.error(f"Error getting absence status: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500
    
    @absence_bp.route('/absence-test-notification', methods=['POST'])
    def test_absence_notification():
        """Sende Test-Benachrichtigung"""
        try:
            api_key, user_key = _get_pushover_credentials()
            
            if not api_key or not user_key:
                return jsonify({
                    'success': False,
                    'error': 'Pushover-Credentials nicht konfiguriert. Bitte API-Token und User-Key eingeben.'
                }), 400
            
            # Hole aktuellen Status
            lights = _get_all_lights()
            windows = _get_all_windows()
            
            # Erstelle Nachricht
            title, message = _build_absence_message(lights, windows)
            
            # Sende Benachrichtigung
            success = _send_pushover_notification(title, message, api_key, user_key)
            
            if success:
                return jsonify({'success': True, 'message': 'Benachrichtigung gesendet'})
            else:
                return jsonify({
                    'success': False,
                    'error': 'Fehler beim Senden der Benachrichtigung'
                }), 500
                
        except Exception as e:
            logger.error(f"Error sending test notification: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500
    
    @absence_bp.route('/absence-trigger', methods=['POST'])
    def trigger_absence_check():
        """Trigger Abwesenheits-Check (z.B. bei Anwesenheits-Änderung)"""
        try:
            absence_config = _get_absence_config()
            
            if not absence_config.get('enabled'):
                return jsonify({
                    'success': False,
                    'message': 'Abwesenheits-Benachrichtigungen sind deaktiviert'
                })
            
            api_key, user_key = _get_pushover_credentials()
            
            if not api_key or not user_key:
                return jsonify({
                    'success': False,
                    'error': 'Pushover-Credentials nicht konfiguriert'
                }), 400
            
            # Hole aktuellen Status
            lights = _get_all_lights()
            windows = _get_all_windows()
            
            # Erstelle und sende Nachricht
            title, message = _build_absence_message(lights, windows)
            success = _send_pushover_notification(title, message, api_key, user_key)
            
            return jsonify({
                'success': success,
                'lights_on': len([l for l in lights if l.get('on')]),
                'windows_open': len([w for w in windows if w.get('state') == 'open']),
                'windows_tilted': len([w for w in windows if w.get('state') == 'tilted'])
            })
            
        except Exception as e:
            logger.error(f"Error triggering absence check: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500
    
    return absence_bp
