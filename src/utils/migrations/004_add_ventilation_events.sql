-- Migration 004: Lüftungs-Events für ML-Training und Statistiken
-- Erstellt: 2025-11-30
-- Beschreibung: Trackt vollständige Lüftungszyklen (Fenster öffnen bis schließen) mit Klimadaten

-- Haupttabelle für Lüftungs-Events (komplette Lüftungszyklen)
CREATE TABLE IF NOT EXISTS ventilation_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    
    -- Fenster-Identifikation
    device_id TEXT NOT NULL,
    device_name TEXT,
    room_name TEXT,
    
    -- Zeitstempel
    opened_at DATETIME NOT NULL,
    closed_at DATETIME,  -- NULL wenn noch offen
    duration_minutes INTEGER,  -- Berechnet beim Schließen
    
    -- Klimadaten beim Öffnen
    temp_start REAL,           -- Raumtemperatur beim Öffnen
    humidity_start REAL,       -- Luftfeuchtigkeit beim Öffnen
    co2_start INTEGER,         -- CO2 beim Öffnen (ppm)
    
    -- Klimadaten beim Schließen
    temp_end REAL,             -- Raumtemperatur beim Schließen
    humidity_end REAL,         -- Luftfeuchtigkeit beim Schließen
    co2_end INTEGER,           -- CO2 beim Schließen (ppm)
    
    -- Änderungen (berechnet)
    temp_change REAL,          -- temp_end - temp_start
    humidity_change REAL,      -- humidity_end - humidity_start
    co2_change INTEGER,        -- co2_end - co2_start
    
    -- Außenbedingungen
    outdoor_temp REAL,         -- Außentemperatur während Lüftung
    outdoor_humidity REAL,     -- Außen-Luftfeuchtigkeit
    
    -- ML-relevante Metadaten
    season TEXT,               -- 'winter', 'spring', 'summer', 'autumn'
    time_of_day TEXT,          -- 'morning', 'afternoon', 'evening', 'night'
    weekday INTEGER,           -- 0=Mo, 6=So
    
    -- Bewertung (für ML-Training)
    effectiveness_score REAL,  -- Wie effektiv war die Lüftung? (0-1)
    was_optimal BOOLEAN,       -- War die Lüftungsdauer optimal?
    
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Indizes für Performance
CREATE INDEX IF NOT EXISTS idx_vent_events_room
ON ventilation_events(room_name, opened_at);

CREATE INDEX IF NOT EXISTS idx_vent_events_device
ON ventilation_events(device_id, opened_at);

CREATE INDEX IF NOT EXISTS idx_vent_events_time
ON ventilation_events(opened_at);

CREATE INDEX IF NOT EXISTS idx_vent_events_outdoor_temp
ON ventilation_events(outdoor_temp, duration_minutes);

CREATE INDEX IF NOT EXISTS idx_vent_events_season
ON ventilation_events(season, time_of_day);

-- Tabelle für aktive Lüftungen (offene Fenster)
CREATE TABLE IF NOT EXISTS active_ventilations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id TEXT UNIQUE NOT NULL,
    device_name TEXT,
    room_name TEXT,
    opened_at DATETIME NOT NULL,
    temp_start REAL,
    humidity_start REAL,
    co2_start INTEGER,
    outdoor_temp REAL,
    outdoor_humidity REAL,
    last_check DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_active_vent_device
ON active_ventilations(device_id);

-- View für Lüftungsstatistiken pro Raum
CREATE VIEW IF NOT EXISTS v_room_ventilation_stats AS
SELECT
    room_name,
    COUNT(*) as total_events,
    ROUND(AVG(duration_minutes), 1) as avg_duration_min,
    ROUND(AVG(temp_change), 2) as avg_temp_change,
    ROUND(AVG(humidity_change), 2) as avg_humidity_change,
    ROUND(AVG(co2_change), 0) as avg_co2_change,
    ROUND(AVG(outdoor_temp), 1) as avg_outdoor_temp,
    COUNT(CASE WHEN temp_change < -2 THEN 1 END) as strong_cooling_count,
    COUNT(CASE WHEN co2_change < -200 THEN 1 END) as effective_co2_reduction_count
FROM ventilation_events
WHERE closed_at IS NOT NULL
GROUP BY room_name;

-- View für ML-Training Daten
CREATE VIEW IF NOT EXISTS v_ventilation_ml_training AS
SELECT
    room_name,
    outdoor_temp,
    duration_minutes,
    temp_start,
    temp_change,
    co2_start,
    co2_change,
    humidity_start,
    humidity_change,
    season,
    time_of_day,
    weekday,
    effectiveness_score,
    was_optimal
FROM ventilation_events
WHERE closed_at IS NOT NULL
  AND duration_minutes IS NOT NULL
  AND duration_minutes > 0
  AND outdoor_temp IS NOT NULL;

