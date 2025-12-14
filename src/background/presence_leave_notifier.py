"""
Presence Leave Notifier - Sendet Push-Benachrichtigung wenn alle das Haus verlassen

Nutzt die zentrale Presence-API und informiert über:
- Fenster-Status (offen/gekippt/zu)
- Lichter-Status (an/aus)
"""

import json
import logging
import threading
import time
import requests
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import yaml

logger = logging.getLogger(__name__)

# Singleton-Instanz
_notifier_instance = None


def get_presence_leave_notifier():
    """Gibt die Singleton-Instanz zurück"""
    global _notifier_instance
    return _notifier_instance


class PresenceLeaveNotifier:
    """Überwacht Anwesenheit und sendet Benachrichtigung beim Verlassen"""
    
    def __init__(self, check_interval: int = 30):
        """
        Args:
            check_interval: Prüfintervall in Sekunden (Standard: 30s)
        """
        global _notifier_instance
        _notifier_instance = self
        
        self.check_interval = check_interval
        self._running = False
        self._thread = None
        
        # Status-Tracking
        self._last_anyone_home = None  # Vorheriger Status
        self._last_notification_time = None  # Letzte Benachrichtigung
        self._notification_cooldown = 300  # 5 Minuten Cooldown
        
        # Konfiguration laden
        self.config = self._load_config()
        
        logger.info(f"PresenceLeaveNotifier initialized ({check_interval}s interval)")
    
    def _load_config(self) -> dict:
        """Lädt Konfiguration aus config.yaml"""
        try:
            config_path = Path('config/config.yaml')
            if config_path.exists():
                with open(config_path, 'r') as f:
                    full_config = yaml.safe_load(f) or {}
                    return full_config.get('presence_leave_notification', {
                        'enabled': True,
                        'notify_lights': True,
                        'notify_windows': True,
                        'cooldown_minutes': 5
                    })
        except Exception as e:
            logger.error(f"Error loading config: {e}")
        
        return {
            'enabled': True,
            'notify_lights': True,
            'notify_windows': True,
            'cooldown_minutes': 5
        }
    
    def _get_pushover_credentials(self) -> Tuple[str, str]:
        """Hole Pushover-Credentials aus Config"""
        try:
            config_path = Path('config/config.yaml')
            if config_path.exists():
                with open(config_path, 'r') as f:
                    full_config = yaml.safe_load(f) or {}
                    
                    # Erst Absence-Config prüfen
                    absence = full_config.get('absence', {})
                    api_key = absence.get('pushover_api_key', '')
                    user_key = absence.get('pushover_user_key', '')
                    
                    # Fallback auf Notifications-Config
                    if not api_key or not user_key:
                        notifications = full_config.get('notifications', {})
                        pushover = notifications.get('pushover', {})
                        if not api_key:
                            api_key = pushover.get('api_token', '')
                        if not user_key:
                            user_key = pushover.get('user_key', '')
                    
                    return api_key, user_key
        except Exception as e:
            logger.error(f"Error getting Pushover credentials: {e}")
        
        return '', ''
    
    def _get_presence_status(self) -> dict:
        """Holt den aktuellen Anwesenheitsstatus von der zentralen API"""
        try:
            response = requests.get('http://localhost:8080/api/presence', timeout=5)
            if response.status_code == 200:
                return response.json()
        except Exception as e:
            logger.debug(f"Error getting presence status: {e}")
        
        return {'success': False, 'anyone_home': True}  # Fallback: anwesend
    
    def _get_homey_config(self) -> Tuple[str, str]:
        """Hole Homey URL und Token"""
        try:
            config_path = Path('config/config.yaml')
            if config_path.exists():
                with open(config_path, 'r') as f:
                    full_config = yaml.safe_load(f) or {}
                    homey = full_config.get('homey', {})
                    return homey.get('url', ''), homey.get('token', '')
        except Exception as e:
            logger.error(f"Error getting Homey config: {e}")
        return '', ''
    
    def _get_all_lights(self) -> List[dict]:
        """Hole alle Lichter und deren Status"""
        lights = []
        
        try:
            from src.data_collector.homey_collector import HomeyCollector
            
            homey_url, homey_token = self._get_homey_config()
            
            # Lade device_types Konfiguration
            device_types = {}
            rooms_path = Path('data/rooms.json')
            if rooms_path.exists():
                with open(rooms_path, 'r') as f:
                    rooms_data = json.load(f)
                    device_types = rooms_data.get('device_types', {})
            
            if homey_url and homey_token:
                collector = HomeyCollector(homey_url, homey_token)
                devices = collector.get_all_devices()
                
                for device in devices:
                    device_id = device.get('id', '')
                    device_class = device.get('class', '').lower()
                    caps = device.get('capabilities', [])
                    
                    # Prüfe device_types Konfiguration
                    configured_type = device_types.get(device_id)
                    if configured_type == 'device':
                        continue  # Explizit ausgeschlossen
                    
                    # Ist es ein Licht?
                    is_light = (
                        configured_type == 'light' or
                        device_class == 'light' or 
                        ('onoff' in caps and 'dim' in caps)
                    )
                    
                    if is_light:
                        cap_values = device.get('capabilitiesObj', {})
                        is_on = cap_values.get('onoff', {}).get('value', False)
                        
                        if is_on:  # Nur eingeschaltete Lichter
                            zone = device.get('zone', {})
                            room_name = zone.get('name', '') if isinstance(zone, dict) else ''
                            
                            lights.append({
                                'id': device_id,
                                'name': device.get('name', 'Unbekannt'),
                                'room': room_name
                            })
                        
        except Exception as e:
            logger.error(f"Error getting lights: {e}")
        
        return lights
    
    def _get_all_windows(self) -> Tuple[List[dict], List[dict]]:
        """Hole alle Fenster - gibt (offene, gekippte) zurück"""
        open_windows = []
        tilted_windows = []
        
        try:
            from src.data_collector.homey_collector import HomeyCollector
            
            homey_url, homey_token = self._get_homey_config()
            
            if homey_url and homey_token:
                collector = HomeyCollector(homey_url, homey_token)
                devices = collector.get_all_devices()
                
                for device in devices:
                    caps = device.get('capabilities', [])
                    
                    if 'alarm_contact' in caps:
                        cap_values = device.get('capabilitiesObj', {})
                        contact_open = cap_values.get('alarm_contact', {}).get('value', False)
                        tilt_angle = cap_values.get('measure_tilt', {}).get('value')
                        
                        if contact_open:  # Nur offene/gekippte
                            zone = device.get('zone', {})
                            room_name = zone.get('name', '') if isinstance(zone, dict) else ''
                            
                            window_info = {
                                'name': device.get('name', 'Unbekannt'),
                                'room': room_name
                            }
                            
                            # Bestimme Status
                            if tilt_angle is not None and 5 <= tilt_angle <= 45:
                                tilted_windows.append(window_info)
                            else:
                                open_windows.append(window_info)
                        
        except Exception as e:
            logger.error(f"Error getting windows: {e}")
        
        return open_windows, tilted_windows
    
    def _build_notification(self, who_left: str = None) -> Tuple[str, str]:
        """Erstellt die Benachrichtigung"""
        now = datetime.now().strftime('%H:%M')
        
        lights_on = self._get_all_lights()
        open_windows, tilted_windows = self._get_all_windows()
        
        title = f"🚪 Niemand mehr zuhause ({now})"
        
        message_parts = []
        
        # Wer ist gegangen (wenn bekannt)
        if who_left:
            message_parts.append(f"<b>👋 {who_left} hat das Haus verlassen</b>")
        
        # Fenster-Status
        if self.config.get('notify_windows', True):
            if open_windows:
                windows_str = ', '.join([w['name'] for w in open_windows[:5]])
                if len(open_windows) > 5:
                    windows_str += f" (+{len(open_windows)-5})"
                message_parts.append(f"⚠️ <b>Fenster OFFEN ({len(open_windows)}):</b>\n{windows_str}")
            
            if tilted_windows:
                windows_str = ', '.join([w['name'] for w in tilted_windows[:5]])
                if len(tilted_windows) > 5:
                    windows_str += f" (+{len(tilted_windows)-5})"
                message_parts.append(f"🟡 <b>Fenster GEKIPPT ({len(tilted_windows)}):</b>\n{windows_str}")
            
            if not open_windows and not tilted_windows:
                message_parts.append("✅ <b>Alle Fenster geschlossen</b>")
        
        # Lichter-Status
        if self.config.get('notify_lights', True):
            if lights_on:
                lights_str = ', '.join([l['name'] for l in lights_on[:5]])
                if len(lights_on) > 5:
                    lights_str += f" (+{len(lights_on)-5})"
                message_parts.append(f"💡 <b>Lichter AN ({len(lights_on)}):</b>\n{lights_str}")
            else:
                message_parts.append("✅ <b>Alle Lichter aus</b>")
        
        # Status-Zusammenfassung
        all_ok = not lights_on and not open_windows
        if all_ok:
            message_parts.append("\n✨ <b>Alles in Ordnung!</b>")
        
        # ChatGPT Kommentar hinzufügen wenn aktiviert
        if self.config.get('use_chatgpt', True):
            chatgpt_comment = self._get_chatgpt_comment(lights_on, open_windows, tilted_windows, all_ok)
            if chatgpt_comment:
                message_parts.append(f"\n💬 <i>{chatgpt_comment}</i>")
        
        message = '\n\n'.join(message_parts)
        
        return title, message
    
    def _get_chatgpt_comment(self, lights_on: list, open_windows: list, tilted_windows: list, all_ok: bool) -> Optional[str]:
        """Generiert einen kurzen ChatGPT-Kommentar basierend auf dem Status"""
        try:
            # Hole OpenAI Config
            config_path = Path('config/config.yaml')
            if not config_path.exists():
                return None
            
            with open(config_path, 'r') as f:
                full_config = yaml.safe_load(f) or {}
            
            notifications = full_config.get('notifications', {})
            openai_config = notifications.get('openai', {})
            
            if not openai_config.get('enabled'):
                return None
            
            api_key = openai_config.get('api_key', '')
            if not api_key or api_key == '***':
                return None
            
            model = openai_config.get('model', 'gpt-4o-mini')
            style = notifications.get('chatgpt_style', 'freundlich')
            max_length = notifications.get('max_text_length', 100)
            custom_prompt = notifications.get('custom_prompt', '')
            
            # Baue Kontext
            context_parts = []
            if all_ok:
                context_parts.append("Alles ist in Ordnung - alle Fenster zu und Lichter aus.")
            else:
                if lights_on:
                    context_parts.append(f"{len(lights_on)} Licht(er) noch an: {', '.join([l['name'] for l in lights_on[:3]])}")
                if open_windows:
                    context_parts.append(f"{len(open_windows)} Fenster offen: {', '.join([w['name'] for w in open_windows[:3]])}")
                if tilted_windows:
                    context_parts.append(f"{len(tilted_windows)} Fenster gekippt: {', '.join([w['name'] for w in tilted_windows[:3]])}")
            
            context = ' '.join(context_parts)
            
            # Baue Prompt
            style_hints = {
                'freundlich': 'Sei freundlich und warm.',
                'kurz': 'Sei sehr kurz und direkt.',
                'technisch': 'Sei sachlich und präzise.',
                'witzig': 'Sei humorvoll und locker.'
            }
            
            prompt = f"""Du bist ein Smart Home Assistent. Der Benutzer hat gerade das Haus verlassen.
Status: {context}

Schreibe einen SEHR kurzen Kommentar (max {max_length} Zeichen). 
{style_hints.get(style, '')}
{custom_prompt}

Antworte NUR mit dem Kommentar, keine Anführungszeichen, kein "Hier ist..." etc."""

            # API Call
            response = requests.post(
                'https://api.openai.com/v1/chat/completions',
                headers={
                    'Authorization': f'Bearer {api_key}',
                    'Content-Type': 'application/json'
                },
                json={
                    'model': model,
                    'messages': [{'role': 'user', 'content': prompt}],
                    'max_tokens': 100,
                    'temperature': 0.7
                },
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                comment = data['choices'][0]['message']['content'].strip()
                # Kürze auf max_length
                if len(comment) > max_length:
                    comment = comment[:max_length-3] + '...'
                return comment
            else:
                logger.debug(f"ChatGPT API error: {response.text}")
                
        except Exception as e:
            logger.debug(f"Error getting ChatGPT comment: {e}")
        
        return None
    
    def _send_notification(self, title: str, message: str) -> bool:
        """Sendet Pushover-Benachrichtigung"""
        api_key, user_key = self._get_pushover_credentials()
        
        if not api_key or not user_key:
            logger.warning("Pushover credentials not configured for leave notification")
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
                    'priority': 0
                },
                timeout=30
            )
            
            if response.status_code == 200:
                logger.info(f"Leave notification sent successfully")
                return True
            else:
                logger.error(f"Pushover error: {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"Error sending notification: {e}")
            return False
    
    def _check_presence_change(self):
        """Prüft ob sich die Anwesenheit geändert hat"""
        presence = self._get_presence_status()
        
        if not presence.get('success'):
            return
        
        anyone_home = presence.get('anyone_home', True)
        users = presence.get('users', [])
        
        # Ersten Check initialisieren
        if self._last_anyone_home is None:
            self._last_anyone_home = anyone_home
            logger.info(f"PresenceLeaveNotifier: Initial status - anyone_home={anyone_home}")
            return
        
        # Prüfe ob sich der Status geändert hat: vorher jemand da -> jetzt niemand da
        if self._last_anyone_home and not anyone_home:
            logger.info("🚪 Presence change detected: Last person left!")
            
            # Cooldown prüfen
            if self._last_notification_time:
                elapsed = (datetime.now() - self._last_notification_time).total_seconds()
                cooldown = self.config.get('cooldown_minutes', 5) * 60
                if elapsed < cooldown:
                    logger.debug(f"Notification skipped - cooldown ({int(cooldown - elapsed)}s remaining)")
                    self._last_anyone_home = anyone_home
                    return
            
            # Wer war zuletzt da?
            # (Alle Users sind jetzt weg, also alle die "present: false" haben)
            who_left = None
            if users:
                # Der letzte der ging
                last_users = [u.get('name', 'Unbekannt') for u in users if not u.get('present')]
                if last_users:
                    who_left = last_users[0]  # Nehmen wir den ersten
            
            # Benachrichtigung erstellen und senden
            if self.config.get('enabled', True):
                title, message = self._build_notification(who_left)
                if self._send_notification(title, message):
                    self._last_notification_time = datetime.now()
        
        # Status aktualisieren
        self._last_anyone_home = anyone_home
    
    def _run_loop(self):
        """Haupt-Loop für die Überwachung"""
        logger.info("PresenceLeaveNotifier started")
        
        while self._running:
            try:
                self._check_presence_change()
            except Exception as e:
                logger.error(f"Error in presence leave check: {e}")
            
            time.sleep(self.check_interval)
        
        logger.info("PresenceLeaveNotifier stopped")
    
    def run(self):
        """Wird vom CollectorManager aufgerufen - startet die Überwachung einmalig"""
        if not self._running:
            self.start()
        # Halte den Thread am Leben, da der CollectorManager in einer Schleife läuft
        while self._running:
            time.sleep(60)
    
    def start(self):
        """Startet die Überwachung"""
        if self._running:
            return
        
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info("PresenceLeaveNotifier started")
    
    def stop(self):
        """Stoppt die Überwachung"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("PresenceLeaveNotifier stopped")
    
    def is_running(self) -> bool:
        """Prüft ob der Notifier läuft"""
        return self._running
    
    def get_status(self) -> dict:
        """Gibt aktuellen Status zurück"""
        return {
            'running': self._running,
            'enabled': self.config.get('enabled', True),
            'last_anyone_home': self._last_anyone_home,
            'last_notification': self._last_notification_time.isoformat() if self._last_notification_time else None,
            'check_interval': self.check_interval,
            'cooldown_minutes': self.config.get('cooldown_minutes', 5)
        }
    
    def test_notification(self) -> bool:
        """Sendet eine Test-Benachrichtigung"""
        title, message = self._build_notification("Test-User")
        return self._send_notification(title, message)
