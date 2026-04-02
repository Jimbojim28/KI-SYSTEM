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
