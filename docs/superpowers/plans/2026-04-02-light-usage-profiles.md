# Licht-Usage-Profile Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve forgotten light detection by learning per-device usage patterns (time windows + typical duration with σ-based anomaly detection) so normal usage is not flagged as "forgotten."

**Architecture:** New `LightProfileBuilder` class reads existing `lighting_events` from SQLite, computes per-device time/duration profiles stored in a new `light_usage_profiles` table. The `ForgottenLightDetector` checks against these profiles before falling back to rule-based detection.

**Tech Stack:** Python 3.8+, SQLite, existing `lighting_events` data, no new dependencies

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `src/utils/migrations/010_add_light_usage_profiles.sql` | Create | DB migration for new table |
| `src/models/light_profile_builder.py` | Create | Profile computation, storage, and lookup |
| `src/decision_engine/forgotten_light_detector.py` | Modify | Integrate profile check into detection loop |
| `src/web/app.py` | Modify | New API endpoint for profiles |
| `tests/test_light_profile_builder.py` | Create | Unit tests for profile builder |

---

### Task 1: Database Migration

**Files:**
- Create: `src/utils/migrations/010_add_light_usage_profiles.sql`

- [ ] **Step 1: Write the migration SQL**

```sql
-- Licht-Nutzungsprofile fuer vergessene-Lichter-Erkennung
-- Speichert pro Geraet + Wochentagsgruppe + Stunde typische Dauer und Haeufigkeit

CREATE TABLE IF NOT EXISTS light_usage_profiles (
    device_id TEXT NOT NULL,
    day_group TEXT NOT NULL,
    hour_slot INTEGER NOT NULL,
    avg_duration_min REAL NOT NULL DEFAULT 0,
    std_duration_min REAL NOT NULL DEFAULT 0,
    frequency INTEGER NOT NULL DEFAULT 0,
    total_sessions INTEGER NOT NULL DEFAULT 0,
    last_updated DATETIME,
    PRIMARY KEY (device_id, day_group, hour_slot)
);

CREATE INDEX IF NOT EXISTS idx_light_profiles_device
    ON light_usage_profiles(device_id);
```

- [ ] **Step 2: Verify migration runs**

Run: `cd /Users/shp-art/Documents/Github/KI-SYSTEM && python3 -c "from src.utils.database import Database; db = Database(); print('Migration applied successfully')"`

Expected: No error, table created.

- [ ] **Step 3: Commit**

```bash
git add src/utils/migrations/010_add_light_usage_profiles.sql
git commit -m "feat: add light_usage_profiles table migration"
```

---

### Task 2: LightProfileBuilder Core

**Files:**
- Create: `src/models/light_profile_builder.py`
- Test: `tests/test_light_profile_builder.py`

- [ ] **Step 1: Write failing tests for data classes and core methods**

```python
"""Tests fuer LightProfileBuilder"""
import pytest
from datetime import datetime, timedelta
from src.models.light_profile_builder import (
    LightProfile, ProfileCheckResult, LightProfileBuilder
)


class TestLightProfile:
    def test_creation(self):
        p = LightProfile(
            device_id="light-1",
            day_group="weekday",
            hour_slot=19,
            avg_duration_min=120.0,
            std_duration_min=30.0,
            frequency=15,
            total_sessions=15,
        )
        assert p.device_id == "light-1"
        assert p.day_group == "weekday"
        assert p.avg_duration_min == 120.0

    def test_is_ready_enough_sessions(self):
        p = LightProfile(
            device_id="light-1", day_group="weekday", hour_slot=19,
            avg_duration_min=120.0, std_duration_min=30.0,
            frequency=3, total_sessions=3,
        )
        assert p.is_ready() is True

    def test_is_ready_too_few_sessions(self):
        p = LightProfile(
            device_id="light-1", day_group="weekday", hour_slot=19,
            avg_duration_min=120.0, std_duration_min=30.0,
            frequency=2, total_sessions=2,
        )
        assert p.is_ready() is False


class TestProfileCheckResult:
    def test_normal_usage(self):
        r = ProfileCheckResult(
            is_anomaly=False, reasons=[], is_known_usage=True, deviation_sigma=0.5
        )
        assert r.is_normal() is True

    def test_anomaly_time(self):
        r = ProfileCheckResult(
            is_anomaly=True,
            reasons=["Ungewoehnliche Uhrzeit laut Profil"],
            is_known_usage=False,
            deviation_sigma=0.0,
        )
        assert r.is_normal() is False

    def test_no_profile(self):
        r = ProfileCheckResult.no_profile()
        assert r.is_anomaly is False
        assert r.is_known_usage is False
        assert r.reasons == []


class TestLightProfileBuilder:
    def test_has_enough_data_false(self, test_db):
        builder = LightProfileBuilder(test_db)
        assert builder.has_enough_data("nonexistent-device") is False

    def test_has_enough_data_true(self, test_db):
        # Insert 8 days of on/off events for a device
        now = datetime.now()
        for day_offset in range(8):
            on_time = now - timedelta(days=day_offset, hours=4)
            off_time = on_time + timedelta(hours=2)
            day_label_on = on_time.strftime("%Y-%m-%d %H:%M:%S")
            day_label_off = off_time.strftime("%Y-%m-%d %H:%M:%S")
            weekday = on_time.weekday()
            is_weekend = 1 if weekday >= 5 else 0
            test_db.add_lighting_event(
                "light-1", "Test Light", "Wohnzimmer", "on",
                hour_of_day=on_time.hour, day_of_week=weekday,
                is_weekend=is_weekend,
            )
            test_db.add_lighting_event(
                "light-1", "Test Light", "Wohnzimmer", "off",
                hour_of_day=off_time.hour, day_of_week=weekday,
                is_weekend=is_weekend,
            )
        builder = LightProfileBuilder(test_db)
        assert builder.has_enough_data("light-1") is True

    def test_build_profiles_creates_rows(self, test_db):
        # Insert sessions: 5 weekday sessions at hour 19, duration ~120 min
        base = datetime(2026, 3, 24, 19, 0)  # Tuesday
        for i in range(5):
            on_time = base + timedelta(days=i)
            off_time = on_time + timedelta(minutes=120 + i * 10)
            weekday = on_time.weekday()
            is_weekend = 1 if weekday >= 5 else 0
            test_db.add_lighting_event(
                "light-1", "Test Light", "Wohnzimmer", "on",
                hour_of_day=on_time.hour, day_of_week=weekday,
                is_weekend=is_weekend,
            )
            test_db.add_lighting_event(
                "light-1", "Test Light", "Wohnzimmer", "off",
                hour_of_day=off_time.hour, day_of_week=weekday,
                is_weekend=is_weekend,
            )
        builder = LightProfileBuilder(test_db)
        count = builder.build_profiles()
        assert count > 0

        profile = builder.get_profile("light-1", "weekday", 19)
        assert profile is not None
        assert profile.avg_duration_min > 100
        assert profile.frequency == 5

    def test_check_against_profile_normal(self, test_db):
        # Build profile with 5 sessions at hour 19, ~120 min
        base = datetime(2026, 3, 24, 19, 0)
        for i in range(5):
            on_time = base + timedelta(days=i)
            off_time = on_time + timedelta(minutes=120)
            weekday = on_time.weekday()
            is_weekend = 1 if weekday >= 5 else 0
            test_db.add_lighting_event(
                "light-1", "Test Light", "Wohnzimmer", "on",
                hour_of_day=on_time.hour, day_of_week=weekday,
                is_weekend=is_weekend,
            )
            test_db.add_lighting_event(
                "light-1", "Test Light", "Wohnzimmer", "off",
                hour_of_day=off_time.hour, day_of_week=weekday,
                is_weekend=is_weekend,
            )
        builder = LightProfileBuilder(test_db)
        builder.build_profiles()

        # Check at hour 19, 30 min on → normal (known time, well within duration)
        now = datetime(2026, 4, 1, 19, 30)  # Wednesday
        result = builder.check_against_profile("light-1", on_minutes=30, now=now)
        assert result.is_known_usage is True
        assert result.is_anomaly is False

    def test_check_against_profile_unusual_time(self, test_db):
        # Build profile only for hour 19
        base = datetime(2026, 3, 24, 19, 0)
        for i in range(5):
            on_time = base + timedelta(days=i)
            off_time = on_time + timedelta(minutes=120)
            weekday = on_time.weekday()
            is_weekend = 1 if weekday >= 5 else 0
            test_db.add_lighting_event(
                "light-1", "Test Light", "Wohnzimmer", "on",
                hour_of_day=on_time.hour, day_of_week=weekday,
                is_weekend=is_weekend,
            )
            test_db.add_lighting_event(
                "light-1", "Test Light", "Wohnzimmer", "off",
                hour_of_day=off_time.hour, day_of_week=weekday,
                is_weekend=is_weekend,
            )
        builder = LightProfileBuilder(test_db)
        builder.build_profiles()

        # Check at hour 3 (no profile) → unusual time
        now = datetime(2026, 4, 1, 3, 0)  # Wednesday 3am
        result = builder.check_against_profile("light-1", on_minutes=60, now=now)
        assert result.is_known_usage is False
        assert result.is_anomaly is True
        assert len(result.reasons) > 0

    def test_check_against_profile_duration_exceeded(self, test_db):
        # Build profile with consistent ~120 min duration
        base = datetime(2026, 3, 24, 19, 0)
        for i in range(5):
            on_time = base + timedelta(days=i)
            off_time = on_time + timedelta(minutes=120)
            weekday = on_time.weekday()
            is_weekend = 1 if weekday >= 5 else 0
            test_db.add_lighting_event(
                "light-1", "Test Light", "Wohnzimmer", "on",
                hour_of_day=on_time.hour, day_of_week=weekday,
                is_weekend=is_weekend,
            )
            test_db.add_lighting_event(
                "light-1", "Test Light", "Wohnzimmer", "off",
                hour_of_day=off_time.hour, day_of_week=weekday,
                is_weekend=is_weekend,
            )
        builder = LightProfileBuilder(test_db)
        builder.build_profiles()

        # Check at hour 19, but 300 min on → well over avg + 2σ
        now = datetime(2026, 4, 1, 19, 0)  # Wednesday
        result = builder.check_against_profile("light-1", on_minutes=300, now=now)
        assert result.is_anomaly is True
        assert result.deviation_sigma > 2.0
        assert any("Laenger" in r for r in result.reasons)

    def test_check_no_profile_returns_no_profile(self, test_db):
        builder = LightProfileBuilder(test_db)
        result = builder.check_against_profile("nonexistent", on_minutes=60, now=datetime.now())
        assert result == ProfileCheckResult.no_profile()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/shp-art/Documents/Github/KI-SYSTEM && python3 -m pytest tests/test_light_profile_builder.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'src.models.light_profile_builder'`

- [ ] **Step 3: Implement LightProfileBuilder**

Create `src/models/light_profile_builder.py`:

```python
"""
LightProfileBuilder - Lernt zeitliche Nutzungsprofile pro Licht-Geraet

Analysiert lighting_events und berechnet:
- Typische Zeitfenster (Wann ist ein Licht normalerweise an?)
- Typische Dauer mit μ ± σ (Wie lange normal?)
- Getrennt nach Werktag/Wochenende

Wird vom ForgottenLightDetector genutzt um "normalen" Betrieb
von "vergessen" zu unterscheiden.
"""

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from loguru import logger


@dataclass
class LightProfile:
    """Nutzungsprofil fuer ein Geraet in einem bestimmten Zeitfenster."""
    device_id: str
    day_group: str          # "weekday" oder "weekend"
    hour_slot: int          # 0-23 (Stunde des Einschaltens)
    avg_duration_min: float
    std_duration_min: float
    frequency: int          # Wie oft in diesem Slot an
    total_sessions: int

    def is_ready(self) -> bool:
        """Profil ist nutzbar ab 3 Sessions."""
        return self.total_sessions >= 3


@dataclass
class ProfileCheckResult:
    """Ergebnis der Profil-Pruefung fuer eine aktuell brennende Lampe."""
    is_anomaly: bool        # Abweichung vom Profil erkannt
    reasons: List[str]      # Menschenlesbare Gruende
    is_known_usage: bool    # Stunde ist ein bekannter "An"-Slot
    deviation_sigma: float  # Sigma-Abweichung bei Dauer

    def is_normal(self) -> bool:
        """True wenn die Nutzung als 'normal' gilt laut Profil."""
        return self.is_known_usage and not self.is_anomaly

    @classmethod
    def no_profile(cls) -> "ProfileCheckResult":
        """Kein Profil verfuegbar → Fallback zu regelbasierter Erkennung."""
        return cls(
            is_anomaly=False,
            reasons=[],
            is_known_usage=False,
            deviation_sigma=0.0,
        )


class LightProfileBuilder:
    """
    Berechnet und speichert Licht-Nutzungsprofile.

    Profile werden aus lighting_events (ON/OFF-Paare) berechnet und
    in der Tabelle light_usage_profiles gespeichert.

    Mindestanforderungen fuer aktive Profile:
    - 7 Tage Daten fuer ein Geraet
    - 3+ Sessions in einem Zeitfenster
    """

    MIN_DAYS_DATA = 7
    MIN_SESSIONS_PER_SLOT = 3

    def __init__(self, db):
        self.db = db
        self._ensure_table()

    def _ensure_table(self):
        """Stellt sicher, dass die Tabelle existiert."""
        conn = self.db._get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS light_usage_profiles (
                device_id TEXT NOT NULL,
                day_group TEXT NOT NULL,
                hour_slot INTEGER NOT NULL,
                avg_duration_min REAL NOT NULL DEFAULT 0,
                std_duration_min REAL NOT NULL DEFAULT 0,
                frequency INTEGER NOT NULL DEFAULT 0,
                total_sessions INTEGER NOT NULL DEFAULT 0,
                last_updated DATETIME,
                PRIMARY KEY (device_id, day_group, hour_slot)
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_light_profiles_device
                ON light_usage_profiles(device_id)
        """)
        conn.commit()

    def has_enough_data(self, device_id: str) -> bool:
        """Prueft ob mindestens 7 Tage Daten fuer ein Geraet vorliegen."""
        conn = self.db._get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT COUNT(DISTINCT date(timestamp)) as distinct_days
            FROM lighting_events
            WHERE device_id = ?
        """, (device_id,))
        row = cursor.fetchone()
        days = row[0] if row else 0
        return days >= self.MIN_DAYS_DATA

    def build_profiles(self) -> int:
        """
        Berechnet alle Profile neu aus lighting_events.

        Returns:
            Anzahl der erstellten Profil-Eintraege
        """
        conn = self.db._get_connection()
        cursor = conn.cursor()

        # Alle ON/OFF-Paare holen, gruppiert nach device_id
        cursor.execute("""
            SELECT device_id, timestamp, state, hour_of_day, day_of_week, is_weekend
            FROM lighting_events
            ORDER BY device_id, timestamp
        """)
        rows = cursor.fetchall()

        # Sessions pro (device_id, day_group, hour_slot) sammeln
        sessions: Dict[Tuple[str, str, int], List[float]] = {}
        current_on: Dict[str, datetime] = {}

        for row in rows:
            device_id = row[0]
            timestamp_str = row[1]
            state = row[2]
            hour_of_day = row[3]
            is_weekend = row[5]

            try:
                ts = datetime.fromisoformat(timestamp_str)
            except (ValueError, TypeError):
                continue

            if state == "on":
                current_on[device_id] = ts
            elif state == "off" and device_id in current_on:
                on_time = current_on.pop(device_id)
                duration_min = (ts - on_time).total_seconds() / 60

                # Negative oder unrealistische Dauern filtern
                if duration_min <= 0 or duration_min > 1440:
                    continue

                day_group = "weekend" if is_weekend else "weekday"
                hour_slot = on_time.hour
                key = (device_id, day_group, hour_slot)

                if key not in sessions:
                    sessions[key] = []
                sessions[key].append(duration_min)

        # Profile berechnen und speichern
        now = datetime.now().isoformat()
        count = 0
        for (device_id, day_group, hour_slot), durations in sessions.items():
            if len(durations) < self.MIN_SESSIONS_PER_SLOT:
                continue

            avg = sum(durations) / len(durations)
            variance = sum((d - avg) ** 2 for d in durations) / len(durations)
            std = math.sqrt(variance)

            cursor.execute("""
                INSERT OR REPLACE INTO light_usage_profiles
                (device_id, day_group, hour_slot, avg_duration_min,
                 std_duration_min, frequency, total_sessions, last_updated)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                device_id, day_group, hour_slot,
                round(avg, 1), round(std, 1),
                len(durations), len(durations), now
            ))
            count += 1

        conn.commit()
        logger.info(f"Built {count} light usage profiles from {len(rows)} events")
        return count

    def get_profile(self, device_id: str, day_group: str, hour_slot: int) -> Optional[LightProfile]:
        """Holt das Profil fuer ein Geraet/Tag-Gruppe/Stunde."""
        conn = self.db._get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT avg_duration_min, std_duration_min, frequency, total_sessions
            FROM light_usage_profiles
            WHERE device_id = ? AND day_group = ? AND hour_slot = ?
        """, (device_id, day_group, hour_slot))
        row = cursor.fetchone()
        if not row:
            return None
        return LightProfile(
            device_id=device_id,
            day_group=day_group,
            hour_slot=hour_slot,
            avg_duration_min=row[0],
            std_duration_min=row[1],
            frequency=row[2],
            total_sessions=row[3],
        )

    def check_against_profile(self, device_id: str, on_minutes: float,
                               now: datetime) -> ProfileCheckResult:
        """
        Prueft ob die aktuelle Nutzung zum gelernten Profil passt.

        Logik:
        1. Keine ausreichenden Daten → no_profile Fallback
        2. Stunde kein bekannter Slot → "Ungewoehnliche Uhrzeit"
        3. Dauer > avg + 2σ → "Laenger als sonst"
        4. Stunde bekannt UND Dauer im Rahmen → "Normalnutzung"
        """
        if not self.has_enough_data(device_id):
            return ProfileCheckResult.no_profile()

        day_group = "weekend" if now.weekday() >= 5 else "weekday"
        hour_slot = now.hour

        profile = self.get_profile(device_id, day_group, hour_slot)

        # Stunde ist kein bekannter Slot
        if profile is None or not profile.is_ready():
            # Pruefe ob es ueberhaupt irgendwelche Profile fuer dieses Geraet gibt
            conn = self.db._get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT COUNT(*) FROM light_usage_profiles
                WHERE device_id = ? AND total_sessions >= ?
            """, (device_id, self.MIN_SESSIONS_PER_SLOT))
            has_any = cursor.fetchone()[0] > 0

            if has_any:
                return ProfileCheckResult(
                    is_anomaly=True,
                    reasons=[f"Ungewoehnliche Uhrzeit laut Profil ({now.hour}:00)"],
                    is_known_usage=False,
                    deviation_sigma=0.0,
                )
            return ProfileCheckResult.no_profile()

        # Dauer-Check: sigma-basiert
        sigma = profile.std_duration_min if profile.std_duration_min > 0 else 1.0
        deviation = (on_minutes - profile.avg_duration_min) / sigma

        reasons = []
        is_anomaly = False

        if deviation > 2.0:
            is_anomaly = True
            reasons.append(
                f"Laenger als sonst: {on_minutes:.0f} Min. vs ~{profile.avg_duration_min:.0f} Min. (Profil)"
            )

        return ProfileCheckResult(
            is_anomaly=is_anomaly,
            reasons=reasons,
            is_known_usage=True,
            deviation_sigma=round(deviation, 2),
        )

    def get_all_profiles(self, device_id: str = None) -> List[Dict]:
        """Holt alle Profile, optional gefiltert nach device_id."""
        conn = self.db._get_connection()
        cursor = conn.cursor()
        if device_id:
            cursor.execute("""
                SELECT device_id, day_group, hour_slot, avg_duration_min,
                       std_duration_min, frequency, total_sessions, last_updated
                FROM light_usage_profiles
                WHERE device_id = ?
                ORDER BY day_group, hour_slot
            """, (device_id,))
        else:
            cursor.execute("""
                SELECT device_id, day_group, hour_slot, avg_duration_min,
                       std_duration_min, frequency, total_sessions, last_updated
                FROM light_usage_profiles
                ORDER BY device_id, day_group, hour_slot
            """)
        results = []
        for row in cursor.fetchall():
            results.append({
                'device_id': row[0],
                'day_group': row[1],
                'hour_slot': row[2],
                'avg_duration_min': row[3],
                'std_duration_min': row[4],
                'frequency': row[5],
                'total_sessions': row[6],
                'last_updated': row[7],
            })
        return results
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/shp-art/Documents/Github/KI-SYSTEM && python3 -m pytest tests/test_light_profile_builder.py -v`

Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/models/light_profile_builder.py tests/test_light_profile_builder.py
git commit -m "feat: add LightProfileBuilder with sigma-based anomaly detection"
```

---

### Task 3: Integrate Profile Check into ForgottenLightDetector

**Files:**
- Modify: `src/decision_engine/forgotten_light_detector.py`

- [ ] **Step 1: Add import and init profile builder**

In `forgotten_light_detector.py`, add import near top (after existing imports):

```python
from src.models.light_profile_builder import LightProfileBuilder, ProfileCheckResult
```

In `__init__`, after `self._init_ml_model()` (around line 110), add:

```python
        # Nutzungsprofile
        self.profile_builder: Optional[LightProfileBuilder] = None
        self._init_profile_builder()
```

Add new method after `_init_ml_model`:

```python
    def _init_profile_builder(self):
        """Initialisiert den ProfileBuilder fuer zeitliche Nutzungsprofile"""
        try:
            self.profile_builder = LightProfileBuilder(self.db)
            logger.info("LightProfileBuilder initialized for forgotten light detection")
        except Exception as e:
            logger.warning(f"Could not initialize LightProfileBuilder: {e}")
            self.profile_builder = None
```

- [ ] **Step 2: Add profile check method**

Add new method `_check_against_profile` before `_predict_forgotten`:

```python
    def _check_against_profile(self, device_id: str, on_minutes: float,
                                now: datetime) -> "ProfileCheckResult":
        """Prueft aktuelle Nutzung gegen gelerntes Profil."""
        if not self.profile_builder:
            from src.models.light_profile_builder import ProfileCheckResult
            return ProfileCheckResult.no_profile()
        return self.profile_builder.check_against_profile(device_id, on_minutes, now)
```

- [ ] **Step 3: Integrate into _predict_forgotten**

Modify `_predict_forgotten` method. Insert profile check **after** the minimum duration check (after line `if on_minutes < self.min_on_duration_minutes: return False, 0.0, []`) and **before** the rule-based check:

Replace the section from `# ML-Vorhersage wenn Modell verfügbar` onwards with:

```python
        # Profil-Check: Hat das Geraet ein gelerntes Nutzungsprofil?
        profile_result = self._check_against_profile(device_id, on_minutes, now)

        # Wenn Profil "normal" sagt → nicht vergessen (override regelbasiert)
        if profile_result.is_normal():
            logger.debug(f"Profile says normal for {device_name}: known_usage={profile_result.is_known_usage}, sigma={profile_result.deviation_sigma}")
            return False, 0.0, []

        # Regelbasierte Pruefung (immer ausfuehren)
        rule_reasons = self._check_forgotten_reasons(
            device_id=device_id,
            device_name=device_name,
            room_name=room_name,
            on_minutes=on_minutes,
            presence_home=presence_home,
            outdoor_light=outdoor_light,
            now=now
        )
        rule_confidence = self._calculate_confidence(rule_reasons) if rule_reasons else 0.0

        # Profil-Anomalie-Gruende hinzufuegen
        profile_reasons = profile_result.reasons if profile_result.is_anomaly else []

        if self.ml_model and self.ml_model.is_trained:
            conditions = {
                'hour_of_day': now.hour,
                'day_of_week': now.weekday(),
                'is_weekend': 1 if now.weekday() >= 5 else 0,
                'on_duration_minutes': on_minutes,
                'minutes_since_motion': minutes_since_motion,
                'presence_home': 1 if presence_home else 0,
                'outdoor_light': outdoor_light or 50,
                'room_name': room_name
            }

            ml_forgotten, ml_confidence = self.ml_model.predict(conditions)

            # ML-Modell bestätigt: kombiniere mit Regelgründen
            if ml_forgotten and ml_confidence >= 0.5:
                reasons = ["🤖 ML-Vorhersage"] + profile_reasons + rule_reasons
                combined_confidence = min(1.0, ml_confidence * 0.6 + rule_confidence * 0.4)
                return True, combined_confidence, reasons

            # Profil-Anomalie + regelbasiert
            if profile_reasons and rule_confidence >= 0.3:
                reasons = profile_reasons + rule_reasons
                return True, max(rule_confidence, 0.5), reasons

            # Regelbasiert übernehmen wenn ML unsicher aber Regeln eindeutig
            if rule_confidence >= 0.5:
                return True, rule_confidence, profile_reasons + rule_reasons

            return False, 0.0, []

        # Kein ML-Modell: profilbasiert + regelbasiert
        all_reasons = profile_reasons + rule_reasons
        if all_reasons:
            combined = max(rule_confidence, 0.5 if profile_reasons else 0.0)
            return True, min(combined, 1.0), all_reasons

        return False, 0.0, []
```

- [ ] **Step 4: Add profile info to get_watched_lights**

In `get_watched_lights()`, inside the `if state:` block, after `is_forgotten` check and before `watched.append(...)`, add:

```python
                    # Profil-Status ermitteln
                    profile_status = 'no_profile'
                    profile_info = None
                    if self.profile_builder:
                        presult = self._check_against_profile(device_id, on_minutes, now)
                        if presult.is_normal():
                            profile_status = 'normal'
                            profile_info = f"Normalnutzung laut Profil"
                        elif presult.is_anomaly:
                            profile_status = 'anomaly'
                            profile_info = '; '.join(presult.reasons)
```

Then in the `watched.append({...})` dict, add these two fields:

```python
                        'profile_status': profile_status,
                        'profile_info': profile_info,
```

- [ ] **Step 5: Verify with quick test**

Run: `cd /Users/shp-art/Documents/Github/KI-SYSTEM && ./quick_test.sh`

Expected: All existing tests still pass (profile check gracefully returns `no_profile` when no data).

- [ ] **Step 6: Commit**

```bash
git add src/decision_engine/forgotten_light_detector.py
git commit -m "feat: integrate profile-based detection into ForgottenLightDetector"
```

---

### Task 4: API Endpoint for Profiles

**Files:**
- Modify: `src/web/app.py`

- [ ] **Step 1: Add profile API endpoints**

In `src/web/app.py`, after the existing `@self.app.route('/api/lighting/forgotten/debug')` block (around line 1500), add:

```python
        @self.app.route('/api/lighting/forgotten/profiles')
        def api_lighting_forgotten_profiles():
            """API: Gelernte Nutzungsprofile fuer Lampen"""
            try:
                from src.models.light_profile_builder import LightProfileBuilder
                builder = LightProfileBuilder(db=Database() if not hasattr(self, 'db') else self.db)

                device_id = request.args.get('device_id')
                profiles = builder.get_all_profiles(device_id=device_id)

                return jsonify({
                    'profiles': profiles,
                    'count': len(profiles)
                })
            except Exception as e:
                logger.error(f"Error getting light profiles: {e}")
                return jsonify({'error': str(e)}), 500

        @self.app.route('/api/lighting/forgotten/profiles/rebuild', methods=['POST'])
        def api_lighting_forgotten_profiles_rebuild():
            """API: Profile neu berechnen"""
            try:
                from src.models.light_profile_builder import LightProfileBuilder
                builder = LightProfileBuilder(db=Database() if not hasattr(self, 'db') else self.db)
                count = builder.build_profiles()
                return jsonify({'success': True, 'profiles_built': count})
            except Exception as e:
                logger.error(f"Error rebuilding light profiles: {e}")
                return jsonify({'error': str(e)}), 500
```

- [ ] **Step 2: Verify the endpoints exist**

Run: `cd /Users/shp-art/Documents/Github/KI-SYSTEM && python3 -c "from src.web.app import WebApp; print('Import OK')"`

Expected: No import errors.

- [ ] **Step 3: Commit**

```bash
git add src/web/app.py
git commit -m "feat: add API endpoints for light usage profiles"
```

---

### Task 5: Run Full Verification

**Files:** None (verification only)

- [ ] **Step 1: Run quick test**

Run: `cd /Users/shp-art/Documents/Github/KI-SYSTEM && ./quick_test.sh`

Expected: All checks pass.

- [ ] **Step 2: Run new tests**

Run: `cd /Users/shp-art/Documents/Github/KI-SYSTEM && python3 -m pytest tests/test_light_profile_builder.py -v`

Expected: All 8 tests pass.

- [ ] **Step 3: Run existing tests to verify no regressions**

Run: `cd /Users/shp-art/Documents/Github/KI-SYSTEM && python3 -m pytest tests/ -v`

Expected: All tests pass (existing + new).

---

### Task 6: Auto-Rebuild Integration

**Files:**
- Modify: `src/decision_engine/forgotten_light_detector.py`

- [ ] **Step 1: Add daily profile rebuild to detection loop**

In `_detection_loop`, add profile rebuild once per day. Add at the start of `__init__` attributes (near the stats dict):

```python
        self._last_profile_rebuild: Optional[datetime] = None
```

In `_detection_loop`, after `self._load_rooms_config()`, add:

```python
                # Profile einmal taeglich neu berechnen (nach 3 Uhr)
                if self.profile_builder:
                    now_check = datetime.now()
                    if (self._last_profile_rebuild is None or
                        (now_check - self._last_profile_rebuild).total_seconds() > 86400):
                        try:
                            count = self.profile_builder.build_profiles()
                            self._last_profile_rebuild = now_check
                            if count > 0:
                                logger.info(f"Rebuilt {count} light usage profiles (daily)")
                        except Exception as e:
                            logger.warning(f"Could not rebuild light profiles: {e}")
```

- [ ] **Step 2: Verify**

Run: `cd /Users/shp-art/Documents/Github/KI-SYSTEM && ./quick_test.sh`

Expected: All checks pass.

- [ ] **Step 3: Final commit**

```bash
git add src/decision_engine/forgotten_light_detector.py
git commit -m "feat: daily auto-rebuild of light usage profiles"
```
