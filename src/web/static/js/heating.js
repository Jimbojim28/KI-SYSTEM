// Heating Page JavaScript

let allHeaters = [];
let allWindows = [];
let allRooms = [];
let roomSensorData = {};  // Zentrale Raum-Sensordaten
let outdoorData = {};     // Zentrale Außendaten
let hiddenRooms = [];  // Versteckte Räume aus zentraler /rooms Konfiguration
let zoneNameMap = {};
let currentFilter = 'all';
let currentRoomFilter = 'all';
let currentMode = 'control'; // control oder optimization
let temperatureChart = null; // Chart.js Instanz für Temperaturverlauf
let currentTempTimeframe = 24; // Aktueller Zeitraum für Temperaturverlauf in Stunden

// Fenster-Statistik Charts
let windowDurationChart = null;
let windowFrequencyChart = null;
let windowTrendsChart = null;

// Lade alle Heizgeräte beim Seitenaufruf
document.addEventListener('DOMContentLoaded', async () => {
    // Zuerst versteckte Räume laden (aus zentraler /rooms Konfiguration)
    await loadHiddenRooms();
    
    // Lade zentrale Sensordaten (inkl. Outdoor)
    await loadCentralSensorData();
    
    loadHeaters();
    loadHeatingMode();
    setupEventListeners();
    setupSliders();

    // Lade Fenster-Daten
    loadWindowData();

    // Lade Temperaturverlauf (immer)
    loadTemperatureHistory();

    // Lade Optimierungsdaten (immer, unabhängig vom Modus)
    loadOptimizationData();

    // Lade Heizungs-Analytics
    loadHeatingAnalytics();

    // Lade neue Features
    loadHumidityAlerts();
    loadVentilationRecommendations();
    loadShowerPredictions();
});

// Zentrale Sensordaten laden (für Outdoor-Temperatur und Raumdaten)
async function loadCentralSensorData() {
    try {
        const response = await fetch('/api/rooms/sensor-data');
        if (response.ok) {
            const data = await response.json();
            
            // Speichere Outdoor-Daten
            outdoorData = data.outdoor || {};
            
            // Speichere Raum-Sensordaten
            roomSensorData = {};
            (data.rooms || []).forEach(room => {
                roomSensorData[room.name] = room;
            });
            
            // Update Außentemperatur-Anzeige sofort
            updateOutdoorTempDisplay();
            
            console.log('Central sensor data loaded:', Object.keys(roomSensorData).length, 'rooms');
        }
    } catch (error) {
        console.error('Error loading central sensor data:', error);
    }
}

// Außentemperatur-Anzeige aktualisieren
function updateOutdoorTempDisplay() {
    const outdoorTemp = outdoorData.temperature;
    if (outdoorTemp !== undefined && outdoorTemp !== null) {
        document.getElementById('outdoor-temp').textContent = outdoorTemp.toFixed(1) + '°C';
    }
}

// Versteckte Räume aus zentraler Konfiguration laden
async function loadHiddenRooms() {
    try {
        // Nutze zentrale Settings-API (enthält auch hidden)
        const response = await fetch('/api/rooms/settings');
        if (response.ok) {
            const data = await response.json();
            hiddenRooms = data.hidden || [];
            console.log('Hidden rooms loaded:', hiddenRooms);
        }
    } catch (error) {
        console.error('Error loading hidden rooms:', error);
        hiddenRooms = [];
    }
}

// Event Listeners einrichten
function setupEventListeners() {
    // Refresh Button
    document.getElementById('refresh-heating')?.addEventListener('click', () => {
        loadCentralSensorData();  // Aktualisiere zentrale Daten
        loadHeaters();
        loadWindowData();
        loadTemperatureHistory();
        loadOptimizationData(); // Immer laden
    });

    // Filter
    document.querySelectorAll('.filter-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            currentFilter = btn.dataset.filter;
            renderHeaters();
        });
    });

    document.getElementById('room-filter')?.addEventListener('change', (e) => {
        currentRoomFilter = e.target.value;
        renderHeaters();
    });

    // Analytics Zeitraum Selector
    document.getElementById('analytics-timeframe')?.addEventListener('change', () => {
        loadHeatingAnalytics();
    });

    // Fenster-Statistik Zeitraum Selector
    document.getElementById('window-stats-timeframe')?.addEventListener('change', () => {
        loadWindowStatistics();
    });

    // Temperaturverlauf Zeitraum Selector
    document.querySelectorAll('.temp-timeframe-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            // Entferne active class von allen Buttons
            document.querySelectorAll('.temp-timeframe-btn').forEach(b => {
                b.classList.remove('active');
                b.style.background = 'white';
                b.style.color = '#374151';
            });

            // Setze active class für aktuellen Button
            btn.classList.add('active');
            btn.style.background = '#3b82f6';
            btn.style.color = 'white';

            // Aktualisiere Zeitraum und lade Daten neu
            currentTempTimeframe = parseInt(btn.dataset.hours);
            loadTemperatureHistory();
        });
    });

    // Speichern

    // Zeitplan erstellen
    document.getElementById('add-schedule')?.addEventListener('click', () => {
        document.getElementById('schedule-modal').style.display = 'block';
    });

    // Modal schließen
    document.querySelectorAll('.close').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.modal').forEach(modal => {
                modal.style.display = 'none';
            });
        });
    });

    // Modal außerhalb klicken
    window.addEventListener('click', (e) => {
        if (e.target.classList.contains('modal')) {
            e.target.style.display = 'none';
        }
    });
}

// Slider mit Wert-Anzeige einrichten
function setupSliders() {
    const sliders = [
        { id: 'default-comfort-temp', valueId: 'default-comfort-temp-value' },
        { id: 'default-eco-temp', valueId: 'default-eco-temp-value' },
        { id: 'default-night-temp', valueId: 'default-night-temp-value' },
        { id: 'default-frost-temp', valueId: 'default-frost-temp-value' },
        { id: 'modal-temp-slider', valueId: 'modal-temp-value' },
        { id: 'schedule-temp', valueId: 'schedule-temp-value' }
    ];

    sliders.forEach(({ id, valueId }) => {
        const slider = document.getElementById(id);
        const valueDisplay = document.getElementById(valueId);
        if (slider && valueDisplay) {
            slider.addEventListener('input', () => {
                valueDisplay.textContent = slider.value + '°C';
            });
        }
    });
}

// Lade alle Heizgeräte
async function loadHeaters() {
    try {
        // Lade Geräte (für Steuerung) und zentrale Sensordaten parallel
        const [devicesData, sensorData] = await Promise.all([
            fetchJSON('/api/devices'),
            fetchJSON('/api/rooms/sensor-data')
        ]);

        const allDevices = devicesData.devices || [];
        
        // Speichere zentrale Daten
        outdoorData = sensorData.outdoor || {};
        roomSensorData = {};
        (sensorData.rooms || []).forEach(room => {
            roomSensorData[room.name] = room;
            // Erstelle auch Zone-ID Mapping
            if (room.id) {
                zoneNameMap[room.id] = room.name;
            }
        });
        
        // Update Außentemperatur
        updateOutdoorTempDisplay();

        console.log('Loaded devices:', allDevices.length);
        console.log('Climate devices:', allDevices.filter(d => d.domain === 'climate'));

        // Erstelle Zone-ID zu Name Mapping aus alten Raumdaten falls nötig
        allRooms = Object.values(roomSensorData).map(r => ({ id: r.id, name: r.name }));

        // Filtere nur Heizgeräte (climate domain)
        allHeaters = allDevices.filter(d => {
            // Climate domain ist der Hauptindikator
            if (d.domain === 'climate') return true;

            // Thermostat class
            if (d.attributes?.device_class === 'thermostat') return true;
            if (d.class === 'thermostat') return true;

            // Hat target_temperature capability
            if (d.capabilitiesObj?.target_temperature) return true;
            if (d.capabilities?.target_temperature) return true;
            if (d.attributes?.capabilities?.target_temperature) return true;

            return false;
        });

        // Füge Raumnamen zu Heizgeräten hinzu
        allHeaters.forEach(heater => {
            const zoneId = heater.attributes?.zone || heater.zone;
            heater.zoneName = zoneId ? zoneNameMap[zoneId] : 'Ohne Raum';
        });

        // Filtere Heizgeräte aus versteckten Räumen (aus zentraler /rooms Konfiguration)
        if (hiddenRooms.length > 0) {
            const beforeCount = allHeaters.length;
            allHeaters = allHeaters.filter(h => !hiddenRooms.includes(h.zoneName));
            console.log(`Filtered out ${beforeCount - allHeaters.length} heaters from hidden rooms`);
        }

        console.log('Filtered heaters:', allHeaters.length);
        if (allHeaters.length > 0) {
            console.log('First heater example:', allHeaters[0]);
        }

        updateStatistics();
        populateRoomFilter();
        renderHeaters();
    } catch (error) {
        console.error('Error loading heaters:', error);
        document.getElementById('heaters-container').innerHTML =
            '<div class="error">Fehler beim Laden der Heizgeräte</div>';
    }
}

// Update Statistiken
function updateStatistics() {
    const activeHeaters = allHeaters.filter(h => isHeaterActive(h)).length;
    const temps = allHeaters
        .map(h => getCurrentTemp(h))
        .filter(t => t !== null && !isNaN(t));

    const avgTemp = temps.length > 0
        ? (temps.reduce((a, b) => a + b, 0) / temps.length).toFixed(1)
        : '--';

    document.getElementById('total-heaters').textContent = allHeaters.length;
    document.getElementById('active-heaters').textContent = activeHeaters;
    document.getElementById('avg-temp').textContent = avgTemp + (avgTemp !== '--' ? '°C' : '');
}

// Lade Außentemperatur (nutzt jetzt zentrale Daten)
async function loadOutdoorTemp() {
    // Nutze bereits geladene zentrale Daten
    if (outdoorData.temperature !== undefined) {
        updateOutdoorTempDisplay();
        return;
    }
    
    // Fallback: Lade zentrale Daten wenn noch nicht vorhanden
    await loadCentralSensorData();
}

// Lade Temperaturverlauf für Chart
async function loadTemperatureHistory(hours = null) {
    try {
        // Verwende übergebenen Wert oder aktuellen Zeitraum
        const timeframe = hours || currentTempTimeframe;
        const response = await fetchJSON(`/api/heating/temperature-history?hours=${timeframe}`);

        if (!response.success) {
            console.error('Error loading temperature history:', response.error);
            return;
        }

        // Wenn keine Daten vorhanden
        if (!response.data || response.data.timestamps.length === 0) {
            const chartContainer = document.getElementById('temperature-chart').parentElement;
            chartContainer.innerHTML = `
                <div style="text-align: center; padding: 40px; background: linear-gradient(135deg, #eff6ff 0%, #ffffff 100%); border-radius: 8px; border: 1px solid #dbeafe;">
                    <div style="font-size: 2.5em; margin-bottom: 15px;">⏳</div>
                    <h4 style="margin: 0 0 10px 0; color: #1e40af;">Daten werden gesammelt</h4>
                    <p style="margin: 0 0 10px 0; color: #6b7280;">
                        ${response.message || 'Der HeatingDataCollector sammelt alle 15 Minuten Heizungsdaten.'}
                    </p>
                    <p style="margin: 0; font-size: 0.85em; color: #9ca3af;">
                        Nach 15-30 Minuten werden hier die ersten Temperaturverläufe angezeigt.
                    </p>
                </div>
            `;
            return;
        }

        renderTemperatureChart(response.data);

    } catch (error) {
        console.error('Error loading temperature history:', error);
    }
}

// Rendere Temperaturverlauf Chart
function renderTemperatureChart(data) {
    const ctx = document.getElementById('temperature-chart');
    if (!ctx) return;

    // Zerstöre existierenden Chart
    if (temperatureChart) {
        temperatureChart.destroy();
    }

    // Formatiere Timestamps für X-Achse
    const labels = data.timestamps.map(ts => {
        const date = new Date(ts);
        return date.toLocaleTimeString('de-DE', {
            hour: '2-digit',
            minute: '2-digit'
        });
    });

    // Erstelle Chart
    temperatureChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [
                {
                    label: 'Außentemperatur',
                    data: data.outdoor_temp,
                    borderColor: '#ef4444',
                    backgroundColor: 'rgba(239, 68, 68, 0.1)',
                    borderWidth: 2,
                    tension: 0.4,
                    fill: false,
                    spanGaps: true
                },
                {
                    label: 'Durchschnitt Innen',
                    data: data.indoor_temp,
                    borderColor: '#3b82f6',
                    backgroundColor: 'rgba(59, 130, 246, 0.1)',
                    borderWidth: 2,
                    tension: 0.4,
                    fill: true,
                    spanGaps: true
                },
                {
                    label: 'Zieltemperatur',
                    data: data.target_temp,
                    borderColor: '#10b981',
                    backgroundColor: 'rgba(16, 185, 129, 0.1)',
                    borderWidth: 2,
                    borderDash: [5, 5],
                    tension: 0.4,
                    fill: false,
                    spanGaps: true
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: {
                mode: 'index',
                intersect: false,
            },
            plugins: {
                legend: {
                    display: true,
                    position: 'top',
                },
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            let label = context.dataset.label || '';
                            if (label) {
                                label += ': ';
                            }
                            if (context.parsed.y !== null) {
                                label += context.parsed.y.toFixed(1) + '°C';
                            }
                            return label;
                        }
                    }
                }
            },
            scales: {
                y: {
                    beginAtZero: false,
                    ticks: {
                        callback: function(value) {
                            return value + '°C';
                        }
                    },
                    grid: {
                        color: 'rgba(0, 0, 0, 0.05)'
                    }
                },
                x: {
                    grid: {
                        display: false
                    },
                    ticks: {
                        maxRotation: 45,
                        minRotation: 45
                    }
                }
            }
        }
    });
}

// Fülle Raum-Filter aus
function populateRoomFilter() {
    const roomFilter = document.getElementById('room-filter');
    if (!roomFilter) return;

    const rooms = [...new Set(allHeaters.map(h => h.zoneName))].sort();

    roomFilter.innerHTML = '<option value="all">Alle Räume</option>';
    rooms.forEach(room => {
        const option = document.createElement('option');
        option.value = room;
        option.textContent = room;
        roomFilter.appendChild(option);
    });
}

// Filtere Heizgeräte
function getFilteredHeaters() {
    let filtered = allHeaters;

    // Filter nach Status
    if (currentFilter === 'active') {
        filtered = filtered.filter(h => isHeaterActive(h));
    } else if (currentFilter === 'inactive') {
        filtered = filtered.filter(h => !isHeaterActive(h));
    }

    // Filter nach Raum
    if (currentRoomFilter !== 'all') {
        filtered = filtered.filter(h => h.zoneName === currentRoomFilter);
    }

    return filtered;
}

// Rendere Heizgeräte
function renderHeaters() {
    const container = document.getElementById('heaters-container');
    const filtered = getFilteredHeaters();

    if (filtered.length === 0) {
        container.innerHTML = '<div class="info-box">Keine Heizgeräte gefunden.</div>';
        return;
    }

    container.innerHTML = filtered.map(heater => createHeaterCard(heater)).join('');

    // Event Listener für Karten
    container.querySelectorAll('.heater-card').forEach(card => {
        card.addEventListener('click', () => {
            const heaterId = card.dataset.heaterId;
            const heater = allHeaters.find(h => getHeaterId(h) === heaterId);
            if (heater) {
                openHeaterModal(heater);
            }
        });
    });
}

// Erstelle Heizgeräte-Karte
function createHeaterCard(heater) {
    const isActive = isHeaterActive(heater);
    const currentTemp = getCurrentTemp(heater);
    const targetTemp = getTargetTemp(heater);
    const heaterId = getHeaterId(heater);

    return `
        <div class="heater-card ${isActive ? 'active' : ''}" data-heater-id="${heaterId}">
            <div class="heater-header">
                <div class="heater-name">${heater.name || heater.id}</div>
                <div class="heater-status">
                    ${isActive ? '🔥 Aktiv' : '⏸️ Inaktiv'}
                </div>
            </div>

            <div class="heater-temps">
                <div class="temp-display">
                    <div class="temp-label">Aktuell</div>
                    <div class="temp-value">${currentTemp !== null ? currentTemp.toFixed(1) : '--'}°C</div>
                </div>
                <div class="temp-display">
                    <div class="temp-label">Ziel</div>
                    <div class="temp-value">${targetTemp !== null ? targetTemp.toFixed(1) : '--'}°C</div>
                </div>
            </div>

            <div class="heater-room">
                <span>🏠</span>
                <span>${heater.zoneName}</span>
            </div>
        </div>
    `;
}

// Öffne Heizgeräte-Info-Modal (nur Anzeige, keine Steuerung)
function openHeaterModal(heater) {
    const modal = document.getElementById('heater-modal');
    const currentTemp = getCurrentTemp(heater);
    const targetTemp = getTargetTemp(heater);
    const isActive = isHeaterActive(heater);

    document.getElementById('modal-heater-name').textContent = heater.name || heater.id;
    document.getElementById('modal-heater-room').textContent = '🏠 ' + heater.zoneName;
    document.getElementById('modal-current-temp').textContent =
        currentTemp !== null ? currentTemp.toFixed(1) + '°C' : '--';
    document.getElementById('modal-target-temp').textContent =
        targetTemp !== null ? targetTemp.toFixed(1) + '°C' : '--';
    document.getElementById('modal-heater-status').textContent = isActive ? '🔥 Aktiv' : '⏸️ Inaktiv';

    modal.style.display = 'block';
}

// Hilfsfunktionen für Heizgeräte-Daten
function getHeaterId(heater) {
    return heater.entity_id || heater.id;
}

function getCurrentTemp(heater) {
    // Direkt auf oberster Ebene (von verbesserter API)
    if (heater.current_temperature !== undefined && heater.current_temperature !== null) {
        return heater.current_temperature;
    }
    // In attributes (Home Assistant Format)
    if (heater.attributes?.current_temperature !== undefined) {
        return heater.attributes.current_temperature;
    }
    // In state Objekt
    if (heater.state?.current_temperature !== undefined) {
        return heater.state.current_temperature;
    }
    // Direkt in capabilitiesObj (Homey Format)
    if (heater.capabilitiesObj?.measure_temperature?.value !== undefined) {
        return heater.capabilitiesObj.measure_temperature.value;
    }
    // Als Fallback: state Wert wenn es eine Zahl ist
    const stateValue = parseFloat(heater.state);
    if (!isNaN(stateValue)) {
        return stateValue;
    }
    return null;
}

function getTargetTemp(heater) {
    // Direkt auf oberster Ebene (von verbesserter API)
    if (heater.target_temperature !== undefined && heater.target_temperature !== null) {
        return heater.target_temperature;
    }
    // In attributes.temperature (Home Assistant Format)
    if (heater.attributes?.temperature !== undefined) {
        return heater.attributes.temperature;
    }
    // In state.target_temperature
    if (heater.state?.target_temperature !== undefined) {
        return heater.state.target_temperature;
    }
    // Direkt in capabilitiesObj (Homey Format)
    if (heater.capabilitiesObj?.target_temperature?.value !== undefined) {
        return heater.capabilitiesObj.target_temperature.value;
    }
    return null;
}

function isHeaterActive(heater) {
    const state = heater.state?.state || heater.state;
    if (state === 'heat' || state === 'heating') return true;

    const targetTemp = getTargetTemp(heater);
    const currentTemp = getCurrentTemp(heater);

    if (targetTemp !== null && currentTemp !== null) {
        return targetTemp > currentTemp + 0.5; // 0.5°C Hysterese
    }

    return false;
}

// Setze Temperatur für alle Heizgeräte
async function setAllHeaters(temperature) {
    const resultDiv = document.getElementById('quick-action-result');
    resultDiv.innerHTML = '<div class="loading">Setze Temperatur für alle Heizgeräte...</div>';

    let success = 0;
    let failed = 0;

    for (const heater of allHeaters) {
        try {
            await setHeaterTemperature(heater, temperature);
            success++;
        } catch (error) {
            console.error('Failed to set temperature for', heater.name, error);
            failed++;
        }
    }

    resultDiv.innerHTML = `
        <div class="success">
            ✓ ${success} Heizgeräte auf ${temperature}°C gesetzt
            ${failed > 0 ? `<br>⚠ ${failed} fehlgeschlagen` : ''}
        </div>
    `;

    setTimeout(() => {
        resultDiv.innerHTML = '';
        loadHeaters();
    }, 3000);
}

// Schalte alle Heizgeräte aus
async function turnAllHeatersOff() {
    if (!confirm('Wirklich alle Heizgeräte ausschalten?')) return;

    const resultDiv = document.getElementById('quick-action-result');
    resultDiv.innerHTML = '<div class="loading">Schalte alle Heizgeräte aus...</div>';

    let success = 0;
    let failed = 0;

    for (const heater of allHeaters) {
        try {
            await turnHeaterOff(heater);
            success++;
        } catch (error) {
            console.error('Failed to turn off', heater.name, error);
            failed++;
        }
    }

    resultDiv.innerHTML = `
        <div class="success">
            ✓ ${success} Heizgeräte ausgeschaltet
            ${failed > 0 ? `<br>⚠ ${failed} fehlgeschlagen` : ''}
        </div>
    `;

    setTimeout(() => {
        resultDiv.innerHTML = '';
        loadHeaters();
    }, 3000);
}

// Setze Temperatur für ein Heizgerät
async function setHeaterTemperature(heater, temperature) {
    const heaterId = getHeaterId(heater);

    try {
        const response = await fetch('/api/devices/control', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                entity_id: heaterId,
                action: 'set_temperature',
                temperature: temperature
            })
        });

        if (!response.ok) throw new Error('Failed to set temperature');

        const result = document.getElementById('modal-action-result');
        if (result) {
            result.innerHTML = `<div class="success">✓ Temperatur auf ${temperature}°C gesetzt</div>`;
            setTimeout(() => {
                result.innerHTML = '';
                document.getElementById('heater-modal').style.display = 'none';
                loadHeaters();
            }, 2000);
        }
    } catch (error) {
        console.error('Error setting temperature:', error);
        const result = document.getElementById('modal-action-result');
        if (result) {
            result.innerHTML = '<div class="error">✗ Fehler beim Setzen der Temperatur</div>';
        }
        throw error;
    }
}

// Schalte Heizgerät aus
async function turnHeaterOff(heater) {
    const heaterId = getHeaterId(heater);

    try {
        const response = await fetch('/api/devices/control', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                entity_id: heaterId,
                action: 'turn_off'
            })
        });

        if (!response.ok) throw new Error('Failed to turn off heater');

        const result = document.getElementById('modal-action-result');
        if (result) {
            result.innerHTML = '<div class="success">✓ Heizgerät ausgeschaltet</div>';
            setTimeout(() => {
                result.innerHTML = '';
                document.getElementById('heater-modal').style.display = 'none';
                loadHeaters();
            }, 2000);
        }
    } catch (error) {
        console.error('Error turning off heater:', error);
        const result = document.getElementById('modal-action-result');
        if (result) {
            result.innerHTML = '<div class="error">✗ Fehler beim Ausschalten</div>';
        }
        throw error;
    }
}

// Speichere Einstellungen
async function saveSettings() {
    const resultDiv = document.getElementById('save-result');
    resultDiv.innerHTML = '<div class="loading">Speichere Einstellungen...</div>';

    const settings = {
        default_comfort_temp: parseFloat(document.getElementById('default-comfort-temp').value),
        default_eco_temp: parseFloat(document.getElementById('default-eco-temp').value),
        default_night_temp: parseFloat(document.getElementById('default-night-temp').value),
        default_frost_temp: parseFloat(document.getElementById('default-frost-temp').value),
        auto_heating: document.getElementById('auto-heating').checked,
        window_detection: document.getElementById('window-detection').checked,
        presence_based: document.getElementById('presence-based').checked,
        energy_price_optimization: document.getElementById('energy-price-optimization').checked
    };

    try {
        const response = await fetch('/api/heating/settings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(settings)
        });

        if (!response.ok) throw new Error('Failed to save settings');

        resultDiv.innerHTML = '<div class="success">✓ Einstellungen gespeichert</div>';
        setTimeout(() => resultDiv.innerHTML = '', 3000);
    } catch (error) {
        console.error('Error saving settings:', error);
        resultDiv.innerHTML = '<div class="error">✗ Fehler beim Speichern der Einstellungen</div>';
    }
}

// === HEIZUNGS-OPTIMIERUNG FUNKTIONEN ===

// Lade aktuellen Heizungs-Modus
async function loadHeatingMode() {
    try {
        const data = await fetchJSON('/api/heating/mode');
        currentMode = data.mode || 'control';
        updateModeUI(currentMode);
    } catch (error) {
        console.error('Error loading heating mode:', error);
        currentMode = 'control';
        updateModeUI(currentMode);
    }
}

// Wechsle zwischen Control und Optimization Modus
async function switchMode(newMode) {
    try {
        const response = await fetch('/api/heating/mode', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ mode: newMode })
        });

        if (!response.ok) throw new Error('Failed to switch mode');

        const data = await response.json();
        currentMode = data.mode;
        updateModeUI(currentMode);

        // Lade relevante Daten für den neuen Modus
        if (currentMode === 'optimization') {
            loadOptimizationData();
        }

        console.log('Switched to mode:', currentMode);
    } catch (error) {
        console.error('Error switching mode:', error);
        alert('Fehler beim Wechseln des Modus');
    }
}

// Update UI basierend auf Modus
function updateModeUI(mode) {
    // Zeige/verstecke Modi-spezifische Elemente
    if (mode === 'control') {
        // Steuerungs-Elemente zeigen
        document.querySelectorAll('.mode-control-only').forEach(el => {
            el.style.display = 'block';
        });
        document.querySelectorAll('.mode-monitoring-only').forEach(el => {
            el.style.display = 'none';
        });
        document.getElementById('mode-subtitle').textContent = 'Zentrale Steuerung aller Heizgeräte und Thermostate';
    } else {
        // Monitoring-Elemente zeigen
        document.querySelectorAll('.mode-control-only').forEach(el => {
            el.style.display = 'none';
        });
        document.querySelectorAll('.mode-monitoring-only').forEach(el => {
            el.style.display = 'block';
        });
        document.getElementById('mode-subtitle').textContent = 'KI-Analyse und Optimierungsvorschläge für Tado X';
    }
}

// Lade Optimierungsdaten (Insights, Muster, etc.)
async function loadOptimizationData() {
    try {
        // Lade Insights
        let insights = [];
        try {
            const insightsResponse = await fetchJSON('/api/heating/insights');
            insights = insightsResponse.insights || [];
        } catch (e) {
            console.warn('Could not load heating insights:', e.message);
        }
        renderInsights(insights);

        // Lade Statistiken
        let stats = {};
        try {
            stats = await fetchJSON('/api/heating/statistics');
            console.log('Heating statistics loaded:', stats);
        } catch (e) {
            console.warn('Could not load heating statistics:', e.message);
        }
        
        if (stats.success) {
            renderStatistics(stats);
        } else {
            console.warn('Heating statistics returned success=false or empty');
            renderStatistics({});
        }

        console.log('Optimization data loaded successfully');
    } catch (error) {
        console.error('Error loading optimization data:', error);
        // Zeige Fehler-Status an
        const observationsEl = document.getElementById('monitoring-observations-count');
        if (observationsEl) observationsEl.textContent = 'Fehler';
        const dataDaysEl = document.getElementById('monitoring-data-days');
        if (dataDaysEl) dataDaysEl.textContent = 'Fehler';
    }
}

// Rendere KI-Insights
function renderInsights(insights) {
    const container = document.querySelector('.recommendations-grid');
    if (!container) return;

    // Update Insights-Zähler
    const insightsCount = insights.length;
    const insightsCountEl = document.getElementById('monitoring-insights-count');
    if (insightsCountEl) {
        insightsCountEl.textContent = insightsCount;
    }

    if (insights.length === 0) {
        container.innerHTML = `
            <div class="info-box" style="grid-column: 1 / -1;">
                <strong>ℹ️ Hinweis:</strong> Noch nicht genug Daten für Optimierungsvorschläge.
                <br>Das System sammelt aktuell Daten über dein Heizverhalten.
                <br>Komme in ein paar Tagen wieder, um personalisierte Vorschläge zu erhalten.
            </div>
        `;
        return;
    }

    container.innerHTML = insights.map(insight => createInsightCard(insight)).join('');
}

// Erstelle Insight-Karte
function createInsightCard(insight) {
    const typeClasses = {
        'night_reduction': 'energy',
        'window_warning': 'comfort',
        'temperature_optimization': 'weather',
        'weekend_optimization': 'timing'
    };

    const cardClass = typeClasses[insight.insight_type] || 'energy';

    return `
        <div class="recommendation-card ${cardClass}">
            <div class="recommendation-icon">${insight.icon || '💡'}</div>
            <div class="recommendation-content">
                <h4>${insight.title || insight.insight_type}</h4>
                <p class="recommendation-value">
                    ${insight.potential_saving_percent ? `~${insight.potential_saving_percent}%` : 'Optimierung'}
                </p>
                <p class="recommendation-text">${insight.recommendation}</p>
                ${insight.potential_saving_eur ?
                    `<small style="color: #10b981; font-weight: 600;">Sparpotenzial: ~${insight.potential_saving_eur}€/Monat</small>` :
                    ''}
            </div>
        </div>
    `;
}

// Rendere Statistiken
function renderStatistics(stats) {
    console.log('Rendering statistics:', stats);
    
    // Update Temperatur-Stats wenn vorhanden
    if (stats.avg_temp) {
        const avgTemp = parseFloat(stats.avg_temp).toFixed(1);
        const avgTempEl = document.getElementById('avg-temp');
        if (avgTempEl) {
            avgTempEl.textContent = avgTemp + '°C';
        }
    }

    // Update Heiz-Stats
    if (stats.heating_percent !== undefined) {
        console.log('Heating active:', stats.heating_percent + '%');
    }

    // Update Monitoring-Status
    // Beobachtungen
    const observationsCount = stats.total_observations || 0;
    const observationsEl = document.getElementById('monitoring-observations-count');
    if (observationsEl) {
        observationsEl.textContent = observationsCount > 0 ? observationsCount.toLocaleString() : '--';
    }

    // Daten-Zeitraum
    const dataDays = stats.period_days || 0;
    const dataDaysEl = document.getElementById('monitoring-data-days');
    if (dataDaysEl) {
        dataDaysEl.textContent = dataDays > 0 ? dataDays + ' Tage' : '-- Tage';
    }
    
    // Auch avg_temp in stats.temperatures Format unterstützen (für Kompatibilität)
    if (stats.temperatures && stats.temperatures.avg_indoor) {
        const avgIndoor = stats.temperatures.avg_indoor;
        const avgTempEl = document.getElementById('avg-temp');
        if (avgTempEl) {
            avgTempEl.textContent = avgIndoor + '°C';
        }
    }
}

// === HEIZUNGS-ANALYTICS FUNKTIONEN ===

let heatingTimesChart = null;
let roomComparisonChart = null;
let weatherCorrelationChart = null;

// Lade Heizungs-Analytics
async function loadHeatingAnalytics() {
    const timeframeSelect = document.getElementById('analytics-timeframe');
    if (!timeframeSelect) return;

    const days = parseInt(timeframeSelect.value) || 14;

    try {
        const data = await fetchJSON(`/api/heating/analytics?days=${days}`);

        if (data.sufficient_data) {
            // Rendere alle Analytics - mit Try-Catch für jeden Teil
            try { renderCostEstimates(data.cost_estimates); } catch (e) { console.warn('Error rendering cost estimates:', e); }
            try { renderHeatingTimes(data.heating_times); } catch (e) { console.warn('Error rendering heating times:', e); }
            try { renderTemperatureEfficiency(data.temperature_efficiency); } catch (e) { console.warn('Error rendering temperature efficiency:', e); }
            try { renderRoomComparison(data.room_comparison); } catch (e) { console.warn('Error rendering room comparison:', e); }
            try { renderWeatherCorrelation(data.weather_correlation); } catch (e) { console.warn('Error rendering weather correlation:', e); }

            // Zeige Analytics-Section
            document.querySelector('.heating-analytics-card')?.classList.remove('hidden');
        } else {
            // Zeige Info-Nachricht
            console.log('Nicht genug Daten für Analytics');
        }
    } catch (error) {
        console.error('Error loading heating analytics:', error);
    }
}

// Rendere Kosten-Schätzungen
function renderCostEstimates(costData) {
    if (!costData) return;

    const costDaily = document.getElementById('cost-daily');
    const costMonthly = document.getElementById('cost-monthly');
    const costYearly = document.getElementById('cost-yearly');
    const heatingHours = document.getElementById('heating-hours-per-day');

    if (costDaily) costDaily.textContent = (costData.daily_cost || 0).toFixed(2) + '€';
    if (costMonthly) costMonthly.textContent = (costData.monthly_cost || 0).toFixed(2) + '€';
    if (costYearly) costYearly.textContent = (costData.yearly_cost || 0).toFixed(0) + '€';
    if (heatingHours) heatingHours.textContent = (costData.total_heating_hours || 0).toFixed(1) + 'h';
}

// Rendere Heizzeiten-Chart
function renderHeatingTimes(heatingTimesData) {
    if (!heatingTimesData || !heatingTimesData.hourly_breakdown) return;

    const ctx = document.getElementById('heating-times-chart');
    if (!ctx) return;

    // Zerstöre existierenden Chart
    if (heatingTimesChart) {
        heatingTimesChart.destroy();
    }

    const hours = Array.from({ length: 24 }, (_, i) => i);
    const percentages = hours.map(h => heatingTimesData.hourly_breakdown[h] || 0);

    heatingTimesChart = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: hours.map(h => h + ':00'),
            datasets: [{
                label: 'Heizaktivität (%)',
                data: percentages,
                backgroundColor: percentages.map(p => {
                    if (p > 70) return '#ef4444'; // Hoch - Rot
                    if (p > 40) return '#f59e0b'; // Mittel - Orange
                    return '#10b981'; // Niedrig - Grün
                }),
                borderColor: '#1f2937',
                borderWidth: 1
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
                tooltip: {
                    callbacks: {
                        label: (context) => `${context.parsed.y.toFixed(1)}% der Zeit aktiv`
                    }
                }
            },
            scales: {
                y: {
                    beginAtZero: true,
                    max: 100,
                    title: { display: true, text: 'Heizaktivität (%)' }
                },
                x: {
                    title: { display: true, text: 'Uhrzeit' }
                }
            }
        }
    });

    // Zeige Peak-Zeiten
    if (heatingTimesData.peak_hours && heatingTimesData.peak_hours.length > 0) {
        const peakHoursText = heatingTimesData.peak_hours.join(', ');
        console.log('Peak Heizzeiten:', peakHoursText);
    }
}

// Rendere Temperatur-Effizienz
function renderTemperatureEfficiency(efficiencyData) {
    if (!efficiencyData) return;

    const score = efficiencyData.efficiency_score || 0;
    const scoreText = document.getElementById('efficiency-score-text');
    const scoreCircle = document.getElementById('efficiency-score-circle');

    if (scoreText) {
        scoreText.textContent = score.toFixed(0);
    }

    if (scoreCircle) {
        // Animiere den Kreis (314 = Umfang bei r=50)
        const circumference = 314;
        const offset = circumference - (score / 100) * circumference;
        scoreCircle.style.strokeDashoffset = offset;

        // Farbe basierend auf Score
        let color = '#10b981'; // Grün
        if (score < 60) color = '#f59e0b'; // Orange
        if (score < 40) color = '#ef4444'; // Rot
        scoreCircle.setAttribute('stroke', color);
    }

    // Zeige Details
    const avgDiff = efficiencyData.avg_temp_difference || 0;
    const efficiencyDetails = document.getElementById('efficiency-details');
    if (efficiencyDetails) {
        efficiencyDetails.innerHTML = `
            <div class="efficiency-detail">
                <span class="label">Ø Zieltemperatur:</span>
                <span class="value">${(efficiencyData.avg_target_temp || 0).toFixed(1)}°C</span>
            </div>
            <div class="efficiency-detail">
                <span class="label">Ø Ist-Temperatur:</span>
                <span class="value">${(efficiencyData.avg_actual_temp || 0).toFixed(1)}°C</span>
            </div>
            <div class="efficiency-detail">
                <span class="label">Ø Differenz:</span>
                <span class="value">${avgDiff.toFixed(1)}°C</span>
            </div>
        `;
    }
}

// Rendere Raum-Vergleich
function renderRoomComparison(roomData) {
    // Handle both array and object with 'rooms' property
    const roomsArray = Array.isArray(roomData) ? roomData : (roomData?.rooms || []);
    if (!roomsArray || roomsArray.length === 0) return;

    const ctx = document.getElementById('room-comparison-chart');
    if (!ctx) return;

    // Zerstöre existierenden Chart
    if (roomComparisonChart) {
        roomComparisonChart.destroy();
    }

    const rooms = roomsArray.map(r => r.room || r.room_name);
    const heatingPercent = roomsArray.map(r => r.heating_percentage || r.heating_percent || 0);
    const avgTemp = roomsArray.map(r => r.avg_temperature || r.avg_temp || 0);

    roomComparisonChart = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: rooms,
            datasets: [
                {
                    label: 'Heizaktivität (%)',
                    data: heatingPercent,
                    backgroundColor: 'rgba(239, 68, 68, 0.6)',
                    borderColor: '#ef4444',
                    borderWidth: 1,
                    yAxisID: 'y-percent'
                },
                {
                    label: 'Ø Temperatur (°C)',
                    data: avgTemp,
                    backgroundColor: 'rgba(59, 130, 246, 0.6)',
                    borderColor: '#3b82f6',
                    borderWidth: 1,
                    yAxisID: 'y-temp'
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: true, position: 'top' }
            },
            scales: {
                'y-percent': {
                    type: 'linear',
                    position: 'left',
                    beginAtZero: true,
                    max: 100,
                    title: { display: true, text: 'Heizaktivität (%)' }
                },
                'y-temp': {
                    type: 'linear',
                    position: 'right',
                    beginAtZero: false,
                    title: { display: true, text: 'Temperatur (°C)' },
                    grid: { drawOnChartArea: false }
                }
            }
        }
    });
}

// Rendere Wetter-Korrelation
function renderWeatherCorrelation(weatherData) {
    // Handle both array and object with 'correlation_data' property
    const dataArray = Array.isArray(weatherData) ? weatherData : (weatherData?.correlation_data || []);
    if (!dataArray || dataArray.length === 0) return;

    const ctx = document.getElementById('weather-correlation-chart');
    if (!ctx) return;

    // Zerstöre existierenden Chart
    if (weatherCorrelationChart) {
        weatherCorrelationChart.destroy();
    }

    // Support both old and new field names
    const labels = dataArray.map(w => w.temp_range || w.range || 'Unbekannt');
    const heatingPercent = dataArray.map(w => w.heating_percent ?? w.heating_percentage ?? 0);

    // Farben basierend auf Temperatur-Bereich
    const colors = dataArray.map(w => {
        const rangeStr = w.temp_range || w.range || '';
        const temp = parseFloat(rangeStr.replace(/[^\d-]/g, '').split('-')[0]) || 0; // Nimm untere Grenze
        if (temp < 0 || rangeStr.toLowerCase().includes('unter')) return '#3b82f6'; // Blau (kalt)
        if (temp < 10) return '#10b981'; // Grün (kühl)
        if (temp < 15) return '#f59e0b'; // Orange (mild)
        return '#ef4444'; // Rot (warm)
    });

    weatherCorrelationChart = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: labels,
            datasets: [{
                label: 'Heizaktivität (%)',
                data: heatingPercent,
                backgroundColor: colors,
                borderColor: '#1f2937',
                borderWidth: 1
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
                tooltip: {
                    callbacks: {
                        label: (context) => {
                            const dataPoint = dataArray[context.dataIndex];
                            const avgTemp = dataPoint?.avg_outdoor_temp ?? dataPoint?.avg_outdoor ?? null;
                            const lines = [`Heizaktivität: ${context.parsed.y.toFixed(1)}%`];
                            if (avgTemp !== null) {
                                lines.push(`Ø Außentemp: ${avgTemp.toFixed(1)}°C`);
                            }
                            return lines;
                        }
                    }
                }
            },
            scales: {
                y: {
                    beginAtZero: true,
                    max: 100,
                    title: { display: true, text: 'Heizaktivität (%)' }
                },
                x: {
                    title: { display: true, text: 'Außentemperatur-Bereich (°C)' }
                }
            }
        }
    });
}

// Hilfsfunktion für API-Aufrufe
async function fetchJSON(url) {
    const response = await fetch(url);
    if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
    return await response.json();
}

// ===== FENSTER-STATUS FUNKTIONEN =====

/**
 * Lädt und zeigt ALLE Fenster mit ihrem aktuellen Status
 * (respektiert versteckte Räume aus zentraler /rooms Konfiguration)
 */
async function loadAllWindowStatuses() {
    try {
        const response = await fetchJSON('/api/heating/windows/all');

        const container = document.getElementById('all-windows-container');

        if (!response.data || response.data.length === 0) {
            container.innerHTML = `
                <div style="text-align: center; padding: 20px; background: #f3f4f6; border-radius: 8px;">
                    <div style="font-size: 2em; margin-bottom: 10px;">🪟</div>
                    <p style="margin: 0; color: #6b7280;">Keine Fenster-Sensoren gefunden</p>
                </div>
            `;
            return;
        }

        // Filtere Fenster aus versteckten Räumen
        let windowData = response.data;
        if (hiddenRooms.length > 0) {
            windowData = windowData.filter(w => !hiddenRooms.includes(w.room_name));
        }

        if (windowData.length === 0) {
            container.innerHTML = `
                <div style="text-align: center; padding: 20px; background: #f3f4f6; border-radius: 8px;">
                    <div style="font-size: 2em; margin-bottom: 10px;">🪟</div>
                    <p style="margin: 0; color: #6b7280;">Keine Fenster-Sensoren in sichtbaren Räumen</p>
                </div>
            `;
            return;
        }

        // Zähle offene Fenster
        const openWindows = windowData.filter(w => w.is_open);
        const closedWindows = windowData.filter(w => !w.is_open);

        // Header mit Zusammenfassung
        let headerHTML = '';
        if (openWindows.length > 0) {
            headerHTML = `
                <div style="margin-bottom: 15px; padding: 12px; background: #fef3c7; border-radius: 8px; border-left: 4px solid #f59e0b;">
                    <div style="display: flex; align-items: center; gap: 10px;">
                        <span style="font-size: 1.5em;">⚠️</span>
                        <div>
                            <strong style="color: #92400e;">${openWindows.length} Fenster offen</strong>
                            <div style="font-size: 0.85em; color: #6b7280; margin-top: 3px;">
                                Heizleistung kann beeinträchtigt sein
                            </div>
                        </div>
                    </div>
                </div>
            `;
        } else {
            headerHTML = `
                <div style="margin-bottom: 15px; padding: 12px; background: #f0fdf4; border-radius: 8px; border-left: 4px solid #10b981;">
                    <div style="display: flex; align-items: center; gap: 10px;">
                        <span style="font-size: 1.5em;">✅</span>
                        <div>
                            <strong style="color: #065f46;">Alle Fenster geschlossen</strong>
                            <div style="font-size: 0.85em; color: #6b7280; margin-top: 3px;">
                                Optimale Bedingungen für Heizung
                            </div>
                        </div>
                    </div>
                </div>
            `;
        }

        // Gruppiere Fenster nach Raum
        const windowsByRoom = {};
        windowData.forEach(w => {
            const room = w.room_name || 'Unbekannt';
            if (!windowsByRoom[room]) windowsByRoom[room] = [];
            windowsByRoom[room].push(w);
        });

        // Generiere HTML für Räume
        const roomsHTML = Object.keys(windowsByRoom).sort().map(room => {
            const windows = windowsByRoom[room];
            const openWindowsInRoom = windows.filter(w => w.is_open);
            const isRoomOpen = openWindowsInRoom.length > 0;
            
            const icon = isRoomOpen ? '🔴' : '🟢';
            const statusText = isRoomOpen ? '⚠️ Geöffnet' : '✓ Geschlossen';
            const bgColor = isRoomOpen ? '#fef3c7' : '#f0fdf4';
            const borderColor = isRoomOpen ? '#f59e0b' : '#10b981';
            const textColor = isRoomOpen ? '#92400e' : '#065f46';
            
            // Details für Tooltip/Expand
            const details = windows.map(w => 
                `<div style="display:flex; justify-content:space-between; font-size:0.8em; margin-top:4px; color:#555;">
                    <span>${w.device_name}</span>
                    <span>${w.is_open ? '🔴' : '🟢'}</span>
                 </div>`
            ).join('');

            return `
                <div style="padding: 15px; background: ${bgColor}; border-radius: 8px; border: 1px solid ${borderColor};">
                    <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 8px;">
                        <span style="font-size: 1.5em;">${icon}</span>
                        <div style="flex: 1;">
                            <div style="font-weight: 600; color: #1f2937;">${room}</div>
                            <div style="font-size: 0.85em; color: ${textColor}; font-weight: 600;">
                                ${statusText} <span style="font-weight:normal; color:#666;">(${windows.length} Sensoren)</span>
                            </div>
                        </div>
                    </div>
                    <div style="border-top: 1px solid rgba(0,0,0,0.05); margin-top: 8px; padding-top: 8px;">
                        ${details}
                    </div>
                </div>
            `;
        }).join('');

        container.innerHTML = `
            ${headerHTML}
            <div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 12px;">
                ${roomsHTML}
            </div>
        `;

    } catch (error) {
        console.error('Error loading all window statuses:', error);
        document.getElementById('all-windows-container').innerHTML = `
            <div class="error" style="padding: 15px; background: #fee2e2; border-radius: 8px; color: #991b1b;">
                ❌ Fehler beim Laden der Fensterdaten: ${error.message}
            </div>
        `;
    }
}

/**
 * Lädt und zeigt aktuell geöffnete Fenster (Legacy - nicht mehr genutzt)
 */
async function loadCurrentOpenWindows() {
    try {
        const response = await fetchJSON('/api/heating/windows/current');

        const container = document.getElementById('open-windows-container');

        if (!response.data || response.data.length === 0) {
            container.innerHTML = `
                <div style="text-align: center; padding: 20px; background: #f0fdf4; border-radius: 8px; border: 1px solid #d1fae5;">
                    <div style="font-size: 2em; margin-bottom: 10px;">✅</div>
                    <p style="margin: 0; color: #065f46; font-weight: 600;">Alle Fenster geschlossen</p>
                    <p style="margin: 5px 0 0 0; color: #6b7280; font-size: 0.9em;">Optimale Bedingungen für Heizung</p>
                </div>
            `;
            return;
        }

        // Zeige geöffnete Fenster
        const openWindowsHTML = response.data.map(window => {
            const minutesOpen = window.minutes_open;
            const hoursOpen = Math.floor(minutesOpen / 60);
            const remainingMinutes = minutesOpen % 60;

            let durationText = '';
            if (hoursOpen > 0) {
                durationText = `${hoursOpen}h ${remainingMinutes}min`;
            } else {
                durationText = `${remainingMinutes} min`;
            }

            // Warnung bei langer Öffnung
            const isLongOpen = minutesOpen > 15;
            const bgColor = isLongOpen ? '#fef3c7' : '#fef9c3';
            const borderColor = isLongOpen ? '#f59e0b' : '#eab308';
            const iconColor = isLongOpen ? '#92400e' : '#854d0e';

            return `
                <div style="display: flex; align-items: center; gap: 15px; padding: 15px; background: ${bgColor}; border-radius: 8px; border: 1px solid ${borderColor}; margin-bottom: 10px;">
                    <div style="font-size: 2em;">🪟</div>
                    <div style="flex: 1;">
                        <div style="font-weight: 700; color: ${iconColor};">${window.device_name}</div>
                        <div style="font-size: 0.85em; color: #6b7280;">${window.room_name || 'Unbekannter Raum'}</div>
                    </div>
                    <div style="text-align: right;">
                        <div style="font-size: 1.5em; font-weight: 700; color: ${iconColor};">${durationText}</div>
                        <div style="font-size: 0.75em; color: #6b7280;">offen seit</div>
                    </div>
                </div>
            `;
        }).join('');

        container.innerHTML = `
            <div style="margin-bottom: 10px; padding: 12px; background: #fef3c7; border-radius: 8px; border-left: 4px solid #f59e0b;">
                <div style="display: flex; align-items: center; gap: 10px;">
                    <span style="font-size: 1.5em;">⚠️</span>
                    <div>
                        <strong style="color: #92400e;">${response.data.length} Fenster offen</strong>
                        <div style="font-size: 0.85em; color: #6b7280; margin-top: 3px;">
                            Heizleistung kann beeinträchtigt sein
                        </div>
                    </div>
                </div>
            </div>
            ${openWindowsHTML}
        `;

    } catch (error) {
        console.error('Error loading open windows:', error);
        document.getElementById('open-windows-container').innerHTML = `
            <div class="error" style="padding: 15px; background: #fee2e2; border-radius: 8px; color: #991b1b;">
                ❌ Fehler beim Laden der Fensterdaten: ${error.message}
            </div>
        `;
    }
}

/**
 * Lädt und zeigt Fenster-Öffnungsstatistik
 */
async function loadWindowStatistics() {
    try {
        // Zeige Loading
        const loadingEl = document.getElementById('window-charts-loading');
        const noDataEl = document.getElementById('window-charts-no-data');
        const statsContainer = document.getElementById('window-room-stats');

        if (loadingEl) loadingEl.style.display = 'block';
        if (noDataEl) noDataEl.style.display = 'none';
        if (statsContainer) statsContainer.innerHTML = '';

        // Hole ausgewählten Zeitraum
        const timeframeSelect = document.getElementById('window-stats-timeframe');
        const days = timeframeSelect ? parseInt(timeframeSelect.value) : 7;

        // Lade Chart-Daten
        const response = await fetchJSON(`/api/heating/windows/charts?days=${days}`);

        // Verstecke Loading
        if (loadingEl) loadingEl.style.display = 'none';

        if (!response.data || !response.data.frequency_by_window) {
            if (noDataEl) noDataEl.style.display = 'block';
            return;
        }

        const frequencyData = response.data.frequency_by_window;

        // Prüfe ob Daten vorhanden sind
        if (!frequencyData || frequencyData.length === 0) {
            if (noDataEl) noDataEl.style.display = 'block';
            return;
        }

        // Gruppiere nach Raum
        const roomStats = {};
        frequencyData.forEach(window => {
            const roomName = window.room_name || 'Unbekannt';
            if (!roomStats[roomName]) {
                roomStats[roomName] = {
                    room: roomName,
                    total_openings: 0,
                    windows: []
                };
            }
            roomStats[roomName].total_openings += window.open_count;
            roomStats[roomName].windows.push(window);
        });

        // Rendere Raum-Karten
        renderRoomStats(Object.values(roomStats), statsContainer);

    } catch (error) {
        console.error('Error loading window statistics:', error);
        const loadingEl = document.getElementById('window-charts-loading');
        if (loadingEl) {
            loadingEl.style.display = 'block';
            loadingEl.innerHTML = `
                <div style="padding: 15px; background: #fee2e2; border-radius: 8px; color: #991b1b;">
                    ❌ Fehler beim Laden der Statistiken: ${error.message}
                </div>
            `;
        }
    }
}

/**
 * Rendert Raum-Statistik-Karten
 */
function renderRoomStats(roomStats, container) {
    if (!container) return;

    // Sortiere nach Anzahl der Öffnungen (absteigend)
    const sortedRooms = [...roomStats].sort((a, b) => b.total_openings - a.total_openings);

    // Erstelle Karten
    container.innerHTML = sortedRooms.map(room => {
        // Berechne Durchschnitt pro Tag
        const timeframeSelect = document.getElementById('window-stats-timeframe');
        const days = timeframeSelect ? parseInt(timeframeSelect.value) : 7;
        const avgPerDay = (room.total_openings / days).toFixed(1);

        const windowCount = room.windows.length;
        const windowLabel = windowCount === 1 ? 'Fenster' : 'Fenster';

        return `
            <div class="room-ventilation-card" style="background: linear-gradient(135deg, #f0f9ff 0%, #ffffff 100%); border: 1px solid #bfdbfe; border-radius: 12px; padding: 20px; transition: all 0.2s;">
                <div style="font-size: 2em; margin-bottom: 10px;">🪟</div>
                <h4 style="margin: 0 0 15px 0; color: #1e40af; font-size: 1.1em;">${room.room}</h4>
                <div style="background: white; padding: 12px; border-radius: 8px; margin-bottom: 10px;">
                    <div style="font-size: 2.5em; font-weight: 700; color: #3b82f6; margin-bottom: 5px;">
                        ${room.total_openings}×
                    </div>
                    <div style="font-size: 0.85em; color: #6b7280;">
                        Gelüftet
                    </div>
                </div>
                <div style="display: flex; gap: 8px; font-size: 0.85em; color: #6b7280;">
                    <div style="flex: 1; padding: 8px; background: rgba(59, 130, 246, 0.1); border-radius: 6px; text-align: center;">
                        <div style="font-weight: 600; color: #3b82f6;">${avgPerDay}×</div>
                        <div style="font-size: 0.8em;">pro Tag</div>
                    </div>
                    <div style="flex: 1; padding: 8px; background: rgba(59, 130, 246, 0.1); border-radius: 6px; text-align: center;">
                        <div style="font-weight: 600; color: #3b82f6;">${windowCount}</div>
                        <div style="font-size: 0.8em;">${windowLabel}</div>
                    </div>
                </div>
            </div>
        `;
    }).join('');
}

/**
 * Rendert das Öffnungszeiten-Balkendiagramm
 */
function renderWindowDurationChart(data) {
    const ctx = document.getElementById('window-duration-chart');
    if (!ctx) return;

    // Zerstöre vorherigen Chart
    if (windowDurationChart) {
        windowDurationChart.destroy();
    }

    if (!data || data.length === 0) {
        ctx.parentElement.innerHTML = '<p style="text-align: center; color: #6b7280; padding: 40px;">Keine Daten verfügbar</p>';
        return;
    }

    // Sortiere nach Gesamtstunden (absteigend)
    const sortedData = [...data].sort((a, b) => b.total_hours - a.total_hours);

    // Limitiere auf Top 10 Fenster
    const limitedData = sortedData.slice(0, 10);

    const labels = limitedData.map(d => `${d.device_name} (${d.room_name})`);
    const hours = limitedData.map(d => d.total_hours);

    windowDurationChart = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: labels,
            datasets: [{
                label: 'Stunden offen',
                data: hours,
                backgroundColor: 'rgba(59, 130, 246, 0.7)',
                borderColor: 'rgba(59, 130, 246, 1)',
                borderWidth: 1
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            indexAxis: 'y', // Horizontale Balken
            plugins: {
                legend: {
                    display: false
                },
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            const hours = context.parsed.x;
                            const minutes = Math.round((hours % 1) * 60);
                            const fullHours = Math.floor(hours);
                            return `${fullHours}h ${minutes}min offen`;
                        }
                    }
                }
            },
            scales: {
                x: {
                    beginAtZero: true,
                    title: {
                        display: true,
                        text: 'Stunden'
                    },
                    ticks: {
                        callback: function(value) {
                            return value + 'h';
                        }
                    }
                }
            }
        }
    });
}

/**
 * Rendert das Öffnungshäufigkeits-Balkendiagramm
 */
function renderWindowFrequencyChart(data) {
    const ctx = document.getElementById('window-frequency-chart');
    if (!ctx) return;

    // Zerstöre vorherigen Chart
    if (windowFrequencyChart) {
        windowFrequencyChart.destroy();
    }

    if (!data || data.length === 0) {
        ctx.parentElement.innerHTML = '<p style="text-align: center; color: #6b7280; padding: 40px;">Keine Daten verfügbar</p>';
        return;
    }

    // Sortiere nach Häufigkeit (absteigend)
    const sortedData = [...data].sort((a, b) => b.open_count - a.open_count);

    // Limitiere auf Top 10 Fenster
    const limitedData = sortedData.slice(0, 10);

    const labels = limitedData.map(d => `${d.device_name} (${d.room_name})`);
    const counts = limitedData.map(d => d.open_count);

    windowFrequencyChart = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: labels,
            datasets: [{
                label: 'Anzahl Öffnungen',
                data: counts,
                backgroundColor: 'rgba(16, 185, 129, 0.7)',
                borderColor: 'rgba(16, 185, 129, 1)',
                borderWidth: 1
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            indexAxis: 'y', // Horizontale Balken
            plugins: {
                legend: {
                    display: false
                },
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            return `${context.parsed.x}x geöffnet`;
                        }
                    }
                }
            },
            scales: {
                x: {
                    beginAtZero: true,
                    title: {
                        display: true,
                        text: 'Anzahl Öffnungen'
                    },
                    ticks: {
                        stepSize: 1
                    }
                }
            }
        }
    });
}

/**
 * Rendert das Tägliche-Trends-Diagramm (kombiniert Balken + Linie)
 */
function renderWindowTrendsChart(data) {
    const ctx = document.getElementById('window-trends-chart');
    if (!ctx) return;

    // Zerstöre vorherigen Chart
    if (windowTrendsChart) {
        windowTrendsChart.destroy();
    }

    if (!data || data.length === 0) {
        ctx.parentElement.innerHTML = '<p style="text-align: center; color: #6b7280; padding: 40px;">Keine Daten verfügbar</p>';
        return;
    }

    // Sortiere nach Datum
    const sortedData = [...data].sort((a, b) => a.date.localeCompare(b.date));

    const labels = sortedData.map(d => {
        const date = new Date(d.date);
        return date.toLocaleDateString('de-DE', { day: '2-digit', month: '2-digit' });
    });
    const openCounts = sortedData.map(d => d.open_count);
    const totalHours = sortedData.map(d => d.total_hours);

    windowTrendsChart = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: labels,
            datasets: [
                {
                    type: 'bar',
                    label: 'Anzahl Öffnungen',
                    data: openCounts,
                    backgroundColor: 'rgba(245, 158, 11, 0.7)',
                    borderColor: 'rgba(245, 158, 11, 1)',
                    borderWidth: 1,
                    yAxisID: 'y'
                },
                {
                    type: 'line',
                    label: 'Stunden offen',
                    data: totalHours,
                    borderColor: 'rgba(139, 92, 246, 1)',
                    backgroundColor: 'rgba(139, 92, 246, 0.1)',
                    borderWidth: 2,
                    tension: 0.3,
                    yAxisID: 'y1'
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: {
                mode: 'index',
                intersect: false
            },
            plugins: {
                legend: {
                    display: true,
                    position: 'top'
                },
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            const label = context.dataset.label || '';
                            const value = context.parsed.y;
                            if (label.includes('Stunden')) {
                                const hours = Math.floor(value);
                                const minutes = Math.round((value % 1) * 60);
                                return `${label}: ${hours}h ${minutes}min`;
                            }
                            return `${label}: ${value}`;
                        }
                    }
                }
            },
            scales: {
                y: {
                    type: 'linear',
                    display: true,
                    position: 'left',
                    beginAtZero: true,
                    title: {
                        display: true,
                        text: 'Anzahl Öffnungen'
                    },
                    ticks: {
                        stepSize: 1
                    }
                },
                y1: {
                    type: 'linear',
                    display: true,
                    position: 'right',
                    beginAtZero: true,
                    title: {
                        display: true,
                        text: 'Stunden'
                    },
                    grid: {
                        drawOnChartArea: false
                    },
                    ticks: {
                        callback: function(value) {
                            return value + 'h';
                        }
                    }
                }
            }
        }
    });
}

/**
 * Lädt alle Fenster-Daten
 */
function loadWindowData() {
    loadAllWindowStatuses();
    loadWindowStatistics();
}

// ===== NEUE API-INTEGRATIONEN =====

/**
 * Lädt Luftfeuchtigkeits-Warnungen (Schimmelprävention)
 */
async function loadHumidityAlerts() {
    try {
        const response = await fetchJSON('/api/humidity/alerts');
        
        const container = document.getElementById('humidity-alerts-container');
        const card = document.getElementById('humidity-alerts-card');

        if (!container || !card) {
            console.log('Humidity alerts elements not found, skipping');
            return;
        }

        if (!response.alerts || response.alerts.length === 0) {
            card.style.display = 'none';
            return;
        }

        // Zeige Card wenn Warnungen vorhanden
        card.style.display = 'block';

        // Dedupliziere Alerts - zeige nur den neuesten pro Raum
        const latestAlerts = {};
        response.alerts.forEach(alert => {
            const roomKey = alert.room_name || 'unknown';
            if (!latestAlerts[roomKey] || new Date(alert.timestamp) > new Date(latestAlerts[roomKey].timestamp)) {
                latestAlerts[roomKey] = alert;
            }
        });
        const uniqueAlerts = Object.values(latestAlerts);

        const alertsHTML = uniqueAlerts.map(alert => {
            const severityColors = {
                'critical': { bg: '#fee2e2', border: '#dc2626', icon: '🚨' },
                'warning': { bg: '#fef3c7', border: '#f59e0b', icon: '⚠️' },
                'info': { bg: '#dbeafe', border: '#3b82f6', icon: 'ℹ️' }
            };
            
            const colors = severityColors[alert.severity] || severityColors['warning'];
            
            // Support both old and new field names
            const humidity = alert.current_humidity ?? alert.humidity ?? '?';
            const temperature = alert.current_temperature ?? alert.temperature ?? '?';
            const message = alert.message || alert.alert_type || 'Luftfeuchtigkeits-Warnung';

            return `
                <div style="margin-bottom: 12px; padding: 15px; background: ${colors.bg}; border-left: 4px solid ${colors.border}; border-radius: 8px;">
                    <div style="display: flex; align-items: start; gap: 12px;">
                        <span style="font-size: 1.5em;">${colors.icon}</span>
                        <div style="flex: 1;">
                            <div style="font-weight: 600; color: #1f2937; margin-bottom: 4px;">${alert.room_name || 'Unbekannter Raum'}</div>
                            <div style="font-size: 0.9em; color: #6b7280; margin-bottom: 8px;">${message}</div>
                            ${alert.recommendation ? `
                                <div style="font-size: 0.85em; color: #374151; background: white; padding: 8px; border-radius: 4px;">
                                    💡 ${alert.recommendation}
                                </div>
                            ` : ''}
                            <div style="font-size: 0.75em; color: #9ca3af; margin-top: 8px;">
                                ${humidity}% Luftfeuchtigkeit bei ${temperature}°C
                            </div>
                        </div>
                    </div>
                </div>
            `;
        }).join('');

        container.innerHTML = alertsHTML;

    } catch (error) {
        console.error('Error loading humidity alerts:', error);
        const alertCard = document.getElementById('humidity-alerts-card');
        if (alertCard) alertCard.style.display = 'none';
    }
}

/**
 * Lädt Lüftungsempfehlungen
 */
async function loadVentilationRecommendations() {
    try {
        const response = await fetchJSON('/api/ventilation/recommendation');
        
        const container = document.getElementById('ventilation-recommendations-container');
        const card = document.getElementById('ventilation-card');

        if (!container || !card) {
            console.log('Ventilation elements not found, skipping');
            return;
        }

        if (!response.recommendations || response.recommendations.length === 0) {
            card.style.display = 'none';
            return;
        }

        // Zeige Card wenn Empfehlungen vorhanden
        card.style.display = 'block';

        const recommendationsHTML = response.recommendations.map(rec => {
            const priorityColors = {
                'high': { bg: '#fee2e2', border: '#ef4444', icon: '🔴' },
                'medium': { bg: '#fef3c7', border: '#f59e0b', icon: '🟡' },
                'low': { bg: '#dbeafe', border: '#3b82f6', icon: '🔵' }
            };
            
            const colors = priorityColors[rec.priority] || priorityColors['medium'];

            return `
                <div style="margin-bottom: 12px; padding: 15px; background: ${colors.bg}; border-left: 4px solid ${colors.border}; border-radius: 8px;">
                    <div style="display: flex; align-items: start; gap: 12px;">
                        <span style="font-size: 1.5em;">${colors.icon}</span>
                        <div style="flex: 1;">
                            <div style="font-weight: 600; color: #1f2937; margin-bottom: 4px;">
                                ${rec.room_name || 'Allgemein'} - ${rec.action}
                            </div>
                            <div style="font-size: 0.9em; color: #6b7280; margin-bottom: 8px;">${rec.reason}</div>
                            ${rec.duration_minutes ? `
                                <div style="font-size: 0.85em; color: #374151;">
                                    ⏱️ Empfohlene Dauer: ${rec.duration_minutes} Minuten
                                </div>
                            ` : ''}
                            ${rec.expected_benefit ? `
                                <div style="font-size: 0.85em; color: #059669; margin-top: 4px;">
                                    ✅ ${rec.expected_benefit}
                                </div>
                            ` : ''}
                        </div>
                    </div>
                </div>
            `;
        }).join('');

        container.innerHTML = recommendationsHTML;

    } catch (error) {
        console.error('Error loading ventilation recommendations:', error);
        document.getElementById('ventilation-card').style.display = 'none';
    }
}

/**
 * Lädt Dusch-Vorhersagen
 */
async function loadShowerPredictions() {
    try {
        const response = await fetchJSON('/api/shower/predictions');
        
        const container = document.getElementById('shower-predictions-container');
        const card = document.getElementById('shower-predictions-card');

        if (!response.predictions || response.predictions.length === 0) {
            card.style.display = 'none';
            return;
        }

        // Zeige Card wenn Vorhersagen vorhanden
        card.style.display = 'block';

        const predictionsHTML = response.predictions.map(pred => {
            const confidence = Math.round(pred.confidence * 100);
            const confidenceColor = confidence > 70 ? '#10b981' : confidence > 50 ? '#f59e0b' : '#6b7280';

            return `
                <div style="margin-bottom: 12px; padding: 15px; background: #f9fafb; border: 1px solid #e5e7eb; border-radius: 8px;">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                        <div style="font-weight: 600; color: #1f2937;">
                            🚿 ${pred.predicted_time}
                        </div>
                        <div style="font-size: 0.85em; padding: 4px 8px; background: ${confidenceColor}; color: white; border-radius: 4px;">
                            ${confidence}% Wahrscheinlichkeit
                        </div>
                    </div>
                    ${pred.typical_duration ? `
                        <div style="font-size: 0.9em; color: #6b7280;">
                            ⏱️ Typische Dauer: ${pred.typical_duration} Minuten
                        </div>
                    ` : ''}
                    ${pred.day_of_week ? `
                        <div style="font-size: 0.85em; color: #9ca3af; margin-top: 4px;">
                            📅 Basierend auf ${pred.day_of_week}-Muster
                        </div>
                    ` : ''}
                </div>
            `;
        }).join('');

        container.innerHTML = `
            <div style="margin-bottom: 15px; padding: 12px; background: #eff6ff; border-radius: 8px; border-left: 4px solid #3b82f6;">
                <div style="font-size: 0.9em; color: #1e40af;">
                    <strong>ℹ️ Hinweis:</strong> Vorhersagen basieren auf ${response.training_days || 0} Tagen Trainingsdaten
                </div>
            </div>
            ${predictionsHTML}
        `;

    } catch (error) {
        console.error('Error loading shower predictions:', error);
        document.getElementById('shower-predictions-card').style.display = 'none';
    }
}

/**
 * Lädt aktuellen Schimmelprävention-Status
 */
async function loadMoldPreventionStatus() {
    try {
        const response = await fetchJSON('/api/status');
        
        const container = document.getElementById('mold-status-container');
        const card = document.getElementById('mold-prevention-card');

        if (!response.mold_prevention) {
            container.innerHTML = `
                <div style="padding: 20px; text-align: center; color: #6b7280;">
                    ℹ️ Schimmelprävention nicht konfiguriert
                </div>
            `;
            return;
        }

        const mold = response.mold_prevention;
        
        // Risiko-Level Farben
        const riskStyles = {
            'NIEDRIG': { bg: '#d1fae5', border: '#059669', color: '#065f46', icon: '🟢' },
            'MITTEL': { bg: '#fef3c7', border: '#d97706', color: '#92400e', icon: '🟡' },
            'HOCH': { bg: '#fed7aa', border: '#ea580c', color: '#7c2d12', icon: '🟠' },
            'KRITISCH': { bg: '#fee2e2', border: '#dc2626', color: '#7f1d1d', icon: '🔴' }
        };

        const style = riskStyles[mold.risk_level] || riskStyles['MITTEL'];

        // Hauptstatus-Anzeige
        let statusHTML = `
            <div style="padding: 20px; background: ${style.bg}; border-left: 4px solid ${style.border}; border-radius: 8px;">
                <div style="display: flex; justify-content: space-between; align-items: start; flex-wrap: wrap; gap: 20px;">
                    <div style="flex: 1; min-width: 250px;">
                        <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 10px;">
                            <span style="font-size: 2em;">${style.icon}</span>
                            <div>
                                <div style="font-size: 1.5em; font-weight: 700; color: ${style.color};">${mold.risk_level}</div>
                                <div style="font-size: 0.85em; color: #6b7280;">Schimmelrisiko</div>
                            </div>
                        </div>
                        ${mold.risk_level === 'KRITISCH' ? `
                            <div style="margin-top: 10px; padding: 10px; background: white; border-radius: 6px; font-size: 0.9em; color: #991b1b;">
                                <strong>⚠️ Sofortmaßnahmen erforderlich!</strong>
                            </div>
                        ` : ''}
                    </div>

                    <!-- Messwerte -->
                    <div style="flex: 2; display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 15px;">
                        <div style="background: white; padding: 15px; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.1);">
                            <div style="font-size: 0.75em; color: #6b7280; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 5px;">Luftfeuchtigkeit</div>
                            <div style="font-size: 1.8em; font-weight: 700; color: #1f2937;">${mold.humidity !== null && mold.humidity !== undefined ? mold.humidity.toFixed(1) : '--'}%</div>
                        </div>
                        
                        <div style="background: white; padding: 15px; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.1);">
                            <div style="font-size: 0.75em; color: #6b7280; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 5px;">Temperatur</div>
                            <div style="font-size: 1.8em; font-weight: 700; color: #1f2937;">${mold.temperature !== null && mold.temperature !== undefined ? mold.temperature.toFixed(1) : '--'}°C</div>
                        </div>
                        
                        <div style="background: white; padding: 15px; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.1);">
                            <div style="font-size: 0.75em; color: #6b7280; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 5px;">Taupunkt</div>
                            <div style="font-size: 1.8em; font-weight: 700; color: #1f2937;">${mold.dewpoint !== null && mold.dewpoint !== undefined ? mold.dewpoint.toFixed(1) : '--'}°C</div>
                        </div>
                        
                        <div style="background: white; padding: 15px; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.1);">
                            <div style="font-size: 0.75em; color: #6b7280; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 5px;">Kondensation</div>
                            <div style="font-size: 1.5em; font-weight: 700; color: ${mold.condensation_possible ? '#dc2626' : '#059669'};">
                                ${mold.condensation_possible ? '⚠️ Möglich' : '✓ Keine'}
                            </div>
                        </div>
                        
                        <div style="background: white; padding: 15px; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.1);">
                            <div style="font-size: 0.75em; color: #6b7280; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 5px;">Luftentfeuchter</div>
                            <div style="font-size: 1.5em; font-weight: 700; color: ${mold.dehumidifier_running ? '#059669' : '#6b7280'};">
                                ${mold.dehumidifier_running ? '✓ Aktiv' : '○ Aus'}
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Empfehlungen -->
                ${mold.recommendations && mold.recommendations.length > 0 ? `
                    <div style="margin-top: 20px; padding-top: 20px; border-top: 1px solid rgba(0,0,0,0.1);">
                        <div style="font-weight: 600; color: ${style.color}; margin-bottom: 10px;">💡 Empfehlungen:</div>
                        <ul style="margin: 0; padding-left: 20px; color: #374151;">
                            ${mold.recommendations.map(rec => `<li style="margin-bottom: 5px;">${rec}</li>`).join('')}
                        </ul>
                    </div>
                ` : ''}
            </div>
        `;

        container.innerHTML = statusHTML;

        // Zeige Karte immer an
        card.style.display = 'block';

    } catch (error) {
        console.error('Error loading mold prevention status:', error);
        const container = document.getElementById('mold-status-container');
        container.innerHTML = `
            <div style="padding: 20px; text-align: center; color: #ef4444;">
                ⚠️ Fehler beim Laden der Schimmelprävention
            </div>
        `;
    }
}
