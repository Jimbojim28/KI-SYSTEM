# Datenbank-Optimierung: Ungenutzte Tabellen und Daten

## Analyse-Ergebnis

### Tabellen mit Daten (werden verwendet):
- ✅ `sensor_data`: 48.448 Einträge - wird aktiv genutzt
- ✅ `external_data`: 1.609 Einträge - wird aktiv genutzt
- ✅ `continuous_measurements`: 17.995 Einträge - ML-Training
- ✅ `bathroom_continuous_measurements`: 1.562 Einträge - wird aktiv genutzt
- ✅ `ventilation_events`: 23 Einträge - wird aktiv genutzt
- ✅ `ventilation_recommendations`: 88 Einträge - wird aktiv genutzt
- ✅ `humidity_alerts`: 17 Einträge - wird aktiv genutzt
- ✅ `active_ventilations`: 4 Einträge - wird aktiv genutzt

### Tabellen OHNE Daten (Code vorhanden, aber nie verwendet):
- ⚠️ `decisions`: 0 Einträge - **Code vorhanden** (`insert_decision` wird aufgerufen), aber keine Daten
  - **Ursache**: Möglicherweise werden Entscheidungen nicht gespeichert oder Code-Pfad wird nicht erreicht
- ⚠️ `automation_triggers`: 0 Einträge - **Code vorhanden** (INSERT/SELECT in app.py), aber keine Daten
  - **Ursache**: Automationen werden möglicherweise nicht ausgelöst oder nicht protokolliert
- ⚠️ `heating_insights`: 0 Einträge - **Code vorhanden** (`get_latest_heating_insights` wird aufgerufen), aber `save_heating_insight` wird **NIE** aufgerufen
  - **Ursache**: Insights werden nie gespeichert, nur gelesen (Fehler im Code?)
- ⚠️ `heating_schedules`: 0 Einträge - **Code vorhanden** (`save_heating_schedule` wird aufgerufen in heating_optimizer.py), aber keine Daten
  - **Ursache**: Möglicherweise wird Bedingung für Schedule-Speicherung nie erfüllt
- ⚠️ `heating_room_learning`: 0 Einträge - **Code vorhanden** (`save_room_learning_parameter` wird aufgerufen), aber keine Daten
  - **Ursache**: Möglicherweise werden keine Parameter gelernt oder Bedingung nie erfüllt
- ⚠️ `shower_predictions`: 0 Einträge - **Code vorhanden** (`get_shower_predictions_today` wird aufgerufen), aber keine INSERT-Methode gefunden
  - **Ursache**: Vorhersagen werden möglicherweise nie erstellt
- ❌ `forgotten_light_predictions`: 0 Einträge - **Tabelle existiert, aber KEINE Methoden gefunden**
  - **Ursache**: Tabelle wurde erstellt, aber nie implementiert/genutzt

## Potentielle Dopplungen

### `sensor_data` vs `continuous_measurements`
- **`sensor_data`**: Generische Sensor-Daten (alle Sensortypen)
- **`continuous_measurements`**: Spezifisch für ML-Training (Temperatur)
- **Status**: Beide werden verwendet, aber `sensor_data` könnte reduziert werden wenn nur Temperatur-Daten relevant sind

## Empfehlungen

### 1. Code-Fehler beheben (Priorität 1):
- **`heating_insights`**: `save_heating_insight` wird nie aufgerufen - prüfen warum
- **`forgotten_light_predictions`**: Keine INSERT/GET Methoden vorhanden - implementieren oder entfernen

### 2. Ungenutzte Tabellen entfernen (nur wenn sicher):
```sql
-- Nur wenn sicher dass nicht benötigt:
DROP TABLE IF EXISTS forgotten_light_predictions;  -- Keine Methoden vorhanden
```

### 3. Code prüfen und aktivieren:
- Prüfen warum `decisions`, `automation_triggers`, `heating_schedules`, `heating_room_learning`, `shower_predictions` leer sind
- Möglicherweise fehlen Bedingungen oder Code-Pfade werden nicht erreicht

### 2. `sensor_data` optimieren:
- Prüfen ob alle Sensortypen in `sensor_data` benötigt werden
- Falls nur Temperatur relevant: Daten nach `continuous_measurements` migrieren und `sensor_data` reduzieren

### 3. Alte Daten bereinigen:
```sql
-- Alte sensor_data löschen (älter als 1 Jahr)
DELETE FROM sensor_data WHERE timestamp < datetime('now', '-1 year');

-- Alte external_data löschen (älter als 1 Jahr)
DELETE FROM external_data WHERE timestamp < datetime('now', '-1 year');
```

### 4. Indizes prüfen:
- Sicherstellen dass alle häufig abgefragten Tabellen Indizes haben
- Ungenutzte Indizes entfernen

## Geschätzter Speicherplatz-Gewinn

- Leere Tabellen entfernen: ~50-100 KB (Tabellen-Struktur)
- Alte Daten bereinigen: ~10-20 MB (je nach Datenmenge)
- `sensor_data` optimieren: ~5-10 MB (falls reduziert)

## Vorgehen

1. **Backup erstellen**:
   ```bash
   cp data/ki_system.db data/ki_system.db.backup
   ```

2. **Leere Tabellen entfernen** (nur wenn sicher dass nicht benötigt):
   ```sql
   -- Prüfen ob Code diese Tabellen verwendet
   -- Dann: DROP TABLE ...
   ```

3. **Alte Daten bereinigen**:
   ```python
   # In database_maintenance.py
   db.cleanup_old_data(days=365)
   ```

4. **VACUUM ausführen**:
   ```sql
   VACUUM;
   ```

## Warnung

⚠️ **WICHTIG**: Vor dem Löschen von Tabellen prüfen:
- Wird die Tabelle im Code verwendet?
- Ist sie für zukünftige Features geplant?
- Gibt es Migrationen die diese Tabellen erwarten?

