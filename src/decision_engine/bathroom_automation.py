"""
Intelligente Badezimmer-Automatisierung
Steuert Luftentfeuchter und Heizung basierend auf Sensoren
Mit selbstlernendem Optimierungs-System
"""

from typing import Dict, Optional, List
from datetime import datetime, timedelta
from loguru import logger
from src.utils.database import Database
from src.decision_engine.bathroom_analyzer import BathroomAnalyzer
from src.decision_engine.mold_prevention import MoldPreventionSystem
from src.decision_engine.ventilation_optimizer import VentilationOptimizer
from src.decision_engine.shower_predictor import ShowerPredictor


class BathroomAutomation:
    """
    Intelligente Steuerung für Badezimmer:
    - Erkennt Duschen automatisch
    - Steuert Luftentfeuchter
    - Regelt Heizung
    """

    def __init__(self, config: Dict, enable_learning: bool = True):
        """
        Args:
            config: {
                'humidity_sensor_id': str,
                'temperature_sensor_id': str,
                'dehumidifier_id': str,
                'heater_id': str,
                'door_sensor_id': str (optional),
                'motion_sensor_id': str (optional),
                'window_sensor_id': str (optional, empfohlen),
                'humidity_threshold_high': float (default: 70),
                'humidity_threshold_low': float (default: 60),
                'target_temperature': float (default: 22)
            }
            enable_learning: Aktiviert selbstlernendes System (default: True)
        """
        self.config = config
        self.last_motion_time = None
        self.shower_detected = False
        self.dehumidifier_running = False
        self.enable_learning = enable_learning

        # Schwellwerte (können durch Lernen überschrieben werden)
        self.humidity_high = config.get('humidity_threshold_high', 70.0)
        self.humidity_low = config.get('humidity_threshold_low', 60.0)
        self.target_temp = config.get('target_temperature', 22.0)

        # Heizungs-Boost Einstellungen
        # heating_boost_enabled steuert auch, ob die Heizung überhaupt geregelt wird
        self.heating_boost_enabled = config.get('heating_boost_enabled', False)
        self.heating_boost_delta = config.get('heating_boost_delta', 1.0)

        # Frostschutztemperatur bei offenem Fenster
        self.frost_protection_temp = config.get('frost_protection_temperature', 12.0)

        # Verzögerung bevor Luftentfeuchter ausschaltet
        self.dehumidifier_delay_minutes = config.get('dehumidifier_delay', 5)
        self.dehumidifier_off_hysteresis = config.get('dehumidifier_off_hysteresis', 2.0)
        
        # Maximale Laufzeit für Luftentfeuchter (Sicherheit gegen Endlos-Lauf)
        self.max_dehumidifier_runtime_minutes = config.get('max_dehumidifier_runtime', 120)  # Default: 2 Stunden
        # Harte Abschalt-Schwelle: Unter diesem Wert IMMER ausschalten (unabhängig von Schimmelrisiko)
        self.force_off_humidity = config.get('force_off_humidity', 50.0)  # Default: 50%

        # Event-Tracking
        self.current_event_id = None
        self.event_start_time = None
        self.dehumidifier_start_time = None
        self.humidity_below_threshold_since = None  # Zeitpunkt, wann Luftfeuchtigkeit unter Schwellwert gefallen ist
        self._state_synced = False  # Flag ob States schon synchronisiert wurden

        # Für verbesserte Duscherkennung
        self.humidity_history = []  # Letzte 10 Messungen für Steigungsanalyse
        self.last_humidity_check = None
        self.humidity_rising_fast = False  # Flag ob Luftfeuchtigkeit schnell steigt
        
        # Duschsensor-Historie (zusätzlicher Sensor direkt an der Dusche)
        self.shower_sensor_history = []
        self.last_shower_sensor_humidity = None  # Letzter bekannter Duschsensor-Wert
        self.shower_sensor_enabled = bool(config.get('shower_humidity_sensor'))  # Aktiviert wenn Sensor konfiguriert
        self.shower_sensor_rate_threshold = config.get('rate_threshold', 1.2)  # Standard: 1.2% pro Minute (niedriger für schnellere Reaktion)
        self.shower_sensor_min_humidity = config.get('shower_sensor_min_humidity', 45.0)  # Mindest-Luftfeuchtigkeit für Duscherkennung via Duschsensor
        self.shower_sensor_predictive = config.get('shower_sensor_predictive', True)  # Aktiviert prädiktive Einschaltung bei Duschsensor-Anstieg

        # Datenbank für Lernsystem
        self.db = Database() if enable_learning else None

        # Neue intelligente Module
        self.mold_prevention = MoldPreventionSystem(db=self.db) if self.db else None
        self.ventilation = VentilationOptimizer(db=self.db) if self.db else None
        self.shower_predictor = ShowerPredictor(db=self.db) if self.db else None

        # Lade gelernte Parameter
        if self.db and enable_learning:
            self._load_learned_parameters()

        # Log Initialisierung
        shower_sensor_info = ""
        if self.shower_sensor_enabled:
            shower_sensor_info = f", ShowerSensor(rate={self.shower_sensor_rate_threshold}%/min, min={self.shower_sensor_min_humidity}%, predictive={self.shower_sensor_predictive})"

        logger.info(f"Bathroom automation initialized: High={self.humidity_high}%, Low={self.humidity_low}%, ForceOff={self.force_off_humidity}%, MaxRuntime={self.max_dehumidifier_runtime_minutes}min, Target={self.target_temp}°C, Frost={self.frost_protection_temp}°C, HeatingControl={self.heating_boost_enabled}, Learning={enable_learning}, MoldPrevention={self.mold_prevention is not None}, VentilationOptimizer={self.ventilation is not None}, ShowerPredictor={self.shower_predictor is not None}{shower_sensor_info}")

    def process(self, platform, current_state: Dict) -> List[Dict]:
        """
        Hauptlogik - wird regelmäßig aufgerufen

        Returns:
            Liste von Aktionen die ausgeführt werden sollen
        """
        actions = []
        
        # Synchronisiere internen State mit tatsächlichem Geräte-Status (nur einmal beim ersten Aufruf)
        if not self._state_synced:
            self._sync_device_states(platform)
            self._state_synced = True

        # Nutze übergebene Messwerte falls vorhanden (vermeidet doppelte API-Calls)
        humidity = (current_state or {}).get('humidity')
        if humidity is None:
            humidity = self._get_humidity(platform)

        temperature = (current_state or {}).get('temperature')
        if temperature is None:
            temperature = self._get_temperature(platform)
        motion_detected = (current_state or {}).get('motion_detected')
        if motion_detected is None:
            motion_detected = self._check_motion(platform)

        door_closed = (current_state or {}).get('door_closed')
        if door_closed is None:
            door_closed = self._check_door(platform)

        window_open = (current_state or {}).get('window_open')
        if window_open is None:
            window_open = self._check_window(platform)

        if humidity is None:
            logger.warning("No humidity sensor data available")
            return actions

        # Sicherheitscheck: Bei offenem Fenster Energiesparmodus
        if window_open:
            logger.info("⚠️ Window is open - energy saving mode activated")

            # Schalte Luftentfeuchter aus wenn er läuft
            if self.dehumidifier_running:
                dehumidifier_id = self.config.get('dehumidifier_id')
                if dehumidifier_id:
                    logger.info("💨 Turning OFF dehumidifier (window open)")
                    self.dehumidifier_running = False
                    self._log_device_action('dehumidifier', dehumidifier_id, 'turn_off', 'Window open - energy saving', platform)
                    actions.append({
                        'device_id': dehumidifier_id,
                        'action': 'turn_off',
                        'reason': 'Window open - energy saving'
                    })

            # Setze Heizung auf Frostschutztemperatur (nur wenn Heizungssteuerung aktiv)
            heater_id = self.config.get('heater_id')
            if self.heating_boost_enabled and heater_id and temperature is not None:
                # Nur anpassen wenn Temperatur über Frostschutz + 0.5°C liegt
                if temperature > self.frost_protection_temp + 0.5:
                    logger.info(f"🌡️ Setting heating to frost protection ({self.frost_protection_temp}°C, window open)")
                    self._log_device_action('heater', heater_id, 'set_temperature', 'Window open - frost protection', platform)
                    actions.append({
                        'device_id': heater_id,
                        'action': 'set_temperature',
                        'temperature': self.frost_protection_temp,
                        'reason': 'Window open - frost protection'
                    })

            return actions

        # Update Motion-Tracking
        if motion_detected:
            self.last_motion_time = datetime.now()

        # === DUSCHEN ERKENNUNG ===
        shower_active = self._detect_shower(humidity, motion_detected, door_closed, platform)

        # NEUE PRÄDIKTIVE AKTIVIERUNG: Duschsensor-Frühwarnung
        # Auch wenn noch keine volle Duscherkennung, aber Duschsensor zeigt Anstieg
        shower_sensor_warning = False
        if self.shower_sensor_enabled and self.shower_sensor_predictive:
            shower_sensor_humidity = self._get_shower_sensor_humidity(platform)
            if (shower_sensor_humidity and
                len(self.shower_sensor_history) >= 2 and
                shower_sensor_humidity > 50.0):  # Mindestens 50% am Duschsensor
                # Prüfe ob es einen Trend nach oben gibt
                old_val = self.shower_sensor_history[-2]['value']
                if shower_sensor_humidity > old_val + 0.8:  # Mindestens +0.8% Anstieg
                    shower_sensor_warning = True
                    logger.debug(f"🔔 Shower sensor early warning: {shower_sensor_humidity}% (trend up from {old_val}%)")

            # ShowerPredictor: Tiefere Analyse des Duschsensor-Trends
            if self.shower_predictor and len(self.shower_sensor_history) >= 2:
                signal = self.shower_predictor.check_pre_shower_signal(
                    self.shower_sensor_history,
                    min_humidity=self.shower_sensor_min_humidity,
                    min_rate=self.shower_sensor_rate_threshold
                )
                if signal.get('shower_imminent') and not shower_sensor_warning:
                    shower_sensor_warning = True
                    logger.debug(f"🔔 ShowerPredictor Frühwarnung: {signal['reason']}")

        if shower_active and not self.shower_detected:
            logger.info("🚿 Shower detected! Starting dehumidifier...")
            self.shower_detected = True
            # Starte Event-Tracking
            self._start_event(platform)

        # Speichere Messung während des Events
        if self.current_event_id:
            self._record_measurement(platform)

        # === LUFTENTFEUCHTER STEUERUNG ===
        # Übergebe auch shower_sensor_warning für prädiktive Aktivierung
        dehumidifier_action = self._control_dehumidifier(
            humidity,
            shower_active or shower_sensor_warning,  # Auch bei Frühwarnung aktivieren!
            motion_detected,
            platform  # Für Logging
        )
        if dehumidifier_action:
            actions.append(dehumidifier_action)

        # === HEIZUNG STEUERUNG ===
        # Nur ausführen wenn Heizungssteuerung aktiviert ist
        if self.heating_boost_enabled:
            heating_action = self._control_heating(
                temperature,
                humidity,
                self.dehumidifier_running,
                platform  # Für Logging
            )
            if heating_action:
                actions.append(heating_action)

        # Reset shower detection wenn Luftfeuchtigkeit wieder normal
        if self.shower_detected and humidity < self.humidity_low:
            logger.info("Shower finished, humidity back to normal")
            self.shower_detected = False
            # Beende Event-Tracking
            self._end_event(platform)

        return actions

    def _sync_device_states(self, platform):
        """
        Synchronisiert internen State mit tatsächlichem Geräte-Status
        Wird beim ersten process() Aufruf ausgeführt
        """
        # Prüfe Luftentfeuchter-Status
        dehumidifier_id = self.config.get('dehumidifier_id')
        if dehumidifier_id:
            try:
                device_state = platform.get_state(dehumidifier_id)
                if device_state:
                    caps = device_state.get('attributes', {}).get('capabilities', {})
                    if 'onoff' in caps:
                        actual_running = caps['onoff'].get('value', False)
                        if actual_running != self.dehumidifier_running:
                            logger.info(f"Syncing dehumidifier state: internal={self.dehumidifier_running}, actual={actual_running}")
                            self.dehumidifier_running = actual_running
                            # Wenn Gerät läuft und Luftfeuchtigkeit niedrig ist, starte den Countdown
                            if actual_running:
                                humidity = self._get_humidity(platform)
                                if humidity and humidity < self.humidity_low:
                                    if self.humidity_below_threshold_since is None:
                                        self.humidity_below_threshold_since = datetime.now()
                                        logger.info(f"Dehumidifier already running with low humidity - starting countdown")
            except Exception as e:
                logger.debug(f"Could not sync dehumidifier state: {e}")

    def _get_humidity(self, platform) -> Optional[float]:
        """Liest Luftfeuchtigkeit-Sensor"""
        sensor_id = self.config.get('humidity_sensor_id')
        if not sensor_id:
            return None

        try:
            state = platform.get_state(sensor_id)
            if state:
                caps = state.get('attributes', {}).get('capabilities', {})
                if 'measure_humidity' in caps:
                    return caps['measure_humidity'].get('value')
        except Exception as e:
            logger.error(f"Error reading humidity sensor: {e}")

        return None

    def _get_temperature(self, platform) -> Optional[float]:
        """Liest Temperatur-Sensor"""
        sensor_id = self.config.get('temperature_sensor_id')
        if not sensor_id:
            return None

        try:
            state = platform.get_state(sensor_id)
            if state:
                caps = state.get('attributes', {}).get('capabilities', {})
                if 'measure_temperature' in caps:
                    return caps['measure_temperature'].get('value')
        except Exception as e:
            logger.error(f"Error reading temperature sensor: {e}")

        return None

    def _get_shower_sensor_humidity(self, platform) -> Optional[float]:
        """Liest Luftfeuchtigkeit vom Duschsensor (zusätzlicher Sensor an der Dusche)"""
        sensor_id = self.config.get('shower_humidity_sensor')
        if not sensor_id:
            return None

        try:
            # Versuche Home Assistant Sensor (mit sensor. prefix)
            if sensor_id.startswith('sensor.'):
                state = platform.get_state(sensor_id)
                if state:
                    # Für HA Sensoren ist der Wert direkt im state
                    value = state.get('state')
                    if value and value not in ['unknown', 'unavailable']:
                        return float(value)
            else:
                # Homey Sensor
                state = platform.get_state(sensor_id)
                if state:
                    caps = state.get('attributes', {}).get('capabilities', {})
                    if 'measure_humidity' in caps:
                        return caps['measure_humidity'].get('value')
        except Exception as e:
            logger.debug(f"Error reading shower humidity sensor: {e}")

        return None
    
    def _get_shower_sensor_temperature(self, platform) -> Optional[float]:
        """Liest Temperatur vom Duschsensor (zusätzlicher Sensor an der Dusche)"""
        sensor_id = self.config.get('shower_temperature_sensor')
        if not sensor_id:
            return None

        try:
            # Versuche Home Assistant Sensor
            if sensor_id.startswith('sensor.'):
                state = platform.get_state(sensor_id)
                if state:
                    value = state.get('state')
                    if value and value not in ['unknown', 'unavailable']:
                        return float(value)
            else:
                # Homey Sensor
                state = platform.get_state(sensor_id)
                if state:
                    caps = state.get('attributes', {}).get('capabilities', {})
                    if 'measure_temperature' in caps:
                        return caps['measure_temperature'].get('value')
        except Exception as e:
            logger.debug(f"Error reading shower temperature sensor: {e}")

        return None

    def configure_shower_sensors(self, humidity_sensor: str = None, temperature_sensor: str = None,
                                 enable_rate_detection: bool = True, rate_threshold: float = 1.2,
                                 min_humidity: float = 45.0, enable_predictive: bool = True):
        """
        Konfiguriere zusätzliche Duschsensoren für verbesserte Erkennung

        Args:
            humidity_sensor: Entity ID des Luftfeuchtigkeitssensors an der Dusche
            temperature_sensor: Entity ID des Temperatursensors an der Dusche
            enable_rate_detection: Aktiviert Steigungserkennung
            rate_threshold: Schwellwert für Anstieg in %/Minute (Standard: 1.2)
            min_humidity: Mindest-Luftfeuchtigkeit für Duscherkennung (Standard: 45%)
            enable_predictive: Aktiviert prädiktive Einschaltung (Standard: True)
        """
        if humidity_sensor:
            self.config['shower_humidity_sensor'] = humidity_sensor
            self.shower_sensor_enabled = True
            logger.info(f"Shower humidity sensor configured: {humidity_sensor}")

        if temperature_sensor:
            self.config['shower_temperature_sensor'] = temperature_sensor
            logger.info(f"Shower temperature sensor configured: {temperature_sensor}")

        self.shower_sensor_rate_threshold = rate_threshold
        self.shower_sensor_min_humidity = min_humidity
        self.shower_sensor_predictive = enable_predictive
        logger.info(f"Shower sensor detection: rate_threshold={rate_threshold}%/min, min_humidity={min_humidity}%, predictive={enable_predictive}")


    def _check_motion(self, platform) -> bool:
        """Prüft Bewegungs-Sensor"""
        sensor_id = self.config.get('motion_sensor_id')
        if not sensor_id:
            return False

        try:
            state = platform.get_state(sensor_id)
            if state:
                caps = state.get('attributes', {}).get('capabilities', {})
                # Unterstütze sowohl alarm_motion als auch alarm_presence
                if 'alarm_motion' in caps:
                    return caps['alarm_motion'].get('value', False)
                elif 'alarm_presence' in caps:
                    return caps['alarm_presence'].get('value', False)
        except Exception as e:
            logger.debug(f"Error reading motion sensor: {e}")

        return False

    def _check_door(self, platform) -> bool:
        """Prüft Tür-Sensor (geschlossen = True)"""
        sensor_id = self.config.get('door_sensor_id')
        if not sensor_id:
            return False  # Kein Sensor = ignorieren

        try:
            state = platform.get_state(sensor_id)
            if state:
                caps = state.get('attributes', {}).get('capabilities', {})
                # alarm_contact: true = offen, false = geschlossen (Standard)
                # Mit invert_door_sensor kann die Logik umgekehrt werden
                if 'alarm_contact' in caps:
                    sensor_value = caps['alarm_contact'].get('value', False)
                    invert = self.config.get('invert_door_sensor', False)

                    # sensor_value = true bedeutet normalerweise "offen"
                    # Wir wollen wissen ob GESCHLOSSEN (return True wenn zu)
                    if invert:
                        # Invertierte Logik: true = geschlossen, false = offen
                        is_closed = sensor_value
                    else:
                        # Standard-Logik: true = offen, false = geschlossen
                        is_closed = not sensor_value

                    return is_closed
        except Exception as e:
            logger.debug(f"Error reading door sensor: {e}")

        return False

    def _check_window(self, platform) -> bool:
        """Prüft Fenster-Sensor (offen = True)"""
        sensor_id = self.config.get('window_sensor_id')
        if not sensor_id:
            return False  # Kein Sensor = Fenster als geschlossen annehmen

        try:
            state = platform.get_state(sensor_id)
            if state:
                caps = state.get('attributes', {}).get('capabilities', {})
                # alarm_contact: true = offen, false = geschlossen (Standard)
                # Mit invert_window_sensor kann die Logik umgekehrt werden
                if 'alarm_contact' in caps:
                    sensor_value = caps['alarm_contact'].get('value', False)
                    invert = self.config.get('invert_window_sensor', False)

                    # Wir wollen wissen ob OFFEN (return True wenn offen)
                    if invert:
                        # Invertierte Logik: true = geschlossen, false = offen
                        is_open = not sensor_value
                    else:
                        # Standard-Logik: true = offen, false = geschlossen
                        is_open = sensor_value

                    return is_open
        except Exception as e:
            logger.debug(f"Error reading window sensor: {e}")

        return False  # Bei Fehler: Fenster als geschlossen annehmen

    def _detect_shower(self, humidity: float, motion: bool, door_closed: bool, platform=None) -> bool:
        """
        Verbesserte Duscherkennung mit mehreren Kriterien

        Kriterien:
        1. Luftfeuchtigkeit über Schwellwert (mit Toleranz)
        2. Schneller Anstieg der Luftfeuchtigkeit (>2% pro Minute)
        3. Zusätzlicher Duschsensor (wenn konfiguriert) mit höherer Sensitivität
        4. Bewegung erkannt (wenn Sensor vorhanden)
        5. Tür geschlossen (wenn Sensor vorhanden)

        Returns:
            True wenn Dusche erkannt, False sonst
        """
        if humidity is None:
            return False

        # Speichere Luftfeuchtigkeit in Historie
        now = datetime.now()
        self.humidity_history.append({
            'time': now,
            'value': humidity
        })

        # Halte nur letzte 10 Messungen (ca. 10 Minuten bei 60s Intervall)
        if len(self.humidity_history) > 10:
            self.humidity_history.pop(0)

        # === DUSCHSENSOR AUSLESEN (falls konfiguriert) ===
        shower_sensor_humidity = None
        shower_sensor_rising_fast = False
        
        if platform and self.shower_sensor_enabled:
            shower_sensor_humidity = self._get_shower_sensor_humidity(platform)
            
            if shower_sensor_humidity is not None:
                # Speichere in separater Historie
                self.shower_sensor_history.append({
                    'time': now,
                    'value': shower_sensor_humidity
                })
                
                # Halte nur letzte 10 Messungen
                if len(self.shower_sensor_history) > 10:
                    self.shower_sensor_history.pop(0)
                
                # Prüfe schnellen Anstieg beim Duschsensor (schon nach 2 Messungen!)
                if len(self.shower_sensor_history) >= 2:
                    # Vergleiche mit vorletzter Messung für schnellere Reaktion
                    old_measurement = self.shower_sensor_history[-2]
                    time_diff = (now - old_measurement['time']).seconds / 60

                    if time_diff >= 0.5:  # Schon nach 30 Sekunden prüfen
                        humidity_diff = shower_sensor_humidity - old_measurement['value']
                        rate_per_minute = humidity_diff / time_diff

                        # Duschsensor ist sensibler - nutze konfigurierten niedrigeren Schwellwert
                        if rate_per_minute > self.shower_sensor_rate_threshold:
                            shower_sensor_rising_fast = True
                            logger.info(f"🚿 Shower sensor: Fast rise detected! +{humidity_diff:.1f}% in {time_diff:.1f}min (rate: {rate_per_minute:.1f}%/min, threshold: {self.shower_sensor_rate_threshold}%/min)")

        # === KRITERIUM 1: Hohe Luftfeuchtigkeit ===
        # Reduziere Schwellwert um 5% für bessere Erkennung
        humidity_threshold = self.humidity_high - 5.0  # 70% -> 65%
        high_humidity = humidity > humidity_threshold

        # === KRITERIUM 2: Schneller Anstieg (Hauptsensor) ===
        humidity_rising_fast = False
        if len(self.humidity_history) >= 3:  # Mindestens 3 Messungen
            # Vergleiche aktuelle mit Messung vor 2-3 Minuten
            old_measurement = self.humidity_history[-3]
            time_diff = (now - old_measurement['time']).seconds / 60  # in Minuten
            
            if time_diff >= 1.0:  # Mindestens 1 Minute zwischen Messungen
                humidity_diff = humidity - old_measurement['value']
                rate_per_minute = humidity_diff / time_diff
                
                # Schneller Anstieg: >2% pro Minute
                if rate_per_minute > 2.0:
                    humidity_rising_fast = True
                    logger.debug(f"Fast humidity rise detected: +{humidity_diff:.1f}% in {time_diff:.1f}min (rate: {rate_per_minute:.1f}%/min)")

        self.humidity_rising_fast = humidity_rising_fast

        # === KRITERIUM 3: Bewegung ===
        motion_ok = True
        if self.config.get('motion_sensor_id'):
            if self.last_motion_time:
                time_since_motion = (datetime.now() - self.last_motion_time).seconds / 60
                # Keine Bewegung seit 30 Min -> Wahrscheinlich keine Dusche
                motion_ok = time_since_motion <= 30
            else:
                # Noch nie Bewegung erkannt
                motion_ok = False

        # === ENTSCHEIDUNGS-LOGIK (PRIORISIERT DUSCHSENSOR) ===

        # HÖCHSTE PRIORITÄT: Duschsensor zeigt schnellen Anstieg
        if shower_sensor_rising_fast:
            # Duschsensor ist sehr verlässlich - wenn dort schneller Anstieg erkannt wird, ist es sehr wahrscheinlich Duschen
            # VERBESSERT: Niedrigerer Schwellwert (konfigurierbar, Standard: 45%)
            if shower_sensor_humidity and shower_sensor_humidity > self.shower_sensor_min_humidity:
                self.last_shower_sensor_humidity = shower_sensor_humidity
                logger.info(f"🚿 Shower detected via shower sensor! (shower: {shower_sensor_humidity}%, main: {humidity}%, threshold: {self.shower_sensor_min_humidity}%)")
                return True
            # ALTERNATIV: Auch bei niedrigerer Luftfeuchtigkeit, wenn Hauptsensor bereits erhöht ist
            elif shower_sensor_humidity and humidity > 55:  # Hauptsensor zeigt auch Anstieg
                self.last_shower_sensor_humidity = shower_sensor_humidity
                logger.info(f"🚿 Shower detected via shower sensor (combined)! (shower: {shower_sensor_humidity}%, main: {humidity}%)")
                return True

        # Duschsensor-Wert for Logging merken (auch wenn kein schneller Anstieg)
        if shower_sensor_humidity is not None:
            self.last_shower_sensor_humidity = shower_sensor_humidity
        
        # Option A: Hohe Luftfeuchtigkeit UND (schneller Anstieg ODER Bewegung)
        if high_humidity and (humidity_rising_fast or motion):
            if motion_ok:
                logger.debug(f"Shower detected: humidity={humidity}%, rising_fast={humidity_rising_fast}, motion={motion}")
                return True

        # Option B: Sehr hohe Luftfeuchtigkeit (über Original-Schwellwert) alleine reicht
        if humidity > self.humidity_high:
            if motion_ok:
                logger.debug(f"Shower detected: very high humidity={humidity}%")
                return True

        # Option C: Starker Anstieg + Bewegung (auch bei mittlerer Luftfeuchtigkeit)
        if humidity_rising_fast and motion and humidity > 60:
            logger.debug(f"Shower detected: fast rise + motion, humidity={humidity}%")
            return True

        return False

    def _control_dehumidifier(self, humidity: float, shower_active: bool,
                             motion: bool, platform) -> Optional[Dict]:
        """
        Steuert Luftentfeuchter intelligent

        Returns:
            Action-Dict oder None
        """
        dehumidifier_id = self.config.get('dehumidifier_id')
        if not dehumidifier_id:
            return None

        # WICHTIG: Synchronisiere mit tatsächlichem Geräte-Status
        # Verhindert mehrfaches Ein/Ausschalten
        try:
            device_state = platform.get_state(dehumidifier_id)
            if device_state:
                caps = device_state.get('attributes', {}).get('capabilities', {})
                if 'onoff' in caps:
                    actual_running = caps['onoff'].get('value', False)
                    if actual_running != self.dehumidifier_running:
                        logger.debug(f"Dehumidifier state sync: internal={self.dehumidifier_running}, actual={actual_running}")
                        self.dehumidifier_running = actual_running
                        # Reset Countdown wenn Gerät extern ausgeschaltet wurde
                        if not actual_running:
                            self.humidity_below_threshold_since = None
                            self.dehumidifier_start_time = None
                        # Setze Start-Zeit wenn Gerät extern eingeschaltet wurde (für Runtime-Tracking)
                        elif actual_running and self.dehumidifier_start_time is None:
                            self.dehumidifier_start_time = datetime.now()
                            logger.info(f"Dehumidifier detected as running - starting runtime tracking")
        except Exception as e:
            logger.debug(f"Could not check dehumidifier state: {e}")

        # Prüfe Schimmelrisiko (falls aktiviert)
        mold_risk_detected = False
        mold_risk_level = None
        if self.mold_prevention:
            try:
                # Hole Temperatur für Taupunkt-Berechnung
                temperature = self._get_temperature(platform)
                if temperature is not None:
                    room_name = self.config.get('room_name', 'Bad')
                    analysis = self.mold_prevention.analyze_room_humidity(
                        room_name=room_name,
                        temperature=temperature,
                        humidity=humidity
                    )
                    
                    if analysis and 'condensation_risk' in analysis:
                        risk_data = analysis['condensation_risk']
                        mold_risk_level = risk_data.get('risk_level')
                        # Einschalten bei kritischem oder hohem Risiko
                        if mold_risk_level in ['KRITISCH', 'HOCH']:
                            mold_risk_detected = True
                            logger.warning(f"⚠️ Mold risk detected: {mold_risk_level} (humidity: {humidity}%, dewpoint: {analysis.get('dewpoint', 'N/A')}°C)")
            except Exception as e:
                logger.error(f"Error checking mold risk: {e}")

        # EINSCHALTEN wenn:
        # - Luftfeuchtigkeit zu hoch
        # - Oder Dusche aktiv erkannt
        # - Oder Schimmelrisiko erkannt
        should_turn_on = (humidity > self.humidity_high) or shower_active or mold_risk_detected

        if should_turn_on and not self.dehumidifier_running:
            # Bestimme Grund
            if mold_risk_detected:
                reason = f'Mold risk detected: {mold_risk_level} (humidity: {humidity}%)'
            elif shower_active:
                reason = f'Shower detected (humidity: {humidity}%)'
            else:
                reason = f'High humidity ({humidity}%)'
            
            logger.info(f"💨 Turning ON dehumidifier (humidity: {humidity}%)")
            self.dehumidifier_running = True
            self.dehumidifier_start_time = datetime.now()
            self.humidity_below_threshold_since = None  # Reset Ausschalt-Countdown

            # Protokolliere Aktion
            self._log_device_action('dehumidifier', dehumidifier_id, 'turn_on', reason, platform)

            return {
                'device_id': dehumidifier_id,
                'action': 'turn_on',
                'reason': reason
            }
        elif should_turn_on and self.dehumidifier_running:
            # Gerät läuft bereits - keine Aktion nötig, aber Countdown resetten
            self.humidity_below_threshold_since = None
            logger.debug(f"Dehumidifier already running (humidity: {humidity}%), no action needed")

        # === SICHERHEITS-CHECKS FÜR SOFORTIGES AUSSCHALTEN ===
        
        # 1. HARTE ABSCHALTSCHWELLE: Unter force_off_humidity IMMER sofort ausschalten
        if self.dehumidifier_running and humidity < self.force_off_humidity:
            reason = f'Force OFF: Humidity very low ({humidity}% < {self.force_off_humidity}%)'
            logger.info(f"⚡ FORCE OFF dehumidifier - humidity below force threshold: {humidity}% < {self.force_off_humidity}%")
            self.dehumidifier_running = False
            self.humidity_below_threshold_since = None
            self.dehumidifier_start_time = None
            self._log_device_action('dehumidifier', dehumidifier_id, 'turn_off', reason, platform)
            return {
                'device_id': dehumidifier_id,
                'action': 'turn_off',
                'reason': reason
            }
        
        # 2. MAXIMALE LAUFZEIT: Nach max_dehumidifier_runtime_minutes Minuten IMMER ausschalten
        if self.dehumidifier_running and self.dehumidifier_start_time:
            runtime_minutes = (datetime.now() - self.dehumidifier_start_time).total_seconds() / 60
            if runtime_minutes >= self.max_dehumidifier_runtime_minutes:
                reason = f'Max runtime exceeded ({runtime_minutes:.0f} min >= {self.max_dehumidifier_runtime_minutes} min, humidity: {humidity}%)'
                logger.warning(f"⏰ TIMEOUT: Dehumidifier running too long ({runtime_minutes:.0f} min) - forcing OFF")
                self.dehumidifier_running = False
                self.humidity_below_threshold_since = None
                self.dehumidifier_start_time = None
                self._log_device_action('dehumidifier', dehumidifier_id, 'turn_off', reason, platform)
                return {
                    'device_id': dehumidifier_id,
                    'action': 'turn_off',
                    'reason': reason
                }
            else:
                logger.debug(f"Dehumidifier runtime: {runtime_minutes:.1f} min (max: {self.max_dehumidifier_runtime_minutes} min)")

        # === NORMALE AUSSCHALTLOGIK ===
        # AUSSCHALTEN wenn:
        # - Luftfeuchtigkeit wieder niedrig
        # - UND kein Schimmelrisiko mehr (außer bei sehr niedriger Feuchtigkeit)
        # - UND Verzögerung abgelaufen
        
        # Prüfe erneut Schimmelrisiko für Ausschalt-Entscheidung
        # ABER: Bei sehr niedriger Feuchtigkeit (<humidity_low - 5%) ignoriere Schimmelrisiko
        mold_risk_still_present = False
        humidity_very_low = humidity < (self.humidity_low - 5)  # z.B. unter 49% wenn Low=54%
        
        if self.mold_prevention and self.dehumidifier_running and not humidity_very_low:
            try:
                temperature = self._get_temperature(platform)
                if temperature is not None:
                    room_name = self.config.get('room_name', 'Bad')
                    analysis = self.mold_prevention.analyze_room_humidity(
                        room_name=room_name,
                        temperature=temperature,
                        humidity=humidity
                    )
                    
                    if analysis and 'condensation_risk' in analysis:
                        risk_data = analysis['condensation_risk']
                        risk_level = risk_data.get('risk_level')
                        # Weiterlaufen bei kritischem oder hohem Risiko
                        if risk_level in ['KRITISCH', 'HOCH']:
                            mold_risk_still_present = True
                            logger.info(f"🛡️ Keeping dehumidifier running due to {risk_level} mold risk")
            except Exception as e:
                logger.error(f"Error checking mold risk for shutdown: {e}")
        
        should_turn_off = humidity < self.humidity_low and not mold_risk_still_present
        within_shutdown_window = (
            self.humidity_below_threshold_since is not None
            and humidity < (self.humidity_low + self.dehumidifier_off_hysteresis)
            and not mold_risk_still_present
        )
        
        logger.debug(f"Dehumidifier decision: humidity={humidity}%, threshold={self.humidity_low}%, "
                    f"running={self.dehumidifier_running}, should_off={should_turn_off}, "
                    f"mold_risk={mold_risk_still_present}, humidity_very_low={humidity_very_low}")

        if (should_turn_off or within_shutdown_window) and self.dehumidifier_running:
            # Merke dir, wann Luftfeuchtigkeit unter Schwellwert gefallen ist
            if self.humidity_below_threshold_since is None:
                if should_turn_off:
                    self.humidity_below_threshold_since = datetime.now()
                    logger.info(f"Humidity dropped below threshold ({humidity}%), starting {self.dehumidifier_delay_minutes} min shutdown countdown")
                else:
                    return None
            
            # Prüfe ob Verzögerung abgelaufen ist
            minutes_since_below = (datetime.now() - self.humidity_below_threshold_since).total_seconds() / 60
            if minutes_since_below < self.dehumidifier_delay_minutes:
                remaining = self.dehumidifier_delay_minutes - minutes_since_below
                logger.info(f"Delaying dehumidifier shutdown: {remaining:.1f} min remaining (humidity: {humidity}%)")
                return None

            reason = f'Humidity normalized ({humidity}%)'
            logger.info(f"💨 Turning OFF dehumidifier (humidity: {humidity}%)")
            self.dehumidifier_running = False
            self.humidity_below_threshold_since = None  # Reset
            self.dehumidifier_start_time = None  # Reset runtime tracking

            # Protokolliere Aktion
            self._log_device_action('dehumidifier', dehumidifier_id, 'turn_off', reason, platform)

            return {
                'device_id': dehumidifier_id,
                'action': 'turn_off',
                'reason': reason
            }
        elif humidity >= (self.humidity_low + self.dehumidifier_off_hysteresis):
            # Reset nur bei deutlichem Anstieg über den Schwellwert
            self.humidity_below_threshold_since = None

        return None

    def _control_heating(self, temperature: Optional[float], humidity: float,
                        dehumidifier_running: bool, platform) -> Optional[Dict]:
        """
        Steuert Heizung intelligent

        Während Entfeuchtung: Temperatur leicht erhöhen (beschleunigt Trocknung)
        Normal: Ziel-Temperatur halten
        """
        heater_id = self.config.get('heater_id')
        if not heater_id or temperature is None:
            return None

        # Ziel-Temperatur anpassen
        if dehumidifier_running and self.heating_boost_enabled:
            # Während Entfeuchtung: Boost aktivieren (konfigurierbar)
            target = self.target_temp + self.heating_boost_delta
        else:
            target = self.target_temp

        # Nur anpassen wenn Abweichung > 0.5°C
        if abs(temperature - target) > 0.5:
            reason = f'Target temperature adjustment (boost: {self.heating_boost_enabled and dehumidifier_running})'
            logger.info(f"🌡️ Adjusting heating to {target}°C (current: {temperature}°C, boost: {self.heating_boost_delta if dehumidifier_running and self.heating_boost_enabled else 0}°C)")

            # Protokolliere Aktion
            self._log_device_action('heater', heater_id, 'set_temperature', reason, platform)

            return {
                'device_id': heater_id,
                'action': 'set_temperature',
                'temperature': target,
                'reason': reason
            }

        return None

    def get_status(self, platform) -> Dict:
        """Gibt aktuellen Status zurück"""
        
        # Hole tatsächlichen Geräte-Status von der Plattform
        actual_dehumidifier_running = False
        dehumidifier_id = self.config.get('dehumidifier_id')
        if dehumidifier_id:
            try:
                device_state = platform.get_state(dehumidifier_id)
                if device_state:
                    caps = device_state.get('attributes', {}).get('capabilities', {})
                    if 'onoff' in caps:
                        actual_dehumidifier_running = caps['onoff'].get('value', False)
            except Exception as e:
                logger.debug(f"Could not get dehumidifier state: {e}")
        
        status = {
            'enabled': True,
            'shower_detected': self.shower_detected,
            'dehumidifier_running': actual_dehumidifier_running,  # Tatsächlicher Geräte-Status
            'current_humidity': self._get_humidity(platform),
            'current_temperature': self._get_temperature(platform),
            'thresholds': {
                'humidity_high': self.humidity_high,
                'humidity_low': self.humidity_low,
                'target_temperature': self.target_temp
            },
            'last_motion': self.last_motion_time.isoformat() if self.last_motion_time else None,
            'learning_enabled': self.enable_learning
        }
        
        # Berechne Zeit bis automatisches Ausschalten (nur wenn Timer bereits von Automation gesetzt wurde)
        if actual_dehumidifier_running and self.humidity_below_threshold_since:
            elapsed_seconds = (datetime.now() - self.humidity_below_threshold_since).seconds
            delay_seconds = self.dehumidifier_delay_minutes * 60
            remaining_seconds = delay_seconds - elapsed_seconds
            if remaining_seconds > 0:
                status['dehumidifier_shutdown_in_seconds'] = remaining_seconds

        # Füge Event-Info hinzu wenn aktiv
        if self.current_event_id and self.event_start_time:
            duration = (datetime.now() - self.event_start_time).seconds / 60
            status['current_event'] = {
                'id': self.current_event_id,
                'duration_minutes': duration
            }

        return status

    # === LERN-FUNKTIONEN ===

    def _load_learned_parameters(self):
        """Lädt gelernte Parameter aus der Datenbank"""
        if not self.db:
            return

        try:
            # Lade optimierte Schwellwerte
            learned_high = self.db.get_learned_parameter('humidity_threshold_high')
            learned_low = self.db.get_learned_parameter('humidity_threshold_low')
            learned_delay = self.db.get_learned_parameter('dehumidifier_delay')

            if learned_high:
                self.humidity_high = learned_high
                logger.info(f"Loaded learned humidity_high: {learned_high}%")

            if learned_low:
                # Sicherheitsgrenze: Gelernt darf nicht unter dem konfigurierten Wert liegen
                # (Nutzer hat bewusst einen Wert eingestellt – Lernen darf nur höher gehen)
                config_low = self.config.get('humidity_threshold_low', 60.0)
                floor = max(50.0, config_low)
                if learned_low < floor:
                    logger.info(f"Learned humidity_low={learned_low}% is below configured {floor}% – using configured value")
                    self.humidity_low = floor
                else:
                    self.humidity_low = learned_low
                logger.info(f"Loaded learned humidity_low: {self.humidity_low}%")

            if learned_delay:
                self.dehumidifier_delay_minutes = learned_delay
                logger.info(f"Loaded learned delay: {learned_delay} min")

        except Exception as e:
            logger.error(f"Error loading learned parameters: {e}")

    def _record_measurement(self, platform):
        """Speichert aktuelle Messung während eines Events"""
        if not self.db or not self.current_event_id:
            return

        try:
            humidity = self._get_humidity(platform)
            temperature = self._get_temperature(platform)
            motion = self._check_motion(platform)

            if humidity is not None and temperature is not None:
                self.db.add_bathroom_measurement(
                    event_id=self.current_event_id,
                    humidity=humidity,
                    temperature=temperature,
                    motion=motion,
                    dehumidifier_on=self.dehumidifier_running
                )
        except Exception as e:
            logger.error(f"Error recording measurement: {e}")

    def _log_device_action(self, device_type: str, device_id: str,
                          action: str, reason: str, platform):
        """Protokolliert eine Geräte-Aktion"""
        if not self.db:
            return

        try:
            humidity = self._get_humidity(platform) or 0
            temperature = self._get_temperature(platform) or 0

            self.db.add_bathroom_device_action(
                device_type=device_type,
                device_id=device_id,
                action=action,
                reason=reason,
                humidity=humidity,
                temperature=temperature,
                event_id=self.current_event_id
            )
        except Exception as e:
            logger.error(f"Error logging device action: {e}")

    def _start_event(self, platform):
        """Startet ein neues Badezimmer-Event"""
        if not self.db or self.current_event_id:
            return  # Event läuft bereits

        try:
            humidity = self._get_humidity(platform) or 0
            temperature = self._get_temperature(platform) or 0
            motion = self._check_motion(platform)
            door_closed = self._check_door(platform)

            # Prüfe ob Event via Duschsensor erkannt wurde
            detected_by_shower = (
                self.shower_sensor_enabled and
                self.last_shower_sensor_humidity is not None and
                self.last_shower_sensor_humidity > self.shower_sensor_min_humidity
            )

            self.current_event_id = self.db.start_bathroom_event(
                humidity=humidity,
                temperature=temperature,
                motion=motion,
                door_closed=door_closed,
                shower_start_humidity=self.last_shower_sensor_humidity,
                detected_by_shower_sensor=detected_by_shower
            )

            self.event_start_time = datetime.now()
            logger.info(f"Started bathroom event {self.current_event_id}")

        except Exception as e:
            logger.error(f"Error starting event: {e}")

    def _end_event(self, platform):
        """Beendet das aktuelle Badezimmer-Event"""
        if not self.db or not self.current_event_id:
            return

        try:
            humidity = self._get_humidity(platform) or 0

            # Berechne Luftentfeuchter-Laufzeit
            dehumidifier_runtime = None
            if self.dehumidifier_start_time:
                dehumidifier_runtime = (datetime.now() - self.dehumidifier_start_time).seconds / 60

            self.db.end_bathroom_event(
                event_id=self.current_event_id,
                humidity=humidity,
                dehumidifier_runtime=dehumidifier_runtime
            )

            logger.info(f"Ended bathroom event {self.current_event_id}")

            self.current_event_id = None
            self.event_start_time = None
            self.dehumidifier_start_time = None

        except Exception as e:
            logger.error(f"Error ending event: {e}")

    def optimize_parameters(self, days_back: int = 30, min_confidence: float = 0.7) -> Optional[Dict]:
        """
        Optimiert die Schwellwerte basierend auf historischen Daten

        Returns:
            Dict mit Optimierungs-Ergebnissen oder None
        """
        if not self.db or not self.enable_learning:
            logger.warning("Learning disabled, skipping optimization")
            return None

        try:
            analyzer = BathroomAnalyzer(self.db)

            # Hole optimale Schwellwerte
            suggestions = analyzer.suggest_optimal_thresholds(days_back=days_back)

            if not suggestions:
                logger.warning("Not enough data for optimization")
                return None

            if suggestions['confidence'] < min_confidence:
                logger.warning(f"Confidence too low ({suggestions['confidence']} < {min_confidence}), skipping optimization")
                return {
                    'success': False,
                    'reason': 'Confidence too low',
                    'suggestions': suggestions
                }

            # Speichere gelernte Parameter
            self.db.save_learned_parameter(
                parameter_name='humidity_threshold_high',
                value=suggestions['humidity_threshold_high'],
                confidence=suggestions['confidence'],
                samples_used=suggestions['based_on_events'],
                reason=suggestions['reason']
            )

            self.db.save_learned_parameter(
                parameter_name='humidity_threshold_low',
                value=suggestions['humidity_threshold_low'],
                confidence=suggestions['confidence'],
                samples_used=suggestions['based_on_events'],
                reason=suggestions['reason']
            )

            # Aktualisiere aktuelle Werte
            old_values = {
                'humidity_high': self.humidity_high,
                'humidity_low': self.humidity_low
            }

            self.humidity_high = suggestions['humidity_threshold_high']
            self.humidity_low = suggestions['humidity_threshold_low']

            logger.info(f"✨ Parameters optimized! High: {old_values['humidity_high']}% -> {self.humidity_high}%, Low: {old_values['humidity_low']}% -> {self.humidity_low}%")

            return {
                'success': True,
                'old_values': old_values,
                'new_values': {
                    'humidity_high': self.humidity_high,
                    'humidity_low': self.humidity_low
                },
                'confidence': suggestions['confidence'],
                'based_on_events': suggestions['based_on_events'],
                'statistics': suggestions['statistics']
            }

        except Exception as e:
            logger.error(f"Error during optimization: {e}")
            return None

    def get_analytics(self, days_back: int = 30) -> Dict:
        """
        Holt Analytics und Statistiken

        Returns:
            Dict mit Analytics-Daten
        """
        if not self.db:
            return {'available': False, 'reason': 'Database not available'}

        try:
            analyzer = BathroomAnalyzer(self.db)

            # Hole Muster-Analyse
            patterns = analyzer.analyze_patterns(days_back=days_back)

            # Hole Statistiken
            stats = self.db.get_bathroom_statistics(days_back=days_back)

            # Hole Vorhersage
            prediction = analyzer.predict_next_shower()

            return {
                'available': True,
                'patterns': patterns,
                'statistics': stats,
                'prediction': prediction,
                'learning_enabled': self.enable_learning
            }

        except Exception as e:
            logger.error(f"Error getting analytics: {e}")
            return {'available': False, 'reason': str(e)}
