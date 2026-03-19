"""
Notification Bundler – Bündelt Pushover-Nachrichten innerhalb eines Zeitfensters.

Alle Pushover-Sender leiten ihre Nachrichten hierher.  Der Bundler sammelt sie
für `window_seconds` Sekunden und schickt anschließend eine einzige kombinierte
Push-Nachricht.  Bei priority >= 1 wird der Puffer sofort geleert.
"""

import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional
from pathlib import Path

import yaml
import requests
from loguru import logger


@dataclass
class PendingNotification:
    title: str
    message: str
    priority: int = 0
    html: bool = True
    source: str = ""
    timestamp: datetime = field(default_factory=datetime.now)


class NotificationBundler:
    """
    Thread-sicherer Singleton.

    - add()    → Nachricht in Puffer stellen
    - _flush() → Puffer leeren und eine gebündelte Pushover-Nachricht senden
    """

    def __init__(self):
        self._queue: List[PendingNotification] = []
        self._queue_lock = threading.Lock()
        self._timer: Optional[threading.Timer] = None

    # ------------------------------------------------------------------
    # Öffentliche API
    # ------------------------------------------------------------------

    def add(
        self,
        title: str,
        message: str,
        priority: int = 0,
        html: bool = True,
        source: str = "",
        force_immediate: bool = False,
    ):
        """Nachricht in Puffer stellen.

        Bei priority >= 1 oder force_immediate=True wird der Puffer sofort
        geleert (alle bereits gepufferten Nachrichten werden mitgeschickt).
        """
        config = self._load_config()

        if not config.get("enabled", True):
            # Bundler deaktiviert → direkt senden
            self._send_direct(title, message, priority, html)
            return

        notif = PendingNotification(
            title=title,
            message=message,
            priority=priority,
            html=html,
            source=source,
        )

        is_critical = priority >= 1 or force_immediate

        with self._queue_lock:
            self._queue.append(notif)

            if is_critical:
                logger.debug(
                    f"Bundler: kritische Nachricht → sofortiger Flush ({source or title!r})"
                )
                # Timer abbrechen, sofort senden
                if self._timer:
                    self._timer.cancel()
                    self._timer = None
                notifications = list(self._queue)
                self._queue.clear()

            else:
                # Timer starten, falls noch keiner läuft
                if self._timer is None:
                    window = config.get("window_seconds", 30)
                    self._timer = threading.Timer(window, self._flush_from_timer)
                    self._timer.daemon = True
                    self._timer.start()
                    logger.debug(
                        f"Bundler: Timer gestartet ({window}s) für {source or title!r}"
                    )
                return  # Nachricht liegt im Puffer, Timer läuft

        # Kritischer Pfad: außerhalb des Locks senden
        self._send_bundled(notifications)

    def flush_now(self):
        """Sofortiger Flush (z. B. beim Shutdown)."""
        with self._queue_lock:
            if self._timer:
                self._timer.cancel()
                self._timer = None
            notifications = list(self._queue)
            self._queue.clear()

        if notifications:
            self._send_bundled(notifications)

    # ------------------------------------------------------------------
    # Internes
    # ------------------------------------------------------------------

    def _flush_from_timer(self):
        """Wird vom Timer-Thread aufgerufen."""
        with self._queue_lock:
            self._timer = None
            notifications = list(self._queue)
            self._queue.clear()

        if notifications:
            self._send_bundled(notifications)

    def _load_config(self) -> dict:
        try:
            config_path = Path("config/config.yaml")
            if config_path.exists():
                with open(config_path, "r") as f:
                    full_config = yaml.safe_load(f) or {}
                bundler = full_config.get("notifications", {}).get("bundler", {})
                return {
                    "enabled": bundler.get("enabled", True),
                    "window_seconds": bundler.get("window_seconds", 30),
                }
        except Exception as e:
            logger.debug(f"Bundler: Konnte Config nicht laden: {e}")
        return {"enabled": True, "window_seconds": 30}

    def _get_credentials(self):
        try:
            config_path = Path("config/config.yaml")
            if config_path.exists():
                with open(config_path, "r") as f:
                    full_config = yaml.safe_load(f) or {}
                notifications = full_config.get("notifications", {})
                pushover = notifications.get("pushover", {})
                api_key = pushover.get("api_token", "")
                user_key = pushover.get("user_key", "")

                if not api_key or not user_key:
                    absence = full_config.get("absence", {})
                    api_key = api_key or absence.get("pushover_api_key", "")
                    user_key = user_key or absence.get("pushover_user_key", "")

                return api_key, user_key
        except Exception as e:
            logger.debug(f"Bundler: Konnte Credentials nicht laden: {e}")
        return "", ""

    def _send_bundled(self, notifications: List[PendingNotification]):
        if not notifications:
            return

        api_key, user_key = self._get_credentials()
        if not api_key or not user_key:
            logger.debug("Bundler: Pushover nicht konfiguriert – Nachrichten verworfen")
            return

        if len(notifications) == 1:
            n = notifications[0]
            self._post(api_key, user_key, n.title, n.message, n.priority, n.html)
            logger.info(f"Bundler flush: 1 Nachricht → {n.title!r}")
            return

        # Mehrere Nachrichten bündeln
        max_priority = max(n.priority for n in notifications)
        use_html = any(n.html for n in notifications)

        critical = [n for n in notifications if n.priority >= 1]
        if critical:
            title = f"⚠️ {critical[0].title} (+{len(notifications) - 1} weitere)"
        else:
            title = f"🏠 Smart Home ({len(notifications)} Meldungen)"

        separator = "\n\n――――――――――\n\n"
        parts = []
        for n in notifications:
            if use_html:
                parts.append(f"<b>{n.title}</b>\n{n.message}")
            else:
                parts.append(f"{n.title}\n{n.message}")

        combined = separator.join(parts)
        self._post(api_key, user_key, title, combined, max_priority, use_html)
        logger.info(
            f"Bundler flush: {len(notifications)} Nachrichten → 1 Pushover (priority={max_priority})"
        )

    def _send_direct(self, title: str, message: str, priority: int, html: bool):
        """Direktsenden wenn Bundler deaktiviert."""
        api_key, user_key = self._get_credentials()
        if api_key and user_key:
            self._post(api_key, user_key, title, message, priority, html)

    def _post(
        self,
        api_key: str,
        user_key: str,
        title: str,
        message: str,
        priority: int,
        html: bool,
    ):
        try:
            payload = {
                "token": api_key,
                "user": user_key,
                "title": title,
                "message": message,
                "priority": priority,
            }
            if html:
                payload["html"] = 1

            response = requests.post(
                "https://api.pushover.net/1/messages.json",
                data=payload,
                timeout=30,
            )
            if response.status_code == 200:
                logger.debug(f"Bundler: Pushover OK → {title!r}")
            else:
                logger.error(
                    f"Bundler: Pushover Fehler {response.status_code}: {response.text}"
                )
        except Exception as e:
            logger.error(f"Bundler: Fehler beim Senden: {e}")


# ---------------------------------------------------------------------------
# Modul-Level Singleton
# ---------------------------------------------------------------------------

_bundler: Optional[NotificationBundler] = None
_bundler_lock = threading.Lock()


def get_bundler() -> NotificationBundler:
    """Gibt den globalen NotificationBundler-Singleton zurück."""
    global _bundler
    if _bundler is None:
        with _bundler_lock:
            if _bundler is None:
                _bundler = NotificationBundler()
    return _bundler


def reset_bundler():
    """Setzt den Singleton zurück (nützlich für Tests)."""
    global _bundler
    if _bundler is not None:
        _bundler.flush_now()
    _bundler = None
