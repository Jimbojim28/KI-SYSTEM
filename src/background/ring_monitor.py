"""Background monitor for Ring Intercom — polls events, triggers auto-open, sends notifications."""
import sqlite3
import threading
import time
import json
from datetime import datetime, time as dt_time
from typing import Optional

from loguru import logger

from src.data_collector.ring_collector import RingCollector, RING_AVAILABLE
from src.utils.pushover import PushoverNotifier


class RingMonitor:
    """Background thread that monitors Ring Intercom events."""

    def __init__(self, ring_collector: RingCollector, db_path: str = "data/ki_system.db",
                 poll_interval: int = 15, auto_open_enabled: bool = False,
                 auto_open_delay: int = 5, auto_open_schedules: list = None,
                 daily_reload: bool = True):
        self.collector = ring_collector
        self.db_path = db_path
        self.poll_interval = poll_interval
        self.auto_open_enabled = auto_open_enabled
        self.auto_open_delay = auto_open_delay
        self.auto_open_schedules = auto_open_schedules or []
        self.daily_reload = daily_reload

        self.running = False
        self.thread = None
        self._last_reload_date = None

    def start(self):
        """Start the monitoring thread."""
        if not RING_AVAILABLE:
            logger.warning("Ring: Library not available, monitor not started")
            return
        if self.running:
            logger.warning("Ring: Monitor already running")
            return

        if not self.collector.connect():
            logger.error("Ring: Initial connection failed, will retry in background")

        self.running = True
        self.thread = threading.Thread(target=self._run_loop, daemon=True, name="RingMonitor")
        self.thread.start()
        logger.info(f"Ring: Monitor started (poll every {self.poll_interval}s)")

    def stop(self):
        """Stop the monitoring thread."""
        self.running = False
        if self.thread:
            self.thread.join(timeout=10)
        logger.info("Ring: Monitor stopped")

    def _run_loop(self):
        """Main monitoring loop."""
        while self.running:
            try:
                if self.daily_reload:
                    self._check_daily_reload()

                new_events = self.collector.check_for_new_events()
                for event in new_events:
                    self._handle_event(event)

            except Exception as e:
                logger.error(f"Ring: Monitor loop error: {e}")

            for _ in range(self.poll_interval):
                if not self.running:
                    break
                time.sleep(1)

    def _check_daily_reload(self):
        """Force reconnection once per day at the ~4:00 AM hour."""
        today = datetime.now().date()
        if self._last_reload_date != today and datetime.now().hour == 4:
            self._last_reload_date = today
            logger.info("Ring: Daily reload triggered")
            self.collector.refresh_connection()

    def _handle_event(self, event: dict):
        """Process a new Ring event: save to DB, notify, auto-open."""
        event_type = event.get("event_type", "ding")
        self._save_event(event)

        if event_type == "ding":
            self.collector.pushover.send_ring_event("ding")
            if self.auto_open_enabled and self._is_auto_open_time():
                threading.Timer(
                    self.auto_open_delay,
                    self._auto_open_door,
                    args=[event["event_id"]]
                ).start()

    def _auto_open_door(self, event_id: str):
        """Open the door and log it."""
        if self.collector.open_door():
            self.collector.pushover.send_ring_event("auto_open")
            self._update_event_auto_opened(event_id)
            logger.info(f"Ring: Auto-opened door for event {event_id}")

    def _is_auto_open_time(self) -> bool:
        """Check if current time falls within any auto-open schedule."""
        if not self.auto_open_schedules:
            return False
        now = datetime.now()
        current_day = now.weekday()
        current_time = now.time()
        for schedule in self.auto_open_schedules:
            days = schedule.get("days", list(range(7)))
            if current_day not in days:
                continue
            start = self._parse_time(schedule.get("start", "00:00"))
            end = self._parse_time(schedule.get("end", "23:59"))
            if start <= current_time <= end:
                return True
        return False

    @staticmethod
    def _parse_time(time_str: str) -> dt_time:
        """Parse 'HH:MM' string to datetime.time."""
        parts = time_str.split(":")
        return dt_time(int(parts[0]), int(parts[1]))

    def _save_event(self, event: dict):
        """Persist event to ring_events table."""
        try:
            conn = sqlite3.connect(self.db_path, timeout=10)
            conn.execute(
                """INSERT OR IGNORE INTO ring_events
                   (event_type, ring_event_id, timestamp, duration, answered, auto_opened, metadata)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    event.get("event_type", "ding"),
                    event.get("event_id"),
                    event.get("timestamp", datetime.now().isoformat()),
                    event.get("duration"),
                    event.get("answered", False),
                    False,
                    json.dumps(event),
                )
            )
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Ring: Failed to save event: {e}")

    def _update_event_auto_opened(self, event_id: str):
        """Mark an event as auto-opened."""
        try:
            conn = sqlite3.connect(self.db_path, timeout=10)
            conn.execute(
                "UPDATE ring_events SET auto_opened = ? WHERE ring_event_id = ?",
                (True, event_id),
            )
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Ring: Failed to update event: {e}")

    def get_status(self) -> dict:
        """Return current monitor status for the dashboard."""
        health = self.collector.get_health()
        health["poll_interval"] = self.poll_interval
        health["auto_open_enabled"] = self.auto_open_enabled
        health["auto_open_schedules"] = self.auto_open_schedules
        health["monitor_running"] = self.running
        return health

    def get_recent_events(self, limit: int = 20) -> list:
        """Fetch recent events from database."""
        try:
            conn = sqlite3.connect(self.db_path, timeout=10)
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM ring_events ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            )
            events = [dict(row) for row in cursor.fetchall()]
            conn.close()
            return events
        except Exception as e:
            logger.error(f"Ring: Failed to fetch events: {e}")
            return []

    def update_settings(self, auto_open_enabled: bool = None,
                        auto_open_delay: int = None,
                        auto_open_schedules: list = None):
        """Update monitor settings at runtime."""
        if auto_open_enabled is not None:
            self.auto_open_enabled = auto_open_enabled
        if auto_open_delay is not None:
            self.auto_open_delay = auto_open_delay
        if auto_open_schedules is not None:
            self.auto_open_schedules = auto_open_schedules
        logger.info(f"Ring: Settings updated — auto_open={self.auto_open_enabled}, delay={self.auto_open_delay}s")

    @classmethod
    def from_config(cls, config: dict, db_path: str = "data/ki_system.db") -> Optional["RingMonitor"]:
        """Create RingMonitor from config dict."""
        ring_cfg = config.get("ring", {})
        if not ring_cfg.get("enabled", False):
            return None

        pushover = PushoverNotifier.from_config(config)
        collector = RingCollector(
            email=ring_cfg.get("email", ""),
            password=ring_cfg.get("password", ""),
            token_cache=ring_cfg.get("token_cache", "data/ring_token.cache"),
            pushover=pushover,
        )

        auto_open = ring_cfg.get("auto_open", {})
        return cls(
            ring_collector=collector,
            db_path=db_path,
            poll_interval=ring_cfg.get("poll_interval", 15),
            auto_open_enabled=auto_open.get("enabled", False),
            auto_open_delay=auto_open.get("delay", 5),
            auto_open_schedules=auto_open.get("schedules", []),
            daily_reload=True,
        )
