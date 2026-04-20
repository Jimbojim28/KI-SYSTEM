"""
Background Collector: Garten-Sensoren (Hochbeet, Rasen, Mäher)
Sammelt konfigurierte HA-Sensordaten alle 5 Minuten und speichert sie lokal.
"""

import json
import os
import time
from datetime import datetime
from threading import Thread
from loguru import logger

from src.utils.database import Database

GARTEN_CONFIG_PATH = os.path.join('data', 'garten_config.json')
COLLECT_INTERVAL = 300  # 5 Minuten
RETENTION_DAYS = 90


class GartenDataCollector:
    """Sammelt Garten-Sensordaten aus Home Assistant und persistiert sie lokal."""

    def __init__(self, engine=None, interval_seconds: int = COLLECT_INTERVAL):
        self.engine = engine
        self.interval = interval_seconds
        self.db = Database()
        self.running = False
        self.thread = None

    def start(self):
        if self.running:
            return
        self.running = True
        self.thread = Thread(target=self._run, daemon=True, name="GartenCollector")
        self.thread.start()
        logger.info("GartenDataCollector gestartet")

    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join(timeout=10)
        logger.info("GartenDataCollector gestoppt")

    def _get_collector(self):
        if not self.engine:
            return None
        if hasattr(self.engine, 'platforms') and 'homeassistant' in self.engine.platforms:
            return self.engine.platforms['homeassistant']
        return getattr(self.engine, 'platform', None)

    def _load_entity_ids(self) -> list[str]:
        """Gibt alle konfigurierten Sensor-Entity-IDs zurück."""
        try:
            if not os.path.exists(GARTEN_CONFIG_PATH):
                return []
            with open(GARTEN_CONFIG_PATH, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
            ids = []
            # Bodenfeuchtesensoren
            for key, entity_id in (cfg.get('sensors') or {}).items():
                if entity_id:
                    ids.append(entity_id)
            # Mäher-Sensoren
            mower = cfg.get('mower') or {}
            prefix = mower.get('prefix', '').strip()
            if prefix:
                for suffix in [
                    '_battery_level',
                    '_cutting_height',
                    '_mowing_time_session',
                    '_mowing_area_session',
                    '_voice_volume',
                    '_custom_mowing_direction',
                ]:
                    ids.append(f'sensor.{prefix}{suffix}')
            return ids
        except Exception as e:
            logger.warning(f"GartenCollector: Konnte Config nicht laden: {e}")
            return []

    def collect_once(self) -> int:
        """Liest alle Sensoren einmal aus und speichert in DB. Gibt Anzahl gespeicherter Werte zurück."""
        collector = self._get_collector()
        if not collector:
            return 0

        entity_ids = self._load_entity_ids()
        if not entity_ids:
            return 0

        saved = 0
        conn = self.db._get_connection()
        ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        for entity_id in entity_ids:
            try:
                state = collector.get_state(entity_id)
                if not state:
                    continue
                val = float(state.get('state', ''))
                conn.execute(
                    "INSERT INTO garten_sensor_history (timestamp, entity_id, value) VALUES (?, ?, ?)",
                    (ts, entity_id, val)
                )
                saved += 1
            except (ValueError, TypeError):
                pass  # Sensor unavailable oder kein numerischer Wert
            except Exception as e:
                logger.warning(f"GartenCollector: Fehler bei {entity_id}: {e}")

        if saved > 0:
            conn.commit()
            # Alte Daten bereinigen
            try:
                from datetime import timedelta
                cutoff = (datetime.now() - timedelta(days=RETENTION_DAYS)).strftime('%Y-%m-%d %H:%M:%S')
                conn.execute("DELETE FROM garten_sensor_history WHERE timestamp < ?", (cutoff,))
                conn.commit()
            except Exception:
                pass

        return saved

    def _run(self):
        while self.running:
            try:
                n = self.collect_once()
                if n > 0:
                    logger.debug(f"GartenCollector: {n} Sensorwerte gespeichert")
            except Exception as e:
                logger.error(f"GartenCollector Fehler: {e}")
            time.sleep(self.interval)
