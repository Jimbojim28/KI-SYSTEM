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

// Weihnachtsbeleuchtung Config
let christmasConfig = {
    enabled: false,
    on_time: '16:00',
    off_time: '23:00',
    use_sunset: false,
    start_date: '',
    end_date: '',
    devices: [],
    presence_only: false,
    weekend_extended: false,
    random_delay: true
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
    // Haupt-Tabs (Regeln, Abwesenheit, Weihnachten, Geräte)
    document.querySelectorAll('.main-tab-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const tabName = btn.dataset.maintab;
            
            // Update Buttons
            document.querySelectorAll('.main-tab-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            
            // Update Content
            document.querySelectorAll('.main-tab-content').forEach(content => {
                content.style.display = 'none';
                content.classList.remove('active');
            });
            
            const targetTab = document.getElementById(`tab-${tabName}`);
            if (targetTab) {
                targetTab.style.display = 'block';
                targetTab.classList.add('active');
            }
        });
    });
    
    // Sub-Tabs (innerhalb der Geräte-Verwaltung)
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
    
    // Weihnachtsbeleuchtung initialisieren
    initChristmasTab();

    // Auto-refresh presence alle 30 Sekunden
    setInterval(updatePresenceStatus, 30000);
});

// =====================
// WEIHNACHTSBELEUCHTUNG
// =====================

function initChristmasTab() {
    // Standard-Datumswerte setzen (1. Dezember bis 6. Januar)
    const now = new Date();
    const year = now.getMonth() >= 10 ? now.getFullYear() : now.getFullYear() - 1;
    
    const startDateInput = document.getElementById('christmas-start-date');
    const endDateInput = document.getElementById('christmas-end-date');
    
    if (startDateInput && !startDateInput.value) {
        startDateInput.value = `${year}-12-01`;
    }
    if (endDateInput && !endDateInput.value) {
        endDateInput.value = `${year + 1}-01-06`;
    }
    
    // Event Listener
    const saveBtn = document.getElementById('save-christmas-config');
    if (saveBtn) {
        saveBtn.addEventListener('click', saveChristmasConfig);
    }
    
    const testOnBtn = document.getElementById('christmas-test-on');
    if (testOnBtn) {
        testOnBtn.addEventListener('click', () => testChristmasLights(true));
    }
    
    const testOffBtn = document.getElementById('christmas-test-off');
    if (testOffBtn) {
        testOffBtn.addEventListener('click', () => testChristmasLights(false));
    }
    
    // Sync-Button für Homey-Raum
    const syncBtn = document.getElementById('sync-christmas-zone');
    if (syncBtn) {
        syncBtn.addEventListener('click', syncChristmasZone);
    }
    
    // Config laden
    loadChristmasConfig();
}

async function loadChristmasConfig() {
    try {
        const response = await fetch('/api/christmas/config');
        if (response.ok) {
            const data = await response.json();
            const config = data.config || data;
            christmasConfig = { ...christmasConfig, ...config };
            applyChristmasConfigToUI();
        }
    } catch (error) {
        console.error('Error loading christmas config:', error);
    }
    
    // Geräte laden für Weihnachts-Tab
    loadChristmasDevices();
    updateChristmasStatus();
}

function applyChristmasConfigToUI() {
    const elements = {
        'christmas-enabled': christmasConfig.enabled,
        'christmas-on-time': christmasConfig.on_time,
        'christmas-off-time': christmasConfig.off_time,
        'christmas-use-sunset': christmasConfig.use_sunset,
        'christmas-start-date': christmasConfig.start_date,
        'christmas-end-date': christmasConfig.end_date,
        'christmas-presence-only': christmasConfig.presence_only,
        'christmas-weekend-extended': christmasConfig.weekend_extended,
        'christmas-random-delay': christmasConfig.random_delay
    };
    
    for (const [id, value] of Object.entries(elements)) {
        const el = document.getElementById(id);
        if (el) {
            if (el.type === 'checkbox') {
                el.checked = value;
            } else {
                el.value = value || '';
            }
        }
    }
}

async function loadChristmasDevices() {
    const container = document.getElementById('christmas-devices');
    const infoEl = document.getElementById('christmas-zone-info');
    if (!container) return;
    
    try {
        const response = await fetch('/api/christmas/devices');
        const data = await response.json();
        const devices = data.devices || [];
        const christmasZoneId = data.christmas_zone_id;
        const christmasZoneDevices = data.christmas_zone_devices || [];
        
        // Zeige Info über Weihnachtsraum
        if (infoEl) {
            if (christmasZoneId) {
                infoEl.style.display = 'block';
                infoEl.innerHTML = `🎄 <strong>Homey-Raum "Weihnachtsbeleuchtung" gefunden!</strong> 
                    ${christmasZoneDevices.length} Gerät(e) im Raum. 
                    <em>Klicke "Mit Homey-Raum synchronisieren" um alle automatisch auszuwählen.</em>`;
            } else {
                infoEl.style.display = 'block';
                infoEl.innerHTML = `💡 <strong>Tipp:</strong> Erstelle in Homey einen Raum namens "Weihnachtsbeleuchtung" und füge deine Weihnachtsgeräte dort hinzu. Dann kannst du sie hier automatisch synchronisieren!`;
            }
        }
        
        if (devices.length === 0) {
            container.innerHTML = '<p class="empty-state">Keine Geräte verfügbar</p>';
            return;
        }
        
        const html = devices.map(device => {
            const isSelected = christmasConfig.devices.includes(device.id);
            const icon = device.type === 'light' ? '💡' : '🔌';
            const isFromZone = device.is_christmas_zone;
            return `
                <div class="device-item christmas-device ${isFromZone ? 'from-zone' : ''}">
                    <label>
                        <input type="checkbox"
                               class="christmas-device-checkbox"
                               data-device-id="${device.id}"
                               ${isSelected ? 'checked' : ''}>
                        <span>${icon} ${device.name}</span>
                    </label>
                </div>
            `;
        }).join('');
        
        container.innerHTML = html;
        
        // Event Listener
        container.querySelectorAll('.christmas-device-checkbox').forEach(cb => {
            cb.addEventListener('change', (e) => {
                const deviceId = e.target.dataset.deviceId;
                if (e.target.checked) {
                    if (!christmasConfig.devices.includes(deviceId)) {
                        christmasConfig.devices.push(deviceId);
                    }
                } else {
                    christmasConfig.devices = christmasConfig.devices.filter(id => id !== deviceId);
                }
            });
        });
        
    } catch (error) {
        console.error('Error loading christmas devices:', error);
        container.innerHTML = '<p class="error">Fehler beim Laden der Geräte</p>';
    }
}

async function syncChristmasZone() {
    const syncBtn = document.getElementById('sync-christmas-zone');
    if (syncBtn) {
        syncBtn.disabled = true;
        syncBtn.textContent = '🔄 Synchronisiere...';
    }
    
    try {
        const response = await fetch('/api/christmas/sync-zone', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });
        
        const data = await response.json();
        
        if (data.success) {
            // Aktualisiere lokale Config
            christmasConfig.devices = data.devices || [];
            
            // Geräte-Liste neu laden
            await loadChristmasDevices();
            
            showNotification(`🎄 ${data.count} Geräte synchronisiert!`, 'success');
        } else {
            showNotification(data.error || 'Synchronisierung fehlgeschlagen', 'error');
        }
    } catch (error) {
        console.error('Error syncing christmas zone:', error);
        showNotification('Fehler bei der Synchronisierung', 'error');
    } finally {
        if (syncBtn) {
            syncBtn.disabled = false;
            syncBtn.textContent = '🔄 Mit Homey-Raum synchronisieren';
        }
    }
}

async function saveChristmasConfig() {
    // Sammle Config aus UI
    christmasConfig.enabled = document.getElementById('christmas-enabled')?.checked || false;
    christmasConfig.on_time = document.getElementById('christmas-on-time')?.value || '16:00';
    christmasConfig.off_time = document.getElementById('christmas-off-time')?.value || '23:00';
    christmasConfig.use_sunset = document.getElementById('christmas-use-sunset')?.checked || false;
    christmasConfig.start_date = document.getElementById('christmas-start-date')?.value || '';
    christmasConfig.end_date = document.getElementById('christmas-end-date')?.value || '';
    christmasConfig.presence_only = document.getElementById('christmas-presence-only')?.checked || false;
    christmasConfig.weekend_extended = document.getElementById('christmas-weekend-extended')?.checked || false;
    christmasConfig.random_delay = document.getElementById('christmas-random-delay')?.checked || true;
    
    try {
        const response = await fetch('/api/christmas/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(christmasConfig)
        });
        
        if (response.ok) {
            showNotification('🎄 Weihnachts-Konfiguration gespeichert!', 'success');
            updateChristmasStatus();
        } else {
            showNotification('Fehler beim Speichern', 'error');
        }
    } catch (error) {
        console.error('Error saving christmas config:', error);
        showNotification('Fehler beim Speichern', 'error');
    }
}

async function testChristmasLights(turnOn) {
    try {
        const response = await fetch('/api/christmas/test', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ action: turnOn ? 'on' : 'off' })
        });
        
        if (response.ok) {
            const result = await response.json();
            showNotification(
                turnOn ? `🎄 ${result.affected || 0} Geräte eingeschaltet` : 
                        `⭕ ${result.affected || 0} Geräte ausgeschaltet`,
                'success'
            );
        }
    } catch (error) {
        console.error('Error testing christmas lights:', error);
        showNotification('Fehler beim Testen', 'error');
    }
}

async function updateChristmasStatus() {
    try {
        const response = await fetch('/api/christmas/status');
        if (response.ok) {
            const data = await response.json();
            const status = data.status || data;
            
            const statusEl = document.getElementById('christmas-current-status');
            const nextActionEl = document.getElementById('christmas-next-action');
            const activeDevicesEl = document.getElementById('christmas-active-devices');
            
            if (statusEl) {
                if (status.lights_on) {
                    statusEl.textContent = '🟢 Lichter AN';
                    statusEl.className = 'status-badge active';
                } else if (status.enabled) {
                    statusEl.textContent = '⏸️ Wartet';
                    statusEl.className = 'status-badge waiting';
                } else {
                    statusEl.textContent = '⭕ Deaktiviert';
                    statusEl.className = 'status-badge inactive';
                }
            }
            
            if (nextActionEl) {
                nextActionEl.textContent = status.next_action || '--';
            }
            
            if (activeDevicesEl) {
                activeDevicesEl.textContent = status.active_devices || '0';
            }
        }
    } catch (error) {
        console.log('Christmas status not available');
    }
}

function showNotification(message, type = 'info') {
    // Einfache Notification
    const notification = document.createElement('div');
    notification.className = `notification ${type}`;
    notification.textContent = message;
    notification.style.cssText = `
        position: fixed;
        top: 20px;
        right: 20px;
        padding: 15px 25px;
        background: ${type === 'success' ? '#10b981' : type === 'error' ? '#ef4444' : '#3b82f6'};
        color: white;
        border-radius: 8px;
        box-shadow: 0 4px 15px rgba(0,0,0,0.2);
        z-index: 10000;
        animation: slideIn 0.3s ease;
    `;
    
    document.body.appendChild(notification);
    
    setTimeout(() => {
        notification.style.animation = 'slideOut 0.3s ease';
        setTimeout(() => notification.remove(), 300);
    }, 3000);
}
