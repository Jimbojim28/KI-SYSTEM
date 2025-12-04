"""
Presence Tracker - Verfolgt Aufenthaltszeiten von Handys in Räumen
Speichert alle Positionsänderungen und erstellt Statistiken
"""

import json
import logging
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional
from collections import defaultdict

logger = logging.getLogger(__name__)

# Datei für Tracking-Daten
PRESENCE_HISTORY_FILE = Path(__file__).parent.parent.parent / 'data' / 'presence_history.json'
HA_ENTITIES_FILE = Path(__file__).parent.parent.parent / 'data' / 'ha_entities.json'


class PresenceTracker:
    """Tracker für Handy-Positionen und Aufenthaltsstatistiken"""
    
    def __init__(self, check_interval: int = 60):
        """
        Args:
            check_interval: Prüfintervall in Sekunden (Standard: 60s)
        """
        self.check_interval = check_interval
        self._running = False
        self._thread = None
        self._last_positions = {}  # {entity_id: {'room': str, 'since': datetime}}
        
        # Lade bisherige Historie
        self.history = self._load_history()
        
        logger.info(f"Presence Tracker initialized ({check_interval}s interval)")
    
    def _load_history(self) -> dict:
        """Lädt die Tracking-Historie"""
        if PRESENCE_HISTORY_FILE.exists():
            try:
                with open(PRESENCE_HISTORY_FILE, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Error loading presence history: {e}")
        
        return {
            "tracking_start": datetime.now().isoformat(),
            "devices": {},
            "daily_stats": {}
        }
    
    def _save_history(self):
        """Speichert die Tracking-Historie"""
        try:
            PRESENCE_HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(PRESENCE_HISTORY_FILE, 'w') as f:
                json.dump(self.history, f, indent=2, default=str)
        except Exception as e:
            logger.error(f"Error saving presence history: {e}")
    
    def _get_ha_collector(self):
        """Holt den Home Assistant Collector"""
        try:
            from src.data_collector.ha_collector import HomeAssistantCollector
            import yaml
            
            config_path = Path(__file__).parent.parent.parent / 'config' / 'config.yaml'
            with open(config_path, 'r') as f:
                config = yaml.safe_load(f)
            
            ha_config = config.get('homeassistant', {})
            if not ha_config.get('url') or not ha_config.get('token'):
                return None
            
            return HomeAssistantCollector(ha_config['url'], ha_config['token'])
        except Exception as e:
            logger.error(f"Error creating HA collector: {e}")
            return None
    
    def _get_device_trackers(self) -> List[dict]:
        """Holt alle device_tracker Entitäten aus ha_entities.json"""
        try:
            if HA_ENTITIES_FILE.exists():
                with open(HA_ENTITIES_FILE, 'r') as f:
                    data = json.load(f)
                return [e for e in data.get('entities', []) 
                       if e.get('type') in ['device_tracker', 'person']]
        except Exception as e:
            logger.error(f"Error loading HA entities: {e}")
        return []
    
    def _get_entity_state(self, collector, entity_id: str) -> Optional[str]:
        """Holt den aktuellen Status (Raum) einer Entität"""
        try:
            import requests
            
            url = f"{collector.url}/api/states/{entity_id}"
            headers = {
                "Authorization": f"Bearer {collector.token}",
                "Content-Type": "application/json"
            }
            
            response = requests.get(url, headers=headers, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                state = data.get("state", "unknown")
                # Ignoriere ungültige Zustände
                if state not in ['unknown', 'unavailable']:
                    return state
        except Exception as e:
            logger.debug(f"Error getting state for {entity_id}: {e}")
        
        return None
    
    def _record_position_change(self, entity_id: str, device_name: str, 
                                old_room: Optional[str], new_room: str, 
                                duration_minutes: float):
        """Zeichnet eine Positionsänderung auf"""
        today = datetime.now().strftime('%Y-%m-%d')
        now = datetime.now().isoformat()
        
        # Initialisiere Gerät in Historie wenn nötig
        if entity_id not in self.history['devices']:
            self.history['devices'][entity_id] = {
                'name': device_name,
                'first_seen': now,
                'position_changes': [],
                'room_times': {}  # {room: total_minutes}
            }
        
        device_data = self.history['devices'][entity_id]
        device_data['name'] = device_name  # Update Name falls geändert
        
        # Speichere Positionsänderung (letzte 1000 behalten)
        if old_room and duration_minutes > 0:
            device_data['position_changes'].append({
                'timestamp': now,
                'from_room': old_room,
                'to_room': new_room,
                'duration_minutes': round(duration_minutes, 1)
            })
            
            # Begrenze auf letzte 1000 Einträge
            if len(device_data['position_changes']) > 1000:
                device_data['position_changes'] = device_data['position_changes'][-1000:]
            
            # Aktualisiere Gesamtzeit pro Raum
            if old_room not in device_data['room_times']:
                device_data['room_times'][old_room] = 0
            device_data['room_times'][old_room] += duration_minutes
        
        # Tagesstatistik aktualisieren
        if today not in self.history['daily_stats']:
            self.history['daily_stats'][today] = {}
        
        if entity_id not in self.history['daily_stats'][today]:
            self.history['daily_stats'][today][entity_id] = {
                'name': device_name,
                'room_times': {}
            }
        
        daily_data = self.history['daily_stats'][today][entity_id]
        daily_data['name'] = device_name
        
        if old_room and duration_minutes > 0:
            if old_room not in daily_data['room_times']:
                daily_data['room_times'][old_room] = 0
            daily_data['room_times'][old_room] += duration_minutes
        
        # Alte Tagesstatistiken aufräumen (behalte 30 Tage)
        cutoff = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
        self.history['daily_stats'] = {
            k: v for k, v in self.history['daily_stats'].items() 
            if k >= cutoff
        }
        
        self._save_history()
    
    def _check_positions(self):
        """Prüft aktuelle Positionen aller Tracker"""
        trackers = self._get_device_trackers()
        if not trackers:
            return
        
        collector = self._get_ha_collector()
        if not collector:
            return
        
        now = datetime.now()
        
        for tracker in trackers:
            entity_id = tracker.get('entity_id')
            device_name = tracker.get('name', entity_id)
            
            current_room = self._get_entity_state(collector, entity_id)
            if not current_room:
                continue
            
            # Prüfe ob sich Position geändert hat
            last_pos = self._last_positions.get(entity_id)
            
            if last_pos:
                if last_pos['room'] != current_room:
                    # Position hat sich geändert
                    duration = (now - datetime.fromisoformat(last_pos['since'])).total_seconds() / 60
                    
                    logger.info(f"📍 {device_name}: {last_pos['room']} → {current_room} "
                              f"(war {duration:.1f} Min in {last_pos['room']})")
                    
                    self._record_position_change(
                        entity_id, device_name,
                        last_pos['room'], current_room,
                        duration
                    )
                    
                    # Aktualisiere letzte Position
                    self._last_positions[entity_id] = {
                        'room': current_room,
                        'since': now.isoformat()
                    }
            else:
                # Erste Erfassung
                self._last_positions[entity_id] = {
                    'room': current_room,
                    'since': now.isoformat()
                }
                logger.info(f"📍 {device_name}: Ersterfassung in {current_room}")
    
    def _run_loop(self):
        """Hauptschleife des Trackers"""
        while self._running:
            try:
                self._check_positions()
            except Exception as e:
                logger.error(f"Error in presence tracker loop: {e}")
            
            time.sleep(self.check_interval)
    
    def start(self):
        """Startet den Tracker"""
        if self._running:
            return
        
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info("Presence Tracker started")
    
    def stop(self):
        """Stoppt den Tracker"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        
        # Speichere finale Zeiten
        now = datetime.now()
        for entity_id, last_pos in self._last_positions.items():
            if last_pos:
                duration = (now - datetime.fromisoformat(last_pos['since'])).total_seconds() / 60
                device_data = self.history['devices'].get(entity_id, {})
                self._record_position_change(
                    entity_id,
                    device_data.get('name', entity_id),
                    last_pos['room'],
                    'stopped',
                    duration
                )
        
        logger.info("Presence Tracker stopped")
    
    def get_daily_stats(self, date: str = None) -> dict:
        """
        Holt Tagesstatistik
        
        Args:
            date: Datum im Format YYYY-MM-DD (Standard: heute)
        
        Returns:
            {entity_id: {'name': str, 'room_times': {room: minutes}, 'top_room': str}}
        """
        if date is None:
            date = datetime.now().strftime('%Y-%m-%d')
        
        daily = self.history.get('daily_stats', {}).get(date, {})
        
        result = {}
        for entity_id, data in daily.items():
            room_times = data.get('room_times', {})
            top_room = max(room_times, key=room_times.get) if room_times else None
            
            result[entity_id] = {
                'name': data.get('name', entity_id),
                'room_times': room_times,
                'total_tracked_minutes': sum(room_times.values()),
                'top_room': top_room,
                'top_room_minutes': room_times.get(top_room, 0) if top_room else 0
            }
        
        return result
    
    def get_all_time_stats(self) -> dict:
        """
        Holt Gesamtstatistik über alle Zeiten
        
        Returns:
            {entity_id: {'name': str, 'room_times': {room: minutes}, 'top_rooms': [...]}}
        """
        result = {}
        
        for entity_id, data in self.history.get('devices', {}).items():
            room_times = data.get('room_times', {})
            
            # Sortiere Räume nach Zeit
            sorted_rooms = sorted(room_times.items(), key=lambda x: x[1], reverse=True)
            
            result[entity_id] = {
                'name': data.get('name', entity_id),
                'first_seen': data.get('first_seen'),
                'room_times': room_times,
                'total_tracked_minutes': sum(room_times.values()),
                'top_rooms': sorted_rooms[:5],  # Top 5 Räume
                'recent_changes': data.get('position_changes', [])[-10:]  # Letzte 10 Änderungen
            }
        
        return result
    
    def get_current_positions(self) -> dict:
        """Holt aktuelle Positionen aller Tracker"""
        trackers = self._get_device_trackers()
        collector = self._get_ha_collector()
        
        result = {}
        for tracker in trackers:
            entity_id = tracker.get('entity_id')
            device_name = tracker.get('name', entity_id)
            
            current_room = self._get_entity_state(collector, entity_id) if collector else None
            last_pos = self._last_positions.get(entity_id, {})
            
            # Berechne Zeit im aktuellen Raum
            time_in_room = None
            if last_pos.get('since'):
                since = datetime.fromisoformat(last_pos['since'])
                time_in_room = (datetime.now() - since).total_seconds() / 60
            
            result[entity_id] = {
                'name': device_name,
                'current_room': current_room or last_pos.get('room', 'unknown'),
                'since': last_pos.get('since'),
                'minutes_in_room': round(time_in_room, 1) if time_in_room else 0
            }
        
        return result


# Globale Tracker-Instanz
_presence_tracker: Optional[PresenceTracker] = None


def get_presence_tracker() -> PresenceTracker:
    """Holt oder erstellt die globale Tracker-Instanz"""
    global _presence_tracker
    if _presence_tracker is None:
        _presence_tracker = PresenceTracker(check_interval=60)
    return _presence_tracker


def start_presence_tracker():
    """Startet den globalen Presence Tracker"""
    tracker = get_presence_tracker()
    tracker.start()
    return tracker


def stop_presence_tracker():
    """Stoppt den globalen Presence Tracker"""
    global _presence_tracker
    if _presence_tracker:
        _presence_tracker.stop()
        _presence_tracker = None
