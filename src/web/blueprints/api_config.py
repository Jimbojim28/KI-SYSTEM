"""
API Blueprint für Konfiguration
Enthält alle Endpoints für System-Konfiguration und Verbindungstests
"""

from flask import Blueprint, jsonify, request
from loguru import logger
from pathlib import Path
import yaml
import threading
import time

from .validators import validate_request, validate_json_body, Validators, FieldValidator

config_bp = Blueprint('config', __name__, url_prefix='/api')


def init_config_blueprint(engine, db, config):
    """Initialisiert den Blueprint mit Engine, Database und Config Referenzen"""
    
    @config_bp.route('/config', methods=['GET'])
    def get_config():
        """Hole aktuelle Konfiguration (maskiert sensible Daten)"""
        try:
            config_path = Path('config/config.yaml')
            
            if config_path.exists():
                with open(config_path, 'r') as f:
                    cfg = yaml.safe_load(f) or {}
            else:
                cfg = {}
            
            # Maskiere sensible Daten
            safe_config = {
                'homey': {
                    'url': cfg.get('homey', {}).get('url', ''),
                    'token': '***' if cfg.get('homey', {}).get('token') else ''
                },
                'homeassistant': {
                    'url': cfg.get('homeassistant', {}).get('url', ''),
                    'token': '***' if cfg.get('homeassistant', {}).get('token') else ''
                },
                'platforms': cfg.get('platforms', {}),
                'database': cfg.get('database', {}),
                'features': cfg.get('features', {}),
                'data_collection': cfg.get('data_collection', {})
            }
            
            return jsonify({'success': True, 'config': safe_config})
        except Exception as e:
            logger.error(f"Error getting config: {e}")
            return jsonify({'error': str(e)}), 500

    @config_bp.route('/config', methods=['POST'])
    @validate_json_body()
    def save_config():
        """Speichere Konfiguration"""
        try:
            data = request.get_json()
            config_path = Path('config/config.yaml')
            
            # Lade bestehende Config
            if config_path.exists():
                with open(config_path, 'r') as f:
                    existing_config = yaml.safe_load(f) or {}
            else:
                existing_config = {}
            
            # Update nur die gesendeten Felder (überspringe maskierte Tokens)
            def deep_update(base: dict, update: dict) -> dict:
                for key, value in update.items():
                    if isinstance(value, dict) and key in base and isinstance(base[key], dict):
                        deep_update(base[key], value)
                    elif value != '***':  # Überspringe maskierte Tokens
                        base[key] = value
                return base
            
            deep_update(existing_config, data)
            
            # Speichern
            config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(config_path, 'w') as f:
                yaml.dump(existing_config, f, default_flow_style=False, allow_unicode=True)
            
            logger.info("Configuration saved successfully")
            return jsonify({'success': True, 'message': 'Configuration saved'})
        except Exception as e:
            logger.error(f"Error saving config: {e}")
            return jsonify({'error': str(e)}), 500

    @config_bp.route('/connection/test', methods=['POST'])
    @validate_request({
        'platform': Validators.action(['homey', 'homeassistant'], required=True),
        'url': Validators.url(required=True),
        'token': Validators.token(required=False)
    })
    def test_connection():
        """Teste Verbindung zu einer Plattform"""
        try:
            import requests
            
            data = request.validated_data
            platform = data['platform']
            url = data['url']
            token = data.get('token', '')
            
            if platform == 'homey':
                test_url = f"{url}/api/manager/devices/"
                headers = {'Authorization': f'Bearer {token}'} if token else {}
            else:  # homeassistant
                test_url = f"{url}/api/"
                headers = {'Authorization': f'Bearer {token}'} if token else {}
            
            try:
                response = requests.get(test_url, headers=headers, timeout=10)
                
                if response.status_code == 200:
                    return jsonify({
                        'success': True,
                        'connected': True,
                        'message': f'Verbindung zu {platform} erfolgreich'
                    })
                elif response.status_code == 401:
                    return jsonify({
                        'success': True,
                        'connected': False,
                        'message': 'Authentifizierung fehlgeschlagen'
                    })
                else:
                    return jsonify({
                        'success': True,
                        'connected': False,
                        'message': f'HTTP {response.status_code}'
                    })
            except requests.exceptions.Timeout:
                return jsonify({
                    'success': True,
                    'connected': False,
                    'message': 'Zeitüberschreitung'
                })
            except requests.exceptions.ConnectionError:
                return jsonify({
                    'success': True,
                    'connected': False,
                    'message': 'Verbindung fehlgeschlagen'
                })
        except Exception as e:
            logger.error(f"Error testing connection: {e}")
            return jsonify({'error': str(e)}), 500

    @config_bp.route('/config/data-collection', methods=['POST'])
    @validate_json_body()
    def save_data_collection_config():
        """Speichere Datensammlungs-Konfiguration"""
        try:
            data = request.get_json()
            config_path = Path('config/config.yaml')
            
            # Lade bestehende Config
            if config_path.exists():
                with open(config_path, 'r') as f:
                    existing_config = yaml.safe_load(f) or {}
            else:
                existing_config = {}
            
            # Stelle sicher, dass data_collection existiert
            if 'data_collection' not in existing_config:
                existing_config['data_collection'] = {}
            
            # Update collect_types
            if 'collect_types' in data:
                if 'collect_types' not in existing_config['data_collection']:
                    existing_config['data_collection']['collect_types'] = {}
                existing_config['data_collection']['collect_types'].update(data['collect_types'])
            
            # Update platform_sources
            if 'platform_sources' in data:
                if 'platform_sources' not in existing_config['data_collection']:
                    existing_config['data_collection']['platform_sources'] = {}
                
                for key, value in data['platform_sources'].items():
                    if key not in existing_config['data_collection']['platform_sources']:
                        existing_config['data_collection']['platform_sources'][key] = {}
                    existing_config['data_collection']['platform_sources'][key].update(value)
            
            # Speichern
            config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(config_path, 'w') as f:
                yaml.dump(existing_config, f, default_flow_style=False, allow_unicode=True)
            
            logger.info("Data collection configuration saved successfully")
            return jsonify({'success': True, 'message': 'Configuration saved'})
        except Exception as e:
            logger.error(f"Error saving data collection config: {e}")
            return jsonify({'error': str(e)}), 500

    @config_bp.route('/system/info', methods=['GET'])
    def get_system_info():
        """Hole System-Informationen"""
        try:
            import src
            import platform
            import sys
            
            return jsonify({
                'success': True,
                'info': {
                    'version': src.__version__,
                    'python_version': sys.version,
                    'platform': platform.system(),
                    'platform_version': platform.version()
                }
            })
        except Exception as e:
            logger.error(f"Error getting system info: {e}")
            return jsonify({'error': str(e)}), 500

    return config_bp
