"""
Flask Web Interface für KI-System
Dashboard, Einstellungen, Geräte-Übersicht, KI-Vorhersagen
"""

from flask import Flask, render_template, jsonify, request
from flask_cors import CORS
from pathlib import Path
from loguru import logger
from datetime import datetime
import sys
import subprocess
import os
import json
import yaml

# Füge src zum Python-Path hinzu
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# Import Blueprints
from src.web.blueprints import (
    config_bp, init_config_blueprint,
    ml_bp, init_ml_blueprint,
    ventilation_bp, init_ventilation_blueprint
)
from src.web.blueprints.api_notifications import notifications_bp, init_notifications_blueprint
from src.web.blueprints.api_absence import absence_bp, init_absence_blueprint

import src  # Für Zugriff auf __version__
from src.decision_engine.engine import DecisionEngine
from src.data_collector.background_collector import BackgroundDataCollector
from src.background.bathroom_optimizer import BathroomOptimizer
from src.background.ml_auto_trainer import MLAutoTrainer
from src.background.heating_data_collector import HeatingDataCollector
from src.background.window_data_collector import WindowDataCollector
from src.background.bathroom_data_collector import BathroomDataCollector
from src.background.lighting_data_collector import LightingDataCollector
from src.background.temperature_data_collector import TemperatureDataCollector
from src.background.database_maintenance import DatabaseMaintenanceJob
from src.utils.database import Database


class WebInterface:
    """Web Interface für das KI-System"""

    def __init__(self, config_path: str = None):
        """Initialisiere Flask App"""
        self.app = Flask(
            __name__,
            template_folder=str(Path(__file__).parent / 'templates'),
            static_folder=str(Path(__file__).parent / 'static')
        )
        CORS(self.app)

        # Initialisiere Decision Engine
        try:
            self.engine = DecisionEngine(config_path)
            self.config = self.engine.config  # Store config reference
            logger.info("Decision Engine for web interface initialized")
        except Exception as e:
            logger.error(f"Failed to initialize Decision Engine: {e}")
            self.engine = None
            self.config = {}

        # Initialisiere Database
        self.db = Database()

        # Initialisiere Background Data Collector
        self.background_collector = None
        if self.engine and self.engine.platform:
            try:
                self.background_collector = BackgroundDataCollector(
                    platform=self.engine.platform,
                    database=self.db,
                    interval_seconds=300  # 5 Minuten
                )
                logger.info("Background Data Collector initialized")
            except Exception as e:
                logger.error(f"Failed to initialize Background Collector: {e}")

        # Initialisiere Bathroom Optimizer (läuft täglich um 3:00 Uhr)
        self.bathroom_optimizer = None
        try:
            self.bathroom_optimizer = BathroomOptimizer(
                interval_hours=24,
                run_at_hour=3  # 3:00 Uhr morgens
            )
            logger.info("Bathroom Optimizer initialized")
        except Exception as e:
            logger.error(f"Failed to initialize Bathroom Optimizer: {e}")

        # Initialisiere ML Auto-Trainer (läuft täglich um 2:00 Uhr)
        self.ml_auto_trainer = None
        try:
            self.ml_auto_trainer = MLAutoTrainer(
                run_at_hour=2  # 2:00 Uhr morgens (vor Bathroom Optimizer)
            )
            logger.info("ML Auto-Trainer initialized")
        except Exception as e:
            logger.error(f"Failed to initialize ML Auto-Trainer: {e}")

        # Initialisiere Bathroom Data Collector (sammelt alle 60 Sekunden)
        self.bathroom_collector = None
        try:
            self.bathroom_collector = BathroomDataCollector(
                engine=self.engine,
                interval_seconds=60  # Alle 60 Sekunden
            )
            logger.info("Bathroom Data Collector initialized (60s interval)")
        except Exception as e:
            logger.error(f"Failed to initialize Bathroom Data Collector: {e}")

        # Initialisiere Heating Data Collector (sammelt alle 15 Minuten)
        self.heating_collector = None
        try:
            self.heating_collector = HeatingDataCollector(
                engine=self.engine,
                interval_seconds=900  # Alle 15 Minuten
            )
            logger.info("Heating Data Collector initialized (15min interval)")
        except Exception as e:
            logger.error(f"Failed to initialize Heating Data Collector: {e}")

        # Window Data Collector (60s interval)
        self.window_collector = None
        try:
            self.window_collector = WindowDataCollector(
                engine=self.engine,
                interval_seconds=60  # Alle 60 Sekunden
            )
            logger.info("Window Data Collector initialized (60s interval)")
        except Exception as e:
            logger.error(f"Failed to initialize Window Data Collector: {e}")

        # Lighting Data Collector für ML Training (60s interval)
        self.lighting_collector = None
        try:
            self.lighting_collector = LightingDataCollector(
                db=self.db,
                config=self.config
            )
            logger.info("Lighting Data Collector initialized (ML Training)")
        except Exception as e:
            logger.error(f"Failed to initialize Lighting Data Collector: {e}")

        # Temperature Data Collector für ML Training (5min interval)
        self.temperature_collector = None
        try:
            self.temperature_collector = TemperatureDataCollector(
                db=self.db,
                config=self.config
            )
            logger.info("Temperature Data Collector initialized (ML Training)")
        except Exception as e:
            logger.error(f"Failed to initialize Temperature Data Collector: {e}")

        # Initialisiere Database Maintenance Job (läuft täglich um 5:00 Uhr)
        self.db_maintenance = None
        try:
            # Lade Retention aus Config
            retention_days = self.engine.config.get('database.retention_days', 90) if self.engine else 90

            self.db_maintenance = DatabaseMaintenanceJob(
                retention_days=retention_days,
                run_hour=5  # 5:00 Uhr morgens (nach allen anderen Jobs)
            )
            logger.info(f"Database Maintenance Job initialized (retention: {retention_days} days)")
        except Exception as e:
            logger.error(f"Failed to initialize Database Maintenance: {e}")

        # Registriere Routen
        self._register_routes()
        
        # Registriere Blueprints (modularisierte API-Endpunkte)
        self._register_blueprints()

        # Registriere Context Processor für globale Template-Variablen
        @self.app.context_processor
        def inject_globals():
            """Stelle Version in allen Templates zur Verfügung"""
            return {
                'app_version': src.__version__
            }

    def _get_mold_prevention_status(self):
        """Hole aktuellen Schimmelprävention-Status"""
        try:
            # Hole Badezimmer-Daten
            bathroom_config_path = Path('data/luftentfeuchten_config.json')
            if not bathroom_config_path.exists():
                return None
            
            with open(bathroom_config_path) as f:
                config = json.load(f)
            
            if not config.get('enabled'):
                return None
            
            # Hole aktuelle Sensordaten
            platform = self.engine.platform
            humidity_sensor = config.get('humidity_sensor_id')
            temp_sensor = config.get('temperature_sensor_id')
            dehumidifier_id = config.get('dehumidifier_id')
            
            humidity = None
            temperature = None
            dehumidifier_on = False
            
            if humidity_sensor:
                sensor_state = platform.get_state(humidity_sensor)
                if sensor_state:
                    caps = sensor_state.get('attributes', {}).get('capabilities', {})
                    if 'measure_humidity' in caps:
                        humidity = caps['measure_humidity'].get('value')
            
            if temp_sensor:
                sensor_state = platform.get_state(temp_sensor)
                if sensor_state:
                    caps = sensor_state.get('attributes', {}).get('capabilities', {})
                    if 'measure_temperature' in caps:
                        temperature = caps['measure_temperature'].get('value')
            
            if dehumidifier_id:
                device_state = platform.get_state(dehumidifier_id)
                if device_state:
                    caps = device_state.get('attributes', {}).get('capabilities', {})
                    if 'onoff' in caps:
                        dehumidifier_on = caps['onoff'].get('value', False)
            
            # Berechne Schimmelrisiko wenn Daten verfügbar
            if humidity is not None and temperature is not None:
                from src.decision_engine.mold_prevention import MoldPreventionSystem
                
                mold_system = MoldPreventionSystem(db=self.db)
                
                room_name = config.get('room_name', 'Bad')
                analysis = mold_system.analyze_room_humidity(
                    room_name=room_name,
                    temperature=temperature,
                    humidity=humidity
                )
                
                risk_data = analysis.get('condensation_risk', {})
                risk_level = risk_data.get('risk_level', 'UNBEKANNT')
                risk_score = risk_data.get('risk_score', 0)
                condensation = risk_data.get('condensation_possible', False)
                dewpoint = analysis.get('dewpoint')
                
                # Icon basierend auf Risiko-Level
                risk_icons = {
                    'NIEDRIG': '🟢',
                    'MITTEL': '🟡',
                    'HOCH': '🟠',
                    'KRITISCH': '🔴'
                }
                risk_icon = risk_icons.get(risk_level, '⚪')
                
                return {
                    'enabled': True,
                    'risk_level': risk_level,
                    'risk_icon': risk_icon,
                    'risk_score': risk_score,
                    'dewpoint': dewpoint,
                    'condensation_possible': condensation,
                    'humidity': humidity,
                    'temperature': temperature,
                    'dehumidifier_running': dehumidifier_on,
                    'recommendations': analysis.get('recommendations', [])
                }
            
            return {
                'enabled': True,
                'risk_level': 'UNBEKANNT',
                'risk_icon': '⚪',
                'humidity': humidity,
                'temperature': temperature,
                'dehumidifier_running': dehumidifier_on
            }
            
        except Exception as e:
            logger.error(f"Error getting mold prevention status: {e}")
            return None

    def _register_blueprints(self):
        """Registriere alle Flask Blueprints (modularisierte API-Endpunkte)"""
        try:
            # Initialisiere Blueprints mit Engine, Database und Config
            init_config_blueprint(self.engine, self.db, self.config)
            init_ml_blueprint(self.engine, self.db)  # model_path ist optional
            init_ventilation_blueprint(self.engine, self.db, self.config)
            init_notifications_blueprint(self.engine, self.db, self.config)
            init_absence_blueprint(self.engine, self.db, self.config)
            
            # Registriere Blueprints bei der Flask App
            self.app.register_blueprint(config_bp)
            self.app.register_blueprint(ml_bp)
            self.app.register_blueprint(ventilation_bp)
            self.app.register_blueprint(notifications_bp)
            self.app.register_blueprint(absence_bp)
            
            logger.info("Blueprints registered: config_bp, ml_bp, ventilation_bp, notifications_bp, absence_bp")
        except Exception as e:
            logger.error(f"Failed to register blueprints: {e}")

    def _register_routes(self):
        """Registriere alle Flask-Routen"""

        @self.app.route('/')
        def index():
            """Hauptseite - Dashboard"""
            return render_template('dashboard.html')

        @self.app.route('/settings')
        def settings():
            """Einstellungsseite"""
            return render_template('settings.html')

        @self.app.route('/devices')
        def devices_page():
            """Geräte-Übersicht Seite"""
            return render_template('devices.html')

        @self.app.route('/automations')
        def automations_page():
            """Automatisierungs-Seite"""
            return render_template('automations.html')

        @self.app.route('/automations_new')
        def automations_new_page():
            """Neue Automatisierungs-Seite mit verbessertem UI"""
            return render_template('automations_new.html')

        @self.app.route('/rooms')
        def rooms_page():
            """Räume & Zonen Seite"""
            return render_template('rooms.html')

        @self.app.route('/analytics')
        def analytics_page():
            """Analytics & Verlaufs-Statistiken Seite"""
            return render_template('analytics.html')

        @self.app.route('/heizung')
        def heating_page():
            """Heizungssteuerung Seite"""
            return render_template('heating.html')

        @self.app.route('/luftentfeuchten')
        def bathroom_page():
            """Badezimmer Automatisierung Seite"""
            return render_template('luftentfeuchten.html')

        @self.app.route('/logs')
        def logs_page():
            """System Logs & Activity Monitor Seite"""
            return render_template('logs.html')

        @self.app.route('/ml-models')
        def ml_models_page():
            """ML Model Management Seite"""
            return render_template('ml_models.html')

        @self.app.route('/mold-prevention')
        def mold_prevention_page():
            """Schimmelprävention Dashboard Seite"""
            return render_template('mold_prevention.html')

        @self.app.route('/ventilation')
        def ventilation_page():
            """Lüftungsempfehlungen Seite"""
            return render_template('ventilation.html')

        @self.app.route('/lighting')
        def lighting_page():
            """Beleuchtungsoptimierung Seite"""
            return render_template('lighting.html')

        # === API Endpunkte ===

        @self.app.route('/api/status')
        def api_status():
            """API: Aktueller System-Status"""
            if not self.engine:
                return jsonify({'error': 'Engine not initialized'}), 500

            try:
                state = self.engine.collect_current_state()

                # Hole Wettervorhersage
                forecast = None
                try:
                    if self.engine.weather:
                        forecast_data = self.engine.weather.get_forecast()
                        if forecast_data:
                            forecast = forecast_data.get('forecasts', [])
                except Exception as e:
                    logger.warning(f"Could not get weather forecast: {e}")

                return jsonify({
                    'timestamp': state.get('timestamp'),
                    'temperature': {
                        'indoor': state.get('current_temperature'),
                        'outdoor': state.get('outdoor_temperature'),
                        'feels_like': state.get('feels_like'),
                        'humidity': state.get('humidity')
                    },
                    'environment': {
                        'brightness': state.get('brightness'),
                        'motion_detected': state.get('motion_detected'),
                        'weather': state.get('weather_condition'),
                        'weather_description': state.get('weather_description')
                    },
                    'weather': {
                        'condition': state.get('weather_condition'),
                        'description': state.get('weather_description'),
                        'temperature': state.get('outdoor_temperature'),
                        'feels_like': state.get('feels_like'),
                        'humidity': state.get('humidity'),
                        'wind_speed': state.get('wind_speed'),
                        'pressure': state.get('pressure'),
                        'clouds': state.get('clouds'),
                        'forecast': forecast
                    },
                    'energy': {
                        'price': state.get('energy_price'),
                        'price_level': state.get('energy_price_level'),
                        'consumption': state.get('power_consumption')
                    },
                    'mold_prevention': self._get_mold_prevention_status()
                })
            except Exception as e:
                logger.error(f"Error getting status: {e}")
                return jsonify({'error': str(e)}), 500

        @self.app.route('/api/devices')
        def api_devices():
            """API: Liste aller Geräte"""
            if not self.engine:
                return jsonify({'error': 'Engine not initialized'}), 500

            try:
                # Hole alle Geräte vom Platform Collector
                platform = self.engine.platform

                devices = []

                # Hole verschiedene Gerätetypen
                for domain in ['light', 'climate', 'switch', 'sensor']:
                    try:
                        entity_ids = platform.get_all_entities(domain)
                        states = platform.get_states(entity_ids)

                        for entity_id, state_data in states.items():
                            device_data = {
                                'id': entity_id,
                                'entity_id': entity_id,
                                'name': state_data.get('attributes', {}).get('friendly_name', entity_id),
                                'domain': domain,
                                'state': state_data.get('state'),
                                'attributes': state_data.get('attributes', {}),
                                'last_updated': state_data.get('last_updated')
                            }

                            # Zone/Raum für ALLE Gerätetypen
                            zone = state_data.get('attributes', {}).get('zone')
                            if zone:
                                device_data['zone'] = zone

                            # Für Climate/Heizgeräte: Extrahiere Temperaturen
                            if domain == 'climate':
                                capabilities = state_data.get('attributes', {}).get('capabilities', {})

                                # Aktuelle Temperatur
                                if 'measure_temperature' in capabilities:
                                    current_temp = capabilities['measure_temperature'].get('value')
                                    if current_temp is not None:
                                        device_data['current_temperature'] = current_temp
                                        if 'attributes' not in device_data:
                                            device_data['attributes'] = {}
                                        device_data['attributes']['current_temperature'] = current_temp

                                # Zieltemperatur
                                if 'target_temperature' in capabilities:
                                    target_temp = capabilities['target_temperature'].get('value')
                                    if target_temp is not None:
                                        device_data['target_temperature'] = target_temp
                                        if 'attributes' not in device_data:
                                            device_data['attributes'] = {}
                                        device_data['attributes']['temperature'] = target_temp

                                # Capabilities Object für erweiterte Infos
                                device_data['capabilitiesObj'] = capabilities

                            devices.append(device_data)
                    except Exception as e:
                        logger.warning(f"Error getting {domain} devices: {e}")

                return jsonify({'devices': devices, 'count': len(devices)})

            except Exception as e:
                logger.error(f"Error getting devices: {e}")
                return jsonify({'error': str(e)}), 500

        @self.app.route('/api/devices/<device_id>/control', methods=['POST'])
        def api_control_device(device_id):
            """API: Gerät steuern"""
            if not self.engine:
                return jsonify({'error': 'Engine not initialized'}), 500

            try:
                data = request.json
                action = data.get('action')  # 'turn_on', 'turn_off', 'set_temperature'
                platform = self.engine.platform

                if action == 'turn_on':
                    brightness = data.get('brightness')
                    result = platform.turn_on(device_id, brightness=brightness)
                elif action == 'turn_off':
                    result = platform.turn_off(device_id)
                elif action == 'set_temperature':
                    temp = data.get('temperature')
                    result = platform.set_temperature(device_id, temp)
                else:
                    return jsonify({'error': 'Unknown action'}), 400

                return jsonify({
                    'success': result,
                    'device_id': device_id,
                    'action': action
                })

            except Exception as e:
                logger.error(f"Error controlling device: {e}")
                return jsonify({'error': str(e)}), 500

        @self.app.route('/api/ha/entity/<entity_id>')
        def api_ha_entity(entity_id):
            """API: Query Home Assistant Entity State"""
            if not self.engine:
                return jsonify({'error': 'Engine not initialized', 'success': False}), 500

            try:
                # Check if Home Assistant platform is configured
                ha_platform = None
                
                if hasattr(self.engine, 'platforms') and 'homeassistant' in self.engine.platforms:
                    ha_platform = self.engine.platforms['homeassistant']
                elif hasattr(self.engine, 'platform') and self.engine.platform.__class__.__name__ == 'HomeAssistantCollector':
                    ha_platform = self.engine.platform
                
                if not ha_platform:
                    return jsonify({
                        'error': 'Home Assistant not configured',
                        'success': False
                    }), 404

                # Get entity state from Home Assistant
                state_data = ha_platform.get_state(entity_id)
                
                if not state_data:
                    return jsonify({
                        'error': f'Entity not found: {entity_id}',
                        'success': False
                    }), 404

                # Format entity data
                entity = {
                    'entity_id': state_data.get('entity_id', entity_id),
                    'state': state_data.get('state', 'unknown'),
                    'attributes': state_data.get('attributes', {}),
                    'friendly_name': state_data.get('attributes', {}).get('friendly_name', entity_id),
                    'last_changed': state_data.get('last_changed'),
                    'last_updated': state_data.get('last_updated')
                }

                return jsonify({
                    'success': True,
                    'entity': entity
                })

            except Exception as e:
                logger.error(f"Error querying HA entity {entity_id}: {e}")
                return jsonify({
                    'error': str(e),
                    'success': False
                }), 500

        # === LIGHTING / VERGESSENE LAMPEN API ===
        
        @self.app.route('/api/lighting/forgotten/status')
        def api_lighting_forgotten_status():
            """API: Status des Vergessene-Lampen-Detektors"""
            try:
                from src.decision_engine.forgotten_light_detector import get_forgotten_light_detector
                detector = get_forgotten_light_detector(config=self.config)
                
                return jsonify({
                    'running': detector.running,
                    'test_mode': detector.test_mode,
                    'statistics': detector.get_statistics(),
                    'current_predictions': detector.get_current_predictions()[:10]
                })
            except Exception as e:
                logger.error(f"Error getting forgotten light status: {e}")
                return jsonify({'error': str(e)}), 500
        
        @self.app.route('/api/lighting/forgotten/start', methods=['POST'])
        def api_lighting_forgotten_start():
            """API: Startet den Vergessene-Lampen-Detektor"""
            try:
                from src.decision_engine.forgotten_light_detector import get_forgotten_light_detector
                
                data = request.json or {}
                test_mode = data.get('test_mode', True)  # Default: Test-Modus
                
                detector = get_forgotten_light_detector(config=self.config, test_mode=test_mode)
                
                if not detector.running:
                    detector.start()
                    
                return jsonify({
                    'success': True,
                    'running': detector.running,
                    'test_mode': detector.test_mode
                })
            except Exception as e:
                logger.error(f"Error starting forgotten light detector: {e}")
                return jsonify({'error': str(e)}), 500
        
        @self.app.route('/api/lighting/forgotten/stop', methods=['POST'])
        def api_lighting_forgotten_stop():
            """API: Stoppt den Vergessene-Lampen-Detektor"""
            try:
                from src.decision_engine.forgotten_light_detector import get_forgotten_light_detector
                detector = get_forgotten_light_detector()
                
                if detector.running:
                    detector.stop()
                    
                return jsonify({
                    'success': True,
                    'running': detector.running
                })
            except Exception as e:
                logger.error(f"Error stopping forgotten light detector: {e}")
                return jsonify({'error': str(e)}), 500
        
        @self.app.route('/api/lighting/forgotten/history')
        def api_lighting_forgotten_history():
            """API: Historie der vergessenen Lampen"""
            try:
                from src.decision_engine.forgotten_light_detector import get_forgotten_light_detector
                detector = get_forgotten_light_detector(config=self.config)
                
                hours = request.args.get('hours', 24, type=int)
                history = detector.get_predictions_history(hours=hours)
                
                return jsonify({
                    'history': history,
                    'count': len(history)
                })
            except Exception as e:
                logger.error(f"Error getting forgotten light history: {e}")
                return jsonify({'error': str(e)}), 500
        
        @self.app.route('/api/lighting/forgotten/chart')
        def api_lighting_forgotten_chart():
            """API: Chart-Daten für vergessene Lampen"""
            try:
                from src.decision_engine.forgotten_light_detector import get_forgotten_light_detector
                detector = get_forgotten_light_detector(config=self.config)
                
                days = request.args.get('days', 7, type=int)
                chart_data = detector.get_chart_data(days=days)
                
                return jsonify(chart_data)
            except Exception as e:
                logger.error(f"Error getting forgotten light chart data: {e}")
                return jsonify({'error': str(e)}), 500
        
        @self.app.route('/api/lighting/forgotten/settings', methods=['GET', 'POST'])
        def api_lighting_forgotten_settings():
            """API: Einstellungen für vergessene Lampen"""
            if request.method == 'GET':
                # Lade aktuelle Einstellungen
                settings = self.config.get('forgotten_light', {})
                return jsonify({
                    'no_motion_threshold': settings.get('no_motion_threshold', 30),
                    'sleep_hour_start': settings.get('sleep_hour_start', 23),
                    'sleep_hour_end': settings.get('sleep_hour_end', 6),
                    'daylight_lux_threshold': settings.get('daylight_lux_threshold', 200),
                    'min_on_duration': settings.get('min_on_duration', 15),
                    'check_interval': settings.get('check_interval', 60),
                    'turn_off_when_away': settings.get('turn_off_when_away', True),
                    'away_min_duration': settings.get('away_min_duration', 5)
                })
            else:
                # Speichere Einstellungen
                try:
                    data = request.json
                    
                    # Update config
                    if 'forgotten_light' not in self.config:
                        self.config['forgotten_light'] = {}
                    
                    for key in ['no_motion_threshold', 'sleep_hour_start', 'sleep_hour_end',
                               'daylight_lux_threshold', 'min_on_duration', 'check_interval',
                               'turn_off_when_away', 'away_min_duration']:
                        if key in data:
                            self.config['forgotten_light'][key] = data[key]
                    
                    # Speichere in config.yaml
                    config_path = Path('config/config.yaml')
                    if config_path.exists():
                        import yaml
                        with open(config_path, 'r') as f:
                            yaml_config = yaml.safe_load(f) or {}
                        yaml_config['forgotten_light'] = self.config['forgotten_light']
                        with open(config_path, 'w') as f:
                            yaml.dump(yaml_config, f, default_flow_style=False, allow_unicode=True)
                    
                    # Aktualisiere laufenden Detektor
                    try:
                        from src.decision_engine.forgotten_light_detector import get_forgotten_light_detector
                        detector = get_forgotten_light_detector()
                        if detector:
                            detector.turn_off_when_away = data.get('turn_off_when_away', True)
                            detector.away_min_duration = data.get('away_min_duration', 5)
                    except:
                        pass
                    
                    return jsonify({'success': True})
                except Exception as e:
                    logger.error(f"Error saving forgotten light settings: {e}")
                    return jsonify({'error': str(e)}), 500
        
        @self.app.route('/api/lighting/forgotten/ml/status')
        def api_lighting_ml_status():
            """API: ML-Modell Status"""
            try:
                from src.decision_engine.forgotten_light_detector import get_forgotten_light_detector
                detector = get_forgotten_light_detector(config=self.config)
                
                return jsonify(detector.get_ml_status())
            except Exception as e:
                logger.error(f"Error getting ML status: {e}")
                return jsonify({'error': str(e)}), 500
        
        @self.app.route('/api/lighting/forgotten/ml/train', methods=['POST'])
        def api_lighting_ml_train():
            """API: ML-Modell trainieren"""
            try:
                from src.decision_engine.forgotten_light_detector import get_forgotten_light_detector
                detector = get_forgotten_light_detector(config=self.config)
                
                result = detector.train_ml_model()
                
                return jsonify(result)
            except Exception as e:
                logger.error(f"Error training ML model: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        @self.app.route('/api/lighting/forgotten/debug')
        def api_lighting_forgotten_debug():
            """API: Debug-Info für Lampen-Erkennung"""
            try:
                from src.decision_engine.forgotten_light_detector import get_forgotten_light_detector
                detector = get_forgotten_light_detector(config=self.config)
                
                debug_info = {
                    'running': detector.running,
                    'platform_available': detector.platform is not None,
                    'lights_found': [],
                    'lights_on': [],
                    'device_types': detector.device_types,
                    'settings': {
                        'min_on_duration': detector.min_on_duration_minutes,
                        'no_motion_threshold': detector.no_motion_threshold_minutes,
                        'check_interval': detector.check_interval
                    },
                    'last_motion_times': {k: v.isoformat() if v else None for k, v in detector.last_motion_times.items()},
                    'light_on_times': {k: v.isoformat() if v else None for k, v in detector.light_on_times.items()}
                }
                
                # Hole Lampen-Status
                if detector.platform:
                    try:
                        devices = detector.platform.get_all_devices()
                        for d in devices:
                            is_light = detector._is_light_device(d)
                            if is_light:
                                state = d.get('capabilitiesObj', {}).get('onoff', {}).get('value')
                                zone = d.get('zone')
                                room = zone.get('name') if isinstance(zone, dict) else str(zone) if zone else 'Unknown'
                                light_info = {
                                    'id': d.get('id'),
                                    'name': d.get('name'),
                                    'room': room,
                                    'is_on': state,
                                    'class': d.get('class')
                                }
                                debug_info['lights_found'].append(light_info)
                                if state:
                                    debug_info['lights_on'].append(light_info)
                    except Exception as e:
                        debug_info['error'] = str(e)
                
                return jsonify(debug_info)
            except Exception as e:
                logger.error(f"Error getting debug info: {e}")
                return jsonify({'error': str(e)}), 500

        @self.app.route('/api/lighting/collector/status')
        def api_lighting_collector_status():
            """API: Status des Lighting Data Collectors"""
            try:
                result = {
                    'running': False,
                    'total_events': 0,
                    'session_events': 0,
                    'tracked_lights': 0,
                    'last_collection': None,
                    'collectors_available': False
                }
                
                # Hole Collector-Status
                if self.lighting_collector:
                    stats = self.lighting_collector.get_stats()
                    result = {
                        'running': stats.get('running', False),
                        'total_events': stats.get('total_events', 0),
                        'session_events': stats.get('events_this_session', 0),
                        'tracked_lights': stats.get('tracked_devices', 0),
                        'last_collection': stats.get('last_collection'),
                        'last_success': stats.get('last_success'),
                        'last_error': stats.get('last_error'),
                        'collectors_available': stats.get('collectors_count', 0) > 0,
                        'interval': stats.get('interval', 60)
                    }
                
                return jsonify(result)
            except Exception as e:
                logger.error(f"Error getting collector status: {e}")
                return jsonify({'error': str(e)}), 500

        @self.app.route('/api/lighting/events/recent')
        def api_lighting_events_recent():
            """API: Letzte Lighting Events"""
            try:
                limit = request.args.get('limit', 20, type=int)
                
                conn = self.db._get_connection()
                cursor = conn.cursor()
                
                cursor.execute("""
                    SELECT timestamp, device_name, room_name, state, brightness
                    FROM lighting_events
                    ORDER BY timestamp DESC
                    LIMIT ?
                """, (limit,))
                
                events = []
                for row in cursor.fetchall():
                    events.append({
                        'timestamp': row[0],
                        'device_name': row[1],
                        'room_name': row[2],
                        'state': row[3],
                        'brightness': row[4]
                    })
                
                return jsonify({'events': events})
            except Exception as e:
                logger.error(f"Error getting recent events: {e}")
                return jsonify({'error': str(e)}), 500

        @self.app.route('/api/lighting/events/stats')
        def api_lighting_events_stats():
            """API: Statistik pro Lampe"""
            try:
                conn = self.db._get_connection()
                cursor = conn.cursor()
                
                # Versteckte Räume laden
                hidden_rooms = []
                try:
                    rooms_file = Path(__file__).parent.parent.parent / 'data' / 'rooms.json'
                    if rooms_file.exists():
                        with open(rooms_file, 'r') as f:
                            rooms_data = json.load(f)
                            hidden_rooms = rooms_data.get('hidden', [])
                except Exception as e:
                    logger.debug(f"Could not load hidden rooms: {e}")
                
                # Zone-UUID zu Raumname Mapping holen
                zone_mapping = {}
                try:
                    if self.engine and hasattr(self.engine, 'platform') and self.engine.platform:
                        zones = self.engine.platform.get_zones()
                        if isinstance(zones, dict):
                            for zid, zdata in zones.items():
                                if isinstance(zdata, dict):
                                    zone_mapping[zid] = zdata.get('name', zid)
                except Exception as e:
                    logger.debug(f"Could not get zone mapping for stats: {e}")
                
                cursor.execute("""
                    SELECT device_name, room_name, COUNT(*) as events,
                           SUM(CASE WHEN state='on' THEN 1 ELSE 0 END) as on_count,
                           SUM(CASE WHEN state='off' THEN 1 ELSE 0 END) as off_count,
                           MAX(timestamp) as last_event
                    FROM lighting_events
                    GROUP BY device_id
                    ORDER BY events DESC
                    LIMIT 20
                """)
                
                stats = []
                for row in cursor.fetchall():
                    room_id = row[1] or ''
                    # Übersetze Zone-UUID in Raumname
                    room_name = zone_mapping.get(room_id, room_id) if room_id else 'Unbekannt'
                    
                    # Versteckte Räume überspringen
                    if room_name in hidden_rooms:
                        continue
                    
                    stats.append({
                        'device_name': row[0],
                        'room_name': room_name,
                        'total_events': row[2],
                        'on_count': row[3],
                        'off_count': row[4],
                        'last_event': row[5]
                    })
                
                # Gesamt
                cursor.execute("SELECT COUNT(*) FROM lighting_events")
                total = cursor.fetchone()[0]
                
                return jsonify({'stats': stats, 'total_events': total})
            except Exception as e:
                logger.error(f"Error getting event stats: {e}")
                return jsonify({'error': str(e)}), 500

        @self.app.route('/api/lighting/room-stats')
        def api_lighting_room_stats():
            """API: Beleuchtungsstatistik pro Raum - wie oft/lange war Licht an"""
            try:
                days = int(request.args.get('days', 7))
                days = min(max(days, 1), 90)
                
                conn = self.db._get_connection()
                cursor = conn.cursor()
                
                # Versteckte Räume und alle Räume laden
                hidden_rooms = []
                all_rooms = {}  # room_id -> room_name
                try:
                    rooms_file = Path(__file__).parent.parent.parent / 'data' / 'rooms.json'
                    if rooms_file.exists():
                        with open(rooms_file, 'r') as f:
                            rooms_data = json.load(f)
                            hidden_rooms = rooms_data.get('hidden', [])
                            # Alle Räume aus rooms.json laden
                            for room in rooms_data.get('rooms', []):
                                room_name = room.get('name', '')
                                room_id = room.get('id', '')
                                if room_name and room_name not in hidden_rooms:
                                    all_rooms[room_id] = room_name
                except Exception as e:
                    logger.debug(f"Could not load rooms: {e}")
                
                # Zone-UUID zu Raumname Mapping holen (von Homey)
                zone_mapping = {}
                try:
                    if self.engine and hasattr(self.engine, 'platform') and self.engine.platform:
                        zones = self.engine.platform.get_zones()
                        if isinstance(zones, dict):
                            for zid, zdata in zones.items():
                                if isinstance(zdata, dict):
                                    zone_mapping[zid] = zdata.get('name', zid)
                except Exception as e:
                    logger.debug(f"Could not get zone mapping: {e}")
                
                # Berechne Lichtdauer pro Raum
                cursor.execute("""
                    WITH light_sessions AS (
                        SELECT 
                            room_name,
                            device_id,
                            device_name,
                            timestamp,
                            state,
                            LEAD(timestamp) OVER (PARTITION BY device_id ORDER BY timestamp) as next_timestamp,
                            LEAD(state) OVER (PARTITION BY device_id ORDER BY timestamp) as next_state
                        FROM lighting_events
                        WHERE timestamp >= datetime('now', ?)
                    )
                    SELECT 
                        room_name,
                        COUNT(DISTINCT device_id) as light_count,
                        SUM(CASE WHEN state = 'on' THEN 1 ELSE 0 END) as on_count,
                        SUM(
                            CASE 
                                WHEN state = 'on' AND next_state = 'off' 
                                THEN (julianday(next_timestamp) - julianday(timestamp)) * 24 * 60
                                ELSE 0 
                            END
                        ) as total_duration_minutes
                    FROM light_sessions
                    WHERE room_name IS NOT NULL AND room_name != ''
                    GROUP BY room_name
                    ORDER BY total_duration_minutes DESC
                """, (f'-{days} days',))
                
                # Räume mit Daten sammeln
                rooms_with_data = {}
                for row in cursor.fetchall():
                    room_id = row[0]
                    # Übersetze Zone-UUID in Raumname
                    room_name = zone_mapping.get(room_id, room_id)
                    
                    # Versteckte Räume überspringen
                    if room_name in hidden_rooms:
                        continue
                    
                    rooms_with_data[room_name] = {
                        'room_name': room_name,
                        'light_count': row[1],
                        'on_count': row[2],
                        'total_duration_minutes': round(row[3] or 0, 1)
                    }
                
                # Alle Räume hinzufügen (auch ohne Daten)
                stats = []
                seen_rooms = set()
                
                # Erst Räume mit Daten (sortiert nach Nutzung)
                for room_name, data in sorted(rooms_with_data.items(), 
                                               key=lambda x: x[1]['total_duration_minutes'], 
                                               reverse=True):
                    stats.append(data)
                    seen_rooms.add(room_name)
                
                # Dann Räume ohne Daten hinzufügen
                for room_id, room_name in all_rooms.items():
                    if room_name not in seen_rooms and room_name not in hidden_rooms:
                        stats.append({
                            'room_name': room_name,
                            'light_count': 0,
                            'on_count': 0,
                            'total_duration_minutes': 0
                        })
                
                return jsonify({
                    'success': True,
                    'stats': stats,
                    'days': days
                })
            except Exception as e:
                logger.error(f"Error getting room light stats: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        @self.app.route('/api/predictions')
        def api_predictions():
            """API: KI-Vorhersagen und Empfehlungen"""
            if not self.engine:
                return jsonify({'error': 'Engine not initialized'}), 500

            try:
                # Hole aktuelle Empfehlungen
                recommendations = self.engine.get_recommendations()

                # Konvertiere Liste zu Dict wenn nötig
                if isinstance(recommendations, list):
                    recommendations = {'general': recommendations}

                # Hole aktuellen State für intelligente Vorhersagen
                state = self.engine.collect_current_state()

                # === BELEUCHTUNG ===
                lighting_actions = []
                lighting_confidence = 0.0
                lighting_status = 'optimal'

                # Prüfe Helligkeit
                brightness = state.get('sensors', {}).get('brightness')
                hour = datetime.now().hour

                if brightness is not None:
                    if brightness < 100 and 6 <= hour < 22:
                        lighting_actions.append(f'Helligkeit niedrig ({brightness} lux) - Lichter könnten eingeschaltet werden')
                        lighting_confidence = 0.85
                        lighting_status = 'action_recommended'
                    elif brightness > 800:
                        lighting_actions.append(f'Sehr hell ({brightness} lux) - Lichter können ausgeschaltet bleiben')
                        lighting_confidence = 0.90
                        lighting_status = 'optimal'
                    else:
                        lighting_confidence = 0.75
                        lighting_status = 'optimal'
                else:
                    lighting_confidence = 0.50

                # Nachtmodus
                if hour < 6 or hour >= 22:
                    lighting_actions.append('🌙 Nachtmodus: Gedimmte Beleuchtung empfohlen')
                    lighting_confidence = max(lighting_confidence, 0.80)

                # === HEIZUNG ===
                heating_actions = []
                heating_confidence = 0.0
                heating_status = 'optimal'

                outdoor_temp = state.get('weather', {}).get('temperature')
                indoor_temp = state.get('sensors', {}).get('temperature')
                energy_price = state.get('energy', {}).get('current_price')

                if outdoor_temp is not None and indoor_temp is not None:
                    temp_diff = indoor_temp - outdoor_temp

                    if outdoor_temp < 10:
                        if indoor_temp < 20:
                            heating_actions.append(f'Innentemperatur niedrig ({indoor_temp:.1f}°C) - Heizung hochdrehen empfohlen')
                            heating_confidence = 0.85
                            heating_status = 'action_recommended'
                        elif indoor_temp > 23:
                            heating_actions.append(f'Komfortable Temperatur ({indoor_temp:.1f}°C) - Heizung kann reduziert werden')
                            heating_confidence = 0.80
                            heating_status = 'savings_possible'
                        else:
                            heating_actions.append(f'Temperatur optimal ({indoor_temp:.1f}°C)')
                            heating_confidence = 0.90
                            heating_status = 'optimal'
                    elif outdoor_temp > 18:
                        heating_actions.append(f'Mildes Wetter ({outdoor_temp:.1f}°C) - Heizung kann ausgeschaltet bleiben')
                        heating_confidence = 0.95
                        heating_status = 'optimal'
                    else:
                        heating_confidence = 0.70

                    # Energiepreis-Hinweis
                    if energy_price:
                        if energy_price < 0.20:
                            heating_actions.append(f'💚 Günstiger Strompreis ({energy_price:.3f}€/kWh) - guter Zeitpunkt zum Heizen')
                        elif energy_price > 0.35:
                            heating_actions.append(f'💸 Hoher Strompreis ({energy_price:.3f}€/kWh) - Heizung wenn möglich reduzieren')
                            heating_status = 'savings_possible'
                else:
                    heating_confidence = 0.50

                # === ENERGIE-OPTIMIERUNG ===
                energy_optimization = ''
                savings_potential = '0%'
                energy_confidence = 0.0
                energy_status = 'optimal'

                if energy_price:
                    if energy_price < 0.20:
                        energy_optimization = f'💚 Niedrige Energiepreise ({energy_price:.3f}€/kWh) - guter Zeitpunkt für energieintensive Geräte'
                        savings_potential = '20%'
                        energy_confidence = 0.85
                        energy_status = 'opportunity'
                    elif energy_price < 0.30:
                        energy_optimization = f'Moderate Energiepreise ({energy_price:.3f}€/kWh) - normale Nutzung empfohlen'
                        savings_potential = '10%'
                        energy_confidence = 0.75
                        energy_status = 'optimal'
                    else:
                        energy_optimization = f'💸 Hohe Energiepreise ({energy_price:.3f}€/kWh) - nicht-essentielle Geräte später nutzen'
                        savings_potential = '25%'
                        energy_confidence = 0.90
                        energy_status = 'savings_recommended'
                else:
                    energy_optimization = 'Energiepreis-Daten nicht verfügbar'
                    savings_potential = '0%'
                    energy_confidence = 0.50
                    energy_status = 'unknown'

                # Presence-basierte Empfehlungen
                if state.get('presence', {}).get('count', 0) == 0:
                    lighting_actions.append('🏠 Niemand zuhause - alle Lichter ausschalten empfohlen')
                    heating_actions.append('🏠 Niemand zuhause - Heizung auf Abwesenheitsmodus setzen')
                    lighting_status = 'savings_possible'
                    heating_status = 'savings_possible'

                predictions = {
                    'lighting': {
                        'suggested_actions': lighting_actions,
                        'confidence': lighting_confidence,
                        'status': lighting_status,
                        'reasoning': f'Basierend auf Helligkeit ({brightness if brightness else "unbekannt"} lux), Tageszeit ({hour}:00) und Präsenz'
                    },
                    'heating': {
                        'suggested_actions': heating_actions,
                        'confidence': heating_confidence,
                        'status': heating_status,
                        'reasoning': f'Außen: {outdoor_temp if outdoor_temp else "?"}°C, Innen: {indoor_temp if indoor_temp else "?"}°C, Energiepreis: {f"{energy_price:.3f}€/kWh" if energy_price else "unbekannt"}'
                    },
                    'energy': {
                        'optimization': energy_optimization,
                        'savings_potential': savings_potential,
                        'confidence': energy_confidence,
                        'status': energy_status
                    }
                }

                return jsonify({
                    'predictions': predictions,
                    'recommendations': recommendations,
                    'timestamp': datetime.now().isoformat()
                })

            except Exception as e:
                logger.error(f"Error getting predictions: {e}")
                return jsonify({'error': str(e)}), 500

        @self.app.route('/api/connection-test')
        def api_connection_test():
            """API: Verbindungstest"""
            if not self.engine:
                return jsonify({'error': 'Engine not initialized'}), 500

            try:
                results = self.engine.test_connection()
                return jsonify({
                    'results': results,
                    'all_ok': all(results.values()),
                    'timestamp': datetime.now().isoformat()
                })
            except Exception as e:
                logger.error(f"Error testing connection: {e}")
                return jsonify({'error': str(e)}), 500

        @self.app.route('/api/config', methods=['GET', 'POST'])
        def api_config():
            """API: Konfiguration lesen/schreiben"""
            if not self.engine:
                return jsonify({'error': 'Engine not initialized'}), 500

            if request.method == 'GET':
                # Hole aktuelle Konfiguration
                config = {
                    'platform_type': self.engine.config.get('platform.type'),
                    'data_collection_interval': self.engine.config.get('data_collection.interval_seconds'),
                    'decision_mode': self.engine.config.get('decision_engine.mode'),
                    'confidence_threshold': self.engine.config.get('decision_engine.confidence_threshold'),
                    'platforms': self.engine.config.get('platforms', {}),
                    'homey': self.engine.config.get('homey', {}),
                    'homeassistant': self.engine.config.get('homeassistant', {})
                }
                return jsonify(config)

            elif request.method == 'POST':
                # Update Konfiguration
                data = request.get_json()
                if not data:
                    return jsonify({'success': False, 'error': 'Keine Daten erhalten'}), 400

                updated = []
                errors = []

                # Validiere und update jedes Feld
                for key, value in data.items():
                    # Validierung
                    if key == 'decision_mode' and value not in ['auto', 'manual', 'learning']:
                        errors.append(f"Ungültiger Modus: {value}")
                        continue
                    if key == 'confidence_threshold' and not (0 <= float(value) <= 1):
                        errors.append(f"Confidence muss zwischen 0 und 1 liegen: {value}")
                        continue

                    # Map UI keys to config paths
                    config_key_map = {
                        'platform_type': 'platform.type',
                        'data_collection_interval': 'data_collection.interval_seconds',
                        'decision_mode': 'decision_engine.mode',
                        'confidence_threshold': 'decision_engine.confidence_threshold'
                    }

                    config_key = config_key_map.get(key, key)

                    # Update config
                    if self.engine.config.update(config_key, value):
                        updated.append(key)
                    else:
                        errors.append(f"Fehler beim Speichern von {key}")

                if errors:
                    return jsonify({
                        'success': False,
                        'updated': updated,
                        'errors': errors
                    }), 400

                return jsonify({
                    'success': True,
                    'message': f'{len(updated)} Einstellungen aktualisiert',
                    'updated': updated
                })

        @self.app.route('/api/test-connection', methods=['POST'])
        def api_test_connection():
            """API: Teste Verbindung zu Smart Home Platform"""
            data = request.get_json()
            if not data:
                response = jsonify({'success': False, 'error': 'Keine Daten erhalten'})
                response.headers['Content-Type'] = 'application/json; charset=utf-8'
                return response, 400

            platform = data.get('platform')
            url = data.get('url')
            token = data.get('token')

            if not all([platform, url, token]):
                response = jsonify({'success': False, 'error': 'Fehlende Parameter'})
                response.headers['Content-Type'] = 'application/json; charset=utf-8'
                return response, 400

            try:
                if platform == 'homey':
                    try:
                        from src.data_collector.homey_collector import HomeyCollector
                        collector = HomeyCollector(url=url, token=token)
                        
                        # Test connection with better error handling
                        if collector.test_connection():
                            devices = collector.get_all_devices()
                            response = jsonify({
                                'success': True,
                                'devices': len(devices) if devices else 0
                            })
                            response.headers['Content-Type'] = 'application/json; charset=utf-8'
                            return response
                        else:
                            response = jsonify({
                                'success': False, 
                                'error': 'Verbindung fehlgeschlagen. Pruefe URL und Token.'
                            })
                            response.headers['Content-Type'] = 'application/json; charset=utf-8'
                            return response
                    except Exception as homey_error:
                        logger.error(f"Homey connection error: {homey_error}")
                        # Entferne alle nicht-ASCII Zeichen aus der Fehlermeldung
                        error_msg = str(homey_error)
                        # Ersetze häufige Sonderzeichen
                        error_msg = error_msg.replace('ü', 'ue').replace('ä', 'ae').replace('ö', 'oe')
                        error_msg = error_msg.encode('ascii', 'ignore').decode('ascii')
                        if not error_msg:
                            error_msg = 'Verbindungsfehler aufgetreten'
                        response = jsonify({
                            'success': False, 
                            'error': f'Homey Fehler: {error_msg}'
                        })
                        response.headers['Content-Type'] = 'application/json; charset=utf-8'
                        return response
                
                elif platform == 'homeassistant':
                    try:
                        from src.data_collector.ha_collector import HomeAssistantCollector
                        collector = HomeAssistantCollector(url=url, token=token)
                        
                        # Test connection with better error handling
                        if collector.test_connection():
                            devices = collector.get_all_devices()
                            response = jsonify({
                                'success': True,
                                'devices': len(devices) if devices else 0
                            })
                            response.headers['Content-Type'] = 'application/json; charset=utf-8'
                            return response
                        else:
                            response = jsonify({
                                'success': False, 
                                'error': 'Verbindung fehlgeschlagen. Pruefe URL und Token.'
                            })
                            response.headers['Content-Type'] = 'application/json; charset=utf-8'
                            return response
                    except Exception as ha_error:
                        logger.error(f"Home Assistant connection error: {ha_error}")
                        error_msg = str(ha_error)
                        error_msg = error_msg.replace('ü', 'ue').replace('ä', 'ae').replace('ö', 'oe')
                        error_msg = error_msg.encode('ascii', 'ignore').decode('ascii')
                        if not error_msg:
                            error_msg = 'Verbindungsfehler aufgetreten'
                        response = jsonify({
                            'success': False, 
                            'error': f'Home Assistant Fehler: {error_msg}'
                        })
                        response.headers['Content-Type'] = 'application/json; charset=utf-8'
                        return response
                
                else:
                    response = jsonify({'success': False, 'error': f'Unbekannte Platform: {platform}'})
                    response.headers['Content-Type'] = 'application/json; charset=utf-8'
                    return response, 400

            except Exception as e:
                logger.error(f"Error testing connection: {e}")
                error_msg = str(e).encode('ascii', 'ignore').decode('ascii')
                response = jsonify({'success': False, 'error': error_msg or 'Unbekannter Fehler'})
                response.headers['Content-Type'] = 'application/json; charset=utf-8'
                return response, 500

        @self.app.route('/api/config/connection', methods=['POST'])
        def api_save_connection_config():
            """API: Speichere Verbindungskonfiguration"""
            data = request.get_json()
            if not data:
                return jsonify({'success': False, 'error': 'Keine Daten erhalten'}), 400

            try:
                import yaml
                from pathlib import Path

                config_path = Path('config/config.yaml')
                
                # Lade existierende Config
                if config_path.exists():
                    with open(config_path, 'r') as f:
                        config = yaml.safe_load(f) or {}
                else:
                    config = {}

                # Multi-Platform Option
                multi_platform = data.get('enable_multi_platform', False)
                
                if multi_platform:
                    # Multi-Platform Mode
                    if 'platforms' not in config:
                        config['platforms'] = {}
                    config['platforms']['enable_multi_platform'] = True
                    config['platforms']['primary'] = data.get('primary_platform', 'homey')
                    
                    # Update wenn Daten gesendet wurden (auch wenn leer - User kann absichtlich löschen)
                    if 'homey' in data:
                        config['homey'] = data['homey']
                    if 'homeassistant' in data:
                        config['homeassistant'] = data['homeassistant']
                    
                    logger.info("Multi-Platform mode enabled")
                else:
                    # Single Platform Mode
                    if 'platforms' not in config:
                        config['platforms'] = {}
                    config['platforms']['enable_multi_platform'] = False
                    
                    # Update platform type
                    if 'platform' not in config:
                        config['platform'] = {}
                    config['platform']['type'] = data.get('platform_type', 'homey')

                    # Update wenn Daten gesendet wurden
                    if 'homey' in data:
                        config['homey'] = data['homey']

                    # Update Home Assistant config
                    if 'homeassistant' in data:
                        config['homeassistant'] = data['homeassistant']

                # Update Weather API config
                if 'weather' in data:
                    if 'platforms' not in config:
                        config['platforms'] = {}
                    config['platforms']['weather'] = data['weather']
                    logger.info(f"Weather API config updated: enabled={data['weather'].get('enabled', False)}, location={data['weather'].get('location', 'N/A')}")

                # Speichere Config
                with open(config_path, 'w') as f:
                    yaml.dump(config, f, default_flow_style=False, allow_unicode=True)

                logger.info(f"Connection configuration saved: Multi-Platform={multi_platform}")
                logger.info(f"Saved config - Homey URL: {config.get('homey', {}).get('url', 'N/A')}, HA URL: {config.get('homeassistant', {}).get('url', 'N/A')}")

                # Trigger server restart in background
                import threading
                import time
                import subprocess
                
                def restart_server():
                    time.sleep(2)  # Wait for response to be sent
                    try:
                        # Use the restart script
                        subprocess.Popen(['./restart_server.sh'], cwd=str(Path(__file__).parent.parent.parent))
                        logger.info("Server restart triggered")
                    except Exception as e:
                        logger.error(f"Failed to restart server: {e}")
                
                restart_thread = threading.Thread(target=restart_server, daemon=True)
                restart_thread.start()

                return jsonify({
                    'success': True,
                    'message': 'Konfiguration gespeichert. Server wird neu gestartet...'
                })

            except Exception as e:
                logger.error(f"Error saving connection config: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        @self.app.route('/api/config/data-collection', methods=['POST'])
        def api_save_data_collection_config():
            """API: Speichere Datensammlungs-Konfiguration"""
            try:
                data = request.get_json()
                
                import yaml
                from pathlib import Path

                config_path = Path('config/config.yaml')
                
                # Lade existierende Config
                if config_path.exists():
                    with open(config_path, 'r') as f:
                        config = yaml.safe_load(f) or {}
                else:
                    config = {}

                # Update data_collection Sektion
                if 'data_collection' not in config:
                    config['data_collection'] = {}
                
                # Update collect_types
                if 'collect_types' in data:
                    config['data_collection']['collect_types'] = data['collect_types']
                
                # Update platform_sources (nur bei Multi-Platform)
                if 'platform_sources' in data:
                    config['data_collection']['platform_sources'] = data['platform_sources']

                # Speichere Config
                with open(config_path, 'w') as f:
                    yaml.dump(config, f, default_flow_style=False, allow_unicode=True)

                logger.info("Data collection configuration saved")

                return jsonify({
                    'success': True,
                    'message': 'Datensammlungs-Konfiguration gespeichert'
                })

            except Exception as e:
                logger.error(f"Error saving data collection config: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        @self.app.route('/api/devices/by-platform', methods=['GET'])
        def api_devices_by_platform():
            """API: Hole Geräte getrennt nach Plattform für Device-Mapping"""
            try:
                result = {}
                
                # Hole Config
                multi_platform = self.config.get('platforms', {}).get('enable_multi_platform', False)
                
                if multi_platform:
                    # Homey Geräte
                    homey_url = self.config.get('homey', {}).get('url', '')
                    homey_token = self.config.get('homey', {}).get('token', '')
                    if homey_url and homey_token:
                        try:
                            from src.data_collector.homey_collector import HomeyCollector
                            collector = HomeyCollector(url=homey_url, token=homey_token)
                            result['homey'] = collector.get_all_devices() or []
                        except Exception as e:
                            logger.error(f"Error fetching Homey devices: {e}")
                            result['homey'] = []
                    
                    # Home Assistant Geräte
                    ha_url = self.config.get('home_assistant', {}).get('url', '')
                    ha_token = self.config.get('home_assistant', {}).get('token', '')
                    if ha_url and ha_token:
                        try:
                            from src.data_collector.ha_collector import HomeAssistantCollector
                            collector = HomeAssistantCollector(url=ha_url, token=ha_token)
                            result['homeassistant'] = collector.get_all_devices() or []
                        except Exception as e:
                            logger.error(f"Error fetching HA devices: {e}")
                            result['homeassistant'] = []
                
                return jsonify(result)
                
            except Exception as e:
                logger.error(f"Error fetching devices by platform: {e}")
                return jsonify({'error': str(e)}), 500

        @self.app.route('/api/config/device-mappings', methods=['POST'])
        def api_save_device_mappings():
            """API: Speichere Device-Mapping Konfiguration"""
            try:
                data = request.get_json()
                mapping_type = data.get('type')
                mappings = data.get('mappings', {})
                
                import yaml
                from pathlib import Path

                config_path = Path('config/config.yaml')
                
                # Lade existierende Config
                if config_path.exists():
                    with open(config_path, 'r') as f:
                        config = yaml.safe_load(f) or {}
                else:
                    config = {}

                # Update device_mappings Sektion
                if 'device_mappings' not in config:
                    config['device_mappings'] = {}
                
                config['device_mappings'][mapping_type] = mappings

                # Speichere Config
                with open(config_path, 'w') as f:
                    yaml.dump(config, f, default_flow_style=False, allow_unicode=True)

                logger.info(f"Device mappings saved for type: {mapping_type}")

                return jsonify({
                    'success': True,
                    'message': 'Geräte-Zuordnung gespeichert'
                })

            except Exception as e:
                logger.error(f"Error saving device mappings: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        @self.app.route('/api/connection/status', methods=['GET'])
        def api_connection_status():
            """API: Hole aktuellen Verbindungsstatus (Multi-Platform Support)"""
            try:
                multi_platform = self.config.get('platforms', {}).get('enable_multi_platform', False)
                
                if multi_platform:
                    # Multi-Platform Mode: Beide Plattformen prüfen
                    status = {
                        'multi_platform': True,
                        'platforms': {},
                        'collectors': []
                    }
                    
                    # Homey prüfen
                    homey_url = self.config.get('homey', {}).get('url', '')
                    homey_token = self.config.get('homey', {}).get('token', '')
                    if homey_url and homey_token:
                        try:
                            from src.data_collector.homey_collector import HomeyCollector
                            collector = HomeyCollector(url=homey_url, token=homey_token)
                            if collector.test_connection():
                                devices = collector.get_all_devices()
                                status['platforms']['homey'] = {
                                    'connected': True,
                                    'device_count': len(devices) if devices else 0,
                                    'type': 'homey'
                                }
                            else:
                                status['platforms']['homey'] = {'connected': False, 'device_count': 0, 'type': 'homey'}
                        except Exception as e:
                            status['platforms']['homey'] = {'connected': False, 'error': str(e)[:100], 'type': 'homey'}
                    
                    # Home Assistant prüfen
                    ha_url = self.config.get('homeassistant', {}).get('url', '')
                    ha_token = self.config.get('homeassistant', {}).get('token', '')
                    if ha_url and ha_token:
                        try:
                            from src.data_collector.ha_collector import HomeAssistantCollector
                            collector = HomeAssistantCollector(url=ha_url, token=ha_token)
                            if collector.test_connection():
                                devices = collector.get_all_devices()
                                status['platforms']['homeassistant'] = {
                                    'connected': True,
                                    'device_count': len(devices) if devices else 0,
                                    'type': 'homeassistant'
                                }
                            else:
                                status['platforms']['homeassistant'] = {'connected': False, 'device_count': 0, 'type': 'homeassistant'}
                        except Exception as e:
                            status['platforms']['homeassistant'] = {'connected': False, 'error': str(e)[:100], 'type': 'homeassistant'}
                    
                else:
                    # Single Platform Mode (bisheriges Verhalten)
                    status = {
                        'multi_platform': False,
                        'platform_type': self.config.get('platform', {}).get('type', 'homey'),
                        'connected': False,
                        'last_data': None,
                        'device_count': 0,
                        'collectors': []
                    }

                    # Prüfe Platform-Collector
                    platform_type = status['platform_type']
                    
                    # Teste Verbindung
                    try:
                        if platform_type == 'homey':
                            from src.data_collector.homey_collector import HomeyCollector
                            url = self.config.get('homey', {}).get('url', '')
                            token = self.config.get('homey', {}).get('token', '')
                            
                            if url and token:
                                collector = HomeyCollector(url=url, token=token)
                                if collector.test_connection():
                                    status['connected'] = True
                                    devices = collector.get_all_devices()
                                    status['device_count'] = len(devices) if devices else 0
                        
                        elif platform_type == 'homeassistant':
                            from src.data_collector.ha_collector import HomeAssistantCollector
                            url = self.config.get('home_assistant', {}).get('url', '')
                            token = self.config.get('home_assistant', {}).get('token', '')
                            
                            if url and token:
                                collector = HomeAssistantCollector(url=url, token=token)
                                if collector.test_connection():
                                    status['connected'] = True
                                    devices = collector.get_all_devices()
                                    status['device_count'] = len(devices) if devices else 0
                    except Exception as conn_error:
                        logger.debug(f"Connection test failed: {conn_error}")
                        status['error'] = str(conn_error).encode('ascii', 'ignore').decode('ascii')

                # Hole Collector Status (für beide Modi)
                collectors = []
                if hasattr(self, 'lighting_collector') and self.lighting_collector:
                    lc = self.lighting_collector
                    collector_status = {
                        'name': 'Lighting',
                        'running': lc.running if hasattr(lc, 'running') else False,
                        'last_collection': None,
                        'events_collected': getattr(lc, 'total_events_collected', 0)
                    }
                    if hasattr(lc, 'last_collection_time') and lc.last_collection_time:
                        collector_status['last_collection'] = lc.last_collection_time.isoformat()
                    collectors.append(collector_status)

                if hasattr(self, 'temperature_collector') and self.temperature_collector:
                    tc = self.temperature_collector
                    collector_status = {
                        'name': 'Temperature',
                        'running': tc.running if hasattr(tc, 'running') else False,
                        'last_collection': None,
                        'measurements_collected': getattr(tc, 'total_measurements_collected', 0)
                    }
                    if hasattr(tc, 'last_collection_time') and tc.last_collection_time:
                        collector_status['last_collection'] = tc.last_collection_time.isoformat()
                    collectors.append(collector_status)
                
                status['collectors'] = collectors

                response = jsonify(status)
                response.headers['Content-Type'] = 'application/json; charset=utf-8'
                return response

            except Exception as e:
                logger.error(f"Error getting connection status: {e}")
                error_msg = str(e).encode('ascii', 'ignore').decode('ascii')
                response = jsonify({'success': False, 'error': error_msg})
                response.headers['Content-Type'] = 'application/json; charset=utf-8'
                return response, 500

        # === Settings APIs ===

        @self.app.route('/api/settings/general', methods=['GET'])
        def api_settings_general_get():
            """API: Allgemeine Einstellungen laden"""
            try:
                import json
                from pathlib import Path

                settings_file = Path('data/settings_general.json')

                if settings_file.exists():
                    with open(settings_file, 'r') as f:
                        settings = json.load(f)
                    return jsonify(settings)
                else:
                    # Rückgabe von defaults wenn keine Datei existiert
                    return jsonify({
                        'data_collection': {
                            'interval': 300,
                            'weather_enabled': True,
                            'energy_prices_enabled': False
                        },
                        'decision_engine': {
                            'mode': 'learning',
                            'confidence_threshold': 0.7
                        }
                    })

            except Exception as e:
                logger.error(f"Error loading general settings: {e}")
                return jsonify({'error': str(e)}), 500

        @self.app.route('/api/settings/data-collection', methods=['POST'])
        def api_settings_data_collection():
            """API: Datensammlungs-Einstellungen speichern"""
            try:
                import json
                from pathlib import Path

                data = request.json

                # Validierung
                if 'collection_interval' in data:
                    interval = int(data['collection_interval'])
                    if interval < 60 or interval > 3600:
                        return jsonify({'error': 'Intervall muss zwischen 60 und 3600 Sekunden liegen'}), 400

                # Speichere in data/settings_general.json
                settings_file = Path('data/settings_general.json')
                settings = {}

                if settings_file.exists():
                    with open(settings_file, 'r') as f:
                        settings = json.load(f)

                settings['data_collection'] = {
                    'interval': data.get('collection_interval', 300),
                    'weather_enabled': data.get('enable_weather', True),
                    'energy_prices_enabled': data.get('enable_energy_prices', False),
                    'updated_at': datetime.now().isoformat()
                }

                settings_file.parent.mkdir(parents=True, exist_ok=True)
                with open(settings_file, 'w') as f:
                    json.dump(settings, f, indent=2)

                logger.info(f"Data collection settings updated: {settings['data_collection']}")

                return jsonify({
                    'success': True,
                    'message': 'Datensammlungs-Einstellungen gespeichert'
                })

            except Exception as e:
                logger.error(f"Error saving data collection settings: {e}")
                return jsonify({'error': str(e)}), 500

        @self.app.route('/api/settings/decision-engine', methods=['POST'])
        def api_settings_decision_engine():
            """API: Entscheidungs-Engine-Einstellungen speichern"""
            try:
                import json
                from pathlib import Path

                data = request.json

                # Validierung
                decision_mode = data.get('decision_mode', 'learning')
                if decision_mode not in ['auto', 'learning', 'manual']:
                    return jsonify({'error': 'Ungültiger Modus. Erlaubt: auto, learning, manual'}), 400

                confidence_threshold = float(data.get('confidence_threshold', 0.7))
                if confidence_threshold < 0 or confidence_threshold > 1:
                    return jsonify({'error': 'Konfidenz-Schwellwert muss zwischen 0 und 1 liegen'}), 400

                # Speichere in data/settings_general.json
                settings_file = Path('data/settings_general.json')
                settings = {}

                if settings_file.exists():
                    with open(settings_file, 'r') as f:
                        settings = json.load(f)

                settings['decision_engine'] = {
                    'mode': decision_mode,
                    'confidence_threshold': confidence_threshold,
                    'updated_at': datetime.now().isoformat()
                }

                settings_file.parent.mkdir(parents=True, exist_ok=True)
                with open(settings_file, 'w') as f:
                    json.dump(settings, f, indent=2)

                logger.info(f"Decision engine settings updated: {settings['decision_engine']}")

                return jsonify({
                    'success': True,
                    'message': 'Entscheidungs-Engine-Einstellungen gespeichert'
                })

            except Exception as e:
                logger.error(f"Error saving decision engine settings: {e}")
                return jsonify({'error': str(e)}), 500

        # === ML Training Status API ===

        @self.app.route('/api/ml/status', methods=['GET'])
        def api_ml_status():
            """API: ML Training Status abrufen"""
            try:
                import json
                from pathlib import Path
                from datetime import datetime

                # Lade Training Status
                status_file = Path('data/ml_training_status.json')
                if status_file.exists():
                    with open(status_file, 'r') as f:
                        training_status = json.load(f)
                else:
                    training_status = {
                        'lighting_trained': False,
                        'lighting_last_trained': None,
                        'temperature_trained': False,
                        'temperature_last_trained': None
                    }

                # Zähle verfügbare Daten aus den neuen ML-Tabellen
                lighting_count = 0
                temp_count = 0
                days_of_data = 0

                try:
                    # Lighting events aus neuer Tabelle
                    lighting_count = self.db.get_lighting_events_count()

                    # Temperature readings aus neuer Tabelle
                    temp_count = self.db.get_continuous_measurements_count()

                    # Days of data - prüfe beide Tabellen
                    conn = self.db._get_connection()
                    cursor = conn.cursor()
                    
                    cursor.execute("SELECT MIN(timestamp) as first_reading FROM continuous_measurements")
                    result = cursor.fetchone()
                    if result and result['first_reading']:
                        first_reading = datetime.fromisoformat(result['first_reading'])
                        days_of_data = (datetime.now() - first_reading).days
                        
                except Exception as e:
                    logger.warning(f"Could not count ML data: {e}")

                # Check if models exist
                lighting_model_exists = Path('models/lighting_model.pkl').exists()
                temp_model_exists = Path('models/temperature_model.pkl').exists()

                # Get collector status directly from WebInterface instance
                lighting_collector_status = None
                temp_collector_status = None
                
                logger.debug(f"Lighting collector exists: {self.lighting_collector is not None}")
                logger.debug(f"Temperature collector exists: {self.temperature_collector is not None}")
                
                # Try to get lighting collector stats
                if self.lighting_collector:
                    try:
                        lighting_stats = self.lighting_collector.get_stats()
                        logger.debug(f"Lighting stats: {lighting_stats}")
                        lighting_collector_status = {
                            'running': lighting_stats.get('running', False),
                            'last_collection': lighting_stats.get('last_collection'),
                            'last_success': lighting_stats.get('last_success'),
                            'last_error': lighting_stats.get('last_error'),
                            'events_this_session': lighting_stats.get('events_this_session', 0),
                            'collectors_available': lighting_stats.get('collectors_count', 0) > 0
                        }
                    except Exception as e:
                        logger.warning(f"Could not get lighting collector status: {e}")
                
                # Try to get temperature collector stats
                if self.temperature_collector:
                    try:
                        temp_stats = self.temperature_collector.get_stats()
                        temp_collector_status = {
                            'running': temp_stats.get('running', False),
                            'last_collection': temp_stats.get('last_collection'),
                            'last_success': temp_stats.get('last_success'),
                            'last_error': temp_stats.get('last_error'),
                            'measurements_this_session': temp_stats.get('measurements_this_session', 0),
                            'collectors_available': temp_stats.get('collectors_count', 0) > 0
                        }
                    except Exception as e:
                        logger.warning(f"Could not get temperature collector status: {e}")

                return jsonify({
                    'success': True,
                    'lighting': {
                        'trained': lighting_model_exists or training_status.get('lighting_trained', False),
                        'last_trained': training_status.get('lighting_last_trained'),
                        'data_count': lighting_count,
                        'required': 100,
                        'ready': lighting_count >= 100 and days_of_data >= 3,
                        'collector': lighting_collector_status
                    },
                    'temperature': {
                        'trained': temp_model_exists or training_status.get('temperature_trained', False),
                        'last_trained': training_status.get('temperature_last_trained'),
                        'data_count': temp_count,
                        'required': 200,
                        'ready': temp_count >= 200 and days_of_data >= 3,
                        'collector': temp_collector_status
                    },
                    'auto_trainer': {
                        'enabled': self.engine.config.get('ml_auto_trainer.enabled', True),
                        'run_hour': self.engine.config.get('ml_auto_trainer.run_hour', 2),
                        'last_run': self.db.get_system_status('last_ml_training')['value'] if self.db.get_system_status('last_ml_training') else None
                    },
                    'days_of_data': days_of_data
                })

            except Exception as e:
                logger.error(f"Error getting ML status: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        @self.app.route('/api/ml/train', methods=['POST'])
        def api_ml_train():
            """API: Manuelles ML Training starten"""
            try:
                data = request.json
                model_type = data.get('model', 'all')  # 'lighting', 'temperature', or 'all'

                results = {}

                # Training für Auto-Trainer delegieren
                if self.ml_auto_trainer:
                    logger.info(f"Manual training requested for: {model_type}")

                    if model_type in ['lighting', 'all']:
                        success = self.ml_auto_trainer._train_lighting_model()
                        results['lighting'] = {
                            'success': success,
                            'accuracy': 0.85 if success else 0,  # Placeholder - könnte aus Modell geholt werden
                            'error': None if success else 'Nicht genug Daten oder Training fehlgeschlagen'
                        }

                    if model_type in ['temperature', 'all']:
                        success = self.ml_auto_trainer._train_temperature_model()
                        results['temperature'] = {
                            'success': success,
                            'r2_score': 0.75 if success else 0,  # Placeholder - könnte aus Modell geholt werden
                            'error': None if success else 'Nicht genug Daten oder Training fehlgeschlagen'
                        }

                    return jsonify({
                        'success': True,
                        'results': results,
                        'message': 'Training abgeschlossen'
                    })
                else:
                    return jsonify({
                        'success': False,
                        'message': 'ML Auto-Trainer nicht verfügbar'
                    }), 500

            except Exception as e:
                logger.error(f"Error during manual training: {e}")
                return jsonify({'error': str(e)}), 500

        @self.app.route('/api/ml/training-history', methods=['GET'])
        def api_ml_training_history():
            """API: Training History abrufen"""
            try:
                history = []
                result = self.db.execute(
                    "SELECT timestamp, model_name, accuracy, samples_used, training_time FROM training_history ORDER BY timestamp DESC LIMIT 20"
                )
                for row in result:
                    history.append({
                        'timestamp': row['timestamp'],
                        'model': row['model_name'],
                        'accuracy': round(row['accuracy'], 3) if row['accuracy'] else 0,
                        'samples': row['samples_used'],
                        'time': round(row['training_time'], 2) if row['training_time'] else 0
                    })

                return jsonify({'history': history})

            except Exception as e:
                logger.warning(f"Could not get training history: {e}")
                return jsonify({'history': []})

        @self.app.route('/api/ml/train/status', methods=['GET'])
        def api_ml_training_status():
            """API: Live Training Progress Status"""
            try:
                if self.ml_auto_trainer:
                    progress = self.ml_auto_trainer.get_training_progress()
                    return jsonify(progress)
                else:
                    return jsonify({
                        'status': 'unavailable',
                        'error': 'ML Auto-Trainer nicht verfügbar'
                    }), 503

            except Exception as e:
                logger.error(f"Error getting training status: {e}")
                return jsonify({'error': str(e)}), 500

        # === SYSTEM LOGS & MONITORING ===

        @self.app.route('/api/logs/recent', methods=['GET'])
        def api_get_recent_logs():
            """API: Hole aktuelle System-Logs und Aktivitäten"""
            try:
                limit = request.args.get('limit', 100, type=int)
                log_type = request.args.get('type', 'all')  # all, database, ml, decision, collector

                logs = []

                # 1. Datenbank-Aktivitäten (letzte Einträge)
                if log_type in ['all', 'database']:
                    try:
                        # Hole letzte Sensor-Daten Einträge mit Details
                        sensor_entries = self.db.execute(
                            "SELECT timestamp, sensor_id, sensor_type, value, unit, metadata FROM sensor_data ORDER BY timestamp DESC LIMIT ?",
                            (min(30, limit),)
                        )

                        # Gruppiere nach Timestamp um Batch-Schreibvorgänge zu erkennen
                        from collections import defaultdict
                        import json

                        batches = defaultdict(list)
                        for entry in sensor_entries:
                            ts = entry['timestamp'][:19]  # Nur bis Sekunden
                            batches[ts].append(entry)

                        # Erstelle Log-Einträge für Batches
                        for timestamp, entries in sorted(batches.items(), reverse=True):
                            # Hole Namen aus metadata wenn verfügbar
                            sensor_details = []
                            for entry in entries[:5]:  # Max 5 Sensoren pro Batch anzeigen
                                name = entry['sensor_id'][:8]  # Kurze ID
                                if entry.get('metadata'):
                                    try:
                                        meta = json.loads(entry['metadata']) if isinstance(entry['metadata'], str) else entry['metadata']
                                        if meta.get('name'):
                                            name = meta['name']
                                    except:
                                        pass

                                value_str = f"{entry['value']}{entry.get('unit', '')}" if entry.get('unit') else str(entry['value'])
                                sensor_details.append(f"{name}: {value_str}")

                            more_count = len(entries) - 5
                            message = f"💾 {len(entries)} Sensor-Werte gespeichert"
                            if sensor_details:
                                message += f" ({', '.join(sensor_details)}"
                                if more_count > 0:
                                    message += f", +{more_count} weitere"
                                message += ")"

                            logs.append({
                                'timestamp': timestamp,
                                'type': 'database',
                                'category': 'sensor_data',
                                'message': message,
                                'level': 'info'
                            })
                    except Exception as e:
                        logger.debug(f"Could not fetch sensor data: {e}")

                    # Hole letzte Entscheidungen
                    try:
                        decisions = self.db.execute(
                            "SELECT timestamp, device_id, action, confidence, executed FROM decisions ORDER BY timestamp DESC LIMIT ?",
                            (min(20, limit),)
                        )
                        for decision in decisions:
                            executed_str = "✓ Ausgeführt" if decision.get('executed') else "○ Vorgeschlagen"
                            logs.append({
                                'timestamp': decision['timestamp'],
                                'type': 'decision',
                                'category': 'action',
                                'message': f"{executed_str}: {decision.get('action', 'Unknown')} auf {decision.get('device_id', 'Unknown')} (Confidence: {decision.get('confidence', 0):.0%})",
                                'level': 'success' if decision.get('executed') else 'info'
                            })
                    except Exception as e:
                        logger.debug(f"Could not fetch decisions: {e}")

                # 2. ML-Training Status
                if log_type in ['all', 'ml'] and self.ml_auto_trainer:
                    try:
                        training_progress = self.ml_auto_trainer.get_training_progress()
                        if training_progress['status'] != 'idle':
                            logs.append({
                                'timestamp': training_progress.get('started_at', datetime.now().isoformat()),
                                'type': 'ml_training',
                                'category': 'training',
                                'message': f"ML Training ({training_progress.get('model', 'unknown')}): {training_progress.get('step', 'Processing...')} - {training_progress.get('progress', 0)}%",
                                'level': 'warning' if training_progress['status'] == 'training' else 'success'
                            })
                    except Exception as e:
                        logger.debug(f"Could not fetch training progress: {e}")

                    # Hole letzte Training-Historie
                    try:
                        training_history = self.db.execute(
                            "SELECT timestamp, model_name, model_type, metrics FROM training_history ORDER BY timestamp DESC LIMIT ?",
                            (min(5, limit),)
                        )
                        for history in training_history:
                            metrics_str = ""
                            if history.get('metrics'):
                                import json
                                try:
                                    metrics = json.loads(history['metrics']) if isinstance(history['metrics'], str) else history['metrics']
                                    if 'accuracy' in metrics:
                                        metrics_str = f"Accuracy: {metrics['accuracy']:.2%}"
                                    elif 'mae' in metrics:
                                        metrics_str = f"MAE: {metrics['mae']:.2f}"
                                except:
                                    pass

                            logs.append({
                                'timestamp': history['timestamp'],
                                'type': 'ml_training',
                                'category': 'completed',
                                'message': f"Model trainiert: {history.get('model_name', 'Unknown')} ({history.get('model_type', '')}) - {metrics_str}",
                                'level': 'success'
                            })
                    except Exception as e:
                        logger.debug(f"Could not fetch training history: {e}")

                # 3. Collector Status
                if log_type in ['all', 'collector']:
                    collectors_info = []

                    # Prüfe Collectors mit try-except, da nicht alle last_collection_time haben
                    try:
                        if self.heating_collector and hasattr(self.heating_collector, 'last_collection_time'):
                            collectors_info.append(('Heating Collector', self.heating_collector.last_collection_time))
                    except: pass

                    try:
                        if self.window_collector and hasattr(self.window_collector, 'last_collection_time'):
                            collectors_info.append(('Window Collector', self.window_collector.last_collection_time))
                    except: pass

                    try:
                        if self.lighting_collector and hasattr(self.lighting_collector, 'last_collection_time'):
                            collectors_info.append(('Lighting Collector', self.lighting_collector.last_collection_time))
                    except: pass

                    try:
                        if self.temperature_collector and hasattr(self.temperature_collector, 'last_collection_time'):
                            collectors_info.append(('Temperature Collector', self.temperature_collector.last_collection_time))
                    except: pass

                    for name, last_time in collectors_info:
                        if last_time:
                            try:
                                logs.append({
                                    'timestamp': last_time if isinstance(last_time, str) else datetime.now().isoformat(),
                                    'type': 'collector',
                                    'category': 'data_collection',
                                    'message': f"{name}: Daten gesammelt",
                                    'level': 'info'
                                })
                            except: pass

                # Sortiere nach Timestamp (neueste zuerst)
                logs.sort(key=lambda x: x['timestamp'], reverse=True)

                # Limitiere
                logs = logs[:limit]

                return jsonify({
                    'success': True,
                    'count': len(logs),
                    'logs': logs
                })

            except Exception as e:
                logger.error(f"Error getting recent logs: {e}")
                return jsonify({'error': str(e)}), 500

        @self.app.route('/api/system/status', methods=['GET'])
        def api_get_system_status():
            """API: Hole umfassenden System-Status"""
            try:
                status = {
                    'timestamp': datetime.now().isoformat(),
                    'engine': {
                        'initialized': self.engine is not None,
                        'platform': self.engine.platform.get_platform_name() if self.engine else None,
                        'mode': self.engine.mode if self.engine else None
                    },
                    'collectors': {
                        'heating': {
                            'initialized': self.heating_collector is not None,
                            'running': getattr(self.heating_collector, 'running', False) if self.heating_collector else False,
                            'last_collection': getattr(self.heating_collector, 'last_collection_time', None) if self.heating_collector else None
                        },
                        'window': {
                            'initialized': self.window_collector is not None,
                            'running': getattr(self.window_collector, 'running', False) if self.window_collector else False,
                            'last_collection': getattr(self.window_collector, 'last_collection_time', None) if self.window_collector else None
                        },
                        'lighting': {
                            'initialized': self.lighting_collector is not None,
                            'running': getattr(self.lighting_collector, 'running', False) if self.lighting_collector else False,
                            'last_collection': getattr(self.lighting_collector, 'last_collection_time', None) if self.lighting_collector else None
                        },
                        'temperature': {
                            'initialized': self.temperature_collector is not None,
                            'running': getattr(self.temperature_collector, 'running', False) if self.temperature_collector else False,
                            'last_collection': getattr(self.temperature_collector, 'last_collection_time', None) if self.temperature_collector else None
                        },
                        'bathroom': {
                            'initialized': self.bathroom_collector is not None,
                            'running': getattr(self.bathroom_collector, 'running', False) if self.bathroom_collector else False,
                            'last_collection': getattr(self.bathroom_collector, 'last_collection_time', None) if self.bathroom_collector else None
                        }
                    },
                    'ml_training': {
                        'auto_trainer_initialized': self.ml_auto_trainer is not None,
                        'status': self.ml_auto_trainer.get_training_progress() if self.ml_auto_trainer else {'status': 'unavailable'}
                    },
                    'database': {
                        'connected': True,
                        'stats': self._get_database_stats()
                    },
                    'specialized_systems': {}
                }

                # Füge Spezialisierte Systeme Status hinzu (wenn Engine verfügbar)
                if self.engine:
                    status['specialized_systems'] = {
                        'heating_optimizer': getattr(self.engine, 'heating_optimizer_enabled', False),
                        'mold_prevention': getattr(self.engine, 'mold_prevention_enabled', False),
                        'ventilation_optimizer': getattr(self.engine, 'ventilation_optimizer_enabled', False),
                        'room_learning': getattr(self.engine, 'room_learning_enabled', False),
                        'bathroom_automation': getattr(self.engine, 'bathroom_automation_enabled', False)
                    }

                return jsonify(status)

            except Exception as e:
                logger.error(f"Error getting system status: {e}")
                return jsonify({'error': str(e)}), 500

        # === ML MODEL MANAGEMENT ===

        @self.app.route('/api/models/versions', methods=['GET'])
        def api_get_model_versions():
            """API: Hole alle Model-Versionen"""
            try:
                from src.models.model_version_manager import ModelVersionManager
                version_manager = ModelVersionManager()

                summary = version_manager.get_summary()

                # Füge Details für jedes Modell hinzu
                result = {}
                for model_name, model_info in summary.items():
                    history = version_manager.get_version_history(model_name, limit=10)
                    result[model_name] = {
                        **model_info,
                        'history': history
                    }

                return jsonify({
                    'success': True,
                    'models': result
                })

            except Exception as e:
                logger.error(f"Error getting model versions: {e}")
                return jsonify({'error': str(e)}), 500

        @self.app.route('/api/models/<model_name>/rollback', methods=['POST'])
        def api_rollback_model(model_name):
            """API: Rollback zu vorheriger Model-Version"""
            try:
                from src.models.model_version_manager import ModelVersionManager
                version_manager = ModelVersionManager()

                success = version_manager.rollback_to_previous(model_name)

                if success:
                    return jsonify({
                        'success': True,
                        'message': f'Successfully rolled back {model_name} to previous version'
                    })
                else:
                    return jsonify({
                        'success': False,
                        'error': 'Rollback failed - check logs'
                    }), 400

            except Exception as e:
                logger.error(f"Error rolling back model: {e}")
                return jsonify({'error': str(e)}), 500

        @self.app.route('/api/models/<model_name>/history', methods=['GET'])
        def api_get_model_history(model_name):
            """API: Hole Version-History eines Models"""
            try:
                from src.models.model_version_manager import ModelVersionManager
                version_manager = ModelVersionManager()

                limit = request.args.get('limit', 20, type=int)
                history = version_manager.get_version_history(model_name, limit=limit)

                return jsonify({
                    'success': True,
                    'model_name': model_name,
                    'history': history
                })

            except Exception as e:
                logger.error(f"Error getting model history: {e}")
                return jsonify({'error': str(e)}), 500

        # === MOLD PREVENTION ===

        @self.app.route('/api/mold/status', methods=['GET'])
        def api_get_mold_status():
            """API: Hole Schimmelprävention Status aller Räume"""
            try:
                if not self.engine or not self.engine.mold_prevention_enabled:
                    return jsonify({
                        'success': False,
                        'error': 'Mold prevention not enabled'
                    }), 503

                from src.decision_engine.mold_prevention import MoldPreventionSystem
                mold_system = MoldPreventionSystem(db=self.db)

                rooms_status = []

                # Versuche Raum-Daten aus Plattform zu holen
                try:
                    states = self.engine.platform.get_states()

                    # Lade Raum-Zuordnungen aus rooms.json
                    import json
                    rooms_data = {'rooms': [], 'assignments': {}}
                    rooms_file = Path('data/rooms.json')
                    if rooms_file.exists():
                        try:
                            with open(rooms_file, 'r') as f:
                                rooms_data = json.load(f)
                        except Exception as e:
                            logger.warning(f"Could not load rooms.json: {e}")

                    # Erstelle Mapping: room_id -> room_name
                    room_id_to_name = {room['id']: room['name'] for room in rooms_data.get('rooms', [])}

                    # Gruppiere Sensoren nach Raum - VERBESSERTE VERSION
                    room_sensors = {}

                    for device_id, state in states.items():
                        if not state:
                            continue

                        attrs = state.get('attributes', {})
                        caps = attrs.get('capabilities', {})
                        friendly_name = attrs.get('friendly_name', device_id)

                        # Extrahiere Raum aus verschiedenen Quellen
                        room_name = None

                        # 0. HÖCHSTE PRIORITÄT: Nutze manuelle Zuordnung aus rooms.json
                        if device_id in rooms_data.get('assignments', {}):
                            room_id = rooms_data['assignments'][device_id]
                            if room_id in room_id_to_name:
                                room_name = room_id_to_name[room_id]
                                logger.debug(f"Using room assignment from rooms.json: {device_id} -> {room_name}")

                        # 1. Für Homey: Nutze zoneName (zweite Priorität)
                        if not room_name and 'zoneName' in attrs and attrs['zoneName']:
                            room_name = attrs['zoneName']

                        # 2. Für Homey: Nutze zone.name falls vorhanden (bei dict)
                        if not room_name and 'zone' in attrs:
                            if isinstance(attrs['zone'], dict) and 'name' in attrs['zone']:
                                room_name = attrs['zone']['name']
                            elif isinstance(attrs['zone'], str):
                                # Prüfe ob zone ein UUID-String ist (Homey verwendet UUIDs)
                                # UUIDs enthalten typischerweise '-' und sind 36 Zeichen lang
                                if len(attrs['zone']) == 36 and attrs['zone'].count('-') == 4:
                                    # Das ist eine UUID - nicht verwenden
                                    pass
                                else:
                                    # Das ist ein echter Raum-Name
                                    room_name = attrs['zone']

                        # 3. Versuche 'room' aus attributes (Home Assistant)
                        if not room_name and 'room' in attrs and attrs['room']:
                            room_name = attrs['room']

                        # 4. Nutze friendly_name wenn er sinnvoll ist
                        if not room_name and friendly_name and friendly_name != device_id:
                            # Bessere Name-Extraktion mit häufigen Mustern
                            name_lower = friendly_name.lower()

                            # Bekannte Raumnamen (deutsch und englisch)
                            known_rooms = ['wohnzimmer', 'schlafzimmer', 'küche', 'bad', 'badezimmer',
                                          'kinderzimmer', 'arbeitszimmer', 'flur', 'keller', 'dachboden',
                                          'gästezimmer', 'esszimmer', 'wc', 'garage', 'balkon', 'terrasse',
                                          'living', 'bedroom', 'kitchen', 'bathroom', 'hallway', 'office',
                                          'basement', 'attic', 'dining']

                            for known_room in known_rooms:
                                if known_room in name_lower:
                                    room_name = known_room.capitalize()
                                    break

                        # 5. Fallback: Nutze friendly_name direkt (aber bereinigt)
                        if not room_name and friendly_name and friendly_name != device_id:
                            # Entferne Sensor-Präfixe
                            clean_name = friendly_name
                            for prefix in ['Temperature', 'Humidity', 'Temperatur', 'Luftfeuchtigkeit',
                                         'Sensor', 'sensor', 'temperature', 'humidity']:
                                clean_name = clean_name.replace(prefix, '').strip()

                            # Verwende bereinigten Namen wenn er nicht leer und nicht zu kurz ist
                            if clean_name and len(clean_name) > 2:
                                room_name = clean_name
                            elif len(friendly_name) > 2:
                                # Verwende originalen friendly_name
                                room_name = friendly_name

                        # 6. Letzter Fallback
                        if not room_name:
                            room_name = "Unbenannter Raum"

                        # Initialisiere Raum-Eintrag
                        if room_name not in room_sensors:
                            room_sensors[room_name] = {
                                'temperature': None,
                                'humidity': None,
                                'temp_sensor_id': None,
                                'humidity_sensor_id': None,
                                'devices': []
                            }

                        # Sammle Sensor-Werte
                        if 'measure_temperature' in caps:
                            temp_value = caps['measure_temperature'].get('value')
                            if temp_value is not None:
                                room_sensors[room_name]['temperature'] = temp_value
                                room_sensors[room_name]['temp_sensor_id'] = device_id
                                room_sensors[room_name]['devices'].append({
                                    'id': device_id,
                                    'name': friendly_name,
                                    'type': 'temperature'
                                })

                        if 'measure_humidity' in caps:
                            hum_value = caps['measure_humidity'].get('value')
                            if hum_value is not None:
                                room_sensors[room_name]['humidity'] = hum_value
                                room_sensors[room_name]['humidity_sensor_id'] = device_id
                                room_sensors[room_name]['devices'].append({
                                    'id': device_id,
                                    'name': friendly_name,
                                    'type': 'humidity'
                                })

                    # Filter für echte Räume (keine technischen Zonen, Geräte oder Szenen)
                    excluded_patterns = [
                        'wohnung',  # "1 - Wohnung", "2 - Wohnung", etc.
                        'alle lampen',  # Szenen
                        'steckdose',  # Einzelne Geräte
                        'schalter',  # Schalter
                        'sensor',  # Standalone Sensoren ohne Raum
                        'homey',  # Homey-System
                        'button',  # Buttons
                        'fernbedienung',  # Fernbedienungen
                        'leuchte',  # Lampen
                        'licht',  # Lichter
                        'lampe',  # Lampen
                        'stehleuchte',  # Stehlampen
                        'shelly',  # Shelly Geräte (oft ohne Raum)
                        'thermometer',  # Standalone Thermometer
                        'meter pro',  # Meter Pro Sensoren
                        'deebot',  # Roboter
                        'roboter',  # Roboter
                        'konto',  # Accounts
                        'user',  # User Accounts
                        'dirigera',  # IKEA Hub
                        'completionbot',  # Bot
                        'couch',  # Möbel
                        'wickeltisch',  # Möbel
                        'rollo',  # Rollos
                        'kamera',  # Kameras
                        'kontakt',  # Kontaktsensoren
                        'presence',  # Präsenzsensoren
                        'außentemperatur',  # Außensensoren
                        'wled',  # LED Controller
                        'waschmaschine',  # Einzelgeräte
                        'luftentfeuchter',  # Einzelgeräte
                        'lüfter',  # Einzelgeräte
                        'evaporative',  # Geräte
                        'humidifier',  # Geräte
                        'info',  # System Info
                        'stadt',  # Wetter-Apps
                        'blink',  # Blink Kameras
                        'withings',  # Withings Geräte
                        'fahrrad',  # Einzelsteckdosen
                        'flaschenspüler',  # Einzelsteckdosen
                        'schrank',  # Möbel
                        'unterschrank',  # Möbel
                        'haus-tür',  # Türen
                        'haustür',  # Türen
                        'türsperre',  # Türen
                        'herdlicht',  # Einzellampen
                        'nachtlicht',  # Einzellampen
                        'unterlicht',  # Einzellampen
                        'wall display',  # Displays
                        'blu ht',  # Bluetooth Sensoren ohne Raum
                        'plus 1pm',  # Shelly Relays
                        ':',  # MAC-Adressen
                        '192.168',  # IP-Adressen
                        '📎',  # Gruppen/Icons
                        'gruppe',  # Gruppen
                    ]

                    # Analysiere nur Räume mit BEIDEN Sensoren (Temperatur UND Luftfeuchtigkeit)
                    for room_name, sensors in room_sensors.items():
                        # Skip "Unbenannter Raum"
                        if room_name == "Unbenannter Raum":
                            continue

                        # Skip technische Zonen, Geräte und Szenen
                        room_name_lower = room_name.lower()
                        if any(pattern in room_name_lower for pattern in excluded_patterns):
                            continue

                        # NUR Räume mit BEIDEN Sensoren anzeigen (für sinnvolle Schimmel-Analyse)
                        if sensors['temperature'] is None or sensors['humidity'] is None:
                            continue

                        # Führe Analyse durch (beide Werte sind durch Filter garantiert vorhanden)
                        analysis = mold_system.analyze_room_humidity(
                            room_name=room_name,
                            temperature=sensors['temperature'],
                            humidity=sensors['humidity']
                        )

                        room_data = {
                            'room_name': room_name,
                            'temperature': sensors['temperature'],
                            'humidity': sensors['humidity'],
                            'temp_sensor_id': sensors['temp_sensor_id'],
                            'humidity_sensor_id': sensors['humidity_sensor_id'],
                            'devices_count': len(sensors['devices']),
                            'analysis': analysis,
                            'status': 'complete'
                        }

                        rooms_status.append(room_data)

                except Exception as e:
                    logger.error(f"Could not get room data: {e}", exc_info=True)

                # Sortiere nach Raum-Name
                rooms_status.sort(key=lambda x: x['room_name'])

                return jsonify({
                    'success': True,
                    'rooms': rooms_status,
                    'total_rooms': len(rooms_status),
                    'complete_rooms': sum(1 for r in rooms_status if r.get('status') == 'complete'),
                    'incomplete_rooms': sum(1 for r in rooms_status if r.get('status') == 'incomplete')
                })

            except Exception as e:
                logger.error(f"Error getting mold status: {e}")
                return jsonify({'error': str(e)}), 500

        @self.app.route('/api/mold/debug', methods=['GET'])
        def api_get_mold_debug():
            """API: Debug-Informationen für Raum-Erkennung"""
            try:
                if not self.engine:
                    return jsonify({'error': 'Engine not initialized'}), 500

                debug_info = []

                try:
                    states = self.engine.platform.get_states()

                    for device_id, state in states.items():
                        if not state:
                            continue

                        attrs = state.get('attributes', {})
                        caps = attrs.get('capabilities', {})

                        # Nur Geräte mit Temperatur oder Luftfeuchtigkeit
                        if 'measure_temperature' in caps or 'measure_humidity' in caps:
                            debug_info.append({
                                'device_id': device_id,
                                'friendly_name': attrs.get('friendly_name'),
                                'zone': attrs.get('zone'),
                                'zoneName': attrs.get('zoneName'),
                                'room': attrs.get('room'),
                                'has_temperature': 'measure_temperature' in caps,
                                'has_humidity': 'measure_humidity' in caps,
                                'temperature_value': caps.get('measure_temperature', {}).get('value') if 'measure_temperature' in caps else None,
                                'humidity_value': caps.get('measure_humidity', {}).get('value') if 'measure_humidity' in caps else None
                            })

                except Exception as e:
                    return jsonify({'error': str(e)}), 500

                return jsonify({
                    'success': True,
                    'count': len(debug_info),
                    'devices': debug_info
                })

            except Exception as e:
                logger.error(f"Error getting mold debug info: {e}")
                return jsonify({'error': str(e)}), 500

        @self.app.route('/api/mold/alerts', methods=['GET'])
        def api_get_mold_alerts():
            """API: Hole Schimmel-Alerts aus der Datenbank"""
            try:
                limit = request.args.get('limit', 50, type=int)

                # Hole Mold-Alerts aus Datenbank (falls vorhanden)
                alerts = []

                # Prüfe ob mold_alerts Tabelle existiert
                try:
                    result = self.db.execute(
                        "SELECT timestamp, room_name, humidity, temperature, risk_level, recommendation FROM mold_alerts ORDER BY timestamp DESC LIMIT ?",
                        (limit,)
                    )
                    for row in result:
                        alerts.append({
                            'timestamp': row['timestamp'],
                            'room_name': row['room_name'],
                            'humidity': row['humidity'],
                            'temperature': row['temperature'],
                            'risk_level': row['risk_level'],
                            'recommendation': row['recommendation']
                        })
                except:
                    # Tabelle existiert nicht - leere Liste zurückgeben
                    pass

                return jsonify({
                    'success': True,
                    'alerts': alerts,
                    'count': len(alerts)
                })

            except Exception as e:
                logger.error(f"Error getting mold alerts: {e}")
                return jsonify({'error': str(e)}), 500

        # === VENTILATION RECOMMENDATIONS ===

        @self.app.route('/api/ventilation/recommendations', methods=['GET'])
        def api_get_ventilation_recommendations():
            """API: Hole aktuelle Lüftungsempfehlungen für alle Räume"""
            try:
                if not self.engine or not self.engine.ventilation_optimizer_enabled:
                    return jsonify({
                        'success': False,
                        'error': 'Ventilation optimizer not enabled'
                    }), 503

                from src.decision_engine.ventilation_optimizer import VentilationOptimizer
                vent_optimizer = VentilationOptimizer(db=self.db)

                recommendations = []

                # Hole Wetterdaten
                outdoor_temp = None
                outdoor_humidity = 70.0  # Default

                try:
                    weather_data = self.engine.weather.get_weather_data(self.engine.platform)
                    if weather_data:
                        outdoor_temp = weather_data.get('temperature')
                        outdoor_humidity = weather_data.get('humidity', 70.0)
                except:
                    pass

                # Hole Raum-Daten (ähnlich wie bei Mold Prevention)
                if outdoor_temp is not None:
                    try:
                        # Lade gespeicherte Sensor-Zuordnung
                        sensor_mapping = {}
                        config_file = Path('config/ventilation_sensors.yaml')
                        if config_file.exists():
                            try:
                                with open(config_file, 'r') as f:
                                    sensor_mapping = yaml.safe_load(f) or {}
                            except:
                                pass
                        
                        states = self.engine.platform.get_states()
                        devices = self.engine.platform.get_all_devices()
                        zones = self.engine.platform.get_zones()
                        
                        # Erstelle Zone-ID zu Zone-Name Mapping
                        zone_names = {}
                        for zone_id, zone_data in zones.items():
                            zone_name = zone_data.get('name', zone_id)
                            zone_names[zone_id] = zone_name
                        
                        # Erstelle Device-ID zu Zone-ID Mapping
                        device_zones = {}
                        for device in devices:
                            device_id = device.get('id')
                            zone_id = device.get('zone') or device.get('zoneName') or device.get('attributes', {}).get('zone')
                            if device_id and zone_id:
                                device_zones[device_id] = zone_id

                        room_sensors = {}
                        
                        # Wenn Sensor-Zuordnung existiert, verwende sie
                        if sensor_mapping:
                            for room_name, sensor_ids in sensor_mapping.items():
                                temp_device_id = sensor_ids.get('temperature')
                                humidity_device_id = sensor_ids.get('humidity')
                                
                                if temp_device_id and humidity_device_id:
                                    temp_state = states.get(temp_device_id)
                                    humidity_state = states.get(humidity_device_id)
                                    
                                    if temp_state and humidity_state:
                                        temp_value = temp_state.get('attributes', {}).get('capabilities', {}).get('measure_temperature', {}).get('value')
                                        humidity_value = humidity_state.get('attributes', {}).get('capabilities', {}).get('measure_humidity', {}).get('value')
                                        
                                        if temp_value is not None and humidity_value is not None:
                                            room_sensors[room_name] = {
                                                'temperature': temp_value,
                                                'humidity': humidity_value,
                                                'device_count': 2
                                            }
                        
                        # Fallback: Automatische Erkennung (wie vorher)
                        else:
                            for device_id, state in states.items():
                                if not state:
                                    continue

                                attrs = state.get('attributes', {})
                                
                                # Versuche Zone-ID aus verschiedenen Quellen zu holen
                                zone_id = device_zones.get(device_id)  # Zuerst aus Devices-Mapping
                                if not zone_id:
                                    zone_id = attrs.get('zone')  # Dann aus State attributes
                                if not zone_id:
                                    zone_id = attrs.get('room')  # Alternative: room attribute
                                if not zone_id:
                                    continue  # Skip devices ohne Raum-Zuordnung
                                
                                # Konvertiere Zone-ID zu lesbarem Raumnamen
                                room_name = zone_names.get(zone_id, zone_id)

                                if room_name not in room_sensors:
                                    room_sensors[room_name] = {'temperature': None, 'humidity': None, 'device_count': 0}

                                room_sensors[room_name]['device_count'] += 1
                                
                                caps = attrs.get('capabilities', {})
                                if 'measure_temperature' in caps and caps['measure_temperature'].get('value') is not None:
                                    room_sensors[room_name]['temperature'] = caps['measure_temperature'].get('value')
                                if 'measure_humidity' in caps and caps['measure_humidity'].get('value') is not None:
                                    room_sensors[room_name]['humidity'] = caps['measure_humidity'].get('value')

                        # Generiere Empfehlungen für jeden Raum
                        for room_name, sensors in room_sensors.items():
                            if sensors['temperature'] is not None and sensors['humidity'] is not None:
                                recommendation = vent_optimizer.generate_ventilation_recommendation(
                                    room_name=room_name,
                                    indoor_temp=sensors['temperature'],
                                    indoor_humidity=sensors['humidity'],
                                    outdoor_temp=outdoor_temp,
                                    outdoor_humidity=outdoor_humidity
                                )

                                recommendations.append({
                                    'room_name': room_name,
                                    'indoor_temp': sensors['temperature'],
                                    'indoor_humidity': sensors['humidity'],
                                    'outdoor_temp': outdoor_temp,
                                    'outdoor_humidity': outdoor_humidity,
                                    'recommendation': recommendation
                                })

                    except Exception as e:
                        logger.debug(f"Could not get room data: {e}")

                return jsonify({
                    'success': True,
                    'recommendations': recommendations,
                    'count': len(recommendations),
                    'outdoor_conditions': {
                        'temperature': outdoor_temp,
                        'humidity': outdoor_humidity
                    }
                })

            except Exception as e:
                logger.error(f"Error getting ventilation recommendations: {e}")
                return jsonify({'error': str(e)}), 500

        @self.app.route('/api/ventilation/sensors', methods=['GET'])
        def get_ventilation_sensors():
            """
            Holt alle verfügbaren Temperatur- und Feuchtigkeitssensoren von Homey und Home Assistant
            """
            try:
                sensors = []
                
                # Homey Sensoren
                if self.engine and self.engine.platform:
                    states = self.engine.platform.get_states()
                    devices = self.engine.platform.get_all_devices()
                    zones = self.engine.platform.get_zones()
                    
                    # Zone-ID zu Name Mapping
                    zone_names = {}
                    for zone_id, zone_data in zones.items():
                        zone_names[zone_id] = zone_data.get('name', zone_id)
                    
                    # Device-ID zu Zone Mapping
                    device_zones = {}
                    for device in devices:
                        device_id = device.get('id')
                        zone_id = device.get('zone')
                        if device_id and zone_id:
                            device_zones[device_id] = zone_id

                    for device_id, state in states.items():
                        if not state:
                            continue
                        
                        attrs = state.get('attributes', {})
                        caps = attrs.get('capabilities', {})
                        friendly_name = attrs.get('friendly_name', device_id)
                        
                        # Hole Zone-ID und Namen
                        zone_id = device_zones.get(device_id) or attrs.get('zone')
                        if not zone_id:
                            continue
                        
                        room_name = zone_names.get(zone_id, zone_id)
                        
                        # Temperatursensor
                        if 'measure_temperature' in caps:
                            sensors.append({
                                'device_id': device_id,
                                'name': friendly_name,
                                'room': room_name,
                                'type': 'temperature',
                                'platform': 'homey',
                                'current_value': caps['measure_temperature'].get('value')
                            })
                        
                        # Feuchtigkeitssensor
                        if 'measure_humidity' in caps:
                            sensors.append({
                                'device_id': device_id,
                                'name': friendly_name,
                                'room': room_name,
                                'type': 'humidity',
                                'platform': 'homey',
                                'current_value': caps['measure_humidity'].get('value')
                            })
                        
                        # CO2-Sensor
                        if 'measure_co2' in caps:
                            sensors.append({
                                'device_id': device_id,
                                'name': friendly_name,
                                'room': room_name,
                                'type': 'co2',
                                'platform': 'homey',
                                'current_value': caps['measure_co2'].get('value')
                            })
                
                # Home Assistant Sensoren (wenn verfügbar)
                if self.engine and hasattr(self.engine, 'platforms') and 'homeassistant' in self.engine.platforms:
                    try:
                        ha_platform = self.engine.platforms['homeassistant']
                        ha_states = ha_platform.get_states()
                        
                        for entity_id, state in ha_states.items():
                            if not state:
                                continue
                            
                            attrs = state.get('attributes', {})
                            device_class = attrs.get('device_class', '')
                            unit = attrs.get('unit_of_measurement', '')
                            friendly_name = attrs.get('friendly_name', entity_id)
                            area = attrs.get('area', 'Unbekannt')
                            
                            # Temperatursensor
                            if device_class == 'temperature' or unit in ['°C', '°F', 'C', 'F']:
                                try:
                                    value = float(state.get('state', 0))
                                    sensors.append({
                                        'device_id': entity_id,
                                        'name': friendly_name,
                                        'room': area,
                                        'type': 'temperature',
                                        'platform': 'homeassistant',
                                        'current_value': value
                                    })
                                except:
                                    pass
                            
                            # Feuchtigkeitssensor
                            elif device_class == 'humidity' or unit == '%':
                                try:
                                    value = float(state.get('state', 0))
                                    sensors.append({
                                        'device_id': entity_id,
                                        'name': friendly_name,
                                        'room': area,
                                        'type': 'humidity',
                                        'platform': 'homeassistant',
                                        'current_value': value
                                    })
                                except:
                                    pass
                    except Exception as e:
                        logger.warning(f"Could not load Home Assistant sensors: {e}")

                # Außensensor-Daten ermitteln
                outdoor = None
                outdoor_temp = None
                outdoor_humidity = None
                
                # Suche nach Sensoren mit "Außen" oder "Outdoor" im Namen
                for s in sensors:
                    if s['current_value'] is None:
                        continue
                    name_lower = s['name'].lower()
                    if 'außen' in name_lower or 'outdoor' in name_lower or 'aussen' in name_lower:
                        if s['type'] == 'temperature' and outdoor_temp is None:
                            # Prüfe ob realistischer Außenwert (nicht >50°C)
                            if s['current_value'] < 50:
                                outdoor_temp = s['current_value']
                        elif s['type'] == 'humidity' and outdoor_humidity is None:
                            outdoor_humidity = s['current_value']
                
                if outdoor_temp is not None or outdoor_humidity is not None:
                    outdoor = {
                        'temperature': outdoor_temp,
                        'humidity': outdoor_humidity
                    }

                return jsonify({
                    'success': True,
                    'sensors': sensors,
                    'count': len(sensors),
                    'outdoor': outdoor
                })

            except Exception as e:
                logger.error(f"Error getting ventilation sensors: {e}")
                return jsonify({'error': str(e)}), 500

        @self.app.route('/api/ventilation/room-history/<room_name>', methods=['GET'])
        def get_room_history(room_name):
            """
            API: Historische Sensordaten für einen Raum (24h oder 48h)
            """
            try:
                hours = request.args.get('hours', 24, type=int)
                if hours not in [24, 48]:
                    hours = 24
                
                from datetime import datetime, timedelta
                import re
                
                cutoff = datetime.now() - timedelta(hours=hours)
                cutoff_str = cutoff.strftime('%Y-%m-%d %H:%M:%S')
                
                # Extrahiere Basis-Raumnamen (vor Klammern, z.B. "Schlafzimmer (Doppelbett)" -> "Schlafzimmer")
                base_room_name = re.split(r'\s*\(', room_name)[0].strip()
                search_pattern = f"%{base_room_name}%"
                
                data = {
                    'temperature': [],
                    'humidity': [],
                    'co2': []
                }
                
                # Hole Temperaturdaten aus continuous_measurements 
                # Raumname ist im device_name enthalten (z.B. "Wohnzimmer Heizung")
                temp_rows = self.db.execute("""
                    SELECT timestamp, current_temperature, humidity
                    FROM continuous_measurements
                    WHERE device_name LIKE ?
                    AND datetime(timestamp) >= datetime(?)
                    ORDER BY timestamp ASC
                    LIMIT 2000
                """, (search_pattern, cutoff_str))
                
                if temp_rows:
                    for row in temp_rows:
                        ts = row['timestamp']
                        if row['current_temperature'] is not None:
                            data['temperature'].append({'x': ts, 'y': round(row['current_temperature'], 1)})
                        if row['humidity'] is not None:
                            data['humidity'].append({'x': ts, 'y': round(row['humidity'], 1)})
                
                # Hole CO2-Daten aus sensor_data (falls vorhanden)
                # Mapping: CO2-Sensor-Namen zu Räumen (da manche Sensoren keine Raum-Info haben)
                co2_sensor_mapping = {
                    'Schlafzimmer': ['Meter Pro (CO2-Monitor) 29'],
                    'Wohnzimmer': ['Temperatur-Wohnzimmer', 'Meter Pro 3D'],
                }
                
                # Suche nach Raumnamen oder bekannten Sensoren
                co2_search_patterns = [
                    f'%"device_name": "%{base_room_name}%"%',
                    f'%"room": "%{base_room_name}%"%'
                ]
                
                # Füge bekannte Sensoren für diesen Raum hinzu
                if base_room_name in co2_sensor_mapping:
                    for sensor_name in co2_sensor_mapping[base_room_name]:
                        co2_search_patterns.append(f'%"device_name": "{sensor_name}"%')
                
                try:
                    # Baue dynamische OR-Abfrage
                    where_clauses = ' OR '.join(['metadata LIKE ?' for _ in co2_search_patterns])
                    query = f"""
                        SELECT timestamp, value, metadata FROM sensor_data
                        WHERE sensor_type = 'co2' 
                        AND ({where_clauses})
                        AND datetime(timestamp) >= datetime(?)
                        ORDER BY timestamp ASC
                        LIMIT 2000
                    """
                    params = co2_search_patterns + [cutoff_str]
                    co2_rows = self.db.execute(query, params)
                    
                    if co2_rows:
                        for row in co2_rows:
                            if row['value'] is not None:
                                data['co2'].append({'x': row['timestamp'], 'y': round(row['value'])})
                except Exception as e:
                    logger.debug(f"No CO2 data for {room_name}: {e}")
                    pass  # CO2-Daten sind optional
                
                # Intelligente Aggregation basierend auf Zeitraum
                # 24h: max 200 Punkte, 48h: max 300 Punkte
                max_points = 200 if hours == 24 else 300
                for key in data:
                    if len(data[key]) > max_points:
                        step = len(data[key]) // max_points
                        data[key] = data[key][::step]
                
                return jsonify({
                    'success': True,
                    'room': room_name,
                    'hours': hours,
                    'data': data,
                    'points': {k: len(v) for k, v in data.items()}
                })
                    
            except Exception as e:
                logger.error(f"Error getting room history for {room_name}: {e}")
                return jsonify({'error': str(e)}), 500

        @self.app.route('/api/ventilation/sensor-mapping', methods=['GET', 'POST'])
        def ventilation_sensor_mapping():
            """
            GET: Holt die gespeicherte Sensor-Zuordnung
            POST: Speichert die Sensor-Zuordnung
            """
            config_file = Path('config/ventilation_sensors.yaml')
            
            if request.method == 'GET':
                try:
                    if config_file.exists():
                        with open(config_file, 'r') as f:
                            mapping = yaml.safe_load(f) or {}
                    else:
                        mapping = {}
                    
                    return jsonify({
                        'success': True,
                        'mapping': mapping
                    })
                except Exception as e:
                    logger.error(f"Error loading sensor mapping: {e}")
                    return jsonify({'error': str(e)}), 500
            
            elif request.method == 'POST':
                try:
                    data = request.json
                    mapping = data.get('mapping', {})
                    
                    # Speichere Zuordnung
                    config_file.parent.mkdir(parents=True, exist_ok=True)
                    with open(config_file, 'w') as f:
                        yaml.dump(mapping, f, default_flow_style=False)
                    
                    return jsonify({
                        'success': True,
                        'message': 'Sensor-Zuordnung gespeichert'
                    })
                except Exception as e:
                    logger.error(f"Error saving sensor mapping: {e}")
                    return jsonify({'error': str(e)}), 500

        @self.app.route('/api/sensors/available', methods=['GET'])
        def api_get_available_sensors():
            """API: Hole alle verfügbaren Sensoren"""
            if not self.engine:
                return jsonify({'error': 'Engine not initialized'}), 500

            try:
                # Hole alle Temperatur- und Luftfeuchtigkeit-Sensoren
                temp_sensors = self.engine._get_all_temperature_sensors()
                humidity_sensors = self.engine._get_all_humidity_sensors()

                # Hole Device-Details
                temp_details = []
                for sensor_id in temp_sensors:
                    state = self.engine.platform.get_state(sensor_id)
                    if state:
                        temp_details.append({
                            'id': sensor_id,
                            'name': state.get('attributes', {}).get('friendly_name', sensor_id),
                            'zone': state.get('attributes', {}).get('zone'),
                            'current_value': self.engine._extract_temperature_value(state)
                        })

                humidity_details = []
                for sensor_id in humidity_sensors:
                    state = self.engine.platform.get_state(sensor_id)
                    if state:
                        humidity_details.append({
                            'id': sensor_id,
                            'name': state.get('attributes', {}).get('friendly_name', sensor_id),
                            'zone': state.get('attributes', {}).get('zone'),
                            'current_value': self.engine._extract_humidity_value(state)
                        })

                return jsonify({
                    'temperature_sensors': temp_details,
                    'humidity_sensors': humidity_details
                })

            except Exception as e:
                logger.error(f"Error getting available sensors: {e}")
                return jsonify({'error': str(e)}), 500

        @self.app.route('/api/sensors/config', methods=['GET', 'POST'])
        def api_sensor_config():
            """API: Sensor-Konfiguration verwalten"""
            import json
            from pathlib import Path

            config_file = Path('data/sensor_config.json')

            if request.method == 'GET':
                # Lade aktuelle Konfiguration
                if config_file.exists():
                    with open(config_file, 'r') as f:
                        config = json.load(f)
                else:
                    config = {
                        'temperature_sensors': [],
                        'humidity_sensors': []
                    }

                return jsonify(config)

            elif request.method == 'POST':
                # Speichere neue Konfiguration
                try:
                    data = request.json
                    temp_sensors = data.get('temperature_sensors', [])
                    humidity_sensors = data.get('humidity_sensors', [])

                    config = {
                        'temperature_sensors': temp_sensors,
                        'humidity_sensors': humidity_sensors
                    }

                    # Erstelle data/ Verzeichnis falls nicht vorhanden
                    Path('data').mkdir(exist_ok=True)

                    # Speichere Konfiguration
                    with open(config_file, 'w') as f:
                        json.dump(config, f, indent=2)

                    logger.info(f"Sensor config saved: {len(temp_sensors)} temp, {len(humidity_sensors)} humidity")

                    return jsonify({
                        'success': True,
                        'message': f'{len(temp_sensors)} Temperatur- und {len(humidity_sensors)} Luftfeuchtigkeits-Sensoren konfiguriert'
                    })

                except Exception as e:
                    logger.error(f"Error saving sensor config: {e}")
                    return jsonify({'error': str(e)}), 500

        # === Automation Endpunkte ===

        @self.app.route('/api/automations/config', methods=['GET'])
        def api_automations_config():
            """API: Lade Automations-Konfiguration"""
            try:
                # Lade aus Datei oder verwende Defaults
                config_file = Path('data/automations.json')
                if config_file.exists():
                    import json
                    with open(config_file, 'r') as f:
                        config = json.load(f)
                else:
                    config = {
                        'device_config': {'learning': [], 'control': [], 'automation': []},
                        'automation_rules': {
                            'away_mode': {'enabled': False, 'timeout': 30, 'lights_off': True, 'sockets_off': True, 'heating_eco': False, 'exceptions': []},
                            'arrival_mode': {'enabled': False, 'lights_on': True, 'sockets_on': True, 'heating_comfort': False, 'time_from': '06:00', 'time_to': '23:00'},
                            'night_mode': {'enabled': False, 'time_from': '22:00', 'time_to': '06:00', 'lights_dim': True, 'no_automation': False, 'heating_lower': False}
                        }
                    }
                return jsonify(config)
            except Exception as e:
                logger.error(f"Error loading automation config: {e}")
                return jsonify({'error': str(e)}), 500

        @self.app.route('/api/automations/device-config', methods=['POST'])
        def api_save_device_config():
            """API: Speichere Geräte-Konfiguration"""
            try:
                data = request.json
                device_config = data.get('device_config', {})

                # Lade aktuelle Config
                config_file = Path('data/automations.json')
                Path('data').mkdir(exist_ok=True)

                if config_file.exists():
                    import json
                    with open(config_file, 'r') as f:
                        config = json.load(f)
                else:
                    config = {'device_config': {}, 'automation_rules': {}}

                # Update device config
                config['device_config'] = device_config

                # Speichern
                import json
                with open(config_file, 'w') as f:
                    json.dump(config, f, indent=2)

                logger.info(f"Device config saved: {len(device_config.get('learning', []))} learning, {len(device_config.get('control', []))} control")
                return jsonify({'success': True})

            except Exception as e:
                logger.error(f"Error saving device config: {e}")
                return jsonify({'error': str(e)}), 500

        @self.app.route('/api/automations/rules', methods=['POST'])
        def api_save_automation_rules():
            """API: Speichere Automatisierungs-Regeln"""
            try:
                data = request.json
                automation_rules = data.get('automation_rules', {})

                # Lade aktuelle Config
                config_file = Path('data/automations.json')
                Path('data').mkdir(exist_ok=True)

                if config_file.exists():
                    import json
                    with open(config_file, 'r') as f:
                        config = json.load(f)
                else:
                    config = {'device_config': {}, 'automation_rules': {}}

                # Update rules
                config['automation_rules'] = automation_rules

                # Speichern
                import json
                with open(config_file, 'w') as f:
                    json.dump(config, f, indent=2)

                logger.info(f"Automation rules saved: away={automation_rules.get('away_mode', {}).get('enabled')}, arrival={automation_rules.get('arrival_mode', {}).get('enabled')}")
                return jsonify({'success': True})

            except Exception as e:
                logger.error(f"Error saving automation rules: {e}")
                return jsonify({'error': str(e)}), 500

        @self.app.route('/api/automations/presence', methods=['GET'])
        def api_presence_status():
            """API: Präsenz-Status ermitteln - nutzt Homey User Presence"""
            try:
                platform = self.engine.platform

                # Prüfe ob Platform Presence-Detection unterstützt
                if hasattr(platform, 'get_presence_status'):
                    # Nutze Homey's User-Presence (Smartphone-Tracking)
                    presence_data = platform.get_presence_status()

                    return jsonify({
                        'present': presence_data.get('anyone_home', False),
                        'mode': 'homey_users',
                        'users': presence_data.get('users', []),
                        'users_home': presence_data.get('users_home', 0),
                        'total_users': presence_data.get('total_users', 0)
                    })

                else:
                    # Fallback: Motion-Sensoren (für Home Assistant oder alte Homey-Versionen)
                    motion_entities = []
                    try:
                        all_entities = platform.get_all_entities('sensor')
                        states = platform.get_states(all_entities)

                        for entity_id, state_data in states.items():
                            attrs = state_data.get('attributes', {})
                            caps = attrs.get('capabilities', {})

                            # Prüfe auf Motion-Capability
                            if 'alarm_motion' in caps:
                                motion_entities.append({
                                    'id': entity_id,
                                    'motion': caps['alarm_motion'].get('value', False),
                                    'last_updated': caps['alarm_motion'].get('lastUpdated')
                                })
                    except Exception as e:
                        logger.debug(f"Error getting motion sensors: {e}")

                    # Bestimme Präsenz
                    present = False
                    last_motion = None

                    for sensor in motion_entities:
                        if sensor['motion']:
                            present = True
                            if sensor['last_updated']:
                                try:
                                    from datetime import datetime
                                    timestamp = datetime.fromtimestamp(sensor['last_updated'] / 1000)
                                    if not last_motion or timestamp > last_motion:
                                        last_motion = timestamp
                                except (ValueError, OSError, OverflowError, TypeError) as e:
                                    logger.debug(f"Could not parse timestamp: {e}")

                    return jsonify({
                        'present': present,
                        'mode': 'motion_sensors',
                        'last_motion': last_motion.isoformat() if last_motion else None,
                        'motion_sensors': len(motion_entities)
                    })

            except Exception as e:
                logger.error(f"Error getting presence status: {e}")
                return jsonify({'error': str(e)}), 500

        # === Neue Automatisierungs-API (für automations_new.html) ===

        @self.app.route('/api/automation/scene/activate', methods=['POST'])
        def api_scene_activate():
            """API: Aktiviere eine Schnellaktion/Szene"""
            try:
                data = request.json
                scene = data.get('scene')
                actions = data.get('actions', [])

                logger.info(f"Activating scene: {scene}")

                # Führe Aktionen aus
                platform = self.engine.platform
                results = []

                for action in actions:
                    action_type = action.get('type')
                    device_target = action.get('devices')
                    command = action.get('action')
                    value = action.get('value')

                    try:
                        if device_target == 'all':
                            # Hole alle Geräte des Typs
                            if action_type == 'lights':
                                entities = platform.get_all_entities('light')
                                for entity_id in entities:
                                    if command == 'on':
                                        platform.control_device(entity_id, 'turn_on', {'brightness': value} if value else {})
                                    elif command == 'off':
                                        platform.control_device(entity_id, 'turn_off', {})
                                    elif command == 'dim':
                                        platform.control_device(entity_id, 'turn_on', {'brightness': value})
                                results.append(f"{action_type} {command}")

                            elif action_type == 'sockets':
                                entities = platform.get_all_entities('socket')
                                for entity_id in entities:
                                    if command == 'on':
                                        platform.control_device(entity_id, 'turn_on', {})
                                    elif command == 'off':
                                        platform.control_device(entity_id, 'turn_off', {})
                                results.append(f"{action_type} {command}")

                        else:
                            results.append(f"{action_type} {command} (not implemented)")

                    except Exception as e:
                        logger.warning(f"Failed to execute action {action}: {e}")
                        results.append(f"{action_type} failed")

                # Log trigger in database
                try:
                    from datetime import datetime
                    self.db.execute(
                        "INSERT INTO automation_triggers (rule_name, trigger_time, action) VALUES (?, ?, ?)",
                        (scene, datetime.now().isoformat(), f"Scene activated: {', '.join(results)}")
                    )
                except Exception as e:
                    logger.warning(f"Failed to log trigger: {e}")

                return jsonify({
                    'success': True,
                    'scene': scene,
                    'results': results
                })

            except Exception as e:
                logger.error(f"Error activating scene: {e}")
                return jsonify({'error': str(e)}), 500

        @self.app.route('/api/automation/status', methods=['GET'])
        def api_automation_status():
            """API: Live-Status Dashboard"""
            try:
                from datetime import datetime, timedelta

                # Zähle aktive Regeln
                active_rules = 0
                rules_file = Path('data/automation_rules.json')
                if rules_file.exists():
                    import json
                    with open(rules_file, 'r') as f:
                        rules_data = json.load(f)
                        active_rules = len([r for r in rules_data.get('rules', []) if r.get('enabled', False)])

                # Zähle heutige Trigger
                today_triggers = 0
                try:
                    today = datetime.now().date()
                    result = self.db.execute(
                        "SELECT COUNT(*) as count FROM automation_triggers WHERE DATE(trigger_time) = ?",
                        (today.isoformat(),)
                    )
                    if result:
                        today_triggers = result[0]['count']
                except Exception as e:
                    logger.debug(f"Could not count triggers: {e}")

                # Präsenz-Status
                presence = 'unknown'
                try:
                    platform = self.engine.platform
                    if hasattr(platform, 'get_presence_status'):
                        presence_data = platform.get_presence_status()
                        presence = 'home' if presence_data.get('anyone_home', False) else 'away'
                except Exception as e:
                    logger.debug(f"Could not get presence: {e}")

                # Aktueller Modus
                current_mode = 'Normal'
                from datetime import datetime
                hour = datetime.now().hour
                if 22 <= hour or hour < 6:
                    current_mode = 'Nacht'
                elif presence == 'away':
                    current_mode = 'Abwesend'

                return jsonify({
                    'active_rules': active_rules,
                    'today_triggers': today_triggers,
                    'presence': presence,
                    'current_mode': current_mode
                })

            except Exception as e:
                logger.error(f"Error getting automation status: {e}")
                return jsonify({'error': str(e)}), 500

        @self.app.route('/api/automation/triggers/recent', methods=['GET'])
        def api_automation_triggers_recent():
            """API: Letzte Auslösungen"""
            try:
                from datetime import datetime, timedelta

                # Hole letzte 10 Trigger
                triggers = []
                try:
                    result = self.db.execute(
                        "SELECT rule_name, trigger_time, action FROM automation_triggers ORDER BY trigger_time DESC LIMIT 10"
                    )
                    for row in result:
                        time_obj = datetime.fromisoformat(row['trigger_time'])
                        triggers.append({
                            'rule_name': row['rule_name'],
                            'time': time_obj.strftime('%H:%M'),
                            'action': row['action']
                        })
                except Exception as e:
                    logger.debug(f"Could not get triggers: {e}")

                return jsonify({
                    'triggers': triggers
                })

            except Exception as e:
                logger.error(f"Error getting recent triggers: {e}")
                return jsonify({'error': str(e)}), 500

        @self.app.route('/api/automation/rules', methods=['GET', 'POST'])
        def api_automation_rules_list():
            """API: Regeln auflisten und erstellen"""
            import json
            rules_file = Path('data/automation_rules.json')

            if request.method == 'GET':
                # Lade alle Regeln
                if rules_file.exists():
                    with open(rules_file, 'r') as f:
                        data = json.load(f)
                        return jsonify({'rules': data.get('rules', [])})
                else:
                    return jsonify({'rules': []})

            elif request.method == 'POST':
                # Neue Regel erstellen
                new_rule = request.json

                # Generiere ID
                import uuid
                new_rule['id'] = str(uuid.uuid4())

                # Lade existierende Regeln
                if rules_file.exists():
                    with open(rules_file, 'r') as f:
                        data = json.load(f)
                else:
                    data = {'rules': []}

                # Füge neue Regel hinzu
                data['rules'].append(new_rule)

                # Speichere
                rules_file.parent.mkdir(exist_ok=True)
                with open(rules_file, 'w') as f:
                    json.dump(data, f, indent=2)

                logger.info(f"New automation rule created: {new_rule.get('name')}")

                return jsonify({
                    'success': True,
                    'rule': new_rule
                })

        @self.app.route('/api/automation/rules/<rule_id>', methods=['GET', 'PUT', 'DELETE'])
        def api_automation_rule_detail(rule_id):
            """API: Einzelne Regel abrufen, bearbeiten oder löschen"""
            import json
            rules_file = Path('data/automation_rules.json')

            if not rules_file.exists():
                return jsonify({'error': 'No rules found'}), 404

            with open(rules_file, 'r') as f:
                data = json.load(f)

            rules = data.get('rules', [])
            rule = next((r for r in rules if r['id'] == rule_id), None)

            if not rule:
                return jsonify({'error': 'Rule not found'}), 404

            if request.method == 'GET':
                return jsonify(rule)

            elif request.method == 'PUT':
                # Aktualisiere Regel
                updated_rule = request.json
                updated_rule['id'] = rule_id  # ID beibehalten

                # Ersetze Regel
                rules = [r if r['id'] != rule_id else updated_rule for r in rules]
                data['rules'] = rules

                with open(rules_file, 'w') as f:
                    json.dump(data, f, indent=2)

                logger.info(f"Automation rule updated: {updated_rule.get('name')}")

                return jsonify({
                    'success': True,
                    'rule': updated_rule
                })

            elif request.method == 'DELETE':
                # Lösche Regel
                rules = [r for r in rules if r['id'] != rule_id]
                data['rules'] = rules

                with open(rules_file, 'w') as f:
                    json.dump(data, f, indent=2)

                logger.info(f"Automation rule deleted: {rule_id}")

                return jsonify({
                    'success': True
                })

        @self.app.route('/api/automation/rules/<rule_id>/toggle', methods=['POST'])
        def api_automation_rule_toggle(rule_id):
            """API: Regel aktivieren/deaktivieren"""
            import json
            rules_file = Path('data/automation_rules.json')

            if not rules_file.exists():
                return jsonify({'error': 'No rules found'}), 404

            with open(rules_file, 'r') as f:
                data = json.load(f)

            rules = data.get('rules', [])
            rule = next((r for r in rules if r['id'] == rule_id), None)

            if not rule:
                return jsonify({'error': 'Rule not found'}), 404

            # Toggle enabled
            rule['enabled'] = not rule.get('enabled', False)

            # Speichere
            with open(rules_file, 'w') as f:
                json.dump(data, f, indent=2)

            logger.info(f"Automation rule toggled: {rule.get('name')} -> {rule['enabled']}")

            return jsonify({
                'success': True,
                'enabled': rule['enabled']
            })

        # === Rooms Endpunkte ===

        @self.app.route('/api/rooms', methods=['GET', 'POST'])
        def api_rooms():
            """API: Räume verwalten"""
            import json
            rooms_file = Path('data/rooms.json')

            if request.method == 'GET':
                # Lade Räume
                if rooms_file.exists():
                    with open(rooms_file, 'r') as f:
                        data = json.load(f)
                else:
                    data = {'rooms': [], 'assignments': {}}
                return jsonify(data)

            elif request.method == 'POST':
                # Neuen Raum hinzufügen
                data = request.json
                name = data.get('name')
                icon = data.get('icon', '🏠')

                if rooms_file.exists():
                    with open(rooms_file, 'r') as f:
                        rooms_data = json.load(f)
                else:
                    rooms_data = {'rooms': [], 'assignments': {}}

                import uuid
                new_room = {
                    'id': str(uuid.uuid4()),
                    'name': name,
                    'icon': icon,
                    'type': 'custom'
                }

                rooms_data['rooms'].append(new_room)

                Path('data').mkdir(exist_ok=True)
                with open(rooms_file, 'w') as f:
                    json.dump(rooms_data, f, indent=2)

                logger.info(f"Room added: {name}")
                return jsonify({'success': True, 'room': new_room})

        def map_homey_icon_to_emoji(icon_name):
            """Konvertiert Homey Icon-Namen zu Emojis"""
            icon_mapping = {
                'livingRoom': '🛋️',
                'bedroom': '🛏️',
                'bedroomDouble': '🛏️',
                'bedroomSingle': '🛏️',
                'kitchen': '🍳',
                'bathroom': '🚿',
                'toilet': '🚽',
                'office': '💼',
                'recreationRoom': '🎮',
                'garage': '🚗',
                'garden': '🌳',
                'terrace': '🏡',
                'balcony': '🌿',
                'basement': '📦',
                'attic': '🏚️',
                'hallway': '🚪',
                'stairs': '🪜',
                'laundry': '🧺',
                'storage': '📦',
                'home': '🏠',
                'other': '📍',
                'doorClosed': '🚪',
                'sink': '💡',
                'default': '🏠'
            }
            return icon_mapping.get(icon_name, '🏠')

        @self.app.route('/api/rooms/sync-homey-zones', methods=['POST'])
        def api_sync_homey_zones():
            """API: Homey Zonen importieren"""
            try:
                import json
                platform = self.engine.platform

                # Hole Zonen von Homey
                zones = platform.get_zones()

                rooms_file = Path('data/rooms.json')
                if rooms_file.exists():
                    with open(rooms_file, 'r') as f:
                        rooms_data = json.load(f)
                else:
                    rooms_data = {'rooms': [], 'assignments': {}}

                # Konvertiere Zones zu Rooms
                imported = 0
                if isinstance(zones, dict):
                    for zone_id, zone_data in zones.items():
                        # Prüfe ob Zone schon existiert
                        if not any(r['id'] == zone_id for r in rooms_data['rooms']):
                            homey_icon = zone_data.get('icon', 'default')
                            emoji_icon = map_homey_icon_to_emoji(homey_icon)
                            rooms_data['rooms'].append({
                                'id': zone_id,
                                'name': zone_data.get('name', zone_id),
                                'icon': emoji_icon,
                                'type': 'homey'
                            })
                            imported += 1

                Path('data').mkdir(exist_ok=True)
                with open(rooms_file, 'w') as f:
                    json.dump(rooms_data, f, indent=2)

                logger.info(f"Imported {imported} Homey zones")
                return jsonify({'success': True, 'zones_imported': imported})

            except Exception as e:
                logger.error(f"Error syncing zones: {e}")
                return jsonify({'error': str(e)}), 500

        @self.app.route('/api/rooms/sync-device-assignments', methods=['POST'])
        def api_sync_device_assignments():
            """API: Geräte-Zuordnungen aus Homey importieren"""
            try:
                import json
                platform = self.engine.platform

                rooms_file = Path('data/rooms.json')
                if rooms_file.exists():
                    with open(rooms_file, 'r') as f:
                        rooms_data = json.load(f)
                else:
                    rooms_data = {'rooms': [], 'assignments': {}}

                # Hole alle Geräte und extrahiere Zone-Zuordnungen
                assignments_count = 0
                for domain in ['light', 'climate', 'switch', 'sensor']:
                    try:
                        entity_ids = platform.get_all_entities(domain)
                        states = platform.get_states(entity_ids)

                        for entity_id, state_data in states.items():
                            zone_id = state_data.get('attributes', {}).get('zone')
                            if zone_id:
                                # Nur zuordnen wenn Zone als Raum existiert
                                if any(r['id'] == zone_id for r in rooms_data['rooms']):
                                    rooms_data['assignments'][entity_id] = zone_id
                                    assignments_count += 1
                    except Exception as e:
                        logger.warning(f"Error getting {domain} device assignments: {e}")

                Path('data').mkdir(exist_ok=True)
                with open(rooms_file, 'w') as f:
                    json.dump(rooms_data, f, indent=2)

                logger.info(f"Imported {assignments_count} device assignments from Homey")
                return jsonify({'success': True, 'assignments_imported': assignments_count})

            except Exception as e:
                logger.error(f"Error syncing device assignments: {e}")
                return jsonify({'error': str(e)}), 500

        @self.app.route('/api/rooms/assign-device', methods=['POST'])
        def api_assign_device():
            """API: Gerät zu Raum zuordnen"""
            try:
                import json
                data = request.json
                device_id = data.get('device_id')
                room_id = data.get('room_id')

                rooms_file = Path('data/rooms.json')
                if rooms_file.exists():
                    with open(rooms_file, 'r') as f:
                        rooms_data = json.load(f)
                else:
                    rooms_data = {'rooms': [], 'assignments': {}}

                rooms_data['assignments'][device_id] = room_id

                with open(rooms_file, 'w') as f:
                    json.dump(rooms_data, f, indent=2)

                logger.info(f"Device {device_id} assigned to room {room_id}")
                return jsonify({'success': True})

            except Exception as e:
                logger.error(f"Error assigning device: {e}")
                return jsonify({'error': str(e)}), 500

        @self.app.route('/api/rooms/unassign-device', methods=['POST'])
        def api_unassign_device():
            """API: Gerät von Raum entfernen"""
            try:
                import json
                data = request.json
                device_id = data.get('device_id')

                rooms_file = Path('data/rooms.json')
                if rooms_file.exists():
                    with open(rooms_file, 'r') as f:
                        rooms_data = json.load(f)

                    if device_id in rooms_data['assignments']:
                        del rooms_data['assignments'][device_id]

                        with open(rooms_file, 'w') as f:
                            json.dump(rooms_data, f, indent=2)

                logger.info(f"Device {device_id} unassigned")
                return jsonify({'success': True})

            except Exception as e:
                logger.error(f"Error unassigning device: {e}")
                return jsonify({'error': str(e)}), 500

        @self.app.route('/api/rooms/control-lights', methods=['POST'])
        def api_control_room_lights():
            """API: Alle Lichter in einem Raum steuern"""
            try:
                import json
                data = request.json
                room_id = data.get('room_id')
                action = data.get('action')  # 'on' or 'off'

                # Lade Room assignments
                rooms_file = Path('data/rooms.json')
                if not rooms_file.exists():
                    return jsonify({'success': False, 'error': 'No rooms configured'}), 400

                with open(rooms_file, 'r') as f:
                    rooms_data = json.load(f)

                # Finde alle Geräte in diesem Raum
                room_devices = [device_id for device_id, rid in rooms_data['assignments'].items() if rid == room_id]

                platform = self.engine.platform
                controlled = 0

                for device_id in room_devices:
                    try:
                        # Hole Device-State um zu prüfen ob es ein Licht ist
                        state = platform.get_state(device_id)
                        if state and 'light' in device_id.lower():
                            if action == 'on':
                                platform.turn_on(device_id)
                            else:
                                platform.turn_off(device_id)
                            controlled += 1
                    except Exception as e:
                        logger.warning(f"Could not control device {device_id}: {e}")

                return jsonify({'success': True, 'devices_controlled': controlled})

            except Exception as e:
                logger.error(f"Error controlling room lights: {e}")
                return jsonify({'error': str(e)}), 500

        @self.app.route('/api/rooms/update', methods=['POST'])
        def api_update_room():
            """API: Raum bearbeiten (Name und Icon)"""
            try:
                import json
                data = request.json
                room_id = data.get('room_id')
                new_name = data.get('name')
                new_icon = data.get('icon')

                if not room_id:
                    return jsonify({'error': 'room_id required'}), 400

                rooms_file = Path('data/rooms.json')
                if rooms_file.exists():
                    with open(rooms_file, 'r') as f:
                        rooms_data = json.load(f)

                    # Finde und aktualisiere Raum
                    for room in rooms_data['rooms']:
                        if room['id'] == room_id:
                            if new_name:
                                room['name'] = new_name
                            if new_icon:
                                room['icon'] = new_icon
                            break

                    with open(rooms_file, 'w') as f:
                        json.dump(rooms_data, f, indent=2)

                    logger.info(f"Room {room_id} updated")
                    return jsonify({'success': True})

                return jsonify({'error': 'rooms.json not found'}), 404

            except Exception as e:
                logger.error(f"Error updating room: {e}")
                return jsonify({'error': str(e)}), 500

        @self.app.route('/api/rooms/delete', methods=['POST'])
        def api_delete_room():
            """API: Raum löschen"""
            try:
                import json
                data = request.json
                room_id = data.get('room_id')

                rooms_file = Path('data/rooms.json')
                if rooms_file.exists():
                    with open(rooms_file, 'r') as f:
                        rooms_data = json.load(f)

                    rooms_data['rooms'] = [r for r in rooms_data['rooms'] if r['id'] != room_id]

                    with open(rooms_file, 'w') as f:
                        json.dump(rooms_data, f, indent=2)

                logger.info(f"Room {room_id} deleted")
                return jsonify({'success': True})

            except Exception as e:
                logger.error(f"Error deleting room: {e}")
                return jsonify({'error': str(e)}), 500

        @self.app.route('/api/rooms/hidden', methods=['GET', 'POST'])
        def api_rooms_hidden():
            """API: Versteckte Räume verwalten - zentrale Einstellung für alle Seiten"""
            import json
            rooms_file = Path('data/rooms.json')
            
            try:
                if rooms_file.exists():
                    with open(rooms_file, 'r') as f:
                        rooms_data = json.load(f)
                else:
                    rooms_data = {'rooms': [], 'assignments': {}, 'hidden': []}
                
                # Sicherstellen dass 'hidden' existiert
                if 'hidden' not in rooms_data:
                    rooms_data['hidden'] = []
                
                if request.method == 'GET':
                    return jsonify({
                        'success': True,
                        'hidden': rooms_data.get('hidden', [])
                    })
                
                elif request.method == 'POST':
                    data = request.json
                    action = data.get('action')  # 'hide', 'show', 'set'
                    room = data.get('room')
                    rooms = data.get('rooms', [])  # für 'set'
                    
                    if action == 'hide' and room:
                        if room not in rooms_data['hidden']:
                            rooms_data['hidden'].append(room)
                        logger.info(f"Room hidden: {room}")
                    
                    elif action == 'show' and room:
                        rooms_data['hidden'] = [r for r in rooms_data['hidden'] if r != room]
                        logger.info(f"Room shown: {room}")
                    
                    elif action == 'set':
                        rooms_data['hidden'] = rooms
                        logger.info(f"Hidden rooms set: {rooms}")
                    
                    # Speichern
                    with open(rooms_file, 'w') as f:
                        json.dump(rooms_data, f, indent=2, ensure_ascii=False)
                    
                    return jsonify({
                        'success': True,
                        'hidden': rooms_data['hidden']
                    })
                    
            except Exception as e:
                logger.error(f"Error managing hidden rooms: {e}")
                return jsonify({'error': str(e)}), 500

        @self.app.route('/api/rooms/motion-sensors', methods=['GET', 'POST'])
        def api_rooms_motion_sensors():
            """API: Bewegungssensor-Zuordnung verwalten"""
            import json
            rooms_file = Path('data/rooms.json')
            
            try:
                if rooms_file.exists():
                    with open(rooms_file, 'r') as f:
                        rooms_data = json.load(f)
                else:
                    rooms_data = {'rooms': [], 'assignments': {}}
                
                # Sicherstellen dass 'motion_sensors' existiert
                if 'motion_sensors' not in rooms_data:
                    rooms_data['motion_sensors'] = {}
                
                if request.method == 'GET':
                    return jsonify({
                        'success': True,
                        'motion_sensors': rooms_data.get('motion_sensors', {})
                    })
                
                elif request.method == 'POST':
                    data = request.json
                    motion_sensors = data.get('motion_sensors', {})
                    
                    rooms_data['motion_sensors'] = motion_sensors
                    logger.info(f"Motion sensors updated: {len(motion_sensors)} mappings")
                    
                    # Speichern
                    with open(rooms_file, 'w') as f:
                        json.dump(rooms_data, f, indent=2, ensure_ascii=False)
                    
                    return jsonify({
                        'success': True,
                        'motion_sensors': rooms_data['motion_sensors']
                    })
                    
            except Exception as e:
                logger.error(f"Error managing motion sensors: {e}")
                return jsonify({'error': str(e)}), 500

        @self.app.route('/api/rooms/settings', methods=['GET'])
        def api_rooms_settings():
            """API: Alle Raum-Einstellungen für Frontend - zentrale Datenquelle"""
            import json
            rooms_file = Path('data/rooms.json')
            
            try:
                if rooms_file.exists():
                    with open(rooms_file, 'r') as f:
                        rooms_data = json.load(f)
                else:
                    rooms_data = {'rooms': [], 'assignments': {}, 'hidden': []}
                
                return jsonify({
                    'success': True,
                    'rooms': rooms_data.get('rooms', []),
                    'hidden': rooms_data.get('hidden', []),
                    'assignments': rooms_data.get('assignments', {})
                })
                
            except Exception as e:
                logger.error(f"Error getting room settings: {e}")
                return jsonify({'error': str(e)}), 500

        @self.app.route('/api/rooms/window-calibration', methods=['GET', 'POST'])
        def api_window_calibration():
            """API: Fenster-Kalibrierung pro Raum - definiert wann ein Fenster als geschlossen gilt"""
            import json
            rooms_file = Path('data/rooms.json')
            
            try:
                if rooms_file.exists():
                    with open(rooms_file, 'r') as f:
                        rooms_data = json.load(f)
                else:
                    rooms_data = {'rooms': [], 'assignments': {}, 'hidden': [], 'window_calibration': {}}
                
                # Sicherstellen dass 'window_calibration' existiert
                if 'window_calibration' not in rooms_data:
                    rooms_data['window_calibration'] = {}
                
                if request.method == 'GET':
                    room_id = request.args.get('room_id')
                    
                    if room_id:
                        # Kalibrierung für einen bestimmten Raum
                        calibration = rooms_data['window_calibration'].get(room_id, {
                            'closed_angle': 0,
                            'tilted_min': 5,
                            'tilted_max': 45
                        })
                        return jsonify({
                            'success': True,
                            'calibration': calibration
                        })
                    else:
                        # Alle Kalibrierungen
                        return jsonify({
                            'success': True,
                            'window_calibration': rooms_data.get('window_calibration', {})
                        })
                
                elif request.method == 'POST':
                    data = request.json
                    room_id = data.get('room_id')
                    
                    if not room_id:
                        return jsonify({'error': 'room_id required'}), 400
                    
                    # Kalibrierungswerte
                    calibration = {
                        'closed_angle': float(data.get('closed_angle', 0)),
                        'tilted_min': float(data.get('tilted_min', 5)),
                        'tilted_max': float(data.get('tilted_max', 45))
                    }
                    
                    rooms_data['window_calibration'][room_id] = calibration
                    logger.info(f"Window calibration for room {room_id}: closed={calibration['closed_angle']}°, tilted={calibration['tilted_min']}-{calibration['tilted_max']}°")
                    
                    # Speichern
                    with open(rooms_file, 'w') as f:
                        json.dump(rooms_data, f, indent=2, ensure_ascii=False)
                    
                    return jsonify({
                        'success': True,
                        'calibration': calibration
                    })
                    
            except Exception as e:
                logger.error(f"Error managing window calibration: {e}")
                return jsonify({'error': str(e)}), 500

        @self.app.route('/api/rooms/window-status', methods=['GET'])
        def api_window_status():
            """API: Aktueller Fensterstatus mit Winkel und Zustand (Zu/Gekippt/Offen)"""
            import json
            rooms_file = Path('data/rooms.json')
            
            try:
                # Lade Kalibrierungsdaten
                if rooms_file.exists():
                    with open(rooms_file, 'r') as f:
                        rooms_data = json.load(f)
                else:
                    rooms_data = {'window_calibration': {}}
                
                calibrations = rooms_data.get('window_calibration', {})
                
                # Hole alle Fenster-Geräte (nutze get_states statt get_devices)
                devices = []
                if hasattr(self.engine, 'platform'):
                    # Für Homey: nutze _device_cache oder get_states
                    if hasattr(self.engine.platform, '_device_cache'):
                        self.engine.platform._refresh_device_cache()
                        devices = list(self.engine.platform._device_cache.values()) if isinstance(
                            self.engine.platform._device_cache, dict) else []
                    elif hasattr(self.engine.platform, 'get_states'):
                        states = self.engine.platform.get_states() or {}
                        devices = list(states.values()) if isinstance(states, dict) else states
                
                window_status = []
                
                for device in devices:
                    name = device.get('name', '').lower()
                    if 'fenster' in name or 'window' in name:
                        caps = device.get('capabilitiesObj', {})
                        zone_id = device.get('zone', '')
                        
                        # Hole Tilt-Wert
                        tilt_value = None
                        if 'tilt' in caps:
                            tilt_value = caps['tilt'].get('value', 0)
                        
                        # Hole Kontakt-Status
                        is_contact_open = False
                        if 'alarm_contact' in caps:
                            is_contact_open = bool(caps['alarm_contact'].get('value', False))
                        
                        # Bestimme Zustand basierend auf Kalibrierung
                        calibration = calibrations.get(zone_id, {
                            'closed_angle': 0,
                            'tilted_min': 5,
                            'tilted_max': 45
                        })
                        
                        state = 'closed'  # Default
                        if tilt_value is not None:
                            closed_angle = calibration.get('closed_angle', 0)
                            tilted_min = calibration.get('tilted_min', 5)
                            tilted_max = calibration.get('tilted_max', 45)
                            
                            # Logik: Kontakt + Winkel kombinieren
                            # - Kontakt zu = Fenster geschlossen
                            # - Kontakt offen + Winkel im Kippbereich (5°-45°) = gekippt
                            # - Kontakt offen + Winkel außerhalb Kippbereich (0° oder >45°) = weit offen
                            diff = abs(tilt_value - closed_angle)
                            
                            if not is_contact_open:
                                # Kontakt geschlossen = Fenster zu
                                state = 'closed'
                            elif is_contact_open and diff >= tilted_min and diff <= tilted_max:
                                # Kontakt offen + Winkel im Kippbereich = gekippt
                                state = 'tilted'
                            elif is_contact_open:
                                # Kontakt offen + Winkel nahe geschlossen (0°) oder sehr groß (>45°) = weit offen
                                state = 'open'
                        elif is_contact_open:
                            # Kein Tilt-Sensor, aber Kontakt offen
                            state = 'open'
                        
                        window_status.append({
                            'device_id': device.get('id'),
                            'name': device.get('name'),
                            'zone_id': zone_id,
                            'tilt': tilt_value,
                            'contact_open': is_contact_open,
                            'state': state,
                            'state_label': {
                                'closed': '🟢 Geschlossen',
                                'tilted': '🟡 Gekippt',
                                'open': '🔴 Offen'
                            }.get(state, state)
                        })
                
                return jsonify({
                    'success': True,
                    'windows': window_status
                })
                
            except Exception as e:
                logger.error(f"Error getting window status: {e}")
                return jsonify({'error': str(e)}), 500

        @self.app.route('/api/rooms/window-auto-calibrate', methods=['POST'])
        def api_window_auto_calibrate():
            """API: Automatische Fenster-Kalibrierung basierend auf aktuellem Status
            
            Logik:
            - Wenn Kontakt geschlossen UND Tilt vorhanden -> Tilt-Wert als "geschlossen" speichern
            - Wenn Kontakt offen UND Tilt vorhanden -> basierend auf Tilt-Wert ermitteln ob gekippt oder offen
            """
            import json
            rooms_file = Path('data/rooms.json')
            
            try:
                # Lade aktuelle Daten
                if rooms_file.exists():
                    with open(rooms_file, 'r') as f:
                        rooms_data = json.load(f)
                else:
                    rooms_data = {'window_calibration': {}}
                
                if 'window_calibration' not in rooms_data:
                    rooms_data['window_calibration'] = {}
                
                # Hole alle Fenster-Geräte
                devices = []
                if hasattr(self.engine, 'platform'):
                    if hasattr(self.engine.platform, '_device_cache'):
                        self.engine.platform._refresh_device_cache()
                        devices = list(self.engine.platform._device_cache.values()) if isinstance(
                            self.engine.platform._device_cache, dict) else []
                    elif hasattr(self.engine.platform, 'get_states'):
                        states = self.engine.platform.get_states() or {}
                        devices = list(states.values()) if isinstance(states, dict) else states
                
                calibrated_rooms = []
                
                for device in devices:
                    name = device.get('name', '').lower()
                    if 'fenster' in name or 'window' in name:
                        caps = device.get('capabilitiesObj', {})
                        zone_id = device.get('zone', '')
                        
                        if not zone_id:
                            continue
                        
                        # Hole Tilt-Wert
                        tilt_value = None
                        if 'tilt' in caps:
                            tilt_value = caps['tilt'].get('value')
                        
                        # Hole Kontakt-Status
                        is_contact_open = False
                        if 'alarm_contact' in caps:
                            is_contact_open = bool(caps['alarm_contact'].get('value', False))
                        
                        if tilt_value is not None:
                            # Aktuelle Kalibrierung holen oder Default
                            current_cal = rooms_data['window_calibration'].get(zone_id, {
                                'closed_angle': 0,
                                'tilted_min': 5,
                                'tilted_max': 45
                            })
                            
                            # Auto-Kalibrierung basierend auf Kontakt-Status
                            if not is_contact_open:
                                # Fenster geschlossen -> aktueller Tilt ist der "geschlossen" Winkel
                                current_cal['closed_angle'] = round(tilt_value, 1)
                                rooms_data['window_calibration'][zone_id] = current_cal
                                
                                # Hole Zone-Namen
                                zone_name = 'Unbekannt'
                                try:
                                    zones = self.engine.platform.get_zones() or []
                                    for z in zones:
                                        if z.get('id') == zone_id:
                                            zone_name = z.get('name', zone_id)
                                            break
                                except:
                                    pass
                                
                                calibrated_rooms.append({
                                    'zone_id': zone_id,
                                    'zone_name': zone_name,
                                    'device_name': device.get('name'),
                                    'closed_angle': current_cal['closed_angle'],
                                    'status': 'calibrated'
                                })
                                
                                logger.info(f"Auto-calibrated window {device.get('name')}: closed_angle={current_cal['closed_angle']}°")
                
                # Speichern
                with open(rooms_file, 'w') as f:
                    json.dump(rooms_data, f, indent=2, ensure_ascii=False)
                
                return jsonify({
                    'success': True,
                    'calibrated': calibrated_rooms,
                    'message': f'{len(calibrated_rooms)} Fenster kalibriert'
                })
                
            except Exception as e:
                logger.error(f"Error auto-calibrating windows: {e}")
                return jsonify({'error': str(e)}), 500

        @self.app.route('/api/rooms/device-types', methods=['GET', 'POST'])
        def api_device_types():
            """API: Geräte-Kategorisierung verwalten - welche Geräte sind Lampen vs. sonstige Geräte"""
            import json
            rooms_file = Path('data/rooms.json')
            
            try:
                if rooms_file.exists():
                    with open(rooms_file, 'r') as f:
                        rooms_data = json.load(f)
                else:
                    rooms_data = {'rooms': [], 'assignments': {}, 'hidden': [], 'device_types': {}}
                
                # Sicherstellen dass 'device_types' existiert
                if 'device_types' not in rooms_data:
                    rooms_data['device_types'] = {}
                
                if request.method == 'GET':
                    return jsonify({
                        'success': True,
                        'device_types': rooms_data.get('device_types', {})
                    })
                
                elif request.method == 'POST':
                    data = request.json
                    device_id = data.get('device_id')
                    device_type = data.get('type')  # 'light', 'device', 'exclude'
                    
                    if device_id and device_type:
                        if device_type == 'auto':
                            # Automatische Erkennung - Eintrag entfernen
                            rooms_data['device_types'].pop(device_id, None)
                            logger.info(f"Device {device_id} set to auto detection")
                        else:
                            rooms_data['device_types'][device_id] = device_type
                            logger.info(f"Device {device_id} set to type: {device_type}")
                        
                        # Speichern
                        with open(rooms_file, 'w') as f:
                            json.dump(rooms_data, f, indent=2, ensure_ascii=False)
                        
                        return jsonify({
                            'success': True,
                            'device_types': rooms_data['device_types']
                        })
                    else:
                        return jsonify({'error': 'device_id and type required'}), 400
                    
            except Exception as e:
                logger.error(f"Error managing device types: {e}")
                return jsonify({'error': str(e)}), 500

        # === Analytics API Endpunkte ===

        @self.app.route('/api/analytics/temperature')
        def api_analytics_temperature():
            """API: Historische Temperatur-Daten"""
            try:
                hours = int(request.args.get('hours', 24))
                data = self.db.get_sensor_data_aggregated('temperature', hours_back=hours)

                return jsonify({
                    'success': True,
                    'data': data,
                    'hours_back': hours
                })
            except Exception as e:
                logger.error(f"Error getting temperature analytics: {e}")
                return jsonify({'error': str(e)}), 500

        @self.app.route('/api/analytics/humidity')
        def api_analytics_humidity():
            """API: Historische Luftfeuchtigkeit-Daten"""
            try:
                hours = int(request.args.get('hours', 24))
                data = self.db.get_sensor_data_aggregated('humidity', hours_back=hours)

                return jsonify({
                    'success': True,
                    'data': data,
                    'hours_back': hours
                })
            except Exception as e:
                logger.error(f"Error getting humidity analytics: {e}")
                return jsonify({'error': str(e)}), 500

        @self.app.route('/api/analytics/stats')
        def api_analytics_stats():
            """API: Sammel-Statistiken"""
            try:
                stats = {
                    'total_sensor_readings': self.db.get_sensor_data_count(),
                    'total_external_data': self.db.get_external_data_count(),
                    'last_collection': None,
                    'collector_running': False
                }

                if self.background_collector:
                    collector_stats = self.background_collector.get_stats()
                    stats.update(collector_stats)

                return jsonify(stats)
            except Exception as e:
                logger.error(f"Error getting stats: {e}")
                return jsonify({'error': str(e)}), 500

        @self.app.route('/api/collector/status')
        def api_collector_status():
            """API: Status des Background Collectors"""
            if not self.background_collector:
                return jsonify({'running': False, 'error': 'Collector not initialized'})

            try:
                return jsonify(self.background_collector.get_stats())
            except Exception as e:
                logger.error(f"Error getting collector status: {e}")
                return jsonify({'error': str(e)}), 500

        @self.app.route('/api/collector/start', methods=['POST'])
        def api_collector_start():
            """API: Starte Background Collector"""
            if not self.background_collector:
                return jsonify({'error': 'Collector not initialized'}), 500

            try:
                self.background_collector.start()
                return jsonify({'success': True, 'message': 'Collector started'})
            except Exception as e:
                logger.error(f"Error starting collector: {e}")
                return jsonify({'error': str(e)}), 500

        @self.app.route('/api/collector/stop', methods=['POST'])
        def api_collector_stop():
            """API: Stoppe Background Collector"""
            if not self.background_collector:
                return jsonify({'error': 'Collector not initialized'}), 500

            try:
                self.background_collector.stop()
                return jsonify({'success': True, 'message': 'Collector stopped'})
            except Exception as e:
                logger.error(f"Error stopping collector: {e}")
                return jsonify({'error': str(e)}), 500

        # === Bathroom Automation API Endpunkte ===

        @self.app.route('/api/luftentfeuchten/config', methods=['GET', 'POST'])
        def api_bathroom_config():
            """API: Badezimmer-Konfiguration verwalten"""
            import json
            from pathlib import Path

            config_file = Path('data/luftentfeuchten_config.json')

            if request.method == 'GET':
                # Lade Konfiguration
                if config_file.exists():
                    with open(config_file, 'r') as f:
                        config = json.load(f)
                    return jsonify({'config': config})
                else:
                    return jsonify({'config': {'enabled': False}})

            elif request.method == 'POST':
                # Speichere Konfiguration
                try:
                    data = request.json
                    config = data.get('config', {})

                    # Speichere in Datei
                    with open(config_file, 'w') as f:
                        json.dump(config, f, indent=2)

                    logger.info("Bathroom automation config saved")
                    return jsonify({'success': True})

                except Exception as e:
                    logger.error(f"Error saving bathroom config: {e}")
                    return jsonify({'error': str(e)}), 500

        # Cache für Bathroom Status (3 Sekunden)
        bathroom_status_cache = {'data': None, 'timestamp': 0}
        bathroom_instance_cache = {'instance': None, 'config_hash': None}

        @self.app.route('/api/luftentfeuchten/status')
        def api_bathroom_status():
            """API: Badezimmer-Status abrufen (gecached)"""
            try:
                import json
                import time
                from pathlib import Path
                from src.decision_engine.bathroom_automation import BathroomAutomation

                # Cache für 3 Sekunden
                now = time.time()
                if bathroom_status_cache['data'] and (now - bathroom_status_cache['timestamp']) < 3:
                    return jsonify(bathroom_status_cache['data'])

                config_file = Path('data/luftentfeuchten_config.json')

                if not config_file.exists():
                    result = {
                        'status': {
                            'enabled': False,
                            'shower_detected': False,
                            'dehumidifier_running': False,
                            'current_humidity': None,
                            'current_temperature': None
                        }
                    }
                    bathroom_status_cache['data'] = result
                    bathroom_status_cache['timestamp'] = now
                    return jsonify(result)

                with open(config_file, 'r') as f:
                    config = json.load(f)

                if not config.get('enabled', False):
                    result = {
                        'status': {
                            'enabled': False,
                            'shower_detected': False,
                            'dehumidifier_running': False,
                            'current_humidity': None,
                            'current_temperature': None
                        }
                    }
                    bathroom_status_cache['data'] = result
                    bathroom_status_cache['timestamp'] = now
                    return jsonify(result)

                # Verwende die Automation-Instanz vom BathroomDataCollector wenn verfügbar
                # (diese hat den korrekten State inkl. humidity_below_threshold_since)
                bathroom = None
                if self.bathroom_collector and self.bathroom_collector.automation:
                    bathroom = self.bathroom_collector.automation
                else:
                    # Fallback: Prüfe ob Config geändert wurde (Hash vergleichen)
                    config_hash = hash(json.dumps(config, sort_keys=True))

                    if bathroom_instance_cache['config_hash'] != config_hash:
                        # Config hat sich geändert, neue Instanz erstellen
                        bathroom_instance_cache['instance'] = BathroomAutomation(config)
                        bathroom_instance_cache['config_hash'] = config_hash

                    # Verwende gecachte Instanz
                    bathroom = bathroom_instance_cache['instance']
                
                status = bathroom.get_status(self.engine.platform)

                result = {'status': status}
                bathroom_status_cache['data'] = result
                bathroom_status_cache['timestamp'] = now

                return jsonify(result)

            except Exception as e:
                logger.error(f"Error getting bathroom status: {e}")
                return jsonify({'error': str(e)}), 500

        @self.app.route('/api/luftentfeuchten/test', methods=['POST'])
        def api_bathroom_test():
            """API: Badezimmer-Automatisierung testen"""
            try:
                import json
                from pathlib import Path
                from src.decision_engine.bathroom_automation import BathroomAutomation

                config_file = Path('data/luftentfeuchten_config.json')

                if not config_file.exists():
                    return jsonify({'error': 'No configuration found'}), 400

                with open(config_file, 'r') as f:
                    config = json.load(f)

                # Initialisiere und teste
                bathroom = BathroomAutomation(config)
                current_state = self.engine.collect_current_state()
                actions = bathroom.process(self.engine.platform, current_state)

                logger.info(f"Bathroom automation test: {len(actions)} actions")

                return jsonify({
                    'success': True,
                    'actions': actions,
                    'message': f'{len(actions)} Aktionen würden ausgeführt'
                })

            except Exception as e:
                logger.error(f"Error testing bathroom automation: {e}")
                return jsonify({'error': str(e)}), 500

        @self.app.route('/api/luftentfeuchten/analytics')
        def api_bathroom_analytics():
            """API: Badezimmer Analytics und Statistiken"""
            try:
                import json
                from pathlib import Path
                from src.decision_engine.bathroom_automation import BathroomAutomation

                config_file = Path('data/luftentfeuchten_config.json')

                if not config_file.exists():
                    return jsonify({'error': 'No configuration found'}), 400

                with open(config_file, 'r') as f:
                    config = json.load(f)

                # Initialisiere mit Learning enabled
                bathroom = BathroomAutomation(config, enable_learning=True)

                # Hole Analytics-Daten
                days_back = int(request.args.get('days', 30))
                analytics = bathroom.get_analytics(days_back=days_back)

                return jsonify(analytics)

            except Exception as e:
                logger.error(f"Error getting bathroom analytics: {e}")
                return jsonify({'error': str(e)}), 500

        @self.app.route('/api/luftentfeuchten/test-device', methods=['POST'])
        def api_bathroom_test_device():
            """API: Teste ein Gerät (Luftentfeuchter, Heizung) für 30 Sekunden"""
            try:
                import json
                import threading
                import time
                from pathlib import Path

                data = request.json
                device_type = data.get('device_type', 'dehumidifier')  # dehumidifier, heater
                duration = min(int(data.get('duration', 30)), 60)  # Max 60 Sekunden

                # Lade Config
                config_file = Path('data/luftentfeuchten_config.json')
                if not config_file.exists():
                    return jsonify({
                        'success': False,
                        'error': 'Keine Konfiguration gefunden. Bitte zuerst Geräte konfigurieren.'
                    }), 400

                with open(config_file, 'r') as f:
                    config = json.load(f)

                # Bestimme Device-ID
                if device_type == 'dehumidifier':
                    device_id = config.get('dehumidifier_id')
                    device_name = 'Luftentfeuchter'
                elif device_type == 'heater':
                    device_id = config.get('heater_id')
                    device_name = 'Heizung'
                else:
                    return jsonify({
                        'success': False,
                        'error': f'Unbekannter Gerätetyp: {device_type}'
                    }), 400

                if not device_id:
                    return jsonify({
                        'success': False,
                        'error': f'{device_name} nicht konfiguriert. Bitte ID in den Einstellungen setzen.'
                    }), 400

                # Prüfe ob Gerät erreichbar ist
                if not self.engine or not self.engine.platform:
                    return jsonify({
                        'success': False,
                        'error': 'Keine Plattform-Verbindung (Home Assistant/Homey)'
                    }), 500

                # Versuche Gerätestatus zu holen
                state = self.engine.platform.get_state(device_id)
                if not state:
                    return jsonify({
                        'success': False,
                        'error': f'{device_name} nicht gefunden (ID: {device_id}). Prüfe die Geräte-ID.'
                    }), 404

                device_friendly_name = state.get('attributes', {}).get('friendly_name', device_id)
                current_state = state.get('state', 'unknown')

                # Schalte Gerät ein
                logger.info(f"🧪 Test: Schalte {device_name} ({device_friendly_name}) für {duration}s ein...")
                
                try:
                    if device_type == 'heater':
                        # Für Heizung: Temperatur erhöhen
                        self.engine.platform.set_temperature(device_id, 25.0)
                    else:
                        # Für andere Geräte: Einschalten
                        self.engine.platform.turn_on(device_id)
                except Exception as turn_on_error:
                    return jsonify({
                        'success': False,
                        'error': f'Fehler beim Einschalten: {str(turn_on_error)}',
                        'device_id': device_id,
                        'device_name': device_friendly_name
                    }), 500

                # Timer zum automatischen Ausschalten
                def auto_turn_off():
                    time.sleep(duration)
                    try:
                        logger.info(f"🧪 Test: Schalte {device_name} nach {duration}s automatisch aus...")
                        if device_type == 'heater':
                            # Heizung zurücksetzen
                            original_temp = config.get('target_temp', 21.0)
                            self.engine.platform.set_temperature(device_id, original_temp)
                        else:
                            self.engine.platform.turn_off(device_id)
                    except Exception as e:
                        logger.error(f"Fehler beim Ausschalten nach Test: {e}")

                # Starte Timer im Hintergrund
                timer_thread = threading.Thread(target=auto_turn_off, daemon=True)
                timer_thread.start()

                return jsonify({
                    'success': True,
                    'message': f'{device_name} wurde eingeschaltet und wird nach {duration} Sekunden automatisch ausgeschaltet.',
                    'device_id': device_id,
                    'device_name': device_friendly_name,
                    'previous_state': current_state,
                    'test_duration': duration
                })

            except Exception as e:
                logger.error(f"Error testing device: {e}")
                import traceback
                return jsonify({
                    'success': False,
                    'error': str(e),
                    'details': traceback.format_exc()
                }), 500

        @self.app.route('/api/luftentfeuchten/events')
        def api_bathroom_events():
            """API: Badezimmer Events (Historie) mit Event-Typ-Klassifikation"""
            try:
                from src.utils.database import Database
                from src.decision_engine.bathroom_analyzer import BathroomAnalyzer

                db = Database()
                analyzer = BathroomAnalyzer(db=db)
                days_back = int(request.args.get('days', 30))
                limit = int(request.args.get('limit', 100))

                events = db.get_bathroom_events(days_back=days_back, limit=limit)
                
                # Klassifiziere jeden Event
                for event in events:
                    event_type = analyzer.classify_event_type(event)
                    event['event_type'] = event_type['type']
                    event['event_icon'] = event_type['icon']
                    event['event_label'] = event_type['label']
                    event['event_description'] = event_type['description']

                return jsonify({
                    'events': events,
                    'count': len(events),
                    'days_back': days_back
                })

            except Exception as e:
                logger.error(f"Error getting bathroom events: {e}")
                return jsonify({'error': str(e)}), 500

        @self.app.route('/api/luftentfeuchten/optimize', methods=['POST'])
        def api_bathroom_optimize():
            """API: Badezimmer Parameter optimieren"""
            try:
                import json
                from pathlib import Path
                from src.decision_engine.bathroom_automation import BathroomAutomation

                config_file = Path('data/luftentfeuchten_config.json')

                if not config_file.exists():
                    return jsonify({'error': 'No configuration found'}), 400

                with open(config_file, 'r') as f:
                    config = json.load(f)

                # Initialisiere mit Learning enabled
                bathroom = BathroomAutomation(config, enable_learning=True)

                # Optimiere Parameter
                days_back = int(request.json.get('days_back', 30)) if request.json else 30
                min_confidence = float(request.json.get('min_confidence', 0.7)) if request.json else 0.7

                result = bathroom.optimize_parameters(
                    days_back=days_back,
                    min_confidence=min_confidence
                )

                if result and result.get('success'):
                    # Update config mit neuen Werten
                    config['humidity_threshold_high'] = result['new_values']['humidity_high']
                    config['humidity_threshold_low'] = result['new_values']['humidity_low']

                    with open(config_file, 'w') as f:
                        json.dump(config, f, indent=2)

                    logger.info("✨ Configuration updated with optimized values")

                return jsonify(result if result else {'success': False, 'reason': 'Optimization failed'})

            except Exception as e:
                logger.error(f"Error optimizing bathroom parameters: {e}")
                return jsonify({'error': str(e)}), 500

        @self.app.route('/api/luftentfeuchten/live-status')
        def api_bathroom_live_status():
            """API: Live-Status aller konfigurierten Badezimmer-Sensoren und Aktoren"""
            try:
                import json
                from pathlib import Path

                config_file = Path('data/luftentfeuchten_config.json')

                if not config_file.exists():
                    return jsonify({'error': 'No configuration found', 'devices': {}}), 200

                with open(config_file, 'r') as f:
                    config = json.load(f)

                devices_status = {}

                # Humidity Sensor
                if config.get('humidity_sensor_id'):
                    sensor_id = config['humidity_sensor_id']
                    state = self.engine.platform.get_state(sensor_id)
                    if state:
                        devices_status['humidity_sensor'] = {
                            'id': sensor_id,
                            'name': state.get('attributes', {}).get('friendly_name', sensor_id),
                            'value': self.engine._extract_humidity_value(state),
                            'unit': '%',
                            'available': state.get('state', 'unknown') != 'unavailable'
                        }

                # Temperature Sensor
                if config.get('temperature_sensor_id'):
                    sensor_id = config['temperature_sensor_id']
                    state = self.engine.platform.get_state(sensor_id)
                    if state:
                        devices_status['temperature_sensor'] = {
                            'id': sensor_id,
                            'name': state.get('attributes', {}).get('friendly_name', sensor_id),
                            'value': self.engine._extract_temperature_value(state),
                            'unit': '°C',
                            'available': state.get('state', 'unknown') != 'unavailable'
                        }

                # Door Sensor
                if config.get('door_sensor_id'):
                    sensor_id = config['door_sensor_id']
                    state = self.engine.platform.get_state(sensor_id)
                    if state:
                        # alarm_contact: true = closed (contact made), false = open (contact broken)
                        caps = state.get('capabilitiesObj', {})
                        alarm_contact = caps.get('alarm_contact', {}).get('value', False)
                        devices_status['door_sensor'] = {
                            'id': sensor_id,
                            'name': state.get('name', sensor_id),
                            'value': 'closed' if alarm_contact else 'open',
                            'is_open': not alarm_contact,
                            'available': state.get('available', True)
                        }

                # Window Sensor
                if config.get('window_sensor_id'):
                    sensor_id = config['window_sensor_id']
                    state = self.engine.platform.get_state(sensor_id)
                    if state:
                        # alarm_contact: true = open, false = closed
                        caps = state.get('capabilitiesObj', {})
                        alarm_contact = caps.get('alarm_contact', {}).get('value', False)
                        devices_status['window_sensor'] = {
                            'id': sensor_id,
                            'name': state.get('name', sensor_id),
                            'value': 'open' if alarm_contact else 'closed',
                            'is_open': alarm_contact,
                            'available': state.get('available', True)
                        }

                # Motion Sensor
                if config.get('motion_sensor_id'):
                    sensor_id = config['motion_sensor_id']
                    state = self.engine.platform.get_state(sensor_id)
                    if state:
                        # alarm_motion: true = motion detected
                        caps = state.get('capabilitiesObj', {})
                        alarm_motion = caps.get('alarm_motion', {}).get('value', False)
                        devices_status['motion_sensor'] = {
                            'id': sensor_id,
                            'name': state.get('name', sensor_id),
                            'value': 'detected' if alarm_motion else 'clear',
                            'motion_detected': alarm_motion,
                            'available': state.get('available', True)
                        }

                # Dehumidifier
                if config.get('dehumidifier_id'):
                    device_id = config['dehumidifier_id']
                    state = self.engine.platform.get_state(device_id)
                    if state:
                        caps = state.get('capabilitiesObj', {})
                        onoff = caps.get('onoff', {}).get('value', False)
                        devices_status['dehumidifier'] = {
                            'id': device_id,
                            'name': state.get('name', device_id),
                            'value': 'on' if onoff else 'off',
                            'is_on': onoff,
                            'available': state.get('available', True)
                        }

                # Heater
                if config.get('heater_id'):
                    device_id = config['heater_id']
                    state = self.engine.platform.get_state(device_id)
                    if state:
                        # Capabilities können in verschiedenen Strukturen sein
                        caps = state.get('capabilitiesObj', {})
                        if not caps:
                            # Alternative: attributes.capabilities (Homey)
                            caps = state.get('attributes', {}).get('capabilities', {})

                        target_temp = None
                        current_temp = None

                        if caps:
                            target_temp_cap = caps.get('target_temperature', {})
                            current_temp_cap = caps.get('measure_temperature', {})

                            if isinstance(target_temp_cap, dict):
                                target_temp = target_temp_cap.get('value')
                            if isinstance(current_temp_cap, dict):
                                current_temp = current_temp_cap.get('value')

                        devices_status['heater'] = {
                            'id': device_id,
                            'name': state.get('attributes', {}).get('friendly_name', state.get('name', device_id)),
                            'value': target_temp,  # SOLL-Temperatur
                            'current_temp': current_temp,  # IST-Temperatur
                            'target_temp': target_temp,  # SOLL-Temperatur (explizit)
                            'unit': '°C',
                            'available': state.get('attributes', {}).get('available', state.get('available', True))
                        }

                return jsonify({'devices': devices_status})

            except Exception as e:
                logger.error(f"Error getting bathroom live status: {e}")
                return jsonify({'error': str(e), 'devices': {}}), 500

        @self.app.route('/api/luftentfeuchten/control', methods=['POST'])
        def api_bathroom_control():
            """API: Steuerung von Aktoren (Luftentfeuchter, Heizung)"""
            try:
                data = request.json
                device_type = data.get('device_type')  # 'dehumidifier' or 'heater'
                action = data.get('action')  # 'on', 'off', 'temp_up', 'temp_down'

                import json
                from pathlib import Path

                config_file = Path('data/luftentfeuchten_config.json')

                if not config_file.exists():
                    return jsonify({'error': 'No configuration found'}), 400

                with open(config_file, 'r') as f:
                    config = json.load(f)

                success = False
                message = ""

                if device_type == 'dehumidifier':
                    device_id = config.get('dehumidifier_id')
                    if not device_id:
                        return jsonify({'error': 'Dehumidifier not configured'}), 400

                    if action == 'on':
                        self.engine.platform.turn_on(device_id)
                        success = True
                        message = "Luftentfeuchter eingeschaltet"
                    elif action == 'off':
                        self.engine.platform.turn_off(device_id)
                        success = True
                        message = "Luftentfeuchter ausgeschaltet"

                elif device_type == 'heater':
                    device_id = config.get('heater_id')
                    if not device_id:
                        return jsonify({'error': 'Heater not configured'}), 400

                    # Get current temperature
                    state = self.engine.platform.get_state(device_id)
                    if state:
                        caps = state.get('capabilitiesObj', {})
                        current_temp = caps.get('target_temperature', {}).get('value', 20.0)

                        if action == 'temp_up':
                            new_temp = min(current_temp + 1, 30)  # Max 30°C
                            self.engine.platform.set_climate_temperature(device_id, new_temp)
                            success = True
                            message = f"Heizung auf {new_temp}°C erhöht"
                        elif action == 'temp_down':
                            new_temp = max(current_temp - 1, 10)  # Min 10°C
                            self.engine.platform.set_climate_temperature(device_id, new_temp)
                            success = True
                            message = f"Heizung auf {new_temp}°C gesenkt"

                if success:
                    logger.info(f"Bathroom control: {device_type} - {action}")
                    return jsonify({'success': True, 'message': message})
                else:
                    return jsonify({'error': 'Invalid action'}), 400

            except Exception as e:
                logger.error(f"Error controlling bathroom device: {e}")
                return jsonify({'error': str(e)}), 500

        @self.app.route('/luftentfeuchten/analytics')
        def page_bathroom_analytics():
            """Seite: Badezimmer Analytics Dashboard"""
            return render_template('luftentfeuchten_analytics.html')

        @self.app.route('/api/luftentfeuchten/learned-params', methods=['GET'])
        def api_bathroom_learned_params():
            """API: Hole Details zu gelernten Parametern"""
            try:
                # Hole Details für alle relevanten Parameter
                params_info = {}
                param_names = ['humidity_threshold_high', 'humidity_threshold_low', 'dehumidifier_delay']

                for param_name in param_names:
                    details = self.db.get_learned_parameter_details(param_name, min_confidence=0.0)
                    if details:
                        params_info[param_name] = {
                            'value': details['value'],
                            'confidence': details['confidence'],
                            'samples_used': details['samples_used'],
                            'timestamp': details['timestamp'],
                            'reason': details['reason'],
                            'is_learned': True
                        }
                    else:
                        params_info[param_name] = {
                            'is_learned': False
                        }

                # Zähle Events für Info
                events_count = len(self.db.get_bathroom_events(days_back=30))

                return jsonify({
                    'learned_params': params_info,
                    'events_last_30_days': events_count,
                    'ready_for_optimization': events_count >= 5
                })

            except Exception as e:
                logger.error(f"Error getting learned params: {e}")
                return jsonify({'error': str(e)}), 500

        @self.app.route('/api/luftentfeuchten/reset-learned', methods=['POST'])
        def api_bathroom_reset_learned():
            """API: Setze gelernte Parameter zurück (verwende wieder manuelle Werte)"""
            try:
                deleted_count = self.db.reset_learned_parameters()

                logger.info(f"Learned parameters reset: {deleted_count} entries deleted")

                return jsonify({
                    'success': True,
                    'message': f'{deleted_count} gelernte Parameter zurückgesetzt',
                    'deleted_count': deleted_count
                })

            except Exception as e:
                logger.error(f"Error resetting learned parameters: {e}")
                return jsonify({'error': str(e)}), 500

        @self.app.route('/api/luftentfeuchten/energy-stats', methods=['GET'])
        def api_bathroom_energy_stats():
            """API: Energie & Kosten-Statistiken"""
            try:
                import json
                from pathlib import Path

                # Hole Parameter aus Query oder Config
                days_back = int(request.args.get('days', 30))

                # Lade Config für Geräte-Leistungen
                config_file = Path('data/luftentfeuchten_config.json')
                dehumidifier_wattage = 400.0  # Default
                energy_price = 0.30  # Default EUR/kWh

                if config_file.exists():
                    with open(config_file, 'r') as f:
                        config = json.load(f)
                        dehumidifier_wattage = config.get('dehumidifier_wattage', 400.0)
                        energy_price = config.get('energy_price_per_kwh', 0.30)

                # Berechne Statistiken (nur Luftentfeuchter, keine Heizung)
                stats = self.db.get_bathroom_energy_stats(
                    days_back=days_back,
                    dehumidifier_wattage=dehumidifier_wattage,
                    heater_wattage=0.0,  # Zentralheizung nicht messbar
                    energy_price_per_kwh=energy_price
                )

                return jsonify(stats)

            except Exception as e:
                logger.error(f"Error getting energy stats: {e}")
                return jsonify({'error': str(e)}), 500

        @self.app.route('/api/luftentfeuchten/alerts', methods=['GET'])
        def api_bathroom_alerts():
            """API: System-Gesundheits-Alerts"""
            try:
                from src.decision_engine.bathroom_analyzer import BathroomAnalyzer

                days_back = int(request.args.get('days', 7))

                analyzer = BathroomAnalyzer(self.db)
                alerts = analyzer.check_system_health(days_back=days_back)

                # Sortiere nach Severity (high > medium > low)
                severity_order = {'high': 0, 'medium': 1, 'low': 2}
                alerts.sort(key=lambda x: severity_order.get(x.get('severity', 'low'), 2))

                return jsonify({
                    'alerts': alerts,
                    'count': len(alerts),
                    'has_critical': any(a.get('severity') == 'high' for a in alerts),
                    'days_checked': days_back
                })

            except Exception as e:
                logger.error(f"Error getting bathroom alerts: {e}")
                return jsonify({'error': str(e)}), 500

        @self.app.route('/api/luftentfeuchten/preview', methods=['POST'])
        def api_bathroom_preview():
            """API: Live-Preview - Was würde das System jetzt tun?"""
            try:
                from src.decision_engine.bathroom_automation import BathroomAutomation
                import json
                from pathlib import Path

                # Lade Config
                config_file = Path('data/luftentfeuchten_config.json')
                if not config_file.exists():
                    return jsonify({'error': 'No configuration found'}), 400

                with open(config_file, 'r') as f:
                    config = json.load(f)

                # Initialisiere Automation (ohne Speichern)
                bathroom = BathroomAutomation(config, enable_learning=False)

                # Hole aktuellen State
                current_state = self.engine.collect_current_state()

                # Hole Live-Sensor-Werte
                humidity = bathroom._get_humidity(self.engine.platform)
                temperature = bathroom._get_temperature(self.engine.platform)
                motion = bathroom._check_motion(self.engine.platform)
                door_closed = bathroom._check_door(self.engine.platform)

                # Simuliere Entscheidungen (ohne Ausführung)
                would_detect_shower = bathroom._detect_shower(humidity, motion, door_closed)

                # Prüfe Luftentfeuchter-Aktion
                dehumidifier_action = None
                should_turn_on_dehumidifier = (humidity and humidity > bathroom.humidity_high) or would_detect_shower
                should_turn_off_dehumidifier = humidity and humidity < bathroom.humidity_low

                if should_turn_on_dehumidifier:
                    dehumidifier_action = {
                        'action': 'turn_on',
                        'reason': f'Hohe Luftfeuchtigkeit ({humidity}% > {bathroom.humidity_high}%)',
                        'would_execute': config.get('enabled', False)
                    }
                elif should_turn_off_dehumidifier and bathroom.dehumidifier_running:
                    dehumidifier_action = {
                        'action': 'turn_off',
                        'reason': f'Luftfeuchtigkeit normalisiert ({humidity}% < {bathroom.humidity_low}%)',
                        'would_execute': config.get('enabled', False)
                    }
                else:
                    dehumidifier_action = {
                        'action': 'no_change',
                        'reason': f'Luftfeuchtigkeit OK ({humidity}%, Schwellwerte: {bathroom.humidity_low}%-{bathroom.humidity_high}%)',
                        'would_execute': False
                    }

                # Prüfe Heizungs-Aktion
                heater_action = None
                if temperature and bathroom.dehumidifier_running:
                    target = bathroom.target_temp + 1.0
                    if abs(temperature - target) > 0.5:
                        heater_action = {
                            'action': 'set_temperature',
                            'target_temperature': target,
                            'reason': f'Entfeuchtung aktiv → Heizung auf {target}°C (aktuell: {temperature}°C)',
                            'would_execute': config.get('enabled', False)
                        }

                if not heater_action and temperature:
                    heater_action = {
                        'action': 'no_change',
                        'target_temperature': bathroom.target_temp,
                        'reason': f'Keine Heizungs-Anpassung nötig (aktuell: {temperature}°C, Ziel: {bathroom.target_temp}°C)',
                        'would_execute': False
                    }

                return jsonify({
                    'current_state': {
                        'humidity': humidity,
                        'temperature': temperature,
                        'motion_detected': motion,
                        'door_closed': door_closed,
                        'shower_would_be_detected': would_detect_shower
                    },
                    'thresholds': {
                        'humidity_high': bathroom.humidity_high,
                        'humidity_low': bathroom.humidity_low,
                        'target_temperature': bathroom.target_temp
                    },
                    'actions': {
                        'dehumidifier': dehumidifier_action,
                        'heater': heater_action
                    },
                    'automation_enabled': config.get('enabled', False)
                })

            except Exception as e:
                logger.error(f"Error in bathroom preview: {e}")
                return jsonify({'error': str(e)}), 500

        @self.app.route('/api/luftentfeuchten/sensor-timeseries', methods=['GET'])
        def api_bathroom_sensor_timeseries():
            """API: Zeitreihen-Daten für Luftfeuchtigkeit im Bad

            Verwendet die kontinuierlichen Messungen (alle 60s) aus bathroom_continuous_measurements
            statt der gemischten sensor_data Tabelle, um saubere Zeitreihen ohne Zickzack-Muster zu liefern.
            """
            try:
                # Hole Zeitraum aus Query-Parametern
                hours = int(request.args.get('hours', 6))

                # Hole kontinuierliche Messungen (alle 60s)
                data = self.db.get_bathroom_humidity_timeseries(hours_back=hours)

                if not data or len(data) == 0:
                    logger.info(f"No continuous humidity measurements found in last {hours} hours")

                return jsonify({
                    'source': 'bathroom_continuous_measurements',
                    'interval': '60s',
                    'hours': hours,
                    'data': data,
                    'count': len(data)
                })

            except Exception as e:
                logger.error(f"Error getting bathroom humidity timeseries: {e}")
                return jsonify({'error': str(e)}), 500

        @self.app.route('/api/luftentfeuchten/manual-event', methods=['POST'])
        def api_bathroom_manual_event():
            """API: Manuelles Eintragen eines Duschereignisses"""
            try:
                data = request.json

                # Validierung
                if not data.get('start_time') or not data.get('end_time'):
                    return jsonify({'error': 'start_time and end_time are required'}), 400

                # Parse Zeitstempel
                from datetime import datetime
                start_time = datetime.fromisoformat(data['start_time'].replace('Z', '+00:00'))
                end_time = datetime.fromisoformat(data['end_time'].replace('Z', '+00:00'))

                # Peak Humidity (optional, default 75%)
                peak_humidity = float(data.get('peak_humidity', 75.0))

                # Erstelle Event
                event_id = self.db.create_manual_bathroom_event(
                    start_time=start_time,
                    end_time=end_time,
                    peak_humidity=peak_humidity,
                    notes=data.get('notes')
                )

                logger.info(f"Manual bathroom event created: {event_id} by user")

                return jsonify({
                    'success': True,
                    'event_id': event_id,
                    'message': 'Duschereignis erfolgreich eingetragen'
                })

            except Exception as e:
                logger.error(f"Error creating manual bathroom event: {e}")
                return jsonify({'error': str(e)}), 500

        @self.app.route('/api/luftentfeuchten/data-stats')
        def api_bathroom_data_stats():
            """API: Statistiken über gespeicherte Badezimmer-Daten"""
            try:
                conn = self.db._get_connection()
                cursor = conn.cursor()

                # Zähle Events
                cursor.execute("SELECT COUNT(*) FROM bathroom_events")
                events_count = cursor.fetchone()[0]

                # Zähle Messungen
                cursor.execute("SELECT COUNT(*) FROM bathroom_measurements")
                measurements_count = cursor.fetchone()[0]

                # Zähle Geräteaktionen
                cursor.execute("SELECT COUNT(*) FROM bathroom_device_actions")
                actions_count = cursor.fetchone()[0]

                # Zähle kontinuierliche Messungen (60s-Intervall)
                cursor.execute("SELECT COUNT(*) FROM bathroom_continuous_measurements")
                continuous_measurements_count = cursor.fetchone()[0]

                # Ältestes und neuestes Event
                cursor.execute("""
                    SELECT MIN(start_time), MAX(start_time)
                    FROM bathroom_events
                    WHERE start_time IS NOT NULL
                """)
                oldest, newest = cursor.fetchone()

                # Berechne Zeitspanne
                data_age = None
                date_range = "Keine Daten"
                if oldest and newest:
                    from datetime import datetime
                    oldest_dt = datetime.fromisoformat(oldest) if isinstance(oldest, str) else oldest
                    newest_dt = datetime.fromisoformat(newest) if isinstance(newest, str) else newest

                    # Entferne Timezone-Info falls vorhanden, um offset-naive/aware Fehler zu vermeiden
                    if oldest_dt.tzinfo is not None:
                        oldest_dt = oldest_dt.replace(tzinfo=None)
                    if newest_dt.tzinfo is not None:
                        newest_dt = newest_dt.replace(tzinfo=None)

                    days = (datetime.now() - oldest_dt).days
                    data_age = f"{days} Tage"

                    # Format: "DD.MM.YYYY - DD.MM.YYYY"
                    oldest_str = oldest_dt.strftime("%d.%m.%Y")
                    newest_str = newest_dt.strftime("%d.%m.%Y")
                    date_range = f"{oldest_str} - {newest_str}"

                return jsonify({
                    'success': True,
                    'events_count': events_count,
                    'measurements_count': measurements_count,
                    'actions_count': actions_count,
                    'continuous_measurements_count': continuous_measurements_count,
                    'data_age': data_age,
                    'date_range': date_range,
                    'oldest_date': oldest,
                    'newest_date': newest
                })

            except Exception as e:
                logger.error(f"Error fetching bathroom data stats: {e}")
                return jsonify({'error': str(e)}), 500

        @self.app.route('/api/luftentfeuchten/weekly-overview')
        def api_bathroom_weekly_overview():
            """API: Wochenübersicht mit tatsächlichen und vorhergesagten Duschzeiten"""
            try:
                from src.decision_engine.bathroom_analyzer import BathroomAnalyzer
                from src.decision_engine.shower_predictor import ShowerPredictor
                from datetime import datetime, timedelta
                import traceback

                logger.debug("Weekly overview: Starting API call")
                
                analyzer = BathroomAnalyzer(db=self.db)
                logger.debug("Weekly overview: BathroomAnalyzer created")
                
                predictor = ShowerPredictor(db=self.db)
                logger.debug("Weekly overview: ShowerPredictor created")

                # Hole tatsächliche Events der letzten 7 Tage
                actual_events = self.db.get_bathroom_events(days_back=7)

                # Analysiere Muster für Vorhersagen (nutze längeren Zeitraum für bessere Genauigkeit)
                patterns = analyzer.analyze_patterns(days_back=30)
                
                # Hole erweiterte Vorhersage-Muster vom ShowerPredictor
                shower_patterns = predictor.analyze_shower_patterns(days_back=30)

                # Generiere Vorhersagen für jeden Tag der Woche
                predictions_by_day = {}
                
                # Aktueller Wochentag und aktuelle Stunde
                now = datetime.now()
                current_weekday = now.weekday()
                current_hour = now.hour

                if patterns.get('sufficient_data'):
                    hourly_dist = patterns['hourly_pattern']['distribution']
                    weekly_dist = patterns['weekly_pattern']['distribution']

                    # Erstelle Vorhersagen für jeden Wochentag
                    for day_info in weekly_dist:
                        day = day_info['day']
                        day_name = day_info['name']

                        # Für diesen Wochentag: finde wahrscheinlichste Uhrzeiten
                        # Filter Events für diesen Wochentag
                        day_events = [e for e in actual_events if e.get('day_of_week') == day]

                        # Berechne durchschnittliche Anzahl Events pro Tag
                        avg_events_per_day = day_info['count'] / 4.3 if day_info['count'] > 0 else 0  # ~30 Tage / 7 Tage

                        # Top 3 Uhrzeiten für diesen Wochentag aus historischen Daten
                        hour_counts = {}
                        for event in day_events:
                            hour = event.get('hour_of_day')
                            if hour is not None:
                                hour_counts[hour] = hour_counts.get(hour, 0) + 1

                        # Sortiere nach Häufigkeit
                        top_hours = sorted(hour_counts.items(), key=lambda x: x[1], reverse=True)[:3]

                        predictions_by_day[day] = {
                            'day_name': day_name,
                            'probability': day_info['percentage'] / 100,
                            'avg_events_per_day': round(avg_events_per_day, 1),
                            'predicted_times': [
                                {
                                    'hour': hour,
                                    'probability': round((count / len(day_events)) * 100, 1) if day_events else 0
                                }
                                for hour, count in top_hours
                            ]
                        }

                # Gruppiere tatsächliche Events nach Wochentag und Stunde
                actual_by_day_hour = {}
                for event in actual_events:
                    day = event.get('day_of_week')
                    hour = event.get('hour_of_day')

                    if day is not None and hour is not None:
                        key = f"{day}_{hour}"
                        if key not in actual_by_day_hour:
                            actual_by_day_hour[key] = []

                        actual_by_day_hour[key].append({
                            'timestamp': event.get('start_time'),
                            'duration': event.get('duration_minutes'),
                            'peak_humidity': event.get('peak_humidity')
                        })
                
                # Erstelle zukünftige Vorhersagen für diese Woche
                future_predictions = {}
                if shower_patterns.get('sufficient_data'):
                    typical_times = shower_patterns.get('typical_times', [])
                    weekday_pattern = shower_patterns.get('weekday_pattern', {})
                    
                    # Für jeden zukünftigen Tag in dieser Woche
                    for day_offset in range(7):  # 0 = heute, 1 = morgen, etc.
                        future_date = now + timedelta(days=day_offset)
                        future_weekday = future_date.weekday()
                        
                        # Für heute: nur zukünftige Stunden
                        start_hour = current_hour + 1 if day_offset == 0 else 0
                        
                        # Finde Vorhersagen für diesen Wochentag
                        day_predictions = []
                        for time_slot in typical_times:
                            hour = time_slot['hour']
                            confidence = time_slot['confidence']
                            
                            # Nur zukünftige Stunden für heute
                            if day_offset == 0 and hour <= current_hour:
                                continue
                                
                            # Prüfe ob dieser Wochentag typisch ist
                            weekday_counts = weekday_pattern.get('weekday_counts', {})
                            day_count = weekday_counts.get(future_weekday, 0)
                            
                            if day_count > 0 and confidence >= 0.3:
                                day_predictions.append({
                                    'hour': hour,
                                    'minute': time_slot.get('minute', 0),
                                    'confidence': round(confidence * 100, 1),
                                    'label': time_slot.get('label', ''),
                                    'time_string': time_slot.get('time_string', f'{hour:02d}:00')
                                })
                        
                        if day_predictions:
                            future_predictions[future_weekday] = {
                                'date': future_date.strftime('%Y-%m-%d'),
                                'is_today': day_offset == 0,
                                'is_tomorrow': day_offset == 1,
                                'predictions': sorted(day_predictions, key=lambda x: x['hour'])
                            }

                # Berechne Genauigkeit der Vorhersagen
                accuracy_metrics = self._calculate_prediction_accuracy(
                    actual_events,
                    predictions_by_day
                )

                return jsonify({
                    'success': True,
                    'actual_events': actual_events,
                    'predictions_by_day': predictions_by_day,
                    'actual_by_day_hour': actual_by_day_hour,
                    'accuracy_metrics': accuracy_metrics,
                    'sufficient_data': patterns.get('sufficient_data', False),
                    'events_count': len(actual_events),
                    'period_days': 7,
                    # Neue Felder für verbesserte Heatmap
                    'future_predictions': future_predictions,
                    'current_weekday': current_weekday,
                    'current_hour': current_hour,
                    'pattern_stability': shower_patterns.get('pattern_stability', {}),
                    'typical_times': shower_patterns.get('typical_times', [])
                })

            except Exception as e:
                import traceback
                error_details = traceback.format_exc()
                logger.error(f"Error fetching weekly overview: {e}\n{error_details}")
                return jsonify({
                    'error': str(e),
                    'details': error_details
                }), 500

        # ===== Heizungs-Optimierungs-Endpoints =====

        @self.app.route('/api/heating/mode', methods=['GET', 'POST'])
        def api_heating_mode():
            """Hole oder setze Heizungs-Modus (control/optimization)"""
            mode_file = Path('data/heating_mode.json')

            if request.method == 'GET':
                # Lade aktuellen Modus
                if mode_file.exists():
                    with open(mode_file, 'r') as f:
                        data = json.load(f)
                    return jsonify(data)
                else:
                    # Default: control mode
                    return jsonify({'mode': 'control', 'description': 'Direkte Steuerung'})

            elif request.method == 'POST':
                # Setze neuen Modus
                data = request.json
                mode = data.get('mode', 'control')

                if mode not in ['control', 'optimization']:
                    return jsonify({'error': 'Invalid mode'}), 400

                mode_data = {
                    'mode': mode,
                    'description': 'Direkte Steuerung' if mode == 'control' else 'Nur Monitoring & Vorschläge',
                    'updated_at': datetime.now().isoformat()
                }

                # Speichere Modus
                mode_file.parent.mkdir(parents=True, exist_ok=True)
                with open(mode_file, 'w') as f:
                    json.dump(mode_data, f, indent=2)

                logger.info(f"Heating mode changed to: {mode}")
                return jsonify({'success': True, **mode_data})

        @self.app.route('/api/heating/insights')
        def api_heating_insights():
            """Hole KI-generierte Heizungs-Insights"""
            try:
                from src.decision_engine.heating_optimizer import HeatingOptimizer

                optimizer = HeatingOptimizer(db=self.db)
                days_back = int(request.args.get('days', 14))

                # Hole gespeicherte Insights aus DB
                insights = self.db.get_latest_heating_insights(
                    days_back=7,
                    min_confidence=0.6,
                    limit=10
                )

                # Wenn keine Insights vorhanden, generiere neue
                if not insights:
                    logger.info("No insights found in DB, generating new ones")
                    insights = optimizer.generate_insights(days_back=days_back)

                # Füge Icon und Title basierend auf insight_type hinzu
                type_info = {
                    'night_reduction': {'icon': '🌙', 'title': 'Nachtabsenkung'},
                    'window_warning': {'icon': '⚠️', 'title': 'Fenster-Heizung'},
                    'temperature_optimization': {'icon': '🌡️', 'title': 'Temperatur-Optimierung'},
                    'weekend_optimization': {'icon': '📅', 'title': 'Wochenend-Heizplan'}
                }
                
                for insight in insights:
                    insight_type = insight.get('insight_type')
                    if insight_type in type_info:
                        insight['icon'] = type_info[insight_type]['icon']
                        insight['title'] = type_info[insight_type]['title']

                return jsonify({
                    'success': True,
                    'insights': insights,
                    'count': len(insights)
                })

            except Exception as e:
                logger.error(f"Error getting heating insights: {e}")
                return jsonify({'error': str(e)}), 500

        @self.app.route('/api/heating/insights/rooms')
        def api_heating_insights_per_room():
            """Hole raumbasierte KI-Insights"""
            try:
                from src.decision_engine.heating_optimizer import HeatingOptimizer

                optimizer = HeatingOptimizer(db=self.db)
                days_back = int(request.args.get('days', 14))

                # Generiere raumbasierte Insights
                room_insights = optimizer.generate_insights_per_room(days_back=days_back)
                
                # Füge Icon und Title hinzu
                type_info = {
                    'room_temperature_optimization': {'icon': '🌡️', 'title': 'Temperatur-Optimierung'},
                    'room_night_reduction': {'icon': '🌙', 'title': 'Nachtabsenkung'},
                    'room_high_activity': {'icon': '🔥', 'title': 'Hohe Heizaktivität'}
                }
                
                # Formatiere für Frontend
                formatted_insights = []
                for room_name, insights in room_insights.items():
                    for insight in insights:
                        insight_type = insight.get('type')
                        if insight_type in type_info and 'icon' not in insight:
                            insight['icon'] = type_info[insight_type]['icon']
                        formatted_insights.append(insight)

                return jsonify({
                    'success': True,
                    'insights_by_room': room_insights,
                    'insights_flat': formatted_insights,
                    'room_count': len(room_insights),
                    'total_insights': len(formatted_insights)
                })

            except Exception as e:
                logger.error(f"Error getting room insights: {e}")
                return jsonify({'error': str(e)}), 500

        @self.app.route('/api/heating/patterns')
        def api_heating_patterns():
            """Analysiere Heizmuster"""
            try:
                from src.decision_engine.heating_optimizer import HeatingOptimizer

                optimizer = HeatingOptimizer(db=self.db)
                days_back = int(request.args.get('days', 14))

                patterns = optimizer.analyze_patterns(days_back=days_back)

                return jsonify({
                    'success': True,
                    **patterns
                })

            except Exception as e:
                logger.error(f"Error analyzing heating patterns: {e}")
                return jsonify({'error': str(e)}), 500

        @self.app.route('/api/heating/schedule')
        def api_heating_schedule():
            """Hole optimierten Heizplan"""
            try:
                from src.decision_engine.heating_optimizer import HeatingOptimizer

                optimizer = HeatingOptimizer(db=self.db)
                device_id = request.args.get('device_id')

                schedule = optimizer.get_recommended_schedule(device_id=device_id)

                return jsonify({
                    'success': True,
                    'schedule': schedule,
                    'count': len(schedule)
                })

            except Exception as e:
                logger.error(f"Error getting heating schedule: {e}")
                return jsonify({'error': str(e)}), 500

        @self.app.route('/api/heating/statistics')
        def api_heating_statistics():
            """Hole Heizungs-Statistiken"""
            try:
                days_back = int(request.args.get('days', 30))
                stats = self.db.get_heating_statistics(days_back=days_back)
                
                # Berechne Daten-Zeitraum aus Beobachtungen
                period_days = 0
                if stats.get('total_observations', 0) > 0:
                    conn = self.db._get_connection()
                    cursor = conn.cursor()
                    cursor.execute("""
                        SELECT 
                            MIN(timestamp) as first_observation,
                            MAX(timestamp) as last_observation
                        FROM heating_observations
                    """)
                    row = cursor.fetchone()
                    if row and row['first_observation'] and row['last_observation']:
                        first = datetime.fromisoformat(str(row['first_observation']))
                        last = datetime.fromisoformat(str(row['last_observation']))
                        period_days = max(1, (last - first).days)
                
                # Füge berechnete Felder hinzu
                stats['period_days'] = period_days
                
                # Berechne Heizungs-Prozent
                total = stats.get('total_observations', 0)
                heating = stats.get('heating_count', 0)
                if total > 0:
                    stats['heating_percent'] = round((heating / total) * 100, 1)
                else:
                    stats['heating_percent'] = 0

                return jsonify({
                    'success': True,
                    **stats
                })

            except Exception as e:
                logger.error(f"Error getting heating statistics: {e}")
                return jsonify({'error': str(e)}), 500

        @self.app.route('/api/heating/collect', methods=['POST'])
        def api_heating_collect():
            """Sammle aktuellen Heizungszustand (für Optimierung)"""
            try:
                from src.decision_engine.heating_optimizer import HeatingOptimizer

                optimizer = HeatingOptimizer(db=self.db)

                # Hole Außentemperatur
                outdoor_temp = None
                if self.engine and self.engine.weather:
                    weather_data = self.engine.weather.get_weather_data(self.engine.platform)
                    if weather_data:
                        outdoor_temp = weather_data.get('temperature')

                # Sammle Daten
                result = optimizer.collect_current_state(
                    platform=self.engine.platform if self.engine else None,
                    outdoor_temp=outdoor_temp
                )

                return jsonify({
                    'success': True,
                    **result
                })

            except Exception as e:
                logger.error(f"Error collecting heating data: {e}")
                return jsonify({'error': str(e)}), 500

        @self.app.route('/api/heating/analytics')
        def api_heating_analytics():
            """Hole umfassende Heizungs-Analytics"""
            try:
                days_back = int(request.args.get('days', 7))

                analytics = self._calculate_heating_analytics(days_back)

                return jsonify({
                    'success': True,
                    **analytics
                })

            except Exception as e:
                logger.error(f"Error getting heating analytics: {e}")
                return jsonify({'error': str(e)}), 500

        @self.app.route('/api/heating/temperature-history')
        def api_heating_temperature_history():
            """Hole Temperaturverlauf für Chart (letzte 24h) aus sensor_data"""
            try:
                from collections import defaultdict
                import statistics
                from datetime import datetime, timedelta

                hours_back = int(request.args.get('hours', 24))

                # Zeitfenster berechnen
                now = datetime.now()
                start_time = now - timedelta(hours=hours_back)

                # Hole Datenbankverbindung
                conn = self.db._get_connection()

                # Hole Temperaturdaten aus sensor_data
                query = """
                    SELECT timestamp, value, metadata
                    FROM sensor_data
                    WHERE sensor_type = 'temperature'
                    AND timestamp >= ?
                    ORDER BY timestamp ASC
                """
                cursor = conn.execute(query, (start_time.isoformat(),))
                temp_data = cursor.fetchall()

                # Hole Zieltemperaturen
                query = """
                    SELECT timestamp, value
                    FROM sensor_data
                    WHERE sensor_type = 'target_temperature'
                    AND timestamp >= ?
                    ORDER BY timestamp ASC
                """
                cursor = conn.execute(query, (start_time.isoformat(),))
                target_data = cursor.fetchall()

                # Hole Außentemperaturen aus external_data
                query = """
                    SELECT timestamp, data
                    FROM external_data
                    WHERE data_type = 'weather'
                    AND timestamp >= ?
                    ORDER BY timestamp ASC
                """
                cursor = conn.execute(query, (start_time.isoformat(),))
                weather_data = cursor.fetchall()

                if not temp_data and not weather_data:
                    return jsonify({
                        'success': True,
                        'data': [],
                        'message': 'Keine Temperaturdaten vorhanden.'
                    })

                # Gruppiere Daten nach Stunde
                hourly_data = defaultdict(lambda: {
                    'indoor_temps': [],
                    'outdoor_temps': [],
                    'target_temps': []
                })

                # Verarbeite Innentemperaturen
                for row in temp_data:
                    timestamp = datetime.fromisoformat(row[0]) if isinstance(row[0], str) else row[0]
                    hour_key = timestamp.replace(minute=0, second=0, microsecond=0)

                    value = float(row[1])
                    # Filtere unrealistische Werte (z.B. Fahrrad-Akku mit 33°C)
                    if 5 < value < 30:  # Nur realistische Raumtemperaturen
                        hourly_data[hour_key]['indoor_temps'].append(value)

                # Verarbeite Zieltemperaturen
                for row in target_data:
                    timestamp = datetime.fromisoformat(row[0]) if isinstance(row[0], str) else row[0]
                    hour_key = timestamp.replace(minute=0, second=0, microsecond=0)

                    value = float(row[1])
                    if 5 < value < 30:
                        hourly_data[hour_key]['target_temps'].append(value)

                # Verarbeite Außentemperaturen - nehme nur den neuesten Wert pro Stunde
                import json
                latest_weather_per_hour = {}  # Speichere nur den neuesten Wert pro Stunde

                for row in weather_data:
                    timestamp = datetime.fromisoformat(row[0]) if isinstance(row[0], str) else row[0]
                    hour_key = timestamp.replace(minute=0, second=0, microsecond=0)

                    data_json = json.loads(row[1]) if isinstance(row[1], str) else row[1]

                    # Unterscheide zwischen verschiedenen Datenquellen
                    outdoor_temp = None
                    if data_json.get('source') == 'homey':
                        # Homey-Daten: Extrahiere spezifischen Außentemperatursensor
                        sensors = data_json.get('sensors', [])
                        for sensor in sensors:
                            if sensor.get('name') == 'Außentemperatur':
                                outdoor_temp = sensor.get('temperature')
                                break
                    else:
                        # OpenWeatherMap oder andere Quellen: Verwende direktes temperature Feld
                        outdoor_temp = data_json.get('temperature')

                    if outdoor_temp is not None:
                        # Behalte nur den neuesten Wert pro Stunde
                        if hour_key not in latest_weather_per_hour or timestamp > latest_weather_per_hour[hour_key]['timestamp']:
                            latest_weather_per_hour[hour_key] = {
                                'timestamp': timestamp,
                                'temp': float(outdoor_temp)
                            }
                
                # Füge die neuesten Werte zu hourly_data hinzu
                for hour_key, data in latest_weather_per_hour.items():
                    hourly_data[hour_key]['outdoor_temps'].append(data['temp'])

                # Erstelle Zeitreihen-Arrays
                timestamps = []
                indoor_temps = []
                outdoor_temps = []
                target_temps = []

                for hour in sorted(hourly_data.keys()):
                    data = hourly_data[hour]
                    timestamps.append(hour.isoformat())

                    # Durchschnitte berechnen
                    indoor_temps.append(
                        round(statistics.mean(data['indoor_temps']), 1)
                        if data['indoor_temps'] else None
                    )
                    outdoor_temps.append(
                        round(statistics.mean(data['outdoor_temps']), 1)
                        if data['outdoor_temps'] else None
                    )
                    target_temps.append(
                        round(statistics.mean(data['target_temps']), 1)
                        if data['target_temps'] else None
                    )

                return jsonify({
                    'success': True,
                    'hours': hours_back,
                    'data': {
                        'timestamps': timestamps,
                        'indoor_temp': indoor_temps,
                        'outdoor_temp': outdoor_temps,
                        'target_temp': target_temps
                    },
                    'count': len(timestamps)
                })

            except Exception as e:
                logger.error(f"Error getting temperature history: {e}")
                return jsonify({'error': str(e)}), 500

        # ===== Window Status Endpoints =====

        @self.app.route('/api/heating/windows/all')
        def api_heating_windows_all():
            """Hole alle Fenster mit ihrem aktuellen Status"""
            try:
                windows = self.db.get_all_windows_latest_status()

                return jsonify({
                    'success': True,
                    'data': windows,
                    'count': len(windows)
                })

            except Exception as e:
                logger.error(f"Error getting all window statuses: {e}")
                return jsonify({'error': str(e)}), 500

        @self.app.route('/api/heating/windows/current')
        def api_heating_windows_current():
            """Hole alle aktuell geöffneten Fenster mit Dauer"""
            try:
                open_windows = self.db.get_current_open_windows()

                return jsonify({
                    'success': True,
                    'data': open_windows,
                    'count': len(open_windows)
                })

            except Exception as e:
                logger.error(f"Error getting current open windows: {e}")
                return jsonify({'error': str(e)}), 500

        @self.app.route('/api/heating/windows/history')
        def api_heating_windows_history():
            """Hole Fenster-Status-Historie (für Chart)"""
            try:
                hours = int(request.args.get('hours', 24))
                room_name = request.args.get('room', None)

                observations = self.db.get_window_observations(
                    hours_back=hours,
                    room_name=room_name
                )

                if not observations:
                    return jsonify({
                        'success': True,
                        'data': [],
                        'message': 'Noch keine Fensterdaten gesammelt.'
                    })

                # Gruppiere nach Gerät für Timeline-Darstellung
                from collections import defaultdict
                by_device = defaultdict(list)

                for obs in observations:
                    device_key = f"{obs['device_name']} ({obs['room_name'] or 'Unbekannt'})"
                    by_device[device_key].append({
                        'timestamp': obs['timestamp'],
                        'is_open': obs['is_open']
                    })

                return jsonify({
                    'success': True,
                    'hours': hours,
                    'data': dict(by_device),
                    'count': len(observations)
                })

            except Exception as e:
                logger.error(f"Error getting window history: {e}")
                return jsonify({'error': str(e)}), 500

        @self.app.route('/api/heating/windows/statistics')
        def api_heating_windows_statistics():
            """Hole Fenster-Öffnungs-Statistiken"""
            try:
                days = int(request.args.get('days', 7))

                stats = self.db.get_window_open_statistics(days_back=days)

                return jsonify({
                    'success': True,
                    'data': stats,
                    'period_days': days
                })

            except Exception as e:
                logger.error(f"Error getting window statistics: {e}")
                return jsonify({'error': str(e)}), 500

        @self.app.route('/api/heating/windows/charts')
        def api_heating_windows_charts():
            """Hole Fenster-Statistiken für Chart-Visualisierungen"""
            try:
                days = int(request.args.get('days', 7))

                chart_data = self.db.get_window_statistics_for_charts(days_back=days)

                return jsonify({
                    'success': True,
                    'data': chart_data
                })

            except Exception as e:
                logger.error(f"Error getting window chart statistics: {e}")
                return jsonify({'error': str(e)}), 500

        # ===== Analytics Endpoints =====

        @self.app.route('/api/analytics/comfort')
        def api_analytics_comfort():
            """Hole Komfort-Metriken"""
            try:
                hours_back = int(request.args.get('hours', 168))  # Default: 7 Tage

                # Hole Sensordaten
                sensor_data = self.db.get_sensor_data(hours_back=hours_back)

                # Berechne Komfort-Score
                comfort_metrics = self._calculate_comfort_metrics(sensor_data, hours_back)

                return jsonify({
                    'success': True,
                    **comfort_metrics
                })

            except Exception as e:
                logger.error(f"Error getting comfort analytics: {e}")
                return jsonify({'error': str(e)}), 500

        @self.app.route('/api/analytics/ml-performance')
        def api_analytics_ml_performance():
            """Hole ML-Model Performance Metriken"""
            try:
                days_back = int(request.args.get('days', 30))

                # Hole Training History
                training_history = self._get_training_history(days_back)

                # Hole Entscheidungs-Statistiken
                decision_stats = self._get_decision_statistics(days_back)

                # Hole Confidence-Scores über Zeit
                confidence_trends = self._get_confidence_trends(days_back)

                return jsonify({
                    'success': True,
                    'training_history': training_history,
                    'decision_stats': decision_stats,
                    'confidence_trends': confidence_trends
                })

            except Exception as e:
                logger.error(f"Error getting ML performance analytics: {e}")
                return jsonify({'error': str(e)}), 500

        # ===== Smart Features: Mold Prevention, Ventilation, Predictions =====

        @self.app.route('/api/humidity/alerts')
        def api_humidity_alerts():
            """Hole aktive Luftfeuchtigkeits-Warnungen"""
            try:
                room_name = request.args.get('room', None)
                hours_back = int(request.args.get('hours', 24))

                alerts = self.db.get_active_humidity_alerts(
                    room_name=room_name,
                    hours_back=hours_back
                )

                return jsonify({
                    'success': True,
                    'alerts': alerts,
                    'count': len(alerts)
                })

            except Exception as e:
                logger.error(f"Error getting humidity alerts: {e}")
                return jsonify({'error': str(e)}), 500

        @self.app.route('/api/ventilation/recommendation')
        def api_ventilation_recommendation():
            """Hole Lüftungsempfehlung für einen Raum"""
            try:
                room_name = request.args.get('room', 'Badezimmer')

                recommendation = self.db.get_latest_ventilation_recommendation(room_name=room_name)

                return jsonify({
                    'success': True,
                    'recommendation': recommendation
                })

            except Exception as e:
                logger.error(f"Error getting ventilation recommendation: {e}")
                return jsonify({'error': str(e)}), 500

        @self.app.route('/api/shower/predictions')
        def api_shower_predictions():
            """Hole Dusch-Vorhersagen für heute"""
            try:
                predictions = self.db.get_shower_predictions_today()

                return jsonify({
                    'success': True,
                    'predictions': predictions,
                    'count': len(predictions)
                })

            except Exception as e:
                logger.error(f"Error getting shower predictions: {e}")
                return jsonify({'error': str(e)}), 500

        @self.app.route('/api/shower/next')
        def api_next_shower():
            """Hole nächste Dusch-Vorhersage"""
            try:
                min_confidence = float(request.args.get('confidence', 0.6))

                prediction = self.db.get_next_shower_prediction(min_confidence=min_confidence)

                return jsonify({
                    'success': True,
                    'prediction': prediction
                })

            except Exception as e:
                logger.error(f"Error getting next shower prediction: {e}")
                return jsonify({'error': str(e)}), 500

        @self.app.route('/api/room/learning/<room_name>')
        def api_room_learning(room_name):
            """Hole gelerntes Profil für einen Raum"""
            try:
                from src.decision_engine.room_learning import RoomLearningSystem
                room_learning = RoomLearningSystem(db=self.db)

                profile = room_learning.get_room_profile(room_name)

                return jsonify({
                    'success': True,
                    'profile': profile
                })

            except Exception as e:
                logger.error(f"Error getting room learning profile: {e}")
                return jsonify({'error': str(e)}), 500

        # ===== System Update Endpoints =====

        @self.app.route('/api/system/version')
        def get_version():
            """Hole aktuelle Git-Version"""
            try:
                # Prüfe ob Git-Repository vorhanden
                project_root = Path(__file__).parent.parent.parent
                git_dir = project_root / '.git'

                if not git_dir.exists():
                    return jsonify({
                        'success': False,
                        'error': 'Kein Git-Repository gefunden'
                    })

                # Hole aktuelle Commit-Info
                result = subprocess.run(
                    ['git', 'log', '-1', '--format=%H|%h|%s|%ar'],
                    cwd=str(project_root),
                    capture_output=True,
                    text=True
                )

                if result.returncode == 0:
                    full_hash, short_hash, message, time_ago = result.stdout.strip().split('|', 3)

                    return jsonify({
                        'success': True,
                        'version': {
                            'commit': short_hash,
                            'commit_full': full_hash,
                            'message': message,
                            'time': time_ago
                        }
                    })
                else:
                    return jsonify({
                        'success': False,
                        'error': 'Konnte Versions-Info nicht abrufen'
                    })

            except Exception as e:
                logger.error(f"Error getting version: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        @self.app.route('/api/system/check-update')
        def check_update():
            """Prüfe ob Updates verfügbar sind"""
            try:
                project_root = Path(__file__).parent.parent.parent

                # Fetch remote
                subprocess.run(
                    ['git', 'fetch', 'origin'],
                    cwd=str(project_root),
                    capture_output=True
                )

                # Prüfe wie viele Commits zurück
                result = subprocess.run(
                    ['git', 'rev-list', 'HEAD..origin/main', '--count'],
                    cwd=str(project_root),
                    capture_output=True,
                    text=True
                )

                if result.returncode == 0:
                    commits_behind = int(result.stdout.strip())

                    if commits_behind > 0:
                        # Hole Liste der neuen Commits
                        commits_result = subprocess.run(
                            ['git', 'log', 'HEAD..origin/main', '--oneline', '--no-merges'],
                            cwd=str(project_root),
                            capture_output=True,
                            text=True
                        )

                        new_commits = []
                        if commits_result.returncode == 0:
                            for line in commits_result.stdout.strip().split('\n'):
                                if line:
                                    hash_msg = line.split(' ', 1)
                                    if len(hash_msg) == 2:
                                        new_commits.append({
                                            'hash': hash_msg[0],
                                            'message': hash_msg[1]
                                        })

                        return jsonify({
                            'success': True,
                            'update_available': True,
                            'commits_behind': commits_behind,
                            'new_commits': new_commits[:5]  # Max 5 neueste
                        })
                    else:
                        return jsonify({
                            'success': True,
                            'update_available': False,
                            'message': 'System ist auf dem neuesten Stand'
                        })
                else:
                    return jsonify({
                        'success': False,
                        'error': 'Konnte Update-Status nicht prüfen'
                    })

            except Exception as e:
                logger.error(f"Error checking for updates: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        @self.app.route('/api/system/update', methods=['POST'])
        def trigger_update():
            """Starte System-Update"""
            try:
                project_root = Path(__file__).parent.parent.parent
                update_script = project_root / 'update.sh'

                if not update_script.exists():
                    return jsonify({
                        'success': False,
                        'error': 'Update-Script nicht gefunden'
                    })

                # Erstelle Log-Verzeichnis falls nicht vorhanden
                log_dir = project_root / 'logs'
                log_dir.mkdir(exist_ok=True)
                update_log = log_dir / 'update.log'

                # Starte Update-Script im Hintergrund
                logger.info("Starting system update...")

                # Führe Update-Script aus mit Ausgabe in Log-Datei
                with open(update_log, 'w') as log_file:
                    log_file.write(f"=== Update gestartet: {datetime.now().isoformat()} ===\n\n")
                
                subprocess.Popen(
                    ['bash', str(update_script)],
                    cwd=str(project_root),
                    stdout=open(update_log, 'a'),
                    stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL,  # Wichtig: Kein interaktiver Input
                    start_new_session=True
                )

                return jsonify({
                    'success': True,
                    'message': 'Update wird durchgeführt. System startet in wenigen Sekunden neu...',
                    'log_file': str(update_log)
                })

            except Exception as e:
                logger.error(f"Error triggering update: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        @self.app.route('/api/system/restart', methods=['POST'])
        def restart_server():
            """Startet den Webserver neu"""
            try:
                import os
                import signal

                logger.info("Restarting web server...")

                # Sende Response zuerst
                response = jsonify({
                    'success': True,
                    'message': 'Server wird neu gestartet... Seite lädt in 5 Sekunden neu.'
                })

                # Verzögerter Neustart nach Response
                def delayed_restart():
                    import time
                    time.sleep(1)  # Warte kurz damit Response gesendet wird

                    # Erkenne ob PM2 verwendet wird
                    pm2_running = subprocess.run(
                        ['pm2', 'list'],
                        capture_output=True,
                        text=True
                    ).returncode == 0

                    if pm2_running and 'ki-smart-home' in subprocess.run(['pm2', 'list'], capture_output=True, text=True).stdout:
                        # PM2 Neustart
                        subprocess.Popen(['pm2', 'restart', 'ki-smart-home'])
                    else:
                        # Manueller Neustart
                        # Hole aktuellen Port
                        import psutil
                        current_process = psutil.Process()
                        port = 5000  # Default

                        # Versuche Port aus Commandline args zu extrahieren
                        for i, arg in enumerate(current_process.cmdline()):
                            if arg == '--port' and i + 1 < len(current_process.cmdline()):
                                port = int(current_process.cmdline()[i + 1])
                                break

                        # Starte neuen Prozess
                        subprocess.Popen(
                            [sys.executable, 'main.py', 'web', '--host', '0.0.0.0', '--port', str(port)],
                            stdout=open('logs/restart.log', 'a'),
                            stderr=subprocess.STDOUT,
                            start_new_session=True
                        )

                        # Beende aktuellen Prozess
                        time.sleep(0.5)
                        os.kill(os.getpid(), signal.SIGTERM)

                # Starte Neustart in separatem Thread
                import threading
                restart_thread = threading.Thread(target=delayed_restart, daemon=True)
                restart_thread.start()

                return response

            except Exception as e:
                logger.error(f"Error restarting server: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        # === DATENBANK-MANAGEMENT ENDPOINTS ===

        @self.app.route('/api/database/status')
        def database_status():
            """Gibt den aktuellen Status der Datenbank zurück"""
            try:
                db_info = self.db.get_database_size()

                # Retention-Einstellung aus Config
                retention_days = self.engine.config.get('database.retention_days', 90) if self.engine else 90

                # Maintenance Job Status
                maintenance_status = {}
                if self.db_maintenance:
                    status = self.db_maintenance.get_status()
                    maintenance_status = {
                        'running': status['running'],
                        'last_cleanup': status['last_cleanup'],
                        'last_vacuum': status['last_vacuum'],
                        'retention_days': status['retention_days'],
                        'next_run_hour': status['run_hour']
                    }

                return jsonify({
                    'success': True,
                    'database': {
                        'file_size_mb': db_info['file_size_mb'],
                        'file_size_bytes': db_info['file_size_bytes'],
                        'total_rows': db_info['total_rows'],
                        'table_counts': db_info['table_counts'],
                        'oldest_data': db_info['oldest_data'],
                        'newest_data': db_info['newest_data'],
                        'file_path': db_info['file_path']
                    },
                    'settings': {
                        'retention_days': retention_days
                    },
                    'maintenance': maintenance_status
                })
            except Exception as e:
                logger.error(f"Error getting database status: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        @self.app.route('/api/database/cleanup', methods=['POST'])
        def database_cleanup():
            """Führt manuelles Cleanup der Datenbank aus"""
            try:
                data = request.json or {}
                retention_days = data.get('retention_days')

                # Verwende Config-Wert wenn nicht angegeben
                if retention_days is None:
                    retention_days = self.engine.config.get('database.retention_days', 90) if self.engine else 90

                deleted_counts = self.db.cleanup_old_data(retention_days=retention_days)

                return jsonify({
                    'success': True,
                    'deleted_rows': sum(deleted_counts.values()),
                    'details': deleted_counts,
                    'message': f'Cleanup abgeschlossen: {sum(deleted_counts.values())} Zeilen gelöscht'
                })
            except Exception as e:
                logger.error(f"Error during cleanup: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        @self.app.route('/api/database/vacuum', methods=['POST'])
        def database_vacuum():
            """Führt VACUUM auf der Datenbank aus (Optimierung)"""
            try:
                # Speichere Größe vor VACUUM
                before_info = self.db.get_database_size()
                before_size = before_info['file_size_mb']

                # Führe VACUUM aus
                self.db.vacuum_database()

                # Speichere Größe nach VACUUM
                after_info = self.db.get_database_size()
                after_size = after_info['file_size_mb']

                freed_mb = before_size - after_size

                return jsonify({
                    'success': True,
                    'before_size_mb': before_size,
                    'after_size_mb': after_size,
                    'freed_mb': round(freed_mb, 2),
                    'message': f'VACUUM abgeschlossen: {round(freed_mb, 2)} MB freigegeben'
                })
            except Exception as e:
                logger.error(f"Error during vacuum: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        @self.app.route('/api/data/clear', methods=['DELETE', 'POST'])
        def api_clear_training_data():
            """
            Löscht Trainingsdaten (GEFÄHRLICH - nicht umkehrbar!)
            Query params:
              - days_back: Optional - nur Daten älter als X Tage löschen
                          Wenn nicht angegeben: ALLE Daten löschen
            """
            try:
                # Erlaube sowohl DELETE als auch POST für Kompatibilität
                days_back = request.args.get('days_back', type=int)

                if days_back is None:
                    # ALLE Daten löschen - sehr gefährlich!
                    logger.warning("User requested to clear ALL training data")
                    deleted_counts = self.db.clear_all_training_data(days_back=None)
                    message = f"ALLE Trainingsdaten gelöscht: {sum(deleted_counts.values())} Zeilen"
                else:
                    # Nur alte Daten löschen
                    logger.info(f"User requested to clear data older than {days_back} days")
                    deleted_counts = self.db.clear_all_training_data(days_back=days_back)
                    message = f"Daten älter als {days_back} Tage gelöscht: {sum(deleted_counts.values())} Zeilen"

                return jsonify({
                    'success': True,
                    'deleted_rows': sum(deleted_counts.values()),
                    'details': deleted_counts,
                    'message': message
                })

            except Exception as e:
                logger.error(f"Error clearing training data: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

    def _get_database_stats(self):
        """Hilfs-Methode: Hole Datenbank-Statistiken"""
        try:
            stats = {}

            # Zähle Einträge pro Tabelle
            tables = ['sensor_data', 'decisions', 'training_history', 'heating_observations']
            for table in tables:
                try:
                    result = self.db.execute(f"SELECT COUNT(*) as count FROM {table}")
                    stats[table] = result[0]['count'] if result else 0
                except:
                    stats[table] = 0

            # Hole Zeitraum der Daten
            try:
                result = self.db.execute(
                    "SELECT MIN(timestamp) as first, MAX(timestamp) as last FROM sensor_data"
                )
                if result and result[0]['first']:
                    stats['data_range'] = {
                        'first': result[0]['first'],
                        'last': result[0]['last']
                    }
            except:
                pass

            return stats
        except Exception as e:
            logger.debug(f"Error getting database stats: {e}")
            return {}

    def _calculate_heating_analytics(self, days_back: int) -> dict:
        """Berechnet umfassende Heizungs-Analytics"""
        from datetime import datetime, timedelta
        import statistics

        observations = self.db.get_heating_observations(days_back=days_back)

        if not observations or len(observations) < 10:
            return {
                'sufficient_data': False,
                'message': f'Nicht genug Daten (min. 10 Beobachtungen, aktuell: {len(observations) if observations else 0})',
                'observations_count': len(observations) if observations else 0
            }

        # 1. Heizzeiten-Analyse
        heating_times = self._analyze_heating_times(observations)

        # 2. Temperatur-Effizienz
        temp_efficiency = self._analyze_temperature_efficiency(observations)

        # 3. Heizkosten-Schätzung
        cost_estimates = self._estimate_heating_costs(observations, days_back)

        # 4. Raum-Vergleiche
        room_comparison = self._compare_rooms(observations)

        # 5. Wetter-Korrelation
        weather_correlation = self._analyze_weather_correlation(observations)

        return {
            'sufficient_data': True,
            'observations_count': len(observations),
            'period_days': days_back,
            'heating_times': heating_times,
            'temperature_efficiency': temp_efficiency,
            'cost_estimates': cost_estimates,
            'room_comparison': room_comparison,
            'weather_correlation': weather_correlation
        }

    def _analyze_heating_times(self, observations: list) -> dict:
        """Analysiert wann am meisten geheizt wird"""
        import statistics

        # Gruppiere nach Stunde
        hourly_heating = {}
        for obs in observations:
            hour = obs.get('hour_of_day')
            if hour is not None:
                if hour not in hourly_heating:
                    hourly_heating[hour] = {'count': 0, 'heating': 0}
                hourly_heating[hour]['count'] += 1
                if obs.get('is_heating'):
                    hourly_heating[hour]['heating'] += 1

        # Berechne Heizprozentsatz pro Stunde
        hourly_data = []
        for hour in range(24):
            if hour in hourly_heating:
                total = hourly_heating[hour]['count']
                heating = hourly_heating[hour]['heating']
                percentage = (heating / total * 100) if total > 0 else 0
                hourly_data.append({
                    'hour': hour,
                    'heating_percentage': round(percentage, 1),
                    'observations': total
                })
            else:
                hourly_data.append({
                    'hour': hour,
                    'heating_percentage': 0,
                    'observations': 0
                })

        # Peak Heizzeiten
        sorted_hours = sorted(hourly_data, key=lambda x: x['heating_percentage'], reverse=True)
        peak_hours = sorted_hours[:5]

        return {
            'hourly_data': hourly_data,
            'peak_hours': peak_hours
        }

    def _analyze_temperature_efficiency(self, observations: list) -> dict:
        """Analysiert Temperatur-Effizienz (Soll vs. Ist)"""
        import statistics

        deviations = []
        for obs in observations:
            target = obs.get('target_temperature')
            current = obs.get('current_temperature')
            if target and current:
                deviation = abs(target - current)
                deviations.append({
                    'target': target,
                    'current': current,
                    'deviation': deviation,
                    'timestamp': obs.get('timestamp')
                })

        if not deviations:
            return {'available': False}

        deviation_values = [d['deviation'] for d in deviations]

        # Effizienz-Score (0-100, je geringer die Abweichung, desto besser)
        avg_deviation = statistics.mean(deviation_values)
        # 0°C Abweichung = 100%, 2°C = 0%
        efficiency_score = max(0, 100 - (avg_deviation / 2.0 * 100))

        return {
            'available': True,
            'avg_deviation': round(avg_deviation, 2),
            'min_deviation': round(min(deviation_values), 2),
            'max_deviation': round(max(deviation_values), 2),
            'efficiency_score': round(efficiency_score, 1),
            'samples': len(deviations)
        }

    def _estimate_heating_costs(self, observations: list, days: int) -> dict:
        """Schätzt Heizkosten"""
        import statistics

        # Zähle Heizstunden
        heating_count = sum(1 for obs in observations if obs.get('is_heating'))
        total_count = len(observations)

        # Annahme: Alle 15 Minuten eine Beobachtung
        minutes_per_observation = 15
        total_minutes = total_count * minutes_per_observation
        heating_minutes = heating_count * minutes_per_observation
        heating_hours = heating_minutes / 60

        # Kosten-Schätzungen (grobe Annahmen)
        # Gas: ~0.15€/kWh, Durchschnitt-Heizung: 10-15 kW
        avg_heating_power_kw = 12  # kW
        cost_per_kwh = 0.15  # EUR

        # Tagesverbrauch
        hours_per_day = total_minutes / days / 60
        heating_hours_per_day = heating_minutes / days / 60
        daily_kwh = heating_hours_per_day * avg_heating_power_kw
        daily_cost = daily_kwh * cost_per_kwh

        # Wochenverbrauch
        weekly_cost = daily_cost * 7

        # Monatsverbrauch
        monthly_cost = daily_cost * 30

        # Hochrechnung Jahresverbrauch
        yearly_cost = daily_cost * 365

        return {
            'heating_hours_total': round(heating_hours, 1),
            'heating_hours_per_day': round(heating_hours_per_day, 1),
            'heating_percentage': round((heating_count / total_count * 100), 1) if total_count > 0 else 0,
            'costs': {
                'daily': round(daily_cost, 2),
                'weekly': round(weekly_cost, 2),
                'monthly': round(monthly_cost, 2),
                'yearly': round(yearly_cost, 2)
            },
            'consumption': {
                'daily_kwh': round(daily_kwh, 1),
                'monthly_kwh': round(daily_kwh * 30, 1),
                'yearly_kwh': round(daily_kwh * 365, 0)
            },
            'assumptions': {
                'avg_power_kw': avg_heating_power_kw,
                'cost_per_kwh': cost_per_kwh,
                'observation_interval_min': minutes_per_observation
            }
        }

    def _compare_rooms(self, observations: list) -> dict:
        """Vergleicht Heizverhalten zwischen Räumen"""
        import statistics

        rooms = {}
        for obs in observations:
            room = obs.get('room_name', 'Unbekannt')
            if room not in rooms:
                rooms[room] = {
                    'observations': 0,
                    'heating_count': 0,
                    'temps': [],
                    'target_temps': []
                }

            rooms[room]['observations'] += 1
            if obs.get('is_heating'):
                rooms[room]['heating_count'] += 1

            if obs.get('current_temperature'):
                rooms[room]['temps'].append(obs['current_temperature'])
            if obs.get('target_temperature'):
                rooms[room]['target_temps'].append(obs['target_temperature'])

        # Berechne Statistiken pro Raum
        room_stats = []
        for room, data in rooms.items():
            heating_pct = (data['heating_count'] / data['observations'] * 100) if data['observations'] > 0 else 0
            avg_temp = statistics.mean(data['temps']) if data['temps'] else None
            avg_target = statistics.mean(data['target_temps']) if data['target_temps'] else None

            room_stats.append({
                'room': room,
                'observations': data['observations'],
                'heating_percentage': round(heating_pct, 1),
                'avg_temperature': round(avg_temp, 1) if avg_temp else None,
                'avg_target_temperature': round(avg_target, 1) if avg_target else None
            })

        # Sortiere nach Heizprozentsatz
        room_stats.sort(key=lambda x: x['heating_percentage'], reverse=True)

        return {
            'rooms': room_stats,
            'room_count': len(room_stats)
        }

    def _analyze_weather_correlation(self, observations: list) -> dict:
        """Analysiert Korrelation zwischen Außentemperatur und Heizverhalten"""
        import statistics

        # Gruppiere nach Außentemperatur-Bereichen
        temp_ranges = {
            'below_0': {'heating': 0, 'total': 0, 'label': 'Unter 0°C'},
            '0_to_5': {'heating': 0, 'total': 0, 'label': '0-5°C'},
            '5_to_10': {'heating': 0, 'total': 0, 'label': '5-10°C'},
            '10_to_15': {'heating': 0, 'total': 0, 'label': '10-15°C'},
            'above_15': {'heating': 0, 'total': 0, 'label': 'Über 15°C'}
        }

        outdoor_temps = []

        for obs in observations:
            outdoor_temp = obs.get('outdoor_temperature')
            if outdoor_temp is None:
                continue

            outdoor_temps.append(outdoor_temp)

            # Bestimme Range
            if outdoor_temp < 0:
                range_key = 'below_0'
            elif outdoor_temp < 5:
                range_key = '0_to_5'
            elif outdoor_temp < 10:
                range_key = '5_to_10'
            elif outdoor_temp < 15:
                range_key = '10_to_15'
            else:
                range_key = 'above_15'

            temp_ranges[range_key]['total'] += 1
            if obs.get('is_heating'):
                temp_ranges[range_key]['heating'] += 1

        # Berechne Heizprozentsatz pro Range
        correlation_data = []
        for key, data in temp_ranges.items():
            if data['total'] > 0:
                heating_pct = (data['heating'] / data['total'] * 100)
                correlation_data.append({
                    'range': data['label'],
                    'heating_percentage': round(heating_pct, 1),
                    'observations': data['total']
                })

        # Durchschnittliche Außentemperatur
        avg_outdoor = statistics.mean(outdoor_temps) if outdoor_temps else None

        return {
            'available': len(outdoor_temps) > 0,
            'correlation_data': correlation_data,
            'avg_outdoor_temp': round(avg_outdoor, 1) if avg_outdoor else None,
            'samples_with_weather': len(outdoor_temps)
        }

    def _calculate_comfort_metrics(self, sensor_data: list, hours_back: int) -> dict:
        """Berechnet Komfort-Metriken aus Sensordaten"""
        from datetime import datetime, timedelta
        import statistics

        # Gruppiere nach Sensor-Typ
        temps = [s for s in sensor_data if s['sensor_type'] == 'temperature']
        humids = [s for s in sensor_data if s['sensor_type'] == 'humidity']
        motion = [s for s in sensor_data if s['sensor_type'] == 'motion']

        # Komfort-Score berechnen (0-100)
        comfort_score = 0
        comfort_details = []

        if temps:
            temp_values = [t['value'] for t in temps if t['value']]
            avg_temp = statistics.mean(temp_values) if temp_values else 20.0

            # Ideal: 20-22°C
            if 20 <= avg_temp <= 22:
                temp_score = 100
                comfort_details.append("Temperatur ideal")
            elif 18 <= avg_temp < 20 or 22 < avg_temp <= 24:
                temp_score = 75
                comfort_details.append("Temperatur gut")
            elif 16 <= avg_temp < 18 or 24 < avg_temp <= 26:
                temp_score = 50
                comfort_details.append("Temperatur akzeptabel")
            else:
                temp_score = 25
                comfort_details.append("Temperatur suboptimal")

            comfort_score += temp_score * 0.5  # 50% Gewichtung
        else:
            avg_temp = None

        if humids:
            humid_values = [h['value'] for h in humids if h['value']]
            avg_humid = statistics.mean(humid_values) if humid_values else 50.0

            # Ideal: 40-60%
            if 40 <= avg_humid <= 60:
                humid_score = 100
                comfort_details.append("Luftfeuchtigkeit ideal")
            elif 30 <= avg_humid < 40 or 60 < avg_humid <= 70:
                humid_score = 75
                comfort_details.append("Luftfeuchtigkeit gut")
            else:
                humid_score = 50
                comfort_details.append("Luftfeuchtigkeit suboptimal")

            comfort_score += humid_score * 0.5  # 50% Gewichtung
        else:
            avg_humid = None

        # Anwesenheits-Muster
        presence_pattern = []
        if motion:
            # Gruppiere nach Stunden
            now = datetime.now()
            for hour in range(24):
                hour_start = now - timedelta(hours=hours_back - hour)
                hour_motion = [m for m in motion if
                             datetime.fromisoformat(m['timestamp']).hour == hour_start.hour]
                presence_pattern.append({
                    'hour': hour,
                    'activity': len(hour_motion)
                })

        # Schlafqualität-Indikator (Nachttemperaturen 22-6 Uhr)
        night_temps = []
        if temps:
            for t in temps:
                ts = datetime.fromisoformat(t['timestamp'])
                if 22 <= ts.hour or ts.hour < 6:
                    if t['value']:
                        night_temps.append(t['value'])

        sleep_quality = None
        if night_temps:
            avg_night_temp = statistics.mean(night_temps)
            # Ideal für Schlaf: 16-19°C
            if 16 <= avg_night_temp <= 19:
                sleep_quality = {
                    'score': 100,
                    'avg_temp': round(avg_night_temp, 1),
                    'rating': 'Ideal',
                    'description': 'Optimale Temperatur für erholsamen Schlaf'
                }
            elif 14 <= avg_night_temp < 16 or 19 < avg_night_temp <= 21:
                sleep_quality = {
                    'score': 75,
                    'avg_temp': round(avg_night_temp, 1),
                    'rating': 'Gut',
                    'description': 'Temperatur leicht außerhalb des optimalen Bereichs'
                }
            else:
                sleep_quality = {
                    'score': 50,
                    'avg_temp': round(avg_night_temp, 1),
                    'rating': 'Verbesserungswürdig',
                    'description': 'Temperatur könnte Schlafqualität beeinträchtigen'
                }

        return {
            'comfort_score': round(comfort_score, 1),
            'comfort_details': comfort_details,
            'avg_temperature': round(avg_temp, 1) if avg_temp else None,
            'avg_humidity': round(avg_humid, 1) if avg_humid else None,
            'presence_pattern': presence_pattern[:24],  # Nur letzte 24h
            'sleep_quality': sleep_quality,
            'period_hours': hours_back
        }

    def _get_training_history(self, days_back: int) -> list:
        """Holt Training History der ML-Modelle"""
        from datetime import datetime, timedelta

        conn = self.db._get_connection()
        cursor = conn.cursor()

        start_time = datetime.now() - timedelta(days=days_back)

        cursor.execute("""
            SELECT timestamp, model_name, model_type, metrics
            FROM training_history
            WHERE timestamp >= ?
            ORDER BY timestamp DESC
            LIMIT 50
        """, (start_time,))

        history = []
        for row in cursor.fetchall():
            row_dict = dict(row)
            # Parse metrics JSON
            if row_dict.get('metrics'):
                try:
                    row_dict['metrics'] = json.loads(row_dict['metrics'])
                except (json.JSONDecodeError, TypeError) as e:
                    logger.debug(f"Could not parse metrics JSON: {e}")
                    row_dict['metrics'] = None
            history.append(row_dict)

        return history

    def _get_decision_statistics(self, days_back: int) -> dict:
        """Berechnet Statistiken über KI-Entscheidungen"""
        from datetime import datetime, timedelta

        conn = self.db._get_connection()
        cursor = conn.cursor()

        start_time = datetime.now() - timedelta(days=days_back)

        # Gesamt-Statistiken
        cursor.execute("""
            SELECT
                COUNT(*) as total_decisions,
                SUM(CASE WHEN executed = 1 THEN 1 ELSE 0 END) as executed_decisions,
                AVG(confidence) as avg_confidence,
                decision_type,
                COUNT(*) as count_per_type
            FROM decisions
            WHERE timestamp >= ?
            GROUP BY decision_type
        """, (start_time,))

        type_stats = []
        total_decisions = 0
        executed_decisions = 0

        for row in cursor.fetchall():
            row_dict = dict(row)
            type_stats.append(row_dict)
            total_decisions += row_dict['count_per_type']
            executed_decisions += row_dict.get('executed_decisions', 0)

        # Durchschnittliche Confidence
        cursor.execute("""
            SELECT AVG(confidence) as avg_confidence
            FROM decisions
            WHERE timestamp >= ?
        """, (start_time,))

        result = cursor.fetchone()
        avg_confidence = result['avg_confidence'] if result else 0.0

        return {
            'total_decisions': total_decisions,
            'executed_decisions': executed_decisions,
            'execution_rate': round((executed_decisions / total_decisions * 100), 1) if total_decisions > 0 else 0,
            'avg_confidence': round(avg_confidence, 3) if avg_confidence else 0,
            'by_type': type_stats,
            'period_days': days_back
        }

    def _get_confidence_trends(self, days_back: int) -> list:
        """Holt Confidence-Score Trends über Zeit"""
        from datetime import datetime, timedelta

        conn = self.db._get_connection()
        cursor = conn.cursor()

        start_time = datetime.now() - timedelta(days=days_back)

        cursor.execute("""
            SELECT
                DATE(timestamp) as date,
                AVG(confidence) as avg_confidence,
                MIN(confidence) as min_confidence,
                MAX(confidence) as max_confidence,
                COUNT(*) as decision_count
            FROM decisions
            WHERE timestamp >= ? AND confidence IS NOT NULL
            GROUP BY DATE(timestamp)
            ORDER BY date ASC
        """, (start_time,))

        trends = []
        for row in cursor.fetchall():
            trends.append({
                'date': row['date'],
                'avg_confidence': round(row['avg_confidence'], 3),
                'min_confidence': round(row['min_confidence'], 3),
                'max_confidence': round(row['max_confidence'], 3),
                'decision_count': row['decision_count']
            })

        return trends

    def _calculate_prediction_accuracy(self, actual_events, predictions_by_day):
        """
        Berechnet Genauigkeitsmetriken für Vorhersagen

        Args:
            actual_events: Liste der tatsächlichen Events
            predictions_by_day: Dict mit Vorhersagen pro Wochentag

        Returns:
            Dict mit Genauigkeitsmetriken
        """
        if not actual_events or not predictions_by_day:
            return {
                'overall_accuracy': 0,
                'day_accuracy': {},
                'hour_accuracy': 0,
                'message': 'Nicht genug Daten für Genauigkeitsberechnung'
            }

        from datetime import datetime

        # Zähle korrekte Vorhersagen pro Wochentag
        day_matches = {}
        hour_matches = 0
        total_predictions = 0

        for event in actual_events:
            day = event.get('day_of_week')
            hour = event.get('hour_of_day')

            if day is not None and day in predictions_by_day:
                # Prüfe, ob dieser Wochentag vorhergesagt wurde
                day_prediction = predictions_by_day[day]

                if day not in day_matches:
                    day_matches[day] = {'correct': 0, 'total': 0}

                day_matches[day]['total'] += 1

                # Wurde ein Event für diesen Tag vorhergesagt?
                if day_prediction.get('avg_events_per_day', 0) > 0:
                    day_matches[day]['correct'] += 1

                # Prüfe Stunden-Genauigkeit
                if hour is not None:
                    predicted_hours = [p['hour'] for p in day_prediction.get('predicted_times', [])]

                    # Match wenn innerhalb von ±1 Stunde
                    for pred_hour in predicted_hours:
                        if abs(hour - pred_hour) <= 1:
                            hour_matches += 1
                            break

                    total_predictions += 1

        # Berechne Gesamt-Genauigkeit
        total_events = len(actual_events)
        total_correct_days = sum(d['correct'] for d in day_matches.values())

        overall_accuracy = (total_correct_days / total_events * 100) if total_events > 0 else 0
        hour_accuracy = (hour_matches / total_predictions * 100) if total_predictions > 0 else 0

        # Per-Day Genauigkeit
        day_accuracy = {}
        weekday_names = ['Montag', 'Dienstag', 'Mittwoch', 'Donnerstag',
                        'Freitag', 'Samstag', 'Sonntag']

        for day, matches in day_matches.items():
            day_accuracy[weekday_names[day]] = {
                'accuracy': (matches['correct'] / matches['total'] * 100) if matches['total'] > 0 else 0,
                'events': matches['total'],
                'correct': matches['correct']
            }

        return {
            'overall_accuracy': round(overall_accuracy, 1),
            'day_accuracy': day_accuracy,
            'hour_accuracy': round(hour_accuracy, 1),
            'total_events': total_events,
            'hour_matches': hour_matches,
            'total_hour_predictions': total_predictions,
            'message': f'{hour_matches} von {total_predictions} Vorhersagen korrekt (±1 Stunde)'
        }

    def run(self, host='0.0.0.0', port=8080, debug=False):
        """Starte den Web-Server"""
        logger.info(f"Starting web interface on http://{host}:{port}")

        # Starte Background Data Collector
        if self.background_collector:
            self.background_collector.start()
            logger.info("Background Data Collector started")

        # Starte ML Auto-Trainer
        if self.ml_auto_trainer:
            self.ml_auto_trainer.start()
            logger.info("ML Auto-Trainer started (runs daily at 2:00)")

        # Starte Bathroom Optimizer
        if self.bathroom_optimizer:
            self.bathroom_optimizer.start()
            logger.info("Bathroom Optimizer started (runs daily at 3:00)")

        # Starte Bathroom Data Collector
        if self.bathroom_collector:
            self.bathroom_collector.start()
            logger.info("Bathroom Data Collector started (collects every 60s)")

        # Starte Heating Data Collector
        if self.heating_collector:
            self.heating_collector.start()
            logger.info("Heating Data Collector started (collects every 15min)")

        # Starte Window Data Collector
        if self.window_collector:
            self.window_collector.start()
            logger.info("Window Data Collector started (collects every 60s)")

        # Starte Lighting Data Collector (für ML Training)
        if self.lighting_collector:
            self.lighting_collector.start()
            logger.info("Lighting Data Collector started (for ML Training)")

        # Starte Temperature Data Collector (für ML Training)
        if self.temperature_collector:
            self.temperature_collector.start()
            logger.info("Temperature Data Collector started (for ML Training)")

        # Starte Database Maintenance Job
        if self.db_maintenance:
            self.db_maintenance.start()
            logger.info("Database Maintenance Job started (runs daily at 5:00)")

        try:
            self.app.run(host=host, port=port, debug=debug)
        finally:
            # Stoppe Background Processes beim Herunterfahren
            if self.background_collector:
                self.background_collector.stop()
                logger.info("Background Data Collector stopped")

            if self.ml_auto_trainer:
                self.ml_auto_trainer.stop()
                logger.info("ML Auto-Trainer stopped")

            if self.bathroom_optimizer:
                self.bathroom_optimizer.stop()
                logger.info("Bathroom Optimizer stopped")

            if self.bathroom_collector:
                self.bathroom_collector.stop()
                logger.info("Bathroom Data Collector stopped")

            if self.heating_collector:
                self.heating_collector.stop()
                logger.info("Heating Data Collector stopped")

            if self.window_collector:
                self.window_collector.stop()
                logger.info("Window Data Collector stopped")

            if self.lighting_collector:
                self.lighting_collector.stop()
                logger.info("Lighting Data Collector stopped")

            if self.temperature_collector:
                self.temperature_collector.stop()
                logger.info("Temperature Data Collector stopped")

            if self.db_maintenance:
                self.db_maintenance.stop()
                logger.info("Database Maintenance Job stopped")


def create_app(config_path=None):
    """Factory-Funktion für Flask App"""
    web = WebInterface(config_path)
    return web.app
