"""
Tests fuer LightProfileBuilder
"""

import pytest
from datetime import datetime, timedelta

from src.models.light_profile_builder import (
    LightProfile,
    ProfileCheckResult,
    LightProfileBuilder,
)


# ============================================================
# Dataclass Tests
# ============================================================


def test_light_profile_creation():
    """Test: LightProfile Dataclass kann erstellt werden."""
    profile = LightProfile(
        device_id="light-1",
        day_group="weekday",
        hour_slot=19,
        avg_duration_min=120.0,
        std_duration_min=30.0,
        frequency=5,
        total_sessions=5,
    )
    assert profile.device_id == "light-1"
    assert profile.day_group == "weekday"
    assert profile.hour_slot == 19
    assert profile.avg_duration_min == 120.0
    assert profile.std_duration_min == 30.0
    assert profile.frequency == 5
    assert profile.total_sessions == 5


def test_is_ready_enough_sessions():
    """Test: is_ready() = True bei 3 Sessions."""
    profile = LightProfile(
        device_id="light-1",
        day_group="weekday",
        hour_slot=19,
        avg_duration_min=60.0,
        std_duration_min=10.0,
        frequency=3,
        total_sessions=3,
    )
    assert profile.is_ready() is True


def test_is_ready_too_few():
    """Test: is_ready() = False bei 2 Sessions."""
    profile = LightProfile(
        device_id="light-1",
        day_group="weekday",
        hour_slot=19,
        avg_duration_min=60.0,
        std_duration_min=10.0,
        frequency=2,
        total_sessions=2,
    )
    assert profile.is_ready() is False


def test_profile_check_result_normal():
    """Test: is_normal() True wenn known_usage und keine Anomalie."""
    result = ProfileCheckResult(
        is_anomaly=False,
        reasons=[],
        is_known_usage=True,
        deviation_sigma=0.5,
    )
    assert result.is_normal() is True
    assert result.is_anomaly is False
    assert result.is_known_usage is True


def test_profile_check_result_anomaly():
    """Test: is_normal() False bei Anomalie."""
    result = ProfileCheckResult(
        is_anomaly=True,
        reasons=["Zu lange"],
        is_known_usage=True,
        deviation_sigma=3.0,
    )
    assert result.is_normal() is False
    assert result.is_anomaly is True


def test_profile_check_result_no_profile():
    """Test: no_profile() Factory-Methode."""
    result = ProfileCheckResult.no_profile()
    assert result.is_anomaly is False
    assert result.reasons == []
    assert result.is_known_usage is False
    assert result.deviation_sigma == 0.0
    assert result.is_normal() is False


# ============================================================
# Helper: Direkte SQL-Inserts fuer kontrollierte Testdaten
# ============================================================

def _insert_event(conn, device_id, device_name, room_name, state,
                  hour_of_day, day_of_week, is_weekend, timestamp_str,
                  brightness=100, outdoor_light=50.0):
    """Hilfsfunktion: Fuegt lighting_event direkt via SQL ein."""
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO lighting_events
        (timestamp, device_id, device_name, room_name, state, brightness,
         hour_of_day, day_of_week, is_weekend, outdoor_light, presence, motion_detected)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (timestamp_str, device_id, device_name, room_name, state, brightness,
          hour_of_day, day_of_week, is_weekend, outdoor_light, 1, 1))
    conn.commit()


# ============================================================
# LightProfileBuilder Tests
# ============================================================


def test_has_enough_data_false(test_db):
    """Test: has_enough_data() False fuer nicht existentes Geraet."""
    builder = LightProfileBuilder(test_db)
    assert builder.has_enough_data("nonexistent-device") is False


def test_has_enough_data_true(test_db):
    """Test: has_enough_data() True mit 8 Tagen Daten."""
    conn = test_db._get_connection()
    base_date = datetime(2026, 1, 1, 19, 0, 0)

    # Insert events on 8 different days
    for i in range(8):
        day = base_date + timedelta(days=i)
        _insert_event(
            conn, "light-test", "Test Light", "Wohnzimmer", "on",
            hour_of_day=19, day_of_week=day.weekday(),
            is_weekend=day.weekday() >= 5,
            timestamp_str=day.isoformat(),
        )

    builder = LightProfileBuilder(test_db)
    assert builder.has_enough_data("light-test") is True


def test_build_profiles_creates_rows(test_db):
    """Test: build_profiles() erstellt korrekte Profile."""
    conn = test_db._get_connection()
    device_id = "light-build"
    device_name = "Build Light"
    room_name = "Wohnzimmer"

    # Insert 5 weekday ON/OFF sessions at hour 19, each 120 min
    # Jan 5 2026 = Monday, go Mon-Fri (5 weekdays)
    weekday_dates = [datetime(2026, 1, 5, 19, 0, 0) + timedelta(days=i) for i in range(5)]

    for day in weekday_dates:
        on_time = day
        off_time = day + timedelta(minutes=120)

        _insert_event(
            conn, device_id, device_name, room_name, "on",
            hour_of_day=19, day_of_week=day.weekday(),
            is_weekend=day.weekday() >= 5,
            timestamp_str=on_time.isoformat(),
        )
        _insert_event(
            conn, device_id, device_name, room_name, "off",
            hour_of_day=21, day_of_week=day.weekday(),
            is_weekend=day.weekday() >= 5,
            timestamp_str=off_time.isoformat(),
        )

    builder = LightProfileBuilder(test_db)
    count = builder.build_profiles()

    assert count == 1

    profile = builder.get_profile(device_id, "weekday", 19)
    assert profile is not None
    assert profile.device_id == device_id
    assert profile.day_group == "weekday"
    assert profile.hour_slot == 19
    assert profile.total_sessions == 5
    assert profile.avg_duration_min == 120.0
    assert profile.std_duration_min == 0.0  # All durations are identical


def test_check_normal_usage(test_db):
    """Test: Normale Nutzung wird erkannt (keine Anomalie)."""
    conn = test_db._get_connection()
    device_id = "light-normal"
    device_name = "Normal Light"
    room_name = "Wohnzimmer"

    # Need 8+ distinct days for has_enough_data, all weekdays for weekday profile
    weekday_dates = [
        datetime(2026, 1, 5),   # Mon
        datetime(2026, 1, 6),   # Tue
        datetime(2026, 1, 7),   # Wed
        datetime(2026, 1, 8),   # Thu
        datetime(2026, 1, 9),   # Fri
        datetime(2026, 1, 12),  # Mon
        datetime(2026, 1, 13),  # Tue
        datetime(2026, 1, 14),  # Wed
    ]

    # Build profile with ~60min average and some variance (std ~12.2)
    durations = [50, 55, 60, 65, 70, 52, 62, 68]
    for i, day in enumerate(weekday_dates):
        on_time = day.replace(hour=19)
        off_time = on_time + timedelta(minutes=durations[i])

        _insert_event(
            conn, device_id, device_name, room_name, "on",
            hour_of_day=19, day_of_week=day.weekday(),
            is_weekend=day.weekday() >= 5,
            timestamp_str=on_time.isoformat(),
        )
        _insert_event(
            conn, device_id, device_name, room_name, "off",
            hour_of_day=20, day_of_week=day.weekday(),
            is_weekend=day.weekday() >= 5,
            timestamp_str=off_time.isoformat(),
        )

    builder = LightProfileBuilder(test_db)
    builder.build_profiles()

    # Check at weekday 19:00 with 55 min (well within 2 sigma of ~60 avg)
    check_time = datetime(2026, 1, 15, 19, 30, 0)  # Thursday
    result = builder.check_against_profile(device_id, 55.0, check_time)

    assert result.is_known_usage is True
    assert result.is_anomaly is False
    assert result.is_normal() is True


def test_check_unusual_time(test_db):
    """Test: Nutzung zu ungewoehnlicher Zeit wird als Anomalie erkannt."""
    conn = test_db._get_connection()
    device_id = "light-time"
    device_name = "Time Light"
    room_name = "Wohnzimmer"

    # Need 8+ distinct days for has_enough_data
    weekday_dates = [
        datetime(2026, 1, 5),
        datetime(2026, 1, 6),
        datetime(2026, 1, 7),
        datetime(2026, 1, 8),
        datetime(2026, 1, 9),
        datetime(2026, 1, 12),
        datetime(2026, 1, 13),
        datetime(2026, 1, 14),
    ]

    # Build profile ONLY for hour 19 (weekday)
    for day in weekday_dates:
        on_time = day.replace(hour=19)
        off_time = on_time + timedelta(minutes=60)

        _insert_event(
            conn, device_id, device_name, room_name, "on",
            hour_of_day=19, day_of_week=day.weekday(),
            is_weekend=day.weekday() >= 5,
            timestamp_str=on_time.isoformat(),
        )
        _insert_event(
            conn, device_id, device_name, room_name, "off",
            hour_of_day=20, day_of_week=day.weekday(),
            is_weekend=day.weekday() >= 5,
            timestamp_str=off_time.isoformat(),
        )

    builder = LightProfileBuilder(test_db)
    builder.build_profiles()

    # Check at weekday 03:00 (no profile for this slot)
    check_time = datetime(2026, 1, 15, 3, 0, 0)  # Thursday at 3 AM
    result = builder.check_against_profile(device_id, 30.0, check_time)

    assert result.is_anomaly is True
    assert len(result.reasons) > 0
    assert "Ungewoehnliche Uhrzeit" in result.reasons[0]


def test_check_duration_exceeded(test_db):
    """Test: Ueberdurchschnittlich lange Nutzung wird als Anomalie erkannt."""
    conn = test_db._get_connection()
    device_id = "light-dur"
    device_name = "Duration Light"
    room_name = "Wohnzimmer"

    # Need 8+ distinct days for has_enough_data
    weekday_dates = [
        datetime(2026, 1, 5),
        datetime(2026, 1, 6),
        datetime(2026, 1, 7),
        datetime(2026, 1, 8),
        datetime(2026, 1, 9),
        datetime(2026, 1, 12),
        datetime(2026, 1, 13),
        datetime(2026, 1, 14),
    ]

    # Build profile with ~120min average, with some variance
    durations = [100, 110, 120, 130, 140, 115, 125, 135]
    for i, day in enumerate(weekday_dates):
        on_time = day.replace(hour=19)
        off_time = on_time + timedelta(minutes=durations[i])

        _insert_event(
            conn, device_id, device_name, room_name, "on",
            hour_of_day=19, day_of_week=day.weekday(),
            is_weekend=day.weekday() >= 5,
            timestamp_str=on_time.isoformat(),
        )
        _insert_event(
            conn, device_id, device_name, room_name, "off",
            hour_of_day=20, day_of_week=day.weekday(),
            is_weekend=day.weekday() >= 5,
            timestamp_str=off_time.isoformat(),
        )

    builder = LightProfileBuilder(test_db)
    builder.build_profiles()

    # Check with 300 min → should be well beyond 2 sigma
    check_time = datetime(2026, 1, 15, 19, 0, 0)  # Thursday
    result = builder.check_against_profile(device_id, 300.0, check_time)

    assert result.is_anomaly is True
    assert result.deviation_sigma > 2.0
    assert any("Laenger als sonst" in r for r in result.reasons)


def test_check_no_profile_returns_no_profile(test_db):
    """Test: Nicht existentes Geraet liefert no_profile()."""
    builder = LightProfileBuilder(test_db)
    result = builder.check_against_profile(
        "nonexistent-device", 60.0, datetime(2026, 1, 13, 19, 0, 0)
    )
    assert result.is_anomaly is False
    assert result.is_known_usage is False
    assert result.deviation_sigma == 0.0
