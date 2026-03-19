"""
API Blueprint für Benachrichtigungen (Pushover + ChatGPT)
"""

from flask import Blueprint, jsonify, request
from loguru import logger
from pathlib import Path
import yaml

notifications_bp = Blueprint('notifications', __name__, url_prefix='/api/notifications')


def init_notifications_blueprint(engine, db, config):
    """Initialisiert den Blueprint"""
    
    from src.utils.notifications import NotificationService, get_notification_service
    
    def _get_notification_config():
        """Lade Notification-Konfiguration"""
        config_path = Path('config/config.yaml')
        if config_path.exists():
            with open(config_path, 'r') as f:
                full_config = yaml.safe_load(f) or {}
                return full_config.get('notifications', {})
        return {}
    
    def _save_notification_config(notifications_config: dict):
        """Speichere Notification-Konfiguration"""
        config_path = Path('config/config.yaml')
        
        if config_path.exists():
            with open(config_path, 'r') as f:
                full_config = yaml.safe_load(f) or {}
        else:
            full_config = {}
        
        full_config['notifications'] = notifications_config
        
        config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(config_path, 'w') as f:
            yaml.dump(full_config, f, default_flow_style=False, allow_unicode=True)
    
    @notifications_bp.route('/config', methods=['GET'])
    def get_config():
        """Hole Benachrichtigungs-Konfiguration"""
        try:
            config = _get_notification_config()
            
            # Maskiere API-Keys
            safe_config = {
                'pushover': {
                    'enabled': config.get('pushover', {}).get('enabled', False),
                    'api_token': '***' if config.get('pushover', {}).get('api_token') else '',
                    'user_key': '***' if config.get('pushover', {}).get('user_key') else '',
                    'has_credentials': bool(config.get('pushover', {}).get('api_token') and config.get('pushover', {}).get('user_key'))
                },
                'openai': {
                    'enabled': config.get('openai', {}).get('enabled', False),
                    'api_key': '***' if config.get('openai', {}).get('api_key') else '',
                    'model': config.get('openai', {}).get('model', 'gpt-4o-mini'),
                    'daily_call_limit': config.get('openai', {}).get('daily_call_limit', 10),
                    'cache_ttl_seconds': config.get('openai', {}).get('cache_ttl_seconds', 3600),
                    'has_credentials': bool(config.get('openai', {}).get('api_key'))
                },
                'bundler': {
                    'window_seconds': config.get('bundler', {}).get('window_seconds', 30)
                },
                'default_priority': config.get('default_priority', 0),
                'quiet_hours_start': config.get('quiet_hours_start', '22:00'),
                'quiet_hours_end': config.get('quiet_hours_end', '07:00'),
                'chatgpt_style': config.get('chatgpt_style', 'freundlich'),
                'max_text_length': config.get('max_text_length', 100),
                'custom_prompt': config.get('custom_prompt', ''),
                'events': config.get('events', {
                    'window_open_long': {'enabled': True, 'threshold_minutes': 15},
                    'temperature_alert': {'enabled': True, 'threshold_deviation': 3},
                    'humidity_alert': {'enabled': True},
                    'co2_alert': {'enabled': True, 'threshold_ppm': 1200},
                    'ventilation_complete': {'enabled': False},
                    'morning_summary': {'enabled': False, 'time': '07:00'},
                    'mold_risk': {'enabled': True}
                })
            }
            
            return jsonify({'success': True, 'config': safe_config})
            
        except Exception as e:
            logger.error(f"Error getting notification config: {e}")
            return jsonify({'error': str(e)}), 500
    
    @notifications_bp.route('/config', methods=['POST'])
    def save_config():
        """Speichere Benachrichtigungs-Konfiguration"""
        try:
            data = request.get_json()
            
            # Lade existierende Config
            config = _get_notification_config()
            
            # Update Pushover
            if 'pushover' in data:
                if 'pushover' not in config:
                    config['pushover'] = {}
                config['pushover']['enabled'] = data['pushover'].get('enabled', False)
                
                # Nur aktualisieren wenn nicht maskiert
                if data['pushover'].get('api_token') and data['pushover']['api_token'] != '***':
                    config['pushover']['api_token'] = data['pushover']['api_token']
                if data['pushover'].get('user_key') and data['pushover']['user_key'] != '***':
                    config['pushover']['user_key'] = data['pushover']['user_key']
            
            # Update OpenAI
            if 'openai' in data:
                if 'openai' not in config:
                    config['openai'] = {}
                config['openai']['enabled'] = data['openai'].get('enabled', False)
                config['openai']['model'] = data['openai'].get('model', 'gpt-4o-mini')
                
                if data['openai'].get('api_key') and data['openai']['api_key'] != '***':
                    config['openai']['api_key'] = data['openai']['api_key']
                
                if 'daily_call_limit' in data['openai']:
                    config['openai']['daily_call_limit'] = int(data['openai']['daily_call_limit'])
                if 'cache_ttl_seconds' in data['openai']:
                    config['openai']['cache_ttl_seconds'] = int(data['openai']['cache_ttl_seconds'])
            
            # Update andere Einstellungen
            if 'default_priority' in data:
                config['default_priority'] = data['default_priority']
            if 'quiet_hours_start' in data:
                config['quiet_hours_start'] = data['quiet_hours_start']
            if 'quiet_hours_end' in data:
                config['quiet_hours_end'] = data['quiet_hours_end']
            if 'chatgpt_style' in data:
                config['chatgpt_style'] = data['chatgpt_style']
            if 'max_text_length' in data:
                config['max_text_length'] = data['max_text_length']
            if 'custom_prompt' in data:
                config['custom_prompt'] = data['custom_prompt']
            if 'events' in data:
                config['events'] = data['events']
            if 'bundler' in data:
                if 'bundler' not in config:
                    config['bundler'] = {}
                w = data['bundler'].get('window_seconds')
                if w is not None:
                    config['bundler']['window_seconds'] = max(5, min(300, int(w)))
            
            _save_notification_config(config)
            
            # Reinitialisiere Service
            global _notification_service
            from src.utils.notifications import NotificationService
            _notification_service = None  # Reset singleton
            
            logger.info("Notification configuration saved")
            return jsonify({'success': True, 'message': 'Konfiguration gespeichert'})
            
        except Exception as e:
            logger.error(f"Error saving notification config: {e}")
            return jsonify({'error': str(e)}), 500
    
    @notifications_bp.route('/test', methods=['POST'])
    def test_notification():
        """Teste Benachrichtigung senden"""
        try:
            data = request.get_json() or {}
            test_type = data.get('type', 'simple')
            
            config = _get_notification_config()
            service = NotificationService({"notifications": config})
            
            # Prüfe zuerst ob Pushover konfiguriert ist
            if not service.pushover_enabled:
                pushover_config = config.get('pushover', {})
                if not pushover_config.get('api_token'):
                    return jsonify({'success': False, 'error': 'Pushover API Token fehlt. Bitte in den Einstellungen konfigurieren.'}), 400
                if not pushover_config.get('user_key'):
                    return jsonify({'success': False, 'error': 'Pushover User Key fehlt. Bitte in den Einstellungen konfigurieren.'}), 400
                return jsonify({'success': False, 'error': 'Pushover ist nicht aktiviert.'}), 400
            
            if test_type == 'simple':
                # Einfache Test-Nachricht – sofort senden (kein Bundling)
                success, error_msg = service.send_notification_with_details(
                    title="🏠 KI Smart Home",
                    message="Test-Benachrichtigung erfolgreich! Die Pushover-Integration funktioniert.",
                    priority=0,
                    sound="pushover",
                    force_immediate=True
                )
            elif test_type == 'chatgpt':
                # Prüfe ob ChatGPT konfiguriert ist
                if not service.openai_enabled:
                    openai_config = config.get('openai', {})
                    if not openai_config.get('api_key'):
                        return jsonify({'success': False, 'error': 'OpenAI API Key fehlt. Bitte in den Einstellungen konfigurieren.'}), 400
                    return jsonify({'success': False, 'error': 'ChatGPT ist nicht aktiviert.'}), 400
                
                # Test mit ChatGPT
                success, error_msg = service.send_smart_notification_with_details(
                    event_type='morning_summary',
                    context={
                        'avg_indoor_temp': 21.5,
                        'outdoor_temp': 8.3,
                        'weather': 'bewölkt',
                        'open_windows': 0
                    },
                    style=config.get('chatgpt_style', 'freundlich'),
                    use_chatgpt=True
                )
            else:
                return jsonify({'success': False, 'error': 'Unbekannter Test-Typ'}), 400
            
            if success:
                return jsonify({'success': True, 'message': 'Test-Benachrichtigung gesendet!'})
            else:
                return jsonify({'success': False, 'error': error_msg or 'Unbekannter Fehler beim Senden.'}), 400
                
        except Exception as e:
            logger.error(f"Error testing notification: {e}")
            return jsonify({'error': str(e)}), 500
    
    @notifications_bp.route('/test-connection', methods=['GET'])
    def test_connection():
        """Teste Verbindung zu Pushover und OpenAI"""
        try:
            config = _get_notification_config()
            service = NotificationService({"notifications": config})
            result = service.test_connection()
            
            return jsonify({
                'success': True,
                'pushover': result['pushover'],
                'openai': result['openai']
            })
            
        except Exception as e:
            logger.error(f"Error testing connection: {e}")
            return jsonify({'error': str(e)}), 500
    
    @notifications_bp.route('/preview', methods=['POST'])
    def preview_text():
        """Vorschau eines ChatGPT-generierten Textes"""
        try:
            data = request.get_json()
            event_type = data.get('event_type', 'morning_summary')
            context = data.get('context', {})
            style = data.get('style', 'freundlich')
            
            config = _get_notification_config()
            service = NotificationService({"notifications": config})
            
            # Generiere Text
            generated_text = service.generate_smart_text(event_type, context, style)
            
            return jsonify({
                'success': True,
                'text': generated_text,
                'used_chatgpt': service.openai_enabled
            })
            
        except Exception as e:
            logger.error(f"Error generating preview: {e}")
            return jsonify({'error': str(e)}), 500
    
    @notifications_bp.route('/send', methods=['POST'])
    def send_notification():
        """Manuell eine Benachrichtigung senden"""
        try:
            data = request.get_json()
            
            if not data.get('title') or not data.get('message'):
                return jsonify({'error': 'Titel und Nachricht erforderlich'}), 400
            
            config = _get_notification_config()
            service = NotificationService({"notifications": config})
            
            success = service.send_notification(
                title=data['title'],
                message=data['message'],
                priority=data.get('priority', 0),
                sound=data.get('sound', 'pushover'),
                url=data.get('url'),
                url_title=data.get('url_title')
            )
            
            if success:
                return jsonify({'success': True, 'message': 'Benachrichtigung gesendet'})
            else:
                return jsonify({'success': False, 'error': 'Fehler beim Senden'}), 400
                
        except Exception as e:
            logger.error(f"Error sending notification: {e}")
            return jsonify({'error': str(e)}), 500

    @notifications_bp.route('/morning-summary', methods=['POST'])
    def send_morning_summary():
        """Sendet die Morgenzusammenfassung sofort (manueller Test)"""
        try:
            from src.background.notification_scheduler import NotificationScheduler
            
            # Erstelle temporären Scheduler
            scheduler = NotificationScheduler(engine=engine, check_interval=60)
            
            success = scheduler.send_morning_summary_now()
            
            if success:
                return jsonify({
                    'success': True, 
                    'message': 'Morgenzusammenfassung gesendet!'
                })
            else:
                return jsonify({
                    'success': False, 
                    'error': 'Fehler beim Senden. Ist Pushover konfiguriert?'
                }), 400
                
        except Exception as e:
            logger.error(f"Error sending morning summary: {e}")
            return jsonify({'error': str(e)}), 500

    @notifications_bp.route('/scheduler-status', methods=['GET'])
    def get_scheduler_status():
        """Gibt den Status des Notification Schedulers zurück"""
        try:
            from flask import current_app
            
            # Versuche Scheduler von der App zu holen
            app_instance = current_app._get_current_object()
            if hasattr(app_instance, 'smart_home_app') and hasattr(app_instance.smart_home_app, 'notification_scheduler'):
                scheduler = app_instance.smart_home_app.notification_scheduler
                if scheduler:
                    return jsonify({
                        'success': True,
                        'status': scheduler.get_status()
                    })
            
            # Fallback: Config-basierter Status
            config = _get_notification_config()
            events = config.get('events', {})
            
            return jsonify({
                'success': True,
                'status': {
                    'running': False,
                    'message': 'Scheduler nicht direkt erreichbar',
                    'scheduled_events': {
                        'morning_summary': {
                            'enabled': events.get('morning_summary', {}).get('enabled', False),
                            'time': events.get('morning_summary', {}).get('time', '07:00')
                        }
                    }
                }
            })
            
        except Exception as e:
            logger.error(f"Error getting scheduler status: {e}")
            return jsonify({'error': str(e)}), 500
    
    return notifications_bp
