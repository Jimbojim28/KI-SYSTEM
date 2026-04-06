"""Pushover notification utility for KI-SYSTEM."""
import requests
from loguru import logger


class PushoverNotifier:
    """Send push notifications via Pushover API."""

    API_URL = "https://api.pushover.net/1/messages.json"

    def __init__(self, user_key: str, app_key: str):
        self.user_key = user_key
        self.app_key = app_key
        self.enabled = bool(user_key and app_key)

    def send(self, message: str, title: str = "KI Smart Home", priority: int = 0) -> bool:
        """Send a push notification. Returns True on success."""
        if not self.enabled:
            logger.warning("Pushover not configured, skipping notification")
            return False

        try:
            response = requests.post(self.API_URL, data={
                "user": self.user_key,
                "token": self.app_key,
                "message": message,
                "title": title,
                "priority": priority,
            }, timeout=10)
            if response.status_code == 200:
                logger.info(f"Pushover sent: {message[:50]}")
                return True
            else:
                logger.error(f"Pushover error {response.status_code}: {response.text}")
                return False
        except Exception as e:
            logger.error(f"Pushover failed: {e}")
            return False

    def send_ring_event(self, event_type: str) -> bool:
        """Send notification for a Ring event."""
        messages = {
            "ding": "Jemand klingelt an der Tuer",
            "auto_open": "Tuer automatisch geoeffnet",
            "manual_open": "Tuer manuell geoeffnet",
            "token_expired": "Ring Token abgelaufen - 2FA noetig!",
            "connection_lost": "Ring API nicht erreichbar",
            "connection_restored": "Ring Verbindung wiederhergestellt",
        }
        priorities = {
            "ding": 0,
            "auto_open": 0,
            "manual_open": 0,
            "token_expired": 1,
            "connection_lost": 1,
            "connection_restored": -1,
        }
        msg = messages.get(event_type, f"Ring Event: {event_type}")
        prio = priorities.get(event_type, 0)
        return self.send(msg, title="Ring Intercom", priority=prio)

    @staticmethod
    def from_config(config: dict) -> "PushoverNotifier":
        """Create notifier from config dict."""
        # Pushover can live at top level or under notifications.pushover
        pushover_cfg = config.get("pushover") or config.get("notifications", {}).get("pushover", {})
        return PushoverNotifier(
            user_key=pushover_cfg.get("user_key", ""),
            app_key=pushover_cfg.get("api_token", pushover_cfg.get("app_key", "")),
        )