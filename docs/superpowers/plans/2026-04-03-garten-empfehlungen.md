# Tomaten-Pflanz-Empfehlung & Rasen-Temperatur-Verbesserung

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add tomato planting recommendations to the Hochbeet section and improve Rasen recommendations with combined temperature logic.

**Architecture:** All changes in `src/web/templates/garten.html` (frontend JS) + one small backend change in `src/data_collector/weather_collector.py` to extend forecast from 24h to 5 days for night temperature calculation.

**Tech Stack:** JavaScript (inline in Jinja2 template), Chart.js, Flask backend, OpenWeatherMap 5-day forecast API

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `src/data_collector/weather_collector.py:78-80` | Modify | Extend forecast from 8 to 40 entries (5 days) |
| `src/web/templates/garten.html:59-129` | Modify | Add tomato recommendation HTML section between Hochbeet and Rasen |
| `src/web/templates/garten.html:382-1173` | Modify | Add JS functions `_tomatenEmpfehlungen`, `renderTomatenEmpfehlungen`, extend `_rasenEmpfehlungen`, extend `refreshAll` |

---

### Task 1: Extend Weather Forecast to 5 Days

**Files:**
- Modify: `src/data_collector/weather_collector.py:78-80`

Currently the forecast only returns `data['list'][:8]` (24h). OpenWeatherMap's `/data/2.5/forecast` returns 40 entries (5 days x 8 entries/day). We need all 40 for night temperature calculation.

- [ ] **Step 1: Change forecast slice limit**

In `src/data_collector/weather_collector.py`, line 80:

Change:
```python
for item in data['list'][:8]:  # 8 * 3h = 24h
```

To:
```python
for item in data['list'][:40]:  # 40 * 3h = 5 Tage
```

- [ ] **Step 2: Verify**

Run: `python3 -c "from src.data_collector.weather_collector import WeatherCollector; print('import ok')"`
Expected: `import ok`

- [ ] **Step 3: Commit**

```bash
git add src/data_collector/weather_collector.py
git commit -m "feat: extend weather forecast from 24h to 5 days for garden recommendations"
```

---

### Task 2: Add Tomaten-Empfehlung HTML Section

**Files:**
- Modify: `src/web/templates/garten.html` — insert after line 129 (closing `</div>` of Hochbeet grid), before line 131 (`<h3>` Rasen)

- [ ] **Step 1: Insert tomato recommendation HTML block**

Insert between the `</div>` that closes the Hochbeet grid (line 129) and the `<h3 style="margin-bottom: 15px;">🌾 Rasen</h3>` (line 131):

```html
    <!-- Tomaten-Pflanz-Empfehlung -->
    <h3 style="margin-top: 10px; margin-bottom: 15px;">🍅 Tomaten-Pflanz-Empfehlung</h3>
    <div class="card" id="tomaten-pflanz-card">
        <div id="tomaten-pflanz-status" style="margin-bottom: 16px;">
            <div style="text-align: center; padding: 20px; color: #6b7280;">Wird berechnet…</div>
        </div>
        <div id="tomaten-pflanz-details" style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px;">
        </div>
        <div id="tomaten-pflanz-tipps" style="margin-top: 14px; display: none;">
        </div>
        <div style="margin-top: 14px; font-size: 0.78em; color: #9ca3af; border-top: 1px solid #f3f4f6; padding-top: 10px;" id="tomaten-pflanz-info"></div>
    </div>
```

- [ ] **Step 2: Verify page loads**

Run: `python3 main.py web --port 5000` (or just check the template renders without Jinja errors by visiting `/garten`)

- [ ] **Step 3: Commit**

```bash
git add src/web/templates/garten.html
git commit -m "feat: add tomato planting recommendation HTML section"
```

---

### Task 3: Add `_tomatenEmpfehlungen` and `renderTomatenEmpfehlungen` Functions

**Files:**
- Modify: `src/web/templates/garten.html` — insert in the `<script>` section, after `_rasenEmpfehlungen` function (after line 763, before `renderRasenEmpfehlungen`)

- [ ] **Step 1: Add the `_tomatenEmpfehlungen` function**

Insert after line 763 (`return items;` closing `_rasenEmpfehlungen`) and before `function renderRasenEmpfehlungen`:

```javascript
// ─── Tomaten-Pflanz-Empfehlungen ──────────────────────────────────
const EISHEILIGE_DATE = '05-15'; // 15. Mai (Mamertus-Sophie)
const TOMATO_SEASON_START = 4;   // April
const TOMATO_SEASON_END = 7;     // Juli

function _tomatenEmpfehlungen(soilTemp, weather) {
    const now = new Date();
    const month = now.getMonth() + 1;
    const year = now.getFullYear();

    // Eisheilige-Datum in diesem Jahr
    const eisheiligeDate = new Date(year, 4, 15); // Mai = Monat 4 (0-indiziert)
    const eisheiligePassed = now > eisheiligeDate;
    const daysUntilEisheilige = eisheiligePassed ? 0 : Math.ceil((eisheiligeDate - now) / (1000 * 60 * 60 * 24));

    // Nachttemperatur-Durchschnitt aus Forecast
    const forecast = weather?.forecast || [];
    const nightTemps = [];

    // Forecast hat 3h-Intervalle. Nacht = Eintraege mit Stunde 0,3,21 (und 18 im Winter)
    // Einfacher: Tiefstwert pro Tag aus allen Forecast-Eintraegen
    const tempsByDay = {};
    for (const f of forecast) {
        if (!f.timestamp) continue;
        const day = f.timestamp.slice(0, 10); // "YYYY-MM-DD"
        const temp = parseFloat(f.temperature);
        if (isNaN(temp)) continue;
        if (!tempsByDay[day]) tempsByDay[day] = [];
        tempsByDay[day].push(temp);
    }

    // Tiefstwert pro Tag
    const dailyMins = [];
    for (const [day, temps] of Object.entries(tempsByDay)) {
        if (temps.length > 0) dailyMins.push(Math.min(...temps));
    }

    // Durchschnitt der Nacht-Tiefstwerte (max 5 Tage)
    const nightAvg = dailyMins.length >= 3
        ? dailyMins.slice(0, 5).reduce((a, b) => a + b, 0) / Math.min(dailyMins.length, 5)
        : null;

    // Fallback: 5-Tage-Historiendurchschnitt - 5 Grad Nachtabschlag
    const histAvgTemp = weather?.avgTempDays ?? null;
    const nightAvgEffective = nightAvg !== null ? nightAvg : (histAvgTemp !== null ? histAvgTemp - 5 : null);

    // Bodentemperatur (Sensor oder Fallback)
    const soilTempEffective = soilTemp !== null ? soilTemp : histAvgTemp;

    // Kriterien pruefen
    const criteria = {
        eisheilige: {
            met: eisheiligePassed,
            value: eisheiligePassed ? 'Vorbei' : `Noch ${daysUntilEisheilige} Tage`,
            text: eisheiligePassed
                ? 'Eisheilige vorbei (nach 15. Mai) - kein Frostrisiko mehr'
                : `Noch ${daysUntilEisheilige} Tage bis nach den Eisheiligen (15. Mai) - nicht pflanzen!`,
            status: eisheiligePassed ? 'green' : (daysUntilEisheilige <= 7 ? 'orange' : 'red')
        },
        nightTemp: {
            met: nightAvgEffective !== null && nightAvgEffective > 10,
            value: nightAvgEffective !== null ? nightAvgEffective.toFixed(1) + ' °C' : '–',
            text: nightAvgEffective === null
                ? 'Keine Forecast-Daten verfuegbar'
                : nightAvgEffective > 10
                    ? `Naechte warm genug (${nightAvgEffective.toFixed(1)} °C Durchschnitt)`
                    : `Naechte zu kalt (${nightAvgEffective.toFixed(1)} °C) - brauche > 10 °C`,
            status: nightAvgEffective === null ? 'gray'
                  : nightAvgEffective > 10 ? 'green'
                  : nightAvgEffective > 8 ? 'orange' : 'red'
        },
        soilTemp: {
            met: soilTempEffective !== null && soilTempEffective >= 12,
            value: soilTempEffective !== null ? soilTempEffective.toFixed(1) + ' °C' : '–',
            text: soilTempEffective === null
                ? 'Keine Bodentemperatur verfuegbar (Sensor oder Historie fehlt)'
                : soilTempEffective >= 12
                    ? `Boden warm genug (${soilTempEffective.toFixed(1)} °C)`
                    : `Boden zu kalt (${soilTempEffective.toFixed(1)} °C) - brauche >= 12 °C`,
            status: soilTempEffective === null ? 'gray'
                  : soilTempEffective >= 12 ? 'green'
                  : soilTempEffective >= 10 ? 'orange' : 'red'
        }
    };

    // Gesamt-Status
    const allMet = criteria.eisheilige.met && criteria.nightTemp.met && criteria.soilTemp.met;
    const anyRed = Object.values(criteria).some(c => c.status === 'red');
    const inSeason = month >= TOMATO_SEASON_START && month <= TOMATO_SEASON_END;

    let overallStatus, overallText, overallIcon;
    if (!inSeason) {
        overallStatus = 'gray';
        overallIcon = '🍅';
        overallText = month < TOMATO_SEASON_START
            ? `Ausserhalb der Tomaten-Saison (ab April relevant)`
            : 'Ausserhalb der Tomaten-Saison';
    } else if (allMet) {
        overallStatus = 'green';
        overallIcon = '✅';
        overallText = 'Alle Bedingungen erfuellt - Tomaten koennen ins Hochbeet!';
    } else if (anyRed) {
        overallStatus = 'red';
        overallIcon = '🔴';
        overallText = 'Noch nicht pflanzen - Bedingungen nicht erfuellt';
    } else {
        overallStatus = 'orange';
        overallIcon = '⚠️';
        overallText = 'Fast bereit - einzelne Kriterien noch nicht erfuellt';
    }

    // Tipps (nur in der Saison anzeigen)
    const tipps = [];
    if (inSeason) {
        tipps.push({ icon: '🌤️', text: 'Abhaerten: Pflanzen 1-2 Wochen vorher schrittweise an Aussenbedingungen gewoehnen' });
        tipps.push({ icon: '☀️', text: 'Standort: Sonnig und windgeschuetzt - Tomaten brauchen 6+ Stunden Sonne' });
        tipps.push({ icon: '🪴', text: 'Boden: Kompost einarbeiten, leicht feucht halten beim Pflanzen' });
        if (!eisheiligePassed && daysUntilEisheilige <= 14) {
            tipps.push({ icon: '🧊', text: 'Frostschutz bereithalten (Vlies/Folie) falls doch mal kalte Nacht kommt' });
        }
    }

    return { overallStatus, overallIcon, overallText, criteria, tipps, inSeason };
}

function renderTomatenEmpfehlungen(soilTemp) {
    const weather = _rasenWeatherCache;
    const result = _tomatenEmpfehlungen(soilTemp, weather);

    const sc = {
        green:  { bg: '#f0fdf4', border: '#86efac', col: '#14532d' },
        orange: { bg: '#fffbeb', border: '#fcd34d', col: '#78350f' },
        red:    { bg: '#fef2f2', border: '#fca5a5', col: '#7f1d1d' },
        gray:   { bg: '#f9fafb', border: '#e5e7eb', col: '#6b7280' }
    };

    // Hauptstatus
    const os = sc[result.overallStatus];
    const statusEl = document.getElementById('tomaten-pflanz-status');
    statusEl.innerHTML = `
        <div style="padding: 16px; background: ${os.bg}; border: 2px solid ${os.border}; border-radius: 10px; text-align: center;">
            <div style="font-size: 2em; margin-bottom: 6px;">${result.overallIcon}</div>
            <div style="font-size: 1.1em; font-weight: 700; color: ${os.col};">${result.overallText}</div>
        </div>`;

    // Detail-Karten
    const detailEl = document.getElementById('tomaten-pflanz-details');
    const criteriaLabels = {
        eisheilige: { icon: '❄️', label: 'Eisheilige' },
        nightTemp: { icon: '🌙', label: 'Nachttemp. Ø' },
        soilTemp: { icon: '🌡️', label: 'Bodentemp.' }
    };
    detailEl.innerHTML = Object.entries(result.criteria).map(([key, c]) => {
        const meta = criteriaLabels[key];
        const s = sc[c.status];
        return `<div style="padding: 10px 12px; background: ${s.bg}; border: 1px solid ${s.border}; border-radius: 8px;">
            <div style="display: flex; align-items: center; gap: 6px; margin-bottom: 4px;">
                <span>${meta.icon}</span>
                <span style="font-weight: 600; color: ${s.col}; font-size: 0.9em;">${meta.label}</span>
                <span style="margin-left: auto; font-weight: 700; color: ${s.col}; font-size: 0.95em;">${c.value}</span>
            </div>
            <div style="font-size: 0.78em; color: ${s.col}; line-height: 1.4;">${c.text}</div>
        </div>`;
    }).join('');

    // Tipps
    const tippsEl = document.getElementById('tomaten-pflanz-tipps');
    if (result.tipps.length > 0) {
        tippsEl.style.display = 'block';
        tippsEl.innerHTML = '<div style="font-size: 0.85em; font-weight: 600; color: #374151; margin-bottom: 6px;">💡 Tipps:</div>' +
            result.tipps.map(t =>
                `<div style="font-size: 0.8em; color: #4b5563; padding: 4px 0; padding-left: 8px; border-left: 2px solid #d1d5db; margin-bottom: 4px;">${t.icon} ${t.text}</div>`
            ).join('');
    } else {
        tippsEl.style.display = 'none';
    }

    // Info-Zeile
    const soilStr = soilTemp !== null ? soilTemp.toFixed(1) + ' °C' : '–';
    const nightStr = weather?.avgTempDays !== null && weather?.avgTempDays !== undefined
        ? `Ø 5T: ${weather.avgTempDays.toFixed(1)} °C` : '';
    document.getElementById('tomaten-pflanz-info').textContent =
        `Bodentemp.: ${soilStr}${nightStr ? ' | ' + nightStr : ''} | Eisheilige: 11.-15. Mai`;
}
```

- [ ] **Step 2: Verify template has no syntax errors**

Run: `python3 -c "from jinja2 import Environment, FileSystemLoader; env = Environment(loader=FileSystemLoader('src/web/templates')); t = env.get_template('garten.html'); print('template ok')"`
Expected: `template ok`

- [ ] **Step 3: Commit**

```bash
git add src/web/templates/garten.html
git commit -m "feat: add tomato planting recommendation logic"
```

---

### Task 4: Extend `_rasenEmpfehlungen` with `effTemp` and Trend

**Files:**
- Modify: `src/web/templates/garten.html` — replace the `_rasenEmpfehlungen` function (lines 617-763)

- [ ] **Step 1: Replace `_rasenEmpfehlungen` with improved version**

Replace the entire function body of `_rasenEmpfehlungen` (from `function _rasenEmpfehlungen(moisture, soilTemp, weather) {` to its closing `}`) with:

```javascript
function _rasenEmpfehlungen(moisture, soilTemp, weather) {
    const month = new Date().getMonth() + 1;
    const rainProb = weather?.rainProbMax ?? 0;
    const outdoor  = weather?.outdoor ?? null;
    const avgTemp  = weather?.avgTempDays ?? null;
    const items    = [];

    // ── Effektive Temperatur berechnen ─────────────────
    let effTemp;
    if (soilTemp !== null && avgTemp !== null) {
        effTemp = 0.6 * soilTemp + 0.4 * avgTemp;
    } else if (soilTemp !== null) {
        effTemp = soilTemp;
    } else if (avgTemp !== null) {
        effTemp = avgTemp;
    } else {
        effTemp = null;
    }

    // ── Trend berechnen (aus Tagesliste) ────────────────
    let trend = null;
    let trendIcon = '';
    const dailyList = weather?.avgTempDailyList || [];
    if (dailyList.length >= 5) {
        const first2 = dailyList.slice(0, 2).reduce((s, d) => s + d.avg_temp, 0) / 2;
        const last3  = dailyList.slice(-3).reduce((s, d) => s + d.avg_temp, 0) / 3;
        const diff = last3 - first2;
        if (diff > 1) { trend = 'rising'; trendIcon = '↗️'; }
        else if (diff < -1) { trend = 'falling'; trendIcon = '↘️'; }
        else { trend = 'stable'; trendIcon = '→'; }
    }

    // ── Hilfsvariablen ──────────────────────────────────
    const grassGrows = effTemp !== null ? effTemp >= 10
                     : month >= 4 && month <= 10;
    const soilWarmEnough = effTemp !== null ? effTemp >= 12
                         : month >= 4;
    const heatWave = (outdoor !== null && outdoor > 28) || (effTemp !== null && effTemp > 26 && trend === 'rising');
    const trendHint = trend ? ` ${trendIcon} ${trend === 'rising' ? 'steigend' : trend === 'falling' ? 'fallend' : 'stabil'}` : '';
    const effTempStr = effTemp !== null ? effTemp.toFixed(1) + ' °C' : '–';

    // ── Giessen ─────────────────────────────────
    let gSt, gTx;
    if (!grassGrows) {
        gSt = 'gray';   gTx = `Kein Giessen noetig (Wachstumspause, eff. ${effTempStr})`;
    } else if (rainProb >= 60) {
        gSt = 'green';  gTx = 'Regen erwartet - kein Giessen noetig';
    } else if (moisture !== null && moisture > 60) {
        gSt = 'green';  gTx = 'Boden feucht genug - kein Giessen noetig';
    } else if (heatWave && moisture !== null && moisture < 50) {
        gSt = 'red';    gTx = `Hitzeperiode! Taeglich morgens giessen (6-9 Uhr)${trendHint}`;
    } else if (moisture !== null && moisture < 30 && rainProb < 30) {
        gSt = 'red';    gTx = 'Dringend giessen! Boden sehr trocken -> beste Zeit: 6-9 Uhr';
    } else if (moisture !== null && moisture < 50 && rainProb < 30) {
        gSt = 'orange'; gTx = 'Giessen empfohlen - morgens 6-9 Uhr, nicht in der Mittagssonne';
    } else {
        gSt = 'green';  gTx = 'Bodenfeuchte akzeptabel';
    }
    items.push({ icon: '💧', label: 'Giessen', status: gSt, text: gTx });

    // ── Maehen ───────────────────────────────────
    let mSt, mTx;
    if (month < 3 || month > 11) {
        mSt = 'gray';   mTx = 'Maehpause (Winter)';
    } else if (!grassGrows) {
        mSt = 'gray';   mTx = `Gras waechst noch nicht - zu kalt (eff. ${effTempStr})${trendHint}`;
    } else if (moisture !== null && moisture > 75) {
        mSt = 'red';    mTx = 'Boden zu nass - Maehen vermeiden (Bodenverdichtung)';
    } else if (rainProb >= 60) {
        mSt = 'orange'; mTx = 'Regen erwartet - Maehen besser verschieben';
    } else if (heatWave) {
        mSt = 'orange'; mTx = `Hitzeperiode (eff. ${effTempStr}): Schnitthoehe 6-7 cm, frueh morgens maehen${trendHint}`;
    } else {
        const firstMow = effTemp !== null ? effTemp < 12 : month === 3;
        mSt = 'green';
        mTx = firstMow ? 'Erstes Maehen moeglich - Schnitthoehe 4-5 cm' : 'Gute Bedingungen (Schnitthoehe 4-5 cm)';
    }
    items.push({ icon: '🌾', label: 'Maehen', status: mSt, text: mTx });

    // ── Lueften / Standen ────────────────────────
    let lSt, lTx;
    if ([4, 5].includes(month)) {
        if (moisture !== null && moisture > 70) {
            lSt = 'orange'; lTx = 'Boden noch zu nass - warten bis etwas trockener';
        } else {
            lSt = 'green';  lTx = 'Ideale Zeit zum Belueften / Standen (April-Mai)';
        }
    } else if ([9, 10].includes(month)) {
        lSt = 'green';  lTx = 'Herbst-Belueftung moeglich (September-Oktober)';
    } else if (month >= 6 && month <= 8) {
        lSt = 'gray';   lTx = 'Kein Lueften im Sommer (Hitzestress fuer Gras)';
    } else {
        lSt = 'gray';   lTx = 'Saison: April-Mai und September-Oktober';
    }
    items.push({ icon: '🍃', label: 'Lueften / Standen', status: lSt, text: lTx });

    // ── Vertikutieren ───────────────────────────
    let vSt, vTx;
    if (month === 3 || month === 4) {
        if (!soilWarmEnough) {
            vSt = 'orange'; vTx = `Fast Zeit - warten bis eff. Temp. >= 12 °C (aktuell ${effTempStr})${trendHint}`;
        } else if (moisture !== null && (moisture > 70 || moisture < 25)) {
            vSt = 'orange'; vTx = 'Boden zu nass/trocken - optimale Feuchte abwarten';
        } else {
            vSt = 'green';  vTx = `Optimale Zeit zum Vertikutieren (Fruehjahr)!${trendHint}`;
        }
    } else if (month === 9) {
        vSt = 'green';  vTx = 'Herbst-Vertikutierung moeglich (mind. 6 Wochen vor Frost)';
    } else if (month >= 5 && month <= 8) {
        vSt = 'gray';   vTx = 'Nicht im Sommer vertikutieren (zu viel Stress)';
    } else {
        vSt = 'gray';   vTx = 'Saison: Maerz-April und September';
    }
    items.push({ icon: '⚙️', label: 'Vertikutieren', status: vSt, text: vTx });

    // ── Dueengen ──────────────────────────────────
    let dSt, dTx;
    if (month === 4 || month === 5) {
        dSt = 'green';  dTx = `Jetzt Langzeit-Fruejahrsduenger (NPK) ausbringen${trendHint}`;
    } else if (month === 6) {
        dSt = 'green';  dTx = 'Sommerduenger moeglich (leichte Gabe, viel danach giessen)';
    } else if (month === 9) {
        dSt = 'green';  dTx = 'Herbstduenger ausbringen - kaliumreich, kein Stickstoff!';
    } else if (month === 3) {
        if (soilWarmEnough) {
            dSt = 'orange'; dTx = `Fruehduenger moeglich - Boden warm genug (eff. ${effTempStr})${trendHint}`;
        } else {
            dSt = 'gray';   dTx = `Noch zu frueh - warten bis eff. Temp. mind. 10 °C (aktuell ${effTempStr})${trendHint}`;
        }
    } else if (heatWave && (month >= 7 && month <= 8)) {
        dSt = 'gray';   dTx = 'Kein Duenger bei Hitze (Verbrennungsgefahr)';
    } else if (month >= 7 && month <= 8) {
        dSt = 'gray';   dTx = 'Kein Stickstoff-Duenger im Hochsommer';
    } else if (month === 10) {
        dSt = 'orange'; dTx = 'Kein Duenger mehr - Gras geht in Ruhephase';
    } else {
        dSt = 'gray';   dTx = 'Ausserhalb der Dueengesaison';
    }
    items.push({ icon: '🌿', label: 'Dueengen', status: dSt, text: dTx });

    // ── Nachsaeen ────────────────────────────────
    let nSt, nTx;
    if (month === 4 || month === 5) {
        const trendGood = trend === 'rising' ? ' - Temperaturen steigen, gutes Zeitfenster!' : '';
        nSt = 'green';  nTx = `Ideale Zeit zum Nachsaeen (warm + Niederschlaege)${trendGood}`;
    } else if (month === 9) {
        nSt = 'green';  nTx = 'Herbst-Nachsaat empfohlen (September)';
    } else if (month === 3) {
        if (soilWarmEnough) {
            nSt = 'orange'; nTx = `Fruehsaat moeglich - Boden ausreichend warm (eff. ${effTempStr})${trendHint}`;
        } else {
            nSt = 'gray';   nTx = `Noch zu kalt fuer Rasensamen (eff. ${effTempStr})${trendHint}`;
        }
    } else if (month >= 6 && month <= 8) {
        nSt = 'orange'; nTx = 'Saat im Sommer nur mit sehr regelmaszigem Giessen moeglich';
    } else {
        nSt = 'gray';   nTx = 'Ausserhalb der Rasensaat-Saison';
    }
    items.push({ icon: '🌱', label: 'Nachsaeen', status: nSt, text: nTx });

    // Trend-Daten fuer Info-Zeile speichern
    items._effTemp = effTemp;
    items._trend = trend;
    items._trendIcon = trendIcon;

    return items;
}
```

- [ ] **Step 2: Verify template renders**

Run: `python3 -c "from jinja2 import Environment, FileSystemLoader; env = Environment(loader=FileSystemLoader('src/web/templates')); t = env.get_template('garten.html'); print('template ok')"`
Expected: `template ok`

- [ ] **Step 3: Commit**

```bash
git add src/web/templates/garten.html
git commit -m "feat: improve lawn recommendations with effective temperature and trend"
```

---

### Task 5: Update `renderRasenEmpfehlungen` Info-Line and `refreshAll`

**Files:**
- Modify: `src/web/templates/garten.html` — update `renderRasenEmpfehlungen` (lines ~766-796) and `refreshAll` (lines ~799-822)

- [ ] **Step 1: Update `renderRasenEmpfehlungen` info-line**

In `renderRasenEmpfehlungen`, replace the info-line section at the bottom (the part after `items.map(...)`) with:

```javascript
    const months = ['','Januar','Februar','Maerz','April','Mai','Juni','Juli','August','September','Oktober','November','Dezember'];
    const m = new Date().getMonth() + 1;
    const mStr = moisture !== null ? moisture.toFixed(1) + ' %' : '–';
    const tStr = soilTemp !== null ? soilTemp.toFixed(1) + ' °C' : '–';
    const avgStr = weather?.avgTempDays !== null && weather?.avgTempDays !== undefined
        ? weather.avgTempDays.toFixed(1) + ' °C' : '–';
    const effStr = items._effTemp !== null && items._effTemp !== undefined
        ? items._effTemp.toFixed(1) + ' °C' : '–';
    const trendStr = items._trendIcon && items._trend
        ? ` | Trend: ${items._trendIcon} ${items._trend === 'rising' ? 'steigend' : items._trend === 'falling' ? 'fallend' : 'stabil'}`
        : '';
    document.getElementById('rasen-pflege-info').textContent =
        `Empfehlungen fuer ${months[m]} — Boden: ${tStr} | Ø 5T: ${avgStr} | Effektiv: ${effStr}${trendStr}`;
```

- [ ] **Step 2: Update `refreshAll` to call tomato recommendations**

In `refreshAll`, after the line `renderRasenEmpfehlungen(rasenMoisture, rasenSoilTemp);`, add the tomato rendering. Also need to collect Hochbeet soil temp for the tomato function.

Replace the `refreshAll` function body. Find `async function refreshAll() {` and replace the entire function with:

```javascript
async function refreshAll() {
    const keys = ['hochbeet1', 'hochbeet2', 'rasen1'];
    const moistureSensors = [SENSORS.hochbeet1, SENSORS.hochbeet2, SENSORS.rasen1];
    const tempSensors     = [SENSORS.hochbeet1_temp, SENSORS.hochbeet2_temp, SENSORS.rasen1_temp];

    let successCount = 0;
    let rasenMoisture = null, rasenSoilTemp = null;
    let hochbeetSoilTemp = null;
    for (let i = 0; i < keys.length; i++) {
        const [moistureData, tempData] = await Promise.all([
            fetchSensorValue(moistureSensors[i]),
            fetchSensorValue(tempSensors[i])
        ]);
        updateCard(keys[i], moistureData, tempData);
        if (moistureData) successCount++;
        if (keys[i] === 'rasen1') {
            rasenMoisture = moistureData ? parseFloat(moistureData.state) : null;
            if (isNaN(rasenMoisture)) rasenMoisture = null;
            rasenSoilTemp = tempData ? parseFloat(tempData.state) : null;
            if (isNaN(rasenSoilTemp)) rasenSoilTemp = null;
        }
        if (keys[i] === 'hochbeet1' || keys[i] === 'hochbeet2') {
            const t = tempData ? parseFloat(tempData.state) : null;
            if (t !== null && !isNaN(t)) {
                // Nimm den hoeheren Wert falls beide Sensoren vorhanden
                hochbeetSoilTemp = hochbeetSoilTemp !== null ? Math.max(hochbeetSoilTemp, t) : t;
            }
        }
    }
    await updateSummary(successCount);
    renderTomatenEmpfehlungen(hochbeetSoilTemp);
    renderRasenEmpfehlungen(rasenMoisture, rasenSoilTemp);
}
```

- [ ] **Step 3: Verify template renders**

Run: `python3 -c "from jinja2 import Environment, FileSystemLoader; env = Environment(loader=FileSystemLoader('src/web/templates')); t = env.get_template('garten.html'); print('template ok')"`
Expected: `template ok`

- [ ] **Step 4: Commit**

```bash
git add src/web/templates/garten.html
git commit -m "feat: wire up tomato recommendations and update rasen info line with trend"
```

---

### Task 6: End-to-End Verification

- [ ] **Step 1: Start the web server**

Run: `python3 main.py web --port 5000`

- [ ] **Step 2: Verify in browser**

Open `http://localhost:5000/garten` and check:
- Tomaten-Empfehlung section appears between Hochbeet and Rasen
- Shows Eisheilige status (should show countdown to May 15 if before that date)
- Shows Nachttemp status
- Shows Bodentemp status
- Rasen recommendations show "Effektiv: X °C" and trend in the info line
- All recommendation cards render correctly with color coding
- Page refreshes every 60 seconds without errors

- [ ] **Step 3: Check browser console for errors**

Open browser DevTools → Console. Expected: No JavaScript errors.

- [ ] **Step 4: Final commit if any fixes needed**

```bash
git add -A
git commit -m "fix: address any issues found during verification"
```
