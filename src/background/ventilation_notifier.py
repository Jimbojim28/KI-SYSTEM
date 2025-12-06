"""
Ventilation Notifier - Sendet Benachrichtigungen bei Lüftungs-Ereignissen

Überwacht:
- CO2 zu hoch (konfigurierbar)
- Luftfeuchtigkeit zu hoch (konfigurierbar)
- Lüftung abgeschlossen (optional)
- Frostwarnung bei offenen Fenstern
- Schimmelgefahr
"""

import threading
import time
from datetime import datetime, timedelta
from typing import Dict, Optional
from pathlib import Path
import yaml
import requests
from loguru import logger


class VentilationNotifier:
    """Sendet Pushover-Benachrichtigungen für Lüftungs-Ereignisse"""

    def __init__(self, engine=None, check_interval: int = 60):
        """
        Args:
            engine: DecisionEngine Instanz
            check_interval: Prüf-Intervall in Sekunden (default: 60)
        """
        self.engine = engine
        self.check_interval = check_interval
        self.running = False
        self.thread = None
        
        # Cooldown: Verhindert zu viele Benachrichtigungen
        self._last_notifications: Dict[str, datetime] = {}
        self._cooldown_minutes = 30  # Mindestens 30 Min zwischen gleichen Benachrichtigungen
        
        # Tracke offene Fenster und deren Öffnungszeit
        self._open_windows: Dict[str, datetime] = {}  # device_id -> opened_at
        
        # Anwesenheits-Tracking
        self._presence_home: bool = True
        self._away_since: Optional[datetime] = None
        
        logger.info(f"Ventilation Notifier initialized ({check_interval}s interval)")

    def _load_config(self) -> dict:
        """Lade Benachrichtigungs-Konfiguration mit Defaults für fehlende Optionen"""
        # Standard-Konfiguration (wird für fehlende Optionen verwendet)
        defaults = {
            'enabled': False,
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
        }
        
        config_path = Path('config/config.yaml')
        if config_path.exists():
            with open(config_path, 'r') as f:
                full_config = yaml.safe_load(f) or {}
                user_config = full_config.get('ventilation_notifications', {})
                
                # Merge: User-Config überschreibt Defaults
                merged = defaults.copy()
                merged.update(user_config)
                return merged
        
        return defaults

    def _get_pushover_credentials(self) -> tuple:
        """Hole Pushover-Credentials"""
        config_path = Path('config/config.yaml')
        if config_path.exists():
            with open(config_path, 'r') as f:
                full_config = yaml.safe_load(f) or {}
                
                # Versuche verschiedene Quellen
                notifications = full_config.get('notifications', {})
                pushover = notifications.get('pushover', {})
                api_key = pushover.get('api_token', '')
                user_key = pushover.get('user_key', '')
                
                # Fallback: absence config
                if not api_key or not user_key:
                    absence = full_config.get('absence', {})
                    if not api_key:
                        api_key = absence.get('pushover_api_key', '')
                    if not user_key:
                        user_key = absence.get('pushover_user_key', '')
                
                return api_key, user_key
        return '', ''

    def _send_notification(self, title: str, message: str, priority: int = 0, 
                          notification_key: str = None) -> bool:
        """Sende Pushover-Benachrichtigung mit Cooldown"""
        
        # Prüfe Cooldown
        if notification_key:
            last_sent = self._last_notifications.get(notification_key)
            if last_sent and datetime.now() - last_sent < timedelta(minutes=self._cooldown_minutes):
                logger.debug(f"Notification skipped (cooldown): {notification_key}")
                return False
        
        api_key, user_key = self._get_pushover_credentials()
        if not api_key or not user_key:
            logger.debug("Pushover credentials not configured")
            return False
        
        try:
            response = requests.post(
                'https://api.pushover.net/1/messages.json',
                data={
                    'token': api_key,
                    'user': user_key,
                    'title': title,
                    'message': message,
                    'html': 1,
                    'priority': priority
                },
                timeout=30
            )
            
            if response.status_code == 200:
                logger.info(f"Ventilation notification sent: {title}")
                if notification_key:
                    self._last_notifications[notification_key] = datetime.now()
                return True
            else:
                logger.error(f"Pushover error: {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"Error sending notification: {e}")
            return False

    def start(self):
        """Startet die kontinuierliche Überwachung"""
        if self.running:
            logger.warning("Ventilation Notifier is already running")
            return

        self.running = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        logger.info(f"Ventilation Notifier started (checks every {self.check_interval}s)")

    def stop(self):
        """Stoppt die Überwachung"""
        if not self.running:
            return

        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
        logger.info("Ventilation Notifier stopped")

    def _run(self):
        """Haupt-Loop für kontinuierliche Überwachung"""
        while self.running:
            try:
                config = self._load_config()
                if config.get('enabled'):
                    self._check_conditions(config)
            except Exception as e:
                logger.error(f"Error in ventilation notification check: {e}")
            
            time.sleep(self.check_interval)

    def _check_conditions(self, config: dict):
        """Prüft alle Benachrichtigungs-Bedingungen"""
        if not self.engine or not self.engine.platform:
            return
        
        try:
            # Hole aktuelle Daten
            room_data = self._get_room_climate_data()
            outdoor_temp = self._get_outdoor_temp()
            open_windows = self._get_open_windows()
            
            # Update tracked windows
            current_open = set(w['device_id'] for w in open_windows)
            
            # Neue offene Fenster - mit Benachrichtigung
            new_windows = []
            for window in open_windows:
                if window['device_id'] not in self._open_windows:
                    self._open_windows[window['device_id']] = datetime.now()
                    new_windows.append(window)
            
            # === Fenster wurde geöffnet ===
            if config.get('window_opened_alert', True) and new_windows:
                for window in new_windows:
                    room_name = window.get('room', 'Unbekannt')
                    room_climate = room_data.get(room_name, {})
                    
                    # Berechne empfohlene Lüftungsdauer
                    duration = self._calculate_ventilation_duration(
                        outdoor_temp=outdoor_temp,
                        indoor_temp=room_climate.get('temp'),
                        humidity=room_climate.get('humidity'),
                        co2=room_climate.get('co2')
                    )
                    
                    # Baue Nachrichtentext
                    message_parts = [f'🪟 <b>{window["name"]}</b> wurde geöffnet']
                    
                    # Zeige Raum-Klimadaten wenn verfügbar
                    climate_info = []
                    if room_climate.get('temp'):
                        climate_info.append(f"🌡️ {room_climate['temp']:.1f}°C")
                    if room_climate.get('humidity'):
                        climate_info.append(f"💧 {room_climate['humidity']:.0f}%")
                    if room_climate.get('co2'):
                        climate_info.append(f"💨 {room_climate['co2']:.0f} ppm")
                    
                    if climate_info:
                        message_parts.append(f"\n<b>{room_name}:</b> " + ' | '.join(climate_info))
                    
                    if outdoor_temp is not None:
                        message_parts.append(f"\n🌤️ Außen: {outdoor_temp:.1f}°C")
                    
                    # Lüftungsempfehlung
                    message_parts.append(f"\n\n⏱️ <b>Empfohlen:</b> {duration['text']}")
                    if duration.get('reason'):
                        message_parts.append(f"\n💡 {duration['reason']}")
                    
                    self._send_notification(
                        '🪟 Fenster geöffnet',
                        ''.join(message_parts),
                        notification_key=f'window_opened_{window["device_id"]}'
                    )
            
            # Geschlossene Fenster entfernen
            closed = set(self._open_windows.keys()) - current_open
            for device_id in closed:
                del self._open_windows[device_id]
            
            # === CO2 zu hoch ===
            if config.get('co2_high_alert'):
                threshold = config.get('co2_threshold', 1000)
                for room, data in room_data.items():
                    co2 = data.get('co2')
                    if co2 and co2 >= threshold:
                        self._send_notification(
                            '💨 CO₂ zu hoch!',
                            f'<b>{room}:</b> CO₂ bei <b>{co2:.0f} ppm</b>\n\n'
                            f'🪟 Bitte Fenster öffnen für bessere Luftqualität.',
                            notification_key=f'co2_high_{room}'
                        )
            
            # === Luftfeuchtigkeit zu hoch ===
            if config.get('humidity_high_alert'):
                threshold = config.get('humidity_threshold', 70)
                for room, data in room_data.items():
                    humidity = data.get('humidity')
                    if humidity and humidity >= threshold:
                        self._send_notification(
                            '💧 Hohe Luftfeuchtigkeit!',
                            f'<b>{room}:</b> Luftfeuchtigkeit bei <b>{humidity:.0f}%</b>\n\n'
                            f'🪟 Lüften empfohlen um Schimmelbildung zu vermeiden.',
                            notification_key=f'humidity_high_{room}'
                        )
            
            # === Frostwarnung ===
            if config.get('frost_warning') and outdoor_temp is not None:
                frost_threshold = config.get('frost_threshold', 2)
                if outdoor_temp < frost_threshold:
                    for window in open_windows:
                        device_id = window['device_id']
                        opened_at = self._open_windows.get(device_id)
                        if opened_at:
                            minutes_open = (datetime.now() - opened_at).total_seconds() / 60
                            if minutes_open >= 10:  # Mind. 10 Min offen
                                self._send_notification(
                                    '❄️ Frostwarnung!',
                                    f'<b>Außentemperatur: {outdoor_temp:.1f}°C</b>\n\n'
                                    f'🪟 <b>{window["name"]}</b> ist seit {minutes_open:.0f} Min. offen.\n\n'
                                    f'⚠️ Bitte Fenster schließen um Heizkosten zu sparen.',
                                    priority=1,
                                    notification_key=f'frost_{device_id}'
                                )
            
            # === Schimmelgefahr ===
            if config.get('mold_warning'):
                for room, data in room_data.items():
                    humidity = data.get('humidity')
                    temp = data.get('temp')
                    if humidity and temp:
                        # Schimmelgefahr: hohe Feuchtigkeit + niedrige Temperatur
                        if humidity >= 75 and temp <= 18:
                            self._send_notification(
                                '⚠️ Schimmelgefahr!',
                                f'<b>{room}:</b>\n'
                                f'💧 Luftfeuchtigkeit: {humidity:.0f}%\n'
                                f'🌡️ Temperatur: {temp:.1f}°C\n\n'
                                f'🔴 Kritische Bedingungen für Schimmelbildung!\n'
                                f'🪟 Dringend lüften empfohlen.',
                                priority=1,
                                notification_key=f'mold_{room}'
                            )
            
            # === Fenster offen bei Abwesenheit ===
            if config.get('window_away_alert', True):
                presence_home = self._check_presence()
                self._update_presence(presence_home)
                
                if not presence_home and open_windows:
                    # Prüfe wie lange niemand zuhause ist
                    away_minutes = 0
                    if self._away_since:
                        away_minutes = (datetime.now() - self._away_since).total_seconds() / 60
                    
                    # Nur warnen wenn mind. 5 Min. weg
                    if away_minutes >= 5:
                        for window in open_windows:
                            device_id = window['device_id']
                            opened_at = self._open_windows.get(device_id)
                            minutes_open = 0
                            if opened_at:
                                minutes_open = (datetime.now() - opened_at).total_seconds() / 60
                            
                            room_name = window.get('room', 'Unbekannt')
                            
                            # Warnung senden
                            message = (
                                f'🪟 <b>{window["name"]}</b> ist offen!\n\n'
                                f'🏠 <b>Niemand zuhause</b> seit {int(away_minutes)} Min.\n'
                                f'⏱️ Fenster offen seit: {int(minutes_open)} Min.'
                            )
                            
                            # Bei Kälte zusätzliche Warnung
                            if outdoor_temp is not None and outdoor_temp < 10:
                                message += f'\n\n❄️ Außentemperatur: {outdoor_temp:.1f}°C\n⚠️ Heizkosten steigen!'
                            
                            self._send_notification(
                                '🚨 Fenster offen - Niemand zuhause!',
                                message,
                                priority=1,
                                notification_key=f'window_away_{device_id}'
                            )
            
        except Exception as e:
            logger.error(f"Error checking ventilation conditions: {e}")

    def _check_presence(self) -> bool:
        """Prüft ob jemand zuhause ist"""
        try:
            if hasattr(self.engine.platform, '_device_cache'):
                devices = list(self.engine.platform._device_cache.values()) if isinstance(
                    self.engine.platform._device_cache, dict) else self.engine.platform._device_cache
            else:
                devices = self.engine.platform.get_states() or []
            
            for device in devices:
                if not isinstance(device, dict):
                    continue
                
                name = device.get('name', '').lower()
                caps = device.get('capabilitiesObj', {})
                
                # Prüfe Anwesenheits-Sensoren
                if any(kw in name for kw in ['presence', 'anwesen', 'zuhause', 'home', 'person']):
                    if 'homealarm_state' in caps:
                        state = caps['homealarm_state'].get('value', '')
                        # "armed" = niemand zuhause, "disarmed" = jemand zuhause
                        if state == 'disarmed':
                            return True
                    if 'onoff' in caps:
                        if caps['onoff'].get('value'):
                            return True
                
                # Prüfe ob Smartphone zuhause
                if 'phone' in name or 'handy' in name or 'iphone' in name:
                    if 'onoff' in caps and caps['onoff'].get('value'):
                        return True
                        
        except Exception as e:
            logger.debug(f"Error checking presence: {e}")
        
        # Fallback: annehmen jemand ist zuhause
        return True
    
    def _update_presence(self, presence_home: bool):
        """Aktualisiert das Anwesenheits-Tracking"""
        if not presence_home:
            # Niemand zu Hause
            if self._away_since is None:
                self._away_since = datetime.now()
                logger.info("🏠 Niemand mehr zu Hause - Fenster-Tracking aktiviert")
            self._presence_home = False
        else:
            # Jemand ist zu Hause
            if self._away_since is not None:
                away_duration = (datetime.now() - self._away_since).total_seconds() / 60
                logger.debug(f"🏠 Jemand ist wieder zu Hause (war {int(away_duration)} Min. weg)")
            self._away_since = None
            self._presence_home = True

    def _get_room_climate_data(self) -> Dict[str, Dict]:
        """Holt Klimadaten für alle Räume"""
        rooms = {}
        
        try:
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
            
            for device in devices:
                if not isinstance(device, dict):
                    continue
                
                zone_id = device.get('zone')
                room_name = zones.get(zone_id)
                if not room_name:
                    continue
                
                caps = device.get('capabilitiesObj', {})
                
                if room_name not in rooms:
                    rooms[room_name] = {}
                
                # Temperatur
                if 'measure_temperature' in caps:
                    val = caps['measure_temperature'].get('value')
                    if val is not None and -40 < val < 60:
                        rooms[room_name]['temp'] = val
                
                # Luftfeuchtigkeit
                if 'measure_humidity' in caps:
                    val = caps['measure_humidity'].get('value')
                    if val is not None and 0 <= val <= 100:
                        rooms[room_name]['humidity'] = val
                
                # CO2
                if 'measure_co2' in caps:
                    val = caps['measure_co2'].get('value')
                    if val is not None and 200 < val < 10000:
                        rooms[room_name]['co2'] = val
                        
        except Exception as e:
            logger.error(f"Error getting room climate data: {e}")
        
        return rooms

    def _get_outdoor_temp(self) -> Optional[float]:
        """Holt Außentemperatur"""
        try:
            if hasattr(self.engine.platform, '_device_cache'):
                devices = list(self.engine.platform._device_cache.values()) if isinstance(
                    self.engine.platform._device_cache, dict) else self.engine.platform._device_cache
            else:
                devices = self.engine.platform.get_states() or []
            
            for device in devices:
                if not isinstance(device, dict):
                    continue
                name = device.get('name', '').lower()
                if any(kw in name for kw in ['außen', 'outdoor', 'aussen', 'garten', 'balkon']):
                    caps = device.get('capabilitiesObj', {})
                    if 'measure_temperature' in caps:
                        return caps['measure_temperature'].get('value')
        except:
            pass
        return None

    def _get_open_windows(self) -> list:
        """Holt alle offenen Fenster"""
        windows = []
        
        try:
            if hasattr(self.engine.platform, '_device_cache'):
                devices = list(self.engine.platform._device_cache.values()) if isinstance(
                    self.engine.platform._device_cache, dict) else self.engine.platform._device_cache
            else:
                devices = self.engine.platform.get_states() or []
            
            # Hole Zone-Mapping für Raum-Namen
            zones = {}
            try:
                zone_list = self.engine.platform.get_zones() or []
                zones = {z.get('id'): z.get('name') for z in zone_list}
            except:
                pass
            
            for device in devices:
                if not isinstance(device, dict):
                    continue
                
                name = device.get('name', '').lower()
                
                # Nur Fenster, keine Türen
                is_door = any(kw in name for kw in ['door', 'tür', 'tur', 'türe'])
                is_window = any(kw in name for kw in ['window', 'fenster'])
                
                if is_door or not is_window:
                    continue
                
                caps = device.get('capabilitiesObj', {})
                if 'alarm_contact' in caps:
                    is_open = caps['alarm_contact'].get('value', False)
                    if is_open:
                        # Hole Raum-Namen aus Zone
                        zone_id = device.get('zone')
                        room_name = zones.get(zone_id, 'Unbekannt')
                        
                        windows.append({
                            'device_id': device.get('id'),
                            'name': device.get('name', 'Unbekannt'),
                            'room': room_name
                        })
                        
        except Exception as e:
            logger.error(f"Error getting open windows: {e}")
        
        return windows

    def _calculate_ventilation_duration(self, outdoor_temp: float = None, 
                                        indoor_temp: float = None,
                                        humidity: float = None, 
                                        co2: float = None) -> dict:
        """Berechnet die empfohlene Lüftungsdauer basierend auf den Bedingungen"""
        
        # Standardwerte
        min_duration = 5
        max_duration = 15
        reason = None
        
        # Außentemperatur-basierte Anpassung
        if outdoor_temp is not None:
            if outdoor_temp < 0:
                min_duration = 3
                max_duration = 5
                reason = "Sehr kalt - kurzes Stoßlüften reicht"
            elif outdoor_temp < 5:
                min_duration = 5
                max_duration = 8
                reason = "Kalt - nicht zu lange lüften"
            elif outdoor_temp < 15:
                min_duration = 8
                max_duration = 15
                reason = "Gute Lüftungsbedingungen"
            elif outdoor_temp < 25:
                min_duration = 10
                max_duration = 20
                reason = "Angenehme Außentemperatur"
            else:
                min_duration = 5
                max_duration = 10
                reason = "Heiß - morgens/abends länger lüften"
        
        # CO2-basierte Anpassung
        if co2 is not None:
            if co2 > 2000:
                min_duration = max(min_duration, 15)
                max_duration = max(max_duration, 25)
                reason = "CO₂ sehr hoch - ausgiebig lüften!"
            elif co2 > 1400:
                min_duration = max(min_duration, 10)
                max_duration = max(max_duration, 20)
                reason = "CO₂ erhöht - gründlich lüften"
            elif co2 > 1000:
                min_duration = max(min_duration, 8)
                max_duration = max(max_duration, 15)
        
        # Luftfeuchtigkeit-basierte Anpassung
        if humidity is not None:
            if humidity > 75:
                min_duration = max(min_duration, 10)
                max_duration = max(max_duration, 20)
                if not reason or 'CO₂' not in reason:
                    reason = "Hohe Feuchtigkeit - länger lüften"
            elif humidity > 65:
                min_duration = max(min_duration, 8)
        
        # Erstelle Text
        if min_duration == max_duration:
            duration_text = f"ca. {min_duration} Minuten"
        else:
            duration_text = f"{min_duration}-{max_duration} Minuten"
        
        return {
            'min_minutes': min_duration,
            'max_minutes': max_duration,
            'text': duration_text,
            'reason': reason
        }

    def get_status(self) -> dict:
        """Gibt den aktuellen Status zurück"""
        config = self._load_config()
        return {
            'running': self.running,
            'enabled': config.get('enabled', False),
            'check_interval': self.check_interval,
            'open_windows_tracked': len(self._open_windows),
            'notifications_sent': len(self._last_notifications)
        }
