"""
LightProfileBuilder - Lernt pro-Geraet Licht-Verwendungsmuster aus lighting_events.

Erstellt Profile basierend auf:
- Geraete-ID
- Wochentag-Gruppe (weekday/weekend)
- Stunden-Slot (0-23)

Erkennt Anomalien basierend auf Sigma-Abweichung von gelernten Mustern.
"""

from dataclasses import dataclass
from datetime import datetime
from math import sqrt
from typing import List, Dict, Optional

from loguru import logger

from src.utils.database import Database


@dataclass
class LightProfile:
    """Profil fuer ein Geraet an einem bestimmten Tag/Zeit-Slot."""

    device_id: str
    day_group: str          # "weekday" or "weekend"
    hour_slot: int          # 0-23 (hour when light was turned on)
    avg_duration_min: float
    std_duration_min: float
    frequency: int
    total_sessions: int

    def is_ready(self) -> bool:
        """Profil ist bereit wenn mindestens 3 Sessions vorhanden."""
        return self.total_sessions >= 3


@dataclass
class ProfileCheckResult:
    """Ergebnis einer Profil-Pruefung."""

    is_anomaly: bool
    reasons: List[str]
    is_known_usage: bool
    deviation_sigma: float

    def is_normal(self) -> bool:
        """Nutzung ist normal wenn bekannt und keine Anomalie."""
        return self.is_known_usage and not self.is_anomaly

    @classmethod
    def no_profile(cls) -> "ProfileCheckResult":
        """Factory: Kein Profil vorhanden."""
        return cls(is_anomaly=False, reasons=[], is_known_usage=False, deviation_sigma=0.0)


class LightProfileBuilder:
    """
    Erstellt Licht-Verwendungsprofile pro Geraet und erkennt Anomalien.

    Profile werden aus lighting_events ON/OFF-Paaren berechnet und in der
    Tabelle light_usage_profiles gespeichert.
    """

    MIN_DAYS_DATA = 7
    MIN_SESSIONS_PER_SLOT = 3

    def __init__(self, db: Database):
        self.db = db
        self._ensure_table()

    def _ensure_table(self):
        """Erstellt die light_usage_profiles Tabelle falls nicht vorhanden."""
        conn = self.db._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS light_usage_profiles (
                device_id TEXT NOT NULL,
                day_group TEXT NOT NULL,
                hour_slot INTEGER NOT NULL,
                avg_duration_min REAL NOT NULL,
                std_duration_min REAL NOT NULL DEFAULT 0.0,
                frequency INTEGER NOT NULL DEFAULT 1,
                total_sessions INTEGER NOT NULL DEFAULT 1,
                last_updated DATETIME NOT NULL,
                PRIMARY KEY (device_id, day_group, hour_slot)
            )
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_light_usage_profiles_device
            ON light_usage_profiles(device_id)
        """)

        conn.commit()

    def has_enough_data(self, device_id: str) -> bool:
        """Prueft ob mindestens MIN_DAYS_DATA verschiedene Tage Daten vorliegen."""
        conn = self.db._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT COUNT(DISTINCT date(timestamp))
            FROM lighting_events
            WHERE device_id = ?
        """, (device_id,))

        row = cursor.fetchone()
        distinct_days = row[0] if row else 0
        return distinct_days >= self.MIN_DAYS_DATA

    def build_profiles(self) -> int:
        """
        Erstellt alle Profile aus lighting_events.

        Verfolgt ON/OFF-Paare pro Geraet, berechnet Session-Dauern und
        gruppiert nach (device_id, day_group, hour_slot).

        Returns:
            Anzahl der erstellten Profile.
        """
        conn = self.db._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT device_id, state, timestamp
            FROM lighting_events
            ORDER BY device_id, timestamp
        """)

        rows = cursor.fetchall()

        # Track ON/OFF pairs per device
        # Key: device_id, Value: list of (on_time, duration_min) tuples
        sessions: Dict[str, List[tuple]] = {}
        pending_on: Dict[str, datetime] = {}

        for row in rows:
            device_id = row[0]
            state = row[1].lower() if row[1] else ""
            timestamp_str = row[2]

            try:
                ts = datetime.fromisoformat(timestamp_str)
            except (ValueError, TypeError):
                continue

            if state == "on":
                pending_on[device_id] = ts
            elif state == "off" and device_id in pending_on:
                on_time = pending_on.pop(device_id)
                duration_min = (ts - on_time).total_seconds() / 60.0

                if 0 < duration_min <= 1440:
                    if device_id not in sessions:
                        sessions[device_id] = []
                    sessions[device_id].append((on_time, duration_min))

        # Group sessions by (device_id, day_group, hour_slot)
        # Key: (device_id, day_group, hour_slot), Value: list of durations
        groups: Dict[tuple, List[float]] = {}

        for device_id, device_sessions in sessions.items():
            for on_time, duration in device_sessions:
                day_group = "weekend" if on_time.weekday() >= 5 else "weekday"
                hour_slot = on_time.hour
                key = (device_id, day_group, hour_slot)

                if key not in groups:
                    groups[key] = []
                groups[key].append(duration)

        # Build and save profiles for groups with enough sessions
        profiles_built = 0
        now = datetime.now()

        for (device_id, day_group, hour_slot), durations in groups.items():
            if len(durations) < self.MIN_SESSIONS_PER_SLOT:
                continue

            avg = sum(durations) / len(durations)

            # Population standard deviation
            if len(durations) > 1:
                variance = sum((d - avg) ** 2 for d in durations) / len(durations)
                std = sqrt(variance)
            else:
                std = 0.0

            cursor.execute("""
                INSERT OR REPLACE INTO light_usage_profiles
                (device_id, day_group, hour_slot, avg_duration_min,
                 std_duration_min, frequency, total_sessions, last_updated)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                device_id,
                day_group,
                hour_slot,
                avg,
                std,
                len(durations),
                len(durations),
                now,
            ))

            profiles_built += 1

        conn.commit()
        logger.info(f"Built {profiles_built} light usage profiles from {len(rows)} events")

        return profiles_built

    def get_profile(self, device_id: str, day_group: str,
                    hour_slot: int) -> Optional[LightProfile]:
        """Holt ein einzelnes Profil fuer device/day_group/hour_slot."""
        conn = self.db._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT device_id, day_group, hour_slot,
                   avg_duration_min, std_duration_min,
                   frequency, total_sessions
            FROM light_usage_profiles
            WHERE device_id = ? AND day_group = ? AND hour_slot = ?
        """, (device_id, day_group, hour_slot))

        row = cursor.fetchone()
        if not row:
            return None

        return LightProfile(
            device_id=row[0],
            day_group=row[1],
            hour_slot=row[2],
            avg_duration_min=row[3],
            std_duration_min=row[4],
            frequency=row[5],
            total_sessions=row[6],
        )

    def check_against_profile(self, device_id: str, on_minutes: float,
                              now: datetime) -> ProfileCheckResult:
        """
        Prueft eine aktuelle Licht-Nutzung gegen das gelernte Profil.

        Args:
            device_id: Geraete-ID
            on_minutes: Aktuelle Einschaltdauer in Minuten
            now: Aktueller Zeitpunkt

        Returns:
            ProfileCheckResult mit Anomalie-Status und Gruenden.
        """
        if not self.has_enough_data(device_id):
            return ProfileCheckResult.no_profile()

        day_group = "weekend" if now.weekday() >= 5 else "weekday"
        hour_slot = now.hour

        profile = self.get_profile(device_id, day_group, hour_slot)

        if profile is None or not profile.is_ready():
            # Check if device has ANY ready profiles
            conn = self.db._get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT COUNT(*) FROM light_usage_profiles
                WHERE device_id = ? AND total_sessions >= ?
            """, (device_id, self.MIN_SESSIONS_PER_SLOT))
            row = cursor.fetchone()
            has_any_profiles = row[0] > 0 if row else False

            if has_any_profiles:
                return ProfileCheckResult(
                    is_anomaly=True,
                    reasons=[f"Ungewoehnliche Uhrzeit laut Profil ({hour_slot}:00)"],
                    is_known_usage=False,
                    deviation_sigma=0.0,
                )
            else:
                return ProfileCheckResult.no_profile()

        # Compute sigma deviation
        deviation_sigma = abs(on_minutes - profile.avg_duration_min) / max(profile.std_duration_min, 1.0)

        reasons = []
        is_anomaly = False

        if deviation_sigma > 2.0:
            is_anomaly = True
            reasons.append(
                f"Laenger als sonst: {on_minutes:.0f} Min. vs ~{profile.avg_duration_min:.0f} Min. (Profil)"
            )

        return ProfileCheckResult(
            is_anomaly=is_anomaly,
            reasons=reasons,
            is_known_usage=True,
            deviation_sigma=deviation_sigma,
        )

    def get_all_profiles(self, device_id: str = None) -> List[Dict]:
        """Holt alle Profile, optional gefiltert nach device_id."""
        conn = self.db._get_connection()
        cursor = conn.cursor()

        if device_id:
            cursor.execute("""
                SELECT device_id, day_group, hour_slot,
                       avg_duration_min, std_duration_min,
                       frequency, total_sessions, last_updated
                FROM light_usage_profiles
                WHERE device_id = ?
                ORDER BY device_id, day_group, hour_slot
            """, (device_id,))
        else:
            cursor.execute("""
                SELECT device_id, day_group, hour_slot,
                       avg_duration_min, std_duration_min,
                       frequency, total_sessions, last_updated
                FROM light_usage_profiles
                ORDER BY device_id, day_group, hour_slot
            """)

        results = []
        for row in cursor.fetchall():
            results.append({
                "device_id": row[0],
                "day_group": row[1],
                "hour_slot": row[2],
                "avg_duration_min": row[3],
                "std_duration_min": row[4],
                "frequency": row[5],
                "total_sessions": row[6],
                "last_updated": row[7],
            })

        return results
