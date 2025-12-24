"""
Christmas Lights Controller - Steuerung der Weihnachtsbeleuchtung

Features:
- Zeitgesteuerte Ein/Ausschaltung
- Sonnenuntergang-basiertes Einschalten
- Wochenend-Verlängerung
- Anwesenheits-abhängige Steuerung
"""

import json
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional
import random
import os

from loguru import logger

# Setze Zeitzone für Deutschland (MEZ/MESZ)
try:
    import zoneinfo
    TIMEZONE = zoneinfo.ZoneInfo("Europe/Berlin")
except ImportError:
    # Fallback für ältere Python-Versionen
    TIMEZONE = None
    logger.warning("zoneinfo not available, using system timezone")

def get_local_time() -> datetime:
    """Gibt die aktuelle lokale Zeit zurück (Europe/Berlin)"""
    if TIMEZONE:
        return datetime.now(TIMEZONE)
    return datetime.now()

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

try:
    from astral import LocationInfo
    from astral.sun import sun
    ASTRAL_AVAILABLE = True
except ImportError:
    ASTRAL_AVAILABLE = False
    logger.warning("astral library not available - sunset feature disabled")


class ChristmasLightsController:
    """Steuert Weihnachtsbeleuchtung nach Zeitplan"""
    
    CONFIG_FILE = Path('data/christmas_config.json')
    
    def __init__(self, platform=None):
        self.platform = platform
        self.running = False
        self.thread = None
        self.lights_on = False
        self._last_action_time = None
        
        # Standard-Konfiguration
        self.config = {
            'enabled': False,
            'on_time': '16:00',
            'off_time': '23:00',
            'use_sunset': False,
            'start_date': '',
            'end_date': '',
            'devices': [],
            'device_labels': {},  # Benutzerdefinierte Namen für Geräte
            'device_schedules': {},  # Individuelle Zeitpläne pro Gerät {device_id: {on_time, off_time}}
            'presence_devices': [],  # Geräte die nur bei Anwesenheit leuchten
            'presence_only': False,
            'weekend_extended': False,
            'random_delay': True,
            'notifications_enabled': True,  # Push-Benachrichtigungen
            # Spezielle Zeiten für Adventssonntage und Heiligabend
            'special_days': {
                'advent_sundays': {
                    'enabled': False,
                    'on_time': '09:00',
                    'off_time': '23:30'
                },
                'christmas_eve': {
                    'enabled': False,
                    'on_time': '09:00',
                    'off_time': '01:00'
                }
            }
        }
        
        # Location für Sonnenuntergang (Berlin als Default) - nur wenn astral verfügbar
        if ASTRAL_AVAILABLE:
            self.location = LocationInfo("Berlin", "Germany", "Europe/Berlin", 52.52, 13.405)
        else:
            self.location = None
        
        # Track device states to avoid redundant commands
        self._device_states: Dict[str, bool] = {}  # device_id -> is_on
        
        # Manuelle Überschreibung - verhindert automatisches Schalten bis zur Ausschaltzeit
        self._manual_override_until: Optional[datetime] = None
        self._manual_override_keep_on: bool = False  # True = AN halten, False = AUS halten
        
        # Geräte-spezifische Overrides: {device_id: {'until': datetime, 'keep_on': bool}}
        self._device_overrides: Dict[str, dict] = {}
        
        # Notification cooldown (verhindert Spam)
        self._last_notification_time: Optional[datetime] = None
        
        # Lade gespeicherte Config
        self._load_config()
        
        logger.info(f"Christmas Lights Controller initialized (enabled: {self.config['enabled']})")
    
    def _load_config(self):
        """Lade Konfiguration aus Datei"""
        if self.CONFIG_FILE.exists():
            try:
                with open(self.CONFIG_FILE, 'r') as f:
                    saved_config = json.load(f)
                    self.config.update(saved_config)
                    logger.debug(f"Christmas config loaded: {len(self.config['devices'])} devices")
            except Exception as e:
                logger.error(f"Error loading christmas config: {e}")
    
    def _save_config(self):
        """Speichere Konfiguration in Datei"""
        try:
            self.CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(self.CONFIG_FILE, 'w') as f:
                json.dump(self.config, f, indent=2)
            logger.debug("Christmas config saved")
        except Exception as e:
            logger.error(f"Error saving christmas config: {e}")
    
    def update_config(self, new_config: Dict):
        """Aktualisiere Konfiguration"""
        self.config.update(new_config)
        self._save_config()
        logger.info(f"Christmas config updated: enabled={self.config['enabled']}, "
                   f"devices={len(self.config['devices'])}")
    
    def get_config(self) -> Dict:
        """Gibt aktuelle Konfiguration zurück"""
        return self.config.copy()
    
    def get_device_state(self, device_id: str) -> Optional[bool]:
        """Öffentliche Methode: Gibt den aktuellen Status eines Geräts zurück.
        Fragt zuerst den echten Status von Homey ab, dann Fallback auf Cache."""
        # Versuche echten Status von Homey zu holen
        real_state = self._get_device_state(device_id)
        if real_state is not None:
            # Update cache mit echtem Status
            self._device_states[device_id] = real_state
            return real_state
        # Fallback auf Cache
        return self._device_states.get(device_id)
    
    def get_all_device_states(self) -> Dict[str, bool]:
        """Gibt alle bekannten Gerätezustände zurück"""
        return self._device_states.copy()
    
    def _get_pushover_credentials(self):
        """Hole Pushover Credentials aus config.yaml"""
        try:
            import yaml
            config_path = Path('config/config.yaml')
            if config_path.exists():
                with open(config_path, 'r') as f:
                    full_config = yaml.safe_load(f) or {}
                    notifications = full_config.get('notifications', {})
                    pushover = notifications.get('pushover', {})
                    # Unterstütze beide Varianten: api_token (neu) und api_key (alt)
                    api_key = pushover.get('api_token') or pushover.get('api_key', '')
                    user_key = pushover.get('user_key', '')
                    return api_key, user_key
        except Exception as e:
            logger.debug(f"Could not load pushover credentials: {e}")
        return '', ''
    
    def _send_notification(self, title: str, message: str):
        """Sende Push-Benachrichtigung via Pushover"""
        if not self.config.get('notifications_enabled', True):
            return
        
        if not REQUESTS_AVAILABLE:
            logger.debug("requests library not available for notifications")
            return
        
        # Cooldown: Max eine Notification pro 5 Minuten
        if self._last_notification_time:
            if get_local_time() - self._last_notification_time < timedelta(minutes=5):
                logger.debug("Notification skipped (cooldown)")
                return
        
        api_key, user_key = self._get_pushover_credentials()
        if not api_key or not user_key:
            logger.debug("Pushover credentials not configured")
            return
        
        try:
            response = requests.post(
                'https://api.pushover.net/1/messages.json',
                data={
                    'token': api_key,
                    'user': user_key,
                    'title': title,
                    'message': message,
                    'priority': 0
                },
                timeout=10
            )
            if response.status_code == 200:
                self._last_notification_time = get_local_time()
                logger.info(f"🔔 Christmas notification sent: {title}")
            else:
                logger.warning(f"Pushover notification failed: {response.status_code}")
        except Exception as e:
            logger.error(f"Error sending notification: {e}")
    
    def start(self):
        """Startet den Background-Thread"""
        if self.running:
            return
        
        self.running = True
        
        # Initialisiere Gerätezustände beim Start, um Benachrichtigungs-Spam zu vermeiden
        self._initialize_device_states()
        
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        logger.info("Christmas Lights Controller started")
    
    def _initialize_device_states(self):
        """Initialisiert die Gerätezustände von der Plattform"""
        devices = self.config.get('devices', [])
        if not devices or not self.platform:
            return
        
        try:
            all_states = self.platform.get_states() or {}
            for device_id in devices:
                state = self._get_device_state(device_id)
                if state is not None:
                    self._device_states[device_id] = state
                    device_label = self._get_device_label(device_id)
                    logger.debug(f"🎄 Initialized {device_label}: {'ON' if state else 'OFF'}")
        except Exception as e:
            logger.warning(f"Could not initialize device states: {e}")
    
    def stop(self):
        """Stoppt den Background-Thread"""
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
        logger.info("Christmas Lights Controller stopped")
    
    def _run(self):
        """Haupt-Loop - prüft jede Minute"""
        while self.running:
            try:
                if self.config['enabled']:
                    self._check_schedule()
                else:
                    logger.debug("🎄 Christmas lights disabled in config")
            except Exception as e:
                logger.error(f"Error in christmas lights loop: {e}")
            
            # Prüfe alle 60 Sekunden
            time.sleep(60)
    
    def _check_schedule(self):
        """Prüft ob Lichter ein- oder ausgeschaltet werden sollen"""
        now = get_local_time()
        
        # Debug: Zeige aktuelle Konfiguration
        logger.debug(f"🎄 Check schedule at {now.strftime('%H:%M:%S')}")
        logger.debug(f"🎄 Config: on_time={self.config.get('on_time')}, off_time={self.config.get('off_time')}, use_sunset={self.config.get('use_sunset')}")
        logger.debug(f"🎄 Devices configured: {len(self.config.get('devices', []))}")
        
        # Prüfe manuelle Überschreibung
        if self._manual_override_until:
            if now < self._manual_override_until:
                # Override aktiv - prüfe ob Lichter AN oder AUS gehalten werden sollen
                if self._manual_override_keep_on:
                    # Manuell eingeschaltet - stelle sicher, dass Lichter AN bleiben
                    logger.debug(f"🎄 Manual ON override active until {self._manual_override_until.strftime('%H:%M')} - keeping lights ON")
                    # Stelle sicher, dass alle Geräte AN sind
                    for device_id in self.config.get('devices', []):
                        if self._device_states.get(device_id) != True:
                            self._turn_device_on(device_id)
                else:
                    # Manuell ausgeschaltet - nichts tun
                    logger.debug(f"🎄 Manual OFF override active until {self._manual_override_until.strftime('%H:%M')} - keeping lights OFF")
                return  # Nichts weiter tun während Override aktiv ist
            else:
                # Override abgelaufen
                if self._manual_override_keep_on:
                    logger.info("🎄 Manual ON override expired - turning lights OFF")
                    # Lichter ausschalten da Ausschaltzeit erreicht
                    self._turn_all_lights_off("Manual override expired")
                else:
                    logger.info("🎄 Manual OFF override expired, resuming automatic schedule")
                self._manual_override_until = None
                self._manual_override_keep_on = False
        
        # Prüfe Datumsgrenzen
        if not self._is_within_date_range(now):
            if self.lights_on:
                self._turn_all_lights_off("Outside date range")
            return
        
        # Prüfe Anwesenheit (global)
        someone_home = self._is_someone_home()
        
        # Falls globale Anwesenheitssteuerung aktiv und niemand zuhause
        if self.config['presence_only'] and not someone_home:
            if self.lights_on:
                self._turn_all_lights_off("No one home")
            return
        
        devices = self.config.get('devices', [])
        device_schedules = self.config.get('device_schedules', {})
        presence_devices = self.config.get('presence_devices', [])  # Geräte mit Anwesenheitssteuerung
        current_time = now.time()
        
        any_on = False
        turned_on_count = 0
        turned_off_count = 0
        turned_on_names = []
        turned_off_names = []
        
        for device_id in devices:
            # Prüfe zuerst geräte-spezifischen Override
            device_override = self._device_overrides.get(device_id)
            if device_override:
                if now < device_override['until']:
                    # Override aktiv für dieses Gerät
                    device_label = self._get_device_label(device_id)
                    if device_override['keep_on']:
                        # Gerät soll AN bleiben
                        if self._device_states.get(device_id) != True:
                            self._turn_device_on(device_id)
                        logger.debug(f"🎄 {device_label}: Manual ON override until {device_override['until'].strftime('%H:%M')}")
                    else:
                        # Gerät soll AUS bleiben
                        if self._device_states.get(device_id) != False:
                            self._turn_device_off(device_id)
                        logger.debug(f"🎄 {device_label}: Manual OFF override until {device_override['until'].strftime('%H:%M')}")
                    if device_override['keep_on']:
                        any_on = True
                    continue  # Nächstes Gerät, dieses wird nicht vom Scheduler beeinflusst
                else:
                    # Override abgelaufen - entfernen
                    device_label = self._get_device_label(device_id)
                    logger.info(f"🎄 Device override expired for {device_label}")
                    del self._device_overrides[device_id]
            
            # Hole individuelle Zeitplan oder Standard
            schedule = device_schedules.get(device_id, {})
            
            # Einschaltzeit für dieses Gerät
            on_time = self._get_device_on_time(now, schedule)
            off_time = self._get_device_off_time(now, schedule)
            
            # Entscheide ob Gerät an sein soll
            should_be_on = False
            
            if on_time <= off_time:
                # Normaler Fall: z.B. 16:00 - 23:00
                should_be_on = on_time <= current_time <= off_time
            else:
                # Über Mitternacht: z.B. 16:00 - 00:30
                should_be_on = current_time >= on_time or current_time <= off_time
            
            # Hole den Gerätenamen (aus Plattform oder Config)
            device_label = self._get_device_label(device_id)
            
            # Prüfe individuelle Anwesenheitssteuerung für dieses Gerät
            device_has_presence_control = device_id in presence_devices
            if device_has_presence_control and not someone_home:
                # Dieses Gerät soll nur bei Anwesenheit leuchten - ausschalten
                should_be_on = False
                logger.debug(f"🎄 {device_label}: Anwesenheitssteuerung aktiv, niemand zuhause -> AUS")
            else:
                logger.debug(f"🎄 {device_label}: on={on_time}, off={off_time}, now={current_time}, should_be_on={should_be_on}")
            
            # Track state changes for notifications
            # was_on kann None (unbekannt), True oder False sein
            was_on = self._device_states.get(device_id)
            
            if should_be_on:
                any_on = True
                # Schalte dieses Gerät ein (falls nicht schon an)
                self._turn_device_on(device_id)
                # Nur benachrichtigen wenn Status sich wirklich ändert (was_on war explizit False)
                # Bei None (unbekannt) keine Benachrichtigung - vermeidet Spam beim Start
                if was_on is False:
                    turned_on_count += 1
                    turned_on_names.append(device_label)
            else:
                # Schalte dieses Gerät aus (falls nicht schon aus)
                self._turn_device_off(device_id)
                # Nur benachrichtigen wenn Status sich wirklich ändert (was_on war explizit True)
                # Bei None (unbekannt) keine Benachrichtigung - vermeidet Spam beim Start
                if was_on is True:
                    turned_off_count += 1
                    turned_off_names.append(device_label)
        
        # Sende Benachrichtigungen für Statusänderungen
        if turned_on_count > 0:
            names = ", ".join(turned_on_names[:3])
            if turned_on_count > 3:
                names += f" (+{turned_on_count - 3})"
            self._send_notification(
                "🎄 Weihnachtsbeleuchtung AN",
                f"{turned_on_count} Gerät(e) eingeschaltet: {names}"
            )
        
        if turned_off_count > 0:
            names = ", ".join(turned_off_names[:3])
            if turned_off_count > 3:
                names += f" (+{turned_off_count - 3})"
            self._send_notification(
                "🌙 Weihnachtsbeleuchtung AUS",
                f"{turned_off_count} Gerät(e) ausgeschaltet: {names}"
            )
        
        self.lights_on = any_on
    
    def _get_device_on_time(self, now: datetime, schedule: dict):
        """Berechnet Einschaltzeit für ein Gerät (mit Sonnenuntergang-Option und speziellen Tagen)"""
        # Prüfe spezielle Tage (Heiligabend hat Priorität vor Adventssonntagen)
        special_days_config = self.config.get('special_days', {})

        if self._is_christmas_eve(now):
            christmas_eve_config = special_days_config.get('christmas_eve', {})
            if christmas_eve_config.get('enabled', False):
                try:
                    t_str = christmas_eve_config.get('on_time', '09:00')
                    logger.debug(f"🎄 Heiligabend erkannt - verwende spezielle Zeit: {t_str}")
                    if len(t_str) == 5:
                        return datetime.strptime(t_str, '%H:%M').time()
                    elif len(t_str) == 8:
                        return datetime.strptime(t_str, '%H:%M:%S').time()
                except ValueError:
                    logger.warning(f"Invalid christmas_eve on_time format: {t_str}")

        advent_sunday = self._is_advent_sunday(now)
        if advent_sunday > 0:
            advent_config = special_days_config.get('advent_sundays', {})
            if advent_config.get('enabled', False):
                try:
                    t_str = advent_config.get('on_time', '09:00')
                    logger.debug(f"🎄 {advent_sunday}. Advent erkannt - verwende spezielle Zeit: {t_str}")
                    if len(t_str) == 5:
                        return datetime.strptime(t_str, '%H:%M').time()
                    elif len(t_str) == 8:
                        return datetime.strptime(t_str, '%H:%M:%S').time()
                except ValueError:
                    logger.warning(f"Invalid advent_sundays on_time format: {t_str}")

        # Individuelle Zeit hat Vorrang vor globaler Zeit, aber nicht vor speziellen Tagen
        if schedule.get('on_time'):
            try:
                t_str = schedule['on_time']
                if len(t_str) == 5: # HH:MM
                    return datetime.strptime(t_str, '%H:%M').time()
                elif len(t_str) == 8: # HH:MM:SS
                    return datetime.strptime(t_str, '%H:%M:%S').time()
            except ValueError:
                logger.warning(f"Invalid on_time format: {schedule.get('on_time')}")
                pass

        # Fallback: globale Einstellung
        if self.config['use_sunset'] and ASTRAL_AVAILABLE and self.location:
            try:
                s = sun(self.location.observer, date=now.date())
                sunset = s['sunset'].time()
                # 15 Minuten vor Sonnenuntergang
                sunset_dt = datetime.combine(now.date(), sunset) - timedelta(minutes=15)
                return sunset_dt.time()
            except Exception as e:
                logger.debug(f"Could not calculate sunset: {e}")

        # Fallback: konfigurierte Zeit
        try:
            t_str = self.config['on_time']
            if len(t_str) == 5:
                return datetime.strptime(t_str, '%H:%M').time()
            elif len(t_str) == 8:
                return datetime.strptime(t_str, '%H:%M:%S').time()
            return datetime.strptime(t_str, '%H:%M').time()
        except ValueError:
            return datetime.strptime('16:00', '%H:%M').time()
    
    def _get_device_off_time(self, now: datetime, schedule: dict):
        """Berechnet Ausschaltzeit für ein Gerät (mit Wochenend-Verlängerung und speziellen Tagen)"""
        # Prüfe spezielle Tage (Heiligabend hat Priorität vor Adventssonntagen)
        special_days_config = self.config.get('special_days', {})

        if self._is_christmas_eve(now):
            christmas_eve_config = special_days_config.get('christmas_eve', {})
            if christmas_eve_config.get('enabled', False):
                try:
                    t_str = christmas_eve_config.get('off_time', '01:00')
                    logger.debug(f"🎄 Heiligabend erkannt - verwende spezielle Ausschaltzeit: {t_str}")
                    if len(t_str) == 5:
                        return datetime.strptime(t_str, '%H:%M').time()
                    elif len(t_str) == 8:
                        return datetime.strptime(t_str, '%H:%M:%S').time()
                except ValueError:
                    logger.warning(f"Invalid christmas_eve off_time format: {t_str}")

        advent_sunday = self._is_advent_sunday(now)
        if advent_sunday > 0:
            advent_config = special_days_config.get('advent_sundays', {})
            if advent_config.get('enabled', False):
                try:
                    t_str = advent_config.get('off_time', '23:30')
                    logger.debug(f"🎄 {advent_sunday}. Advent erkannt - verwende spezielle Ausschaltzeit: {t_str}")
                    if len(t_str) == 5:
                        return datetime.strptime(t_str, '%H:%M').time()
                    elif len(t_str) == 8:
                        return datetime.strptime(t_str, '%H:%M:%S').time()
                except ValueError:
                    logger.warning(f"Invalid advent_sundays off_time format: {t_str}")

        # Individuelle Zeit hat Vorrang vor globaler Zeit, aber nicht vor speziellen Tagen
        if schedule.get('off_time'):
            try:
                t_str = schedule['off_time']
                if len(t_str) == 5:
                    return datetime.strptime(t_str, '%H:%M').time()
                elif len(t_str) == 8:
                    return datetime.strptime(t_str, '%H:%M:%S').time()
            except ValueError:
                logger.warning(f"Invalid off_time format: {schedule.get('off_time')}")
                pass

        # Fallback: globale Einstellung
        base_time = self.config['off_time']

        # Wochenend-Verlängerung
        if self.config['weekend_extended'] and now.weekday() >= 4:  # Fr, Sa, So
            base_time = '00:00'  # Bis Mitternacht

        try:
            if len(base_time) == 5:
                return datetime.strptime(base_time, '%H:%M').time()
            elif len(base_time) == 8:
                return datetime.strptime(base_time, '%H:%M:%S').time()
            return datetime.strptime(base_time, '%H:%M').time()
        except ValueError:
            return datetime.strptime('23:00', '%H:%M').time()
    
    def _get_device_state(self, device_id: str) -> Optional[bool]:
        """Ermittelt den aktuellen Status eines Geräts vom Platform-Provider"""
        if not self.platform:
            return self._device_states.get(device_id)
            
        try:
            # Hole alle Geräte-Status
            all_states = self.platform.get_states() or {}
            
            # get_states kann Dict oder Liste sein
            if isinstance(all_states, dict):
                device = all_states.get(device_id, {})
            else:
                device = next((d for d in all_states if d.get('id') == device_id), None)
            
            if device:
                # Prüfe capabilitiesObj (Homey-Struktur)
                caps_obj = device.get('capabilitiesObj', {})
                if 'onoff' in caps_obj:
                    return caps_obj['onoff'].get('value', False)
                
                # Fallback: attributes.capabilities
                attrs = device.get('attributes', {})
                caps = attrs.get('capabilities', {})
                if isinstance(caps, dict) and 'onoff' in caps:
                    return caps['onoff'].get('value', False)
            
            # Fallback auf Cache
            return self._device_states.get(device_id)
        except Exception as e:
            logger.debug(f"Error getting device state for {device_id}: {e}")
            return self._device_states.get(device_id)

    def _get_device_label(self, device_id: str) -> str:
        """Ermittelt den Namen eines Geräts - priorisiert user-definierte Labels"""
        # 1. Prüfe ob ein benutzerdefinierter Name konfiguriert ist
        user_label = self.config.get('device_labels', {}).get(device_id)
        if user_label:
            return user_label
        
        # 2. Versuche den Namen von der Plattform zu holen
        if self.platform:
            try:
                all_states = self.platform.get_states() or {}
                
                if isinstance(all_states, dict):
                    device = all_states.get(device_id, {})
                else:
                    device = next((d for d in all_states if d.get('id') == device_id), None)
                
                if device:
                    # Homey verwendet 'name' direkt
                    name = device.get('name')
                    if name:
                        return name
                    
                    # Home Assistant hat oft friendly_name in attributes
                    attrs = device.get('attributes', {})
                    friendly_name = attrs.get('friendly_name')
                    if friendly_name:
                        return friendly_name
            except Exception as e:
                logger.debug(f"Error getting device name for {device_id}: {e}")
        
        # 3. Fallback: gekürzte Device-ID (etwas länger für bessere Lesbarkeit)
        return device_id[:12] if len(device_id) > 12 else device_id

    def _turn_device_on(self, device_id: str):
        """Schaltet ein einzelnes Gerät ein (nur wenn nicht schon an)"""
        # Prüfe echten Status
        current_state = self._get_device_state(device_id)
        
        if current_state is True:
            # Update cache just in case
            self._device_states[device_id] = True
            return  # Schon an
        
        try:
            if self.platform:
                self.platform.turn_on(device_id)
                self._device_states[device_id] = True
                device_label = self._get_device_label(device_id)
                logger.info(f"🎄 Christmas ON: {device_label}")
        except Exception as e:
            logger.error(f"Error turning on christmas device {device_id}: {e}")
    
    def _turn_device_off(self, device_id: str):
        """Schaltet ein einzelnes Gerät aus (nur wenn nicht schon aus)"""
        # Prüfe echten Status
        current_state = self._get_device_state(device_id)
        
        if current_state is False:
            # Update cache just in case
            self._device_states[device_id] = False
            return  # Schon aus
        
        try:
            if self.platform:
                self.platform.turn_off(device_id)
                self._device_states[device_id] = False
                device_label = self._get_device_label(device_id)
                logger.info(f"🎄 Christmas OFF: {device_label}")
        except Exception as e:
            logger.error(f"Error turning off christmas device {device_id}: {e}")
    
    def toggle_single_device_manual(self, device_id: str, turn_on: bool) -> bool:
        """Schaltet ein einzelnes Gerät manuell mit geräte-spezifischem Override
        
        Setzt einen Override nur für dieses eine Gerät bis zur Ausschaltzeit.
        Andere Geräte werden vom Scheduler normal behandelt.
        """
        if not self.platform:
            logger.warning("Cannot toggle device - platform not available")
            return False
        
        try:
            device_label = self._get_device_label(device_id)
            now = get_local_time()
            
            if turn_on:
                self.platform.turn_on(device_id)
                self._device_states[device_id] = True
                
                # Geräte-spezifischen Override setzen bis zur Ausschaltzeit
                off_time = self._get_device_off_time(now, self.config.get('device_schedules', {}).get(device_id, {}))
                override_until = datetime.combine(now.date(), off_time)
                if TIMEZONE:
                    override_until = override_until.replace(tzinfo=TIMEZONE)
                
                # Falls Ausschaltzeit schon vorbei ist
                if override_until <= now:
                    override_until = datetime.combine(now.date() + timedelta(days=1), off_time)
                    if TIMEZONE:
                        override_until = override_until.replace(tzinfo=TIMEZONE)
                
                self._device_overrides[device_id] = {
                    'until': override_until,
                    'keep_on': True
                }
                logger.info(f"🎄 Manual ON: {device_label} (override until {override_until.strftime('%H:%M')})")
            else:
                self.platform.turn_off(device_id)
                self._device_states[device_id] = False
                
                # Geräte-spezifischen Override setzen bis zur nächsten Einschaltzeit
                on_time = self._get_device_on_time(now, self.config.get('device_schedules', {}).get(device_id, {}))
                override_until = datetime.combine(now.date(), on_time)
                if TIMEZONE:
                    override_until = override_until.replace(tzinfo=TIMEZONE)
                
                # Falls Einschaltzeit schon vorbei ist, morgen
                if override_until <= now:
                    override_until = datetime.combine(now.date() + timedelta(days=1), on_time)
                    if TIMEZONE:
                        override_until = override_until.replace(tzinfo=TIMEZONE)
                
                self._device_overrides[device_id] = {
                    'until': override_until,
                    'keep_on': False
                }
                logger.info(f"🎄 Manual OFF: {device_label} (override until {override_until.strftime('%H:%M')})")
            
            return True
        except Exception as e:
            logger.error(f"Error toggling christmas device {device_id}: {e}")
            return False
    
    def _turn_all_lights_off(self, reason: str = ""):
        """Schaltet alle Weihnachtslichter aus"""
        devices = self.config.get('devices', [])
        if not devices:
            return
        
        affected = 0
        for device_id in devices:
            try:
                if self.platform:
                    self.platform.turn_off(device_id)
                    affected += 1
            except Exception as e:
                logger.error(f"Error turning off christmas device {device_id}: {e}")
        
        self.lights_on = False
        self._last_action_time = get_local_time()
        logger.info(f"🎄 Christmas lights OFF ({affected} devices) - {reason}")
    
    def _is_advent_sunday(self, now: datetime) -> int:
        """Prüft ob heute ein Adventssonntag ist und gibt die Nummer zurück (1-4), sonst 0"""
        # Advent = 4 Sonntage vor Weihnachten (25.12)
        # 4. Advent = letzter Sonntag vor dem 25.12
        # 1. Advent = 4 Wochen vor dem 4. Advent

        if now.weekday() != 6:  # 6 = Sonntag
            return 0

        year = now.year
        christmas = datetime(year, 12, 25, tzinfo=now.tzinfo)

        # Finde den 4. Advent (letzter Sonntag vor Weihnachten)
        days_until_christmas = (christmas - now).days
        christmas_weekday = christmas.weekday()

        # Berechne wie viele Tage von Weihnachten zurück zum letzten Sonntag
        if christmas_weekday == 6:  # Weihnachten ist Sonntag
            fourth_advent = christmas - timedelta(days=7)
        else:
            days_back = (christmas_weekday + 1) % 7
            fourth_advent = christmas - timedelta(days=days_back)

        # Berechne die anderen Adventssonntage
        third_advent = fourth_advent - timedelta(days=7)
        second_advent = fourth_advent - timedelta(days=14)
        first_advent = fourth_advent - timedelta(days=21)

        # Prüfe ob heute einer der Adventssonntage ist
        today_date = now.date()
        if today_date == fourth_advent.date():
            return 4
        elif today_date == third_advent.date():
            return 3
        elif today_date == second_advent.date():
            return 2
        elif today_date == first_advent.date():
            return 1

        return 0

    def _is_christmas_eve(self, now: datetime) -> bool:
        """Prüft ob heute Heiligabend (24.12) ist"""
        return now.month == 12 and now.day == 24

    def _is_within_date_range(self, now: datetime) -> bool:
        """Prüft ob aktuelles Datum im Weihnachtszeitraum liegt"""
        start_str = self.config.get('start_date', '')
        end_str = self.config.get('end_date', '')

        if not start_str or not end_str:
            # Kein Datumslimit gesetzt -> immer aktiv
            return True

        try:
            start_date = datetime.strptime(start_str, '%Y-%m-%d').date()
            end_date = datetime.strptime(end_str, '%Y-%m-%d').date()
            return start_date <= now.date() <= end_date
        except ValueError:
            return True
    
    def _get_random_delay(self) -> int:
        """Gibt zufällige Verzögerung in Sekunden zurück (0-300s = 0-5min)"""
        return random.randint(0, 300)
    
    def _is_someone_home(self) -> bool:
        """Prüft ob jemand zuhause ist - nutzt kombinierte Daten aus Homey UND Home Assistant"""
        
        # Zuerst: Versuche die zentrale Presence-API (kombiniert Homey + Home Assistant)
        try:
            import requests
            response = requests.get('http://localhost:8080/api/presence', timeout=2)
            if response.status_code == 200:
                data = response.json()
                if data.get('success'):
                    anyone_home = data.get('anyone_home', False)
                    total_home = data.get('total_home', 0)
                    logger.debug(f"🎄 Presence check via API: anyone_home={anyone_home}, total={total_home}")
                    return anyone_home
        except Exception as e:
            logger.debug(f"🎄 Presence API not available, falling back to Homey: {e}")
        
        # Fallback: Direkt Homey prüfen
        if not self.platform:
            return True  # Fallback: annehmen ja
        
        try:
            # Versuche Homey-Benutzer zu prüfen
            if hasattr(self.platform, 'get_users'):
                users = self.platform.get_users() or []
                for user in users:
                    if user.get('present', False):
                        return True
                return False
            
            # Fallback: Präsenz-Sensoren prüfen
            devices = self.platform.get_states() or []
            for device in devices:
                if not isinstance(device, dict):
                    continue
                name = device.get('name', '').lower()
                if 'presence' in name or 'anwesen' in name:
                    caps = device.get('capabilitiesObj', {})
                    if 'onoff' in caps and caps['onoff'].get('value'):
                        return True
        except Exception as e:
            logger.debug(f"Error checking presence: {e}")
        
        return True  # Fallback
    
    def test_lights(self, turn_on: bool) -> int:
        """Testet die Lichter (manuelles Ein/Ausschalten)"""
        devices = self.config.get('devices', [])
        affected = 0
        
        for device_id in devices:
            try:
                if self.platform:
                    if turn_on:
                        self.platform.turn_on(device_id)
                        self._device_states[device_id] = True
                    else:
                        self.platform.turn_off(device_id)
                        self._device_states[device_id] = False
                    affected += 1
            except Exception as e:
                logger.error(f"Error testing christmas device {device_id}: {e}")
        
        self.lights_on = turn_on
        
        # Bei manuellem AUS: Override setzen bis zur nächsten regulären Ausschaltzeit
        # Das verhindert, dass der automatische Scheduler sofort wieder einschaltet
        if not turn_on:
            now = get_local_time()
            off_time = self._get_device_off_time(now, {})
            # Override bis zur Ausschaltzeit + 1 Minute (damit der nächste Zyklus normal startet)
            override_until = datetime.combine(now.date(), off_time) + timedelta(minutes=1)
            if TIMEZONE:
                override_until = override_until.replace(tzinfo=TIMEZONE)
            # Falls Ausschaltzeit schon vorbei ist, Override bis morgen früh
            if override_until <= now:
                override_until = datetime.combine(now.date() + timedelta(days=1), datetime.strptime('06:00', '%H:%M').time())
                if TIMEZONE:
                    override_until = override_until.replace(tzinfo=TIMEZONE)
            self._manual_override_until = override_until
            self._manual_override_keep_on = False  # Lichter sollen AUS bleiben
            logger.info(f"🎄 Manual OFF override set until {override_until.strftime('%H:%M')}")
            
            # Push-Benachrichtigung für manuelles Ausschalten
            self._send_notification(
                "🌙 Weihnachtsbeleuchtung manuell AUS",
                f"{affected} Gerät(e) ausgeschaltet. Automatik pausiert bis {override_until.strftime('%H:%M')} Uhr."
            )
        else:
            # Bei manuellem AN: Override setzen bis zur nächsten Ausschaltzeit
            # Lichter bleiben AN bis zur regulären Ausschaltzeit
            now = get_local_time()
            off_time = self._get_device_off_time(now, {})
            override_until = datetime.combine(now.date(), off_time)
            if TIMEZONE:
                override_until = override_until.replace(tzinfo=TIMEZONE)
            
            # Falls Ausschaltzeit schon vorbei ist (z.B. nach 23:00), bis morgen
            if override_until <= now:
                # Prüfe ob Ausschaltzeit über Mitternacht geht
                off_time_str = self.config.get('off_time', '23:00')
                off_hour = int(off_time_str.split(':')[0])
                if off_hour < 12:  # Ausschaltzeit ist nach Mitternacht (z.B. 00:30)
                    override_until = datetime.combine(now.date() + timedelta(days=1), off_time)
                else:
                    # Reguläre Ausschaltzeit morgen
                    override_until = datetime.combine(now.date() + timedelta(days=1), off_time)
                if TIMEZONE:
                    override_until = override_until.replace(tzinfo=TIMEZONE)
            
            self._manual_override_until = override_until
            self._manual_override_keep_on = True  # Lichter sollen AN bleiben
            logger.info(f"🎄 Manual ON override set until {override_until.strftime('%H:%M')} - lights will stay ON")
            
            # Push-Benachrichtigung für manuelles Einschalten
            self._send_notification(
                "🎄 Weihnachtsbeleuchtung manuell AN",
                f"{affected} Gerät(e) eingeschaltet. Bleiben AN bis {override_until.strftime('%H:%M')} Uhr."
            )
        
        logger.info(f"🎄 Christmas lights TEST: {'ON' if turn_on else 'OFF'} ({affected} devices)")
        return affected
    
    def get_status(self) -> Dict:
        """Gibt aktuellen Status zurück"""
        now = get_local_time()
        
        # Berechne nächste Aktion basierend auf Standard-Zeit
        next_action = "--"
        if self.config['enabled']:
            on_time = self._get_device_on_time(now, {})
            off_time = self._get_device_off_time(now, {})
            
            if self.lights_on:
                next_action = f"Aus um {off_time.strftime('%H:%M')}"
            else:
                next_action = f"An um {on_time.strftime('%H:%M')}"
                if self.config['use_sunset']:
                    next_action += " (Dämmerung)"
        
        # Override-Info hinzufügen
        manual_override_info = None
        if self._manual_override_until:
            override_type = "AN" if self._manual_override_keep_on else "AUS"
            manual_override_info = {
                'active': True,
                'type': override_type,
                'until': self._manual_override_until.strftime('%H:%M'),
                'until_iso': self._manual_override_until.isoformat()
            }
        
        # Debug-Info für Troubleshooting
        debug_info = {
            'current_time': now.strftime('%H:%M:%S'),
            'on_time_raw': self.config.get('on_time'),
            'off_time_raw': self.config.get('off_time'),
            'on_time_calculated': on_time.strftime('%H:%M') if on_time else None,
            'off_time_calculated': off_time.strftime('%H:%M') if off_time else None,
            'use_sunset': self.config.get('use_sunset', False),
            'start_date': self.config.get('start_date'),
            'end_date': self.config.get('end_date'),
            'device_count': len(self.config.get('devices', [])),
            'devices': self.config.get('devices', []),
            'device_states': self._device_states,
            'controller_running': self.running
        }
        
        return {
            'enabled': self.config['enabled'],
            'lights_on': self.lights_on,
            'next_action': next_action,
            'active_devices': len(self.config.get('devices', [])),
            'last_action': self._last_action_time.isoformat() if self._last_action_time else None,
            'within_date_range': self._is_within_date_range(now),
            'device_schedules': self.config.get('device_schedules', {}),
            'manual_override': manual_override_info,
            'debug': debug_info
        }
