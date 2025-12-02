"""
Forgotten Light Detector - Erkennt vergessene Lampen

Analysiert:
- Lampen die lange an sind ohne Bewegung
- Ungewöhnliche Muster (Lampe an, aber niemand zu Hause)
- Schlafenszeit-Lampen die noch an sind
- Tageslicht + Lampe an

Im Test-Modus: Protokolliert nur, schaltet nicht aus

Respektiert device_types aus /rooms Konfiguration:
- Geräte mit device_type="device" werden ignoriert
- Nur Geräte mit device_type="light" oder ohne Eintrag werden geprüft
"""

import json
import time
from datetime import datetime, timedelta
from pathlib import Path
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
    
    Mit aktiviertem ML-Modell:
    - Lernt aus historischen Mustern
    - Erkennt raum-spezifische Muster
    - Verbessert sich mit mehr Daten
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
        self.use_ml = settings.get('use_ml', True)  # ML-Modell nutzen wenn verfügbar
        
        # Device Types aus rooms.json
        self.device_types: Dict[str, str] = {}
        self._load_device_types()
        
        # Tracking
        self.light_on_times: Dict[str, datetime] = {}  # device_id -> wann eingeschaltet
        self.last_motion_times: Dict[str, datetime] = {}  # room -> letzte Bewegung
        self.predictions: List[Dict] = []  # Aktuelle Vorhersagen
        
        # Statistiken (vor ML-Modell initialisieren!)
        self.stats = {
            'total_predictions': 0,
            'predictions_today': 0,
            'last_check': None,
            'ml_enabled': False
        }
        
        # Datenbank-Tabelle sicherstellen
        self._ensure_table()
        
        # Platform für Geräte-Abfrage
        self.platform = None
        self._init_platform()
        
        # ML-Modell
        self.ml_model = None
        self._init_ml_model()
    
    def _load_device_types(self):
        """Lädt device_types aus rooms.json"""
        try:
            rooms_file = Path('data/rooms.json')
            if rooms_file.exists():
                with open(rooms_file, 'r') as f:
                    data = json.load(f)
                    self.device_types = data.get('device_types', {})
        except Exception as e:
            logger.warning(f"Could not load device_types from rooms.json: {e}")
            self.device_types = {}
    
    def _ensure_table(self):
        """Stellt sicher, dass die Datenbank-Tabelle existiert"""
        try:
            conn = self.db._get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS forgotten_light_predictions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    device_id TEXT NOT NULL,
                    device_name TEXT,
                    room_name TEXT,
                    on_duration_minutes REAL,
                    confidence REAL,
                    reasons TEXT,
                    ml_prediction REAL,
                    action_taken TEXT DEFAULT 'logged'
                )
            """)
            conn.commit()
            logger.debug("Ensured forgotten_light_predictions table exists")
        except Exception as e:
            logger.error(f"Error creating forgotten_light_predictions table: {e}")
        
    def _init_ml_model(self):
        """Initialisiert das ML-Modell wenn verfügbar"""
        if not self.use_ml:
            return
            
        try:
            from src.models.forgotten_light_model import ForgottenLightModel
            self.ml_model = ForgottenLightModel()
            
            # Versuche gespeichertes Modell zu laden
            if self.ml_model.load():
                logger.info("ML model loaded for forgotten light detection")
                self.stats['ml_enabled'] = True
            else:
                logger.info("No trained ML model found, using rule-based detection")
                self.stats['ml_enabled'] = False
        except Exception as e:
            logger.warning(f"Could not initialize ML model: {e}")
            self.ml_model = None
        
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
                # Device types neu laden (falls geändert in /rooms)
                self._load_device_types()
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
            
            # Hole Zone-Mapping für Raumname-Auflösung
            zone_mapping = self._get_zone_mapping()
            
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
                
                # Handle zone - löse UUID zu Raumname auf
                zone = device.get('zone')
                if isinstance(zone, dict):
                    room_name = zone.get('name', 'Unknown')
                elif isinstance(zone, str):
                    # Zone ist UUID - versuche aufzulösen
                    room_name = zone_mapping.get(zone, zone)
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
                    
                    # Minuten seit letzter Bewegung im Raum
                    last_motion = self.last_motion_times.get(room_name)
                    minutes_since_motion = 0
                    if last_motion:
                        minutes_since_motion = (now - last_motion).total_seconds() / 60
                    
                    # ML-Vorhersage oder Regelbasiert
                    is_forgotten, confidence, reasons = self._predict_forgotten(
                        device_id=device_id,
                        device_name=device_name,
                        room_name=room_name,
                        on_minutes=on_minutes,
                        minutes_since_motion=minutes_since_motion,
                        presence_home=presence_home,
                        outdoor_light=outdoor_light,
                        now=now
                    )
                    
                    if is_forgotten and confidence >= 0.5:
                        self._record_forgotten_prediction(
                            device_id=device_id,
                            device_name=device_name,
                            room_name=room_name,
                            on_minutes=on_minutes,
                            reasons=reasons,
                            confidence=confidence,
                            ml_prediction=self.ml_model is not None and self.ml_model.is_trained
                        )
                else:
                    # Lampe ist aus - entferne aus Tracking
                    if device_id in self.light_on_times:
                        del self.light_on_times[device_id]
                        
        except Exception as e:
            logger.error(f"Error checking forgotten lights: {e}")
    
    def _predict_forgotten(self, device_id: str, device_name: str, room_name: str,
                           on_minutes: float, minutes_since_motion: float,
                           presence_home: bool, outdoor_light: float, 
                           now: datetime) -> Tuple[bool, float, List[str]]:
        """
        Vorhersage ob Lampe vergessen wurde.
        Nutzt ML-Modell wenn verfügbar, sonst Regeln.
        
        Returns:
            (is_forgotten, confidence, reasons)
        """
        # Mindest-Einschaltdauer
        if on_minutes < self.min_on_duration_minutes:
            return False, 0.0, []
        
        # ML-Vorhersage wenn Modell verfügbar
        if self.ml_model and self.ml_model.is_trained:
            conditions = {
                'hour_of_day': now.hour,
                'day_of_week': now.weekday(),
                'is_weekend': 1 if now.weekday() >= 5 else 0,
                'on_duration_minutes': on_minutes,
                'minutes_since_motion': minutes_since_motion,
                'presence_home': 1 if presence_home else 0,
                'outdoor_light': outdoor_light or 50,
                'room_name': room_name
            }
            
            is_forgotten, confidence = self.ml_model.predict(conditions)
            
            # Generiere Erklärungen für UI
            reasons = []
            if is_forgotten:
                reasons.append("🤖 ML-Vorhersage")
                if minutes_since_motion > 30:
                    reasons.append(f"Keine Bewegung seit {int(minutes_since_motion)} Min.")
                if not presence_home:
                    reasons.append("Niemand zu Hause")
                if on_minutes > 60:
                    reasons.append(f"Seit {int(on_minutes)} Min. an")
            
            return is_forgotten, confidence, reasons
        
        # Fallback: Regelbasiert
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
            confidence = self._calculate_confidence(reasons)
            return True, confidence, reasons
        
        return False, 0.0, []
    
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
        elif on_minutes > 30:
            # Keine Bewegungsdaten für diesen Raum, aber Lampe ist schon lange an
            reasons.append("Keine Bewegungsdaten verfügbar")
        
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
                                      reasons: List[str], confidence: float,
                                      ml_prediction: bool = False):
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
            'test_mode': self.test_mode,
            'ml_prediction': ml_prediction
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
            # Nutze value >= 1 da value als REAL gespeichert ist (1.0 statt 1)
            cursor.execute("""
                SELECT metadata, MAX(timestamp) as last_motion
                FROM sensor_data
                WHERE sensor_type = 'motion' AND value >= 1
                AND timestamp > datetime('now', '-2 hours')
                GROUP BY metadata
            """)
            
            # Zone UUID zu Raumname Mapping aufbauen
            zone_to_room = self._get_zone_mapping()
            
            for row in cursor.fetchall():
                try:
                    metadata = json.loads(row[0]) if row[0] else {}
                    zone_id = metadata.get('zone', '')
                    
                    # Zuerst versuchen Zone-UUID in Raumnamen zu übersetzen
                    if zone_id and zone_id in zone_to_room:
                        room = zone_to_room[zone_id]
                    else:
                        # Fallback auf Gerätename oder Zone-ID
                        room = metadata.get('name', zone_id or 'Unknown')
                    
                    if room:
                        self.last_motion_times[room] = datetime.fromisoformat(row[1])
                except Exception as e:
                    logger.debug(f"Error parsing motion metadata: {e}")
                    
        except Exception as e:
            logger.debug(f"Could not update motion data: {e}")
    
    def _get_zone_mapping(self) -> Dict[str, str]:
        """Holt Zone-UUID zu Raumname Mapping von der Platform"""
        zone_mapping = {}
        try:
            if self.platform:
                # Versuche Zonen von der Platform zu holen
                if hasattr(self.platform, 'get_zones'):
                    zones = self.platform.get_zones()
                    # Homey gibt Dict zurück: {zone_id: {id, name, ...}}
                    if isinstance(zones, dict):
                        for zone_id, zone_data in zones.items():
                            if isinstance(zone_data, dict):
                                zone_name = zone_data.get('name', '')
                                if zone_id and zone_name:
                                    zone_mapping[zone_id] = zone_name
                    elif isinstance(zones, list):
                        # Fallback für Listen-Format
                        for zone in zones:
                            zone_id = zone.get('id', '')
                            zone_name = zone.get('name', '')
                            if zone_id and zone_name:
                                zone_mapping[zone_id] = zone_name
        except Exception as e:
            logger.debug(f"Could not get zone mapping: {e}")
        return zone_mapping
    
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
        """
        Prüft ob Gerät eine Lampe ist.
        
        Respektiert device_types aus /rooms:
        - device_type="device" -> wird ignoriert (return False)
        - device_type="light" -> wird als Lampe behandelt
        - kein Eintrag -> wird nach Homey-Klasse geprüft
        """
        device_id = device.get('id', '')
        device_name = device.get('name', '')
        
        # 1. Prüfe ob in rooms.json als "device" markiert
        configured_type = self.device_types.get(device_id)
        if configured_type == 'device':
            # Explizit als "nicht Lampe" markiert
            return False
        
        if configured_type == 'light':
            # Explizit als Lampe markiert
            return True
        
        # 2. Fallback: Homey-Klasse prüfen
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
    
    def train_ml_model(self) -> Dict:
        """
        Trainiert das ML-Modell mit gesammelten Daten.
        Kann manuell oder automatisch aufgerufen werden.
        """
        try:
            from src.models.forgotten_light_model import ForgottenLightModel
            
            if self.ml_model is None:
                self.ml_model = ForgottenLightModel()
            
            # Trainiere mit Daten aus DB
            result = self.ml_model.train(db=self.db)
            
            if result.get('success'):
                # Speichere Modell
                self.ml_model.save()
                self.stats['ml_enabled'] = True
                logger.info(f"ML model trained successfully: {result}")
            else:
                logger.warning(f"ML model training failed: {result}")
            
            return result
            
        except Exception as e:
            logger.error(f"Error training ML model: {e}")
            return {'success': False, 'error': str(e)}
    
    def get_ml_status(self) -> Dict:
        """Gibt Status des ML-Modells zurück"""
        return {
            'enabled': self.ml_model is not None,
            'trained': self.ml_model.is_trained if self.ml_model else False,
            'model_version': self.ml_model.model_version if self.ml_model else None,
            'room_stats': len(self.ml_model.room_stats) if self.ml_model else 0
        }


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
