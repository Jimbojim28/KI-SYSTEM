"""Ring Intercom collector — auth, events, door control, health monitoring."""
import json
import time
from pathlib import Path
from typing import Dict, List, Optional, Any

from loguru import logger

try:
    from ring_doorbell import Ring, Auth
    RING_AVAILABLE = True
except ImportError:
    RING_AVAILABLE = False
    logger.warning("ring_doorbell not installed, Ring integration disabled")

from src.utils.pushover import PushoverNotifier


class RingCollector:
    """Wraps ring_doorbell library for Ring Intercom integration."""

    def __init__(self, email: str, password: str, token_cache: str = "data/ring_token.cache",
                 pushover: Optional[PushoverNotifier] = None):
        self.email = email
        self.password = password
        self.token_cache = Path(token_cache)
        self.pushover = pushover or PushoverNotifier("", "")
        self.ring: Optional[Ring] = None
        self.intercom = None
        self.connected = False
        self.last_event_id: Optional[str] = None
        self._consecutive_failures = 0
        self._max_failures = 3

    def connect(self) -> bool:
        """Authenticate with Ring API and find the Intercom device."""
        if not RING_AVAILABLE:
            logger.error("ring_doorbell library not available")
            return False

        try:
            auth = Auth("KI-SYSTEM/1.0")

            # Try loading cached token first
            if self.token_cache.exists():
                try:
                    token_data = json.loads(self.token_cache.read_text())
                    auth.token = token_data
                    logger.info("Ring: Loaded cached token")
                except Exception as e:
                    logger.warning(f"Ring: Failed to load cached token: {e}")

            # If no valid token, authenticate with credentials
            if not auth.token:
                logger.info("Ring: Authenticating with email/password...")
                auth.fetch_token(username=self.email, password=self.password)
                self._save_token(auth.token)

            self.ring = Ring(auth)
            self.ring.update_data()

            # Find intercom device
            intercoms = list(self.ring.intercoms)
            if intercoms:
                self.intercom = intercoms[0]
                self.connected = True
                self._consecutive_failures = 0
                logger.info(f"Ring: Connected to intercom '{self.intercom.name}'")
                return True
            else:
                logger.error("Ring: No intercom device found")
                return False

        except Exception as e:
            logger.error(f"Ring: Connection failed: {e}")
            self._handle_connection_failure()
            return False

    def _save_token(self, token: dict):
        """Persist auth token to cache file."""
        self.token_cache.parent.mkdir(parents=True, exist_ok=True)
        self.token_cache.write_text(json.dumps(token))
        logger.debug("Ring: Token saved to cache")

    def _load_token(self) -> Optional[dict]:
        """Load auth token from cache file."""
        if self.token_cache.exists():
            try:
                return json.loads(self.token_cache.read_text())
            except Exception:
                return None
        return None

    def get_health(self) -> Dict[str, Any]:
        """Return connection health status."""
        return {
            "connected": self.connected,
            "token_valid": self.ring is not None,
            "intercom_found": self.intercom is not None,
            "consecutive_failures": self._consecutive_failures,
            "last_poll": getattr(self, "_last_poll_time", None),
        }

    def open_door(self) -> bool:
        """Trigger the intercom door unlock."""
        if not self.connected or not self.intercom:
            logger.error("Ring: Cannot open door — not connected")
            return False
        try:
            self.intercom.open_door()
            logger.info("Ring: Door opened")
            return True
        except Exception as e:
            logger.error(f"Ring: Failed to open door: {e}")
            return False

    def get_latest_events(self, limit: int = 10) -> List[Dict]:
        """Fetch latest events from Ring API (last N events)."""
        if not self.connected or not self.intercom:
            return []
        try:
            events = []
            history = self.intercom.history(limit=limit)
            for event in history:
                events.append({
                    "event_id": str(event.get("id", "")),
                    "event_type": event.get("kind", "ding"),
                    "timestamp": event.get("created_at", ""),
                    "answered": event.get("answered", False),
                    "duration": event.get("duration", 0),
                })
            return events
        except Exception as e:
            logger.error(f"Ring: Failed to fetch events: {e}")
            return []

    def check_for_new_events(self) -> List[Dict]:
        """Poll for new events since last check. Returns list of new events."""
        if not self.connected:
            if not self.connect():
                return []
        try:
            self._last_poll_time = time.time()
            events = self.get_latest_events(limit=5)
            new_events = []
            for event in events:
                eid = event["event_id"]
                if eid and eid != self.last_event_id:
                    new_events.append(event)
                    self.last_event_id = eid
                    self._consecutive_failures = 0
            return new_events
        except Exception as e:
            logger.error(f"Ring: Poll failed: {e}")
            self._handle_connection_failure()
            return []

    def _handle_connection_failure(self):
        """Handle connection failures with escalation."""
        self._consecutive_failures += 1
        self.connected = False

        if self._consecutive_failures >= self._max_failures:
            self.pushover.send_ring_event("connection_lost")
            logger.error(f"Ring: {self._consecutive_failures} consecutive failures — alert sent")

    def refresh_connection(self) -> bool:
        """Force reconnection attempt."""
        logger.info("Ring: Refreshing connection...")
        self.connected = False
        self.ring = None
        self.intercom = None
        success = self.connect()
        if success:
            self.pushover.send_ring_event("connection_restored")
        return success
