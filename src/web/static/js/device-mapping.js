// Device Mapping Modal Functions

let currentMappingType = '';
let deviceMappings = {}; // Format: {type: {deviceId: {mode: 'replace'|'additional', name: '...'}}}
let primaryDevices = [];
let secondaryDevices = [];

async function openDeviceMappingModal(dataType) {
    currentMappingType = dataType;
    const modal = document.getElementById('device-mapping-modal');
    const config = await fetchJSON('/api/config');
    
    const primaryPlatform = config.platforms?.primary || config.platform?.type || 'homey';
    const secondaryPlatform = primaryPlatform === 'homey' ? 'homeassistant' : 'homey';
    
    // Update Modal Title
    const titles = {
        lighting: '💡 Licht Events - Geräte-Zuordnung',
        temperature: '🌡️ Temperatur Daten - Geräte-Zuordnung',
        heating: '🔥 Heizungs-Daten - Geräte-Zuordnung',
        windows: '🪟 Fenster Status - Geräte-Zuordnung',
        bathroom: '🚿 Badezimmer Daten - Geräte-Zuordnung'
    };
    document.getElementById('modal-title').textContent = titles[dataType] || 'Geräte-Zuordnung';
    
    // Update Platform Names
    const platformNames = {
        homey: 'Homey Pro',
        homeassistant: 'Home Assistant'
    };
    document.getElementById('primary-platform-name').textContent = platformNames[primaryPlatform];
    document.getElementById('primary-devices-title').textContent = `Hauptplattform (${platformNames[primaryPlatform]})`;
    document.getElementById('secondary-devices-title').textContent = `Sekundäre Plattform (${platformNames[secondaryPlatform]})`;
    
    // Load devices
    await loadDevicesForMapping(primaryPlatform, secondaryPlatform, dataType);
    
    // Load existing mappings
    if (config.device_mappings && config.device_mappings[dataType]) {
        deviceMappings[dataType] = config.device_mappings[dataType];
    } else {
        deviceMappings[dataType] = {};
    }
    
    updateMappingCount();
    modal.style.display = 'flex';
}

function closeDeviceMappingModal() {
    const modal = document.getElementById('device-mapping-modal');
    modal.style.display = 'none';
}

async function loadDevicesForMapping(primaryPlatform, secondaryPlatform, dataType) {
    const primaryList = document.getElementById('primary-devices-list');
    const secondaryList = document.getElementById('secondary-devices-list');
    
    primaryList.innerHTML = '<div class="loading">Lade Geräte...</div>';
    secondaryList.innerHTML = '<div class="loading">Lade Geräte...</div>';
    
    try {
        // Hole Geräte beider Plattformen  
        const response = await fetch('/api/devices/by-platform');
        const data = await response.json();
        
        primaryDevices = filterDevicesByType(data[primaryPlatform] || [], dataType);
        secondaryDevices = filterDevicesByType(data[secondaryPlatform] || [], dataType);
        
        renderPrimaryDevices();
        renderSecondaryDevices();
    } catch (error) {
        console.error('Error loading devices:', error);
        primaryList.innerHTML = '<div style="color: #ef4444;">Fehler beim Laden</div>';
        secondaryList.innerHTML = '<div style="color: #ef4444;">Fehler beim Laden</div>';
    }
}

function filterDevicesByType(devices, dataType) {
    // Filter devices based on data type
    const filters = {
        lighting: (d) => d.class === 'light' || d.capabilities?.includes('onoff'),
        temperature: (d) => d.class === 'sensor' && d.capabilities?.includes('measure_temperature'),
        heating: (d) => d.class === 'thermostat' || d.class === 'heater',
        windows: (d) => d.class === 'windowcoverings' || d.class === 'sensor' && d.capabilities?.includes('alarm_contact'),
        bathroom: (d) => d.zone?.name?.toLowerCase().includes('bad') || d.zone?.name?.toLowerCase().includes('bath')
    };
    
    const filter = filters[dataType];
    return filter ? devices.filter(filter) : devices;
}

function renderPrimaryDevices() {
    const list = document.getElementById('primary-devices-list');
    
    if (primaryDevices.length === 0) {
        list.innerHTML = '<div style="color: #6b7280; text-align: center; padding: 20px;">Keine Geräte gefunden</div>';
        return;
    }
    
    let html = '';
    primaryDevices.forEach(device => {
        html += `
            <div class="device-item" style="cursor: default;">
                <div style="flex: 1;">
                    <div style="font-weight: 600; font-size: 14px;">${device.name}</div>
                    <div style="font-size: 12px; color: #6b7280;">${device.zone?.name || 'Kein Raum'}</div>
                </div>
                <span style="color: #10b981; font-size: 12px;">✓ Standard</span>
            </div>
        `;
    });
    
    list.innerHTML = html;
}

function renderSecondaryDevices() {
    const list = document.getElementById('secondary-devices-list');
    
    if (secondaryDevices.length === 0) {
        list.innerHTML = '<div style="color: #6b7280; text-align: center; padding: 20px;">Keine Geräte gefunden</div>';
        return;
    }
    
    let html = '';
    secondaryDevices.forEach(device => {
        const isSelected = deviceMappings[currentMappingType]?.[device.id];
        const mode = isSelected?.mode || 'replace';
        
        html += `
            <div class="device-item ${isSelected ? 'selected' : ''}" data-device-id="${device.id}" data-device-name="${device.name}">
                <input type="checkbox" class="device-checkbox" ${isSelected ? 'checked' : ''}>
                <div style="flex: 1;">
                    <div style="font-weight: 600; font-size: 14px;">${device.name}</div>
                    <div style="font-size: 12px; color: #6b7280;">${device.zone?.name || 'Kein Raum'}</div>
                </div>
                ${isSelected ? `
                    <select class="device-mode-select" style="padding: 4px 8px; border: 1px solid #e5e7eb; border-radius: 4px; font-size: 12px;">
                        <option value="replace" ${mode === 'replace' ? 'selected' : ''}>Ersetzen</option>
                        <option value="additional" ${mode === 'additional' ? 'selected' : ''}>Zusätzlich</option>
                    </select>
                ` : ''}
            </div>
        `;
    });
    
    list.innerHTML = html;
    
    // Add click handlers
    list.querySelectorAll('.device-item').forEach(item => {
        const checkbox = item.querySelector('.device-checkbox');
        const deviceId = item.getAttribute('data-device-id');
        const deviceName = item.getAttribute('data-device-name');
        
        item.addEventListener('click', (e) => {
            if (e.target.classList.contains('device-mode-select')) return;
            
            checkbox.checked = !checkbox.checked;
            toggleDeviceMapping(deviceId, deviceName, checkbox.checked);
        });
        
        checkbox.addEventListener('change', (e) => {
            e.stopPropagation();
            toggleDeviceMapping(deviceId, deviceName, e.target.checked);
        });
        
        const modeSelect = item.querySelector('.device-mode-select');
        if (modeSelect) {
            modeSelect.addEventListener('change', (e) => {
                e.stopPropagation();
                updateDeviceMode(deviceId, e.target.value);
            });
        }
    });
}

function toggleDeviceMapping(deviceId, deviceName, isSelected) {
    if (!deviceMappings[currentMappingType]) {
        deviceMappings[currentMappingType] = {};
    }
    
    if (isSelected) {
        deviceMappings[currentMappingType][deviceId] = {
            name: deviceName,
            mode: 'replace'
        };
    } else {
        delete deviceMappings[currentMappingType][deviceId];
    }
    
    renderSecondaryDevices();
    updateMappingCount();
}

function updateDeviceMode(deviceId, mode) {
    if (deviceMappings[currentMappingType]?.[deviceId]) {
        deviceMappings[currentMappingType][deviceId].mode = mode;
    }
}

function updateMappingCount() {
    const count = Object.keys(deviceMappings[currentMappingType] || {}).length;
    document.getElementById('mapping-count').textContent = `${count} Gerät${count !== 1 ? 'e' : ''}`;
}

function filterSecondaryDevices() {
    const searchTerm = document.getElementById('secondary-device-search').value.toLowerCase();
    const items = document.querySelectorAll('#secondary-devices-list .device-item');
    
    items.forEach(item => {
        const deviceName = item.getAttribute('data-device-name').toLowerCase();
        if (deviceName.includes(searchTerm)) {
            item.style.display = 'flex';
        } else {
            item.style.display = 'none';
        }
    });
}

async function saveDeviceMapping() {
    const btn = document.getElementById('save-mapping');
    btn.disabled = true;
    btn.textContent = 'Speichere...';
    
    try {
        const response = await fetch('/api/config/device-mappings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                type: currentMappingType,
                mappings: deviceMappings[currentMappingType] || {}
            })
        });
        
        const data = await response.json();
        
        if (data.success) {
            // Update summary display
            const count = Object.keys(deviceMappings[currentMappingType] || {}).length;
            const summaryEl = document.getElementById(`${currentMappingType}-mapping-summary`);
            if (summaryEl) {
                if (count > 0) {
                    summaryEl.textContent = `✓ ${count} Gerät${count !== 1 ? 'e' : ''} von sekundärer Plattform`;
                    summaryEl.style.display = 'block';
                } else {
                    summaryEl.style.display = 'none';
                }
            }
            
            closeDeviceMappingModal();
        } else {
            alert('[FEHLER] ' + data.error);
        }
    } catch (error) {
        alert('[FEHLER] ' + error.message);
    } finally {
        btn.disabled = false;
        btn.textContent = 'Zuordnung speichern';
    }
}
