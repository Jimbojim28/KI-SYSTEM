"""Ring Intercom collector — auth, events, door control, health monitoring."""
import asyncio
import json
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional, Any

from loguru import logger

try:
    from ring_doorbell import Ring, Auth, AuthenticationError, Requires2FAError
    from ring_doorbell import RingEventListener
    RING_AVAILABLE = True
except ImportError:
    RING_AVAILABLE = False
    Ring = None
    Auth = None
    AuthenticationError = Exception
    Requires2FAError = Exception
    RingEventListener = None
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
        self._seen_event_ids: set = set()  # all IDs seen in this session
        self.last_error: Optional[str] = None
        self.requires_2fa = False
        self._consecutive_failures = 0
        self._max_failures = 3
        self._auth_failed = False  # True after credentials are rejected — blocks auto-reconnect
        self._event_listener: Optional[Any] = None  # RingEventListener instance
        self._on_ding_callback = None  # callable set by RingMonitor

        # Persistent event loop in its own thread so aiohttp sessions stay alive across calls.
        self._loop = asyncio.new_event_loop()
        self._loop_thread = threading.Thread(
            target=self._loop.run_forever, daemon=True, name="RingEventLoop"
        )
        self._loop_thread.start()

    def _run_async(self, coro, timeout: int = 30):
        """Run an async coroutine on the persistent Ring event loop (thread-safe)."""
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout=timeout)

    def connect(self, otp_code: Optional[str] = None) -> bool:
        """Authenticate with Ring API and find the Intercom device."""
        if not RING_AVAILABLE:
            self.last_error = "Ring-Bibliothek nicht verfuegbar"
            self.requires_2fa = False
            logger.error("ring_doorbell library not available")
            return False

        self.last_error = None
        self.requires_2fa = False

        try:
            token_data = self._load_token()
            auth = Auth("KI-SYSTEM/1.0", token_data, self._save_token)

            if token_data:
                logger.info("Ring: Loaded cached token")
                self.ring = Ring(auth)
                try:
                    self._run_async(self.ring.async_update_data())
                except AuthenticationError:
                    logger.info("Ring: Cached token invalid, retrying with credentials")
                    auth = self._authenticate_with_credentials(otp_code=otp_code)
                    self.ring = Ring(auth)
                    self._run_async(self.ring.async_update_data())
            else:
                auth = self._authenticate_with_credentials(otp_code=otp_code)
                self.ring = Ring(auth)
                self._run_async(self.ring.async_update_data())

            # Find intercom device
            intercoms = list(self.ring.devices().other)
            if intercoms:
                self.intercom = intercoms[0]
                self.connected = True
                self.last_error = None
                self.requires_2fa = False
                self._auth_failed = False
                self._consecutive_failures = 0
                logger.info(f"Ring: Connected to intercom '{self.intercom.name}'")
                return True
            else:
                self.connected = False
                self.last_error = "Kein Ring Intercom gefunden"
                logger.error("Ring: No intercom device found")
                return False

        except Requires2FAError:
            self.connected = False
            self.requires_2fa = True
            self._auth_failed = True
            self.last_error = "2FA-Code erforderlich"
            logger.warning("Ring: 2FA code required for authentication")
            return False
        except AuthenticationError as e:
            self.connected = False
            self._auth_failed = True
            self.last_error = "Authentifizierung fehlgeschlagen"
            logger.error(f"Ring: Authentication failed: {e}")
            self._handle_connection_failure()
            return False
        except Exception as e:
            self.connected = False
            self.last_error = str(e) or "Verbindung fehlgeschlagen"
            logger.error(f"Ring: Connection failed: {e}")
            self._handle_connection_failure()
            return False

    def _authenticate_with_credentials(self, otp_code: Optional[str] = None):
        """Authenticate with Ring credentials and optional OTP (ring_doorbell 0.9.x async API)."""
        logger.info("Ring: Authenticating with email/password...")
        auth = Auth("KI-SYSTEM/1.0", None, self._save_token)
        self._run_async(auth.async_fetch_token(
            username=self.email, password=self.password, otp_code=otp_code
        ))
        if auth._token:
            self._save_token(auth._token)
        return auth

    def test_connection(self, otp_code: Optional[str] = None) -> Dict[str, Any]:
        """Run a connection test and return a user-facing result payload."""
        # Manual test always gets a fresh attempt regardless of prior auth failures.
        self._auth_failed = False
        success = self.connect(otp_code=otp_code)
        if success:
            return {
                "success": True,
                "message": "Verbindung erfolgreich! Ring-Token gespeichert.",
            }

        result = {
            "success": False,
            "error": self.last_error or "Authentifizierung fehlgeschlagen",
        }
        if self.requires_2fa:
            result["requires_2fa"] = True
        return result

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
        battery = None
        if self.intercom is not None:
            try:
                battery = self.intercom.battery_life
            except Exception:
                pass
        return {
            "connected": self.connected,
            "token_valid": self.ring is not None,
            "intercom_found": self.intercom is not None,
            "requires_2fa": self.requires_2fa,
            "error": self.last_error,
            "consecutive_failures": self._consecutive_failures,
            "last_poll": getattr(self, "_last_poll_time", None),
            "battery_life": battery,
        }

    def open_door(self, notify: bool = True) -> bool:
        """Trigger the intercom door unlock."""
        if not self.connected or not self.intercom:
            logger.error("Ring: Cannot open door — not connected")
            return False
        try:
            self._run_async(self.intercom.async_open_door())
            logger.info("Ring: Door opened")
            if notify:
                self.pushover.send_ring_event("manual_open")
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
            history = self._run_async(self.intercom.async_history(limit=limit))
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
            if self._auth_failed:
                return []
            if not self.connect():
                return []
        try:
            self._last_poll_time = time.time()
            events = self.get_latest_events(limit=5)
            new_events = []
            for event in events:
                eid = event["event_id"]
                if eid and eid not in self._seen_event_ids:
                    new_events.append(event)
                self._seen_event_ids.add(eid)
                self.last_event_id = eid
            if new_events:
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
        self.stop_event_listener()
        self.connected = False
        self.ring = None
        self.intercom = None
        success = self.connect()
        if success:
            self.pushover.send_ring_event("connection_restored")
        return success

    def start_event_listener(self, callback) -> bool:
        """Start the FCM push listener for real-time Ring events.

        *callback* receives a ``RingEvent`` dataclass on each push notification.
        Returns True when the listener was started successfully.
        """
        if not RING_AVAILABLE or RingEventListener is None:
            logger.warning("Ring: RingEventListener not available")
            return False
        if not self.ring:
            logger.warning("Ring: Cannot start listener — not connected")
            return False

        self._on_ding_callback = callback

        try:
            credentials_path = self.token_cache.with_suffix(".listener")
            creds = None
            if credentials_path.exists():
                try:
                    creds = json.loads(credentials_path.read_text())
                except Exception:
                    pass

            def _save_listener_creds(new_creds):
                credentials_path.parent.mkdir(parents=True, exist_ok=True)
                credentials_path.write_text(json.dumps(new_creds))

            self._event_listener = RingEventListener(
                self.ring,
                credentials=creds,
                credentials_updated_callback=_save_listener_creds,
            )
            self._event_listener.add_notification_callback(self._on_push_notification)

            started = self._run_async(self._event_listener.start(timeout=15))
            if started:
                logger.info("Ring: Push event listener started (FCM)")
            else:
                logger.warning("Ring: Push event listener failed to start")
            return started
        except Exception as e:
            logger.error(f"Ring: Failed to start event listener: {e}")
            self._event_listener = None
            return False

    def _on_push_notification(self, event):
        """Internal callback — forwards push events to the registered handler."""
        logger.info(f"Ring: Push event received — kind={event.kind}, id={event.id}")
        if self._on_ding_callback:
            try:
                self._on_ding_callback(event)
            except Exception as e:
                logger.error(f"Ring: Error in push event callback: {e}")

    def stop_event_listener(self):
        """Stop the FCM push listener if running."""
        if self._event_listener:
            try:
                self._run_async(self._event_listener.stop())
                logger.info("Ring: Push event listener stopped")
            except Exception as e:
                logger.warning(f"Ring: Error stopping event listener: {e}")
            self._event_listener = None
