# Ring Intercom Integration Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrate Ring Intercom directly via `ring_doorbell` Python library with event monitoring, door opener, Pushover notifications, and dashboard UI.

**Architecture:** Ring Collector wraps the `ring_doorbell` library for auth/event/device control. Ring Monitor runs as a background thread polling for events. Pushover utility handles notifications. Flask Blueprint serves API + dashboard page.

**Tech Stack:** Python 3.8+, `ring_doorbell` library, Flask Blueprint, SQLite, Pushover API, loguru

**Spec:** `docs/superpowers/specs/2026-04-03-ring-intercom-design.md`

---

### Task 1: Add `ring_doorbell` Dependency

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Add ring_doorbell to requirements.txt**

Append to `requirements.txt`:
```
ring_doorbell==0.9.10
```

- [ ] **Step 2: Install dependency**

Run: `cd /Users/shp-art/Documents/Github/KI-SYSTEM && source venv/bin/activate && pip install ring_doorbell==0.9.10`
Expected: Successfully installed

- [ ] **Step 3: Commit**

```bash
git add requirements.txt
git commit -m "chore: add ring_doorbell dependency"
```

---

### Task 2: Database Schema — `ring_events` Table

**Files:**
- Modify: `src/utils/database.py`

- [ ] **Step 1: Add ring_events table creation to database init**

In `src/utils/database.py`, find the `_init_database` method. Add this table creation after the existing tables:

```python
            # Ring Events
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS ring_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    ring_event_id TEXT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    duration INTEGER,
                    answered BOOLEAN DEFAULT FALSE,
                    auto_opened BOOLEAN DEFAULT FALSE,
                    metadata TEXT
                )
            ''')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_ring_events_timestamp ON ring_events(timestamp)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_ring_events_ring_id ON ring_events(ring_event_id)')
```

- [ ] **Step 2: Verify database creates table**

Run: `cd /Users/shp-art/Documents/Github/KI-SYSTEM && source venv/bin/activate && python3 -c "from src.utils.database import Database; db = Database('data/test_ring.db'); print(db.execute('SELECT name FROM sqlite_master WHERE type=\"table\" AND name=\"ring_events\"'))"`
Expected: `[{'name': 'ring_events'}]`

- [ ] **Step 3: Clean up test db and commit**

```bash
rm -f data/test_ring.db
git add src/utils/database.py
git commit -m "feat: add ring_events database table"
```

---

### Task 3: Pushover Notification Utility

**Files:**
- Create: `src/utils/pushover.py`

- [ ] **Step 1: Create pushover.py**

Create `src/utils/pushover.py`:

```python
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
            "token_expired": "Ring Token abgelaufen - 2FA noetig!",
            "connection_lost": "Ring API nicht erreichbar",
            "connection_restored": "Ring Verbindung wiederhergestellt",
        }
        priorities = {
            "ding": 0,
            "auto_open": 0,
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
        pushover_cfg = config.get("pushover", {})
        return PushoverNotifier(
            user_key=pushover_cfg.get("user_key", ""),
            app_key=pushover_cfg.get("app_key", ""),
        )
```

- [ ] **Step 2: Verify import works**

Run: `cd /Users/shp-art/Documents/Github/KI-SYSTEM && source venv/bin/activate && python3 -c "from src.utils.pushover import PushoverNotifier; n = PushoverNotifier('', ''); print('disabled' if not n.enabled else 'enabled')"`
Expected: `disabled`

- [ ] **Step 3: Commit**

```bash
git add src/utils/pushover.py
git commit -m "feat: add Pushover notification utility"
```

---

### Task 4: Ring Collector — Auth & Device Control

**Files:**
- Create: `src/data_collector/ring_collector.py`

- [ ] **Step 1: Create ring_collector.py**

Create `src/data_collector/ring_collector.py`:

```python
"""Ring Intercom collector — auth, events, door control, health monitoring."""
import json
import time
from pathlib import Path
from typing import Dict, List, Optional, Any

from loguru import logger

try:
    from ring_doorbell import Ring, Auth
    from ring_doorbell.auth import OTP
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
            auth = Auth("KI-SYSTEM/1.0", token_updater=self._save_token)

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
```

- [ ] **Step 2: Verify import works**

Run: `cd /Users/shp-art/Documents/Github/KI-SYSTEM && source venv/bin/activate && python3 -c "from src.data_collector.ring_collector import RingCollector, RING_AVAILABLE; print(f'ring_doorbell available: {RING_AVAILABLE}')"`
Expected: `ring_doorbell available: True`

- [ ] **Step 3: Commit**

```bash
git add src/data_collector/ring_collector.py
git commit -m "feat: add Ring Intercom collector with auth, events, door control"
```

---

### Task 5: Ring Monitor — Background Process

**Files:**
- Create: `src/background/ring_monitor.py`

- [ ] **Step 1: Create ring_monitor.py**

Create `src/background/ring_monitor.py`:

```python
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
                # Daily reload for token refresh
                if self.daily_reload:
                    self._check_daily_reload()

                # Poll for new events
                new_events = self.collector.check_for_new_events()
                for event in new_events:
                    self._handle_event(event)

            except Exception as e:
                logger.error(f"Ring: Monitor loop error: {e}")

            # Sleep in small increments for responsive shutdown
            for _ in range(self.poll_interval):
                if not self.running:
                    break
                time.sleep(1)

    def _check_daily_reload(self):
        """Force reconnection once per day (default: at ~4:00 AM)."""
        today = datetime.now().date()
        if self._last_reload_date != today and datetime.now().hour == 4:
            self._last_reload_date = today
            logger.info("Ring: Daily reload triggered")
            self.collector.refresh_connection()

    def _handle_event(self, event: dict):
        """Process a new Ring event: save to DB, notify, auto-open."""
        event_type = event.get("event_type", "ding")

        # Save to database
        self._save_event(event)

        # Send Pushover notification for ding events
        if event_type == "ding":
            self.collector.pushover.send_ring_event("ding")

            # Check if auto-open should trigger
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
        current_day = now.weekday()  # 0=Mon, 6=Sun
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
```

- [ ] **Step 2: Verify import works**

Run: `cd /Users/shp-art/Documents/Github/KI-SYSTEM && source venv/bin/activate && python3 -c "from src.background.ring_monitor import RingMonitor; print('RingMonitor imported OK')"`
Expected: `RingMonitor imported OK`

- [ ] **Step 3: Commit**

```bash
git add src/background/ring_monitor.py
git commit -m "feat: add Ring Monitor background process with auto-open and scheduling"
```

---

### Task 6: Ring Blueprint — API Endpoints

**Files:**
- Create: `src/web/blueprints/api_ring.py`

- [ ] **Step 1: Create api_ring.py**

Create `src/web/blueprints/api_ring.py`:

```python
"""Ring Intercom Flask Blueprint — API endpoints and dashboard page."""
from flask import Blueprint, jsonify, request, render_template
from loguru import logger

ring_bp = Blueprint('ring', __name__, url_prefix='/ring')

# Global references — set by init function
_ring_monitor = None
_db = None
_config = None


def init_ring_blueprint(ring_monitor, db, config):
    """Initialize blueprint with Ring Monitor and Database references."""
    global _ring_monitor, _db, _config
    _ring_monitor = ring_monitor
    _db = db
    _config = config


# ─── Dashboard Page ──────────────────────────────────────────────

@ring_bp.route('')
def ring_dashboard():
    """Render Ring Intercom dashboard page."""
    return render_template('ring.html')


# ─── API Endpoints ───────────────────────────────────────────────

@ring_bp.route('/api/ring/status', methods=['GET'])
def get_status():
    """GET /ring/api/ring/status — Connection health and last event."""
    if not _ring_monitor:
        return jsonify({"error": "Ring monitor not configured", "connected": False}), 200

    status = _ring_monitor.get_status()
    events = _ring_monitor.get_recent_events(limit=1)
    if events:
        status["last_event"] = events[0]

    return jsonify(status)


@ring_bp.route('/api/ring/events', methods=['GET'])
def get_events():
    """GET /ring/api/ring/events?limit=20 — Recent events."""
    limit = request.args.get("limit", 20, type=int)
    if not _ring_monitor:
        return jsonify({"events": []})
    events = _ring_monitor.get_recent_events(limit=limit)
    return jsonify({"events": events})


@ring_bp.route('/api/ring/open', methods=['POST'])
def open_door():
    """POST /ring/api/ring/open — Manually open the door."""
    if not _ring_monitor:
        return jsonify({"error": "Ring monitor not configured"}), 503

    success = _ring_monitor.collector.open_door()
    if success:
        return jsonify({"success": True, "message": "Tuer geoeffnet"})
    else:
        return jsonify({"success": False, "error": "Oeffnen fehlgeschlagen"}), 500


@ring_bp.route('/api/ring/health', methods=['GET'])
def get_health():
    """GET /ring/api/ring/health — Detailed health check."""
    if not _ring_monitor:
        return jsonify({"connected": False, "error": "not configured"})

    health = _ring_monitor.collector.get_health()
    health["monitor_running"] = _ring_monitor.running
    health["poll_interval"] = _ring_monitor.poll_interval
    return jsonify(health)


@ring_bp.route('/api/ring/settings', methods=['GET'])
def get_settings():
    """GET /ring/api/ring/settings — Current settings."""
    if not _ring_monitor:
        return jsonify({})

    return jsonify({
        "auto_open_enabled": _ring_monitor.auto_open_enabled,
        "auto_open_delay": _ring_monitor.auto_open_delay,
        "auto_open_schedules": _ring_monitor.auto_open_schedules,
        "poll_interval": _ring_monitor.poll_interval,
    })


@ring_bp.route('/api/ring/settings', methods=['POST'])
def update_settings():
    """POST /ring/api/ring/settings — Update auto-open settings."""
    if not _ring_monitor:
        return jsonify({"error": "Ring monitor not configured"}), 503

    data = request.get_json()
    _ring_monitor.update_settings(
        auto_open_enabled=data.get("auto_open_enabled"),
        auto_open_delay=data.get("auto_open_delay"),
        auto_open_schedules=data.get("auto_open_schedules"),
    )
    return jsonify({"success": True})


@ring_bp.route('/api/ring/test-notification', methods=['POST'])
def test_notification():
    """POST /ring/api/ring/test-notification — Send Pushover test message."""
    if not _ring_monitor:
        return jsonify({"error": "Ring monitor not configured"}), 503

    success = _ring_monitor.collector.pushover.send(
        "Test-Benachrichtigung vom KI-SYSTEM",
        title="Ring Intercom Test",
    )
    return jsonify({"success": success})


@ring_bp.route('/api/ring/reconnect', methods=['POST'])
def reconnect():
    """POST /ring/api/ring/reconnect — Force reconnection."""
    if not _ring_monitor:
        return jsonify({"error": "Ring monitor not configured"}), 503

    success = _ring_monitor.collector.refresh_connection()
    return jsonify({"success": success})
```

- [ ] **Step 2: Verify import works**

Run: `cd /Users/shp-art/Documents/Github/KI-SYSTEM && source venv/bin/activate && python3 -c "from src.web.blueprints.api_ring import ring_bp, init_ring_blueprint; print(f'Blueprint: {ring_bp.name}, prefix: {ring_bp.url_prefix}')"`
Expected: `Blueprint: ring, prefix: /ring`

- [ ] **Step 3: Commit**

```bash
git add src/web/blueprints/api_ring.py
git commit -m "feat: add Ring Intercom Flask Blueprint with API endpoints"
```

---

### Task 7: Ring Dashboard HTML

**Files:**
- Create: `src/web/templates/ring.html`
- Modify: `src/web/templates/base.html` — Add nav link

- [ ] **Step 1: Create ring.html**

Create `src/web/templates/ring.html`:

```html
{% extends "base.html" %}

{% block title %}Ring Intercom — KI Smart Home{% endblock %}

{% block content %}
<div class="fade-in">
    <div class="dashboard-header">
        <div class="dashboard-header-label">Intercom</div>
        <h2>Ring <span class="dashboard-header-accent">Intercom</span></h2>
        <p class="subtitle">Tuersprechanlage — Events, Tueroeffner, Automatisierung</p>
    </div>

    <!-- Status Card -->
    <div class="status-cards" id="statusCards">
        <div class="card" id="statusCard">
            <h3>📡 Verbindungsstatus</h3>
            <div class="card-content">
                <div class="metric">
                    <span class="label">Status</span>
                    <span class="value" id="connectionStatus">Pruefe...</span>
                </div>
                <div class="metric">
                    <span class="label">Letztes Event</span>
                    <span class="value" id="lastEvent">—</span>
                </div>
                <div class="metric">
                    <span class="label">Naechster Poll</span>
                    <span class="value" id="pollInterval">—</span>
                </div>
            </div>
        </div>

        <div class="card" id="autoOpenCard">
            <h3>🚪 Auto-Oeffnung</h3>
            <div class="card-content">
                <div class="metric">
                    <span class="label">Status</span>
                    <span class="value" id="autoOpenStatus">—</span>
                </div>
                <div class="metric">
                    <span class="label">Verzoegerung</span>
                    <span class="value" id="autoOpenDelay">—</span>
                </div>
                <div class="metric">
                    <span class="label">Zeitfenster</span>
                    <span class="value" id="autoOpenSchedule">—</span>
                </div>
            </div>
        </div>

        <div class="card" id="doorControlCard">
            <h3>🔓 Tueroeffner</h3>
            <div class="card-content" style="align-items: center; padding-top: 12px;">
                <button class="btn btn-primary" id="openDoorBtn"
                        style="font-size: 1.1rem; padding: 16px 40px;"
                        onclick="openDoor()">
                    🔓 Tuer oeffnen
                </button>
                <span id="doorResult" style="font-size: 0.85rem; color: var(--text-tertiary); margin-top: 8px;"></span>
            </div>
        </div>
    </div>

    <!-- Settings -->
    <div class="card" style="margin-bottom: 20px;">
        <h3>⚙️ Einstellungen</h3>
        <div class="card-content">
            <div style="display: flex; flex-wrap: wrap; gap: 16px; align-items: center;">
                <label style="display: flex; align-items: center; gap: 8px; cursor: pointer;">
                    <input type="checkbox" id="autoOpenToggle" onchange="toggleAutoOpen()">
                    <span class="label">Auto-Oeffnung bei Klingel</span>
                </label>
                <div style="display: flex; align-items: center; gap: 8px;">
                    <span class="label">Verzoegerung:</span>
                    <input type="number" id="delayInput" min="1" max="30" value="5"
                           style="width: 60px; padding: 6px 10px; border: 1px solid var(--border-default);
                                  border-radius: 8px; font-family: var(--font-mono); text-align: center;">
                    <span class="label">Sek.</span>
                    <button class="btn btn-secondary btn-small" onclick="saveDelay()">Speichern</button>
                </div>
                <button class="btn btn-secondary btn-small" onclick="sendTestNotification()">
                    🔔 Pushover Test
                </button>
                <button class="btn btn-secondary btn-small" onclick="reconnect()">
                    🔄 Neu verbinden
                </button>
            </div>
        </div>
    </div>

    <!-- Event History -->
    <div class="card">
        <h3>📋 Klingel-Historie</h3>
        <div class="card-content">
            <table style="width: 100%; border-collapse: collapse; font-size: 0.85rem;">
                <thead>
                    <tr style="border-bottom: 2px solid var(--border-subtle);">
                        <th style="text-align: left; padding: 8px;">Zeit</th>
                        <th style="text-align: left; padding: 8px;">Typ</th>
                        <th style="text-align: left; padding: 8px;">Beantwortet</th>
                        <th style="text-align: left; padding: 8px;">Auto-Open</th>
                        <th style="text-align: left; padding: 8px;">Dauer</th>
                    </tr>
                </thead>
                <tbody id="eventTable">
                    <tr><td colspan="5" style="padding: 16px; text-align: center; color: var(--text-tertiary);">Lade Events...</td></tr>
                </tbody>
            </table>
        </div>
    </div>
</div>

<script>
const REFRESH_INTERVAL = 10000;

async function fetchStatus() {
    try {
        const res = await fetch('/ring/api/ring/status');
        const data = await res.json();

        const statusEl = document.getElementById('connectionStatus');
        if (data.connected) {
            statusEl.textContent = 'Verbunden';
            statusEl.style.color = '#27ae60';
        } else if (data.error) {
            statusEl.textContent = data.error === 'not configured' ? 'Nicht konfiguriert' : 'Getrennt';
            statusEl.style.color = '#e17055';
        } else {
            statusEl.textContent = 'Getrennt';
            statusEl.style.color = '#e17055';
        }

        document.getElementById('pollInterval').textContent = (data.poll_interval || '—') + 's';

        if (data.last_event) {
            const d = new Date(data.last_event.timestamp);
            const diff = Math.floor((Date.now() - d.getTime()) / 60000);
            document.getElementById('lastEvent').textContent = diff < 1 ? 'Gerade eben' : `vor ${diff} Min.`;
        }

        document.getElementById('autoOpenStatus').textContent = data.auto_open_enabled ? 'Aktiv' : 'Aus';
        document.getElementById('autoOpenStatus').style.color = data.auto_open_enabled ? '#27ae60' : '#636e72';
        document.getElementById('autoOpenDelay').textContent = (data.auto_open_delay || '—') + 's';

        const schedules = data.auto_open_schedules || [];
        if (schedules.length > 0) {
            const parts = schedules.map(s => `${s.start}-${s.end} ${s.days.map(d => ['So','Mo','Di','Mi','Do','Fr','Sa'][d]).join(',')}`);
            document.getElementById('autoOpenSchedule').textContent = parts.join(' | ');
        } else {
            document.getElementById('autoOpenSchedule').textContent = 'Keine Zeiten';
        }

        document.getElementById('autoOpenToggle').checked = data.auto_open_enabled;
        document.getElementById('delayInput').value = data.auto_open_delay || 5;

    } catch (e) {
        console.error('Status fetch failed:', e);
    }
}

async function fetchEvents() {
    try {
        const res = await fetch('/ring/api/ring/events?limit=20');
        const data = await res.json();
        const tbody = document.getElementById('eventTable');

        if (!data.events || data.events.length === 0) {
            tbody.innerHTML = '<tr><td colspan="5" style="padding: 16px; text-align: center; color: var(--text-tertiary);">Keine Events</td></tr>';
            return;
        }

        tbody.innerHTML = data.events.map(e => {
            const d = new Date(e.timestamp);
            const time = d.toLocaleString('de-DE', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
            const answered = e.answered ? '<span style="color:#27ae60">Ja</span>' : '<span style="color:#b2bec3">Nein</span>';
            const auto = e.auto_opened ? '<span style="color:#00b894">Ja</span>' : '<span style="color:#b2bec3">—</span>';
            const dur = e.duration ? e.duration + 's' : '—';
            return `<tr style="border-bottom: 1px solid var(--border-subtle);">
                <td style="padding: 8px;">${time}</td>
                <td style="padding: 8px;">${e.event_type}</td>
                <td style="padding: 8px;">${answered}</td>
                <td style="padding: 8px;">${auto}</td>
                <td style="padding: 8px;">${dur}</td>
            </tr>`;
        }).join('');
    } catch (e) {
        console.error('Events fetch failed:', e);
    }
}

async function openDoor() {
    const btn = document.getElementById('openDoorBtn');
    const result = document.getElementById('doorResult');
    btn.disabled = true;
    btn.textContent = 'Oeffne...';
    result.textContent = '';

    try {
        const res = await fetch('/ring/api/ring/open', { method: 'POST' });
        const data = await res.json();
        result.textContent = data.success ? 'Tuer geoeffnet' : data.error || 'Fehler';
        result.style.color = data.success ? '#27ae60' : '#e17055';
    } catch (e) {
        result.textContent = 'Verbindungsfehler';
        result.style.color = '#e17055';
    }

    btn.disabled = false;
    btn.textContent = '🔓 Tuer oeffnen';
}

async function toggleAutoOpen() {
    const enabled = document.getElementById('autoOpenToggle').checked;
    await fetch('/ring/api/ring/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ auto_open_enabled: enabled }),
    });
    fetchStatus();
}

async function saveDelay() {
    const delay = parseInt(document.getElementById('delayInput').value) || 5;
    await fetch('/ring/api/ring/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ auto_open_delay: delay }),
    });
    fetchStatus();
}

async function sendTestNotification() {
    const res = await fetch('/ring/api/ring/test-notification', { method: 'POST' });
    const data = await res.json();
    alert(data.success ? 'Test-Nachricht gesendet!' : 'Fehler: ' + (data.error || 'Pushover nicht konfiguriert'));
}

async function reconnect() {
    const res = await fetch('/ring/api/ring/reconnect', { method: 'POST' });
    const data = await res.json();
    alert(data.success ? 'Verbindung hergestellt!' : 'Verbindung fehlgeschlagen');
    fetchStatus();
}

// Initial load + auto-refresh
fetchStatus();
fetchEvents();
setInterval(() => { fetchStatus(); fetchEvents(); }, REFRESH_INTERVAL);
</script>
{% endblock %}
```

- [ ] **Step 2: Add Ring nav link to base.html**

In `src/web/templates/base.html`, add a new nav item after the Garten link (around line 37):

```html
                <li><a href="/ring" class="{% if request.path == '/ring' %}active{% endif %}">🚪 Ring</a></li>
```

- [x] **Step 3: Verify template renders** — Done, Template OK

Run: `cd /Users/shp-art/Documents/Github/KI-SYSTEM && source venv/bin/activate && python3 -c "from jinja2 import Environment, FileSystemLoader; env = Environment(loader=FileSystemLoader('src/web/templates')); t = env.get_template('ring.html'); print('Template OK, extends base.html')"`
Expected: `Template OK, extends base.html`

- [ ] **Step 4: Commit**

```bash
git add src/web/templates/ring.html src/web/templates/base.html
git commit -m "feat: add Ring Intercom dashboard page with nav link"
```

---

### Task 8: Integration — App, Config, Gitignore

**Files:**
- Modify: `src/web/app.py` — Register blueprint
- Modify: `config/config.yaml` — Add ring + pushover sections
- Modify: `.gitignore` — Add ring_token.cache

- [ ] **Step 1: Add ring_token.cache to .gitignore**

Append to `.gitignore`:
```
# Ring token cache
data/ring_token.cache
```

- [ ] **Step 2: Add ring + pushover config to config.yaml**

Append to `config/config.yaml`:

```yaml
# Ring Intercom
ring:
  enabled: false
  email: ""
  password: ""
  poll_interval: 15
  token_cache: "data/ring_token.cache"
  auto_open:
    enabled: false
    delay: 5
    schedules: []

# Pushover Notifications
pushover:
  enabled: false
  user_key: ""
  app_key: ""
```

- [x] **Step 3: Register Ring Blueprint in app.py** — Done

At the top of `src/web/app.py`, add import (near other blueprint imports):

```python
from src.web.blueprints.api_ring import ring_bp, init_ring_blueprint
```

In the `_register_blueprints` method, add before the Christmas blueprint section:

```python
        # Ring Intercom Blueprint
        try:
            from src.background.ring_monitor import RingMonitor
            self.ring_monitor = RingMonitor.from_config(self.config, db_path=self.config.get('database', {}).get('path', 'data/ki_system.db'))
            if self.ring_monitor:
                init_ring_blueprint(self.ring_monitor, self.db, self.config)
                self.app.register_blueprint(ring_bp)
                logger.info("Ring Intercom blueprint registered")
        except Exception as e:
            logger.warning(f"Ring Intercom not available: {e}")
```

- [ ] **Step 4: Start Ring Monitor as background task**

In `src/web/app.py`, find where background processes are started (likely in a `_start_background_processes` or similar method). Add:

```python
        # Start Ring Monitor
        if hasattr(self, 'ring_monitor') and self.ring_monitor:
            self.ring_monitor.start()
            logger.info("Ring Monitor background process started")
```

If there's no centralized background start method, add it at the end of the `run()` or `start()` method of the WebApp class.

- [ ] **Step 5: Verify everything imports cleanly**

Run: `cd /Users/shp-art/Documents/Github/KI-SYSTEM && source venv/bin/activate && python3 -c "from src.web.blueprints.api_ring import ring_bp; from src.background.ring_monitor import RingMonitor; print('All imports OK')"`
Expected: `All imports OK`

- [ ] **Step 6: Commit**

```bash
git add src/web/app.py config/config.yaml .gitignore
git commit -m "feat: integrate Ring Intercom into app, config, and gitignore"
```

---

### Task 9: Deploy and Test

**Files:** None (deployment only)

- [ ] **Step 1: Push to remote**

```bash
git push
```

- [ ] **Step 2: Deploy to production**

```bash
ssh root@192.168.12.198 "cd /var/www/KI-SYSTEM && git pull && pip install -r requirements.txt && pm2 restart ki-smart-home"
```

- [x] **Step 3: Verify locally** — Done, dashboard loads with "Nicht konfiguriert" status

Run: `cd /Users/shp-art/Documents/Github/KI-SYSTEM && source venv/bin/activate && python3 main.py web --port 5001`

Open browser: `http://localhost:5001/ring`

Expected: Dashboard page loads with "Nicht konfiguriert" status (since ring.enabled=false)

- [ ] **Step 4: Configure Ring credentials** — Pending user action

Edit `config/config.yaml` on production server:
```yaml
ring:
  enabled: true
  email: "YOUR_RING_EMAIL"
  password: "YOUR_RING_PASSWORD"
pushover:
  enabled: true
  user_key: "YOUR_PUSHOVER_USER_KEY"
  app_key: "YOUR_PUSHOVER_APP_KEY"
```

Then: `ssh root@192.168.12.198 "cd /var/www/KI-SYSTEM && pm2 restart ki-smart-home"`

- [ ] **Step 5: Verify connection on production** — Pending user action

Check logs: `ssh root@192.168.12.198 "cd /var/www/KI-SYSTEM && pm2 logs ki-smart-home --lines 30"`

Expected: `Ring: Connected to intercom '...'` or `Ring: Connection failed` (if credentials wrong)

- [x] **Step 6: Final commit with deployment tag** — Done

```bash
git tag -a v0.9.0-ring -m "Ring Intercom integration"
git push origin v0.9.0-ring
```
