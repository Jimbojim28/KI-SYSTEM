# Design: KI-SYSTEM Frontend Redesign - Hell & Freundlich

**Datum**: 2026-04-03
**Status**: Draft
**Dateien**: `src/web/templates/base.html`, alle 19 Template-Dateien

## Zusammenfassung

Kompletter Frontend-Redesign des KI-SYSTEM Dashboards von Dark Tech-Noir zu einem warmen, natuerlichen, freundlichen Design. Das bestehende Layout (horizontale Navigation oben) bleibt erhalten, nur die visuelle Gestaltung aendert sich.

## 1. Farbpalette

### Hintergruende
| Element | Farbe | Usage |
|---------|-------|-------|
| Haupt-HG | `#faf7f2` | Body-Hintergrund (Creme-Weiss) |
| Karten | `#ffffff` | Alle Karten-Inhalte |
| Sidebar/Panel | `#f0ebe3` | Seitliche Bereiche, Hervorhebungen |
| Hover | `#f5f0e8` | Hover-Zustaende |
| Page-Header | Gradient `#faf7f2` → `#f0ebe3` | Bereichs-Ueberschriften |

### Akzentfarben
| Name | Farbe | Verwendung |
|------|-------|-----------|
| Primaer (Gruen) | `#00b894` | Buttons, aktive States, Erfolg |
| Erfolg | `#27ae60` | Positive Meldungen, "OK" States |
| Warnung | `#fdcb6e` | Warnungen, "Achtung" |
| Gefahr | `#e17055` | Fehler, kritische Zustaende |
| Info | `#6c5ce7` | Informationen, Hinweise |
| Akzent (Orange) | `#f0932b` | Hervorhebungen, besondere Werte |

### Textfarben
| Name | Farbe | Verwendung |
|------|-------|-----------|
| Ueberschriften | `#2d3436` | h1-h6, wichtige Labels |
| Fliesstext | `#636e72` | Absaetze, Beschreibungen |
| Untertitel | `#b2bec3` | Sekundaere Infos, Zeitstempel |

### Status-Badge-Farben
| Status | Hintergrund | Text |
|--------|-------------|------|
| Optimal/OK | `#d4edda` | `#155724` |
| Warnung | `#fff3cd` | `#856404` |
| Gefahr/Fehler | `#fde2e2` | `#721c24` |
| Info | `#e8daef` | `#6c3483` |
| Offline/Inaktiv | `#f0f0f0` | `#636e72` |

## 2. Navigation (Obere Leiste)

### Struktur
- Horizontale Leiste oben, fixiert (sticky)
- Hintergrund: `#ffffff`
- Rahmen unten: `1px solid #e8e0d4`
- Leichte Boxshadow: `0 1px 4px rgba(0,0,0,0.03)`
- Hoehe: ca. 60px

### Brand
- Links: "KI Smart Home" in `font-weight: 700`, Farbe `#2d3436`
- Optional kleines Logo-Icon oder Haus-Emoji

### Tabs
- Inaktiv: Farbe `#636e72`, kein Hintergrund
- Hover: Farbe `#2d3436`, Hintergrund `#f5f0e8`, Radius `8px`
- Aktiv: Farbe `#00b894`, Hintergrund `#d4edda`, Radius `8px`, `font-weight: 600`
- Untereinander: Tabs mit zusammengefassten Gruppen (z.B. "Haus", "Garten", "System")

### Mobile
- Burger-Menue mit Slide-in von rechts
- Hintergrund: `#ffffff`
- Gleiche Tab-Stile wie Desktop

## 3. Karten & Komponenten

### Standard-Karte
- Hintergrund: `#ffffff`
- Border-Radius: `16px`
- Box-Shadow: `0 2px 12px rgba(0,0,0,0.05)`
- Rahmen: `1px solid rgba(0,0,0,0.04)`
- Padding: `20px`
- Hover: `translateY(-2px)`, Box-Shadow: `0 4px 20px rgba(0,0,0,0.08)`
- Transition: `all 0.2s ease`

### Wert-Kacheln (Sensorwerte)
- Border-Radius: `12px`
- Hintergrund: Farbton passend zum Typ
  - Temperatur: `#fff8f0` (warm-orange)
  - Feuchte: `#f0fdf4` (gruen)
  - Status/Info: `#f0f0ff` (lila)
- Grosser Wert: `font-size: 22px`, `font-weight: 700`, farbige Zahl
- Label darunter: `font-size: 10px`, Farbe `#636e72`

### Badges
- Pillenform: `border-radius: 20px`
- Padding: `4px 12px`
- Pastellige Hinterlegung (nicht neon/saettig)
- Text in passender dunkler Farbe
- Font-Size: `11px`, `font-weight: 600`

### Buttons
- Primaer:
  - Hintergrund: `#00b894`
  - Text: `#ffffff`
  - Border-Radius: `10px`
  - Padding: `10px 20px`
  - Hover: `#00a884` (dunkler)
  - Box-Shadow: `0 2px 8px rgba(0,184,148,0.25)`
- Sekundaer:
  - Hintergrund: `#ffffff`
  - Rahmen: `1px solid #e0d6c8`
  - Text: `#2d3436`
  - Hover: Hintergrund `#f5f0e8`

### Formular-Elemente
- Hintergrund: `#ffffff`
- Rahmen: `1px solid #e0d6c8`
- Border-Radius: `10px`
- Padding: `10px 14px`
- Focus: Rahmen `#00b894`, Box-Shadow `0 0 0 3px rgba(0,184,148,0.15)`
- Placeholder: Farbe `#b2bec3`

### Progress-Bars
- Hintergrund: `#e8e0d4` (warmer als vorher)
- Fuell-Farbe: je nach Status (Gruen/Gelb/Rot)
- Border-Radius: `8px`
- Hoehe: `10px`
- Transition: `width 0.5s ease`

## 4. Typografie

### Schriftarten
| Verwendung | Schriftart | Weight |
|-----------|-----------|--------|
| Ueberschriften | DM Sans | 600, 700 |
| Fliesstext | DM Sans | 400 |
| Zahlen/Werte | JetBrains Mono | 600 |
| Code/Ausschnitte | JetBrains Mono | 400 |

### Groessen
| Element | Groesse | Weight |
|---------|---------|--------|
| Page-Header (h2) | 24px | 700 |
| Section-Header (h3) | 18px | 600 |
| Karten-Titel | 16px | 600 |
| Fliesstext | 14px | 400 |
| Labels/Badges | 11-12px | 600 |
| Kleintext | 10px | 400 |

## 5. Layout

### Container
- Max-Breite: `1200px`, zentriert
- Padding: `24px` zum Rand
- Karten-Abstand (Gap): `20px`

### Grids
- Sensor-Karten: `grid-template-columns: repeat(auto-fit, minmax(280px, 1fr))`
- Empfehlungs-Karten: `grid-template-columns: repeat(auto-fit, minmax(220px, 1fr))`
- Statistik-Zeilen: Flexbox mit `gap: 20px`

### Bereiche auf der Seite
- Section-Abstand: `24px` zwischen Bereichen
- Bereichs-Ueberschrift: `margin-bottom: 16px`
- Info-Zeile am Ende: `border-top: 1px solid #f0ebe3`, `padding-top: 12px`

## 6. Animationen

### Einblenden
```css
@keyframes fadeIn {
  from { opacity: 0; transform: translateY(10px); }
  to { opacity: 1; transform: translateY(0); }
}
```
- Dauer: `0.3s`
- Gestaffelt: `animation-delay` in 50ms Schritten

### Hover
- Karten: `translateY(-2px)` mit sanftem Schatten
- Buttons: Hintergrund-Aenderung
- Transition-Dauer: `0.2s ease`

### Keine Effekte mehr
- Keine Neon-Glow
- Keine Glasmorphismus-Blur-Effekte
- Keine Noise-Texture-Overlays
- Keine Puls-Animationen bei Status-Punkten

## 7. Was sich NICHT aendert

- Seitenstruktur und Routing (Flask)
- JavaScript-Logik (Sensor-Abfragen, Empfehlungen, Charts)
- API-Endpoints
- Template-Dateinamen und -inhalt-Struktur
- Chart.js-Konfiguration (nur Farben passen sich an)
- Emoji-Icons in Navigation und Karten

## 8. Umsetzung

### Betroffene Datei
- `src/web/templates/base.html` - Einzige Datei die geaendert werden muss (globales CSS + Navigation)

### Vorgehen
1. CSS-Variablen in `:root` austauschen (alle Farben)
2. Karten-, Button-, Badge-, Form-Stile aktualisieren
3. Navigation-Styling anpassen
4. Animationen reduzieren (Glow/Blur entfernen)
5. Noise-Texture-Overlay entfernen
6. Hintergrund-Farben aller Bereiche anpassen
7. Hover- und Fokus-Effekte sanfter machen

Alle 19 Template-Dateien erben automatisch vom base.html, daher reicht die Aenderung einer einzigen Datei.
