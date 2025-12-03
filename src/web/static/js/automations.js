// Automations Page JavaScript

let allDevices = [];
let deviceConfig = {
    learning: [],
    control: [],
    automation: []
};

let automationRules = {
    away_mode: {
        enabled: false,
        timeout: 30,
        lights_off: true,
        sockets_off: true,
        heating_eco: false,
        exceptions: []
    },
    arrival_mode: {
        enabled: false,
        lights_on: true,
        sockets_on: true,
        heating_comfort: false,
        time_from: '06:00',
        time_to: '23:00'
    },
    night_mode: {
        enabled: false,
        time_from: '22:00',
        time_to: '06:00',
        lights_dim: true,
        no_automation: false,
        heating_lower: false
    }
};

// Lade alle Geräte
async function loadDevices() {
    try {
        const data = await fetchJSON('/api/devices');
        allDevices = data.devices;
        renderDeviceLists();
        populateExceptionsList();
    } catch (error) {
        console.error('Error loading devices:', error);
    }
}

// Rendere Geräte-Listen
function renderDeviceLists() {
    renderDeviceList('learning', deviceConfig.learning);
    renderDeviceList('control', deviceConfig.control);
    renderDeviceList('automation', deviceConfig.automation);
}

// Rendere einzelne Geräte-Liste
function renderDeviceList(category, selectedIds) {
    const container = document.getElementById(`${category}-devices`);

    if (allDevices.length === 0) {
        container.innerHTML = '<p class="empty-state">Keine Geräte verfügbar</p>';
        return;
    }

    const html = allDevices.map(device => {
        const isSelected = selectedIds.includes(device.id);
        return `
            <div class="device-item">
                <label>
                    <input type="checkbox"
                           class="device-checkbox"
                           data-category="${category}"
                           data-device-id="${device.id}"
                           ${isSelected ? 'checked' : ''}>
                    <span>${getDeviceIcon(device.domain)} ${device.name}</span>
                    <span class="device-domain">${getDomainName(device.domain)}</span>
                </label>
            </div>
        `;
    }).join('');

    container.innerHTML = html;

    // Event Listener
    container.querySelectorAll('.device-checkbox').forEach(cb => {
        cb.addEventListener('change', (e) => {
            const category = e.target.dataset.category;
            const deviceId = e.target.dataset.deviceId;

            if (e.target.checked) {
                if (!deviceConfig[category].includes(deviceId)) {
                    deviceConfig[category].push(deviceId);
                }
            } else {
                deviceConfig[category] = deviceConfig[category].filter(id => id !== deviceId);
            }
        });
    });
}

// Populate Ausnahmen-Liste
function populateExceptionsList() {
    const select = document.getElementById('away-exceptions');
    select.innerHTML = allDevices
        .filter(d => d.domain === 'light' || d.domain === 'switch')
        .map(device => `<option value="${device.id}">${device.name}</option>`)
        .join('');
}

// Tabs
function setupTabs() {
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const tab = btn.dataset.tab;

            // Update buttons
            document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');

            // Update content
            document.querySelectorAll('.tab-content').forEach(content => {
                content.classList.add('hidden');
            });
            document.getElementById(`${tab}-tab`).classList.remove('hidden');
        });
    });
}

// Lade Konfiguration
async function loadConfig() {
    try {
        const data = await fetchJSON('/api/automations/config');

        if (data.device_config) {
            deviceConfig = data.device_config;
            renderDeviceLists();
        }

        if (data.automation_rules) {
            automationRules = data.automation_rules;
            applyRulesToUI();
        }

    } catch (error) {
        console.error('Error loading automation config:', error);
    }
}

// Wende Regeln auf UI an
function applyRulesToUI() {
    // Default-Werte falls nicht vorhanden
    const awayMode = automationRules.away_mode || {};
    const arrivalMode = automationRules.arrival_mode || {};
    const nightMode = automationRules.night_mode || {};
    
    // Away Mode
    const awayEnabled = document.getElementById('away-mode-enabled');
    const awayTimeout = document.getElementById('away-timeout');
    const awayLightsOff = document.getElementById('away-lights-off');
    const awaySocketsOff = document.getElementById('away-sockets-off');
    const awayHeatingEco = document.getElementById('away-heating-eco');
    
    if (awayEnabled) awayEnabled.checked = awayMode.enabled || false;
    if (awayTimeout) awayTimeout.value = awayMode.timeout || 15;
    if (awayLightsOff) awayLightsOff.checked = awayMode.lights_off !== false;
    if (awaySocketsOff) awaySocketsOff.checked = awayMode.sockets_off || false;
    if (awayHeatingEco) awayHeatingEco.checked = awayMode.heating_eco !== false;

    // Arrival Mode
    const arrivalEnabled = document.getElementById('arrival-mode-enabled');
    const arrivalLightsOn = document.getElementById('arrival-lights-on');
    const arrivalSocketsOn = document.getElementById('arrival-sockets-on');
    const arrivalHeatingComfort = document.getElementById('arrival-heating-comfort');
    const arrivalTimeFrom = document.getElementById('arrival-time-from');
    const arrivalTimeTo = document.getElementById('arrival-time-to');
    
    if (arrivalEnabled) arrivalEnabled.checked = arrivalMode.enabled || false;
    if (arrivalLightsOn) arrivalLightsOn.checked = arrivalMode.lights_on || false;
    if (arrivalSocketsOn) arrivalSocketsOn.checked = arrivalMode.sockets_on || false;
    if (arrivalHeatingComfort) arrivalHeatingComfort.checked = arrivalMode.heating_comfort || false;
    if (arrivalTimeFrom) arrivalTimeFrom.value = arrivalMode.time_from || '17:00';
    if (arrivalTimeTo) arrivalTimeTo.value = arrivalMode.time_to || '22:00';

    // Night Mode
    const nightEnabled = document.getElementById('night-mode-enabled');
    const nightTimeFrom = document.getElementById('night-time-from');
    const nightTimeTo = document.getElementById('night-time-to');
    const nightLightsDim = document.getElementById('night-lights-dim');
    const nightNoAutomation = document.getElementById('night-no-automation');
    const nightHeatingLower = document.getElementById('night-heating-lower');
    
    if (nightEnabled) nightEnabled.checked = nightMode.enabled || false;
    if (nightTimeFrom) nightTimeFrom.value = nightMode.time_from || '22:00';
    if (nightTimeTo) nightTimeTo.value = nightMode.time_to || '06:00';
    if (nightLightsDim) nightLightsDim.checked = nightMode.lights_dim !== false;
    if (nightNoAutomation) nightNoAutomation.checked = nightMode.no_automation || false;
    if (nightHeatingLower) nightHeatingLower.checked = nightMode.heating_lower || false;
}

// Sammle Regeln aus UI
function collectRulesFromUI() {
    return {
        away_mode: {
            enabled: document.getElementById('away-mode-enabled').checked,
            timeout: parseInt(document.getElementById('away-timeout').value),
            lights_off: document.getElementById('away-lights-off').checked,
            sockets_off: document.getElementById('away-sockets-off').checked,
            heating_eco: document.getElementById('away-heating-eco').checked,
            exceptions: Array.from(document.getElementById('away-exceptions').selectedOptions).map(o => o.value)
        },
        arrival_mode: {
            enabled: document.getElementById('arrival-mode-enabled').checked,
            lights_on: document.getElementById('arrival-lights-on').checked,
            sockets_on: document.getElementById('arrival-sockets-on').checked,
            heating_comfort: document.getElementById('arrival-heating-comfort').checked,
            time_from: document.getElementById('arrival-time-from').value,
            time_to: document.getElementById('arrival-time-to').value
        },
        night_mode: {
            enabled: document.getElementById('night-mode-enabled').checked,
            time_from: document.getElementById('night-time-from').value,
            time_to: document.getElementById('night-time-to').value,
            lights_dim: document.getElementById('night-lights-dim').checked,
            no_automation: document.getElementById('night-no-automation').checked,
            heating_lower: document.getElementById('night-heating-lower').checked
        }
    };
}

// Speichere Geräte-Konfiguration
document.getElementById('save-device-config').addEventListener('click', async () => {
    try {
        const result = await postJSON('/api/automations/device-config', {
            device_config: deviceConfig
        });

        if (result.success) {
            alert('Geräte-Konfiguration gespeichert!');
        }
    } catch (error) {
        console.error('Error saving device config:', error);
        alert('Fehler beim Speichern der Konfiguration');
    }
});

// Speichere Automatisierungs-Regeln
document.getElementById('save-automations').addEventListener('click', async () => {
    try {
        const rules = collectRulesFromUI();

        const result = await postJSON('/api/automations/rules', {
            automation_rules: rules
        });

        if (result.success) {
            alert('Automatisierungs-Regeln gespeichert!');
            automationRules = rules;
        }
    } catch (error) {
        console.error('Error saving automation rules:', error);
        alert('Fehler beim Speichern der Regeln');
    }
});

// Update Präsenz-Status
async function updatePresenceStatus() {
    try {
        const data = await fetchJSON('/api/automations/presence');

        const presenceDot = document.getElementById('presence-dot');
        const presenceText = document.getElementById('presence-text');
        const lastMotion = document.getElementById('last-motion');

        // Status-Anzeige
        if (data.present) {
            presenceDot.className = 'presence-dot present';

            // Zeige wer zuhause ist (Homey User Tracking)
            if (data.mode === 'homey_users' && data.users) {
                const usersHome = data.users.filter(u => u.present).map(u => u.name);
                if (usersHome.length > 0) {
                    presenceText.textContent = `Anwesend: ${usersHome.join(', ')}`;
                } else {
                    presenceText.textContent = 'Anwesend';
                }

                // Zeige Detail-Info
                lastMotion.textContent = `${data.users_home} von ${data.total_users} Person(en) zuhause`;
            } else {
                // Fallback: Motion-Sensor Modus
                presenceText.textContent = 'Anwesend';
                lastMotion.textContent = data.last_motion ?
                    new Date(data.last_motion).toLocaleString('de-DE') : '--';
            }
        } else {
            presenceDot.className = 'presence-dot away';
            presenceText.textContent = 'Abwesend';

            if (data.mode === 'homey_users') {
                lastMotion.textContent = 'Alle Nutzer sind unterwegs';
            } else {
                lastMotion.textContent = data.last_motion ?
                    `Letzte Bewegung: ${new Date(data.last_motion).toLocaleString('de-DE')}` : '--';
            }
        }

    } catch (error) {
        console.error('Error updating presence:', error);
        presenceText.textContent = 'Fehler beim Laden';
        lastMotion.textContent = '--';
    }
}

// Hilfsfunktionen (kopiert von devices.js)
function getDeviceIcon(domain) {
    const icons = {
        'light': '💡',
        'climate': '🌡️',
        'switch': '🔌',
        'sensor': '📊'
    };
    return icons[domain] || '📱';
}

function getDomainName(domain) {
    const names = {
        'light': 'Beleuchtung',
        'climate': 'Klima',
        'switch': 'Schalter',
        'sensor': 'Sensor'
    };
    return names[domain] || domain;
}

// Init
document.addEventListener('DOMContentLoaded', () => {
    setupTabs();
    loadDevices();
    loadConfig();
    updatePresenceStatus();

    // Auto-refresh presence alle 30 Sekunden
    setInterval(updatePresenceStatus, 30000);
});
