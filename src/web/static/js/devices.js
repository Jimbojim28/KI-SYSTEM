// Devices Page JavaScript - Enhanced Version

let allDevices = [];
let allRooms = [];
let zoneNameMap = {};
let currentFilter = 'all';
let currentView = 'grid';
let currentPlatform = 'all';
let searchTerm = '';

// ============================================
// LOAD DEVICES
// ============================================

async function loadDevices() {
    try {
        const container = document.getElementById('devices-container');
        container.innerHTML = `
            <div class="loading">
                <div class="loading-spinner"></div>
                <p>Lade Geräte...</p>
            </div>
        `;

        // Lade Geräte und Raum-Einstellungen parallel (zentrale Settings-API)
        const [devicesData, roomsData] = await Promise.all([
            fetchJSON('/api/devices'),
            fetchJSON('/api/rooms/settings')
        ]);

        allDevices = devicesData.devices || [];
        allRooms = roomsData.rooms || [];
        
        // Sensor-Mappings sind jetzt auch verfügbar in roomsData.sensor_mappings
        // (kann für zukünftige Features genutzt werden)

        // Erstelle Zone-ID zu Name Mapping
        zoneNameMap = {};
        allRooms.forEach(room => {
            zoneNameMap[room.id] = room.name;
        });

        // Füge Raumnamen zu Geräten hinzu (falls nicht vorhanden)
        allDevices.forEach(device => {
            if (!device.zoneName && device.zone) {
                device.zoneName = zoneNameMap[device.zone] || 'Ohne Raum';
            }
            if (!device.zoneName) {
                device.zoneName = 'Ohne Raum';
            }
        });

        updateStatistics();
        renderDevices();
        updateLastUpdateTime();

    } catch (error) {
        console.error('Error loading devices:', error);
        document.getElementById('devices-container').innerHTML =
            '<div class="empty-state">❌ Fehler beim Laden der Geräte</div>';
    }
}

// ============================================
// STATISTICS
// ============================================

function updateStatistics() {
    const filtered = getFilteredByPlatform(allDevices);
    
    const stats = {
        total: filtered.length,
        on: filtered.filter(d => d.state === 'on').length,
        lights: filtered.filter(d => d.domain === 'light').length,
        switches: filtered.filter(d => d.domain === 'switch').length,
        climate: filtered.filter(d => d.domain === 'climate').length,
        sensors: filtered.filter(d => d.domain === 'sensor').length
    };

    document.getElementById('total-devices').textContent = stats.total;
    document.getElementById('devices-on').textContent = stats.on;
    document.getElementById('lights-count').textContent = stats.lights;
    document.getElementById('switches-count').textContent = stats.switches;
    document.getElementById('climate-count').textContent = stats.climate;
    document.getElementById('sensors-count').textContent = stats.sensors;
}

function updateLastUpdateTime() {
    const el = document.getElementById('last-update-time');
    if (el) {
        el.textContent = `Aktualisiert: ${new Date().toLocaleTimeString('de-DE')}`;
    }
}

// ============================================
// FILTERING
// ============================================

function getFilteredByPlatform(devices) {
    if (currentPlatform === 'all') return devices;
    return devices.filter(d => d.platform === currentPlatform);
}

function getFilteredDevices() {
    let filtered = getFilteredByPlatform(allDevices);

    // Filter nach Typ
    if (currentFilter !== 'all') {
        filtered = filtered.filter(d => {
            if (currentFilter === 'switch') {
                return d.domain === 'switch' || d.class === 'socket';
            }
            if (currentFilter === 'other') {
                return !['light', 'climate', 'switch', 'sensor'].includes(d.domain);
            }
            return d.domain === currentFilter;
        });
    }

    // Filter nach Suchbegriff
    if (searchTerm) {
        const term = searchTerm.toLowerCase();
        filtered = filtered.filter(d =>
            d.name.toLowerCase().includes(term) ||
            (d.zoneName && d.zoneName.toLowerCase().includes(term)) ||
            getDomainName(d.domain).toLowerCase().includes(term) ||
            (d.class && d.class.toLowerCase().includes(term))
        );
    }

    return filtered;
}

// ============================================
// RENDER DEVICES
// ============================================

function renderDevices() {
    const container = document.getElementById('devices-container');
    const filtered = getFilteredDevices();

    // Update Titel
    const title = document.getElementById('devices-section-title');
    if (searchTerm) {
        title.textContent = `Suchergebnisse (${filtered.length})`;
    } else if (currentFilter !== 'all') {
        title.textContent = `${getDomainName(currentFilter)} (${filtered.length})`;
    } else {
        title.textContent = `Alle Geräte (${filtered.length})`;
    }

    if (filtered.length === 0) {
        container.innerHTML = '<div class="empty-state">🔍 Keine Geräte gefunden</div>';
        return;
    }

    // Setze View-Klasse
    container.className = `devices-display ${currentView}-view`;

    // Rendere basierend auf aktueller Ansicht
    if (currentView === 'grid') {
        renderGridView(container, filtered);
    } else if (currentView === 'list') {
        renderListView(container, filtered);
    } else if (currentView === 'rooms') {
        renderRoomsView(container, filtered);
    }
}

// ============================================
// GRID VIEW
// ============================================

function renderGridView(container, devices) {
    container.innerHTML = devices.map(device => {
        const isOn = device.state === 'on';
        const icon = getDeviceIcon(device);
        const statusInfo = getDeviceStatusInfo(device);
        const canControl = canControlDevice(device);
        const configBadge = getConfigBadge(device);

        return `
            <div class="device-card ${isOn ? 'on' : ''} ${!device.available ? 'unavailable' : ''}" data-id="${device.id}">
                <div class="device-card-header">
                    <div class="device-icon">${icon}</div>
                    <div class="device-status-indicator ${isOn ? 'on' : 'off'}"></div>
                </div>
                <div class="device-card-body">
                    <h4 title="${device.name}">${device.name}</h4>
                    <p class="device-zone">📍 ${device.zoneName}</p>
                    <div class="device-badges">
                        <span class="badge badge-domain">${getDomainName(device.domain)}</span>
                        ${configBadge}
                    </div>
                    ${statusInfo ? `<div class="device-status-info">${statusInfo}</div>` : ''}
                </div>
                ${canControl ? `
                    <button class="device-quick-toggle ${isOn ? 'turn-off' : 'turn-on'}" 
                            onclick="quickToggleDevice('${device.id}', event)">
                        ${isOn ? '⏻ Aus' : '⏻ Ein'}
                    </button>
                ` : ''}
            </div>
        `;
    }).join('');

    attachDeviceClickListeners();
}

// ============================================
// LIST VIEW
// ============================================

function renderListView(container, devices) {
    container.innerHTML = devices.map(device => {
        const isOn = device.state === 'on';
        const icon = getDeviceIcon(device);
        const statusValues = getDeviceStatusValues(device);
        const canControl = canControlDevice(device);

        return `
            <div class="device-list-item ${isOn ? 'on' : ''}" data-id="${device.id}">
                <div class="device-list-icon">${icon}</div>
                <div class="device-list-info">
                    <h4>${device.name}</h4>
                    <p class="device-zone">📍 ${device.zoneName} · ${getDomainName(device.domain)}</p>
                </div>
                <div class="device-list-status">
                    ${statusValues}
                </div>
                <div class="device-list-actions">
                    ${canControl ? `
                        <button class="btn btn-small ${isOn ? 'btn-secondary' : 'btn-primary'}" 
                                onclick="quickToggleDevice('${device.id}', event)">
                            ${isOn ? 'Aus' : 'Ein'}
                        </button>
                    ` : ''}
                </div>
            </div>
        `;
    }).join('');

    attachDeviceClickListeners();
}

// ============================================
// ROOMS VIEW
// ============================================

function renderRoomsView(container, devices) {
    // Gruppiere nach Raum
    const byRoom = {};

    devices.forEach(device => {
        const room = device.zoneName || 'Ohne Raum';
        if (!byRoom[room]) {
            byRoom[room] = [];
        }
        byRoom[room].push(device);
    });

    // Sortiere Räume alphabetisch, aber "Ohne Raum" kommt ans Ende
    const rooms = Object.keys(byRoom).sort((a, b) => {
        if (a === 'Ohne Raum') return 1;
        if (b === 'Ohne Raum') return -1;
        return a.localeCompare(b);
    });

    container.innerHTML = rooms.map(room => {
        const roomDevices = byRoom[room];
        const onCount = roomDevices.filter(d => d.state === 'on').length;

        // Finde Raum-Icon
        const roomData = allRooms.find(r => r.name === room);
        const roomIcon = roomData?.icon || '🏠';

        return `
            <div class="room-group">
                <div class="room-group-header">
                    <h4>${roomIcon} ${room}</h4>
                    <span class="room-device-count">
                        ${roomDevices.length} Gerät${roomDevices.length !== 1 ? 'e' : ''}
                        ${onCount > 0 ? ` · ${onCount} aktiv` : ''}
                    </span>
                </div>
                <div class="room-devices-grid">
                    ${roomDevices.map(device => {
                        const isOn = device.state === 'on';
                        const icon = getDeviceIcon(device);
                        const canControl = canControlDevice(device);

                        return `
                            <div class="device-card ${isOn ? 'on' : ''}" data-id="${device.id}">
                                <div class="device-card-header">
                                    <div class="device-icon">${icon}</div>
                                    <div class="device-status-indicator ${isOn ? 'on' : 'off'}"></div>
                                </div>
                                <div class="device-card-body">
                                    <h4>${device.name}</h4>
                                    <span class="badge">${getDomainName(device.domain)}</span>
                                </div>
                                ${canControl ? `
                                    <button class="device-quick-toggle ${isOn ? 'turn-off' : 'turn-on'}" 
                                            onclick="quickToggleDevice('${device.id}', event)">
                                        ${isOn ? '⏻ Aus' : '⏻ Ein'}
                                    </button>
                                ` : ''}
                            </div>
                        `;
                    }).join('')}
                </div>
            </div>
        `;
    }).join('');

    attachDeviceClickListeners();
}

// ============================================
// HELPER FUNCTIONS
// ============================================

function getDeviceIcon(device) {
    const domain = device.domain;
    const deviceClass = device.class || '';
    
    // Spezifische Icons basierend auf Geräteklasse
    if (deviceClass === 'light' || domain === 'light') {
        if (device.state === 'on') return '💡';
        return '🔅';
    }
    if (deviceClass === 'thermostat' || deviceClass === 'heater' || domain === 'climate') return '🌡️';
    if (deviceClass === 'socket') return '🔌';
    if (deviceClass === 'switch' || domain === 'switch') return '🔘';
    if (domain === 'sensor') {
        const caps = device.capabilities || [];
        if (caps.includes('measure_temperature')) return '🌡️';
        if (caps.includes('measure_humidity')) return '💧';
        if (caps.includes('measure_co2')) return '💨';
        if (caps.includes('measure_luminance')) return '☀️';
        if (caps.includes('alarm_motion') || caps.includes('alarm_presence')) return '🚶';
        if (caps.includes('alarm_contact')) return '🚪';
        return '📊';
    }
    
    return '📱';
}

function getDomainName(domain) {
    const names = {
        'light': 'Licht',
        'climate': 'Klima',
        'thermostat': 'Thermostat',
        'heater': 'Heizung',
        'switch': 'Schalter',
        'socket': 'Steckdose',
        'sensor': 'Sensor',
        'other': 'Sonstige'
    };
    return names[domain] || domain || 'Unbekannt';
}

function getConfigBadge(device) {
    // Zeige Badge für konfigurierte Geräte (aus /rooms device_types)
    if (device.configured_type === 'light') {
        return '<span class="badge badge-config badge-light">💡 Als Lampe</span>';
    }
    if (device.configured_type === 'device') {
        return '<span class="badge badge-config badge-device">🔌 Als Gerät</span>';
    }
    return '';
}

function canControlDevice(device) {
    const controllableDomains = ['light', 'switch', 'climate'];
    const controllableClasses = ['light', 'socket', 'thermostat', 'heater'];
    const caps = device.capabilities || [];
    
    return controllableDomains.includes(device.domain) || 
           controllableClasses.includes(device.class) ||
           caps.includes('onoff');
}

function getDeviceStatusInfo(device) {
    const items = [];
    const attrs = device.attributes || {};
    
    // Helligkeit
    if (attrs.brightness_pct !== undefined && device.state === 'on') {
        items.push(`<span class="device-status-item">🔆 ${attrs.brightness_pct}%</span>`);
    }
    
    // Temperatur
    if (attrs.current_temperature !== undefined) {
        items.push(`<span class="device-status-item highlight">🌡️ ${attrs.current_temperature}°C</span>`);
    }
    if (attrs.target_temperature !== undefined) {
        items.push(`<span class="device-status-item">🎯 ${attrs.target_temperature}°C</span>`);
    }
    
    // Energie
    if (attrs.power !== undefined) {
        const powerClass = attrs.power > 100 ? 'warning' : '';
        items.push(`<span class="device-status-item ${powerClass}">⚡ ${attrs.power}W</span>`);
    }
    
    // Luftfeuchtigkeit
    if (attrs.humidity !== undefined) {
        const humClass = attrs.humidity > 70 ? 'warning' : '';
        items.push(`<span class="device-status-item ${humClass}">💧 ${attrs.humidity}%</span>`);
    }
    
    // CO2
    if (attrs.co2 !== undefined) {
        const co2Class = attrs.co2 > 1000 ? 'danger' : (attrs.co2 > 800 ? 'warning' : '');
        items.push(`<span class="device-status-item ${co2Class}">💨 ${attrs.co2} ppm</span>`);
    }
    
    // Batterie
    if (attrs.battery !== undefined) {
        const battClass = attrs.battery < 20 ? 'danger' : (attrs.battery < 50 ? 'warning' : '');
        items.push(`<span class="device-status-item ${battClass}">🔋 ${attrs.battery}%</span>`);
    }
    
    // Bewegung
    if (attrs.motion === true) {
        items.push(`<span class="device-status-item warning">🚶 Bewegung</span>`);
    }
    
    // Kontakt (Fenster/Tür)
    if (attrs.contact_open === true) {
        items.push(`<span class="device-status-item danger">🚪 Offen</span>`);
    }
    
    return items.join('');
}

function getDeviceStatusValues(device) {
    const items = [];
    const attrs = device.attributes || {};
    const isOn = device.state === 'on';
    
    // Status
    items.push(`<span class="device-list-value ${isOn ? 'on' : ''}">${isOn ? '● Ein' : '○ Aus'}</span>`);
    
    // Wichtige Werte
    if (attrs.brightness_pct !== undefined && isOn) {
        items.push(`<span class="device-list-value">🔆 ${attrs.brightness_pct}%</span>`);
    }
    if (attrs.current_temperature !== undefined) {
        items.push(`<span class="device-list-value">🌡️ ${attrs.current_temperature}°C</span>`);
    }
    if (attrs.power !== undefined && attrs.power > 0) {
        items.push(`<span class="device-list-value">⚡ ${attrs.power}W</span>`);
    }
    if (attrs.humidity !== undefined) {
        items.push(`<span class="device-list-value">💧 ${attrs.humidity}%</span>`);
    }
    
    return items.join('');
}

// ============================================
// DEVICE CONTROL
// ============================================

async function quickToggleDevice(deviceId, event) {
    event.stopPropagation();
    
    const device = allDevices.find(d => d.id === deviceId);
    if (!device) return;
    
    const isOn = device.state === 'on';
    const action = isOn ? 'turn_off' : 'turn_on';
    
    // Visual feedback
    const btn = event.target;
    btn.disabled = true;
    btn.textContent = '...';

    try {
        const result = await postJSON(`/api/devices/${deviceId}/control`, { action });
        if (result.success) {
            // Update lokal sofort
            device.state = isOn ? 'off' : 'on';
            renderDevices();
            updateStatistics();
        } else {
            showNotification('Fehler beim Steuern des Geräts', 'error');
        }
    } catch (error) {
        console.error('Error toggling device:', error);
        showNotification('Fehler beim Steuern des Geräts', 'error');
    }
    
    // Volle Aktualisierung nach kurzer Verzögerung
    setTimeout(loadDevices, 1500);
}

async function controlDevice(deviceId, action) {
    try {
        const result = await postJSON(`/api/devices/${deviceId}/control`, { action });

        if (result.success) {
            showNotification('✓ Gerät erfolgreich gesteuert', 'success');
            closeModal();
            setTimeout(loadDevices, 1000);
        } else {
            showNotification('✗ Fehler beim Steuern des Geräts', 'error');
        }
    } catch (error) {
        console.error('Error controlling device:', error);
        showNotification('✗ Fehler beim Steuern des Geräts', 'error');
    }
}

async function setBrightness(deviceId) {
    try {
        const slider = document.getElementById('brightness-slider');
        const brightness = parseInt(slider.value);

        const result = await postJSON(`/api/devices/${deviceId}/control`, {
            action: 'turn_on',
            brightness
        });

        if (result.success) {
            showNotification('✓ Helligkeit gesetzt', 'success');
            closeModal();
            setTimeout(loadDevices, 1000);
        } else {
            showNotification('✗ Fehler', 'error');
        }
    } catch (error) {
        console.error('Error setting brightness:', error);
        showNotification('✗ Fehler', 'error');
    }
}

async function setTemperature(deviceId) {
    try {
        const slider = document.getElementById('temp-slider');
        const temperature = parseFloat(slider.value);

        const result = await postJSON(`/api/devices/${deviceId}/control`, {
            action: 'set_temperature',
            temperature
        });

        if (result.success) {
            showNotification('✓ Temperatur gesetzt', 'success');
            closeModal();
            setTimeout(loadDevices, 1000);
        } else {
            showNotification('✗ Fehler', 'error');
        }
    } catch (error) {
        console.error('Error setting temperature:', error);
        showNotification('✗ Fehler', 'error');
    }
}

// ============================================
// BULK ACTIONS
// ============================================

async function bulkAction(domain, action) {
    const resultEl = document.getElementById('quick-action-result');
    const devices = allDevices.filter(d => {
        if (domain === 'switch') {
            return d.domain === 'switch' || d.class === 'socket';
        }
        return d.domain === domain;
    });

    if (devices.length === 0) {
        resultEl.textContent = `Keine ${getDomainName(domain)} gefunden`;
        resultEl.className = 'action-result error';
        setTimeout(() => resultEl.className = 'action-result', 3000);
        return;
    }

    resultEl.textContent = `⏳ Führe Aktion für ${devices.length} Geräte aus...`;
    resultEl.className = 'action-result success';

    let success = 0;
    for (const device of devices) {
        try {
            const result = await postJSON(`/api/devices/${device.id}/control`, { action });
            if (result.success) success++;
        } catch (error) {
            console.error('Error:', error);
        }
    }

    resultEl.textContent = `✓ ${success} von ${devices.length} Geräten erfolgreich gesteuert`;
    setTimeout(() => {
        resultEl.className = 'action-result';
        loadDevices();
    }, 3000);
}

// ============================================
// MODAL
// ============================================

function showDeviceModal(device) {
    const modal = document.getElementById('device-modal');
    const isOn = device.state === 'on';
    const attrs = device.attributes || {};

    // Header
    document.getElementById('modal-device-icon').textContent = getDeviceIcon(device);
    document.getElementById('modal-device-name').textContent = device.name;
    document.getElementById('modal-device-type').textContent = getDomainName(device.domain);
    document.getElementById('modal-device-zone').textContent = `📍 ${device.zoneName}`;
    document.getElementById('modal-device-platform').textContent = device.platform || 'homey';
    
    const statusBadge = document.getElementById('modal-device-status-badge');
    statusBadge.textContent = isOn ? '● Eingeschaltet' : '○ Ausgeschaltet';
    statusBadge.className = `device-modal-status ${isOn ? 'on' : 'off'}`;

    // Status Cards
    const statusCards = [];
    
    if (attrs.brightness_pct !== undefined) {
        statusCards.push({ icon: '🔆', value: `${attrs.brightness_pct}%`, label: 'Helligkeit' });
    }
    if (attrs.current_temperature !== undefined) {
        statusCards.push({ icon: '🌡️', value: `${attrs.current_temperature}°C`, label: 'Temperatur' });
    }
    if (attrs.target_temperature !== undefined) {
        statusCards.push({ icon: '🎯', value: `${attrs.target_temperature}°C`, label: 'Zieltemperatur' });
    }
    if (attrs.power !== undefined) {
        statusCards.push({ icon: '⚡', value: `${attrs.power}W`, label: 'Leistung' });
    }
    if (attrs.energy !== undefined) {
        statusCards.push({ icon: '📊', value: `${attrs.energy.toFixed(2)} kWh`, label: 'Verbrauch' });
    }
    if (attrs.humidity !== undefined) {
        statusCards.push({ icon: '💧', value: `${attrs.humidity}%`, label: 'Luftfeuchte' });
    }
    if (attrs.co2 !== undefined) {
        statusCards.push({ icon: '💨', value: `${attrs.co2} ppm`, label: 'CO₂' });
    }
    if (attrs.battery !== undefined) {
        statusCards.push({ icon: '🔋', value: `${attrs.battery}%`, label: 'Batterie' });
    }
    if (attrs.luminance !== undefined) {
        statusCards.push({ icon: '☀️', value: `${attrs.luminance} lx`, label: 'Helligkeit' });
    }

    document.getElementById('modal-status-cards').innerHTML = statusCards.length > 0 
        ? statusCards.map(card => `
            <div class="status-card">
                <div class="status-card-icon">${card.icon}</div>
                <div class="status-card-value">${card.value}</div>
                <div class="status-card-label">${card.label}</div>
            </div>
        `).join('')
        : '<p style="color: #6b7280;">Keine Statuswerte verfügbar</p>';

    // Controls
    let controlsHTML = '';
    const caps = device.capabilities || [];
    
    if (caps.includes('onoff') || device.domain === 'light' || device.domain === 'switch') {
        controlsHTML += `
            <div class="control-row">
                <button class="btn btn-primary" onclick="controlDevice('${device.id}', 'turn_on')">
                    💡 Einschalten
                </button>
                <button class="btn btn-secondary" onclick="controlDevice('${device.id}', 'turn_off')">
                    ⏻ Ausschalten
                </button>
            </div>
        `;
    }
    
    if (caps.includes('dim') || device.domain === 'light') {
        const currentBrightness = attrs.brightness || 255;
        controlsHTML += `
            <div class="control-group">
                <label>🔆 Helligkeit: <span id="brightness-display">${Math.round((currentBrightness / 255) * 100)}%</span></label>
                <input type="range" id="brightness-slider" min="0" max="255" value="${currentBrightness}" class="slider">
                <button class="btn btn-primary" style="margin-top: 10px;" onclick="setBrightness('${device.id}')">
                    Helligkeit setzen
                </button>
            </div>
        `;
    }
    
    if (caps.includes('target_temperature') || device.domain === 'climate') {
        const currentTemp = attrs.target_temperature || 20;
        controlsHTML += `
            <div class="control-group">
                <label>🎯 Zieltemperatur: <span id="temp-display">${currentTemp}°C</span></label>
                <input type="range" id="temp-slider" min="5" max="30" step="0.5" value="${currentTemp}" class="slider">
                <button class="btn btn-primary" style="margin-top: 10px;" onclick="setTemperature('${device.id}')">
                    Temperatur setzen
                </button>
            </div>
        `;
    }
    
    if (!controlsHTML) {
        controlsHTML = '<p style="color: #6b7280;">Dieses Gerät kann nicht gesteuert werden.</p>';
    }

    document.getElementById('modal-device-controls').innerHTML = controlsHTML;

    // Capabilities
    const capsHTML = caps.length > 0
        ? `<div class="capabilities-list">${caps.map(c => `<span class="capability-tag">${c}</span>`).join('')}</div>`
        : '<p style="color: #6b7280;">Keine Fähigkeiten bekannt</p>';
    
    document.getElementById('modal-device-capabilities').innerHTML = capsHTML;

    // Setup Sliders
    setupSliders();

    modal.style.display = 'block';
}

function setupSliders() {
    const tempSlider = document.getElementById('temp-slider');
    if (tempSlider) {
        tempSlider.addEventListener('input', (e) => {
            document.getElementById('temp-display').textContent = `${e.target.value}°C`;
        });
    }

    const brightnessSlider = document.getElementById('brightness-slider');
    if (brightnessSlider) {
        brightnessSlider.addEventListener('input', (e) => {
            const percent = Math.round((e.target.value / 255) * 100);
            document.getElementById('brightness-display').textContent = `${percent}%`;
        });
    }
}

function closeModal() {
    document.getElementById('device-modal').style.display = 'none';
}

function attachDeviceClickListeners() {
    document.querySelectorAll('.device-card, .device-list-item').forEach(card => {
        card.addEventListener('click', (e) => {
            if (e.target.tagName === 'BUTTON') return;
            
            const deviceId = card.dataset.id;
            const device = allDevices.find(d => d.id === deviceId);
            if (device) {
                showDeviceModal(device);
            }
        });
    });
}

// ============================================
// EVENT HANDLERS
// ============================================

function setupFilters() {
    document.querySelectorAll('.filter-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            currentFilter = btn.dataset.filter;
            renderDevices();
            updateStatistics();
        });
    });
}

function setupViewToggle() {
    document.querySelectorAll('.view-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.view-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            currentView = btn.dataset.view;
            renderDevices();
        });
    });
}

function setupPlatformTabs() {
    document.querySelectorAll('.platform-tab').forEach(tab => {
        tab.addEventListener('click', () => {
            document.querySelectorAll('.platform-tab').forEach(t => t.classList.remove('active'));
            tab.classList.add('active');
            currentPlatform = tab.dataset.platform;
            renderDevices();
            updateStatistics();
        });
    });
}

function setupSearch() {
    const searchInput = document.getElementById('device-search');
    let debounceTimer;
    
    searchInput.addEventListener('input', (e) => {
        clearTimeout(debounceTimer);
        debounceTimer = setTimeout(() => {
            searchTerm = e.target.value;
            renderDevices();
        }, 200);
    });
}

function setupQuickActions() {
    document.getElementById('all-lights-on').addEventListener('click', () => bulkAction('light', 'turn_on'));
    document.getElementById('all-lights-off').addEventListener('click', () => bulkAction('light', 'turn_off'));
    document.getElementById('all-switches-off').addEventListener('click', () => bulkAction('switch', 'turn_off'));
    document.getElementById('refresh-devices').addEventListener('click', loadDevices);
}

function setupModal() {
    document.querySelector('.close').addEventListener('click', closeModal);
    
    window.addEventListener('click', (e) => {
        const modal = document.getElementById('device-modal');
        if (e.target === modal) {
            closeModal();
        }
    });
}

// ============================================
// INITIALIZATION
// ============================================

document.addEventListener('DOMContentLoaded', () => {
    loadDevices();
    setupFilters();
    setupViewToggle();
    setupPlatformTabs();
    setupSearch();
    setupQuickActions();
    setupModal();

    // Auto-refresh alle 30 Sekunden
    setInterval(loadDevices, 30000);
});
