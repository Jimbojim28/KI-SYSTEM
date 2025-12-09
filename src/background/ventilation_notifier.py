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
from typing import Any, Dict, Optional, TYPE_CHECKING
from pathlib import Path

if TYPE_CHECKING:
    from src.decision_engine.engine import DecisionEngine
import yaml
import requests
from loguru import logger

from src.utils.config_manager import get_config_section


class VentilationNotifier:
    """Sendet Pushover-Benachrichtigungen für Lüftungs-Ereignisse"""

    def __init__(self, engine: Optional["DecisionEngine"] = None, check_interval: int = 60):
        """
        Args:
            engine: DecisionEngine Instanz
            check_interval: Prüf-Intervall in Sekunden (default: 60)
        """
        self.engine: Optional["DecisionEngine"] = engine
        self.check_interval = check_interval
        self.running = False
        self.thread = None
        
        # Cooldown: Verhindert zu viele Benachrichtigungen
        self._last_notifications: Dict[str, datetime] = {}
        self._cooldown_minutes = 30  # Mindestens 30 Min zwischen gleichen Benachrichtigungen
        
        # Tracke offene Fenster und deren Öffnungszeit
        self._open_windows: Dict[str, dict] = {}  # device_id -> {opened_at, room, name, climate_start}
        
        # Anwesenheits-Tracking
        self._presence_home: bool = True
        self._away_since: Optional[datetime] = None
        
        logger.info(f"Ventilation Notifier initialized ({check_interval}s interval)")

    @property
    def _platform(self) -> Any:
        """Sicherer Zugriff auf die Plattform (vermeidet Type-Checker Warnungen)"""
        if self.engine and self.engine.platform:
            return self.engine.platform
        return None

    def _load_config(self) -> dict:
        """Lade Benachrichtigungs-Konfiguration mit Defaults für fehlende Optionen"""
        return get_config_section('ventilation_notifications')

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
                          notification_key: Optional[str] = None) -> bool:
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
                else:
                    logger.debug("Ventilation notifications disabled in config")
            except Exception as e:
                logger.error(f"Error in ventilation notification check: {e}")
            
            time.sleep(self.check_interval)

    def _check_conditions(self, config: dict):
        """Prüft alle Benachrichtigungs-Bedingungen"""
        if not self.engine or not self.engine.platform:
            logger.debug("No engine/platform available for ventilation check")
            return
        
        try:
            # Hole aktuelle Daten
            room_data = self._get_room_climate_data()
            outdoor_temp = self._get_outdoor_temp()
            open_windows = self._get_open_windows()
            
            logger.debug(f"Ventilation check: {len(open_windows)} open windows found")
            for w in open_windows:
                logger.debug(f"  - {w['name']} ({w['room']}): state={w.get('state')}, tilt={w.get('tilt')}")
            
            # Update tracked windows
            current_open = set(w['device_id'] for w in open_windows)
            
            # Debug: Zeige verfügbare Klimadaten
            if room_data:
                logger.debug(f"Room climate data available for: {list(room_data.keys())}")
            else:
                logger.debug("No room climate data available")
            
            # Neue offene Fenster - mit Benachrichtigung
            new_windows = []
            for window in open_windows:
                if window['device_id'] not in self._open_windows:
                    room_name = window.get('room', 'Unbekannt')
                    room_climate = room_data.get(room_name, {})
                    
                    # Fallback: Versuche Raumnamen-Varianten
                    if not room_climate:
                        for key in room_data.keys():
                            if key.lower() == room_name.lower() or room_name.lower() in key.lower():
                                room_climate = room_data[key]
                                logger.debug(f"Found climate data for {room_name} via fallback key: {key}")
                                break
                    
                    logger.debug(f"Window {window.get('name')} in {room_name}: climate={room_climate}")
                    
                    # Speichere Fensterdaten inkl. Klima-Startwerte
                    self._open_windows[window['device_id']] = {
                        'opened_at': datetime.now(),
                        'room': room_name,
                        'name': window.get('name', 'Unbekannt'),
                        'climate_start': {
                            'temp': room_climate.get('temp'),
                            'humidity': room_climate.get('humidity'),
                            'co2': room_climate.get('co2'),
                            'outdoor_temp': outdoor_temp
                        }
                    }
                    new_windows.append(window)
            
            # === Fenster wurde geöffnet ===
            if config.get('window_opened_alert', True) and new_windows:
                for window in new_windows:
                    room_name = window.get('room', 'Unbekannt')
                    room_climate = room_data.get(room_name, {})
                    window_state = window.get('state', 'open')
                    
                    # Berechne empfohlene Lüftungsdauer
                    duration = self._calculate_ventilation_duration(
                        outdoor_temp=outdoor_temp,
                        indoor_temp=room_climate.get('temp'),
                        humidity=room_climate.get('humidity'),
                        co2=room_climate.get('co2')
                    )
                    
                    # Baue Nachrichtentext mit Zustand (gekippt/offen)
                    state_emoji = '📐' if window_state == 'tilted' else '🪟'
                    state_text = 'gekippt' if window_state == 'tilted' else 'geöffnet'
                    message_parts = [f'{state_emoji} <b>{window["name"]}</b> wurde {state_text}']
                    
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
                    
                    title = '📐 Fenster gekippt' if window_state == 'tilted' else '🪟 Fenster geöffnet'
                    self._send_notification(
                        title,
                        ''.join(message_parts),
                        notification_key=f'window_opened_{window["device_id"]}'
                    )
            
            # === Fenster wurde geschlossen - Benachrichtigung mit Dauer und Effektivität ===
            closed = set(self._open_windows.keys()) - current_open
            
            # Debug: Zeige Tracking-Status
            logger.debug(f"Tracking {len(self._open_windows)} windows, {len(closed)} just closed")
            if closed:
                logger.info(f"Windows closed: {closed}")
            
            if config.get('window_closed_alert', True) and closed:
                for device_id in closed:
                    window_info = self._open_windows.get(device_id, {})
                    opened_at = window_info.get('opened_at')
                    window_name = window_info.get('name', 'Fenster')
                    room_name = window_info.get('room', 'Unbekannt')
                    climate_start = window_info.get('climate_start', {})
                    
                    # Berechne Dauer
                    if opened_at:
                        duration_seconds = (datetime.now() - opened_at).total_seconds()
                        duration_minutes = int(duration_seconds / 60)
                    else:
                        duration_minutes = 0
                    
                    # Formatiere Dauer
                    if duration_minutes >= 60:
                        hours = duration_minutes // 60
                        mins = duration_minutes % 60
                        duration_text = f"{hours}h {mins}min" if mins > 0 else f"{hours}h"
                    else:
                        duration_text = f"{duration_minutes} Minuten"
                    
                    # Hole aktuelle Klimadaten für Vergleich
                    room_climate_now = room_data.get(room_name, {})
                    
                    # Fallback: Versuche Raumnamen-Varianten
                    if not room_climate_now:
                        for key in room_data.keys():
                            if key.lower() == room_name.lower() or room_name.lower() in key.lower():
                                room_climate_now = room_data[key]
                                break
                    
                    logger.debug(f"Window closed - {window_name}: climate_start={climate_start}, climate_now={room_climate_now}")
                    
                    # Berechne Effektivität
                    effectiveness = self._calculate_ventilation_effectiveness(
                        climate_start, room_climate_now, duration_minutes
                    )
                    
                    # Baue Nachrichtentext
                    message_parts = [f'✅ <b>{window_name}</b> geschlossen']
                    message_parts.append(f'\n\n⏱️ <b>Lüftungsdauer:</b> {duration_text}')
                    
                    # Zeige Klima-Veränderungen (wenn Vorher/Nachher verfügbar)
                    changes = []
                    has_start_data = climate_start.get('temp') or climate_start.get('humidity') or climate_start.get('co2')
                    has_now_data = room_climate_now.get('temp') or room_climate_now.get('humidity') or room_climate_now.get('co2')
                    
                    if has_start_data and has_now_data:
                        # Vollständiger Vergleich
                        if climate_start.get('temp') and room_climate_now.get('temp'):
                            temp_diff = room_climate_now['temp'] - climate_start['temp']
                            arrow = '↓' if temp_diff < 0 else '↑' if temp_diff > 0 else '→'
                            changes.append(f"🌡️ {climate_start['temp']:.1f}→{room_climate_now['temp']:.1f}°C ({arrow}{abs(temp_diff):.1f}°)")
                        
                        if climate_start.get('humidity') and room_climate_now.get('humidity'):
                            hum_diff = room_climate_now['humidity'] - climate_start['humidity']
                            arrow = '↓' if hum_diff < 0 else '↑' if hum_diff > 0 else '→'
                            changes.append(f"💧 {climate_start['humidity']:.0f}→{room_climate_now['humidity']:.0f}% ({arrow}{abs(hum_diff):.0f}%)")
                        
                        if climate_start.get('co2') and room_climate_now.get('co2'):
                            co2_diff = room_climate_now['co2'] - climate_start['co2']
                            arrow = '↓' if co2_diff < 0 else '↑' if co2_diff > 0 else '→'
                            changes.append(f"💨 {climate_start['co2']:.0f}→{room_climate_now['co2']:.0f} ppm ({arrow}{abs(co2_diff):.0f})")
                        
                        if changes:
                            message_parts.append(f"\n\n<b>Veränderung ({room_name}):</b>\n" + '\n'.join(changes))
                    
                    elif has_now_data:
                        # Nur aktuelle Daten verfügbar
                        current_info = []
                        if room_climate_now.get('temp'):
                            current_info.append(f"🌡️ {room_climate_now['temp']:.1f}°C")
                        if room_climate_now.get('humidity'):
                            current_info.append(f"💧 {room_climate_now['humidity']:.0f}%")
                        if room_climate_now.get('co2'):
                            current_info.append(f"💨 {room_climate_now['co2']:.0f} ppm")
                        
                        if current_info:
                            message_parts.append(f"\n\n<b>Aktuell ({room_name}):</b>\n" + '\n'.join(current_info))
                    
                    else:
                        # Keine Sensordaten - zeige Außentemperatur wenn verfügbar
                        if outdoor_temp is not None:
                            message_parts.append(f"\n\n🌤️ Außentemperatur: {outdoor_temp:.1f}°C")
                        else:
                            message_parts.append(f"\n\n<i>Keine Sensordaten für {room_name} verfügbar</i>")
                    
                    # Effektivitäts-Bewertung
                    message_parts.append(f"\n\n{effectiveness['emoji']} <b>Effektivität:</b> {effectiveness['rating']}")
                    if effectiveness.get('comment'):
                        message_parts.append(f"\n{effectiveness['comment']}")
                    
                    self._send_notification(
                        '✅ Lüftung beendet',
                        ''.join(message_parts),
                        notification_key=f'window_closed_{device_id}'
                    )
            
            # Geschlossene Fenster aus Tracking entfernen
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
                        window_info = self._open_windows.get(device_id, {})
                        opened_at = window_info.get('opened_at') if isinstance(window_info, dict) else None
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
                            window_info = self._open_windows.get(device_id, {})
                            opened_at = window_info.get('opened_at') if isinstance(window_info, dict) else None
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
        platform = self._platform
        if not platform:
            return True  # Fallback: annehmen jemand ist zuhause
            
        try:
            if hasattr(platform, '_device_cache'):
                devices = list(platform._device_cache.values()) if isinstance(
                    platform._device_cache, dict) else platform._device_cache
            else:
                devices = platform.get_states() or []
            
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
        
        platform = self._platform
        if not platform:
            return rooms
        
        try:
            if hasattr(platform, '_device_cache'):
                platform._refresh_device_cache()
                devices = list(platform._device_cache.values()) if isinstance(
                    platform._device_cache, dict) else platform._device_cache
            else:
                devices = platform.get_states() or []
            
            # Hole Zone-Mapping
            zones = {}
            try:
                zone_list = platform.get_zones() or []
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
        platform = self._platform
        if not platform:
            return None
            
        try:
            if hasattr(platform, '_device_cache'):
                devices = list(platform._device_cache.values()) if isinstance(
                    platform._device_cache, dict) else platform._device_cache
            else:
                devices = platform.get_states() or []
            
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
        
        platform = self._platform
        if not platform:
            return windows
        
        try:
            # Wichtig: Cache refreshen um aktuelle Werte zu bekommen!
            if hasattr(platform, '_refresh_device_cache'):
                platform._refresh_device_cache()
            
            if hasattr(platform, '_device_cache'):
                devices = list(platform._device_cache.values()) if isinstance(
                    platform._device_cache, dict) else platform._device_cache
            else:
                devices = platform.get_states() or []
            
            # Hole Zone-Mapping für Raum-Namen
            zones = {}
            try:
                zone_list = platform.get_zones() or []
                zones = {z.get('id'): z.get('name') for z in zone_list}
            except:
                pass
            
            # Lade Kalibrierungsdaten aus rooms.json (wie bei /rooms)
            calibrations = {}
            try:
                rooms_file = Path('data/rooms.json')
                if rooms_file.exists():
                    import json
                    with open(rooms_file, 'r') as f:
                        rooms_data = json.load(f)
                    calibrations = rooms_data.get('window_calibration', {})
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
                    is_contact_open = caps['alarm_contact'].get('value', False)
                    if is_contact_open:
                        # Hole Raum-Namen aus Zone
                        zone_id = device.get('zone')
                        room_name = zones.get(zone_id, 'Unbekannt')
                        
                        # Ermittle Fensterzustand (gekippt vs offen) - gleiche Logik wie /rooms
                        window_state = 'open'  # Default
                        tilt_value = None
                        
                        # Prüfe ob Tilt-Sensor verfügbar (verschiedene mögliche Namen)
                        tilt_caps = ['tilt', 'windowcoverings_tilt_set', 'measure_tilt', 'tilt_angle']
                        for tilt_cap in tilt_caps:
                            if tilt_cap in caps:
                                tilt_value = caps[tilt_cap].get('value')
                                break
                        
                        if tilt_value is not None:
                            # Hole Kalibrierung für diese Zone
                            calibration = calibrations.get(zone_id, {
                                'closed_angle': 0,
                                'tilted_min': 5,
                                'tilted_max': 45
                            })
                            
                            closed_angle = calibration.get('closed_angle', 0)
                            tilted_min = calibration.get('tilted_min', 5)
                            tilted_max = calibration.get('tilted_max', 45)
                            
                            # Logik: Winkel im Kippbereich (5°-45°) = gekippt
                            diff = abs(tilt_value - closed_angle)
                            
                            logger.debug(f"Window {device.get('name')}: tilt={tilt_value}, diff={diff}, tilted_min={tilted_min}, tilted_max={tilted_max}")
                            
                            if diff >= tilted_min and diff <= tilted_max:
                                window_state = 'tilted'
                            else:
                                # Winkel nahe geschlossen (0°) oder sehr groß (>45°) = weit offen
                                window_state = 'open'
                        else:
                            logger.debug(f"Window {device.get('name')}: No tilt sensor, caps: {list(caps.keys())}")
                        
                        windows.append({
                            'device_id': device.get('id'),
                            'name': device.get('name', 'Unbekannt'),
                            'room': room_name,
                            'state': window_state,
                            'tilt': tilt_value
                        })
                        
        except Exception as e:
            logger.error(f"Error getting open windows: {e}")
        
        return windows

    def _calculate_ventilation_duration(self, outdoor_temp: Optional[float] = None, 
                                        indoor_temp: Optional[float] = None,
                                        humidity: Optional[float] = None, 
                                        co2: Optional[float] = None) -> dict:
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

    def _calculate_ventilation_effectiveness(self, climate_start: dict, 
                                             climate_now: dict, 
                                             duration_minutes: int) -> dict:
        """Berechnet die Effektivität der Lüftung basierend auf Klima-Veränderungen"""
        
        score = 0
        max_score = 0
        comments = []
        
        # CO2-Reduktion (wichtigster Faktor)
        co2_start = climate_start.get('co2')
        co2_now = climate_now.get('co2')
        if co2_start and co2_now:
            max_score += 40
            co2_reduction = co2_start - co2_now
            
            if co2_start > 1000:
                # Bei hohem CO2 - wie viel wurde reduziert?
                if co2_now < 800:
                    score += 40
                    comments.append("CO₂ deutlich gesenkt 👍")
                elif co2_reduction > 300:
                    score += 30
                elif co2_reduction > 150:
                    score += 20
                elif co2_reduction > 50:
                    score += 10
                else:
                    comments.append("CO₂ kaum verändert")
            else:
                # CO2 war schon OK
                if co2_now < 1000:
                    score += 35
                    comments.append("CO₂ blieb gut")
        
        # Luftfeuchtigkeit
        hum_start = climate_start.get('humidity')
        hum_now = climate_now.get('humidity')
        if hum_start and hum_now:
            max_score += 30
            hum_diff = hum_start - hum_now
            
            if hum_start > 65:
                # Bei hoher Feuchtigkeit - wurde sie gesenkt?
                if hum_now < 60:
                    score += 30
                    comments.append("Feuchtigkeit gesenkt 👍")
                elif hum_diff > 10:
                    score += 25
                elif hum_diff > 5:
                    score += 15
                elif hum_diff > 0:
                    score += 8
            elif hum_start < 40 and hum_now > hum_start:
                # Bei zu niedriger Feuchtigkeit - Erhöhung ist gut
                score += 25
                comments.append("Feuchtigkeit erhöht 👍")
            else:
                # Feuchtigkeit war OK
                if 40 <= hum_now <= 65:
                    score += 25
        
        # Temperatur (situationsabhängig)
        temp_start = climate_start.get('temp')
        temp_now = climate_now.get('temp')
        outdoor_temp = climate_start.get('outdoor_temp')
        if temp_start and temp_now:
            max_score += 30
            temp_diff = temp_now - temp_start
            
            # Im Winter sollte nicht zu viel auskühlen
            if outdoor_temp is not None and outdoor_temp < 10:
                if abs(temp_diff) < 2:
                    score += 30
                    comments.append("Temperatur stabil gehalten")
                elif abs(temp_diff) < 4:
                    score += 20
                else:
                    score += 5
                    comments.append("Raum stark abgekühlt")
            else:
                # Im Sommer ist Kühlung OK
                if temp_start > 24 and temp_diff < -1:
                    score += 30
                    comments.append("Raum erfrischt 👍")
                elif abs(temp_diff) < 3:
                    score += 25
                else:
                    score += 15
        
        # Dauer-Bewertung
        if duration_minutes < 3:
            comments.append("Sehr kurze Lüftung")
            score = int(score * 0.7)  # Abzug
        elif duration_minutes > 30 and outdoor_temp is not None and outdoor_temp < 5:
            comments.append("Lange Lüftung bei Kälte")
            score = int(score * 0.8)  # Abzug
        
        # Berechne Prozentsatz
        if max_score > 0:
            percentage = int((score / max_score) * 100)
        else:
            # Keine Sensordaten - bewerte nur anhand der Dauer
            if duration_minutes >= 5 and duration_minutes <= 15:
                percentage = 75
                comments.append("Gute Lüftungsdauer")
            elif duration_minutes >= 3 and duration_minutes <= 25:
                percentage = 60
                comments.append("Akzeptable Lüftungsdauer")
            elif duration_minutes < 3:
                percentage = 30
                comments.append("Zu kurz gelüftet")
            else:
                percentage = 50
                comments.append("Keine Sensordaten verfügbar")
        
        # Rating und Emoji
        if percentage >= 80:
            rating = "Sehr gut"
            emoji = "🌟"
        elif percentage >= 60:
            rating = "Gut"
            emoji = "✅"
        elif percentage >= 40:
            rating = "OK"
            emoji = "👌"
        elif percentage >= 20:
            rating = "Mäßig"
            emoji = "⚠️"
        else:
            rating = "Gering"
            emoji = "❌"
        
        # Füge Prozent zum Rating
        rating = f"{rating} ({percentage}%)"
        
        return {
            'rating': rating,
            'emoji': emoji,
            'percentage': percentage,
            'comment': comments[0] if comments else None,
            'all_comments': comments
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
