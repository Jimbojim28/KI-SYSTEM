-- Migration 008: Fügt window_state zu ventilation_events und active_ventilations hinzu
-- Erstellt: 2025-12-03
-- Beschreibung: Trackt ob Fenster gekippt oder weit offen ist für bessere ML-Vorhersagen

-- Spalte für window_state in active_ventilations
ALTER TABLE active_ventilations ADD COLUMN window_state TEXT DEFAULT 'open';
-- 'tilted' = gekippt, 'open' = weit offen

-- Spalte für window_state in ventilation_events
ALTER TABLE ventilation_events ADD COLUMN window_state TEXT DEFAULT 'open';

-- Index für Abfragen nach window_state
CREATE INDEX IF NOT EXISTS idx_vent_events_window_state
ON ventilation_events(window_state, room_name);

-- View für Lüftungs-Lernstatistiken nach Fensterzustand
CREATE VIEW IF NOT EXISTS ventilation_learning_by_state AS
SELECT 
    room_name,
    window_state,
    outdoor_temp,
    COUNT(*) as sample_count,
    ROUND(AVG(duration_minutes), 1) as avg_duration,
    ROUND(AVG(temp_change), 2) as avg_temp_change,
    ROUND(AVG(humidity_change), 2) as avg_humidity_change,
    ROUND(AVG(co2_change), 0) as avg_co2_change,
    ROUND(AVG(effectiveness_score), 2) as avg_effectiveness,
    -- Gruppierte Außentemperatur-Bereiche
    CASE 
        WHEN outdoor_temp < 0 THEN 'freezing'
        WHEN outdoor_temp < 10 THEN 'cold'
        WHEN outdoor_temp < 20 THEN 'mild'
        ELSE 'warm'
    END as temp_range
FROM ventilation_events
WHERE closed_at IS NOT NULL
  AND duration_minutes > 0
  AND duration_minutes < 120
GROUP BY room_name, window_state, temp_range
ORDER BY room_name, window_state, outdoor_temp;
