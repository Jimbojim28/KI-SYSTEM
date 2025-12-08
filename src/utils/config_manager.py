"""
Config Manager - Zentrales Konfigurations-Management mit Default-Werten

Stellt sicher, dass bei Updates neue Config-Optionen automatisch 
mit sinnvollen Defaults gefüllt werden.
"""

import yaml
from pathlib import Path
from typing import Dict, Any, Optional
from copy import deepcopy
from loguru import logger


# Alle Default-Konfigurationen an einem Ort
DEFAULT_CONFIG = {
    # Ventilation Notifications
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
        'window_closed_alert': True,
        'window_away_alert': True
    },
    
    # Forgotten Light Detection
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
    
    # Heating
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
    
    # ML Auto Trainer
    'ml_auto_trainer': {
        'enabled': True,
        'run_hour': 2,
        'min_samples_heating': 200,
        'min_samples_lighting': 100,
        'training_time': '03:00'
    },
    
    # Data Collection
    'data_collection': {
        'interval_seconds': 300,
        'collect_types': {
            'sensor_data': True,
            'temperature_data': True,
            'window_states': True,
            'lighting_events': True,
            'heating_observations': True,
            'bathroom_data': True,
            'weather_data': True
        }
    },
    
    # Collectors
    'collectors': {
        'heating': {
            'enabled': True,
            'interval': 60
        },
        'lighting': {
            'enabled': True,
            'interval': 60
        },
        'windows': {
            'enabled': True,
            'interval': 60
        },
        'temperature': {
            'enabled': True,
            'interval': 60
        },
        'bathroom': {
            'enabled': False,
            'interval': 60
        }
    },
    
    # Bathroom Optimizer
    'bathroom_optimizer': {
        'enabled': False,
        'optimization_time': '03:30'
    },
    
    # Database Maintenance
    'database_maintenance': {
        'enabled': True,
        'cleanup_time': '04:00',
        'retention_days': 90
    },
    
    # Notifications (Pushover)
    'notifications': {
        'pushover': {
            'api_token': '',
            'user_key': ''
        }
    },
    
    # Absence Detection
    'absence': {
        'enabled': True,
        'detection_method': 'presence_sensor',
        'pushover_api_key': '',
        'pushover_user_key': ''
    },
    
    # Decision Engine
    'decision_engine': {
        'mode': 'auto',
        'confidence_threshold': 0.7,
        'safety_checks': True
    },
    
    # Logging
    'logging': {
        'level': 'INFO',
        'path': 'logs/ki_system.log',
        'max_size_mb': 100
    }
}


def deep_merge(base: Dict, override: Dict) -> Dict:
    """
    Tiefes Mergen von zwei Dictionaries.
    Override-Werte überschreiben Base-Werte.
    Fehlende Keys in Override werden aus Base übernommen.
    """
    result = deepcopy(base)
    
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    
    return result


class ConfigManager:
    """Zentrales Config-Management mit automatischen Defaults"""
    
    _instance = None
    _config: Dict[str, Any] = {}
    _config_path = Path('config/config.yaml')
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._load_config()
        return cls._instance
    
    def _load_config(self):
        """Lädt Config und merged mit Defaults"""
        user_config = {}
        
        if self._config_path.exists():
            try:
                with open(self._config_path, 'r') as f:
                    user_config = yaml.safe_load(f) or {}
            except Exception as e:
                logger.error(f"Error loading config: {e}")
        
        # Merge: User-Config überschreibt Defaults
        self._config = deep_merge(DEFAULT_CONFIG, user_config)
        logger.debug("Config loaded and merged with defaults")
    
    def reload(self):
        """Config neu laden"""
        self._load_config()
    
    def get(self, key: str, default: Any = None) -> Any:
        """
        Hole Config-Wert mit Punkt-Notation.
        
        Beispiel: config.get('ventilation_notifications.enabled')
        """
        keys = key.split('.')
        value = self._config
        
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default
        
        return value
    
    def get_section(self, section: str) -> Dict:
        """Hole kompletten Config-Abschnitt mit Defaults"""
        return self._config.get(section, DEFAULT_CONFIG.get(section, {}))
    
    def set(self, key: str, value: Any, save: bool = False):
        """Setze Config-Wert (optional speichern)"""
        keys = key.split('.')
        config = self._config
        
        for k in keys[:-1]:
            if k not in config:
                config[k] = {}
            config = config[k]
        
        config[keys[-1]] = value
        
        if save:
            self.save()
    
    def save(self):
        """Speichere aktuelle Config"""
        try:
            self._config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._config_path, 'w') as f:
                yaml.dump(self._config, f, default_flow_style=False, allow_unicode=True)
            logger.info("Config saved")
        except Exception as e:
            logger.error(f"Error saving config: {e}")
    
    @property
    def config(self) -> Dict:
        """Volle Config als Dict"""
        return self._config
    
    # Convenience-Methoden für häufige Abschnitte
    @property
    def ventilation(self) -> Dict:
        return self.get_section('ventilation_notifications')
    
    @property
    def forgotten_light(self) -> Dict:
        return self.get_section('forgotten_light')
    
    @property
    def heating(self) -> Dict:
        return self.get_section('heating')
    
    @property
    def notifications(self) -> Dict:
        return self.get_section('notifications')


# Singleton-Instanz für einfachen Import
def get_config() -> ConfigManager:
    """Hole Config-Manager Instanz"""
    return ConfigManager()


def get_config_value(key: str, default: Any = None) -> Any:
    """Shortcut für ConfigManager().get()"""
    return ConfigManager().get(key, default)


def get_config_section(section: str) -> Dict:
    """Shortcut für ConfigManager().get_section()"""
    return ConfigManager().get_section(section)
