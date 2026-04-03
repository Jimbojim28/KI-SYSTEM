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


@ring_bp.route('')
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
