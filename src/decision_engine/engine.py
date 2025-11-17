"""Zentrale Entscheidungs-Engine"""

from typing import Dict, List, Optional, Tuple
from datetime import datetime
from loguru import logger
from pathlib import Path

from ..models.lighting_model import LightingModel
from ..models.temperature_model import TemperatureModel
from ..models.energy_optimizer import EnergyOptimizer
from ..data_collector.base_collector import SmartHomeCollector
from ..data_collector.platform_factory import PlatformFactory
from ..data_collector.weather_collector import WeatherCollector
from ..data_collector.energy_price_collector import EnergyPriceCollector
from ..utils.database import Database
from ..utils.config_loader import ConfigLoader

# Spezialisierte Optimierungs- und Automationssysteme
from ..decision_engine.heating_optimizer import HeatingOptimizer
from ..decision_engine.mold_prevention import MoldPreventionSystem
from ..decision_engine.ventilation_optimizer import VentilationOptimizer
from ..decision_engine.room_learning import RoomLearningSystem
from ..decision_engine.bathroom_automation import BathroomAutomation


class DecisionEngine:
    """
    Zentrale Engine für alle automatisierten Entscheidungen
    Koordiniert ML-Modelle, Datensammler und Smart Home Platform (Home Assistant oder Homey Pro)
    """

    def __init__(self, config_path: str = None):
        # Lade Konfiguration
        self.config = ConfigLoader(config_path)

        # Initialisiere Datenbank
        db_path = self.config.get('database.path', 'data/ki_system.db')
        self.db = Database(db_path)

        # Initialisiere Smart Home Collector (Home Assistant und/oder Homey)
        # Multi-Platform Support: Kann beide gleichzeitig nutzen
        self.multi_platform_enabled = self.config.get('platforms.enable_multi_platform', False)
        
        if self.multi_platform_enabled:
            # Beide Plattformen initialisieren
            self.platforms = {}
            
            # Homey initialisieren
            homey_url = self.config.get('homey.url')
            homey_token = self.config.get('homey.token')
            if homey_url and homey_token:
                homey_collector = PlatformFactory.create_collector('homey', homey_url, homey_token)
                if homey_collector:
                    self.platforms['homey'] = homey_collector
                    logger.info("Homey platform initialized")
            
            # Home Assistant initialisieren
            ha_url = self.config.get('homeassistant.url')
            ha_token = self.config.get('homeassistant.token')
            if ha_url and ha_token:
                ha_collector = PlatformFactory.create_collector('homeassistant', ha_url, ha_token)
                if ha_collector:
                    self.platforms['homeassistant'] = ha_collector
                    logger.info("Home Assistant platform initialized")
            
            # Primary Platform für Legacy-Kompatibilität
            primary = self.config.get('platforms.primary', 'homey')
            self.platform = self.platforms.get(primary)
            
            if not self.platforms:
                logger.warning("No platforms configured in multi-platform mode - engine will run without smart home access")
                self.platform = None
            else:
                logger.info(f"Multi-Platform mode: {len(self.platforms)} platforms active (primary: {primary})")
        else:
            # Single Platform Mode (bisheriges Verhalten)
            platform_type = self.config.get('platform.type', 'homeassistant')

            if platform_type.lower() in ['homey', 'homey_pro']:
                platform_url = self.config.get('homey.url')
                platform_token = self.config.get('homey.token')
            else:
                platform_url = self.config.get('homeassistant.url')
                platform_token = self.config.get('homeassistant.token')

            self.platform = PlatformFactory.create_collector(
                platform_type,
                platform_url,
                platform_token
            )

            if not self.platform:
                raise ValueError(f"Failed to initialize platform: {platform_type}")

            self.platforms = {platform_type: self.platform}
            logger.info(f"Using platform: {self.platform.get_platform_name()}")

        # Alias für Backwards-Kompatibilität
        self.ha = self.platform

        # Initialisiere externe Datensammler
        # Versuche zuerst platforms.weather, dann external_data.weather (backwards compat)
        weather_key = self.config.get('platforms.weather.api_key') or self.config.get('external_data.weather.api_key')
        weather_location = self.config.get('platforms.weather.location') or self.config.get('external_data.weather.location', 'Berlin, DE')
        weather_enabled = self.config.get('platforms.weather.enabled', True)
        
        if weather_enabled and weather_key:
            self.weather = WeatherCollector(weather_key, weather_location)
            logger.info(f"Weather collector initialized: {weather_location}")
        else:
            self.weather = None
            logger.info("Weather API integration disabled")

        # Energy Prices (optional)
        self.energy_prices_enabled = self.config.get('external_data.energy_prices.enabled', False)
        if self.energy_prices_enabled:
            energy_provider = self.config.get('external_data.energy_prices.provider', 'awattar')
            energy_key = self.config.get('external_data.energy_prices.api_key')
            self.energy_prices = EnergyPriceCollector(energy_provider, energy_key)
            logger.info(f"Energy price integration enabled: {energy_provider}")
        else:
            self.energy_prices = None
            logger.info("Energy price integration disabled")

        # Initialisiere ML-Modelle
        self.lighting_model = LightingModel(
            self.config.get('models.lighting.type', 'random_forest')
        )
        self.temperature_model = TemperatureModel(
            self.config.get('models.heating.type', 'gradient_boosting')
        )

        # Initialisiere Energy Optimizer
        optimizer_config = self.config.get('models.energy_optimizer', {})
        self.energy_optimizer = EnergyOptimizer(optimizer_config)

        # Engine Status
        self.mode = self.config.get('decision_engine.mode', 'auto')
        self.confidence_threshold = self.config.get('decision_engine.confidence_threshold', 0.7)
        self.safety_checks_enabled = self.config.get('decision_engine.safety_checks', True)

        # Lade existierende Modelle
        self._load_models()

        # === SPEZIALISIERTE SYSTEME ===
        # Diese werden optional aktiviert basierend auf Konfiguration

        # Heizungsoptimierung (Insights & Analytics)
        self.heating_optimizer_enabled = self.config.get('heating_optimizer.enabled', True)
        if self.heating_optimizer_enabled:
            self.heating_optimizer = HeatingOptimizer(db=self.db)
            logger.info("Heating Optimizer enabled")
        else:
            self.heating_optimizer = None

        # Schimmelprävention
        self.mold_prevention_enabled = self.config.get('mold_prevention.enabled', True)
        if self.mold_prevention_enabled:
            self.mold_prevention = MoldPreventionSystem(db=self.db)
            logger.info("Mold Prevention System enabled")
        else:
            self.mold_prevention = None

        # Lüftungsoptimierung
        self.ventilation_optimizer_enabled = self.config.get('ventilation_optimizer.enabled', True)
        if self.ventilation_optimizer_enabled:
            self.ventilation_optimizer = VentilationOptimizer(db=self.db)
            logger.info("Ventilation Optimizer enabled")
        else:
            self.ventilation_optimizer = None

        # Raumspezifisches Lernen
        self.room_learning_enabled = self.config.get('room_learning.enabled', True)
        if self.room_learning_enabled:
            self.room_learning = RoomLearningSystem(db=self.db)
            logger.info("Room Learning System enabled")
        else:
            self.room_learning = None

        # Badezimmer-Automation
        self.bathroom_automation_enabled = self.config.get('bathroom_automation.enabled', False)
        if self.bathroom_automation_enabled:
            # Lade Badezimmer-Konfiguration
            bathroom_config = self._load_bathroom_config()
            if bathroom_config:
                self.bathroom_automation = BathroomAutomation(
                    config=bathroom_config,
                    enable_learning=True
                )
                logger.info("Bathroom Automation enabled")
            else:
                self.bathroom_automation = None
                logger.warning("Bathroom Automation disabled: No config found")
        else:
            self.bathroom_automation = None

        logger.info("Decision Engine initialized with specialized systems")

    def _load_sensor_config(self) -> Dict:
        """Lädt die Sensor-Konfiguration aus data/sensor_config.json"""
        try:
            from pathlib import Path
            import json
            config_file = Path('data/sensor_config.json')
            if config_file.exists():
                with open(config_file, 'r') as f:
                    return json.load(f)
        except Exception as e:
            logger.debug(f"Could not load sensor config: {e}")
        return {}

    def _load_bathroom_config(self) -> Optional[Dict]:
        """Lädt die Badezimmer-Konfiguration aus data/bathroom_config.json"""
        try:
            import json
            config_file = Path('data/bathroom_config.json')
            if config_file.exists():
                with open(config_file, 'r') as f:
                    return json.load(f)
            else:
                logger.debug("Bathroom config file not found")
                return None
        except Exception as e:
            logger.error(f"Could not load bathroom config: {e}")
            return None

    def _get_indoor_temperature(self, sensor_config: Dict) -> Optional[float]:
        """
        Holt Indoor-Temperatur als Durchschnitt ausgewählter Sensoren
        Falls keine Sensoren konfiguriert: Nutze automatisch ALLE Temperatur-Sensoren
        """
        selected_sensors = sensor_config.get('temperature_sensors', [])

        # Hole alle verfügbaren Temperatur-Sensoren von der Platform
        all_temp_sensors = self._get_all_temperature_sensors()

        # Falls keine Sensoren ausgewählt: Nutze alle
        if not selected_sensors:
            selected_sensors = all_temp_sensors

        # Sammle Temperaturen
        temps = []
        for sensor_id in selected_sensors:
            sensor_state = self.platform.get_state(sensor_id)
            if sensor_state:
                # Extrahiere Temperatur aus verschiedenen Formaten
                temp = self._extract_temperature_value(sensor_state)
                if temp and -20 <= temp <= 40:  # Realistische Indoor-Werte
                    temps.append(temp)

        if temps:
            avg_temp = sum(temps) / len(temps)
            logger.debug(f"Indoor temperature: {avg_temp:.1f}°C (from {len(temps)} sensors)")
            return round(avg_temp, 1)

        return None

    def _get_indoor_humidity(self, sensor_config: Dict) -> Optional[float]:
        """Holt Indoor-Luftfeuchtigkeit als Durchschnitt"""
        selected_sensors = sensor_config.get('humidity_sensors', [])

        # Hole alle verfügbaren Humidity-Sensoren
        all_humidity_sensors = self._get_all_humidity_sensors()

        if not selected_sensors:
            selected_sensors = all_humidity_sensors

        humidities = []
        for sensor_id in selected_sensors:
            sensor_state = self.platform.get_state(sensor_id)
            if sensor_state:
                humidity = self._extract_humidity_value(sensor_state)
                if humidity and 0 <= humidity <= 100:
                    humidities.append(humidity)

        if humidities:
            return round(sum(humidities) / len(humidities), 0)

        return None

    def _get_all_temperature_sensors(self) -> List[str]:
        """Findet alle Temperatur-Sensoren der Platform"""
        sensors = []
        try:
            # Hole alle Devices
            self.platform._refresh_device_cache()
            devices = self.platform._device_cache

            if isinstance(devices, dict):
                devices = list(devices.values())

            # Nur diese Device-Classes erlauben (Whitelist)
            allowed_classes = ['sensor', 'thermostat', 'heater']

            for device in devices:
                capabilities = device.get('capabilitiesObj', {})
                device_class = device.get('class', '').lower()

                # Prüfe auf Temperatur-Capability
                if 'measure_temperature' in capabilities:
                    # Nur erlaubte Device-Classes (echte Sensoren und Thermostate)
                    if device_class in allowed_classes:
                        device_id = device.get('id')
                        if device_id:
                            sensors.append(device_id)

        except Exception as e:
            logger.debug(f"Error getting temperature sensors: {e}")

        return sensors

    def _get_all_humidity_sensors(self) -> List[str]:
        """Findet alle Luftfeuchtigkeit-Sensoren"""
        sensors = []
        try:
            self.platform._refresh_device_cache()
            devices = self.platform._device_cache

            if isinstance(devices, dict):
                devices = list(devices.values())

            # Nur diese Device-Classes erlauben (Whitelist)
            allowed_classes = ['sensor', 'thermostat', 'heater']

            for device in devices:
                capabilities = device.get('capabilitiesObj', {})
                device_class = device.get('class', '').lower()

                if 'measure_humidity' in capabilities:
                    # Nur erlaubte Device-Classes (echte Sensoren)
                    if device_class in allowed_classes:
                        device_id = device.get('id')
                        if device_id:
                            sensors.append(device_id)

        except Exception as e:
            logger.debug(f"Error getting humidity sensors: {e}")

        return sensors

    def _extract_temperature_value(self, sensor_state: Dict) -> Optional[float]:
        """Extrahiert Temperatur-Wert aus Sensor-State"""
        try:
            # Homey Format
            capabilities = sensor_state.get('attributes', {}).get('capabilities', {})
            if 'measure_temperature' in capabilities:
                value = capabilities['measure_temperature'].get('value')
                if value is not None:
                    return float(value)

            # Home Assistant Format
            state_value = sensor_state.get('state')
            if state_value and state_value not in ['unknown', 'unavailable']:
                return float(state_value)

        except (ValueError, TypeError):
            pass

        return None

    def _extract_humidity_value(self, sensor_state: Dict) -> Optional[float]:
        """Extrahiert Luftfeuchtigkeit-Wert aus Sensor-State"""
        try:
            capabilities = sensor_state.get('attributes', {}).get('capabilities', {})
            if 'measure_humidity' in capabilities:
                value = capabilities['measure_humidity'].get('value')
                if value is not None:
                    return float(value)

            state_value = sensor_state.get('state')
            if state_value and state_value not in ['unknown', 'unavailable']:
                return float(state_value)

        except (ValueError, TypeError):
            pass

        return None

    def _load_models(self):
        """Lädt trainierte Modelle falls vorhanden"""
        try:
            self.lighting_model.load()
            logger.info("Lighting model loaded")
        except FileNotFoundError:
            logger.warning("No trained lighting model found")

        try:
            self.temperature_model.load()
            logger.info("Temperature model loaded")
        except FileNotFoundError:
            logger.warning("No trained temperature model found")

    def collect_current_state(self) -> Dict:
        """
        Sammelt aktuellen Zustand von allen Sensoren und externen Quellen
        """
        state = {
            'timestamp': datetime.now().isoformat()
        }

        # Lade Sensor-Konfiguration (falls vorhanden)
        sensor_config = self._load_sensor_config()

        # Temperatur-Sensoren sammeln
        state['current_temperature'] = self._get_indoor_temperature(sensor_config)
        state['humidity'] = self._get_indoor_humidity(sensor_config)

        # Bewegungssensoren (optional - kann später konfiguriert werden)
        state['motion_detected'] = 0

        # Externe Daten (Wetter von Homey-Sensoren oder OpenWeatherMap)
        if self.weather:
            weather = self.weather.get_weather_data(self.platform)
            if weather:
                # WICHTIG: Nur outdoor_temperature setzen, nicht current_temperature überschreiben!
                state['outdoor_temperature'] = weather.get('temperature')

                # Nur Humidity überschreiben wenn nicht schon von Indoor-Sensoren gesetzt
                if 'humidity' not in state:
                    state['humidity'] = weather.get('humidity')

                state['weather_condition'] = weather.get('weather_condition', 'clear')
                state['weather_description'] = weather.get('weather_description', '')
                state['feels_like'] = weather.get('feels_like')
                state['wind_speed'] = weather.get('wind_speed')
                state['pressure'] = weather.get('pressure')
                state['clouds'] = weather.get('clouds')

                # Speichere in DB
                self.db.insert_external_data('weather', weather)
        else:
            logger.debug("Weather collector not initialized - skipping external weather data")

        # Energiepreise (optional)
        if self.energy_prices_enabled and self.energy_prices:
            prices = self.energy_prices.get_prices()
            if prices:
                state['energy_price'] = prices.get('current_price')
                state['energy_price_level'] = self.energy_optimizer.calculate_energy_price_level(
                    prices.get('current_price', 0),
                    prices.get('hourly_prices', [])
                )

                # Speichere in DB
                self.db.insert_external_data('energy_prices', prices)
        else:
            # Default-Werte wenn Energiepreise deaktiviert
            state['energy_price_level'] = 2  # Mittel

        # Anwesenheit (falls vorhanden)
        # Nutze Homey's User-Presence wenn verfügbar
        if hasattr(self.platform, 'get_presence_status'):
            try:
                presence_data = self.platform.get_presence_status()
                state['presence_home'] = 1 if presence_data.get('anyone_home', False) else 0
                state['users_home'] = presence_data.get('users_home', 0)
                logger.debug(f"Presence from Homey: {state['presence_home']} ({state.get('users_home', 0)} users)")
            except Exception as e:
                logger.debug(f"Could not get presence from platform: {e}")
                state['presence_home'] = 1  # Default: anwesend
        else:
            # Fallback: Default oder Motion-Sensoren
            state['presence_home'] = 1  # Default

        return state

    def decide_lighting(self, room: str = None) -> List[Dict]:
        """
        Entscheidet über Beleuchtung für einen oder alle Räume

        Returns:
            Liste von Aktionen [{device_id, action, confidence, executed}]
        """
        actions = []

        # Sammle aktuellen Zustand
        state = self.collect_current_state()

        # Hole alle Licht-Entities
        light_entities = self.ha.get_all_entities(domain='light')

        if room:
            # Filtere für spezifischen Raum
            light_entities = [e for e in light_entities if room.lower() in e.lower()]

        for entity_id in light_entities:
            try:
                # Hole aktuellen Zustand
                current_state = self.ha.get_state(entity_id)
                if not current_state:
                    continue

                is_on = current_state['state'] == 'on'

                # ML-Vorhersage
                prediction, confidence = self.lighting_model.predict(state)

                should_be_on = prediction == 1

                # Entscheidung nur wenn Confidence hoch genug
                if confidence < self.confidence_threshold:
                    logger.debug(f"Confidence too low for {entity_id}: {confidence:.2f}")
                    continue

                # Aktion nur wenn Zustand ändern sollte
                if should_be_on != is_on:
                    action = {
                        'device_id': entity_id,
                        'device_type': 'light',
                        'action': 'turn_on' if should_be_on else 'turn_off',
                        'confidence': confidence,
                        'reasoning': f"ML prediction with {confidence:.1%} confidence",
                        'executed': False
                    }

                    # Führe Aktion aus wenn im Auto-Modus
                    if self.mode == 'auto':
                        success = self._execute_action(action)
                        action['executed'] = success

                    actions.append(action)

                    # Speichere Entscheidung in DB
                    self.db.insert_decision(
                        entity_id,
                        'lighting',
                        action['action'],
                        confidence,
                        self.lighting_model.model_version
                    )

            except Exception as e:
                logger.error(f"Error deciding for {entity_id}: {e}")

        return actions

    def decide_heating(self, room: str = None) -> List[Dict]:
        """
        Entscheidet über Heizung/Temperatur für einen oder alle Räume

        Returns:
            Liste von Aktionen
        """
        actions = []

        # Sammle aktuellen Zustand
        state = self.collect_current_state()

        # Hole alle Climate-Entities (Thermostate)
        climate_entities = self.ha.get_all_entities(domain='climate')

        if room:
            climate_entities = [e for e in climate_entities if room.lower() in e.lower()]

        # Energiepreis-Level für Optimierung
        energy_level = state.get('energy_price_level', 2)

        for entity_id in climate_entities:
            try:
                current_state = self.ha.get_state(entity_id)
                if not current_state:
                    continue

                current_temp = current_state['attributes'].get('current_temperature')
                current_target = current_state['attributes'].get('temperature')

                # ML-Vorhersage mit Energieoptimierung
                predicted_temp, metadata = self.temperature_model.predict_with_energy_optimization(
                    state,
                    energy_level
                )

                # Runde auf 0.5°C
                predicted_temp = round(predicted_temp * 2) / 2

                # Aktion nur wenn signifikante Änderung (>= 0.5°C)
                if abs(predicted_temp - current_target) >= 0.5:
                    action = {
                        'device_id': entity_id,
                        'device_type': 'climate',
                        'action': 'set_temperature',
                        'temperature': predicted_temp,
                        'current_temperature': current_temp,
                        'old_target': current_target,
                        'reasoning': metadata,
                        'executed': False
                    }

                    # Safety Check
                    if self.safety_checks_enabled:
                        if not self._safety_check_temperature(predicted_temp, state):
                            logger.warning(f"Safety check failed for {entity_id}")
                            continue

                    # Führe Aktion aus
                    if self.mode == 'auto':
                        success = self._execute_action(action)
                        action['executed'] = success

                    actions.append(action)

                    # Speichere in DB
                    self.db.insert_decision(
                        entity_id,
                        'heating',
                        f"set_temperature:{predicted_temp}",
                        0.8,  # Confidence für Regression schwieriger zu bestimmen
                        self.temperature_model.model_version
                    )

            except Exception as e:
                logger.error(f"Error deciding heating for {entity_id}: {e}")

        return actions

    def _execute_action(self, action: Dict) -> bool:
        """Führt eine Aktion aus"""
        try:
            device_id = action['device_id']
            action_type = action['action']

            if action_type == 'turn_on':
                success = self.ha.turn_on(device_id)
            elif action_type == 'turn_off':
                success = self.ha.turn_off(device_id)
            elif action_type == 'set_temperature':
                success = self.ha.set_temperature(device_id, action['temperature'])
            else:
                logger.error(f"Unknown action type: {action_type}")
                return False

            if success:
                logger.info(f"Executed: {action_type} on {device_id}")

            return success

        except Exception as e:
            logger.error(f"Error executing action: {e}")
            return False

    def _safety_check_temperature(self, temperature: float, state: Dict) -> bool:
        """
        Sicherheits-Check für Temperatur-Entscheidungen
        """
        # Check 1: Temperatur in sicheren Grenzen
        if temperature < 16.0 or temperature > 25.0:
            logger.warning(f"Temperature {temperature}°C outside safe range")
            return False

        # Check 2: Nicht zu stark von aktueller Temperatur abweichen
        current_temp = state.get('current_temperature', 20.0)
        if abs(temperature - current_temp) > 5.0:
            logger.warning(f"Temperature change too extreme: {temperature}°C vs {current_temp}°C")
            return False

        # Check 3: Bei Abwesenheit nicht über 20°C heizen
        if state.get('presence_home', 1) == 0 and temperature > 20.0:
            logger.warning("High temperature when nobody home")
            return False

        return True

    def run_cycle(self):
        """
        Führt einen vollständigen Entscheidungs-Zyklus aus
        - Sammelt Daten
        - Trifft Entscheidungen
        - Führt Aktionen aus
        - Nutzt spezialisierte Optimierungssysteme
        """
        logger.info("=== Starting decision cycle ===")

        try:
            # Sammle aktuellen Zustand
            state = self.collect_current_state()
            logger.info(f"Current state collected: {len(state)} parameters")

            # Basis-Entscheidungen treffen (Lighting & Heating)
            lighting_actions = self.decide_lighting()
            heating_actions = self.decide_heating()

            # === SPEZIALISIERTE SYSTEME AUSFÜHREN ===

            # 1. Heizungsoptimierung - Sammle Daten und generiere Insights
            if self.heating_optimizer_enabled and self.heating_optimizer:
                try:
                    outdoor_temp = state.get('outdoor_temperature')
                    self.heating_optimizer.collect_current_state(
                        platform=self.platform,
                        outdoor_temp=outdoor_temp
                    )
                    logger.debug("Heating data collected for optimization")
                except Exception as e:
                    logger.error(f"Error in heating optimizer: {e}")

            # 2. Schimmelprävention - Prüfe kritische Räume
            mold_alerts = []
            if self.mold_prevention_enabled and self.mold_prevention:
                try:
                    # Hier könnten wir alle Räume mit hoher Luftfeuchtigkeit prüfen
                    # Für jetzt: nur wenn Luftfeuchtigkeit im State verfügbar
                    if state.get('humidity') and state.get('current_temperature'):
                        room_name = "Hauptraum"  # TODO: Raum-spezifisch machen
                        analysis = self.mold_prevention.analyze_room_humidity(
                            room_name=room_name,
                            temperature=state['current_temperature'],
                            humidity=state['humidity'],
                            outdoor_temp=state.get('outdoor_temperature')
                        )
                        if analysis.get('alert_required'):
                            mold_alerts.append(analysis)
                            logger.warning(f"Mold alert for {room_name}: {analysis.get('humidity_status', {}).get('level')}")
                except Exception as e:
                    logger.error(f"Error in mold prevention: {e}")

            # 3. Lüftungsoptimierung - Generiere Empfehlungen
            ventilation_recommendations = []
            if self.ventilation_optimizer_enabled and self.ventilation_optimizer:
                try:
                    if (state.get('humidity') and state.get('current_temperature') and
                        state.get('outdoor_temperature')):
                        # Annahme: outdoor_humidity verfügbar oder aus Wetterdaten
                        outdoor_humidity = state.get('outdoor_humidity', 70.0)

                        recommendation = self.ventilation_optimizer.generate_ventilation_recommendation(
                            room_name="Hauptraum",
                            indoor_temp=state['current_temperature'],
                            indoor_humidity=state['humidity'],
                            outdoor_temp=state['outdoor_temperature'],
                            outdoor_humidity=outdoor_humidity
                        )
                        ventilation_recommendations.append(recommendation)

                        if recommendation['priority'] == 'HOCH':
                            logger.info(f"Ventilation recommendation: {recommendation['action']}")
                except Exception as e:
                    logger.error(f"Error in ventilation optimizer: {e}")

            # 4. Badezimmer-Automation
            bathroom_actions = []
            if self.bathroom_automation_enabled and self.bathroom_automation:
                try:
                    bathroom_actions = self.bathroom_automation.process(
                        platform=self.platform,
                        current_state=state
                    )
                    if bathroom_actions:
                        logger.info(f"Bathroom automation: {len(bathroom_actions)} actions")
                        # Führe Badezimmer-Aktionen aus
                        for action in bathroom_actions:
                            self._execute_action(action)
                except Exception as e:
                    logger.error(f"Error in bathroom automation: {e}")

            # Zusammenfassung
            summary = {
                'timestamp': datetime.now().isoformat(),
                'state': state,
                'lighting_actions': len(lighting_actions),
                'heating_actions': len(heating_actions),
                'bathroom_actions': len(bathroom_actions),
                'mold_alerts': len(mold_alerts),
                'ventilation_recommendations': len(ventilation_recommendations),
                'total_actions': len(lighting_actions) + len(heating_actions) + len(bathroom_actions),
                'specialized_systems': {
                    'heating_optimizer': self.heating_optimizer_enabled,
                    'mold_prevention': self.mold_prevention_enabled,
                    'ventilation_optimizer': self.ventilation_optimizer_enabled,
                    'bathroom_automation': self.bathroom_automation_enabled,
                    'room_learning': self.room_learning_enabled
                }
            }

            logger.info(f"Cycle completed: {summary['total_actions']} actions taken")
            logger.info(f"Specialized systems: Heating={self.heating_optimizer_enabled}, "
                       f"Mold={self.mold_prevention_enabled}, Ventilation={self.ventilation_optimizer_enabled}, "
                       f"Bathroom={self.bathroom_automation_enabled}, RoomLearning={self.room_learning_enabled}")

            return summary

        except Exception as e:
            logger.error(f"Error in decision cycle: {e}")
            return None

    def get_recommendations(self) -> List[str]:
        """Holt intelligente Empfehlungen"""
        state = self.collect_current_state()

        # Hole Forecast für Empfehlungen
        # (Hier vereinfacht, könnte detaillierter sein)
        forecast = []  # TODO: Implementiere Forecast-Sammlung

        recommendations = self.energy_optimizer.get_smart_recommendations(
            state,
            forecast
        )

        return recommendations

    def test_connection(self) -> Dict:
        """Testet alle Verbindungen"""
        results = {
            'smart_home_platform': self.platform.test_connection(),
            'weather_api': self.weather.get_weather_data(self.ha) is not None,
            'database': True  # DB immer verfügbar (SQLite)
        }

        # Energy Prices nur testen wenn aktiviert
        if self.energy_prices_enabled and self.energy_prices:
            results['energy_prices'] = self.energy_prices.get_prices() is not None
        else:
            results['energy_prices'] = 'disabled'

        return results

    def _execute_action(self, action: Dict) -> bool:
        """
        Führt eine generische Aktion aus (z.B. von Bathroom Automation)

        Args:
            action: Dict mit 'device_id', 'action', 'reason', optional 'temperature'

        Returns:
            True wenn erfolgreich
        """
        try:
            device_id = action.get('device_id')
            action_type = action.get('action')
            reason = action.get('reason', 'Automated action')

            if not device_id or not action_type:
                logger.warning(f"Invalid action format: {action}")
                return False

            # Führe Aktion aus basierend auf Typ
            if action_type == 'turn_on':
                success = self.platform.turn_on(device_id)
                logger.info(f"Turned ON {device_id}: {reason}")
            elif action_type == 'turn_off':
                success = self.platform.turn_off(device_id)
                logger.info(f"Turned OFF {device_id}: {reason}")
            elif action_type == 'set_temperature':
                temperature = action.get('temperature')
                if temperature is None:
                    logger.warning(f"Missing temperature for set_temperature action")
                    return False
                success = self.platform.set_temperature(device_id, temperature)
                logger.info(f"Set temperature {device_id} to {temperature}°C: {reason}")
            else:
                logger.warning(f"Unknown action type: {action_type}")
                return False

            return success

        except Exception as e:
            logger.error(f"Error executing action {action}: {e}")
            return False
