"""Ring Intercom Flask Blueprint — API endpoints and dashboard page."""
from flask import Blueprint, jsonify, request, render_template
from loguru import logger

ring_bp = Blueprint('ring', __name__, url_prefix='/ring')

_ring_monitor = None
_db = None
_config = None


def init_ring_blueprint(ring_monitor, db, config):
    """Initialize blueprint with Ring Monitor and Database references."""
    global _ring_monitor, _db, _config
    _ring_monitor = ring_monitor
    _db = db
    _config = config


@ring_bp.route('/')
def ring_dashboard():
    """Render Ring Intercom dashboard page."""
    return render_template('ring.html')


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
        return jsonify({
            "auto_open_enabled": False,
            "auto_open_delay": 5,
            "auto_open_schedules": [],
            "poll_interval": 15,
        })

    return jsonify({
        "auto_open_enabled": _ring_monitor.auto_open_enabled,
        "auto_open_delay": _ring_monitor.auto_open_delay,
        "auto_open_schedules": _ring_monitor.auto_open_schedules,
        "poll_interval": _ring_monitor.poll_interval,
    })


@ring_bp.route('/api/ring/settings', methods=['POST'])
def update_settings():
    """POST /ring/api/ring/settings — Update auto-open settings."""
    data = request.get_json()
    if _ring_monitor:
        _ring_monitor.update_settings(
            auto_open_enabled=data.get("auto_open_enabled"),
            auto_open_delay=data.get("auto_open_delay"),
            auto_open_schedules=data.get("auto_open_schedules"),
        )
    # Persist to config file
    _save_to_config(data)
    return jsonify({"success": True})


def _save_to_config(data):
    """Persist schedule settings to config.yaml so they survive restarts."""
    try:
        import yaml
        config_path = _config.get("config_path", "config/config.yaml") if _config else "config/config.yaml"
        with open(config_path, 'r') as f:
            cfg = yaml.safe_load(f) or {}
        if "ring" not in cfg:
            cfg["ring"] = {}
        if "auto_open" not in cfg["ring"]:
            cfg["ring"]["auto_open"] = {}
        if data.get("auto_open_schedules") is not None:
            cfg["ring"]["auto_open"]["schedules"] = data["auto_open_schedules"]
        if data.get("auto_open_enabled") is not None:
            cfg["ring"]["auto_open"]["enabled"] = data["auto_open_enabled"]
        if data.get("auto_open_delay") is not None:
            cfg["ring"]["auto_open"]["delay"] = data["auto_open_delay"]
        with open(config_path, 'w') as f:
            yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True)
        logger.info("Ring: Schedules saved to config")
    except Exception as e:
        logger.error(f"Ring: Failed to save config: {e}")


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
