"""Konfiguration laden und verwalten"""

import yaml
import os
from pathlib import Path
from typing import Dict, Any, Optional
from dotenv import load_dotenv
from loguru import logger

try:
    from pydantic import ValidationError
    from .config_schema import KISystemConfig
    PYDANTIC_AVAILABLE = True
except ImportError:
    PYDANTIC_AVAILABLE = False
    logger.warning("Pydantic not available - config validation disabled. Install with: pip install pydantic")


# Default-Konfigurationen für alle Bereiche
# Diese werden mit der User-Config gemerged
DEFAULT_CONFIG = {
    'ventilation_notifications': {
        'enabled': True,
        'co2_high_alert': True,
        'co2_threshold': 1000,
        'humidity_high_alert': True,
        'humidity_threshold': 70,
        'ventilation_complete': False,
        'frost_warning': True,
        'frost_threshold': 2,
        'mold_warning': True,
        'window_opened_alert': True,
        'window_away_alert': True
    },
    'forgotten_light': {
        'enabled': True,
        'notifications_enabled': True,
        'no_motion_threshold': 30,
        'sleep_hour_start': 23,
        'sleep_hour_end': 6,
        'daylight_lux_threshold': 200,
        'min_on_duration': 15,
        'check_interval': 60,
        'use_ml': True,
        'turn_off_when_away': True,
        'away_min_duration': 5,
        'test_mode': True
    },
    'bathroom_automation': {
        'enabled': False,
        'humidity_threshold_high': 70,
        'humidity_threshold_low': 55,  # Bei 55% wird ausgeschaltet (nicht 60%)
        'target_temperature': 22,
        'heating_boost_enabled': False,
        'heating_boost_delta': 1.0,
        'frost_protection_temperature': 12,
        'dehumidifier_delay': 3  # Nur 3 Min. Verzögerung statt 5
    },
    'heating': {
        'enabled': True,
        'eco_temperature': 18,
        'comfort_temperature': 21,
        'night_temperature': 17,
        'away_temperature': 16,
        'frost_protection_temp': 7,
        'window_open_reduction': 5,
        'presence_boost': True,
        'weather_adjustment': True,
        'schedule_enabled': True
    },
    'ml_auto_trainer': {
        'enabled': True,
        'run_hour': 2,
        'min_samples_heating': 200,
        'min_samples_lighting': 100
    },
    'collectors': {
        'heating': {'enabled': True, 'interval': 60},
        'lighting': {'enabled': True, 'interval': 60},
        'windows': {'enabled': True, 'interval': 60},
        'temperature': {'enabled': True, 'interval': 60},
        'bathroom': {'enabled': False, 'interval': 60}
    },
    'database_maintenance': {
        'enabled': True,
        'cleanup_time': '04:00',
        'retention_days': 90
    },
    'notifications': {
        'pushover': {
            'api_token': '',
            'user_key': ''
        }
    },
    'decision_engine': {
        'mode': 'auto',
        'confidence_threshold': 0.7,
        'safety_checks': True
    },
    'logging': {
        'level': 'INFO',
        'path': 'logs/ki_system.log',
        'max_size_mb': 100
    }
}


def deep_merge(base: dict, override: dict) -> dict:
    """Tiefes Mergen von zwei Dictionaries"""
    from copy import deepcopy
    result = deepcopy(base)
    
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = deepcopy(value) if isinstance(value, dict) else value
    
    return result


class ConfigValidationError(Exception):
    """Custom exception for configuration validation errors"""
    pass


class ConfigLoader:
    """Lädt und verwaltet Konfiguration aus YAML und .env Dateien"""

    def __init__(self, config_path: str = None, validate: bool = True):
        """
        Initialize ConfigLoader

        Args:
            config_path: Path to config.yaml file
            validate: Whether to validate config with Pydantic (default: True)
        """
        # Load environment variables
        load_dotenv()

        # Set config path
        if config_path is None:
            config_path = Path(__file__).parent.parent.parent / "config" / "config.yaml"

        self.config_path = Path(config_path)
        self.example_defaults = self._load_example_defaults()
        self.config = self._load_config()
        self._merge_env_variables()

        # Validate configuration if requested and Pydantic is available
        if validate and PYDANTIC_AVAILABLE:
            self._validate_config()

    def _load_example_defaults(self) -> Dict[str, str]:
        """Lädt Default-Werte aus .env.example"""
        try:
            # config_path is usually .../config/config.yaml
            # .env.example is in root, so ../../.env.example
            example_path = self.config_path.parent.parent / ".env.example"
            defaults = {}
            if example_path.exists():
                with open(example_path, 'r') as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith('#'): continue
                        if '=' in line:
                            key, val = line.split('=', 1)
                            defaults[key.strip()] = val.strip()
            return defaults
        except Exception as e:
            logger.warning(f"Could not load .env.example: {e}")
            return {}

    def _load_config(self) -> Dict[str, Any]:
        """Lädt die YAML-Konfiguration und merged mit Defaults"""
        if not self.config_path.exists():
            logger.warning(f"Config file not found: {self.config_path}, using defaults")
            return DEFAULT_CONFIG.copy()

        with open(self.config_path, 'r', encoding='utf-8') as f:
            user_config = yaml.safe_load(f) or {}
        
        # Merge: User-Config überschreibt Defaults
        merged = deep_merge(DEFAULT_CONFIG, user_config)
        logger.debug("Config loaded and merged with defaults")
        return merged

    def _get_valid_env(self, key: str, current_value: Any = None) -> Optional[str]:
        """
        Holt Umgebungsvariable, ignoriert aber Placeholder-Werte und Defaults,
        wenn bereits eine Konfiguration existiert.
        """
        val = os.getenv(key)
        if not val:
            return None
            
        # Check for placeholders
        val_lower = val.lower()
        if 'your_' in val_lower or 'example' in val_lower or 'placeholder' in val_lower:
            return None
            
        # Check against .env.example defaults
        default_val = self.example_defaults.get(key)
        if default_val and val == default_val:
            # It matches the example default.
            # If we have a current value from config (and it's not empty/None), prefer that!
            if current_value:
                return None
            
        return val

    def _merge_env_variables(self):
        """Überschreibt Config-Werte mit Umgebungsvariablen"""
        # Platform Type
        current_type = self.config.get('platform', {}).get('type')
        platform_type = self._get_valid_env('PLATFORM_TYPE', current_type)
        if platform_type:
            if 'platform' not in self.config:
                self.config['platform'] = {}
            self.config['platform']['type'] = platform_type

        # Home Assistant
        current_ha_url = self.config.get('home_assistant', {}).get('url')
        ha_url = self._get_valid_env('HA_URL', current_ha_url)
        if ha_url:
            if 'home_assistant' not in self.config:
                self.config['home_assistant'] = {}
            self.config['home_assistant']['url'] = ha_url
            
        current_ha_token = self.config.get('home_assistant', {}).get('token')
        ha_token = self._get_valid_env('HA_TOKEN', current_ha_token)
        if ha_token:
            if 'home_assistant' not in self.config:
                self.config['home_assistant'] = {}
            self.config['home_assistant']['token'] = ha_token

        # Homey
        current_homey_url = self.config.get('homey', {}).get('url')
        homey_url = self._get_valid_env('HOMEY_URL', current_homey_url)
        if homey_url:
            if 'homey' not in self.config:
                self.config['homey'] = {}
            self.config['homey']['url'] = homey_url
            
        current_homey_token = self.config.get('homey', {}).get('token')
        homey_token = self._get_valid_env('HOMEY_TOKEN', current_homey_token)
        if homey_token:
            if 'homey' not in self.config:
                self.config['homey'] = {}
            self.config['homey']['token'] = homey_token

        # Weather API
        current_weather_key = self.config.get('external_data', {}).get('weather', {}).get('api_key')
        weather_key = self._get_valid_env('WEATHER_API_KEY', current_weather_key)
        if weather_key:
            if 'external_data' not in self.config:
                self.config['external_data'] = {}
            if 'weather' not in self.config['external_data']:
                self.config['external_data']['weather'] = {}
            self.config['external_data']['weather']['api_key'] = weather_key

        # Energy API
        current_energy_key = self.config.get('external_data', {}).get('energy_prices', {}).get('api_key')
        energy_key = self._get_valid_env('ENERGY_API_KEY', current_energy_key)
        if energy_key:
            if 'external_data' not in self.config:
                self.config['external_data'] = {}
            if 'energy_prices' not in self.config['external_data']:
                self.config['external_data']['energy_prices'] = {}
            self.config['external_data']['energy_prices']['api_key'] = energy_key
            
        current_energy_provider = self.config.get('external_data', {}).get('energy_prices', {}).get('provider')
        energy_provider = self._get_valid_env('ENERGY_PROVIDER', current_energy_provider)
        if energy_provider:
            if 'external_data' not in self.config:
                self.config['external_data'] = {}
            if 'energy_prices' not in self.config['external_data']:
                self.config['external_data']['energy_prices'] = {}
            self.config['external_data']['energy_prices']['provider'] = energy_provider

    def _validate_config(self):
        """
        Validates configuration using Pydantic schema

        Raises:
            ConfigValidationError: If configuration is invalid
        """
        try:
            # Validate config against Pydantic schema
            validated_config = KISystemConfig(**self.config)
            logger.info("Configuration validated successfully")

            # Update config with validated data (ensures all defaults are set)
            self.config = validated_config.model_dump(mode='python')

        except ValidationError as e:
            # Format validation errors nicely
            error_messages = []
            for error in e.errors():
                location = " -> ".join(str(loc) for loc in error['loc'])
                message = error['msg']
                error_messages.append(f"  • {location}: {message}")

            error_text = "\n".join([
                "Configuration validation failed:",
                *error_messages,
                "",
                "Please check your config/config.yaml file and .env variables."
            ])

            logger.error(error_text)
            raise ConfigValidationError(error_text) from e

        except Exception as e:
            logger.error(f"Unexpected error during config validation: {e}")
            raise ConfigValidationError(f"Config validation error: {e}") from e

    def get(self, key: str, default: Any = None) -> Any:
        """
        Holt einen Config-Wert mit Dot-Notation
        Beispiel: config.get('home_assistant.url')
        """
        keys = key.split('.')
        value = self.config

        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
                if value is None:
                    return default
            else:
                return default

        return value

    def __getitem__(self, key: str) -> Any:
        """Ermöglicht dict-ähnlichen Zugriff"""
        return self.config[key]

    def get_all(self) -> Dict[str, Any]:
        """Gibt die gesamte Konfiguration zurück"""
        return self.config

    def update(self, key: str, value: Any) -> bool:
        """
        Aktualisiert einen Config-Wert mit Dot-Notation und speichert in YAML
        Beispiel: config.update('decision_engine.mode', 'learning')

        Returns:
            bool: True wenn erfolgreich, False bei Fehler
        """
        keys = key.split('.')
        config_ref = self.config

        # Navigate to parent
        for k in keys[:-1]:
            if k not in config_ref:
                config_ref[k] = {}
            config_ref = config_ref[k]

        # Set value
        config_ref[keys[-1]] = value

        # Save to YAML
        return self._save_config()

    def _save_config(self) -> bool:
        """Speichert die aktuelle Konfiguration in die YAML-Datei"""
        try:
            with open(self.config_path, 'w', encoding='utf-8') as f:
                yaml.dump(self.config, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
            return True
        except Exception as e:
            print(f"Fehler beim Speichern der Config: {e}")
            return False
