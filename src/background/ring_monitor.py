"""Background monitor for Ring Intercom — polls events, triggers auto-open, sends notifications."""
import sqlite3
import threading
import time
import json
from datetime import datetime, time as dt_time
from typing import Optional

try:
    from zoneinfo import ZoneInfo
    _SCHEDULE_TZ = ZoneInfo("Europe/Berlin")
except Exception:
    _SCHEDULE_TZ = None

from loguru import logger

from src.data_collector.ring_collector import RingCollector, RING_AVAILABLE
from src.utils.pushover import PushoverNotifier


class RingMonitor:
    """Background thread that monitors Ring Intercom events."""

    def __init__(self, ring_collector: RingCollector, db_path: str = "data/ki_system.db",
                 poll_interval: int = 15, auto_open_enabled: bool = False,
                 auto_open_delay: int = 5, auto_open_schedules: list = None,
                 daily_reload: bool = True, ding_cooldown_seconds: int = 20):
        self.collector = ring_collector
        self.db_path = db_path
        self.poll_interval = poll_interval
        self.auto_open_enabled = auto_open_enabled
        self.auto_open_delay = auto_open_delay
        self.auto_open_schedules = auto_open_schedules or []
        self.daily_reload = daily_reload
        self.ding_cooldown_seconds = max(0, int(ding_cooldown_seconds or 0))

        self.running = False
        self.thread = None
        self._last_reload_date = None
        self._last_ding_ts: Optional[datetime] = None
        self._listener_active = False
        self._reconnect_failures = 0
        self._max_backoff = 300  # max 5 Minuten zwischen Reconnect-Versuchen
        self._last_push_event_ts: Optional[datetime] = None
        self._push_listener_check_interval = 600  # Push-Listener alle 10 Min prüfen
        self._last_listener_check_ts: Optional[datetime] = None

    def _preload_known_event_ids(self):
        """Mark all currently available Ring events as seen so no false notifications fire on startup."""
        # Step 1: load IDs already persisted in DB
        try:
            conn = sqlite3.connect(self.db_path, timeout=10)
            rows = conn.execute(
                "SELECT ring_event_id FROM ring_events ORDER BY timestamp DESC LIMIT 20"
            ).fetchall()
            conn.close()
            known = {row[0] for row in rows if row[0]}
            self.collector._seen_event_ids.update(known)
        except Exception as e:
            logger.warning(f"Ring: Could not preload event IDs from DB: {e}")

        # Step 2: silent poll — add whatever Ring returns right now without sending notifications
        if self.collector.connected:
            try:
                current = self.collector.get_latest_events(limit=10)
                ids_from_api = {e["event_id"] for e in current if e.get("event_id")}
                self.collector._seen_event_ids.update(ids_from_api)
                logger.info(
                    f"Ring: Startup silent poll — marked {len(ids_from_api)} current events as seen"
                )
            except Exception as e:
                logger.warning(f"Ring: Startup silent poll failed: {e}")

    def start(self):
        """Start the monitoring thread."""
        if not RING_AVAILABLE:
            logger.warning("Ring: Library not available, monitor not started")
            return
        if self.running:
            logger.warning("Ring: Monitor already running")
            return

        if not self.collector.connect():
            if getattr(self.collector, "_auth_failed", False):
                logger.error("Ring: Credentials rejected — monitor will not auto-retry. Use the UI to re-test.")
            else:
                logger.error("Ring: Initial connection failed, will retry in background")

        self._preload_known_event_ids()

        # Prevent daily reload from firing immediately when the server starts during hour 4
        self._last_reload_date = datetime.now().date()

        # Try push-based listener first (real-time, <2s latency)
        if self.collector.connected:
            self._listener_active = self.collector.start_event_listener(self._on_push_event)
            if self._listener_active:
                logger.info("Ring: Using push-based event listener (real-time)")
            else:
                logger.warning("Ring: Push listener unavailable, falling back to polling")

        self.running = True
        self.thread = threading.Thread(target=self._run_loop, daemon=True, name="RingMonitor")
        self.thread.start()
        logger.info(f"Ring: Monitor started (poll every {self.poll_interval}s, push={'active' if self._listener_active else 'inactive'})")

    def stop(self):
        """Stop the monitoring thread."""
        self.running = False
        if self._listener_active:
            self.collector.stop_event_listener()
            self._listener_active = False
        if self.thread:
            self.thread.join(timeout=10)
        logger.info("Ring: Monitor stopped")

    def _run_loop(self):
        """Main monitoring loop."""
        while self.running:
            try:
                if self.daily_reload:
                    self._check_daily_reload()

                was_connected = self.collector.connected
                new_events = self.collector.check_for_new_events()
                just_reconnected = not was_connected and self.collector.connected

                for event in new_events:
                    self._handle_event(event)

                if self.collector.connected:
                    self._reconnect_failures = 0
                    # Push-Listener nach Reconnect neu starten
                    if just_reconnected and not self._listener_active:
                        logger.info("Ring: Reconnected — restarting push listener")
                        self._listener_active = self.collector.start_event_listener(self._on_push_event)
                        if self._listener_active:
                            logger.info("Ring: Push listener restarted after reconnect")
                        else:
                            logger.warning("Ring: Push listener restart failed, staying on polling")
                    # Periodischer Health-Check des Push-Listeners
                    self._check_push_listener_health()
                else:
                    self._reconnect_failures += 1

            except Exception as e:
                logger.error(f"Ring: Monitor loop error: {e}")
                self._reconnect_failures += 1

            sleep_seconds = self._get_sleep_interval()
            for _ in range(sleep_seconds):
                if not self.running:
                    break
                time.sleep(1)

    def _get_sleep_interval(self) -> int:
        """Exponentieller Backoff wenn nicht verbunden, sonst normales Poll-Intervall."""
        if self._reconnect_failures == 0:
            return self.poll_interval
        backoff = min(self.poll_interval * (2 ** min(self._reconnect_failures - 1, 5)), self._max_backoff)
        logger.debug(f"Ring: Backoff nach {self._reconnect_failures} Fehlern: {backoff}s")
        return int(backoff)

    def _check_push_listener_health(self):
        """Prüft ob der Push-Listener noch lebt — startet ihn neu wenn er zu lange schweigt."""
        if not self._listener_active:
            return
        now = datetime.now()
        if self._last_listener_check_ts and \
                (now - self._last_listener_check_ts).total_seconds() < self._push_listener_check_interval:
            return
        self._last_listener_check_ts = now
        # Wenn seit >10 Min kein Push-Event und Verbindung eigentlich aktiv → Listener neu starten
        if self._last_push_event_ts is not None:
            silence = (now - self._last_push_event_ts).total_seconds()
            if silence > self._push_listener_check_interval:
                logger.warning(f"Ring: Push-Listener seit {silence:.0f}s ohne Event — neustart")
                self.collector.stop_event_listener()
                self._listener_active = self.collector.start_event_listener(self._on_push_event)
                if self._listener_active:
                    logger.info("Ring: Push-Listener erfolgreich neugestartet")
                else:
                    logger.warning("Ring: Push-Listener Neustart fehlgeschlagen, falle auf Polling zurück")

    def _check_daily_reload(self):
        """Force reconnection once per day at the ~4:00 AM hour."""
        today = datetime.now().date()
        if self._last_reload_date != today and datetime.now().hour == 4:
            self._last_reload_date = today
            logger.info("Ring: Daily reload triggered")
            success = self.collector.refresh_connection()
            # refresh_connection stops the push listener — restart it
            if success:
                self._listener_active = self.collector.start_event_listener(self._on_push_event)
                if self._listener_active:
                    logger.info("Ring: Push listener restarted after daily reload")
                else:
                    self._listener_active = False
                    logger.warning("Ring: Push listener restart failed after daily reload, falling back to polling")
            else:
                self._listener_active = False

    def _handle_event(self, event: dict):
        """Process a new Ring event: save to DB, notify, auto-open."""
        event_type = event.get("event_type", "ding")
        inserted = self._save_event(event)
        if not inserted:
            logger.debug(f"Ring: Duplicate event ignored: {event.get('event_id')}")
            return

        if event_type == "ding":
            event_ts = self._parse_event_timestamp(event.get("timestamp"))
            if self._is_ding_in_cooldown(event_ts):
                logger.info(
                    "Ring: Ding suppressed by cooldown "
                    f"({self.ding_cooldown_seconds}s) for event {event.get('event_id')}"
                )
                return

            self._last_ding_ts = event_ts
            self.collector.pushover.send_ring_event("ding")
            if self.auto_open_enabled and self._is_auto_open_time():
                threading.Timer(
                    self.auto_open_delay,
                    self._auto_open_door,
                    args=[event["event_id"]]
                ).start()

    def _on_push_event(self, ring_event):
        """Handle a real-time push event from RingEventListener.

        *ring_event* is a ``ring_doorbell.RingEvent`` dataclass with fields
        like ``id``, ``kind``, ``device_name``, ``now``.
        """
        event_id = str(ring_event.id)
        event_type = getattr(ring_event, "kind", "ding")

        # Convert to the dict format _handle_event expects
        event = {
            "event_id": event_id,
            "event_type": event_type,
            "timestamp": datetime.now(),
            "answered": False,
            "duration": 0,
            "source": "push",
        }

        # Mark as seen so the polling loop won't re-process it
        if hasattr(self.collector, "_seen_event_ids"):
            self.collector._seen_event_ids.add(event_id)

        self._last_push_event_ts = datetime.now()
        logger.info(f"Ring: Push event — {event_type} (id={event_id})")
        self._handle_event(event)

    def _parse_event_timestamp(self, timestamp_value) -> datetime:
        """Convert Ring timestamp value to datetime, fallback to current time."""
        if isinstance(timestamp_value, datetime):
            return timestamp_value

        if isinstance(timestamp_value, str) and timestamp_value:
            try:
                return datetime.fromisoformat(timestamp_value)
            except ValueError:
                pass

        return datetime.now()

    def _is_ding_in_cooldown(self, event_ts: datetime) -> bool:
        """Return True when a ding happened recently and should be suppressed."""
        if self.ding_cooldown_seconds <= 0 or self._last_ding_ts is None:
            return False

        delta = (event_ts - self._last_ding_ts).total_seconds()
        return 0 <= delta < self.ding_cooldown_seconds

    def _auto_open_door(self, event_id: str):
        """Open the door and log it."""
        if self.collector.open_door():
            self.collector.pushover.send_ring_event("auto_open")
            self._update_event_auto_opened(event_id)
            logger.info(f"Ring: Auto-opened door for event {event_id}")

    def _is_auto_open_time(self) -> bool:
        """Check if current time falls within any auto-open schedule.

        Schedules werden in Europe/Berlin ausgewertet, damit die UI-Zeiten
        unabhaengig von der Server-Zeitzone (z.B. UTC) korrekt greifen.
        """
        if not self.auto_open_schedules:
            return True  # no schedule restriction = always allowed when enabled
        if _SCHEDULE_TZ is not None:
            now = datetime.now(_SCHEDULE_TZ)
        else:
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

    def _save_event(self, event: dict) -> bool:
        """Persist event to ring_events table and return True on new insert."""
        try:
            # Timestamps from ring_doorbell 0.9.x may be datetime objects — normalise to str.
            def _to_str(v):
                return v.isoformat() if hasattr(v, "isoformat") else v

            serialisable = {k: _to_str(v) for k, v in event.items()}
            timestamp = _to_str(event.get("timestamp", datetime.now().isoformat()))

            conn = sqlite3.connect(self.db_path, timeout=10)
            cursor = conn.execute(
                """INSERT OR IGNORE INTO ring_events
                   (event_type, ring_event_id, timestamp, duration, answered, auto_opened, metadata)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    event.get("event_type", "ding"),
                    event.get("event_id"),
                    timestamp,
                    event.get("duration"),
                    event.get("answered", False),
                    False,
                    json.dumps(serialisable),
                )
            )
            conn.commit()
            conn.close()
            return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Ring: Failed to save event: {e}")
            return False

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
        health["auto_open_delay"] = self.auto_open_delay
        health["auto_open_schedules"] = self.auto_open_schedules
        health["monitor_running"] = self.running
        health["push_listener_active"] = self._listener_active
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
            ding_cooldown_seconds=ring_cfg.get("ding_cooldown_seconds", 20),
        )
