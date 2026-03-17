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
import json
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
    
    # Klassen-Variable für Debug-Logs (global zugänglich)
    _debug_logs: list = []
    _max_debug_logs: int = 100

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
        self._cooldown_minutes = 30  # Default-Cooldown (wird dynamisch angepasst)
        
        # Erweitertes Notification-Tracking für exponentielles Backoff
        self._notification_tracking: Dict[str, dict] = {}  # key -> {count, last_sent, is_critical}
        
        # Kritische Event-Typen (kein exponentielles Backoff, fester Cooldown)
        self._critical_patterns = [
            'window_away',      # Fenster offen + niemand zu Hause
            'frost_',           # Frostwarnung
            'mold_',            # Schimmelgefahr
            'heater_active',    # Fenster offen + Heizung aktiv
        ]
        
        # CO2-Pattern für speziellen Cooldown
        self._co2_patterns = ['co2_high', 'co2_alert']
        
        # Tracke offene Fenster und deren Öffnungszeit
        self._open_windows: Dict[str, dict] = {}  # device_id -> {opened_at, room, name, climate_start}
        
        # Anwesenheits-Tracking
        self._presence_home: bool = True
        self._away_since: Optional[datetime] = None
        
        # Lüftungs-Statistiken für Vergleiche
        self._ventilation_stats: Dict[str, list] = {}  # room -> [{duration, score, timestamp}, ...]
        self._stats_file = Path('data/ventilation_stats.json')
        self._load_stats()
        
        # Tracking für Lüftungserinnerung
        self._last_ventilation: Dict[str, datetime] = {}  # room -> last_ventilation_time
        
        logger.info(f"Ventilation Notifier initialized ({check_interval}s interval)")
    
    def _log_debug_event(self, event_type: str, message: str, details: dict = None, level: str = 'info'):
        """Speichert Debug-Event für Web-Anzeige
        
        Args:
            event_type: Art des Events (window_opened, window_closed, no_sensor_data, error)
            message: Beschreibung
            details: Zusätzliche Details als Dict
            level: Log-Level (info, warning, error)
        """
        log_entry = {
            'timestamp': datetime.now().isoformat(),
            'event_type': event_type,
            'message': message,
            'details': details or {},
            'level': level
        }
        VentilationNotifier._debug_logs.append(log_entry)
        
        # Begrenze Anzahl der Logs
        if len(VentilationNotifier._debug_logs) > VentilationNotifier._max_debug_logs:
            VentilationNotifier._debug_logs = VentilationNotifier._debug_logs[-VentilationNotifier._max_debug_logs:]
    
    @classmethod
    def get_debug_logs(cls) -> list:
        """Gibt alle Debug-Logs zurück"""
        return list(cls._debug_logs)
    
    @classmethod
    def clear_debug_logs(cls):
        """Löscht alle Debug-Logs"""
        cls._debug_logs = []

    @property
    def _platform(self) -> Any:
        """Sicherer Zugriff auf die Plattform (vermeidet Type-Checker Warnungen)"""
        if self.engine and self.engine.platform:
            return self.engine.platform
        return None

    def _load_config(self) -> dict:
        """Lade Benachrichtigungs-Konfiguration mit Defaults für fehlende Optionen
        
        Merged ventilation_notifications mit notifications.events aus dem Frontend.
        Das Frontend speichert Events in notifications.events (z.B. co2_alert, humidity_alert),
        während ventilation_notifications eigene Keys verwendet (z.B. co2_high_alert).
        """
        # Basis-Config aus ventilation_notifications
        config = get_config_section('ventilation_notifications')
        
        # Lade auch Frontend-Events aus notifications.events
        config_path = Path('config/config.yaml')
        if config_path.exists():
            try:
                with open(config_path, 'r') as f:
                    full_config = yaml.safe_load(f) or {}
                    events = full_config.get('notifications', {}).get('events', {})
                    
                    # Map Frontend-Events zu ventilation_notifications Keys
                    if events:
                        # CO2 Alert
                        if 'co2_alert' in events:
                            config['co2_high_alert'] = events['co2_alert'].get('enabled', True)
                            if events['co2_alert'].get('threshold_ppm'):
                                config['co2_threshold'] = events['co2_alert']['threshold_ppm']
                        
                        # Humidity Alert
                        if 'humidity_alert' in events:
                            config['humidity_high_alert'] = events['humidity_alert'].get('enabled', True)
                        
                        # Mold Risk / Warning
                        if 'mold_risk' in events:
                            config['mold_warning'] = events['mold_risk'].get('enabled', True)
                        
                        # Ventilation Complete / Window Closed
                        if 'ventilation_complete' in events:
                            config['window_closed_alert'] = events['ventilation_complete'].get('enabled', False)
                        
                        # Window Open Long -> verwendet für window_opened_alert
                        if 'window_open_long' in events:
                            config['window_opened_alert'] = events['window_open_long'].get('enabled', True)
                            if events['window_open_long'].get('threshold_minutes'):
                                config['window_open_threshold_minutes'] = events['window_open_long']['threshold_minutes']
                            # Gekippte Fenster während Ruhezeit ignorieren
                            config['tilted_quiet_hours_skip'] = events['window_open_long'].get('tilted_quiet_hours_skip', True)
                        
                        # Temperature Alert (Neu!)
                        if 'temperature_alert' in events:
                            config['temperature_alert'] = events['temperature_alert'].get('enabled', True)
                            if events['temperature_alert'].get('threshold_deviation'):
                                config['temperature_threshold_deviation'] = events['temperature_alert']['threshold_deviation']
                            # Ausgeschlossene Räume für Temperaturwarnungen
                            if events['temperature_alert'].get('excluded_rooms'):
                                config['temperature_excluded_rooms'] = events['temperature_alert']['excluded_rooms']
                    
                    # Lade Ruhezeiten
                    notifications = full_config.get('notifications', {})
                    config['quiet_hours_start'] = notifications.get('quiet_hours_start', '22:00')
                    config['quiet_hours_end'] = notifications.get('quiet_hours_end', '07:00')
                        
            except Exception as e:
                logger.debug(f"Could not load frontend events config: {e}")
        
        return config

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

    def _is_quiet_hours(self, config: dict) -> bool:
        """Prüft ob aktuell Ruhezeit ist (z.B. nachts)"""
        try:
            quiet_start_str = config.get('quiet_hours_start', '22:00')
            quiet_end_str = config.get('quiet_hours_end', '07:00')
            
            now = datetime.now()
            current_time = now.time()
            
            # Parse Start und Ende
            start_parts = quiet_start_str.split(':')
            end_parts = quiet_end_str.split(':')
            
            quiet_start = datetime.strptime(quiet_start_str, '%H:%M').time()
            quiet_end = datetime.strptime(quiet_end_str, '%H:%M').time()
            
            # Prüfe ob Ruhezeit über Mitternacht geht (z.B. 22:00 - 07:00)
            if quiet_start > quiet_end:
                # Ruhezeit über Mitternacht: 22:00 - 07:00
                return current_time >= quiet_start or current_time <= quiet_end
            else:
                # Ruhezeit innerhalb eines Tages: z.B. 14:00 - 16:00
                return quiet_start <= current_time <= quiet_end
                
        except Exception as e:
            logger.debug(f"Error checking quiet hours: {e}")
            return False

    def _is_critical_notification(self, notification_key: str) -> bool:
        """Prüft ob eine Benachrichtigung als kritisch eingestuft wird"""
        if not notification_key:
            return False
        key_lower = notification_key.lower()
        return any(pattern in key_lower for pattern in self._critical_patterns)
    
    def _is_co2_notification(self, notification_key: str) -> bool:
        """Prüft ob es sich um eine CO2-Benachrichtigung handelt"""
        if not notification_key:
            return False
        key_lower = notification_key.lower()
        return any(pattern in key_lower for pattern in self._co2_patterns)
    
    def _calculate_cooldown(self, notification_key: str) -> int:
        """Berechnet den Cooldown basierend auf Event-Typ und Anzahl der Benachrichtigungen
        
        Returns:
            Cooldown in Minuten
        """
        if not notification_key:
            return self._cooldown_minutes
        
        # CO2: Fester Cooldown von 30 Minuten
        if self._is_co2_notification(notification_key):
            return 30
        
        # Kritische Events: Fester Cooldown von 5 Minuten
        if self._is_critical_notification(notification_key):
            return 5
        
        # Nicht-kritische Events: Exponentielles Backoff
        tracking = self._notification_tracking.get(notification_key, {})
        count = tracking.get('count', 0)
        
        # Exponentiell: 1, 2, 4, 8, 16, 32, 60 (max) Minuten
        base_cooldown = 1
        max_cooldown = 60
        cooldown = min(base_cooldown * (2 ** count), max_cooldown)
        
        return cooldown
    
    def _update_notification_tracking(self, notification_key: str, sent: bool):
        """Aktualisiert das Tracking nach einer Benachrichtigung"""
        if not notification_key:
            return
        
        now = datetime.now()
        is_critical = self._is_critical_notification(notification_key)
        
        if notification_key not in self._notification_tracking:
            self._notification_tracking[notification_key] = {
                'count': 0,
                'last_sent': None,
                'is_critical': is_critical,
                'first_event': now
            }
        
        tracking = self._notification_tracking[notification_key]
        
        if sent:
            tracking['count'] += 1
            tracking['last_sent'] = now
            cooldown = self._calculate_cooldown(notification_key)
            logger.debug(f"Notification tracking updated: {notification_key}, count={tracking['count']}, next_cooldown={cooldown}min")
    
    def reset_notification_tracking(self, notification_key: str = None):
        """Setzt das Tracking für einen Key oder alle zurück (z.B. wenn Fenster geschlossen)"""
        if notification_key:
            if notification_key in self._notification_tracking:
                del self._notification_tracking[notification_key]
                logger.debug(f"Notification tracking reset: {notification_key}")
        else:
            self._notification_tracking.clear()
            logger.debug("All notification tracking reset")

    def _send_notification(self, title: str, message: str, priority: int = 0, 
                          notification_key: Optional[str] = None) -> bool:
        """Sende Pushover-Benachrichtigung mit intelligentem Cooldown
        
        Cooldown-Logik:
        - Kritische Events (Frost, Schimmel, Abwesenheit): 5 Min fester Cooldown
        - CO2-Benachrichtigungen: 30 Min fester Cooldown
        - Normale Events: Exponentielles Backoff (1, 2, 4, 8, ... bis 60 Min)
        """
        
        # Prüfe Cooldown
        if notification_key:
            tracking = self._notification_tracking.get(notification_key, {})
            last_sent = tracking.get('last_sent') or self._last_notifications.get(notification_key)
            
            if last_sent:
                cooldown_minutes = self._calculate_cooldown(notification_key)
                if datetime.now() - last_sent < timedelta(minutes=cooldown_minutes):
                    remaining = cooldown_minutes - (datetime.now() - last_sent).total_seconds() / 60
                    logger.debug(f"Notification skipped (cooldown {cooldown_minutes}min, {remaining:.1f}min remaining): {notification_key}")
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
            
            # Tracking immer aktualisieren (auch bei Fehler), um Spam zu verhindern
            if notification_key:
                self._last_notifications[notification_key] = datetime.now()
                self._update_notification_tracking(notification_key, sent=(response.status_code == 200))
            
            if response.status_code == 200:
                cooldown = self._calculate_cooldown(notification_key) if notification_key else self._cooldown_minutes
                logger.info(f"Ventilation notification sent: {title} (next in {cooldown}min)")
                return True
            else:
                cooldown = self._calculate_cooldown(notification_key) if notification_key else self._cooldown_minutes
                logger.error(f"Pushover error (retry in {cooldown}min): {response.text}")
                return False
                
        except Exception as e:
            # Auch bei Exception Tracking aktualisieren um Spam zu verhindern
            if notification_key:
                self._last_notifications[notification_key] = datetime.now()
                self._update_notification_tracking(notification_key, sent=False)
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
            
            # DEBUG: Zeige geladene Klimadaten
            logger.info(f"Ventilation check: {len(open_windows)} open windows, {len(room_data)} rooms with climate data")
            for room, data in room_data.items():
                logger.debug(f"  Room '{room}': {data}")
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
                    
                    # Fallback: Versuche Raumnamen-Varianten mit strengerem Matching
                    fallback_key_used = None
                    if not room_climate:
                        room_climate, fallback_key_used = self._find_room_climate_fuzzy(
                            room_name, room_data
                        )
                    
                    # Debug-Event beim Fenster-Öffnen
                    has_climate_data = bool(room_climate.get('temp') or room_climate.get('humidity') or room_climate.get('co2'))
                    self._log_debug_event(
                        'window_opened',
                        f"Fenster '{window.get('name')}' in Raum '{room_name}' geöffnet",
                        {
                            'device_id': window['device_id'],
                            'window_name': window.get('name'),
                            'room_name': room_name,
                            'room_climate_found': has_climate_data,
                            'climate_data': room_climate,
                            'fallback_key_used': fallback_key_used,
                            'available_rooms': list(room_data.keys()),
                            'outdoor_temp': outdoor_temp
                        }
                    )
                    
                    logger.info(f"Window opened - {window.get('name')} in {room_name}: climate_start={room_climate}, available_rooms={list(room_data.keys())}")
                    
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
                    
                    # Prüfe ob gekippte Fenster während Ruhezeit ignoriert werden sollen
                    if window_state == 'tilted' and config.get('tilted_quiet_hours_skip', True):
                        if self._is_quiet_hours(config):
                            logger.info(f"Skipping notification for tilted window '{window.get('name')}' during quiet hours")
                            continue
                    
                    # Berechne empfohlene Lüftungsdauer
                    duration = self._calculate_ventilation_duration(
                        outdoor_temp=outdoor_temp,
                        indoor_temp=room_climate.get('temp'),
                        humidity=room_climate.get('humidity'),
                        co2=room_climate.get('co2')
                    )
                    
                    # Prüfe ob Heizung im Raum aktiv ist
                    heater_warning = self._check_heater_active(room_name)
                    
                    # Luftqualitäts-Empfehlung
                    air_quality = self._get_air_quality_recommendation(
                        co2=room_climate.get('co2'),
                        humidity=room_climate.get('humidity')
                    )
                    
                    # Saisonaler Tipp
                    seasonal_tip = self._get_seasonal_tip(outdoor_temp, window_state)
                    
                    # Temperatur-Differenz berechnen
                    temp_diff_info = None
                    indoor_temp = room_climate.get('temp')
                    if indoor_temp is not None and outdoor_temp is not None:
                        temp_diff = indoor_temp - outdoor_temp
                        if temp_diff > 15:
                            temp_diff_info = f"🌡️ <b>{temp_diff:.0f}°C Unterschied</b> → sehr schneller Luftaustausch!"
                        elif temp_diff > 10:
                            temp_diff_info = f"🌡️ <b>{temp_diff:.0f}°C Unterschied</b> → effizientes Lüften möglich"
                        elif temp_diff > 5:
                            temp_diff_info = f"🌡️ {temp_diff:.0f}°C Unterschied → guter Luftaustausch"
                        elif temp_diff < -5:
                            temp_diff_info = f"🌡️ Außen {abs(temp_diff):.0f}°C wärmer als innen"
                    
                    # Baue Nachrichtentext mit Zustand (gekippt/offen)
                    state_emoji = '📐' if window_state == 'tilted' else '🪟'
                    state_text = 'gekippt' if window_state == 'tilted' else 'geöffnet'
                    message_parts = [f'{state_emoji} <b>{window["name"]}</b> wurde {state_text}']
                    
                    # Heizungs-Warnung direkt nach der Überschrift (wenn aktiv)
                    if heater_warning and heater_warning.get('is_heating'):
                        message_parts.append(f"\n\n🔥 <b>ACHTUNG:</b> {heater_warning['message']}")
                        if heater_warning.get('tip'):
                            message_parts.append(f"\n💡 {heater_warning['tip']}")
                    
                    # Luftqualitäts-Warnung (wenn dringend)
                    if air_quality and air_quality['urgency'] in ['urgent', 'recommended']:
                        message_parts.append(f"\n\n{air_quality['main_issue']}")
                    
                    # Temperatur-Differenz anzeigen
                    if temp_diff_info:
                        message_parts.append(f"\n\n{temp_diff_info}")
                    
                    # Zeige Raum-Klimadaten wenn verfügbar
                    climate_info = []
                    if room_climate.get('temp'):
                        climate_info.append(f"🌡️ {room_climate['temp']:.1f}°C")
                    if room_climate.get('humidity'):
                        climate_info.append(f"💧 {room_climate['humidity']:.0f}%")
                    if room_climate.get('co2'):
                        co2_val = room_climate['co2']
                        co2_emoji = '🚨' if co2_val > 1400 else '⚠️' if co2_val > 1000 else '💨'
                        climate_info.append(f"{co2_emoji} {co2_val:.0f} ppm")
                    
                    if climate_info:
                        message_parts.append(f"\n<b>{room_name}:</b> " + ' | '.join(climate_info))
                    
                    if outdoor_temp is not None:
                        message_parts.append(f"\n🌤️ Außen: {outdoor_temp:.1f}°C")
                    
                    # Lüftungsempfehlung
                    message_parts.append(f"\n\n⏱️ <b>Empfohlen:</b> {duration['text']}")
                    if duration.get('reason'):
                        message_parts.append(f"\n💡 {duration['reason']}")
                    
                    # Saisonaler Tipp (wenn nicht schon Heizungs-Warnung)
                    if seasonal_tip and not (heater_warning and heater_warning.get('is_heating')):
                        message_parts.append(f"\n\n{seasonal_tip}")
                    
                    # Gekippt vs Offen - spezifischer Hinweis
                    if window_state == 'tilted' and outdoor_temp is not None and outdoor_temp < 10:
                        message_parts.append(f"\n\n📐 <i>Tipp: Bei {outdoor_temp:.0f}°C ist Stoßlüften (ganz öffnen) effektiver als Kippen!</i>")

                    # Titel mit Warnung wenn Heizung aktiv oder Luftqualität dringend
                    if heater_warning and heater_warning.get('is_heating'):
                        title = '🔥🪟 Fenster offen - Heizung aktiv!' if window_state != 'tilted' else '🔥📐 Fenster gekippt - Heizung aktiv!'
                    elif air_quality and air_quality['urgency'] == 'urgent':
                        title = '🚨 Fenster geöffnet - Lüften wichtig!'
                    else:
                        title = '📐 Fenster gekippt' if window_state == 'tilted' else '🪟 Fenster geöffnet'
                    
                    self._send_notification(
                        title,
                        ''.join(message_parts),
                        notification_key=f'window_opened_{window["device_id"]}'
                    )

                    # === Nacht-Lüftungs-Empfehlung als eigene Nachricht (15–23 Uhr) ===
                    if config.get('night_ventilation_check', True) and 15 <= datetime.now().hour < 23:
                        min_night_temp = float(config.get('night_ventilation_min_temp', 3.0))
                        night_check = self._get_night_temperature_check(min_night_temp)
                        if night_check:
                            min_temp = night_check['min_temp']
                            min_at = night_check['min_temp_at'].strftime('%H:%M')
                            end_time = night_check['tonight_end'].strftime('%H:%M')
                            room_label = f"<b>{window.get('name', 'Fenster')}</b> – {window.get('room', '')}"
                            if night_check['can_stay_open']:
                                self._send_notification(
                                    '🌙 Nachtlüften empfohlen ✅',
                                    f"{room_label}\n\n"
                                    f"Fenster kann bis <b>{end_time} Uhr</b> offen/gekippt bleiben.\n"
                                    f"Tiefste Außentemperatur: <b>{min_temp:.1f}°C</b> (ca. {min_at} Uhr)",
                                    notification_key=f'night_vent_{window["device_id"]}'
                                )
                            else:
                                self._send_notification(
                                    '🌙 Nachtlüften: ⚠️ Zu kalt!',
                                    f"{room_label}\n\n"
                                    f"Tiefste Außentemperatur: <b>{min_temp:.1f}°C</b> (ca. {min_at} Uhr)\n"
                                    f"Unter <b>{night_check['min_threshold']:.0f}°C</b> erwartet – Fenster besser schließen.",
                                    notification_key=f'night_vent_{window["device_id"]}'
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
                    
                    # Fallback: Versuche Raumnamen-Varianten mit strengerem Matching
                    fallback_used = None
                    if not room_climate_now:
                        room_climate_now, fallback_used = self._find_room_climate_fuzzy(
                            room_name, room_data
                        )
                        
                        if not room_climate_now:
                            logger.warning(f"No climate data found for room '{room_name}'. Available rooms: {list(room_data.keys())}")
                    
                    # Detailliertes Debug-Logging für Sensordaten-Probleme
                    self._log_debug_event(
                        'window_closed',
                        f"Fenster '{window_name}' in Raum '{room_name}' geschlossen",
                        {
                            'device_id': device_id,
                            'room_name': room_name,
                            'climate_start': climate_start,
                            'climate_now': room_climate_now,
                            'available_rooms': list(room_data.keys()),
                            'duration_minutes': duration_minutes,
                            'has_start_data': bool(climate_start.get('temp') or climate_start.get('humidity') or climate_start.get('co2')),
                            'has_now_data': bool(room_climate_now.get('temp') or room_climate_now.get('humidity') or room_climate_now.get('co2')),
                            'fallback_key_used': fallback_used
                        }
                    )
                    
                    logger.info(f"Window closed - {window_name} in {room_name}: climate_start={climate_start}, climate_now={room_climate_now}, available_rooms={list(room_data.keys())}")
                    
                    # Berechne Effektivität
                    effectiveness = self._calculate_ventilation_effectiveness(
                        climate_start, room_climate_now, duration_minutes
                    )
                    
                    # Zeige Klima-Veränderungen (wenn Vorher/Nachher verfügbar)
                    changes = []
                    has_start_data = climate_start.get('temp') or climate_start.get('humidity') or climate_start.get('co2')
                    has_now_data = room_climate_now.get('temp') or room_climate_now.get('humidity') or room_climate_now.get('co2')
                    
                    # Variablen für Bewertungen
                    temp_diff = None
                    temp_rating = None
                    energy_info = None
                    climate_change = {}
                    
                    if has_start_data and has_now_data:
                        # Vollständiger Vergleich
                        if climate_start.get('temp') and room_climate_now.get('temp'):
                            temp_diff = room_climate_now['temp'] - climate_start['temp']
                            arrow = '↓' if temp_diff < 0 else '↑' if temp_diff > 0 else '→'
                            changes.append(f"🌡️ {climate_start['temp']:.1f}→{room_climate_now['temp']:.1f}°C ({arrow}{abs(temp_diff):.1f}°)")
                            climate_change['temp'] = temp_diff
                            
                            # Berechne Energie-Impact
                            energy_info = self._calculate_energy_impact(
                                temp_diff, duration_minutes, outdoor_temp
                            )
                        
                        if climate_start.get('humidity') and room_climate_now.get('humidity'):
                            hum_diff = room_climate_now['humidity'] - climate_start['humidity']
                            arrow = '↓' if hum_diff < 0 else '↑' if hum_diff > 0 else '→'
                            changes.append(f"💧 {climate_start['humidity']:.0f}→{room_climate_now['humidity']:.0f}% ({arrow}{abs(hum_diff):.0f}%)")
                            climate_change['humidity'] = hum_diff
                        
                        if climate_start.get('co2') and room_climate_now.get('co2'):
                            co2_diff = room_climate_now['co2'] - climate_start['co2']
                            arrow = '↓' if co2_diff < 0 else '↑' if co2_diff > 0 else '→'
                            changes.append(f"💨 {climate_start['co2']:.0f}→{room_climate_now['co2']:.0f} ppm ({arrow}{abs(co2_diff):.0f})")
                            climate_change['co2'] = co2_diff
                        
                        # Raumtemperatur-Bewertung 
                        if temp_diff is not None:
                            temp_rating = self._evaluate_temperature_change(
                                temp_diff, 
                                outdoor_temp, 
                                climate_start.get('outdoor_temp'),
                                duration_minutes
                            )
                    
                    # Prüfe ob zu lange gelüftet
                    too_long_warning = self._check_ventilation_too_long(duration_minutes, outdoor_temp)
                    
                    # Hole Ziel-Erreichung
                    goals = self._get_ventilation_goals(climate_start, room_climate_now)
                    
                    # Vergleiche mit Durchschnitt
                    comparison = self._compare_to_average(room_name, effectiveness['percentage'])
                    
                    # Speichere Statistik
                    self._record_ventilation(
                        room_name, 
                        duration_minutes, 
                        effectiveness['percentage'],
                        energy_saved=energy_info.get('kwh') if energy_info else None,
                        climate_change=climate_change
                    )
                    
                    # === BAUE VERBESSERTE NACHRICHT ===
                    message_parts = [f'✅ <b>{window_name}</b> geschlossen']
                    
                    # Dauer mit Warnung wenn zu lang
                    if too_long_warning and too_long_warning.get('warning'):
                        message_parts.append(f'\n\n{too_long_warning["emoji"]} {too_long_warning["text"]}')
                        if too_long_warning.get('tip'):
                            message_parts.append(f'\n💡 {too_long_warning["tip"]}')
                    else:
                        message_parts.append(f'\n\n⏱️ Lüftungsdauer: <b>{duration_text}</b>')
                    
                    # Grafischer Score mit Fortschrittsbalken
                    score = effectiveness['percentage']
                    progress_bar = self._create_progress_bar(score)
                    message_parts.append(f'\n\n🎯 <b>Lüftungs-Score: {score}/100</b>')
                    message_parts.append(f'\n{progress_bar} {effectiveness["rating"]}')
                    
                    # Vergleich mit Durchschnitt
                    if comparison:
                        message_parts.append(f'\n{comparison["emoji"]} {comparison["text"]}')
                    
                    # Klima-Veränderungen
                    if changes:
                        message_parts.append(f"\n\n📊 <b>Veränderung:</b>\n" + '\n'.join(changes))
                    
                    # Ziele erreicht?
                    if goals:
                        achieved = [g for g in goals if g['achieved']]
                        not_achieved = [g for g in goals if not g['achieved']]
                        
                        if achieved:
                            goal_text = ' | '.join([f"{g['emoji']} {g['name']}" for g in achieved])
                            message_parts.append(f"\n\n🎯 <b>Ziele:</b> {goal_text}")
                        
                        if not_achieved:
                            goal_text = ' | '.join([f"{g['emoji']} {g['name']}" for g in not_achieved])
                            message_parts.append(f"\n⚠️ Nicht erreicht: {goal_text}")
                    
                    # Energie-Info (nur wenn Temperaturänderung bekannt)
                    if energy_info and energy_info['kwh'] > 0:
                        message_parts.append(f"\n\n⚡ <b>Energie:</b> {energy_info['text']}")
                    
                    # Raumklima-Bewertung
                    if temp_rating:
                        message_parts.append(f"\n\n{temp_rating['emoji']} <b>Raumklima:</b> {temp_rating['text']}")
                        if temp_rating.get('tip'):
                            message_parts.append(f"\n💡 {temp_rating['tip']}")
                    
                    # Fallback: Nur aktuelle Daten verfügbar
                    elif has_now_data and not has_start_data:
                        current_info = []
                        if room_climate_now.get('temp'):
                            current_info.append(f"🌡️ {room_climate_now['temp']:.1f}°C")
                        if room_climate_now.get('humidity'):
                            current_info.append(f"💧 {room_climate_now['humidity']:.0f}%")
                        if room_climate_now.get('co2'):
                            current_info.append(f"💨 {room_climate_now['co2']:.0f} ppm")
                        
                        if current_info:
                            message_parts.append(f"\n\n📍 <b>Aktuell:</b> " + ' | '.join(current_info))
                    
                    # Keine Sensordaten
                    elif not has_now_data and not has_start_data:
                        self._log_debug_event(
                            'no_sensor_data',
                            f"Keine Sensordaten für Raum '{room_name}' gefunden",
                            {
                                'room_name': room_name,
                                'climate_start': climate_start,
                                'room_climate_now': room_climate_now,
                                'available_rooms': list(room_data.keys()),
                                'outdoor_temp': outdoor_temp
                            },
                            level='warning'
                        )
                        
                        if outdoor_temp is not None:
                            message_parts.append(f"\n\n🌤️ Außentemperatur: {outdoor_temp:.1f}°C")
                        else:
                            message_parts.append(f"\n\n<i>Keine Sensordaten für {room_name} verfügbar</i>")
                    
                    # Effektivitäts-Kommentar
                    if effectiveness.get('comment'):
                        message_parts.append(f"\n\n💬 {effectiveness['comment']}")
                    
                    # === Nacht-Lüftungs-Empfehlung beim Schließen (15–23 Uhr) ===
                    if config.get('night_ventilation_check', True) and 15 <= datetime.now().hour < 23:
                        min_night_temp = float(config.get('night_ventilation_min_temp', 3.0))
                        night_check = self._get_night_temperature_check(min_night_temp)
                        if night_check:
                            min_temp = night_check['min_temp']
                            min_at = night_check['min_temp_at'].strftime('%H:%M')
                            end_time = night_check['tonight_end'].strftime('%H:%M')
                            if night_check['can_stay_open']:
                                message_parts.append(
                                    f"\n\n🌙 <b>Nachtlüften empfohlen:</b> ✅"
                                    f"\nTiefste Temp. bis morgen 07:00: <b>{min_temp:.1f}°C</b> (ca. {min_at} Uhr)"
                                    f"\n→ Fenster kann diese Nacht offen/gekippt bleiben"
                                )
                            else:
                                message_parts.append(
                                    f"\n\n🌙 <b>Nachtlüften:</b> ⚠️ Zu kalt!"
                                    f"\nTiefste Temp. bis morgen 07:00: <b>{min_temp:.1f}°C</b> (ca. {min_at} Uhr)"
                                    f"\n→ Unter {night_check['min_threshold']:.0f}°C erwartet – Fenster besser geschlossen lassen"
                                )

                    # Titel basierend auf Score
                    if score >= 80:
                        title = '🌟 Sehr gute Lüftung!'
                    elif score >= 60:
                        title = '✅ Lüftung beendet'
                    elif score >= 40:
                        title = '👌 Lüftung beendet'
                    else:
                        title = '⚠️ Lüftung beendet'
                    
                    self._send_notification(
                        title,
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
                    # Nachts keine Frostwarnung – man schläft und kann nichts tun
                    if self._is_quiet_hours(config):
                        logger.debug("Frost warning suppressed during quiet hours")
                    else:
                        # Alle betroffenen Fenster sammeln und als EINE Nachricht senden
                        frost_windows = []
                        for window in open_windows:
                            device_id = window['device_id']
                            window_info = self._open_windows.get(device_id, {})
                            opened_at = window_info.get('opened_at') if isinstance(window_info, dict) else None
                            if opened_at:
                                minutes_open = (datetime.now() - opened_at).total_seconds() / 60
                                if minutes_open >= 10:  # Mind. 10 Min offen
                                    frost_windows.append((window['name'], minutes_open))

                        if frost_windows:
                            window_lines = '\n'.join(
                                f'🪟 <b>{name}</b> seit {mins:.0f} Min. offen'
                                for name, mins in frost_windows
                            )
                            self._send_notification(
                                '❄️ Frostwarnung!',
                                f'<b>Außentemperatur: {outdoor_temp:.1f}°C</b>\n\n'
                                f'{window_lines}\n\n'
                                f'⚠️ Bitte Fenster schließen um Heizkosten zu sparen.',
                                priority=1,
                                notification_key='frost_combined'
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
            
            # === Temperaturwarnung (zu große Abweichung) ===
            if config.get('temperature_alert'):
                threshold_deviation = config.get('temperature_threshold_deviation', 3)
                
                # Liste von ausgeschlossenen Räumen aus Einstellungen laden
                # Fallback auf Standard-Liste wenn nicht konfiguriert
                default_excluded = ['heim', 'home', 'outside', 'außen', 'draußen', 'aussen', 'garage', 'keller', 'dachboden', 'abstellraum']
                configured_excluded = config.get('temperature_excluded_rooms', [])
                
                # Wenn konfigurierte Liste vorhanden, diese verwenden (lowercase)
                if configured_excluded:
                    excluded_rooms = [r.lower().strip() for r in configured_excluded if r.strip()]
                else:
                    excluded_rooms = default_excluded
                
                logger.debug(f"Temperature alert excluded rooms: {excluded_rooms}")
                
                # Lade auch Räume mit deaktivierten Sensoren aus dem Mapping
                mapping = self._load_sensor_mapping()
                room_mapping = mapping.get('rooms', {})
                disabled_rooms = set()
                for room_id, sensors in room_mapping.items():
                    temp_sensor = sensors.get('temperature', '')
                    if temp_sensor == 'none':
                        disabled_rooms.add(room_id.lower())
                        # Auch den Display-Namen hinzufügen
                        disabled_rooms.add(room_id.lower().replace('_', ' '))
                
                for room, data in room_data.items():
                    # Überspringe Räume die keine echten Wohnräume sind
                    room_lower = room.lower()
                    if any(excl in room_lower for excl in excluded_rooms):
                        logger.debug(f"Skipping temperature alert for '{room}' (excluded room)")
                        continue
                    
                    # Überspringe Räume mit explizit deaktivierten Temperatursensoren
                    if room_lower in disabled_rooms or room_lower.replace(' ', '_') in disabled_rooms:
                        logger.debug(f"Skipping temperature alert for '{room}' (sensor disabled)")
                        continue
                    
                    temp = data.get('temp')
                    if temp:
                        # Zweite Plausibilitätsprüfung: unrealistische Werte nie alarmieren
                        if not (-20 < temp < 45):
                            logger.debug(f"Skipping temperature alert for '{room}': unrealistic value {temp}°C")
                            continue
                        # Prüfe auf extreme Temperaturen oder große Abweichung vom Komfortbereich
                        # Komfortbereich: 18-23°C
                        comfort_min = 18
                        comfort_max = 23
                        
                        if temp < comfort_min - threshold_deviation:
                            deviation = comfort_min - temp
                            self._send_notification(
                                '🥶 Temperaturwarnung!',
                                f'<b>{room}:</b> Temperatur bei <b>{temp:.1f}°C</b>\n\n'
                                f'📉 {deviation:.1f}°C unter dem Komfortbereich ({comfort_min}°C).\n\n'
                                f'🔥 Heizung einschalten oder Fenster schließen empfohlen.',
                                notification_key=f'temp_low_{room}'
                            )
                        elif temp > comfort_max + threshold_deviation:
                            deviation = temp - comfort_max
                            self._send_notification(
                                '🥵 Temperaturwarnung!',
                                f'<b>{room}:</b> Temperatur bei <b>{temp:.1f}°C</b>\n\n'
                                f'📈 {deviation:.1f}°C über dem Komfortbereich ({comfort_max}°C).\n\n'
                                f'🪟 Lüften oder Beschattung empfohlen.',
                                notification_key=f'temp_high_{room}'
                            )
            
            # === NEU: Warnung bei zu langem Lüften (Energieverschwendung) ===
            if config.get('long_ventilation_warning', True) and outdoor_temp is not None:
                for window in open_windows:
                    device_id = window['device_id']
                    window_state = window.get('state', 'open')
                    window_info = self._open_windows.get(device_id, {})
                    opened_at = window_info.get('opened_at')
                    
                    # Prüfe ob gekippte Fenster während Ruhezeit ignoriert werden sollen
                    if window_state == 'tilted' and config.get('tilted_quiet_hours_skip', True):
                        if self._is_quiet_hours(config):
                            continue
                    
                    if opened_at:
                        minutes_open = (datetime.now() - opened_at).total_seconds() / 60
                        
                        # Berechne maximale empfohlene Dauer
                        if outdoor_temp < 0:
                            max_minutes = 10
                            severity = 'critical'
                        elif outdoor_temp < 5:
                            max_minutes = 15
                            severity = 'warning'
                        elif outdoor_temp < 10:
                            max_minutes = 25
                            severity = 'info'
                        else:
                            max_minutes = 45  # Im Sommer weniger kritisch
                            severity = 'info'
                        
                        # Warnen wenn deutlich über Maximum
                        if minutes_open > max_minutes * 1.5 and severity in ['critical', 'warning']:
                            room_name = window.get('room', 'Unbekannt')
                            
                            if severity == 'critical':
                                title = '❄️ Fenster zu lange offen!'
                                emoji = '🚨'
                            else:
                                title = '⏰ Lange Lüftungsdauer'
                                emoji = '⚠️'
                            
                            message = (
                                f'{emoji} <b>{window["name"]}</b> ist seit {int(minutes_open)} Min. offen!\n\n'
                                f'🌡️ Bei {outdoor_temp:.1f}°C Außentemperatur empfohlen: max. {max_minutes} Min.\n\n'
                                f'💡 <b>Tipp:</b> Stoßlüften (5-10 Min. weit öffnen) ist effektiver '
                                f'als langes Kipplüften und spart Heizkosten!'
                            )
                            
                            self._send_notification(
                                title,
                                message,
                                priority=0 if severity == 'info' else 1,
                                notification_key=f'long_ventilation_{device_id}'
                            )
            
            # === NEU: Lüftungserinnerung (wenn lange nicht gelüftet) ===
            if config.get('ventilation_reminder', False):
                reminder_hours = config.get('ventilation_reminder_hours', 4)
                
                for room, data in room_data.items():
                    # Prüfe ob Raum aktuell ein offenes Fenster hat
                    room_has_open_window = any(
                        w.get('room', '').lower() == room.lower() 
                        for w in open_windows
                    )
                    
                    # Keine Erinnerung wenn gerade gelüftet wird
                    if room_has_open_window:
                        continue
                    
                    # Prüfe letzte Lüftung
                    last_vent = self._last_ventilation.get(room)
                    if last_vent:
                        hours_since = (datetime.now() - last_vent).total_seconds() / 3600
                    else:
                        hours_since = 999  # Noch nie gelüftet
                    
                    # Erinnerung wenn zu lange nicht gelüftet
                    if hours_since >= reminder_hours:
                        co2 = data.get('co2')
                        humidity = data.get('humidity')
                        
                        # Nur erinnern wenn Luftqualität nicht optimal
                        should_remind = False
                        reason = ""
                        
                        if co2 and co2 > 900:
                            should_remind = True
                            reason = f"CO₂ bei {co2:.0f} ppm"
                        elif humidity and humidity > 60:
                            should_remind = True
                            reason = f"Luftfeuchtigkeit bei {humidity:.0f}%"
                        elif hours_since >= reminder_hours * 2:
                            should_remind = True
                            reason = f"Seit {int(hours_since)}h nicht gelüftet"
                        
                        if should_remind:
                            message = (
                                f'💨 <b>{room}</b> sollte gelüftet werden!\n\n'
                                f'⏰ Letzte Lüftung: vor {int(hours_since)} Stunden\n'
                                f'📊 {reason}\n\n'
                                f'🪟 Kurzes Stoßlüften verbessert die Luftqualität.'
                            )
                            
                            if outdoor_temp is not None:
                                duration = self._calculate_ventilation_duration(
                                    outdoor_temp=outdoor_temp,
                                    co2=co2,
                                    humidity=humidity
                                )
                                message += f'\n\n⏱️ Empfohlen: {duration["text"]}'
                            
                            self._send_notification(
                                '💨 Lüftungserinnerung',
                                message,
                                notification_key=f'vent_reminder_{room}'
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
            self._log_debug_event(
                'error',
                f"Fehler bei Lüftungsprüfung: {str(e)}",
                {'exception': str(e), 'type': type(e).__name__},
                level='error'
            )

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

    def _find_room_climate_fuzzy(self, room_name: str, room_data: Dict[str, Dict]) -> tuple:
        """Findet Klimadaten für einen Raum mit intelligentem Fuzzy-Matching
        
        Verwendet strengere Matching-Regeln um falsche Zuordnungen zu vermeiden:
        1. Exaktes Match (case-insensitive)
        2. Der Suchraum ist ein vollständiges Wort im Zielraum
        3. Der Zielraum ist ein vollständiges Wort im Suchraum
        
        Returns:
            Tuple von (room_climate_dict, matched_key oder None)
        """
        if not room_name or not room_data:
            return {}, None
            
        room_name_lower = room_name.lower().strip()
        
        # 1. Exaktes Match (case-insensitive)
        for key in room_data.keys():
            if key.lower().strip() == room_name_lower:
                logger.debug(f"Exact match for '{room_name}': '{key}'")
                return room_data[key], key
        
        # 2. Der Suchraum ist ein vollständiges Wort im Zielraum
        # z.B. "Bad" findet "Bad (oben)" aber nicht "Schlafzimmer (Doppelbett)"
        import re
        for key in room_data.keys():
            key_lower = key.lower()
            # Suche nach dem Raumnamen als vollständiges Wort
            pattern = r'\b' + re.escape(room_name_lower) + r'\b'
            if re.search(pattern, key_lower):
                logger.debug(f"Word match for '{room_name}' in '{key}'")
                return room_data[key], key
        
        # 3. Der Zielraum ist ein vollständiges Wort im Suchraum
        # z.B. "Schlafzimmer (Doppelbett)" findet "Schlafzimmer"
        for key in room_data.keys():
            key_lower = key.lower().strip()
            # Nur wenn der Key mindestens 3 Zeichen hat (verhindert falsche Matches)
            if len(key_lower) >= 3:
                pattern = r'\b' + re.escape(key_lower) + r'\b'
                if re.search(pattern, room_name_lower):
                    logger.debug(f"Reverse word match: '{key}' found in '{room_name}'")
                    return room_data[key], key
        
        # 4. Keine sinnvolle Übereinstimmung gefunden
        logger.debug(f"No fuzzy match found for '{room_name}' in {list(room_data.keys())}")
        return {}, None

    def _check_heater_active(self, room_name: str) -> Optional[dict]:
        """Prüft ob eine Heizung/Thermostat im Raum gerade aktiv heizt
        
        Args:
            room_name: Name des Raums
            
        Returns:
            Dict mit is_heating, heater_name, message, tip oder None wenn keine Heizung gefunden
        """
        platform = self._platform
        if not platform or not room_name:
            return None
            
        try:
            # Hole alle Geräte
            if hasattr(platform, '_device_cache'):
                platform._refresh_device_cache()
                devices = list(platform._device_cache.values()) if isinstance(
                    platform._device_cache, dict) else platform._device_cache
            else:
                devices = platform.get_states() or []
            
            # Hole Zone-Mapping
            zones = {}
            try:
                zone_dict = platform.get_zones() or {}
                # Homey API gibt {zone_id: zone_data, ...} zurück
                if isinstance(zone_dict, dict):
                    for zone_id, zone_data in zone_dict.items():
                        if isinstance(zone_data, dict):
                            zones[zone_id] = zone_data.get('name', '')
            except:
                pass
            
            room_lower = room_name.lower()
            
            # Suche Heizgeräte im Raum
            for device in devices:
                if not isinstance(device, dict):
                    continue
                
                device_name = device.get('name', '').lower()
                zone_id = device.get('zone')
                device_room = zones.get(zone_id, '').lower()
                
                # Prüfe ob das Gerät zum Raum passt
                room_match = (
                    room_lower in device_room or
                    device_room in room_lower or
                    room_lower in device_name
                )
                
                if not room_match:
                    continue
                
                caps = device.get('capabilitiesObj', {})
                
                # === Prüfe verschiedene Heizungs-Typen ===
                
                # 1. Thermostat mit target_temperature (z.B. Homematic, Tado, etc.)
                if 'target_temperature' in caps:
                    target_temp = caps['target_temperature'].get('value')
                    current_temp = caps.get('measure_temperature', {}).get('value')
                    
                    # Heizung ist aktiv wenn Zieltemperatur > aktuelle Temperatur
                    if target_temp and current_temp:
                        if target_temp > current_temp + 0.5:  # 0.5°C Toleranz
                            return {
                                'is_heating': True,
                                'heater_name': device.get('name', 'Thermostat'),
                                'target_temp': target_temp,
                                'current_temp': current_temp,
                                'message': f"Heizung '{device.get('name')}' heizt auf {target_temp:.1f}°C!",
                                'tip': 'Thermostat runterdrehen oder Fenster schnell wieder schließen.'
                            }
                    elif target_temp and target_temp > 5:  # Frostschutz ist ok
                        # Keine aktuelle Temperatur, aber Zieltemperatur gesetzt
                        return {
                            'is_heating': True,
                            'heater_name': device.get('name', 'Thermostat'),
                            'target_temp': target_temp,
                            'current_temp': None,
                            'message': f"Heizung '{device.get('name')}' ist auf {target_temp:.1f}°C eingestellt!",
                            'tip': 'Thermostat runterdrehen um Energie zu sparen.'
                        }
                
                # 2. Heizkörper-Ventil (valve_position > 0%)
                # WICHTIG: NUR valve_position prüfen, NICHT windowcoverings_set (das sind Rollläden!)
                if 'valve_position' in caps:
                    valve_pos = caps['valve_position'].get('value', 0)
                    
                    # Ventil ist offen wenn Position > 10%
                    if valve_pos and valve_pos > 0.1:  # > 10%
                        valve_percent = valve_pos * 100 if valve_pos <= 1 else valve_pos
                        return {
                            'is_heating': True,
                            'heater_name': device.get('name', 'Heizkörper'),
                            'valve_position': valve_percent,
                            'message': f"Heizkörper '{device.get('name')}' ist {valve_percent:.0f}% offen!",
                            'tip': 'Ventil schließen oder nur kurz lüften (5 Min).'
                        }
                
                # 3. Elektrische Heizung (onoff + Heizung im Namen)
                heater_keywords = ['heiz', 'heat', 'radiator', 'konvektor', 'infrarot', 'wärme']
                is_heater = any(kw in device_name for kw in heater_keywords)
                
                if is_heater and 'onoff' in caps:
                    is_on = caps['onoff'].get('value', False)
                    if is_on:
                        # Prüfe auch Leistung wenn verfügbar
                        power = caps.get('measure_power', {}).get('value')
                        power_text = f" ({power:.0f}W)" if power else ""
                        
                        return {
                            'is_heating': True,
                            'heater_name': device.get('name', 'Heizung'),
                            'power': power,
                            'message': f"Heizung '{device.get('name')}' ist eingeschaltet{power_text}!",
                            'tip': 'Heizung ausschalten während des Lüftens.'
                        }
                
                # 4. Fußbodenheizung / Heizungsaktoren
                if 'thermostat_mode' in caps:
                    mode = caps['thermostat_mode'].get('value', '')
                    if mode and mode.lower() in ['heat', 'heating', 'heizen', 'auto']:
                        return {
                            'is_heating': True,
                            'heater_name': device.get('name', 'Thermostat'),
                            'mode': mode,
                            'message': f"Heizung '{device.get('name')}' ist im Modus '{mode}'!",
                            'tip': 'Kurz lüften (max 5-10 Min) um Energieverlust zu minimieren.'
                        }
                        
        except Exception as e:
            logger.debug(f"Error checking heater status for room {room_name}: {e}")
        
        return None

    def _load_sensor_mapping(self) -> dict:
        """Lade Sensor-Mapping aus Datei"""
        mapping_file = Path('data/ventilation_sensor_mapping.json')
        if mapping_file.exists():
            try:
                with open(mapping_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Error loading sensor mapping: {e}")
        return {}

    def _get_sensor_value_by_id(self, entity_id: str, capability_hint: str = None) -> Optional[float]:
        """Hole den aktuellen Wert eines Sensors anhand der ID

        Unterstützt:
        - Homey Device-IDs (UUID format): automatische Capability-Erkennung
        - Homey mit Capability: homey:device_id:capability
        - Home Assistant Entity-IDs: sensor.xxx

        Args:
            entity_id: Die Sensor/Device ID
            capability_hint: Optional hint für gewünschte Capability ('temperature', 'humidity', 'co2')

        Gibt None zurück wenn:
        - entity_id leer ist
        - entity_id == 'none' (explizit kein Sensor gewünscht)
        - Sensor nicht gefunden wird
        """
        if not entity_id or entity_id == 'none':
            return None

        try:
            # Check if it's a Homey Device ID (UUID format: 8-4-4-4-12 characters)
            is_homey_uuid = (len(entity_id) == 36 and
                           entity_id.count('-') == 4 and
                           all(c in '0123456789abcdefABCDEF-' for c in entity_id))

            if entity_id.startswith('homey:') or is_homey_uuid:
                device_id = None
                specific_capability = None

                if entity_id.startswith('homey:'):
                    # Homey Sensor: homey:device_id:capability
                    parts = entity_id.split(':')
                    if len(parts) >= 2:
                        device_id = parts[1]
                        if len(parts) >= 3:
                            specific_capability = f'measure_{parts[2]}'
                else:
                    # Pure Homey Device ID
                    device_id = entity_id

                if device_id:
                    platform = self._platform
                    if platform:
                        # Versuche direkten Zugriff oder Cache
                        device = None
                        if hasattr(platform, 'get_device'):
                            device = platform.get_device(device_id)

                        if not device and hasattr(platform, '_device_cache'):
                            if isinstance(platform._device_cache, dict):
                                device = platform._device_cache.get(device_id)

                        if not device and hasattr(platform, 'get_all_devices'):
                             all_devices = platform.get_all_devices()
                             if isinstance(all_devices, dict):
                                 device = all_devices.get(device_id)

                        if device:
                            caps_obj = device.get('capabilitiesObj', {})

                            # If specific capability was provided, use it
                            if specific_capability and specific_capability in caps_obj:
                                return caps_obj[specific_capability].get('value')

                            # If capability hint was provided, try it first
                            if capability_hint:
                                hint_cap = f'measure_{capability_hint}'
                                if hint_cap in caps_obj:
                                    val = caps_obj[hint_cap].get('value')
                                    if val is not None:
                                        return val

                            # Otherwise, try to find relevant measurement capability
                            # Priority: temperature > humidity > co2 > any measure_
                            for cap_name in ['measure_temperature', 'measure_humidity', 'measure_co2', 'measure_pm25']:
                                if cap_name in caps_obj:
                                    val = caps_obj[cap_name].get('value')
                                    if val is not None:
                                        return val

                            # Fallback: return first measure_ capability found
                            for cap_name, cap_data in caps_obj.items():
                                if cap_name.startswith('measure_'):
                                    val = cap_data.get('value')
                                    if val is not None:
                                        return val
            else:
                # Home Assistant Sensor
                if self.engine and hasattr(self.engine, 'platforms') and 'homeassistant' in self.engine.platforms:
                    ha_platform = self.engine.platforms['homeassistant']
                    if hasattr(ha_platform, 'get_all_devices'):
                        ha_devices = ha_platform.get_all_devices()
                        if ha_devices and entity_id in ha_devices:
                            state = ha_devices[entity_id].get('state')
                            try:
                                return float(state)
                            except (ValueError, TypeError):
                                pass
        except Exception as e:
            logger.debug(f"Error getting sensor value for {entity_id}: {e}")
        return None

    def _get_room_climate_data(self) -> Dict[str, Dict]:
        """Holt Klimadaten für alle Räume (Mapping + Auto-Discovery)"""
        rooms_data = {}
        
        # 1. Versuche Mapping
        mapping = self._load_sensor_mapping()
        room_mapping = mapping.get('rooms', {})
        
        # Lade Raum-Namen und versteckte Räume aus rooms.json
        rooms_file = Path('data/rooms.json')
        room_names = {}
        hidden_rooms = []
        if rooms_file.exists():
            try:
                with open(rooms_file, 'r') as f:
                    content = json.load(f)
                    room_list = content.get('rooms', []) if isinstance(content, dict) else content
                    hidden_rooms = content.get('hidden_rooms', []) if isinstance(content, dict) else []
                    for r in room_list:
                        rid = r.get('id') or r.get('name', '').lower().replace(' ', '_')
                        room_names[rid] = r.get('name', rid)
            except Exception as e:
                logger.error(f"Error loading rooms.json: {e}")

        # Daten aus Mapping holen
        for room_id, sensors in room_mapping.items():
            # Nutze 'name'-Feld aus dem Mapping als primäre Quelle für den Anzeigenamen
            # room_names hat UUID-Keys, Mapping hat String-Keys → Mismatch vermeiden
            pretty_name = sensors.get('name', '')
            room_name = room_names.get(room_id) or pretty_name or room_id
            
            # Überspringe versteckte Räume (z.B. "Heim" = Außenbereich)
            if room_id in hidden_rooms or room_name in hidden_rooms:
                continue
            
            # Prüfe ob Raum explizit keine Sensoren haben soll (beide auf "none")
            temp_sensor_id = sensors.get('temperature', '')
            humidity_sensor_id = sensors.get('humidity', '')
            
            # Wenn beide explizit auf "none" gesetzt sind -> Raum komplett überspringen
            if temp_sensor_id == 'none' and humidity_sensor_id == 'none':
                logger.debug(f"Skipping room '{room_name}': sensors explicitly disabled")
                continue
            
            temp = self._get_sensor_value_by_id(temp_sensor_id, 'temperature')
            humidity = self._get_sensor_value_by_id(humidity_sensor_id, 'humidity')
            co2 = self._get_sensor_value_by_id(sensors.get('co2'), 'co2')

            # Plausibilitätsprüfung: Chip-Eigentemperaturen (>45°C) von
            # Luftqualitätssensoren (PM2.5 etc.) als ungültig markieren
            if temp is not None and not (-20 < temp < 45):
                logger.warning(f"Unrealistic temperature {temp}°C from mapped sensor in '{room_name}' – discarding (likely chip temp)")
                temp = None
            
            if temp is not None or humidity is not None or co2 is not None:
                if room_name not in rooms_data:
                    rooms_data[room_name] = {}
                if temp is not None:
                    rooms_data[room_name]['temp'] = temp
                if humidity is not None:
                    rooms_data[room_name]['humidity'] = humidity
                if co2 is not None:
                    rooms_data[room_name]['co2'] = co2

        # 2. Fallback: Auto-Discovery via Homey Zones (wie in /rooms)
        # NUR für Räume die KEIN Mapping haben!
        # Sammle Räume die bereits gemappte Sensoren haben
        mapped_rooms_lower = set()
        for room_id, sensors in room_mapping.items():
            # Raum gilt als "gemappt" wenn mindestens ein Sensor konfiguriert ist
            # AUCH wenn auf "none" gesetzt (explizit deaktiviert)
            temp_id = sensors.get('temperature', '')
            humidity_id = sensors.get('humidity', '')
            co2_id = sensors.get('co2', '')

            if temp_id or humidity_id or co2_id:
                # room_names nutzt UUID-Keys, Mapping nutzt String-Keys → nutze 'name'-Feld als Quelle
                pretty_name = sensors.get('name', '')
                room_display_name = room_names.get(room_id) or pretty_name or room_id
                mapped_rooms_lower.add(room_display_name.lower())
                mapped_rooms_lower.add(room_id.lower())
                # Auch den Pretty-Name aus dem Mapping-Entry hinzufügen (sichert korrekte Zone-Filterung)
                if pretty_name:
                    mapped_rooms_lower.add(pretty_name.lower())
        
        platform = self._platform
        if platform:
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
                    zone_dict = platform.get_zones() or {}
                    # Homey API gibt {zone_id: zone_data, ...} zurück
                    if isinstance(zone_dict, dict):
                        for zone_id, zone_data in zone_dict.items():
                            if isinstance(zone_data, dict):
                                zones[zone_id] = zone_data.get('name', '')
                    logger.debug(f"Available zones: {zones}")
                except Exception as ze:
                    logger.debug(f"Could not get zones: {ze}")
                
                for device in devices:
                    if not isinstance(device, dict):
                        continue
                    
                    zone_id = device.get('zone')
                    room_name = zones.get(zone_id)
                    if not room_name:
                        continue
                    
                    # WICHTIG: Überspringe Räume die bereits gemappte Sensoren haben!
                    # Diese sollen NUR die konfigurierten Sensoren nutzen
                    if room_name.lower() in mapped_rooms_lower:
                        continue
                    
                    if room_name not in rooms_data:
                        rooms_data[room_name] = {}
                    
                    caps = device.get('capabilitiesObj', {})
                    
                    # Temperatur - NUR wenn kein Mapping existiert
                    if 'measure_temperature' in caps and 'temp' not in rooms_data[room_name]:
                        val = caps['measure_temperature'].get('value')
                        if val is not None and -20 < val < 45:  # >45°C = Chip-Eigentemp
                            rooms_data[room_name]['temp'] = val
                    
                    # Luftfeuchtigkeit - NUR wenn kein Mapping existiert
                    if 'measure_humidity' in caps and 'humidity' not in rooms_data[room_name]:
                        val = caps['measure_humidity'].get('value')
                        if val is not None and 0 <= val <= 100:
                            rooms_data[room_name]['humidity'] = val
                    
                    # CO2 - NUR wenn kein Mapping existiert
                    if 'measure_co2' in caps and 'co2' not in rooms_data[room_name]:
                        val = caps['measure_co2'].get('value')
                        if val is not None and 200 < val < 10000:
                            rooms_data[room_name]['co2'] = val
                            
            except Exception as e:
                logger.error(f"Error in auto-discovery: {e}")
                    
        return rooms_data

    def _get_outdoor_temp(self) -> Optional[float]:
        """Holt Außentemperatur"""
        # Versuche Mapping zuerst
        mapping = self._load_sensor_mapping()
        outdoor_sensors = mapping.get('outdoor_sensors', {})
        temp_sensor = outdoor_sensors.get('temperature')
        
        if temp_sensor:
            val = self._get_sensor_value_by_id(temp_sensor, 'temperature')
            if val is not None:
                return val
                
        # Fallback: Alte Logik
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
                zone_dict = platform.get_zones() or {}
                # Homey API gibt {zone_id: zone_data, ...} zurück
                if isinstance(zone_dict, dict):
                    for zone_id, zone_data in zone_dict.items():
                        if isinstance(zone_data, dict):
                            zones[zone_id] = zone_data.get('name', '')
                logger.debug(f"Window zones available: {zones}")
            except Exception as ze:
                logger.debug(f"Could not get zones for windows: {ze}")
            
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

    def _evaluate_temperature_change(self, temp_diff: float, outdoor_temp: float = None,
                                      outdoor_temp_start: float = None,
                                      duration_minutes: int = 0) -> dict:
        """Bewertet die Temperaturänderung im Kontext (Winter/Sommer, Dauer)
        
        Args:
            temp_diff: Temperaturänderung (negativ = abgekühlt, positiv = erwärmt)
            outdoor_temp: Aktuelle Außentemperatur
            outdoor_temp_start: Außentemperatur beim Öffnen des Fensters
            duration_minutes: Lüftungsdauer in Minuten
            
        Returns:
            Dict mit emoji, text (Bewertung) und optional tip (Tipp)
        """
        # Bestimme Jahreszeit/Kontext basierend auf Außentemperatur
        outdoor = outdoor_temp if outdoor_temp is not None else outdoor_temp_start
        
        # Default: Heizperiode (Oktober-April in Deutschland)
        from datetime import datetime
        month = datetime.now().month
        is_heating_season = month in [1, 2, 3, 4, 10, 11, 12]
        
        # Überschreibe mit Außentemperatur wenn verfügbar
        if outdoor is not None:
            is_heating_season = outdoor < 15  # Unter 15°C = Heizperiode
        
        abs_diff = abs(temp_diff)
        
        if is_heating_season:
            # === HEIZPERIODE (Winter/Herbst/Frühling) ===
            # Ziel: Möglichst wenig Wärmeverlust bei gutem Luftaustausch
            
            if temp_diff >= 0:
                # Temperatur ist gleich geblieben oder gestiegen (ungewöhnlich beim Lüften)
                return {
                    'emoji': '🤔',
                    'text': f'Keine Abkühlung ({temp_diff:+.1f}°C)',
                    'tip': 'Ungewöhnlich - war das Fenster wirklich offen?'
                }
            elif abs_diff <= 0.5:
                # Minimale Abkühlung - perfekt!
                return {
                    'emoji': '🌟',
                    'text': f'Minimale Abkühlung ({temp_diff:.1f}°C)',
                    'tip': 'Perfekt! Frischluft ohne Wärmeverlust.'
                }
            elif abs_diff <= 1.5:
                # Geringe Abkühlung - sehr gut
                return {
                    'emoji': '✅',
                    'text': f'Geringe Abkühlung ({temp_diff:.1f}°C)',
                    'tip': 'Sehr gut - Heizung gleicht das schnell aus.'
                }
            elif abs_diff <= 3.0:
                # Moderate Abkühlung - akzeptabel
                efficiency = abs_diff / max(duration_minutes, 1) * 10  # °C pro 10 Min
                if efficiency > 2:
                    return {
                        'emoji': '⚠️',
                        'text': f'Spürbare Abkühlung ({temp_diff:.1f}°C)',
                        'tip': 'Tipp: Kürzer aber öfter lüften spart Heizkosten.'
                    }
                else:
                    return {
                        'emoji': '👌',
                        'text': f'Moderate Abkühlung ({temp_diff:.1f}°C)',
                        'tip': None
                    }
            elif abs_diff <= 5.0:
                # Starke Abkühlung - Warnung
                return {
                    'emoji': '🥶',
                    'text': f'Starke Abkühlung ({temp_diff:.1f}°C)',
                    'tip': 'Nächstes Mal kürzer lüften (5-10 Min reichen).'
                }
            else:
                # Sehr starke Abkühlung
                return {
                    'emoji': '❄️',
                    'text': f'Sehr starke Abkühlung ({temp_diff:.1f}°C)',
                    'tip': 'Raum stark ausgekühlt! Stoßlüften (3-5 Min) ist effizienter.'
                }
        else:
            # === SOMMERZEIT ===
            # Ziel: Abkühlung ist erwünscht (besonders morgens/abends)
            
            if temp_diff > 0:
                # Temperatur ist gestiegen - schlecht im Sommer
                return {
                    'emoji': '🌡️',
                    'text': f'Erwärmung ({temp_diff:+.1f}°C)',
                    'tip': 'Draußen wärmer als drinnen - besser morgens/abends lüften.'
                }
            elif abs_diff <= 0.5:
                # Keine Abkühlung
                return {
                    'emoji': '😐',
                    'text': f'Kaum Temperaturänderung ({temp_diff:.1f}°C)',
                    'tip': 'Außen- und Innentemperatur sind ähnlich.'
                }
            elif abs_diff <= 2.0:
                # Leichte Abkühlung
                return {
                    'emoji': '👍',
                    'text': f'Leichte Abkühlung ({temp_diff:.1f}°C)',
                    'tip': 'Gut! Frische Luft reingeholt.'
                }
            elif abs_diff <= 4.0:
                # Gute Abkühlung
                return {
                    'emoji': '✅',
                    'text': f'Gute Abkühlung ({temp_diff:.1f}°C)',
                    'tip': 'Super! Raum angenehm abgekühlt.'
                }
            else:
                # Starke Abkühlung - ideal im Sommer
                return {
                    'emoji': '🌟',
                    'text': f'Starke Abkühlung ({temp_diff:.1f}°C)',
                    'tip': 'Perfekt! Ideale Zeit zum Lüften genutzt.'
                }

    def _calculate_ventilation_effectiveness(self, climate_start: dict, 
                                             climate_now: dict, 
                                             duration_minutes: int) -> dict:
        """Berechnet die Effektivität der Lüftung basierend auf Klima-Veränderungen"""
        
        score = 0.0
        weights = 0.0
        comments = []
        
        # Daten extrahieren
        co2_start = climate_start.get('co2')
        co2_now = climate_now.get('co2')
        hum_start = climate_start.get('humidity')
        hum_now = climate_now.get('humidity')
        temp_start = climate_start.get('temp')
        temp_now = climate_now.get('temp')
        outdoor_temp = climate_start.get('outdoor_temp')
        
        # === 1. CO2-Reduktion (40%) ===
        if co2_start and co2_now:
            weights += 0.40
            co2_change = co2_now - co2_start
            
            if co2_change < -400:
                score += 1.0 * 0.40
                comments.append("CO₂ deutlich gesenkt 👍")
            elif co2_change < -250:
                score += 0.85 * 0.40
                comments.append("CO₂ gut gesenkt")
            elif co2_change < -150:
                score += 0.65 * 0.40
            elif co2_change < -50:
                score += 0.40 * 0.40
            else:
                score += 0.15 * 0.40
                if co2_start > 800:
                    comments.append("CO₂ kaum verändert")
            
            # Bonus für Effizienz (schneller Austausch)
            co2_per_minute = abs(co2_change) / max(duration_minutes, 1)
            if co2_per_minute > 30:
                score += 0.10
            elif co2_per_minute > 15:
                score += 0.05
        
        # === 2. Feuchtigkeit (30%) ===
        if hum_start and hum_now:
            weights += 0.30
            hum_change = hum_now - hum_start
            
            if hum_change < -15:
                score += 1.0 * 0.30
                comments.append("Feuchtigkeit stark gesenkt 👍")
            elif hum_change < -10:
                score += 0.85 * 0.30
            elif hum_change < -5:
                score += 0.65 * 0.30
            elif hum_change < 0:
                score += 0.45 * 0.30
            else:
                score += 0.25 * 0.30
        
        # === 3. Temperatur (30%) ===
        if temp_start and temp_now and outdoor_temp is not None:
            weights += 0.30
            temp_change = temp_now - temp_start
            
            if outdoor_temp < 10:  # Winter
                # Wenig Temperaturverlust ist gut, ABER nur wenn auch Luftaustausch stattfand
                co2_ok = (co2_start is None) or (co2_now is not None and (co2_now - co2_start) < -50)
                
                if co2_ok:
                    if temp_change > -1:
                        score += 1.0 * 0.30
                        comments.append("Wärme gut gehalten")
                    elif temp_change > -2:
                        score += 0.80 * 0.30
                    elif temp_change > -4:
                        score += 0.55 * 0.30
                    else:
                        score += 0.25 * 0.30
                        comments.append("Stark abgekühlt")
                else:
                    # CO2 kaum gesunken = schlechter Luftaustausch -> Wenig Temp-Verlust ist kein Verdienst
                    score += 0.20 * 0.30
            else:  # Sommer
                if temp_change < 0:
                    score += 0.80 * 0.30
                    comments.append("Raum abgekühlt 👍")
                else:
                    score += 0.50 * 0.30
        
        # Berechnung Prozent
        if weights > 0:
            percentage = int((score / weights) * 100)
            percentage = min(100, max(0, percentage))
        else:
            # Fallback auf Dauer (keine Sensordaten)
            if 5 <= duration_minutes <= 15:
                percentage = 75
                comments.append("Gute Lüftungsdauer")
            elif 3 <= duration_minutes <= 25:
                percentage = 60
                comments.append("Akzeptable Dauer")
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
            
        rating_text = f"{rating} ({percentage}%)"
        
        return {
            'rating': rating_text,
            'emoji': emoji,
            'percentage': percentage,
            'comment': comments[0] if comments else None,
            'all_comments': comments
        }

    # ============================================================================
    # STATISTIK-SYSTEM: Speichert Lüftungsdaten für Vergleiche
    # ============================================================================
    
    def _load_stats(self):
        """Lade gespeicherte Lüftungsstatistiken"""
        try:
            if self._stats_file.exists():
                with open(self._stats_file, 'r') as f:
                    data = json.load(f)
                    self._ventilation_stats = data.get('stats', {})
                    # Lade letzte Lüftungszeiten
                    last_vent = data.get('last_ventilation', {})
                    for room, ts in last_vent.items():
                        try:
                            self._last_ventilation[room] = datetime.fromisoformat(ts)
                        except:
                            pass
                    logger.debug(f"Loaded ventilation stats for {len(self._ventilation_stats)} rooms")
        except Exception as e:
            logger.error(f"Error loading ventilation stats: {e}")
    
    def _save_stats(self):
        """Speichere Lüftungsstatistiken"""
        try:
            self._stats_file.parent.mkdir(parents=True, exist_ok=True)
            data = {
                'stats': self._ventilation_stats,
                'last_ventilation': {room: ts.isoformat() for room, ts in self._last_ventilation.items()}
            }
            with open(self._stats_file, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving ventilation stats: {e}")
    
    def _record_ventilation(self, room: str, duration_minutes: int, score: int, 
                           energy_saved: float = None, climate_change: dict = None):
        """Speichere eine Lüftung für Statistiken"""
        if room not in self._ventilation_stats:
            self._ventilation_stats[room] = []
        
        record = {
            'timestamp': datetime.now().isoformat(),
            'duration': duration_minutes,
            'score': score,
            'energy_saved': energy_saved,
            'climate_change': climate_change
        }
        
        self._ventilation_stats[room].append(record)
        
        # Behalte nur die letzten 50 Einträge pro Raum
        if len(self._ventilation_stats[room]) > 50:
            self._ventilation_stats[room] = self._ventilation_stats[room][-50:]
        
        # Aktualisiere letzte Lüftungszeit
        self._last_ventilation[room] = datetime.now()
        
        self._save_stats()
    
    def _get_room_stats(self, room: str) -> dict:
        """Hole Statistiken für einen Raum"""
        stats = self._ventilation_stats.get(room, [])
        
        if not stats:
            return {'count': 0, 'avg_score': None, 'avg_duration': None}
        
        scores = [s['score'] for s in stats if s.get('score') is not None]
        durations = [s['duration'] for s in stats if s.get('duration') is not None]
        
        return {
            'count': len(stats),
            'avg_score': sum(scores) / len(scores) if scores else None,
            'avg_duration': sum(durations) / len(durations) if durations else None,
            'last_scores': [s['score'] for s in stats[-5:] if s.get('score')]
        }
    
    def _compare_to_average(self, room: str, current_score: int) -> dict:
        """Vergleiche aktuelle Lüftung mit dem Durchschnitt"""
        stats = self._get_room_stats(room)
        
        if stats['avg_score'] is None or stats['count'] < 3:
            return None  # Nicht genug Daten
        
        avg = stats['avg_score']
        diff = current_score - avg
        percentile = sum(1 for s in self._ventilation_stats.get(room, []) 
                        if s.get('score', 0) < current_score) / max(stats['count'], 1) * 100
        
        if diff >= 15:
            text = f"🏆 Überdurchschnittlich! Besser als {int(percentile)}% deiner Lüftungen"
            emoji = "🏆"
        elif diff >= 5:
            text = f"📈 Über dem Durchschnitt ({int(avg)}%)"
            emoji = "📈"
        elif diff >= -5:
            text = f"📊 Im Durchschnitt ({int(avg)}%)"
            emoji = "📊"
        else:
            text = f"📉 Unter dem Durchschnitt ({int(avg)}%)"
            emoji = "📉"
        
        return {
            'text': text,
            'emoji': emoji,
            'percentile': int(percentile),
            'avg_score': int(avg),
            'diff': int(diff)
        }

    # ============================================================================
    # ENERGIE-BERECHNUNG
    # ============================================================================
    
    def _calculate_energy_impact(self, temp_diff: float, duration_minutes: int,
                                  outdoor_temp: float = None, room_size: str = 'medium') -> dict:
        """Berechnet den Energie-Impact der Lüftung
        
        Vereinfachte Berechnung basierend auf:
        - Temperaturänderung
        - Lüftungsdauer
        - Geschätzte Raumgröße
        
        Returns:
            Dict mit kWh, Kosten-Schätzung und Bewertung
        """
        # Raumvolumen-Schätzung (m³)
        room_volumes = {
            'small': 30,    # ~12m² Raum
            'medium': 50,   # ~20m² Raum
            'large': 80     # ~32m² Raum
        }
        volume = room_volumes.get(room_size, 50)
        
        # Luftdichte: ~1.2 kg/m³, spez. Wärmekapazität Luft: ~1.005 kJ/(kg·K)
        # Energie = Masse × spez. Wärme × Temperaturänderung
        # Q = V × ρ × c × ΔT
        
        air_density = 1.2  # kg/m³
        specific_heat = 1.005  # kJ/(kg·K)
        
        # Nur bei Temperaturverlust (Wärmeverlust) relevant
        if temp_diff >= 0:
            return {
                'kwh': 0,
                'cost': 0,
                'text': 'Kein Wärmeverlust',
                'emoji': '✅'
            }
        
        abs_temp_diff = abs(temp_diff)
        
        # Energie in kJ, dann in kWh umrechnen
        # Berücksichtige Luftaustauschrate (bei Stoßlüften ca. 50-100% pro 5 Min)
        air_exchange_factor = min(duration_minutes / 10, 1.5)  # Max 150% Austausch
        
        energy_kj = volume * air_density * specific_heat * abs_temp_diff * air_exchange_factor
        energy_kwh = energy_kj / 3600  # kJ zu kWh
        
        # Durchschnittlicher Gaspreis: ~0.10 EUR/kWh
        gas_price = 0.10
        cost = energy_kwh * gas_price
        
        # Bewertung
        if energy_kwh < 0.1:
            text = f"Minimal ({energy_kwh:.2f} kWh)"
            emoji = "✅"
        elif energy_kwh < 0.3:
            text = f"Gering ({energy_kwh:.2f} kWh ≈ {cost:.2f}€)"
            emoji = "👍"
        elif energy_kwh < 0.5:
            text = f"Moderat ({energy_kwh:.2f} kWh ≈ {cost:.2f}€)"
            emoji = "⚡"
        else:
            text = f"Hoch ({energy_kwh:.2f} kWh ≈ {cost:.2f}€)"
            emoji = "⚠️"
        
        return {
            'kwh': round(energy_kwh, 3),
            'cost': round(cost, 2),
            'text': text,
            'emoji': emoji
        }

    # ============================================================================
    # VERBESSERTE BENACHRICHTIGUNGEN - Hilfsmethoden
    # ============================================================================
    
    def _create_progress_bar(self, percentage: int, width: int = 10) -> str:
        """Erstellt einen grafischen Fortschrittsbalken"""
        filled = int(percentage / 100 * width)
        empty = width - filled
        return '▓' * filled + '░' * empty

    def _get_night_temperature_check(self, min_night_temp: float = 3.0) -> Optional[Dict]:
        """
        Prüft Wettervorhersage von jetzt bis 07:00 Uhr nächsten Morgens.
        Tiefsttemperatur muss >= min_night_temp bleiben für sicheres Nachtlüften.
        Wird nur bei Fensteröffnung zwischen 16–19 Uhr aufgerufen.
        """
        try:
            if not self.engine or not self.engine.weather:
                return None

            forecast_data = self.engine.weather.get_forecast()
            if not forecast_data or not forecast_data.get('forecasts'):
                return None

            now = datetime.now()
            # Ende: 07:00 Uhr nächsten Morgens
            if now.hour < 7:
                tonight_end = now.replace(hour=7, minute=0, second=0, microsecond=0)
            else:
                tonight_end = (now + timedelta(days=1)).replace(hour=7, minute=0, second=0, microsecond=0)

            night_forecasts = []
            for entry in forecast_data['forecasts']:
                try:
                    entry_time = datetime.strptime(entry['timestamp'], '%Y-%m-%d %H:%M:%S')
                except ValueError:
                    try:
                        entry_time = datetime.fromisoformat(entry['timestamp'])
                    except ValueError:
                        continue
                if now <= entry_time <= tonight_end:
                    night_forecasts.append({'time': entry_time, 'temp': entry['temperature']})

            if not night_forecasts:
                return None

            min_entry = min(night_forecasts, key=lambda f: f['temp'])
            return {
                'min_temp': round(min_entry['temp'], 1),
                'min_temp_at': min_entry['time'],
                'can_stay_open': min_entry['temp'] >= min_night_temp,
                'min_threshold': min_night_temp,
                'tonight_end': tonight_end
            }
        except Exception as e:
            logger.debug(f"Error in night temperature check: {e}")
            return None

    def _get_seasonal_tip(self, outdoor_temp: float, window_state: str = 'open') -> str:
        """Gibt jahreszeit-spezifische Lüftungstipps"""
        month = datetime.now().month
        hour = datetime.now().hour
        
        if outdoor_temp is None:
            return None
        
        if outdoor_temp < 0:
            if window_state == 'tilted':
                return "❄️ Bei Frost: Kippen vermeiden! Stoßlüften ist effizienter und spart Heizkosten."
            return "❄️ Bei Frost: Maximal 5 Min. Stoßlüften, dann Fenster schließen!"
        
        elif outdoor_temp < 5:
            return "🧣 Kalte Luft nimmt weniger Feuchtigkeit auf → kurz aber intensiv lüften"
        
        elif outdoor_temp < 15:
            return "🍂 Ideale Lüftungsbedingungen für guten Luftaustausch"
        
        elif outdoor_temp >= 25:
            if 6 <= hour <= 9:
                return "☀️ Morgens ist die beste Zeit - jetzt ausgiebig lüften!"
            elif 20 <= hour <= 23:
                return "🌙 Abends kühle Luft nutzen für angenehme Nachttemperatur"
            else:
                return "🌡️ Tagsüber besser geschlossen halten, morgens/abends lüften"
        
        else:
            return None
    
    def _get_air_quality_recommendation(self, co2: float = None, humidity: float = None) -> dict:
        """Gibt Luftqualitäts-Empfehlung basierend auf aktuellen Werten"""
        issues = []
        urgency = 'normal'  # normal, recommended, urgent
        
        if co2:
            if co2 > 2000:
                issues.append(('co2_critical', '🚨 CO₂ kritisch hoch!', 'urgent'))
                urgency = 'urgent'
            elif co2 > 1400:
                issues.append(('co2_high', '⚠️ CO₂ erhöht - Lüften empfohlen', 'recommended'))
                if urgency != 'urgent':
                    urgency = 'recommended'
            elif co2 > 1000:
                issues.append(('co2_elevated', '💨 CO₂ leicht erhöht', 'normal'))
        
        if humidity:
            if humidity > 75:
                issues.append(('humidity_high', '💧 Hohe Luftfeuchtigkeit - Schimmelgefahr!', 'urgent'))
                urgency = 'urgent'
            elif humidity > 65:
                issues.append(('humidity_elevated', '💧 Luftfeuchtigkeit erhöht', 'recommended'))
                if urgency != 'urgent':
                    urgency = 'recommended'
            elif humidity < 30:
                issues.append(('humidity_low', '🏜️ Luft sehr trocken', 'normal'))
        
        if not issues:
            return None
        
        return {
            'issues': issues,
            'urgency': urgency,
            'main_issue': issues[0][1],
            'all_texts': [i[1] for i in issues]
        }
    
    def _get_ventilation_goals(self, climate_start: dict, climate_now: dict) -> list:
        """Prüft welche Ziele erreicht wurden"""
        goals = []
        
        co2_start = climate_start.get('co2')
        co2_now = climate_now.get('co2')
        hum_start = climate_start.get('humidity')
        hum_now = climate_now.get('humidity')
        
        # CO2-Ziel: unter 800 ppm
        if co2_start and co2_now:
            if co2_now < 800:
                goals.append({'name': 'CO₂ unter 800 ppm', 'achieved': True, 'emoji': '✅'})
            elif co2_now < co2_start:
                goals.append({'name': 'CO₂ gesenkt', 'achieved': True, 'emoji': '✅'})
            else:
                goals.append({'name': 'CO₂ senken', 'achieved': False, 'emoji': '❌'})
        
        # Luftfeuchtigkeit-Ziel: 40-60%
        if hum_start and hum_now:
            if 40 <= hum_now <= 60:
                goals.append({'name': 'Optimale Feuchtigkeit (40-60%)', 'achieved': True, 'emoji': '✅'})
            elif hum_start > 60 and hum_now < hum_start:
                goals.append({'name': 'Feuchtigkeit gesenkt', 'achieved': True, 'emoji': '✅'})
            elif hum_start > 60:
                goals.append({'name': 'Feuchtigkeit senken', 'achieved': False, 'emoji': '⚠️'})
        
        return goals

    def _check_ventilation_too_long(self, duration_minutes: int, outdoor_temp: float) -> dict:
        """Prüft ob die Lüftung zu lang war (Energieverschwendung)"""
        if outdoor_temp is None:
            return None
        
        # Maximal empfohlene Dauer basierend auf Außentemperatur
        if outdoor_temp < 0:
            max_duration = 8
        elif outdoor_temp < 5:
            max_duration = 12
        elif outdoor_temp < 10:
            max_duration = 20
        else:
            max_duration = 30  # Im Sommer weniger kritisch
        
        if duration_minutes > max_duration * 2:
            return {
                'warning': True,
                'text': f'⏰ {duration_minutes} Min. ist bei {outdoor_temp:.0f}°C sehr lang!',
                'tip': f'Empfohlen: max. {max_duration} Min. bei dieser Temperatur',
                'emoji': '⚠️'
            }
        elif duration_minutes > max_duration:
            return {
                'warning': False,
                'text': f'⏰ Etwas länger als optimal ({max_duration} Min. empfohlen)',
                'tip': None,
                'emoji': '💡'
            }
        
        return None

    def get_status(self) -> dict:
        """Gibt den aktuellen Status zurück"""
        config = self._load_config()
        return {
            'running': self.running,
            'enabled': config.get('enabled', False),
            'check_interval': self.check_interval,
            'open_windows_tracked': len(self._open_windows),
            'notifications_sent': len(self._last_notifications),
            'rooms_with_stats': len(self._ventilation_stats),
            'last_ventilation': {room: ts.isoformat() for room, ts in self._last_ventilation.items()}
        }
