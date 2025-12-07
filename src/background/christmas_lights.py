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
            'presence_only': False,
            'weekend_extended': False,
            'random_delay': True
        }
        
        # Location für Sonnenuntergang (Berlin als Default)
        self.location = LocationInfo("Berlin", "Germany", "Europe/Berlin", 52.52, 13.405)
        
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
        
        # Prüfe Datumsgrenzen
        if not self._is_within_date_range(now):
            if self.lights_on:
                self._turn_lights_off("Outside date range")
            return
        
        # Prüfe Anwesenheit (falls aktiviert)
        if self.config['presence_only'] and not self._is_someone_home():
            if self.lights_on:
                self._turn_lights_off("No one home")
            return
        
        # Berechne Einschaltzeit
        on_time = self._get_on_time(now)
        off_time = self._get_off_time(now)
        
        current_time = now.time()
        
        # Entscheide ob Lichter an sein sollen
        should_be_on = False
        
        if on_time <= off_time:
            # Normaler Fall: z.B. 16:00 - 23:00
            should_be_on = on_time <= current_time <= off_time
        else:
            # Über Mitternacht: z.B. 16:00 - 00:30
            should_be_on = current_time >= on_time or current_time <= off_time
        
        # Aktion ausführen
        if should_be_on and not self.lights_on:
            delay = self._get_random_delay() if self.config['random_delay'] else 0
            if delay > 0:
                logger.debug(f"Christmas lights: waiting {delay}s random delay")
                time.sleep(delay)
            self._turn_lights_on()
        elif not should_be_on and self.lights_on:
            delay = self._get_random_delay() if self.config['random_delay'] else 0
            if delay > 0:
                logger.debug(f"Christmas lights: waiting {delay}s random delay")
                time.sleep(delay)
            self._turn_lights_off("Scheduled off time")
    
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
    
    def _get_on_time(self, now: datetime):
        """Berechnet Einschaltzeit (mit Sonnenuntergang-Option)"""
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
    
    def _get_off_time(self, now: datetime):
        """Berechnet Ausschaltzeit (mit Wochenend-Verlängerung)"""
        base_time = self.config['off_time']
        
        # Wochenend-Verlängerung
        if self.config['weekend_extended'] and now.weekday() >= 4:  # Fr, Sa, So
            base_time = '00:00'  # Bis Mitternacht
        
        try:
            return datetime.strptime(base_time, '%H:%M').time()
        except ValueError:
            return datetime.strptime('23:00', '%H:%M').time()
    
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
    
    def _turn_lights_on(self):
        """Schaltet alle Weihnachtslichter ein"""
        devices = self.config.get('devices', [])
        if not devices:
            logger.debug("No christmas devices configured")
            return
        
        affected = 0
        for device_id in devices:
            try:
                if self.platform:
                    self.platform.turn_on(device_id)
                    affected += 1
            except Exception as e:
                logger.error(f"Error turning on christmas device {device_id}: {e}")
        
        self.lights_on = True
        self._last_action_time = datetime.now()
        logger.info(f"🎄 Christmas lights ON ({affected} devices)")
    
    def _turn_lights_off(self, reason: str = ""):
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
    
    def test_lights(self, turn_on: bool) -> int:
        """Testet die Lichter (manuelles Ein/Ausschalten)"""
        devices = self.config.get('devices', [])
        affected = 0
        
        for device_id in devices:
            try:
                if self.platform:
                    if turn_on:
                        self.platform.turn_on(device_id)
                    else:
                        self.platform.turn_off(device_id)
                    affected += 1
            except Exception as e:
                logger.error(f"Error testing christmas device {device_id}: {e}")
        
        self.lights_on = turn_on
        logger.info(f"🎄 Christmas lights TEST: {'ON' if turn_on else 'OFF'} ({affected} devices)")
        return affected
    
    def get_status(self) -> Dict:
        """Gibt aktuellen Status zurück"""
        now = datetime.now()
        
        # Berechne nächste Aktion
        next_action = "--"
        if self.config['enabled']:
            on_time = self._get_on_time(now)
            off_time = self._get_off_time(now)
            
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
            'within_date_range': self._is_within_date_range(now)
        }
