-- Ensure ring_event_id is unique for real event IDs (NULL/empty allowed)
-- 1) Deduplicate existing rows by keeping the newest row per ring_event_id
DELETE FROM ring_events
WHERE ring_event_id IS NOT NULL
  AND ring_event_id != ''
  AND id NOT IN (
    SELECT MAX(id)
    FROM ring_events
    WHERE ring_event_id IS NOT NULL
      AND ring_event_id != ''
    GROUP BY ring_event_id
  );

-- 2) Enforce uniqueness for future inserts
CREATE UNIQUE INDEX IF NOT EXISTS idx_ring_events_ring_id_unique
ON ring_events(ring_event_id)
WHERE ring_event_id IS NOT NULL AND ring_event_id != '';
