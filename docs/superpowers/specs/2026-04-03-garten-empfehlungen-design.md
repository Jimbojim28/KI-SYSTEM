# Design: Tomaten-Pflanz-Empfehlung & Rasen-Temperatur-Verbesserung

**Datum**: 2026-04-03
**Status**: Draft
**Dateien**: `src/web/templates/garten.html`

## Zusammenfassung

Zwei Verbesserungen am Garten-Bereich:
1. **Neu**: Tomaten-Pflanz-Empfehlung fuer Hochbeet (Eisheilige, Nachttemp, Bodentemp)
2. **Verbesserung**: Rasen-Empfehlungen nutzen kuenftig kombinierte Temperaturbewertung (aktuell + Durchschnitt + Trend)

## 1. Tomaten-Pflanz-Empfehlung (Hochbeet)

### Kriterien

Tomaten duerfen ins Hochbeet gepflanzt werden wenn **alle drei** Bedingungen erfuellt sind:

1. **Eisheilige vorbei**: Datum >= 16. Mai. Die Eisheiligen (11.-15. Mai: Mamertus, Pankratius, Servatius, Bonifatius, Sophie) markieren traditionell das Ende der Frostgefahr in Mitteleuropa.
2. **Nachttemperatur-Durchschnitt > 10 Grad C**: Aus dem Weather-Forecast die naechtlichen Tiefstwerte der naechsten 5 Tage berechnen. Der Durchschnitt daraus muss > 10 Grad C liegen.
3. **Bodentemperatur >= 12 Grad C**: Aus dem Hochbeet-Sensor (falls konfiguriert). Fallback: 5-Tage-Durchschnitt-Aussentemperatur >= 12 Grad C.

### Status-Stufen

| Status | Farbe | Bedeutung |
|--------|-------|-----------|
| Gruen | `green` | Alle Kriterien erfuellt - pflanzen! |
| Orange | `orange` | Fast bereit, einzelne Kriterien fehlen noch |
| Rot | `red` | Noch zu frueh / Frostgefahr |
| Grau | `gray` | Ausserhalb der Saison (vor April / nach Juli) |

### Detail-Empfehlungen

Je Kriterium eine Unterkarte:

- **Eisheilige**: "Noch X Tage bis nach den Eisheiligen (15. Mai)" oder "Eisheilige vorbei - kein Frostrisiko mehr"
- **Nachttemperatur**: "Naechte zu kalt (Durchschnitt X Grad C) - brauche > 10 Grad C" oder "Naechte warm genug"
- **Bodentemperatur**: "Boden zu kalt (X Grad C) - brauche >= 12 Grad C" oder "Boden warm genug"
- **Zusatz-Tipps** (immer sichtbar im Pflanzzeitraum Apr-Jun):
  - Abhaerten: Pflanzen 1-2 Wochen vorher schrittweise an Aussentemperaturen gewoehnen
  - Standort: Sonnig, windgeschuetzt
  - Boden: Kompost einarbeiten vor dem Pflanzen

### Datenquellen

- **Bodentemperatur**: Bestehende `SENSORS.hochbeet1_temp` / `SENSORS.hochbeet2_temp` (Hochbeet-Sensoren)
- **Nachttemperatur**: Neuer Abruf der 5-Tage-Forecast-Daten via bestehendem `/api/status` Weather-Daten, gefiltert auf Nacht-Tiefstwerte
- **Eisheilige**: Festes Datum (11.-15. Mai), kein API-Call noetig

### UI-Platzierung

Neuer Abschnitt `Tomaten-Pflanz-Empfehlung` zwischen den Hochbeet-Karten und dem Rasen-Bereich im Status-Tab. Gleicher Karten-Style wie die Rasen-Pflegeempfehlungen (Grid mit farbigen Karten).

Aufbau:
```
[Haupstatus-Karte: Pflanzen ja/nein mit Icon]
[Eisheilige-Karte] [Nachttemp-Karte] [Bodentemp-Karte]
[Tipp-Karten: Abhaerten, Standort, Bodenvorbereitung]
```

### Nachttemperatur-Berechnung

Aus dem Weather-Forecast (bereits in `_rasenWeatherCache` verfuegbar):
1. Forecast-Eintraege der naechsten 5 Tage laden
2. Pro Tag den Tiefstwert identifizieren (meist nachts)
3. Durchschnitt dieser 5 Tiefstwerte = Nachttemp-Durchschnitt
4. Falls weniger als 3 Tage Forecast verfuegbar: Fallback auf 5-Tage-Durchschnitt-Aussentemp

## 2. Rasen-Empfehlungen - Verbesserte Temperaturnutzung

### Problem

Aktuell nutzt `_rasenEmpfehlungen()` Temperaturdaten inkonsistent:
- Verschiedene Checks nutzen mal `soilTemp`, mal `avgTemp`, mal `outdoor`
- Kein Temperatur-Trend (steigend/fallend)
- Hitze-Erkennung nur auf aktueller Temperatur, nicht auf Trend

### Loesung: Effektive Temperatur + Trend

**Neue Metriken** (zu Beginn von `_rasenEmpfehlungen()` berechnet):

1. **`effTemp`**: Gewichtetes Mittel
   - Wenn Bodentemperatur UND 5-Tage-Durchschnitt verfuegbar: `0.6 * soilTemp + 0.4 * avgTemp`
   - Nur Bodentemperatur: `soilTemp`
   - Nur Durchschnitt: `avgTemp`
   - Keins: Fallback auf Monats-Schaetzung

2. **`trend`**: Aus `avgTempDailyList` (bereits im Cache)
   - Letzte 3 Tage Durchschnitt vs. erste 2 Tage Durchschnitt
   - Differenz > 1 Grad C = `rising`
   - Differenz < -1 Grad C = `falling`
   - Dazwischen = `stable`
   - Fallback wenn weniger als 5 Tage Daten: `null`

3. **`trendIcon`**: `↗️` / `↘️` / `→` / ``

### Anpassung der 6 Kategorien

Alle Kategorien nutzen kuenftig `effTemp` als primaren Entscheidungswert:

| Kategorie | Aenderung |
|-----------|-----------|
| **Giessen** | `heatWave` prueft `outdoor > 28 \|\| (effTemp > 26 && trend === 'rising')` |
| **Maehen** | Wachstum prueft `effTemp >= 10` statt Mix aus soilTemp/avgTemp; Trend-Hinweis im Text |
| **Lueften** | Unveraendert (monatsbasiert) |
| **Vertikutieren** | `effTemp >= 12` statt soilWarmEnough; Trend-Info im Text |
| **Dueengen** | `effTemp >= 12` als Schwelle; Trend-Info im Text |
| **Nachsaeen** | `effTemp >= 10` als Schwelle; Trend-Hinweis "steigend = gutes Zeitfenster" |

### Info-Zeile

Die Zeile unter den Empfehlungskarten zeigt kuenftig:
```
Empfehlungen fuer April — Boden: X Grad C | Ø 5T: Y Grad C | Effektiv: Z Grad C | Trend: ↗️ steigend
```

## Technische Umsetzung

### Betroffene Datei

- `src/web/templates/garten.html` (einzige Datei)

### Aenderungen

1. **Neue Funktion `_tomatenEmpfehlungen(soilTemp, weather)`**: Berechnet Tomaten-Pflanz-Status und liefert Array von Empfehlungs-Items
2. **Neue Funktion `renderTomatenEmpfehlungen(soilTemp)`**: Rendert die Karten ins DOM
3. **Neuer HTML-Abschnitt**: Zwischen Hochbeet- und Rasen-Bereich im Status-Tab
4. **Erweitert `_rasenEmpfehlungen()`**: Berechnet `effTemp`, `trend`, `trendIcon` zu Beginn; alle Kategorien nutzen diese Werte einheitlich
5. **Erweiterte Info-Zeile**: Zeigt effTemp und Trend
6. **`refreshAll()` erweitert**: Ruft auch `renderTomatenEmpfehlungen()` auf
7. **Nachttemperatur aus Forecast**: Extrahiere Nacht-Tiefstwerte aus bestehendem Weather-Daten (via `/api/status`)

### Nachttemperatur-Datenquelle

Die Wetterdaten aus `/api/status` enthalten Forecast-Eintraege mit Temperaturen. Daraus werden:
- Pro Vorhersage-Eintrag der minimale Temperaturwert als Nachttemperatur genommen
- Aus den naechsten 5 Tagen der Durchschnitt dieser Minima berechnet

Falls der Forecast keine expliziten Min-Temperaturen liefert: Fallback auf die berechneten Tagesdurchschnittstemperaturen abzueglich 5 Grad C (Nachtabschlag-Schaetzung).

### Keine neuen API-Endpoints

Alle Daten sind bereits im Frontend verfuegbar oder werden ueber bestehende Endpoints geladen (`/api/status`, `/api/garten/avg-temp`).
