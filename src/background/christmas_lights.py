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
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional
import random

from loguru import logger

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
            'presence_only': False,
            'weekend_extended': False,
            'random_delay': True,
            'notifications_enabled': True  # Push-Benachrichtigungen
        }
        
        # Location für Sonnenuntergang (Berlin als Default)
        self.location = LocationInfo("Berlin", "Germany", "Europe/Berlin", 52.52, 13.405)
        
        # Track device states to avoid redundant commands
        self._device_states: Dict[str, bool] = {}  # device_id -> is_on
        
        # Manuelle Überschreibung - verhindert automatisches Wiedereinschalten bis zur nächsten Ausschaltzeit
        self._manual_override_until: Optional[datetime] = None
        
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
                    return pushover.get('api_key', ''), pushover.get('user_key', '')
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
            if datetime.now() - self._last_notification_time < timedelta(minutes=5):
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
                self._last_notification_time = datetime.now()
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
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        logger.info("Christmas Lights Controller started")
    
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
            except Exception as e:
                logger.error(f"Error in christmas lights loop: {e}")
            
            # Prüfe alle 60 Sekunden
            time.sleep(60)
    
    def _check_schedule(self):
        """Prüft ob Lichter ein- oder ausgeschaltet werden sollen"""
        now = datetime.now()
        
        # Prüfe manuelle Überschreibung
        if self._manual_override_until:
            if now < self._manual_override_until:
                logger.debug(f"🎄 Manual override active until {self._manual_override_until.strftime('%H:%M')}")
                return  # Nichts tun während Override aktiv ist
            else:
                # Override abgelaufen
                logger.info("🎄 Manual override expired, resuming automatic schedule")
                self._manual_override_until = None
        
        # Prüfe Datumsgrenzen
        if not self._is_within_date_range(now):
            if self.lights_on:
                self._turn_all_lights_off("Outside date range")
            return
        
        # Prüfe Anwesenheit (falls aktiviert)
        if self.config['presence_only'] and not self._is_someone_home():
            if self.lights_on:
                self._turn_all_lights_off("No one home")
            return
        
        devices = self.config.get('devices', [])
        device_schedules = self.config.get('device_schedules', {})
        current_time = now.time()
        
        any_on = False
        turned_on_count = 0
        turned_off_count = 0
        turned_on_names = []
        turned_off_names = []
        
        for device_id in devices:
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
            
            # Log die Entscheidung
            device_label = self.config.get('device_labels', {}).get(device_id, device_id[:8])
            logger.debug(f"🎄 {device_label}: on={on_time}, off={off_time}, now={current_time}, should_be_on={should_be_on}")
            
            # Track state changes for notifications
            was_on = self._device_states.get(device_id)
            
            if should_be_on:
                any_on = True
                # Schalte dieses Gerät ein (falls nicht schon an)
                self._turn_device_on(device_id)
                if was_on != True:
                    turned_on_count += 1
                    turned_on_names.append(device_label)
            else:
                # Schalte dieses Gerät aus (falls nicht schon aus)
                self._turn_device_off(device_id)
                if was_on != False:
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
        """Berechnet Einschaltzeit für ein Gerät (mit Sonnenuntergang-Option)"""
        # Individuelle Zeit hat Vorrang
        if schedule.get('on_time'):
            try:
                return datetime.strptime(schedule['on_time'], '%H:%M').time()
            except ValueError:
                pass
        
        # Fallback: globale Einstellung
        if self.config['use_sunset'] and ASTRAL_AVAILABLE:
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
            return datetime.strptime(self.config['on_time'], '%H:%M').time()
        except ValueError:
            return datetime.strptime('16:00', '%H:%M').time()
    
    def _get_device_off_time(self, now: datetime, schedule: dict):
        """Berechnet Ausschaltzeit für ein Gerät (mit Wochenend-Verlängerung)"""
        # Individuelle Zeit hat Vorrang
        if schedule.get('off_time'):
            try:
                return datetime.strptime(schedule['off_time'], '%H:%M').time()
            except ValueError:
                pass
        
        # Fallback: globale Einstellung
        base_time = self.config['off_time']
        
        # Wochenend-Verlängerung
        if self.config['weekend_extended'] and now.weekday() >= 4:  # Fr, Sa, So
            base_time = '00:00'  # Bis Mitternacht
        
        try:
            return datetime.strptime(base_time, '%H:%M').time()
        except ValueError:
            return datetime.strptime('23:00', '%H:%M').time()
    
    def _turn_device_on(self, device_id: str):
        """Schaltet ein einzelnes Gerät ein (nur wenn nicht schon an)"""
        # Prüfe ob schon an
        if self._device_states.get(device_id) == True:
            return  # Schon an, nichts tun
        
        try:
            if self.platform:
                self.platform.turn_on(device_id)
                self._device_states[device_id] = True
                device_label = self.config.get('device_labels', {}).get(device_id, device_id[:8])
                logger.info(f"🎄 Christmas ON: {device_label}")
        except Exception as e:
            logger.error(f"Error turning on christmas device {device_id}: {e}")
    
    def _turn_device_off(self, device_id: str):
        """Schaltet ein einzelnes Gerät aus (nur wenn nicht schon aus)"""
        # Prüfe ob schon aus
        if self._device_states.get(device_id) == False:
            return  # Schon aus, nichts tun
        
        try:
            if self.platform:
                self.platform.turn_off(device_id)
                self._device_states[device_id] = False
                device_label = self.config.get('device_labels', {}).get(device_id, device_id[:8])
                logger.info(f"🎄 Christmas OFF: {device_label}")
        except Exception as e:
            logger.error(f"Error turning off christmas device {device_id}: {e}")
    
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
        self._last_action_time = datetime.now()
        logger.info(f"🎄 Christmas lights OFF ({affected} devices) - {reason}")
    
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
        """Prüft ob jemand zuhause ist"""
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
            now = datetime.now()
            off_time = self._get_device_off_time(now, {})
            # Override bis zur Ausschaltzeit + 1 Minute (damit der nächste Zyklus normal startet)
            override_until = datetime.combine(now.date(), off_time) + timedelta(minutes=1)
            # Falls Ausschaltzeit schon vorbei ist, Override bis morgen früh
            if override_until <= now:
                override_until = datetime.combine(now.date() + timedelta(days=1), datetime.strptime('06:00', '%H:%M').time())
            self._manual_override_until = override_until
            logger.info(f"🎄 Manual override set until {override_until.strftime('%H:%M')}")
            
            # Push-Benachrichtigung für manuelles Ausschalten
            self._send_notification(
                "🌙 Weihnachtsbeleuchtung manuell AUS",
                f"{affected} Gerät(e) ausgeschaltet. Automatik pausiert bis {override_until.strftime('%H:%M')} Uhr."
            )
        else:
            # Bei manuellem AN: Override aufheben
            self._manual_override_until = None
            
            # Push-Benachrichtigung für manuelles Einschalten
            self._send_notification(
                "🎄 Weihnachtsbeleuchtung manuell AN",
                f"{affected} Gerät(e) eingeschaltet."
            )
        
        logger.info(f"🎄 Christmas lights TEST: {'ON' if turn_on else 'OFF'} ({affected} devices)")
        return affected
    
    def get_status(self) -> Dict:
        """Gibt aktuellen Status zurück"""
        now = datetime.now()
        
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
        
        return {
            'enabled': self.config['enabled'],
            'lights_on': self.lights_on,
            'next_action': next_action,
            'active_devices': len(self.config.get('devices', [])),
            'last_action': self._last_action_time.isoformat() if self._last_action_time else None,
            'within_date_range': self._is_within_date_range(now),
            'device_schedules': self.config.get('device_schedules', {})
        }
