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
from datetime import datetime
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

        logger.info(f"Window Data Collector initialized ({interval_seconds}s interval)")

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
        """Holt aktuelle Klimadaten für einen Raum"""
        climate = {'temp': None, 'humidity': None, 'co2': None}
        
        if not room_name or not self.engine or not self.engine.platform:
            return climate
            
        try:
            # Hole alle Geräte
            if hasattr(self.engine.platform, '_device_cache'):
                self.engine.platform._refresh_device_cache()
                devices = list(self.engine.platform._device_cache.values()) if isinstance(
                    self.engine.platform._device_cache, dict) else self.engine.platform._device_cache
            else:
                devices = self.engine.platform.get_states() or []
            
            # Hole Zone-Mapping
            zones = {}
            try:
                zone_list = self.engine.platform.get_zones() or []
                zones = {z.get('id'): z.get('name') for z in zone_list}
            except:
                pass
            
            room_lower = room_name.lower()
            
            # Suche Sensoren im Raum (mehrere Matching-Strategien)
            for device in devices:
                if not isinstance(device, dict):
                    continue
                
                # Strategie 1: Zone-Name stimmt überein
                zone_id = device.get('zone')
                device_room = zones.get(zone_id, '').lower()
                
                # Strategie 2: Gerätename enthält Raumnamen
                device_name = device.get('name', '').lower()
                
                # Prüfe ob das Gerät zum Raum passt
                room_match = (
                    room_lower in device_room or 
                    device_room in room_lower or
                    room_lower in device_name
                )
                
                if not room_match:
                    continue
                    
                caps = device.get('capabilitiesObj', {})
                
                # Temperatur
                if climate['temp'] is None and 'measure_temperature' in caps:
                    val = caps['measure_temperature'].get('value')
                    if val is not None and -40 < val < 60:  # Plausibilitätsprüfung
                        climate['temp'] = val
                
                # Luftfeuchtigkeit
                if climate['humidity'] is None and 'measure_humidity' in caps:
                    val = caps['measure_humidity'].get('value')
                    if val is not None and 0 <= val <= 100:
                        climate['humidity'] = val
                
                # CO2 - nur verwenden wenn das Gerät WIRKLICH in diesem Raum ist
                # CO2-Sensoren sind selten, daher strengeres Matching
                if climate['co2'] is None and 'measure_co2' in caps:
                    # Raum-Match: Zone enthält Raumnamen ODER Raum enthält Zone-Namen
                    # z.B. "schlafzimmer" matches "schlafzimmer (doppelbett)"
                    co2_room_match = (
                        device_room == room_lower or  # Exaktes Zone-Match
                        room_lower in device_room or  # Raum ist Teil der Zone (z.B. "schlafzimmer" in "schlafzimmer (doppelbett)")
                        device_room in room_lower or  # Zone ist Teil des Raums
                        (room_lower in device_name and 'co2' in device_name.lower())  # CO2-Monitor mit Raumnamen
                    )
                    if co2_room_match:
                        val = caps['measure_co2'].get('value')
                        if val is not None and 200 < val < 10000:  # Plausibilitätsprüfung
                            climate['co2'] = val
            
            # Wenn CO2 noch nicht gefunden, suche nach CO2-Sensor mit passendem Namen
            if climate['co2'] is None:
                for device in devices:
                    if not isinstance(device, dict):
                        continue
                    device_name = device.get('name', '').lower()
                    caps = device.get('capabilitiesObj', {})
                    
                    # Suche nach CO2-Monitor der zum Raum passt
                    if 'co2' in device_name and room_lower in device_name:
                        if 'measure_co2' in caps:
                            val = caps['measure_co2'].get('value')
                            if val is not None and 200 < val < 10000:
                                climate['co2'] = val
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
        if not self.engine or not self.engine.platform:
            logger.debug("No engine/platform available for window data collection")
            return

        try:
            # Hole alle Geräte direkt aus dem Cache
            all_devices = []
            
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
            
            if not all_devices:
                logger.debug("No devices found for window data collection")
                return
                
            window_devices = []

            # Filtere nur nach Fenstern (KEINE Türen)
            for device in all_devices:
                # Skip wenn device kein Dictionary ist
                if not isinstance(device, dict):
                    continue

                device_class = device.get('class', '').lower()
                device_name = device.get('name', '').lower()
                capabilities = device.get('capabilitiesObj', {})

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

        # Status: offen oder geschlossen
        is_open = False
        contact_alarm = False

        # Prüfe alarm_contact capability (typisch für Fenster/Tür-Sensoren)
        if 'alarm_contact' in capabilities:
            # alarm_contact: true = offen, false = geschlossen
            alarm_value = capabilities['alarm_contact'].get('value')
            if alarm_value is not None:
                is_open = bool(alarm_value)
                contact_alarm = is_open

        # Alternative: windowcoverings_state (für Rollläden/Jalousien)
        elif 'windowcoverings_state' in capabilities:
            state = capabilities['windowcoverings_state'].get('value', 'idle')
            is_open = (state == 'up')  # up = offen

        # Alternative: onoff (für manche Sensoren)
        elif 'onoff' in capabilities:
            is_open = capabilities['onoff'].get('value', False)

        # Raum-Name aus Zone
        room_name = None
        zone_id = device.get('zone')
        if zone_id and hasattr(self.engine, 'platform'):
            try:
                zones = self.engine.platform.get_zones()
                for zone in zones:
                    if zone.get('id') == zone_id:
                        room_name = zone.get('name')
                        break
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
            contact_alarm=contact_alarm
        )

        # === Lüftungs-Event-Tracking ===
        # Prüfe ob sich der Status geändert hat
        previous_state = self._previous_window_states.get(device_id)
        
        if previous_state is not None and previous_state != is_open:
            # Status hat sich geändert
            if is_open:
                # Fenster wurde geöffnet -> Starte Lüftungs-Event
                self._start_ventilation_event(device_id, device_name, room_name)
            else:
                # Fenster wurde geschlossen -> Beende Lüftungs-Event
                self._end_ventilation_event(device_id, room_name)
        
        elif previous_state is None and is_open:
            # Erstes Mal gesehen und offen -> Starte Event
            self._start_ventilation_event(device_id, device_name, room_name)
        
        # Speichere aktuellen Status
        self._previous_window_states[device_id] = is_open

        return observation_id

    def _start_ventilation_event(self, device_id: str, device_name: str, room_name: str):
        """Startet ein Lüftungs-Event"""
        try:
            # Hole aktuelle Klimadaten
            room_climate = self._get_room_climate(room_name) if room_name else {}
            outdoor = self._get_outdoor_climate()
            
            self.db.start_ventilation_event(
                device_id=device_id,
                device_name=device_name,
                room_name=room_name,
                temp_start=room_climate.get('temp'),
                humidity_start=room_climate.get('humidity'),
                co2_start=room_climate.get('co2'),
                outdoor_temp=outdoor.get('temp'),
                outdoor_humidity=outdoor.get('humidity')
            )
            logger.info(f"🪟 Ventilation started: {device_name} in {room_name} "
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

