# Übersicht: Nutzung der zentralen Raum-Config API

## Status: Zentrale Config (`/api/rooms/settings`)

### ✅ Bereits optimiert (nutzen `/api/rooms/settings`):
1. **`devices.js`** - Nutzt `/api/rooms/settings` ✓
2. **`lighting.html`** - Nutzt `/api/rooms/settings` ✓

### ⚠️ Können optimiert werden:

#### Einfache Fälle (nur GET-Requests):
1. **`luftentfeuchten.js`** 
   - Aktuell: `/api/rooms`
   - Könnte: `/api/rooms/settings` nutzen
   - Nutzt: Nur `rooms` Array

2. **`rooms.js`** (GET-Operation)
   - Aktuell: `/api/rooms`
   - Könnte: `/api/rooms/settings` nutzen
   - Nutzt: `rooms` und `assignments`

3. **`heating.js`**
   - Aktuell: `/api/rooms/hidden` (separater Call)
   - Könnte: `hidden` aus `/api/rooms/settings` nutzen
   - Nutzt: `hidden` Array

4. **`mold_prevention.html`**
   - Aktuell: `/api/rooms/hidden` (separater Call)
   - Könnte: `hidden` aus `/api/rooms/settings` nutzen
   - Nutzt: `hidden` Array

5. **`ventilation.html`**
   - Aktuell: `/api/rooms/hidden` (separater Call)
   - Könnte: `hidden` aus `/api/rooms/settings` nutzen
   - Nutzt: `hidden` Array

#### Komplexe Fälle (mehrere Endpunkte):
6. **`rooms.html`**
   - Aktuell: Nutzt viele separate Endpunkte:
     - `/api/rooms/hidden`
     - `/api/rooms`
     - `/api/ventilation/sensor-mapping`
     - `/api/rooms/motion-sensors`
     - `/api/rooms/device-types`
     - `/api/rooms/window-status`
     - `/api/rooms/valves`
   - Könnte: Teilweise optimiert werden (hidden, rooms, sensor-mappings, motion-sensors aus settings)
   - Hinweis: `window-status`, `valves`, `device-types` sind Live-Daten, bleiben separat

## Empfehlung

### Priorität 1 (Einfach, sofort umsetzbar):
- `luftentfeuchten.js` - 1 Zeile ändern
- `rooms.js` - 1 Zeile ändern  
- `heating.js` - 1 separater Call entfernen
- `mold_prevention.html` - 1 separater Call entfernen
- `ventilation.html` - 1 separater Call entfernen

### Priorität 2 (Komplexer):
- `rooms.html` - Teilweise optimieren (nur Config-Daten, nicht Live-Daten)

## Vorteile der Optimierung:
- ✅ Weniger API-Calls
- ✅ Konsistente Datenquelle
- ✅ Bessere Performance
- ✅ Einfacheres Caching möglich

