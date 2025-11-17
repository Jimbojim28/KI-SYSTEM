"""
Background Service: Sammelt Beleuchtungsdaten für ML-Training
Läuft kontinuierlich und speichert jeden Zustandswechsel
"""

import time
from datetime import datetime
from threading import Thread
from loguru import logger
from typing import Dict, Set

from src.utils.database import Database
from src.data_collector.platform_factory import PlatformFactory
from src.utils.sensor_helper import SensorHelper


class LightingDataCollector:
    """
    Sammelt Beleuchtungsdaten für das LightingModel
    
    Erfasst:
    - Alle Zustandsänderungen von Lampen
    - Helligkeitsänderungen
    - Zeitstempel und Kontext (Tageszeit, Anwesenheit, etc.)
    """
    
    def __init__(self, db: Database = None, config: dict = None, engine=None):
        self.db = db or Database()
        self.config = config or {}
        self.engine = engine
        self.interval = self.config.get('data_collection', {}).get('lighting_interval', 60)
        self.running = False
        self.thread = None
        self.last_states: Dict[str, Dict] = {}  # device_id -> last known state
        self.sensor_helper = SensorHelper(engine) if engine else None
        self.last_collection_time = None
        self.last_collection_success = None
        self.last_error = None
        self.total_events_collected = 0
        
        # Platform-spezifische Collector basierend auf platform.type
        self.collectors = []
        platform_type = self.config.get('platform', {}).get('type', '').lower()

        try:
            if platform_type == 'homey':
                from src.data_collector.homey_collector import HomeyCollector
                homey_config = self.config.get('homey', {})
                homey = HomeyCollector(
                    url=homey_config.get('url', ''),
                    token=homey_config.get('token', '')
                )
                self.collectors.append(('homey', homey))
                logger.info("Homey collector initialized for lighting data")
            elif platform_type == 'homeassistant':
                from src.data_collector.ha_collector import HomeAssistantCollector
                ha_config = self.config.get('homeassistant', {})
                ha = HomeAssistantCollector(
                    url=ha_config.get('url', ''),
                    token=ha_config.get('token', '')
                )
                self.collectors.append(('homeassistant', ha))
                logger.info("Home Assistant collector initialized for lighting data")
            else:
                logger.warning(f"Unknown or missing platform type: {platform_type}")
        except Exception as e:
            logger.error(f"Could not initialize platform collector for lighting data: {e}")
    
    def start(self):
        """Startet Background-Collection"""
        if self.running:
            logger.warning("LightingDataCollector already running")
            return
        
        if not self.collectors:
            logger.warning("No collectors available for lighting data collection")
            return
        
        self.running = True
        self.thread = Thread(target=self._collection_loop, daemon=True)
        self.thread.start()
        logger.info(f"LightingDataCollector started (interval: {self.interval}s)")
    
    def stop(self):
        """Stoppt Background-Collection"""
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
        logger.info("LightingDataCollector stopped")
    
    def _collection_loop(self):
        """Hauptloop für Datensammlung"""
        while self.running:
            try:
                self.last_collection_time = datetime.now()
                self._collect_lighting_data()
                self.last_collection_success = True
                self.last_error = None
            except Exception as e:
                error_msg = str(e).encode('ascii', 'ignore').decode('ascii')
                logger.error(f"Error in lighting data collection: {error_msg}")
                self.last_collection_success = False
                self.last_error = str(e).encode('ascii', 'ignore').decode('ascii') or str(e)[:100]
            
            time.sleep(self.interval)
    
    def _collect_lighting_data(self):
        """Sammelt Daten von allen Beleuchtungsgeräten"""
        for platform_name, collector in self.collectors:
            try:
                devices = collector.get_all_devices()
                
                for device in devices:
                    # Nur Lampen/Lights
                    if not self._is_light_device(device):
                        continue
                    
                    device_id = device.get('id')
                    device_name = device.get('name', 'Unknown')

                    # Handle zone - can be string (ID) or dict
                    zone = device.get('zone')
                    if isinstance(zone, dict):
                        room_name = zone.get('name', 'Unknown')
                    elif isinstance(zone, str):
                        room_name = zone  # Zone ID
                    else:
                        room_name = 'Unknown'
                    
                    # Aktueller Zustand
                    state = device.get('capabilitiesObj', {}).get('onoff', {}).get('value')
                    brightness = device.get('capabilitiesObj', {}).get('dim', {}).get('value')
                    
                    if brightness is not None:
                        brightness = int(brightness * 100)  # 0-100
                    
                    # State-String
                    if state is True:
                        state_str = 'on'
                    elif state is False:
                        state_str = 'off'
                    else:
                        continue  # Kein valider State
                    
                    # Prüfe ob State geändert hat
                    last_state = self.last_states.get(device_id, {})
                    if last_state.get('state') == state_str and last_state.get('brightness') == brightness:
                        continue  # Keine Änderung
                    
                    # Speichere neuen State
                    self.last_states[device_id] = {
                        'state': state_str,
                        'brightness': brightness,
                        'timestamp': datetime.now()
                    }
                    
                    # Zusatzkontext
                    outdoor_light = self._get_outdoor_light()
                    presence = self._detect_presence(room_name)
                    motion_detected = self.sensor_helper.get_motion_detected(room_name) if self.sensor_helper and room_name else False

                    # In DB speichern
                    self.db.add_lighting_event(
                        device_id=device_id,
                        device_name=device_name,
                        room_name=room_name,
                        state=state_str,
                        brightness=brightness,
                        outdoor_light=outdoor_light,
                        presence=presence,
                        motion_detected=motion_detected
                    )
                    self.total_events_collected += 1
                    
                    logger.debug(f"Lighting event: {device_name} -> {state_str} (brightness: {brightness})")
                    
            except Exception as e:
                error_msg = str(e).encode('ascii', 'ignore').decode('ascii')
                logger.error(f"Error collecting from {platform_name}: {error_msg}")
    
    def _is_light_device(self, device: Dict) -> bool:
        """Prüft ob Gerät eine Lampe ist"""
        device_class = device.get('class', '').lower()
        capabilities = device.get('capabilities', [])
        
        # Homey: class=light
        if 'light' in device_class:
            return True
        
        # Capability-basiert
        if 'onoff' in capabilities and ('dim' in capabilities or 'light_hue' in capabilities):
            return True
        
        return False
    
    def _get_outdoor_light(self) -> float:
        """Holt Außenhelligkeit (Luxwert oder Sonnenstand)"""
        if self.sensor_helper:
            return self.sensor_helper.get_outdoor_brightness()

        # Fallback: Einfache Zeit-basierte Schätzung
        now = datetime.now()
        hour = now.hour

        # Grobe Schätzung: 0-100
        if 6 <= hour <= 20:
            # Tag: höhere Helligkeit
            return 80.0
        else:
            # Nacht: niedrige Helligkeit
            return 10.0
    
    def _detect_presence(self, room_name: str) -> bool:
        """Detektiert Anwesenheit im Raum"""
        if self.sensor_helper and room_name:
            return self.sensor_helper.get_presence_in_room(room_name)

        # Fallback: konservativ
        return False
    
    def get_stats(self) -> Dict:
        """Gibt Statistiken zurück"""
        return {
            'running': self.running,
            'interval': self.interval,
            'collectors_count': len(self.collectors),
            'tracked_devices': len(self.last_states),
            'total_events': self.db.get_lighting_events_count(),
            'last_collection': self.last_collection_time.isoformat() if self.last_collection_time else None,
            'last_success': self.last_collection_success,
            'last_error': self.last_error,
            'events_this_session': self.total_events_collected
        }


def start_lighting_collector(config: dict = None):
    """Convenience-Funktion zum Starten"""
    collector = LightingDataCollector(config=config)
    collector.start()
    return collector


if __name__ == '__main__':
    # Test
    from src.utils.config_loader import ConfigLoader
    
    config = ConfigLoader()
    collector = LightingDataCollector(config=config.config)
    
    print("Starting lighting data collector...")
    collector.start()
    
    try:
        while True:
            time.sleep(10)
            stats = collector.get_stats()
            print(f"Stats: {stats}")
    except KeyboardInterrupt:
        print("\nStopping...")
        collector.stop()
