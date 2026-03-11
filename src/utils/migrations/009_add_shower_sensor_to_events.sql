-- Migration 009: Duschsensor-Daten zu bathroom_events hinzufügen
-- Erstellt: 2026-03-11
-- Beschreibung: Speichert Duschsensor-Feuchtigkeit beim Event-Start und die Erkennungsquelle
--               für bessere Analytics und ML-Training

-- Neue Spalten zu bathroom_events hinzufügen
ALTER TABLE bathroom_events ADD COLUMN shower_start_humidity REAL;
ALTER TABLE bathroom_events ADD COLUMN detected_by_shower_sensor BOOLEAN DEFAULT 0;

-- Index für Abfragen nach Erkennungsquelle
CREATE INDEX IF NOT EXISTS idx_bathroom_events_detection
ON bathroom_events(detected_by_shower_sensor, start_time);
