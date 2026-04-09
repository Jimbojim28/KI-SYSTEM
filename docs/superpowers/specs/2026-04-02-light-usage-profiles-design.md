# Design: Zeitfenster-basierte Licht-Profile fuer vergessene Lichter

**Datum:** 2026-04-02
**Status:** Approved

## Problem

Der aktuelle `ForgottenLightDetector` nutzt statische Regeln (Mindestdauer, keine Bewegung, Schlafenszeit, Tageslicht) und ein optionales ML-Modell. Er kann nicht unterscheiden zwischen:

- Ein Licht das **immer** um 19 Uhr angeht und bis 22 Uhr brennt (normal)
- Dem selben Licht das um 3 Uhr nachts an ist, oder seit 5 Stunden statt der üblichen 3 (vergessen)

## Loesung

Neue Komponente `LightProfileBuilder` die pro Geraet individuelle Nutzungsprofile aus historischen `lighting_events` lernt. Die Profile werden im `ForgottenLightDetector` vor den bestehenden Regeln geprueft.

## Architektur

### Neue Datei: `src/models/light_profile_builder.py`

**Klasse `LightProfileBuilder`**

Verantwortlichkeiten:
- Profile aus `lighting_events` berechnen (ON/OFF-Paare pro Geraet)
- Profile in DB speichern (`light_usage_profiles` Tabelle)
- Profile fuer ein Geraet/Stunde abfragen
- Auto-Rebuild alle 24h

Oeffentliche Methoden:
- `build_profiles(db)` - Berechnet alle Profile neu aus lighting_events
- `get_profile(device_id, day_group, hour) -> Optional[LightProfile]`
- `check_against_profile(device_id, on_minutes, now) -> ProfileCheckResult`
- `is_profile_ready(device_id) -> bool` - Min. 7 Tage Daten vorhanden?

**Datenklasse `LightProfile`:**
```python
device_id: str
day_group: str          # "weekday" oder "weekend"
hour_slot: int          # 0-23 (volle Stunde)
avg_duration_min: float
std_duration_min: float
frequency: int          # Wie oft in diesem Slot an
total_sessions: int
last_updated: datetime
```

**Datenklasse `ProfileCheckResult`:**
```python
is_anomaly: bool        # Abweichung vom Profil erkannt
reasons: List[str]      # Menschenlesbare Gruende
is_known_usage: bool    # True = Stunde ist ein bekannter "An"-Slot
deviation_sigma: float  # Wie viele Sigma abweichend (0 = normal)
```

### Neue DB-Tabelle: `light_usage_profiles`

```sql
CREATE TABLE IF NOT EXISTS light_usage_profiles (
    device_id TEXT NOT NULL,
    day_group TEXT NOT NULL,       -- 'weekday' oder 'weekend'
    hour_slot INTEGER NOT NULL,    -- 0-23
    avg_duration_min REAL,
    std_duration_min REAL,
    frequency INTEGER DEFAULT 0,
    total_sessions INTEGER DEFAULT 0,
    last_updated DATETIME,
    PRIMARY KEY (device_id, day_group, hour_slot)
);
```

### Aenderung: `src/decision_engine/forgotten_light_detector.py`

**Neue Methode `_check_against_profile()`:**
- Wird in `_predict_forgotten()` als **erste** Pruefung aufgerufen
- Gibt `ProfileCheckResult` zurueck
- Wenn `is_known_usage=True` und `deviation_sigma < 2` → "Normalnutzung laut Profil",_override der regelbasierten Erkennung (nicht vergessen)
- Wenn `is_anomaly=True` → zusaetzlicher Grund fuer "vergessen"

**Logik in `_predict_forgotten()`:**
1. Mindestdauer pruefen (wie bisher)
2. **NEU:** `_check_against_profile()` aufrufen
3. Wenn Profil "normal" sagt → return (False, 0, []) — nicht vergessen
4. Wenn Profil "anomal" sagt → Profil-Reasons zu regelbasierten Reasons hinzufuegen
5. Bestehende regelbasierte + ML-Logik weiter wie bisher

**Neues Attribut:**
- `self.profile_builder: Optional[LightProfileBuilder]` in `__init__`

**Aenderung `get_watched_lights()`:**
- Profil-Infos im Antwort-Dict pro Licht:
  ```python
  'profile_status': 'normal' | 'anomaly' | 'no_profile'
  'profile_info': 'Normalnutzung (Mo-Fr 18-22 Uhr, ~120 Min.)'  # oder None
  ```

### Aenderung: Web API

Neuer Endpunkt oder Erweiterung bestehender:
- `GET /api/forgotten-light/profiles` - Alle Profile abfragen
- Profil-Infos in `/api/forgotten-light/watched` Response

### Was sich NICHT aendert

- `src/background/lighting_data_collector.py` - Daten sind schon da
- `lighting_events` Tabelle - Schema unveraendert
- Bestehende Regeln bleiben als Fallback
- ML-Modell (`forgotten_light_model.py`) bleibt bestehen
- Notification-System unveraendert
- Profile bauen nur auf bestehenden `lighting_events` Daten auf

## Profil-Berechnung

1. Query: Alle ON/OFF-Paare pro Geraet aus `lighting_events` (letzte 90 Tage)
2. Berechne Dauer pro Session: (off_timestamp - on_timestamp)
3. Gruppiere nach:
   - `day_group`: Mo-Fr = "weekday", Sa-So = "weekend"
   - `hour_slot`: Stunde des Einschaltens (0-23)
4. Pro Gruppe: berechne avg_duration, std_duration, frequency
5. Min. 3 Sessions in einem Slot bevor Profil als "reif" gilt
6. Min. 7 Tage Daten fuer ein Geraet bevor Profile aktiv werden

## Erkennungslogik im Detail

### Zeitfenster-Check
- Ist die aktuelle Stunde ein bekannter "An"-Slot (frequency >= 3)?
- Nein → `reasons.append("Ungewoehnliche Uhrzeit laut Profil")`

### Dauer-Check (sigma-basiert)
- aktuelle_dauer > avg_duration + 2 * std_duration?
- Ja → `reasons.append(f"Laenger als sonst: {on_min:.0f} Min. vs ~{avg_min:.0f} Min. (Profil)")`
- `deviation_sigma = (current - avg) / max(std, 1)`

### Normal-Check (Override)
- Stunde IST ein bekannter Slot
- Dauer liegt innerhalb avg ± 2σ
- → `is_known_usage = True`, kein vergessen

### Fallback
- Kein Profil vorhanden oder nicht reif → bestehende Regeln greifen
- Weniger als 3 Sessions im Slot → Slot gilt nicht als "bekannt"

## Lernphase & Auto-Rebuild

- Min. 7 Tage `lighting_events` fuer ein Geraet
- Auto-Rebuild: taeglich um 03:00 (bestehender background-Prozess)
- Manuell triggerbar via Web UI oder API
- Profile werden komplett neu berechnet (nicht inkrementell)

## Dateiuebersicht

| Datei | Aktion |
|-------|--------|
| `src/models/light_profile_builder.py` | **Neu** - ProfileBuilder Klasse |
| `src/decision_engine/forgotten_light_detector.py` | **Aenderung** - Profil-Check in _predict_forgotten, Profil-Infos in get_watched_lights |
| `src/web/app.py` | **Aenderung** - Neuer API-Endpunkt /api/forgotten-light/profiles |
| `src/utils/database.py` | **Aenderung** - Neue Tabelle light_usage_profiles, add/get Methoden |
