"""
Forgotten Light Detector - Erkennt vergessene Lampen

Analysiert:
- Lampen die lange an sind ohne Bewegung
- Ungewöhnliche Muster (Lampe an, aber niemand zu Hause)
- Schlafenszeit-Lampen die noch an sind
- Tageslicht + Lampe an

Im Test-Modus: Protokolliert nur, schaltet nicht aus
"""

import time
from datetime import datetime, timedelta
from threading import Thread
from typing import Dict, List, Optional, Tuple
from loguru import logger

from src.utils.database import Database
from src.data_collector.platform_factory import PlatformFactory


class ForgottenLightDetector:
    """
    Erkennt Lampen die wahrscheinlich vergessen wurden auszuschalten.
    
    Regeln für "vergessene" Lampen:
    1. Keine Bewegung im Raum seit X Minuten
    2. Alle Bewohner sind nicht zu Hause
    3. Es ist Schlafenszeit (z.B. nach 23:00)
    4. Tageslicht ist ausreichend (hoher Lux-Wert)
    5. Lampe ist länger als X Minuten an ohne Interaktion
    """
    
    def __init__(self, db: Database = None, config: dict = None, test_mode: bool = True):
        self.db = db or Database()
        self.config = config or {}
        self.test_mode = test_mode  # Wenn True: nur protokollieren, nicht ausschalten
        
        self.running = False
        self.thread = None
        
        # Konfigurierbare Schwellwerte
        settings = self.config.get('forgotten_light', {})
        self.no_motion_threshold_minutes = settings.get('no_motion_threshold', 30)  # Min. ohne Bewegung
        self.sleep_hour_start = settings.get('sleep_hour_start', 23)  # Schlafenszeit Start
        self.sleep_hour_end = settings.get('sleep_hour_end', 6)  # Schlafenszeit Ende
        self.daylight_lux_threshold = settings.get('daylight_lux_threshold', 200)  # Lux für "hell genug"
        self.min_on_duration_minutes = settings.get('min_on_duration', 15)  # Min. an bevor "vergessen"
        self.check_interval = settings.get('check_interval', 60)  # Prüf-Intervall in Sekunden
        
        # Tracking
        self.light_on_times: Dict[str, datetime] = {}  # device_id -> wann eingeschaltet
        self.last_motion_times: Dict[str, datetime] = {}  # room -> letzte Bewegung
        self.predictions: List[Dict] = []  # Aktuelle Vorhersagen
        
        # Platform für Geräte-Abfrage
        self.platform = None
        self._init_platform()
        
        # Statistiken
        self.stats = {
            'total_predictions': 0,
            'predictions_today': 0,
            'last_check': None
        }
        
    def _init_platform(self):
        """Initialisiert die Platform (Homey/HA)"""
        try:
            platform_type = self.config.get('platform', {}).get('type', '').lower()
            
            if platform_type == 'homey':
                from src.data_collector.homey_collector import HomeyCollector
                homey_config = self.config.get('homey', {})
                self.platform = HomeyCollector(
                    url=homey_config.get('url', ''),
                    token=homey_config.get('token', '')
                )
                logger.info("Homey platform initialized for ForgottenLightDetector")
            elif platform_type == 'homeassistant':
                from src.data_collector.ha_collector import HomeAssistantCollector
                ha_config = self.config.get('homeassistant', {})
                self.platform = HomeAssistantCollector(
                    url=ha_config.get('url', ''),
                    token=ha_config.get('token', '')
                )
                logger.info("Home Assistant platform initialized for ForgottenLightDetector")
        except Exception as e:
            logger.error(f"Could not initialize platform for ForgottenLightDetector: {e}")
    
    def start(self):
        """Startet den Detektor im Hintergrund"""
        if self.running:
            logger.warning("ForgottenLightDetector already running")
            return
            
        self.running = True
        self.thread = Thread(target=self._detection_loop, daemon=True)
        self.thread.start()
        mode_str = "TEST-MODUS (nur Protokollierung)" if self.test_mode else "AKTIV-MODUS (schaltet aus)"
        logger.info(f"ForgottenLightDetector started - {mode_str}")
        
    def stop(self):
        """Stoppt den Detektor"""
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
        logger.info("ForgottenLightDetector stopped")
    
    def _detection_loop(self):
        """Hauptloop für Erkennung"""
        while self.running:
            try:
                self._check_for_forgotten_lights()
                self.stats['last_check'] = datetime.now().isoformat()
            except Exception as e:
                logger.error(f"Error in forgotten light detection: {e}")
            
            time.sleep(self.check_interval)
    
    def _check_for_forgotten_lights(self):
        """Prüft alle Lampen auf 'vergessen' Status"""
        if not self.platform:
            logger.warning("No platform available for forgotten light detection")
            return
        
        now = datetime.now()
        
        try:
            # Hole alle Geräte
            devices = self.platform.get_all_devices()
            
            # Hole Bewegungsdaten aus DB
            self._update_motion_data()
            
            # Hole Anwesenheit
            presence_home = self._get_presence_status()
            
            # Hole Außenhelligkeit
            outdoor_light = self._get_outdoor_light()
            
            for device in devices:
                if not self._is_light_device(device):
                    continue
                
                device_id = device.get('id')
                device_name = device.get('name', 'Unknown')
                
                # Handle zone
                zone = device.get('zone')
                if isinstance(zone, dict):
                    room_name = zone.get('name', 'Unknown')
                elif isinstance(zone, str):
                    room_name = zone
                else:
                    room_name = 'Unknown'
                
                # Ist die Lampe an?
                state = device.get('capabilitiesObj', {}).get('onoff', {}).get('value')
                
                if state:
                    # Lampe ist an - tracke Zeit
                    if device_id not in self.light_on_times:
                        self.light_on_times[device_id] = now
                    
                    on_duration = now - self.light_on_times[device_id]
                    on_minutes = on_duration.total_seconds() / 60
                    
                    # Prüfe ob "vergessen"
                    reasons = self._check_forgotten_reasons(
                        device_id=device_id,
                        device_name=device_name,
                        room_name=room_name,
                        on_minutes=on_minutes,
                        presence_home=presence_home,
                        outdoor_light=outdoor_light,
                        now=now
                    )
                    
                    if reasons:
                        self._record_forgotten_prediction(
                            device_id=device_id,
                            device_name=device_name,
                            room_name=room_name,
                            on_minutes=on_minutes,
                            reasons=reasons,
                            confidence=self._calculate_confidence(reasons)
                        )
                else:
                    # Lampe ist aus - entferne aus Tracking
                    if device_id in self.light_on_times:
                        del self.light_on_times[device_id]
                        
        except Exception as e:
            logger.error(f"Error checking forgotten lights: {e}")
    
    def _check_forgotten_reasons(self, device_id: str, device_name: str, room_name: str,
                                  on_minutes: float, presence_home: bool, 
                                  outdoor_light: float, now: datetime) -> List[str]:
        """
        Prüft verschiedene Gründe warum eine Lampe "vergessen" sein könnte.
        Gibt Liste von Gründen zurück.
        """
        reasons = []
        
        # Mindest-Einschaltdauer
        if on_minutes < self.min_on_duration_minutes:
            return []  # Noch nicht lange genug an
        
        # 1. Keine Bewegung im Raum
        last_motion = self.last_motion_times.get(room_name)
        if last_motion:
            motion_ago = (now - last_motion).total_seconds() / 60
            if motion_ago > self.no_motion_threshold_minutes:
                reasons.append(f"Keine Bewegung seit {int(motion_ago)} Min.")
        
        # 2. Niemand zu Hause
        if not presence_home:
            reasons.append("Niemand zu Hause")
        
        # 3. Schlafenszeit
        hour = now.hour
        if self.sleep_hour_start <= hour or hour < self.sleep_hour_end:
            if room_name.lower() not in ['schlafzimmer', 'bedroom']:
                reasons.append(f"Schlafenszeit ({hour}:00)")
        
        # 4. Tageslicht ausreichend
        if outdoor_light and outdoor_light > self.daylight_lux_threshold:
            reasons.append(f"Ausreichend Tageslicht ({outdoor_light:.0f} Lux)")
        
        # 5. Sehr lange an
        if on_minutes > 120:  # Mehr als 2 Stunden
            reasons.append(f"Seit {int(on_minutes)} Min. an")
        
        return reasons
    
    def _calculate_confidence(self, reasons: List[str]) -> float:
        """Berechnet Konfidenz basierend auf Anzahl und Gewichtung der Gründe"""
        if not reasons:
            return 0.0
        
        # Gewichtungen
        weights = {
            'Niemand zu Hause': 0.4,
            'Schlafenszeit': 0.25,
            'Keine Bewegung': 0.2,
            'Tageslicht': 0.15,
            'Seit': 0.1
        }
        
        total_weight = 0.0
        for reason in reasons:
            for key, weight in weights.items():
                if key in reason:
                    total_weight += weight
                    break
            else:
                total_weight += 0.1  # Default
        
        return min(total_weight, 1.0)
    
    def _record_forgotten_prediction(self, device_id: str, device_name: str, 
                                      room_name: str, on_minutes: float,
                                      reasons: List[str], confidence: float):
        """Speichert Vorhersage in DB"""
        now = datetime.now()
        
        # Prüfe ob schon kürzlich für diese Lampe protokolliert
        recent = [p for p in self.predictions 
                  if p['device_id'] == device_id 
                  and (now - datetime.fromisoformat(p['timestamp'])).seconds < 300]
        
        if recent:
            return  # Schon kürzlich protokolliert
        
        prediction = {
            'timestamp': now.isoformat(),
            'device_id': device_id,
            'device_name': device_name,
            'room_name': room_name,
            'on_duration_minutes': round(on_minutes, 1),
            'reasons': reasons,
            'confidence': round(confidence, 2),
            'would_turn_off': True,
            'test_mode': self.test_mode
        }
        
        # In Memory speichern
        self.predictions.append(prediction)
        
        # Nur die letzten 100 behalten
        if len(self.predictions) > 100:
            self.predictions = self.predictions[-100:]
        
        # In DB speichern
        try:
            self._save_prediction_to_db(prediction)
            self.stats['total_predictions'] += 1
            self.stats['predictions_today'] += 1
            
            logger.info(f"Forgotten light detected: {device_name} in {room_name} "
                       f"(confidence: {confidence:.0%}, reasons: {', '.join(reasons)})")
            
            # Im aktiven Modus: Lampe ausschalten
            if not self.test_mode:
                self._turn_off_light(device_id, device_name)
                
        except Exception as e:
            logger.error(f"Error saving forgotten light prediction: {e}")
    
    def _save_prediction_to_db(self, prediction: Dict):
        """Speichert Vorhersage in Datenbank"""
        conn = self.db._get_connection()
        cursor = conn.cursor()
        
        # Tabelle erstellen falls nicht vorhanden
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS forgotten_light_predictions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME NOT NULL,
                device_id TEXT NOT NULL,
                device_name TEXT,
                room_name TEXT,
                on_duration_minutes REAL,
                reasons TEXT,
                confidence REAL,
                would_turn_off BOOLEAN,
                test_mode BOOLEAN,
                actually_turned_off BOOLEAN DEFAULT 0
            )
        """)
        
        cursor.execute("""
            INSERT INTO forgotten_light_predictions
            (timestamp, device_id, device_name, room_name, on_duration_minutes, 
             reasons, confidence, would_turn_off, test_mode)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            prediction['timestamp'],
            prediction['device_id'],
            prediction['device_name'],
            prediction['room_name'],
            prediction['on_duration_minutes'],
            ','.join(prediction['reasons']),
            prediction['confidence'],
            prediction['would_turn_off'],
            prediction['test_mode']
        ))
        
        conn.commit()
    
    def _turn_off_light(self, device_id: str, device_name: str):
        """Schaltet Lampe aus (nur im aktiven Modus)"""
        if self.test_mode:
            logger.info(f"TEST: Would turn off {device_name}")
            return
            
        try:
            if hasattr(self.platform, 'turn_off_device'):
                self.platform.turn_off_device(device_id)
                logger.info(f"Turned off forgotten light: {device_name}")
        except Exception as e:
            logger.error(f"Could not turn off {device_name}: {e}")
    
    def _update_motion_data(self):
        """Aktualisiert Bewegungsdaten aus DB"""
        try:
            conn = self.db._get_connection()
            cursor = conn.cursor()
            
            # Letzte Bewegung pro Raum (aus sensor_data)
            cursor.execute("""
                SELECT metadata, MAX(timestamp) as last_motion
                FROM sensor_data
                WHERE sensor_type = 'motion' AND value = 1
                AND timestamp > datetime('now', '-2 hours')
                GROUP BY metadata
            """)
            
            for row in cursor.fetchall():
                try:
                    import json
                    metadata = json.loads(row[0]) if row[0] else {}
                    room = metadata.get('zone') or metadata.get('name', 'Unknown')
                    if room:
                        self.last_motion_times[room] = datetime.fromisoformat(row[1])
                except:
                    pass
                    
        except Exception as e:
            logger.debug(f"Could not update motion data: {e}")
    
    def _get_presence_status(self) -> bool:
        """Prüft ob jemand zu Hause ist"""
        try:
            if hasattr(self.platform, 'get_presence_status'):
                presence = self.platform.get_presence_status()
                return presence.get('anyone_home', True)
        except:
            pass
        return True  # Default: jemand zu Hause
    
    def _get_outdoor_light(self) -> float:
        """Holt Außenhelligkeit"""
        try:
            conn = self.db._get_connection()
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT value FROM sensor_data
                WHERE sensor_type = 'illuminance'
                ORDER BY timestamp DESC
                LIMIT 1
            """)
            
            row = cursor.fetchone()
            if row:
                return float(row[0])
        except:
            pass
        
        # Fallback: Zeit-basierte Schätzung
        hour = datetime.now().hour
        if 8 <= hour <= 18:
            return 300  # Taghell
        elif 6 <= hour <= 20:
            return 100  # Dämmerung
        else:
            return 10  # Nacht
    
    def _is_light_device(self, device: Dict) -> bool:
        """Prüft ob Gerät eine Lampe ist"""
        device_class = device.get('class', '').lower()
        capabilities = device.get('capabilities', [])
        
        if 'light' in device_class:
            return True
        
        if 'onoff' in capabilities and ('dim' in capabilities or 'light_hue' in capabilities):
            return True
        
        return False
    
    def get_current_predictions(self) -> List[Dict]:
        """Gibt aktuelle Vorhersagen zurück"""
        return self.predictions.copy()
    
    def get_predictions_history(self, hours: int = 24) -> List[Dict]:
        """Holt Vorhersage-Historie aus DB"""
        try:
            conn = self.db._get_connection()
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT timestamp, device_id, device_name, room_name, 
                       on_duration_minutes, reasons, confidence, test_mode
                FROM forgotten_light_predictions
                WHERE timestamp > datetime('now', ?)
                ORDER BY timestamp DESC
            """, (f'-{hours} hours',))
            
            history = []
            for row in cursor.fetchall():
                history.append({
                    'timestamp': row[0],
                    'device_id': row[1],
                    'device_name': row[2],
                    'room_name': row[3],
                    'on_duration_minutes': row[4],
                    'reasons': row[5].split(',') if row[5] else [],
                    'confidence': row[6],
                    'test_mode': bool(row[7])
                })
            
            return history
            
        except Exception as e:
            logger.error(f"Error getting predictions history: {e}")
            return []
    
    def get_statistics(self) -> Dict:
        """Gibt Statistiken zurück"""
        try:
            conn = self.db._get_connection()
            cursor = conn.cursor()
            
            # Gesamt-Vorhersagen
            cursor.execute("SELECT COUNT(*) FROM forgotten_light_predictions")
            total = cursor.fetchone()[0]
            
            # Heute
            cursor.execute("""
                SELECT COUNT(*) FROM forgotten_light_predictions
                WHERE date(timestamp) = date('now')
            """)
            today = cursor.fetchone()[0]
            
            # Top vergessene Lampen
            cursor.execute("""
                SELECT device_name, room_name, COUNT(*) as count
                FROM forgotten_light_predictions
                GROUP BY device_id
                ORDER BY count DESC
                LIMIT 5
            """)
            top_forgotten = [
                {'device_name': row[0], 'room_name': row[1], 'count': row[2]}
                for row in cursor.fetchall()
            ]
            
            # Häufigste Uhrzeiten
            cursor.execute("""
                SELECT strftime('%H', timestamp) as hour, COUNT(*) as count
                FROM forgotten_light_predictions
                GROUP BY hour
                ORDER BY count DESC
                LIMIT 5
            """)
            top_hours = [
                {'hour': int(row[0]), 'count': row[1]}
                for row in cursor.fetchall()
            ]
            
            return {
                'total_predictions': total,
                'predictions_today': today,
                'top_forgotten_lights': top_forgotten,
                'top_hours': top_hours,
                'test_mode': self.test_mode,
                'last_check': self.stats.get('last_check')
            }
            
        except Exception as e:
            logger.error(f"Error getting statistics: {e}")
            return {
                'total_predictions': 0,
                'predictions_today': 0,
                'test_mode': self.test_mode,
                'error': str(e)
            }
    
    def get_chart_data(self, days: int = 7) -> Dict:
        """Gibt Daten für Chart-Darstellung zurück"""
        try:
            conn = self.db._get_connection()
            cursor = conn.cursor()
            
            # Pro Tag und Stunde
            cursor.execute("""
                SELECT 
                    date(timestamp) as day,
                    strftime('%H', timestamp) as hour,
                    device_name,
                    room_name,
                    COUNT(*) as count,
                    AVG(confidence) as avg_confidence,
                    AVG(on_duration_minutes) as avg_duration
                FROM forgotten_light_predictions
                WHERE timestamp > datetime('now', ?)
                GROUP BY day, hour, device_id
                ORDER BY day, hour
            """, (f'-{days} days',))
            
            data_points = []
            for row in cursor.fetchall():
                data_points.append({
                    'date': row[0],
                    'hour': int(row[1]),
                    'device_name': row[2],
                    'room_name': row[3],
                    'count': row[4],
                    'avg_confidence': round(row[5] or 0, 2),
                    'avg_duration': round(row[6] or 0, 1)
                })
            
            # Nach Räumen aggregiert
            cursor.execute("""
                SELECT room_name, COUNT(*) as count
                FROM forgotten_light_predictions
                WHERE timestamp > datetime('now', ?)
                GROUP BY room_name
                ORDER BY count DESC
            """, (f'-{days} days',))
            
            by_room = [
                {'room': row[0], 'count': row[1]}
                for row in cursor.fetchall()
            ]
            
            # Nach Stunden aggregiert (für Heatmap)
            cursor.execute("""
                SELECT 
                    strftime('%w', timestamp) as weekday,
                    strftime('%H', timestamp) as hour,
                    COUNT(*) as count
                FROM forgotten_light_predictions
                WHERE timestamp > datetime('now', ?)
                GROUP BY weekday, hour
            """, (f'-{days} days',))
            
            heatmap = []
            for row in cursor.fetchall():
                heatmap.append({
                    'weekday': int(row[0]),
                    'hour': int(row[1]),
                    'count': row[2]
                })
            
            return {
                'data_points': data_points,
                'by_room': by_room,
                'heatmap': heatmap
            }
            
        except Exception as e:
            logger.error(f"Error getting chart data: {e}")
            return {'data_points': [], 'by_room': [], 'heatmap': []}


# Globale Instanz
_detector_instance = None


def get_forgotten_light_detector(config: dict = None, test_mode: bool = True) -> ForgottenLightDetector:
    """Gibt globale Detektor-Instanz zurück"""
    global _detector_instance
    if _detector_instance is None:
        _detector_instance = ForgottenLightDetector(config=config, test_mode=test_mode)
    return _detector_instance


def start_forgotten_light_detector(config: dict = None, test_mode: bool = True) -> ForgottenLightDetector:
    """Startet den Detektor"""
    detector = get_forgotten_light_detector(config=config, test_mode=test_mode)
    detector.start()
    return detector
