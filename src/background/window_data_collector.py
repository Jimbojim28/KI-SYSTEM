"""
Window Data Collector - Kontinuierliche Fenster-Status-Sammlung

Sammelt alle 60 Sekunden Daten von allen Fenstern für Heizungsoptimierung und Lüftungsstatistik:
- Fenster offen/geschlossen
- Raum-Zuordnung
- Alarme
- Lüftungs-Events mit Klimadaten (für ML-Training)

Hinweis: Türen werden explizit NICHT erfasst, nur Fenster!
"""

import threading
import time
import json
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, List
from loguru import logger
from src.utils.database import Database


class WindowDataCollector:
    """Sammelt kontinuierlich Fenster-Status für Heizungsoptimierung und Lüftungsstatistik (nur Fenster, keine Türen)"""

    def __init__(self, engine=None, interval_seconds: int = 60):  # 60 Sekunden = 1 Minute
        """
        Args:
            engine: DecisionEngine Instanz für Zugriff auf Platform
            interval_seconds: Sammel-Intervall in Sekunden (default: 60)
        """
        self.engine = engine
        self.interval_seconds = interval_seconds
        self.running = False
        self.thread = None
        self.last_collection = None
        self.db = Database()
        
        # Tracke vorherigen Fenster-Status für Event-Erkennung
        self._previous_window_states: Dict[str, bool] = {}  # device_id -> is_open
        
        # Sensor-Mapping Datei für CO2-Sensor-Prüfung
        self._sensor_mapping_file = Path('data/ventilation_sensor_mapping.json')
        self._rooms_with_co2_cache: Optional[set] = None
        self._cache_timestamp: Optional[datetime] = None

        # HA Window Mapping
        self._ha_mapping_file = Path('config/ha_window_mapping.json')
        self._ha_mapping_cache = None
        self._ha_mapping_timestamp = None

        logger.info(f"Window Data Collector initialized ({interval_seconds}s interval)")
    
    def _get_ha_mapping(self) -> Dict:
        """Lädt das HA Window Mapping"""
        if (self._ha_mapping_cache is not None and 
            self._ha_mapping_timestamp is not None and
            (datetime.now() - self._ha_mapping_timestamp).seconds < 60):
            return self._ha_mapping_cache
            
        mapping = {}
        try:
            if self._ha_mapping_file.exists():
                with open(self._ha_mapping_file, 'r') as f:
                    data = json.load(f)
                    mapping = data.get('mappings', {})
        except Exception as e:
            logger.error(f"Error loading HA window mapping: {e}")
            
        self._ha_mapping_cache = mapping
        self._ha_mapping_timestamp = datetime.now()
        return mapping

    def _get_ha_collector(self):
        """Holt den HA Collector (aus Engine oder erstellt neu)"""
        if not self.engine:
            return None
            
        # 1. Prüfe ob in Engine vorhanden (Multi-Platform)
        if hasattr(self.engine, 'platforms') and self.engine.platforms:
            if 'homeassistant' in self.engine.platforms:
                return self.engine.platforms['homeassistant']
            if 'ha' in self.engine.platforms:
                return self.engine.platforms['ha']
        
        # 2. Prüfe ob Primary Platform HA ist
        if hasattr(self.engine, 'platform') and self.engine.platform:
            if self.engine.platform.get_platform_name() == 'homeassistant':
                return self.engine.platform

        # 3. Versuche temporär zu erstellen (wenn Config vorhanden)
        try:
            from src.data_collector.ha_collector import HomeAssistantCollector
            ha_url = self.engine.config.get('homeassistant.url')
            ha_token = self.engine.config.get('homeassistant.token')
            
            if ha_url and ha_token:
                return HomeAssistantCollector(ha_url, ha_token)
        except Exception as e:
            logger.debug(f"Could not create temporary HA collector: {e}")
            
        return None

    def _get_rooms_with_co2_sensors(self) -> set:
        """Gibt ein Set von Raumnamen zurück, die CO2-Sensoren haben (aus Sensor-Mapping)"""
        # Cache für 5 Minuten
        if (self._rooms_with_co2_cache is not None and 
            self._cache_timestamp is not None and
            (datetime.now() - self._cache_timestamp).seconds < 300):
            return self._rooms_with_co2_cache
        
        rooms_with_co2 = set()
        
        try:
            if self._sensor_mapping_file.exists():
                with open(self._sensor_mapping_file, 'r') as f:
                    data = json.load(f)
                
                room_mapping = data.get('rooms', {})
                
                # Hole Zonen-Namen
                zones = {}
                if self.engine and self.engine.platform:
                    try:
                        zone_dict = self.engine.platform.get_zones() or {}
                        # Homey API gibt {zone_id: zone_data, ...} zurück
                        if isinstance(zone_dict, dict):
                            for zone_id, zone_data in zone_dict.items():
                                if isinstance(zone_data, dict):
                                    zones[zone_id] = zone_data.get('name', '')
                    except:
                        pass
                
                for room_id, sensors in room_mapping.items():
                    if sensors.get('co2'):
                        # Füge sowohl room_id als auch den Zone-Namen hinzu
                        rooms_with_co2.add(room_id.lower())
                        zone_name = zones.get(room_id, '')
                        if zone_name:
                            rooms_with_co2.add(zone_name.lower())
        except Exception as e:
            logger.debug(f"Error loading sensor mapping for CO2 check: {e}")
        
        self._rooms_with_co2_cache = rooms_with_co2
        self._cache_timestamp = datetime.now()
        
        return rooms_with_co2

    def start(self):
        """Startet die kontinuierliche Datensammlung"""
        if self.running:
            logger.warning("Window Data Collector is already running")
            return

        self.running = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        logger.info(f"Window Data Collector started (collects every {self.interval_seconds}s)")

    def stop(self):
        """Stoppt die kontinuierliche Datensammlung"""
        if not self.running:
            return

        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
        logger.info("Window Data Collector stopped")

    def _run(self):
        """Haupt-Loop für kontinuierliche Datensammlung"""
        while self.running:
            try:
                self._collect_data()
                self.last_collection = datetime.now()
            except Exception as e:
                logger.error(f"Error in window data collection: {e}")

            # Warte bis zum nächsten Intervall
            time.sleep(self.interval_seconds)

    def _get_window_calibration(self, zone_id: str) -> Dict:
        """Holt die Fenster-Kalibrierung für eine Zone aus rooms.json"""
        default_calibration = {
            'closed_angle': 0,
            'tilted_min': 5,
            'tilted_max': 45
        }
        
        if not zone_id:
            return default_calibration
        
        try:
            import json
            from pathlib import Path
            rooms_file = Path('data/rooms.json')
            
            if rooms_file.exists():
                with open(rooms_file, 'r') as f:
                    rooms_data = json.load(f)
                
                calibrations = rooms_data.get('window_calibration', {})
                if zone_id in calibrations:
                    return calibrations[zone_id]
        except Exception as e:
            logger.debug(f"Error loading window calibration: {e}")
        
        return default_calibration

    def _extract_room_from_device_name(self, device_name: str) -> Optional[str]:
        """Extrahiert den Raumnamen aus dem Gerätenamen (z.B. 'Wohnzimmer 2 Fenster' -> 'Wohnzimmer')"""
        if not device_name:
            return None
            
        name_lower = device_name.lower()
        room_name = device_name
        
        # Entferne typische Fenster/Tür-Suffixe
        for suffix in [' fenster', ' tür', ' door', ' window', '-fenster', '-tür']:
            if suffix in name_lower:
                idx = name_lower.find(suffix)
                room_name = device_name[:idx].strip()
                break
        
        # Entferne Nummerierung am Ende (z.B. "Wohnzimmer 2" -> "Wohnzimmer", "Wohnzimmer 1" -> "Wohnzimmer")
        import re
        room_name = re.sub(r'\s+\d+$', '', room_name).strip()
        
        return room_name if room_name else device_name.strip()

    def _get_room_climate(self, room_name: str) -> Dict:
        """Holt aktuelle Klimadaten für einen Raum.

        Priorität:
        1. Sensor-Mapping (ventilation_sensor_mapping.json) – nutzt den explizit gespeicherten Sensor
        2. Zone-basierte Auto-Discovery – Fallback wenn kein Mapping vorhanden

        CO2-Werte werden nur gesammelt wenn der Raum einen CO2-Sensor im Sensor-Mapping hat.
        """
        climate = {'temp': None, 'humidity': None, 'co2': None}

        if not room_name or not self.engine or not self.engine.platform:
            return climate

        # Prüfe ob dieser Raum einen CO2-Sensor im Mapping hat
        rooms_with_co2 = self._get_rooms_with_co2_sensors()
        room_has_co2_sensor = room_name.lower() in rooms_with_co2

        try:
            # Hole alle Geräte (einmalig für beide Strategien)
            if hasattr(self.engine.platform, '_device_cache'):
                self.engine.platform._refresh_device_cache()
                devices = list(self.engine.platform._device_cache.values()) if isinstance(
                    self.engine.platform._device_cache, dict) else self.engine.platform._device_cache
            else:
                devices = self.engine.platform.get_states() or []

            # Lookup-Dict: device_id → device (für Mapping-Strategie)
            device_lookup = {d.get('id', ''): d for d in devices if isinstance(d, dict)}

            # ── Strategie 1: Sensor-Mapping bevorzugen ─────────────────────────────
            try:
                if self._sensor_mapping_file.exists():
                    with open(self._sensor_mapping_file, 'r') as f:
                        mapping_data = json.load(f)

                    room_lower = room_name.lower()
                    mapped_sensors = None

                    # Suche Raum im Mapping anhand des 'name'-Felds (exakter Match)
                    for _room_id, sensors in mapping_data.get('rooms', {}).items():
                        if sensors.get('name', '').lower() == room_lower:
                            mapped_sensors = sensors
                            break

                    if mapped_sensors:
                        # Temperatur aus Mapping
                        temp_id = mapped_sensors.get('temperature', '')
                        if temp_id and temp_id not in ('', 'none') and temp_id in device_lookup:
                            dev = device_lookup[temp_id]
                            caps = dev.get('capabilitiesObj', {})
                            val = caps.get('measure_temperature', {}).get('value')
                            if val is not None and -20 < val < 45:
                                climate['temp'] = val
                                logger.debug(f"Mapped temp für '{room_name}': {val}°C von '{dev.get('name')}'")
                            elif val is not None:
                                logger.warning(
                                    f"Mapping-Sensor '{dev.get('name')}' meldet {val}°C für '{room_name}' – implausibel, ignoriert"
                                )

                        # Luftfeuchtigkeit aus Mapping
                        hum_id = mapped_sensors.get('humidity', '')
                        if hum_id and hum_id not in ('', 'none') and hum_id in device_lookup:
                            dev = device_lookup[hum_id]
                            caps = dev.get('capabilitiesObj', {})
                            val = caps.get('measure_humidity', {}).get('value')
                            if val is not None and 0 <= val <= 100:
                                climate['humidity'] = val
                                logger.debug(f"Mapped humidity für '{room_name}': {val}% von '{dev.get('name')}'")

                        # CO2 aus Mapping (nur wenn Raum CO2-Sensor hat)
                        if room_has_co2_sensor:
                            co2_id = mapped_sensors.get('co2', '')
                            if co2_id and co2_id not in ('', 'none') and co2_id in device_lookup:
                                dev = device_lookup[co2_id]
                                caps = dev.get('capabilitiesObj', {})
                                val = caps.get('measure_co2', {}).get('value')
                                if val is not None and 200 < val < 10000:
                                    climate['co2'] = val

                        # Wenn alle benötigten Werte per Mapping gefunden → fertig
                        if climate['temp'] is not None and climate['humidity'] is not None:
                            return climate
            except Exception as e:
                logger.debug(f"Sensor-Mapping-Lookup für '{room_name}' fehlgeschlagen: {e}")

            # ── Strategie 2: Zone-basierte Auto-Discovery ───────────────────────────
            # (nur für Felder die per Mapping noch nicht gefunden wurden)

            # Hole Zone-Mapping
            zones = {}
            try:
                zone_dict = self.engine.platform.get_zones() or {}
                if isinstance(zone_dict, dict):
                    for zone_id, zone_data in zone_dict.items():
                        if isinstance(zone_data, dict):
                            zones[zone_id] = zone_data.get('name', '')
            except:
                pass

            room_lower = room_name.lower()

            for device in devices:
                if not isinstance(device, dict):
                    continue

                zone_id = device.get('zone')
                device_room = zones.get(zone_id, '').lower()
                device_name = device.get('name', '').lower()

                room_match = (
                    room_lower in device_room or
                    device_room in room_lower or
                    room_lower in device_name
                )

                if not room_match:
                    continue

                caps = device.get('capabilitiesObj', {})

                # Temperatur – nur wenn noch nicht per Mapping gefunden
                if climate['temp'] is None and 'measure_temperature' in caps:
                    val = caps['measure_temperature'].get('value')
                    if val is not None and -20 < val < 45:
                        climate['temp'] = val
                    elif val is not None and val >= 45:
                        logger.debug(f"Auto-Discovery: {val}°C von '{device.get('name')}' in '{room_name}' abgelehnt (Chip-Temp)")

                # Luftfeuchtigkeit – nur wenn noch nicht per Mapping gefunden
                if climate['humidity'] is None and 'measure_humidity' in caps:
                    val = caps['measure_humidity'].get('value')
                    if val is not None and 0 <= val <= 100:
                        climate['humidity'] = val

                # CO2 – NUR sammeln wenn der Raum einen CO2-Sensor im Mapping hat
                if room_has_co2_sensor and climate['co2'] is None and 'measure_co2' in caps:
                    co2_room_match = False
                    if device_room and len(device_room) >= 3:
                        co2_room_match = (
                            device_room == room_lower or
                            room_lower in device_room or
                            (len(device_room) >= 3 and device_room in room_lower)
                        )
                    if not co2_room_match and 'co2' in device_name.lower():
                        co2_room_match = room_lower in device_name

                    if co2_room_match:
                        val = caps['measure_co2'].get('value')
                        if val is not None and 200 < val < 10000:
                            climate['co2'] = val
                            logger.debug(f"CO2 für '{room_name}' von '{device.get('name')}' (Zone '{device_room}'): {val} ppm")

            # Wenn CO2 noch nicht gefunden, suche nach CO2-Gerät mit Raumnamen im Gerätenamen
            if room_has_co2_sensor and climate['co2'] is None:
                for device in devices:
                    if not isinstance(device, dict):
                        continue
                    device_name = device.get('name', '').lower()
                    caps = device.get('capabilitiesObj', {})
                    if 'co2' in device_name and room_lower in device_name and 'measure_co2' in caps:
                        val = caps['measure_co2'].get('value')
                        if val is not None and 200 < val < 10000:
                            climate['co2'] = val
                            logger.debug(f"CO2 für '{room_name}' von '{device.get('name')}' (Namens-Match): {val} ppm")
                            break

        except Exception as e:
            logger.debug(f"Error getting room climate for {room_name}: {e}")

        return climate

    def _get_outdoor_climate(self) -> Dict:
        """Holt aktuelle Außen-Klimadaten"""
        outdoor = {'temp': None, 'humidity': None}
        
        if not self.engine:
            return outdoor
            
        try:
            # Versuche Weather-Daten vom Engine zu holen
            if hasattr(self.engine, 'weather_collector') and self.engine.weather_collector:
                weather = self.engine.weather_collector.get_current_weather()
                if weather:
                    outdoor['temp'] = weather.get('temperature')
                    outdoor['humidity'] = weather.get('humidity')
            
            # Fallback: Suche nach Außensensor
            if outdoor['temp'] is None and self.engine.platform:
                if hasattr(self.engine.platform, '_device_cache'):
                    devices = list(self.engine.platform._device_cache.values()) if isinstance(
                        self.engine.platform._device_cache, dict) else self.engine.platform._device_cache or []
                else:
                    devices = self.engine.platform.get_states() or []
                
                for device in devices:
                    if not isinstance(device, dict):
                        continue
                    name = device.get('name', '').lower()
                    if any(kw in name for kw in ['außen', 'outdoor', 'aussen', 'garten', 'balkon']):
                        caps = device.get('capabilitiesObj', {})
                        if 'measure_temperature' in caps:
                            outdoor['temp'] = caps['measure_temperature'].get('value')
                        if 'measure_humidity' in caps:
                            outdoor['humidity'] = caps['measure_humidity'].get('value')
                        break
                        
        except Exception as e:
            logger.debug(f"Error getting outdoor climate: {e}")
            
        return outdoor

    def _collect_data(self):
        """Sammelt aktuellen Status von allen Fenstern/Türen"""
        if not self.engine:
            logger.debug("No engine available for window data collection")
            return

        try:
            # Hole Konfiguration für Platform Sources
            sources = self.engine.config.get('data_collection.platform_sources.window_states', {})
            use_homey = sources.get('homey', True)
            use_ha = sources.get('homeassistant', True)

            # Hole alle Geräte direkt aus dem Cache
            all_devices = []
            
            # 1. Primary Platform Devices (Homey)
            if use_homey and self.engine.platform:
                if hasattr(self.engine.platform, '_device_cache'):
                    # Homey verwendet _device_cache
                    self.engine.platform._refresh_device_cache()
                    cache = self.engine.platform._device_cache
                    if isinstance(cache, dict):
                        all_devices = list(cache.values())
                    elif isinstance(cache, list):
                        all_devices = cache
                else:
                    # Fallback: Versuche get_states()
                    states = self.engine.platform.get_states()
                    if isinstance(states, list):
                        all_devices = states
            
            # 2. HA Mapped Devices (BTHome etc.)
            ha_mapping = self._get_ha_mapping()
            if use_ha and ha_mapping:
                ha_collector = self._get_ha_collector()
                if ha_collector:
                    for mapping_id, config in ha_mapping.items():
                        try:
                            fake_device = None
                            
                            # Case A: Complex Mapping (Grouped entities)
                            if 'entities' in config and isinstance(config['entities'], dict):
                                entities = config['entities']
                                contact_entity = entities.get('contact')
                                
                                if contact_entity:
                                    state = ha_collector.get_state(contact_entity)
                                    if state:
                                        is_open = state['state'] in ['on', 'open', 'true']
                                        
                                        capabilities = {'alarm_contact': {'value': is_open}}
                                        
                                        # Battery
                                        if 'battery' in entities:
                                            batt_state = ha_collector.get_state(entities['battery'])
                                            if batt_state and batt_state['state'].replace('.','',1).isdigit():
                                                capabilities['measure_battery'] = {'value': float(batt_state['state'])}
                                                
                                        # Illuminance
                                        if 'illuminance' in entities:
                                            lux_state = ha_collector.get_state(entities['illuminance'])
                                            if lux_state and lux_state['state'].replace('.','',1).isdigit():
                                                capabilities['measure_luminance'] = {'value': float(lux_state['state'])}
                                                
                                        # Rotation/Tilt
                                        if 'rotation' in entities:
                                            rot_state = ha_collector.get_state(entities['rotation'])
                                            if rot_state and rot_state['state'].replace('.','',1).isdigit():
                                                capabilities['tilt'] = {'value': float(rot_state['state'])}

                                        fake_device = {
                                            'id': mapping_id,
                                            'name': config.get('name', 'HA Window'),
                                            'class': 'sensor',
                                            'capabilitiesObj': capabilities,
                                            'zone': None,
                                            '_force_room': config.get('room')
                                        }

                            # Case B: Simple Mapping (Key is entity_id)
                            else:
                                entity_id = mapping_id
                                state = ha_collector.get_state(entity_id)
                                if state:
                                    is_open = state['state'] in ['on', 'open', 'true']
                                    
                                    fake_device = {
                                        'id': entity_id,
                                        'name': config.get('name', state.get('attributes', {}).get('friendly_name', entity_id)),
                                        'class': 'sensor',
                                        'capabilitiesObj': {
                                            'alarm_contact': {'value': is_open}
                                        },
                                        'zone': None,
                                        '_force_room': config.get('room')
                                    }
                            
                            if fake_device:
                                # Füge 'window' zum Namen hinzu damit der Filter es als Fenster erkennt
                                if 'window' not in fake_device['name'].lower() and 'fenster' not in fake_device['name'].lower():
                                    fake_device['name'] += ' Fenster'
                                    
                                all_devices.append(fake_device)
                                
                        except Exception as e:
                            logger.error(f"Error collecting HA device {mapping_id}: {e}")
            
            if not all_devices:
                logger.debug("No devices found for window data collection")
                return
            
            # Hole Zone-Mapping für Raum-Filterung
            zone_names = {}
            try:
                zone_dict = self.engine.platform.get_zones() or {}
                if isinstance(zone_dict, dict):
                    for zone_id, zone_data in zone_dict.items():
                        if isinstance(zone_data, dict):
                            zone_names[zone_id] = zone_data.get('name', '')
            except:
                pass
            
            # Räume die keine echten Fenster-Räume sind ausschließen
            excluded_rooms = {'weihnachtsbeleuchtung', 'weihnachtslicht', 'christmas', 'nachtlicht'}
                
            window_devices = []

            # Filtere nur nach Fenstern (KEINE Türen)
            for device in all_devices:
                # Skip wenn device kein Dictionary ist
                if not isinstance(device, dict):
                    continue

                device_class = device.get('class', '').lower()
                device_name = device.get('name', '').lower()
                capabilities = device.get('capabilitiesObj', {})
                
                # Überspringe Geräte aus ausgeschlossenen Räumen
                zone_id = device.get('zone', '')
                room_name = zone_names.get(zone_id, '').lower()
                if room_name in excluded_rooms:
                    continue

                # Prüfe ob es ein Fenster-Sensor ist (aber KEINE Tür)
                # Explizit Türen ausschließen
                is_door = ('door' in device_name or 'tür' in device_name or 
                          'tur' in device_name or 'türe' in device_name)
                
                is_window = ('window' in device_name or 'fenster' in device_name)
                
                # Nur Fenster, keine Türen
                if not is_door and is_window and 'alarm_contact' in capabilities:
                    window_devices.append(device)

            if not window_devices:
                logger.debug("No window devices found for data collection")
                return

            # Sammle Daten von jedem Fenster (keine Türen)
            collected_count = 0
            for device in window_devices:
                try:
                    observation_id = self._collect_device_data(device)
                    if observation_id:
                        collected_count += 1
                except Exception as e:
                    logger.error(f"Error collecting data from device {device.get('id')}: {e}")

            logger.info(f"Collected window data from {collected_count}/{len(window_devices)} window devices")

        except Exception as e:
            logger.error(f"Error in window data collection: {e}")

    def _collect_device_data(self, device: dict) -> Optional[int]:
        """Sammelt Daten von einem einzelnen Fenster"""
        device_id = device.get('id')
        if not device_id:
            return None

        device_name = device.get('name', 'Unbekannt')
        capabilities = device.get('capabilitiesObj', {})
        zone_id = device.get('zone')

        # Hole Tilt-Winkel (falls vorhanden)
        tilt_angle = None
        if 'tilt' in capabilities:
            tilt_angle = capabilities['tilt'].get('value')

        # Status: offen oder geschlossen
        is_open = False
        contact_alarm = False
        window_state = 'closed'  # closed, tilted, open

        # Prüfe alarm_contact capability (typisch für Fenster/Tür-Sensoren)
        if 'alarm_contact' in capabilities:
            # alarm_contact: true = offen, false = geschlossen
            alarm_value = capabilities['alarm_contact'].get('value')
            if alarm_value is not None:
                is_open = bool(alarm_value)
                contact_alarm = is_open

        # Bestimme Fensterzustand basierend auf Kalibrierung (wenn Tilt vorhanden)
        if tilt_angle is not None:
            calibration = self._get_window_calibration(zone_id)
            closed_angle = calibration.get('closed_angle', 0)
            tilted_min = calibration.get('tilted_min', 5)
            tilted_max = calibration.get('tilted_max', 45)
            
            diff = abs(tilt_angle - closed_angle)
            
            if diff <= 2:  # Toleranz für "geschlossen"
                window_state = 'closed'
                is_open = False
            elif diff >= tilted_min and diff <= tilted_max:
                window_state = 'tilted'
                is_open = True  # Gekippt gilt als offen für Lüftung
            else:
                window_state = 'open'
                is_open = True
        elif is_open:
            window_state = 'open'

        # Alternative: windowcoverings_state (für Rollläden/Jalousien)
        if not is_open and 'windowcoverings_state' in capabilities:
            state = capabilities['windowcoverings_state'].get('value', 'idle')
            is_open = (state == 'up')  # up = offen
            if is_open:
                window_state = 'open'

        # Alternative: onoff (für manche Sensoren)
        if not is_open and 'onoff' in capabilities:
            is_open = capabilities['onoff'].get('value', False)
            if is_open:
                window_state = 'open'

        # Raum-Name aus Zone
        room_name = None
        
        # Check for forced room (from HA mapping)
        if device.get('_force_room'):
            room_name = device.get('_force_room')

        if not room_name and zone_id and hasattr(self.engine, 'platform'):
            try:
                zones = self.engine.platform.get_zones() or {}
                # Homey API gibt {zone_id: zone_data, ...} zurück
                if isinstance(zones, dict) and zone_id in zones:
                    zone_data = zones[zone_id]
                    if isinstance(zone_data, dict):
                        room_name = zone_data.get('name')
            except (AttributeError, KeyError, TypeError) as e:
                logger.debug(f"Could not fetch zone name for zone_id {zone_id}: {e}")
        
        # Fallback: Extrahiere Raumnamen aus Gerätenamen
        if not room_name:
            room_name = self._extract_room_from_device_name(device_name)

        # Speichere in Datenbank (Observations)
        observation_id = self.db.add_window_observation(
            device_id=device_id,
            device_name=device_name,
            room_name=room_name,
            is_open=is_open,
            contact_alarm=contact_alarm,
            tilt_angle=tilt_angle,
            window_state=window_state
        )

        # === Lüftungs-Event-Tracking ===
        # Prüfe ob sich der Status geändert hat (is_open oder window_state)
        previous_data = self._previous_window_states.get(device_id)
        previous_is_open = previous_data.get('is_open') if isinstance(previous_data, dict) else previous_data
        previous_window_state = previous_data.get('window_state') if isinstance(previous_data, dict) else None
        
        if previous_is_open is not None and previous_is_open != is_open:
            # Status hat sich geändert (offen <-> geschlossen)
            if is_open:
                # Fenster wurde geöffnet -> Starte Lüftungs-Event
                self._start_ventilation_event(device_id, device_name, room_name, window_state)
            else:
                # Fenster wurde geschlossen -> Beende Lüftungs-Event
                self._end_ventilation_event(device_id, room_name)
        
        elif previous_is_open is None and is_open:
            # Erstes Mal gesehen und offen -> Starte Event
            self._start_ventilation_event(device_id, device_name, room_name, window_state)
        
        elif previous_is_open and is_open and previous_window_state != window_state:
            # Fenster war offen und Zustand hat sich geändert (z.B. von gekippt zu offen)
            # Beende altes Event und starte neues
            self._end_ventilation_event(device_id, room_name)
            self._start_ventilation_event(device_id, device_name, room_name, window_state)
            logger.info(f"🪟 Window state changed: {device_name} {previous_window_state} -> {window_state}")
        
        # Speichere aktuellen Status (jetzt als Dict mit window_state)
        self._previous_window_states[device_id] = {'is_open': is_open, 'window_state': window_state}

        return observation_id

    def _start_ventilation_event(self, device_id: str, device_name: str, room_name: str, 
                                  window_state: str = 'open'):
        """Startet ein Lüftungs-Event
        
        Args:
            window_state: 'tilted' (gekippt) oder 'open' (weit offen)
        """
        try:
            # Hole aktuelle Klimadaten
            room_climate = self._get_room_climate(room_name) if room_name else {}
            outdoor = self._get_outdoor_climate()
            
            state_label = '🪟 gekippt' if window_state == 'tilted' else '🪟 offen'
            
            self.db.start_ventilation_event(
                device_id=device_id,
                device_name=device_name,
                room_name=room_name,
                temp_start=room_climate.get('temp'),
                humidity_start=room_climate.get('humidity'),
                co2_start=room_climate.get('co2'),
                outdoor_temp=outdoor.get('temp'),
                outdoor_humidity=outdoor.get('humidity'),
                window_state=window_state
            )
            logger.info(f"{state_label} Ventilation started: {device_name} in {room_name} "
                       f"(Temp: {room_climate.get('temp')}°C, CO2: {room_climate.get('co2')} ppm)")
        except Exception as e:
            logger.error(f"Error starting ventilation event: {e}")

    def _end_ventilation_event(self, device_id: str, room_name: str):
        """Beendet ein Lüftungs-Event"""
        try:
            # Hole aktuelle Klimadaten
            room_climate = self._get_room_climate(room_name) if room_name else {}
            
            event_id = self.db.end_ventilation_event(
                device_id=device_id,
                temp_end=room_climate.get('temp'),
                humidity_end=room_climate.get('humidity'),
                co2_end=room_climate.get('co2')
            )
            if event_id:
                logger.info(f"🪟 Ventilation ended: {room_name} "
                           f"(Temp: {room_climate.get('temp')}°C, CO2: {room_climate.get('co2')} ppm)")
        except Exception as e:
            logger.error(f"Error ending ventilation event: {e}")

    def get_status(self) -> dict:
        """Gibt den aktuellen Status des Collectors zurück"""
        return {
            'running': self.running,
            'interval_seconds': self.interval_seconds,
            'last_collection': self.last_collection.isoformat() if self.last_collection else None,
            'tracked_windows': len(self._previous_window_states),
            'active_ventilations': len(self.db.get_active_ventilations())
        }

