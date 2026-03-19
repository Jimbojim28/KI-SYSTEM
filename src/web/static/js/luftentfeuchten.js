// Bathroom Automation JavaScript

let allRooms = [];
let selectedRoomId = '';

// Countdown Timer
let countdownInterval = null;
let countdownSeconds = 0;

// ===== TAB VISIBILITY MANAGEMENT =====
// Pausiere Polling wenn Tab nicht sichtbar ist

const PollingManager = {
    statusInterval: null,
    liveStatusInterval: null,
    isPageVisible: true,
    
    init() {
        document.addEventListener('visibilitychange', () => {
            this.isPageVisible = document.visibilityState === 'visible';
            
            if (this.isPageVisible) {
                // Tab wieder sichtbar - sofort aktualisieren und Intervals neu starten
                console.log('Tab wieder sichtbar - aktualisiere Daten');
                this.restartPolling();
            } else {
                // Tab versteckt - Polling pausieren
                console.log('Tab versteckt - pausiere Polling');
                this.pausePolling();
            }
        });
    },
    
    pausePolling() {
        if (this.statusInterval) {
            clearInterval(this.statusInterval);
            this.statusInterval = null;
        }
        if (this.liveStatusInterval) {
            clearInterval(this.liveStatusInterval);
            this.liveStatusInterval = null;
        }
    },
    
    restartPolling() {
        // Stoppe erst alle laufenden Intervals
        this.pausePolling();
        
        // Sofort Daten laden
        loadStatus();
        loadLiveSensorStatus();
        
        // Intervals neu starten
        this.statusInterval = setInterval(loadStatus, 10000);
        this.liveStatusInterval = setInterval(loadLiveSensorStatus, 5000);
    },
    
    // Starte initiales Polling
    startInitialPolling() {
        this.statusInterval = setInterval(loadStatus, 10000);
        this.liveStatusInterval = setInterval(loadLiveSensorStatus, 5000);
    }
};

// ===== MAIN TAB NAVIGATION =====

/**
 * Initialisiere Tab-Navigation
 */
function initMainTabs() {
    const tabButtons = document.querySelectorAll('.main-tab-btn');

    tabButtons.forEach(button => {
        button.addEventListener('click', () => {
            const targetTab = button.dataset.mainTab;
            switchMainTab(targetTab);
        });
    });
}

/**
 * Wechsle zu einem bestimmten Tab
 */
function switchMainTab(tabName) {
    // Entferne active Klasse von allen Buttons und Contents
    document.querySelectorAll('.main-tab-btn').forEach(btn => {
        btn.classList.remove('active');
    });
    document.querySelectorAll('.main-tab-content').forEach(content => {
        content.classList.remove('active');
    });

    // Aktiviere den ausgewählten Tab
    const activeButton = document.querySelector(`.main-tab-btn[data-main-tab="${tabName}"]`);
    const activeContent = document.getElementById(`main-tab-${tabName}`);

    if (activeButton) activeButton.classList.add('active');
    if (activeContent) activeContent.classList.add('active');

    // Speichere aktiven Tab in localStorage
    localStorage.setItem('bathroom_active_main_tab', tabName);
}

/**
 * Stelle letzten aktiven Tab wieder her
 */
function restoreLastMainTab() {
    const lastTab = localStorage.getItem('bathroom_active_main_tab');
    if (lastTab) {
        switchMainTab(lastTab);
    }
}

// ===== END MAIN TAB NAVIGATION =====

// Lade alle Räume (nutze zentrale Settings-API)
async function loadRooms() {
    try {
        const roomsData = await fetchJSON('/api/rooms/settings');
        if (!roomsData) return; // Null bei Netzwerkfehler
        allRooms = roomsData.rooms || [];
        populateRoomSelect();
    } catch (error) {
        console.error('Error loading rooms:', error);
    }
}

// Fülle Raum-Auswahl
function populateRoomSelect() {
    const select = document.getElementById('room-select');
    if (!select) return;

    // Keep the first "-- Raum auswählen --" option
    const firstOption = select.options[0];
    select.innerHTML = '';
    select.appendChild(firstOption);

    // Sortiere Räume alphabetisch
    const sortedRooms = [...allRooms].sort((a, b) => a.name.localeCompare(b.name));

    sortedRooms.forEach(room => {
        const option = document.createElement('option');
        option.value = room.id;
        option.textContent = `${room.icon || '🏠'} ${room.name}`;
        select.appendChild(option);
    });
}

// Lade Konfiguration
async function loadConfig() {
    try {
        const data = await fetchJSON('/api/luftentfeuchten/config');

        if (!data) return; // Null bei Netzwerkfehler
        
        if (data.config) {
            const config = data.config;

            // Raum
            if (config.room_id) {
                const select = document.getElementById('room-select');
                if (select) select.value = config.room_id;
                selectedRoomId = config.room_id;
            }

            // Schwellwerte
            setSlider('humidity-high', config.humidity_threshold_high || 70);
            setSlider('humidity-low', config.humidity_threshold_low || 60);
            setSlider('dehumidifier-delay', config.dehumidifier_delay || 5);
            setSlider('dehumidifier-cooldown', config.dehumidifier_cooldown ?? 15);
            setSlider('max-dehumidifier-runtime', config.max_dehumidifier_runtime || 120);
            setSlider('force-off-humidity', config.force_off_humidity || 50);

            // Heizung
            setSlider('target-temperature', config.target_temperature || 22);
            setSlider('heating-boost-delta', config.heating_boost_delta || 1);
            setSlider('frost-protection-temp', config.frost_protection_temperature || 12);
            const heatingBoostEnabled = document.getElementById('heating-boost-enabled');
            if (heatingBoostEnabled) {
                heatingBoostEnabled.checked = config.heating_boost_enabled !== false; // Default: true
                setupHeatingBoostToggle(); // Trigger toggle logic
            }

            // Sensor-Invertierung (Tab: Erweitert)
            const invertDoorSensor = document.getElementById('invert-door-sensor');
            const invertWindowSensor = document.getElementById('invert-window-sensor');

            if (invertDoorSensor) invertDoorSensor.checked = config.invert_door_sensor || false;
            if (invertWindowSensor) invertWindowSensor.checked = config.invert_window_sensor || false;

            // Energie-Werte (Tab: Erweitert)
            const dehumWattage = document.getElementById('dehumidifier-wattage');
            const energyPrice = document.getElementById('energy-price');

            if (dehumWattage) dehumWattage.value = config.dehumidifier_wattage || 400;
            if (energyPrice) energyPrice.value = config.energy_price_per_kwh || 0.30;

            // Enabled
            document.getElementById('bathroom-enabled').checked = config.enabled || false;
        }
        

    } catch (error) {
        console.error('Error loading bathroom config:', error);
    }
}

function setSlider(sliderId, value) {
    const slider = document.getElementById(sliderId);
    if (slider) {
        slider.value = value;
        updateSliderValue(sliderId);
    }
}

// Speichere Konfiguration
async function saveConfig() {
    try {
        const roomId = document.getElementById('room-select').value;
        
        const config = {
            enabled: document.getElementById('bathroom-enabled').checked,
            room_id: roomId,
            humidity_threshold_high: parseFloat(document.getElementById('humidity-high').value),
            humidity_threshold_low: parseFloat(document.getElementById('humidity-low').value),
            dehumidifier_delay: parseInt(document.getElementById('dehumidifier-delay').value),
            dehumidifier_cooldown: parseInt(document.getElementById('dehumidifier-cooldown').value),
            max_dehumidifier_runtime: parseInt(document.getElementById('max-dehumidifier-runtime').value),
            force_off_humidity: parseFloat(document.getElementById('force-off-humidity').value),
            // Heizung
            target_temperature: parseFloat(document.getElementById('target-temperature').value),
            heating_boost_enabled: document.getElementById('heating-boost-enabled').checked,
            heating_boost_delta: parseFloat(document.getElementById('heating-boost-delta').value),
            frost_protection_temperature: parseFloat(document.getElementById('frost-protection-temp').value),
            // Sensor-Invertierung
            invert_door_sensor: document.getElementById('invert-door-sensor') ? document.getElementById('invert-door-sensor').checked : false,
            invert_window_sensor: document.getElementById('invert-window-sensor') ? document.getElementById('invert-window-sensor').checked : false,
            // Energie-Werte (nur Luftentfeuchter, keine Heizung bei Zentralheizung)
            dehumidifier_wattage: parseFloat(document.getElementById('dehumidifier-wattage').value),
            energy_price_per_kwh: parseFloat(document.getElementById('energy-price').value)
        };

        // Validierung
        if (!config.room_id) {
            alert('Bitte wählen Sie einen Raum aus!');
            return;
        }

        const result = await postJSON('/api/luftentfeuchten/config', { config });

        if (result.success) {
            showToast('✅ Konfiguration gespeichert!', 'success');
            selectedRoomId = roomId;
            
            loadStatus();
            // Energie-Stats neu laden
            loadEnergyStats();
            // Live-Status neu laden (um neue Geräte anzuzeigen)
            loadLiveSensorStatus();
        }
    } catch (error) {
        console.error('Error saving config:', error);
        showToast('❌ Fehler beim Speichern', 'error');
    }
}

// Lade Status
async function loadStatus() {
    try {
        const data = await fetchJSON('/api/luftentfeuchten/status');

        // Wenn null zurückgegeben wurde (Tab nicht sichtbar), überspringe Update
        if (!data) return;

        if (data.status) {
            const status = data.status;

            // Dusche erkannt
            if (status.shower_detected) {
                document.getElementById('shower-status').textContent = 'Ja - Dusche läuft!';
                document.getElementById('shower-status-icon').textContent = '🚿';
            } else {
                document.getElementById('shower-status').textContent = 'Nein';
                document.getElementById('shower-status-icon').textContent = '⏸️';
            }

            // Luftentfeuchter
            const countdownDiv = document.getElementById('dehumidifier-countdown');
            if (status.dehumidifier_running) {
                document.getElementById('dehumidifier-status').textContent = 'An';
                document.getElementById('dehumidifier-status-icon').textContent = '💨';
                
                // Prüfe ob Countdown angezeigt werden soll
                if (status.dehumidifier_shutdown_in_seconds && status.dehumidifier_shutdown_in_seconds > 0) {
                    updateCountdown(status.dehumidifier_shutdown_in_seconds);
                    countdownDiv.style.display = 'block';
                } else if (status.current_humidity !== null && status.thresholds) {
                    const humidityLow = status.thresholds.humidity_low;
                    if (status.current_humidity < humidityLow) {
                        // Luftfeuchtigkeit unter Schwellwert - wird bald ausschalten
                        // Fallback: Zeige 5 Minuten wenn Backend keine Zeit liefert
                        updateCountdown(300);
                        countdownDiv.style.display = 'block';
                    } else {
                        countdownDiv.style.display = 'none';
                    }
                } else {
                    countdownDiv.style.display = 'none';
                }
            } else {
                document.getElementById('dehumidifier-status').textContent = 'Aus';
                document.getElementById('dehumidifier-status-icon').textContent = '⏸️';
                countdownDiv.style.display = 'none';
            }

            // Luftfeuchtigkeit
            if (status.current_humidity !== null) {
                document.getElementById('current-humidity').textContent = `${status.current_humidity.toFixed(1)}%`;
            }

            // Temperatur
            if (status.current_temperature !== null) {
                document.getElementById('current-temperature').textContent = `${status.current_temperature.toFixed(1)}°C`;
            }
        }
    } catch (error) {
        console.error('Error loading status:', error);
    }
}

// Test-Funktion
async function testAutomation() {
    try {
        const result = await postJSON('/api/luftentfeuchten/test', {});

        if (result.success) {
            alert(`Test erfolgreich!\n\nAktionen: ${result.actions.length}\n${result.message || ''}`);
            loadStatus();
        }
    } catch (error) {
        console.error('Error testing automation:', error);
        alert('Fehler beim Test');
    }
}

// Geräte-Test (Luftentfeuchter/Heizung für 30s einschalten)
async function testDevice(deviceType) {
    const resultDiv = document.getElementById('test-result');
    const button = document.getElementById(`test-${deviceType}`);
    const deviceName = deviceType === 'dehumidifier' ? 'Luftentfeuchter' : 'Heizung';
    
    // Button deaktivieren während Test läuft
    if (button) {
        button.disabled = true;
        button.innerHTML = `<span class="spinner"></span> ${deviceName} wird getestet...`;
    }
    
    // Zeige "läuft" Status
    resultDiv.style.display = 'block';
    resultDiv.innerHTML = `
        <div style="padding: 15px; background: #eff6ff; border-left: 4px solid #3b82f6; border-radius: 6px;">
            <div style="display: flex; align-items: center; gap: 10px;">
                <div class="spinner"></div>
                <div>
                    <strong>🧪 Test läuft...</strong>
                    <p style="margin: 5px 0 0 0; font-size: 0.9em; color: #6b7280;">
                        ${deviceName} wird für 30 Sekunden eingeschaltet.
                    </p>
                </div>
            </div>
        </div>
    `;
    
    try {
        const result = await postJSON('/api/luftentfeuchten/test-device', {
            device_type: deviceType,
            duration: 30
        });

        if (result.success) {
            resultDiv.innerHTML = `
                <div style="padding: 15px; background: #d1fae5; border-left: 4px solid #10b981; border-radius: 6px;">
                    <div style="display: flex; align-items: flex-start; gap: 10px;">
                        <span style="font-size: 1.5em;">✅</span>
                        <div>
                            <strong style="color: #065f46;">Test erfolgreich!</strong>
                            <p style="margin: 5px 0 0 0; font-size: 0.9em; color: #047857;">
                                ${result.message}
                            </p>
                            <p style="margin: 8px 0 0 0; font-size: 0.85em; color: #6b7280;">
                                Gerät: <code>${result.device_name || result.device_id}</code><br>
                                Vorheriger Status: ${result.previous_state}
                            </p>
                        </div>
                    </div>
                </div>
            `;
            
            // Countdown anzeigen
            let countdown = result.test_duration || 30;
            const countdownInterval = setInterval(() => {
                countdown--;
                if (countdown <= 0) {
                    clearInterval(countdownInterval);
                    resultDiv.innerHTML += `
                        <div style="margin-top: 10px; padding: 10px; background: #f3f4f6; border-radius: 6px; font-size: 0.9em; color: #6b7280;">
                            ✓ ${deviceName} wurde automatisch ausgeschaltet.
                        </div>
                    `;
                } else {
                    const countdownEl = document.getElementById('test-countdown');
                    if (countdownEl) {
                        countdownEl.textContent = countdown;
                    }
                }
            }, 1000);
            
            // Füge Countdown hinzu
            resultDiv.querySelector('div > div > div:last-child').innerHTML += `
                <p style="margin: 8px 0 0 0; font-size: 0.9em; color: #3b82f6;">
                    ⏱️ Automatisches Ausschalten in <strong id="test-countdown">${countdown}</strong> Sekunden...
                </p>
            `;
            
        } else {
            throw new Error(result.error || 'Unbekannter Fehler');
        }
    } catch (error) {
        console.error('Error testing device:', error);
        
        // Fehlerdetails extrahieren
        let errorMessage = error.message || 'Unbekannter Fehler';
        let errorDetails = '';
        
        if (error.response) {
            try {
                const errData = await error.response.json();
                errorMessage = errData.error || errorMessage;
                errorDetails = errData.details || '';
            } catch (e) {}
        }
        
        resultDiv.innerHTML = `
            <div style="padding: 15px; background: #fee2e2; border-left: 4px solid #ef4444; border-radius: 6px;">
                <div style="display: flex; align-items: flex-start; gap: 10px;">
                    <span style="font-size: 1.5em;">❌</span>
                    <div>
                        <strong style="color: #991b1b;">Test fehlgeschlagen</strong>
                        <p style="margin: 5px 0 0 0; font-size: 0.9em; color: #dc2626;">
                            ${errorMessage}
                        </p>
                        ${errorDetails ? `
                            <details style="margin-top: 10px;">
                                <summary style="cursor: pointer; color: #6b7280; font-size: 0.85em;">Technische Details</summary>
                                <pre style="margin: 8px 0 0 0; padding: 10px; background: #fef2f2; border-radius: 4px; font-size: 0.75em; overflow-x: auto; white-space: pre-wrap;">${errorDetails}</pre>
                            </details>
                        ` : ''}
                        <p style="margin: 10px 0 0 0; font-size: 0.85em; color: #6b7280;">
                            💡 <strong>Mögliche Lösungen:</strong><br>
                            • Prüfe ob die Geräte-ID korrekt ist<br>
                            • Prüfe ob das Gerät eingeschaltet und erreichbar ist<br>
                            • Prüfe die Verbindung zu Home Assistant/Homey
                        </p>
                    </div>
                </div>
            </div>
        `;
    } finally {
        // Button wieder aktivieren
        if (button) {
            button.disabled = false;
            button.innerHTML = deviceType === 'dehumidifier' 
                ? '<span>💨</span><span>Luftentfeuchter testen</span>'
                : '<span>🔥</span><span>Heizung testen</span>';
        }
    }
}

// Slider-Updates
function updateSliderValue(sliderId) {
    const slider = document.getElementById(sliderId);
    const valueSpan = document.getElementById(`${sliderId}-value`);

    if (!slider || !valueSpan) return;

    let value = slider.value;
    let suffix = '';

    if (sliderId.includes('humidity') || sliderId === 'force-off-humidity') {
        suffix = '%';
    } else if (sliderId.includes('temperature')) {
        suffix = '°C';
    } else if (sliderId.includes('delay') || sliderId.includes('runtime') || sliderId.includes('cooldown')) {
        suffix = ' Min';
    } else if (sliderId === 'heating-boost-delta') {
        suffix = '°C';
        value = '+' + value; // Plus-Zeichen für Erhöhung
    } else if (sliderId === 'rate-threshold-luftentfeuchten') {
        suffix = ' %/min';
    }

    valueSpan.textContent = value + suffix;
}

// Setup Slider-Listeners
function setupSliders() {
    const sliders = [
        'humidity-high', 
        'humidity-low', 
        'target-temperature', 
        'dehumidifier-delay',
        'dehumidifier-cooldown',
        'heating-boost-delta', 
        'max-dehumidifier-runtime', 
        'force-off-humidity',
        'rate-threshold-luftentfeuchten'
    ];
    sliders.forEach(sliderId => {
        const slider = document.getElementById(sliderId);
        if (slider) {
            slider.addEventListener('input', () => updateSliderValue(sliderId));
            updateSliderValue(sliderId);
        }
    });
}

// Setup Heating Boost Toggle
function setupHeatingBoostToggle() {
    const toggle = document.getElementById('heating-boost-enabled');
    const boostGroup = document.getElementById('boost-temp-group');

    if (toggle && boostGroup) {
        toggle.addEventListener('change', () => {
            if (toggle.checked) {
                boostGroup.style.display = 'block';
            } else {
                boostGroup.style.display = 'none';
            }
        });

        // Initial state
        if (toggle.checked) {
            boostGroup.style.display = 'block';
        } else {
            boostGroup.style.display = 'none';
        }
    }
}

// Live Sensor Status laden
let liveSensorInterval = null;

async function loadLiveSensorStatus() {
    try {
        const data = await fetchJSON('/api/luftentfeuchten/live-status');

        // Wenn null zurückgegeben wurde (Netzwerkfehler), überspringe Update
        if (!data) return;

        if (!data.devices || Object.keys(data.devices).length === 0) {
            // Keine Geräte konfiguriert - verstecke Live-Card
            document.getElementById('live-sensors-card').style.display = 'none';
            return;
        }

        // Zeige Live-Card
        document.getElementById('live-sensors-card').style.display = 'block';

        const devices = data.devices;

        // Humidity Sensor
        if (devices.humidity_sensor) {
            const card = document.getElementById('live-humidity-card');
            card.style.display = 'block';
            document.getElementById('live-humidity-name').textContent = devices.humidity_sensor.name;
            const value = devices.humidity_sensor.value;
            if (value !== null && value !== undefined) {
                document.getElementById('live-humidity-value').textContent = `${value.toFixed(1)}%`;
                document.getElementById('live-humidity-meta').textContent = devices.humidity_sensor.available ? 'Online' : 'Offline';
            } else {
                document.getElementById('live-humidity-value').textContent = '--';
                document.getElementById('live-humidity-meta').textContent = 'Keine Daten';
            }
        } else {
            document.getElementById('live-humidity-card').style.display = 'none';
        }

        // Temperature Sensor
        if (devices.temperature_sensor) {
            const card = document.getElementById('live-temp-card');
            card.style.display = 'block';
            document.getElementById('live-temp-name').textContent = devices.temperature_sensor.name;
            const value = devices.temperature_sensor.value;
            if (value !== null && value !== undefined) {
                document.getElementById('live-temp-value').textContent = `${value.toFixed(1)}°C`;
                document.getElementById('live-temp-meta').textContent = devices.temperature_sensor.available ? 'Online' : 'Offline';
            } else {
                document.getElementById('live-temp-value').textContent = '--';
                document.getElementById('live-temp-meta').textContent = 'Keine Daten';
            }
        } else {
            document.getElementById('live-temp-card').style.display = 'none';
        }

        // Door Sensor
        if (devices.door_sensor) {
            const card = document.getElementById('live-door-card');
            card.style.display = 'block';
            document.getElementById('live-door-name').textContent = devices.door_sensor.name;
            const valueEl = document.getElementById('live-door-value');
            const iconEl = document.getElementById('live-door-icon');

            if (devices.door_sensor.is_open) {
                valueEl.textContent = 'Offen';
                valueEl.className = 'sensor-value door-open';
                iconEl.textContent = '🚪🔓';
            } else {
                valueEl.textContent = 'Geschlossen';
                valueEl.className = 'sensor-value door-closed';
                iconEl.textContent = '🚪🔒';
            }
            document.getElementById('live-door-meta').textContent = devices.door_sensor.available ? 'Online' : 'Offline';
        } else {
            document.getElementById('live-door-card').style.display = 'none';
        }

        // Window Sensor
        if (devices.window_sensor) {
            const card = document.getElementById('live-window-card');
            card.style.display = 'block';
            document.getElementById('live-window-name').textContent = devices.window_sensor.name;
            const valueEl = document.getElementById('live-window-value');
            const iconEl = document.getElementById('live-window-icon');

            if (devices.window_sensor.is_open) {
                valueEl.textContent = 'Offen';
                valueEl.className = 'sensor-value door-open';
                iconEl.textContent = '🪟🔓';
            } else {
                valueEl.textContent = 'Geschlossen';
                valueEl.className = 'sensor-value door-closed';
                iconEl.textContent = '🪟🔒';
            }
            document.getElementById('live-window-meta').textContent = devices.window_sensor.available ? 'Online' : 'Offline';
        } else {
            document.getElementById('live-window-card').style.display = 'none';
        }

        // Motion Sensor
        if (devices.motion_sensor) {
            const card = document.getElementById('live-motion-card');
            card.style.display = 'block';
            document.getElementById('live-motion-name').textContent = devices.motion_sensor.name;
            const valueEl = document.getElementById('live-motion-value');
            const iconEl = document.getElementById('live-motion-icon');

            if (devices.motion_sensor.motion_detected) {
                valueEl.textContent = 'Bewegung erkannt!';
                valueEl.className = 'sensor-value motion-detected';
                iconEl.textContent = '👤✨';
            } else {
                valueEl.textContent = 'Keine Bewegung';
                valueEl.className = 'sensor-value';
                iconEl.textContent = '👤';
            }
            document.getElementById('live-motion-meta').textContent = devices.motion_sensor.available ? 'Online' : 'Offline';
        } else {
            document.getElementById('live-motion-card').style.display = 'none';
        }

        // Dehumidifier
        if (devices.dehumidifier) {
            const card = document.getElementById('live-dehumidifier-card');
            card.style.display = 'block';
            document.getElementById('live-dehumidifier-name').textContent = devices.dehumidifier.name;
            const valueEl = document.getElementById('live-dehumidifier-value');
            const iconEl = document.getElementById('live-dehumidifier-icon');

            if (devices.dehumidifier.is_on) {
                valueEl.textContent = 'An';
                valueEl.style.color = '#10b981';
                iconEl.textContent = '💨';
            } else {
                valueEl.textContent = 'Aus';
                valueEl.style.color = '#6b7280';
                iconEl.textContent = '💨';
            }
            document.getElementById('live-dehumidifier-meta').textContent = devices.dehumidifier.available ? 'Online' : 'Offline';
        } else {
            document.getElementById('live-dehumidifier-card').style.display = 'none';
        }

        // Heater
        if (devices.heater) {
            const card = document.getElementById('live-heater-card');
            card.style.display = 'block';
            document.getElementById('live-heater-name').textContent = devices.heater.name;

            // IST und SOLL Temperatur anzeigen
            const currentTemp = devices.heater.current_temp;
            const targetTemp = devices.heater.target_temp;

            let displayText = '';
            if (currentTemp !== null && currentTemp !== undefined) {
                displayText = `IST: ${currentTemp.toFixed(1)}°C`;
            } else {
                displayText = 'IST: --°C';
            }

            if (targetTemp !== null && targetTemp !== undefined) {
                displayText += ` | SOLL: ${targetTemp.toFixed(1)}°C`;
            } else {
                displayText += ' | SOLL: --°C';
            }

            document.getElementById('live-heater-value').textContent = displayText;
            document.getElementById('live-heater-meta').textContent = devices.heater.available ? 'Online' : 'Offline';
        } else {
            document.getElementById('live-heater-card').style.display = 'none';
        }

    } catch (error) {
        console.error('Error loading live sensor status:', error);
    }
}

// Aktoren-Steuerung
async function controlActuator(deviceType, action) {
    try {
        const result = await postJSON('/api/luftentfeuchten/control', {
            device_type: deviceType,
            action: action
        });

        if (result.success) {
            // Zeige kurze Bestätigung
            const message = result.message || 'Befehl gesendet';
            showToast(message, 'success');

            // Lade sofort den neuen Status
            setTimeout(loadLiveSensorStatus, 500);
        } else {
            showToast(result.error || 'Fehler beim Steuern', 'error');
        }
    } catch (error) {
        console.error('Error controlling actuator:', error);
        showToast('Fehler beim Steuern des Geräts', 'error');
    }
}

// Toast-Nachricht anzeigen
function showToast(message, type = 'info') {
    // Erstelle Toast Element wenn nicht vorhanden
    let toastContainer = document.getElementById('toast-container');
    if (!toastContainer) {
        toastContainer = document.createElement('div');
        toastContainer.id = 'toast-container';
        toastContainer.style.cssText = 'position: fixed; top: 20px; right: 20px; z-index: 9999;';
        document.body.appendChild(toastContainer);
    }

    const toast = document.createElement('div');
    const bgColor = type === 'success' ? '#10b981' : type === 'error' ? '#ef4444' : '#3b82f6';
    toast.style.cssText = `
        background: ${bgColor};
        color: white;
        padding: 12px 20px;
        border-radius: 6px;
        margin-bottom: 10px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        animation: slideIn 0.3s ease;
    `;
    toast.textContent = message;

    toastContainer.appendChild(toast);

    // Entferne nach 3 Sekunden
    setTimeout(() => {
        toast.style.animation = 'slideOut 0.3s ease';
        setTimeout(() => toast.remove(), 300);
    }, 3000);
}

// Lade gelernte Parameter-Informationen
async function loadLearnedParams() {
    try {
        const data = await fetchJSON('/api/luftentfeuchten/learned-params');

        if (!data) return; // Null bei Netzwerkfehler
        
        const learnedParams = data.learned_params || {};
        const eventsCount = data.events_last_30_days || 0;
        const readyForOptimization = data.ready_for_optimization || false;

        // Prüfe ob irgendein Parameter gelernt wurde
        const hasLearnedParams = Object.values(learnedParams).some(p => p.is_learned);

        if (hasLearnedParams) {
            // Zeige Info-Box
            const infoBox = document.getElementById('learning-info-box');
            const infoText = document.getElementById('learning-info-text');
            const statusBadge = document.getElementById('learning-status-badge');

            if (infoBox && infoText) {
                let learnedCount = Object.values(learnedParams).filter(p => p.is_learned).length;

                infoText.innerHTML = `
                    Das System hat <strong>${learnedCount} Parameter</strong> aus <strong>${eventsCount} Events</strong> gelernt.
                    Die Werte werden automatisch verwendet und überschreiben die manuellen Einstellungen.
                `;
                infoBox.style.display = 'block';
            }

            if (statusBadge) {
                statusBadge.textContent = '🧠 Gelernte Werte aktiv';
                statusBadge.className = 'active';
                statusBadge.style.display = 'block';
            }

            // Zeige Parameter-Infos
            displayParamInfo('humidity_threshold_high', learnedParams.humidity_threshold_high);
            displayParamInfo('humidity_threshold_low', learnedParams.humidity_threshold_low);
            displayParamInfo('dehumidifier_delay', learnedParams.dehumidifier_delay);
        } else if (eventsCount > 0) {
            // Es gibt Events, aber noch keine gelernten Parameter
            const statusBadge = document.getElementById('learning-status-badge');
            if (statusBadge) {
                statusBadge.textContent = `📊 ${eventsCount} Events gesammelt`;
                statusBadge.className = 'inactive';
                statusBadge.style.display = 'block';
            }
        }

    } catch (error) {
        console.error('Error loading learned params:', error);
    }
}

// Zeige Info für einen einzelnen Parameter
function displayParamInfo(paramName, paramData) {
    if (!paramData || !paramData.is_learned) {
        return; // Kein gelernter Wert
    }

    // Map param name to UI element IDs
    const idMap = {
        'humidity_threshold_high': { source: 'humidity-high-source', info: 'humidity-high-learned-info' },
        'humidity_threshold_low': { source: 'humidity-low-source', info: 'humidity-low-learned-info' },
        'dehumidifier_delay': { source: 'delay-source', info: 'delay-learned-info' }
    };

    const ids = idMap[paramName];
    if (!ids) return;

    // Source Badge
    const sourceBadge = document.getElementById(ids.source);
    if (sourceBadge) {
        sourceBadge.textContent = '🧠 Gelernt';
        sourceBadge.className = 'param-source-badge learned';
        sourceBadge.style.display = 'inline-block';
    }

    // Detail Info
    const learnedInfo = document.getElementById(ids.info);
    if (learnedInfo) {
        const confidencePercent = Math.round(paramData.confidence * 100);
        const date = new Date(paramData.timestamp).toLocaleDateString('de-DE');

        learnedInfo.innerHTML = `
            ℹ️ Optimiert aus ${paramData.samples_used} Events
            (Konfidenz: ${confidencePercent}%, ${date})
        `;
        learnedInfo.style.display = 'block';
    }
}

// Reset gelernte Parameter
async function resetLearnedParams() {
    if (!confirm('Möchten Sie wirklich alle gelernten Parameter zurücksetzen?\n\nDas System wird dann wieder die manuell konfigurierten Werte verwenden.')) {
        return;
    }

    try {
        const response = await fetch('/api/luftentfeuchten/reset-learned', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });

        const data = await response.json();

        if (data.success) {
            showToast(`✅ ${data.message}`, 'success');

            // Verstecke Info-Box und Badges
            document.getElementById('learning-info-box').style.display = 'none';
            document.getElementById('learning-status-badge').style.display = 'none';

            // Verstecke alle Parameter-Infos
            document.querySelectorAll('.param-source-badge').forEach(el => el.style.display = 'none');
            document.querySelectorAll('.learned-param-info').forEach(el => el.style.display = 'none');

            // Neu laden nach kurzer Verzögerung
            setTimeout(() => {
                window.location.reload();
            }, 1500);
        } else {
            showToast('❌ Fehler beim Zurücksetzen', 'error');
        }
    } catch (error) {
        console.error('Error resetting learned params:', error);
        showToast('❌ Netzwerkfehler', 'error');
    }
}

// Lade Energie-Statistiken
async function loadEnergyStats() {
    try {
        const data = await fetchJSON('/api/luftentfeuchten/energy-stats?days=30');

        if (!data) return; // Null bei Netzwerkfehler
        
        document.getElementById('energy-stats-loading').style.display = 'none';
        document.getElementById('energy-stats-content').style.display = 'block';

        // Update UI
        document.getElementById('energy-runtime').textContent = data.dehumidifier.runtime_hours + ' h';
        document.getElementById('energy-kwh').textContent = data.total.kwh + ' kWh';
        document.getElementById('energy-cost').textContent = data.total.cost_eur.toFixed(2) + ' €';
        document.getElementById('energy-savings').textContent = data.comparison_always_on.savings_percent + '%';
        document.getElementById('energy-events-count').textContent = data.event_count;
        document.getElementById('energy-avg-runtime').textContent = data.per_event.avg_runtime_minutes.toFixed(1);
        document.getElementById('energy-avg-cost').textContent = data.per_event.avg_cost_eur.toFixed(3);

    } catch (error) {
        console.error('Error loading energy stats:', error);
        document.getElementById('energy-stats-loading').textContent = 'Fehler beim Laden der Statistiken';
    }
}

// Lade Alerts
async function loadAlerts() {
    try {
        const data = await fetchJSON('/api/luftentfeuchten/alerts?days=7');

        if (!data) return;

        if (data.alerts && data.alerts.length > 0) {
            // Filtere bestätigte Warnungen (via localStorage)
            const confirmedKey = 'bathroom_alerts_confirmed';
            const confirmed = JSON.parse(localStorage.getItem(confirmedKey) || '[]');

            const newAlerts = data.alerts.filter(a => {
                const sig = (a.title || '') + '|' + (a.message || '');
                return !confirmed.includes(sig);
            });

            if (newAlerts.length === 0) return;

            const alertsCard = document.getElementById('alerts-card');
            const alertsContent = document.getElementById('alerts-content');

            let html = '';
            newAlerts.forEach(alert => {
                html += `
                    <div class="alert-item severity-${alert.severity}">
                        <div class="alert-title">${alert.title}</div>
                        <div class="alert-message">${alert.message}</div>
                    </div>
                `;
            });

            alertsContent.innerHTML = html;
            alertsCard.style.display = 'block';

            // Bestätigen-Button: alle aktuellen Warnungen speichern
            const confirmBtn = document.getElementById('confirm-alerts-btn');
            if (confirmBtn) {
                confirmBtn.onclick = () => {
                    const sigs = data.alerts.map(a => (a.title || '') + '|' + (a.message || ''));
                    localStorage.setItem(confirmedKey, JSON.stringify(sigs));
                    alertsCard.style.display = 'none';
                };
            }
        }

    } catch (error) {
        console.error('Error loading alerts:', error);
    }
}

// Live-Preview
async function showPreview() {
    try {
        const modal = document.getElementById('preview-modal');
        const content = document.getElementById('preview-content');

        content.innerHTML = '<div style="text-align: center; padding: 20px;">Lade Preview...</div>';
        modal.style.display = 'flex';

        const response = await fetch('/api/luftentfeuchten/preview', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });

        const data = await response.json();

        if (data.error) {
            content.innerHTML = `<div class="alert-item severity-high">Fehler: ${data.error}</div>`;
            return;
        }

        // Build Preview HTML
        let html = '';

        // Current State
        html += `
            <div class="preview-section">
                <h4>📊 Aktueller Zustand</h4>
                <div style="display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px;">
                    <div><strong>Luftfeuchtigkeit:</strong> ${data.current_state.humidity || '--'}%</div>
                    <div><strong>Temperatur:</strong> ${data.current_state.temperature || '--'}°C</div>
                    <div><strong>Bewegung:</strong> ${data.current_state.motion_detected ? 'Ja' : 'Nein'}</div>
                    <div><strong>Tür:</strong> ${data.current_state.door_closed ? 'Geschlossen' : 'Offen'}</div>
                </div>
                ${data.current_state.shower_would_be_detected ? '<div style="margin-top: 10px; color: #3b82f6; font-weight: 600;">🚿 Dusche würde erkannt werden!</div>' : ''}
            </div>
        `;

        // Thresholds
        html += `
            <div class="preview-section">
                <h4>📏 Schwellwerte</h4>
                <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px;">
                    <div><strong>High:</strong> ${data.thresholds.humidity_high}%</div>
                    <div><strong>Low:</strong> ${data.thresholds.humidity_low}%</div>
                    <div><strong>Ziel-Temp:</strong> ${data.thresholds.target_temperature}°C</div>
                </div>
            </div>
        `;

        // Actions
        html += '<div class="preview-section"><h4>🎯 Was würde passieren?</h4>';

        // Dehumidifier Action
        const dehum = data.actions.dehumidifier;
        const dehumClass = dehum.action === 'turn_on' ? 'turn-on' : dehum.action === 'turn_off' ? 'turn-off' : 'no-change';
        html += `
            <div class="preview-action ${dehumClass}">
                <div>
                    <strong>💨 Luftentfeuchter:</strong><br>
                    <span style="font-size: 0.9em; color: #6b7280;">${dehum.reason}</span>
                </div>
                <div>
                    ${dehum.action === 'turn_on' ? '✅ EIN' : dehum.action === 'turn_off' ? '⏸️ AUS' : '➖ Keine Änderung'}
                </div>
            </div>
        `;

        // Heater Action
        if (data.actions.heater) {
            const heater = data.actions.heater;
            const heaterClass = heater.action === 'set_temperature' ? 'turn-on' : 'no-change';
            html += `
                <div class="preview-action ${heaterClass}">
                    <div>
                        <strong>🔥 Heizung:</strong><br>
                        <span style="font-size: 0.9em; color: #6b7280;">${heater.reason}</span>
                    </div>
                    <div>
                        ${heater.action === 'set_temperature' ? '🌡️ ' + heater.target_temperature + '°C' : '➖ Keine Änderung'}
                    </div>
                </div>
            `;
        }

        html += '</div>';

        // Execution Note
        if (!data.automation_enabled) {
            html += `
                <div style="background: #fef3c7; border-left: 4px solid #f59e0b; padding: 12px; border-radius: 6px; margin-top: 15px;">
                    <strong>⚠️ Hinweis:</strong> Automation ist deaktiviert. Aktionen werden nicht ausgeführt.
                </div>
            `;
        }

        content.innerHTML = html;

    } catch (error) {
        console.error('Error loading preview:', error);
        document.getElementById('preview-content').innerHTML = '<div class="alert-item severity-high">Fehler beim Laden der Preview</div>';
    }
}

// Setup Tab System
function setupTabs() {
    const tabButtons = document.querySelectorAll('.tab-btn');
    const tabContents = document.querySelectorAll('.tab-content');

    tabButtons.forEach(button => {
        button.addEventListener('click', () => {
            const targetTab = button.getAttribute('data-tab');

            // Deaktiviere alle Tabs
            tabButtons.forEach(btn => btn.classList.remove('active'));
            tabContents.forEach(content => content.classList.remove('active'));

            // Aktiviere gewählten Tab
            button.classList.add('active');
            document.getElementById(`tab-${targetTab}`).classList.add('active');
        });
    });
}

// Lade Datenstatistiken
async function loadDataStats() {
    try {
        const data = await fetchJSON('/api/luftentfeuchten/data-stats');

        if (!data) return; // Null bei Netzwerkfehler
        
        if (data.success) {
            // Events Count
            document.getElementById('data-events-count').textContent =
                data.events_count.toLocaleString('de-DE');

            // Event Measurements Count
            document.getElementById('data-measurements-count').textContent =
                data.measurements_count.toLocaleString('de-DE');

            // Continuous Measurements Count (alle 60s)
            document.getElementById('data-continuous-count').textContent =
                data.continuous_measurements_count.toLocaleString('de-DE');

            // Actions Count
            document.getElementById('data-actions-count').textContent =
                data.actions_count.toLocaleString('de-DE');

            // Data Age
            if (data.data_age) {
                document.getElementById('data-age').textContent = data.data_age;
                document.getElementById('data-date-range').textContent = data.date_range;
            } else {
                document.getElementById('data-age').textContent = '0 Tage';
                document.getElementById('data-date-range').textContent = 'Keine Daten';
            }
        }
    } catch (error) {
        console.error('Error loading data stats:', error);
        // Zeige Fehler an
        document.getElementById('data-events-count').textContent = 'Fehler';
        document.getElementById('data-measurements-count').textContent = 'Fehler';
        document.getElementById('data-continuous-count').textContent = 'Fehler';
        document.getElementById('data-actions-count').textContent = 'Fehler';
        document.getElementById('data-age').textContent = 'Fehler';
    }
}

// === Wochenübersicht: Tatsächlich vs. Vorhergesagt ===

let weeklyOverviewData = null;

async function loadWeeklyOverview() {
    try {
        const response = await fetchJSON('/api/luftentfeuchten/weekly-overview');
        if (!response) return; // Null bei Netzwerkfehler
        weeklyOverviewData = response;
        renderWeeklyOverview();
    } catch (error) {
        console.error('Error loading weekly overview:', error);
        const heatmapEl = document.getElementById('weekly-heatmap');
        if (heatmapEl) {
            heatmapEl.innerHTML = `
                <div style="color: #ef4444; padding: 20px; text-align: center;">
                    ⚠️ Fehler beim Laden der Wochenübersicht: ${error.message}
                </div>
            `;
        }
    }
}

function renderWeeklyOverview() {
    if (!weeklyOverviewData || !weeklyOverviewData.success) {
        const heatmapEl = document.getElementById('weekly-heatmap');
        if (heatmapEl) {
            heatmapEl.innerHTML = `
                <div style="color: #6b7280; padding: 20px; text-align: center;">
                    Keine Daten verfügbar
                </div>
            `;
        }
        return;
    }

    const { actual_events, predictions_by_day, actual_by_day_hour, accuracy_metrics, sufficient_data } = weeklyOverviewData;

    // Aktualisiere Genauigkeitsmetriken
    const dayAccuracyEl = document.getElementById('day-accuracy');
    const hourAccuracyEl = document.getElementById('hour-accuracy');
    const analyzedEventsEl = document.getElementById('analyzed-events');

    if (dayAccuracyEl) {
        dayAccuracyEl.textContent = sufficient_data ? `${accuracy_metrics.overall_accuracy}%` : 'N/A';
    }
    if (hourAccuracyEl) {
        hourAccuracyEl.textContent = sufficient_data ? `${accuracy_metrics.hour_accuracy}%` : 'N/A';
    }
    if (analyzedEventsEl) {
        analyzedEventsEl.textContent = accuracy_metrics.total_events || 0;
    }

    // Erstelle Heatmap mit erweiterten Daten
    renderWeeklyHeatmap(
        actual_by_day_hour, 
        predictions_by_day, 
        accuracy_metrics, 
        sufficient_data,
        weeklyOverviewData.future_predictions || {},
        weeklyOverviewData.current_weekday,
        weeklyOverviewData.current_hour,
        weeklyOverviewData.typical_times || [],
        weeklyOverviewData.pattern_stability || {}
    );
}

function renderWeeklyHeatmap(actualByDayHour, predictionsByDay, accuracyMetrics, sufficientData, 
                              futurePredictions, currentWeekday, currentHour, typicalTimes, patternStability) {
    const weekdayNames = ['Montag', 'Dienstag', 'Mittwoch', 'Donnerstag', 'Freitag', 'Samstag', 'Sonntag'];
    const container = document.getElementById('weekly-heatmap');

    if (!container) return;
    
    // Bestimme aktuellen Wochentag (falls nicht übergeben)
    if (currentWeekday === undefined) {
        currentWeekday = new Date().getDay();
        // JavaScript: Sonntag=0, wir brauchen Montag=0
        currentWeekday = currentWeekday === 0 ? 6 : currentWeekday - 1;
    }
    if (currentHour === undefined) {
        currentHour = new Date().getHours();
    }

    // Erstelle Heatmap-HTML
    let html = '<div style="display: grid; grid-template-columns: auto repeat(24, 1fr); gap: 2px; font-size: 0.8em;">';

    // Header-Zeile (Stunden)
    html += '<div style="padding: 5px; font-weight: bold;"></div>'; // Ecke oben links

    for (let hour = 0; hour < 24; hour++) {
        // Markiere aktuelle Stunde
        const isCurrentHour = hour === currentHour;
        html += `<div style="padding: 5px; text-align: center; font-weight: bold; font-size: 0.75em; 
            color: ${isCurrentHour ? '#ef4444' : '#6b7280'}; 
            ${isCurrentHour ? 'background: #fef2f2; border-radius: 4px;' : ''}">
            ${hour}${isCurrentHour ? '⏰' : ''}
        </div>`;
    }

    // Zeilen für jeden Wochentag
    for (let day = 0; day < 7; day++) {
        const isToday = day === currentWeekday;
        const isFuture = day > currentWeekday;
        const futurePred = futurePredictions ? futurePredictions[day] : null;
        
        // Wochentagsname mit Markierung für heute
        html += `<div style="padding: 8px; font-weight: 600; color: ${isToday ? '#ef4444' : '#374151'}; 
            display: flex; align-items: center; gap: 6px;
            ${isToday ? 'background: linear-gradient(90deg, #fef2f2, transparent); border-radius: 4px;' : ''}">
            ${weekdayNames[day]}${isToday ? ' <span style="font-size: 0.75em; background: #ef4444; color: white; padding: 2px 6px; border-radius: 10px;">Heute</span>' : ''}
            ${isFuture && futurePred ? ' <span style="font-size: 0.7em; color: #8b5cf6;">🔮</span>' : ''}
        </div>`;

        // Stunden-Zellen
        for (let hour = 0; hour < 24; hour++) {
            const key = `${day}_${hour}`;
            const hasActual = actualByDayHour[key] && actualByDayHour[key].length > 0;
            const prediction = predictionsByDay[day];
            
            // Prüfe ob diese Stunde in der Zukunft liegt
            const isFutureHour = (day > currentWeekday) || (day === currentWeekday && hour > currentHour);
            const isPastHour = (day < currentWeekday) || (day === currentWeekday && hour <= currentHour);

            // Prüfe ob diese Stunde vorhergesagt wurde (historisch)
            let hasPrediction = false;
            let predictionProb = 0;
            if (prediction && prediction.predicted_times) {
                const pred = prediction.predicted_times.find(p => Math.abs(p.hour - hour) <= 1);
                hasPrediction = !!pred;
                predictionProb = pred ? pred.probability : 0;
            }
            
            // Prüfe Zukunftsvorhersage
            let hasFuturePrediction = false;
            let futurePredConf = 0;
            if (isFutureHour && futurePred && futurePred.predictions) {
                const fp = futurePred.predictions.find(p => Math.abs(p.hour - hour) <= 1);
                hasFuturePrediction = !!fp;
                futurePredConf = fp ? fp.confidence : 0;
            }

            // Farbe basierend auf Status
            let bgColor = '#f3f4f6';  // Grau (leer)
            let borderColor = '#e5e7eb';
            let content = '';
            let tooltip = `${weekdayNames[day]} ${hour}:00`;
            let animation = '';

            if (hasActual && hasPrediction) {
                // Beide: Übereinstimmung (Grün)
                bgColor = '#10b981';
                borderColor = '#059669';
                content = '✓';
                const events = actualByDayHour[key];
                tooltip = `${weekdayNames[day]} ${hour}:00\n✓ Vorhersage korrekt!\n${events.length} Event(s)`;
            } else if (hasActual) {
                // Nur tatsächlich (Blau)
                bgColor = '#3b82f6';
                borderColor = '#2563eb';
                content = '●';
                const events = actualByDayHour[key];
                const avgDuration = events.reduce((sum, e) => sum + (e.duration || 0), 0) / events.length;
                tooltip = `${weekdayNames[day]} ${hour}:00\nTatsächlich: ${events.length} Event(s)\nØ Dauer: ${Math.round(avgDuration)} min`;
            } else if (hasFuturePrediction) {
                // Zukünftige Vorhersage (Lila mit Animation)
                bgColor = 'linear-gradient(135deg, #8b5cf6 0%, #7c3aed 100%)';
                borderColor = '#7c3aed';
                content = '🔮';
                animation = 'animation: pulse 2s infinite;';
                tooltip = `${weekdayNames[day]} ${hour}:00\n🔮 VORHERSAGE für die Zukunft\nKonfidenz: ${futurePredConf.toFixed(0)}%`;
            } else if (hasPrediction && isPastHour) {
                // Vergangene Vorhersage die nicht eingetroffen ist (Orange)
                bgColor = '#fbbf24';
                borderColor = '#f59e0b';
                content = '?';
                tooltip = `${weekdayNames[day]} ${hour}:00\nVorhergesagt aber nicht eingetroffen\n(${predictionProb}% Wahrscheinlichkeit)`;
            } else if (hasPrediction && isFutureHour) {
                // Zukünftige Stunde mit historischem Muster (helles Lila)
                bgColor = '#ddd6fe';
                borderColor = '#c4b5fd';
                content = '◊';
                tooltip = `${weekdayNames[day]} ${hour}:00\nHistorisches Muster (${predictionProb}%)\nMöglicherweise Dusche erwartet`;
            }
            
            // Markiere aktuelle Stunde/Tag besonders
            let currentMarker = '';
            if (day === currentWeekday && hour === currentHour) {
                currentMarker = 'box-shadow: 0 0 0 3px #ef4444;';
            }

            html += `
                <div
                    style="
                        background: ${bgColor};
                        border: 1px solid ${borderColor};
                        border-radius: 3px;
                        height: 35px;
                        display: flex;
                        align-items: center;
                        justify-content: center;
                        color: ${hasActual || hasPrediction || hasFuturePrediction ? 'white' : '#9ca3af'};
                        font-weight: bold;
                        cursor: pointer;
                        transition: transform 0.1s ease;
                        ${currentMarker}
                        ${animation}
                    "
                    title="${tooltip}"
                    onmouseover="this.style.transform='scale(1.1)'; this.style.zIndex='10';"
                    onmouseout="this.style.transform='scale(1)'; this.style.zIndex='1';"
                >
                    ${content}
                </div>
            `;
        }
    }

    html += '</div>';
    
    // CSS für Pulse-Animation hinzufügen
    html += `
        <style>
            @keyframes pulse {
                0%, 100% { opacity: 1; }
                50% { opacity: 0.7; }
            }
        </style>
    `;
    
    // Zeige nächste vorhergesagte Dusche
    if (typicalTimes && typicalTimes.length > 0 && sufficientData) {
        const nextPrediction = findNextPredictedShower(typicalTimes, currentWeekday, currentHour, weekdayNames);
        if (nextPrediction) {
            html += `
                <div style="margin-top: 15px; padding: 15px; background: linear-gradient(135deg, #ede9fe 0%, #ddd6fe 100%); 
                    border-left: 4px solid #8b5cf6; border-radius: 6px;">
                    <div style="display: flex; align-items: center; gap: 10px;">
                        <span style="font-size: 1.5em;">🔮</span>
                        <div>
                            <strong style="color: #5b21b6;">Nächste vorhergesagte Dusche</strong>
                            <div style="font-size: 1.1em; margin-top: 4px; color: #374151;">
                                ${nextPrediction.dayName} um <strong>${nextPrediction.timeString}</strong>
                                <span style="color: #6b7280; font-size: 0.9em;">(${nextPrediction.label}, ${(nextPrediction.confidence * 100).toFixed(0)}% Konfidenz)</span>
                            </div>
                            ${nextPrediction.isToday ? '<div style="margin-top: 4px; color: #059669; font-size: 0.9em;">⏰ Das ist heute!</div>' : ''}
                            ${nextPrediction.isTomorrow ? '<div style="margin-top: 4px; color: #2563eb; font-size: 0.9em;">📅 Das ist morgen!</div>' : ''}
                        </div>
                    </div>
                </div>
            `;
        }
    }

    // Info-Box falls nicht genug Daten
    if (!sufficientData) {
        html += `
            <div style="margin-top: 15px; padding: 15px; background: #fef3c7; border-left: 4px solid #f59e0b; border-radius: 6px;">
                <strong>⚠️ Nicht genug Daten</strong>
                <p style="margin: 5px 0 0 0; font-size: 0.9em;">
                    Mindestens 3 Events benötigt für zuverlässige Vorhersagen.
                </p>
            </div>
        `;
    } else if (accuracyMetrics) {
        // Zeige Genauigkeitsnachricht
        html += `
            <div style="margin-top: 15px; padding: 12px; background: #eff6ff; border-left: 4px solid #3b82f6; border-radius: 6px; font-size: 0.9em;">
                ${accuracyMetrics.message}
            </div>
        `;
    }
    
    // Muster-Stabilität anzeigen
    if (patternStability && patternStability.score !== undefined) {
        const stabilityScore = patternStability.score;
        const stabilityDesc = patternStability.description || '';
        const stabilityColor = stabilityScore >= 0.7 ? '#10b981' : stabilityScore >= 0.4 ? '#f59e0b' : '#ef4444';
        
        html += `
            <div style="margin-top: 10px; padding: 10px; background: #f9fafb; border-radius: 6px; font-size: 0.85em; color: #6b7280;">
                <strong>📊 Muster-Stabilität:</strong> 
                <span style="color: ${stabilityColor}; font-weight: 600;">${stabilityDesc}</span>
                <span style="margin-left: 5px;">(${(stabilityScore * 100).toFixed(0)}%)</span>
                ${patternStability.mean_interval_hours ? ` • Ø Intervall: ${patternStability.mean_interval_hours}h` : ''}
            </div>
        `;
    }

    container.innerHTML = html;
}

/**
 * Findet die nächste vorhergesagte Dusche
 */
function findNextPredictedShower(typicalTimes, currentWeekday, currentHour, weekdayNames) {
    if (!typicalTimes || typicalTimes.length === 0) return null;
    
    const now = new Date();
    let bestPrediction = null;
    let minTimeDiff = Infinity;
    
    // Suche in den nächsten 7 Tagen
    for (let dayOffset = 0; dayOffset < 7; dayOffset++) {
        const checkDate = new Date(now);
        checkDate.setDate(checkDate.getDate() + dayOffset);
        const checkWeekday = checkDate.getDay() === 0 ? 6 : checkDate.getDay() - 1; // Konvertiere zu Mo=0
        
        for (const time of typicalTimes) {
            const hour = time.hour;
            const minute = time.minute || 0;
            
            // Für heute: nur zukünftige Zeiten
            if (dayOffset === 0 && (hour < currentHour || (hour === currentHour && minute <= now.getMinutes()))) {
                continue;
            }
            
            // Berechne Zeit bis zu dieser Vorhersage
            const predDate = new Date(checkDate);
            predDate.setHours(hour, minute, 0, 0);
            const timeDiff = predDate - now;
            
            if (timeDiff > 0 && timeDiff < minTimeDiff && time.confidence >= 0.3) {
                minTimeDiff = timeDiff;
                bestPrediction = {
                    dayName: weekdayNames[checkWeekday],
                    hour: hour,
                    minute: minute,
                    timeString: time.time_string || `${hour.toString().padStart(2, '0')}:${minute.toString().padStart(2, '0')}`,
                    confidence: time.confidence,
                    label: time.label || '',
                    isToday: dayOffset === 0,
                    isTomorrow: dayOffset === 1,
                    timeDiff: timeDiff
                };
            }
        }
    }
    
    return bestPrediction;
}

// Init
document.addEventListener('DOMContentLoaded', async () => {
    // Initialisiere Main Tabs
    initMainTabs();
    restoreLastMainTab();

    setupSliders();
    setupTabs();
    setupHeatingBoostToggle();

    // Zeige Lade-Indikator
    const statusSection = document.querySelector('.status-grid');
    if (statusSection) {
        statusSection.style.opacity = '0.6';
    }

    // Lade Devices, Config und gelernte Parameter parallel
    await Promise.all([
        loadRooms(),
        loadConfig(),
        loadLearnedParams(),
        loadEnergyStats(),
        loadAlerts(),
        loadDataStats(),
        loadMoldPreventionStatusBathroom(),
        loadWeeklyOverview()
    ]);

    // Lade Status nach Config (braucht Config-Daten)
    await loadStatus();

    // Entferne Lade-Indikator
    if (statusSection) {
        statusSection.style.opacity = '1';
    }

    // Event Listeners
    document.getElementById('save-bathroom-config').addEventListener('click', saveConfig);
    document.getElementById('test-bathroom').addEventListener('click', testAutomation);

    // Geräte-Test Buttons
    const testDehumidifierBtn = document.getElementById('test-dehumidifier');
    if (testDehumidifierBtn) {
        testDehumidifierBtn.addEventListener('click', () => testDevice('dehumidifier'));
    }
    const testHeaterBtn = document.getElementById('test-heater');
    if (testHeaterBtn) {
        testHeaterBtn.addEventListener('click', () => testDevice('heater'));
    }

    // Reset Button
    const resetBtn = document.getElementById('reset-learned-btn');
    if (resetBtn) {
        resetBtn.addEventListener('click', resetLearnedParams);
    }

    // Preview Button
    const previewBtn = document.getElementById('preview-btn');
    if (previewBtn) {
        previewBtn.addEventListener('click', showPreview);
    }

    // Close Preview Modal
    const closePreviewBtn = document.getElementById('close-preview-btn');
    if (closePreviewBtn) {
        closePreviewBtn.addEventListener('click', () => {
            document.getElementById('preview-modal').style.display = 'none';
        });
    }

    // Dismiss Alerts
    const dismissAlertsBtn = document.getElementById('dismiss-alerts-btn');
    if (dismissAlertsBtn) {
        dismissAlertsBtn.addEventListener('click', () => {
            document.getElementById('alerts-card').style.display = 'none';
        });
    }

    // Event Listener für Raum-Filter
    const roomFilter = document.getElementById('room-filter');
    if (roomFilter) {
        roomFilter.addEventListener('change', (e) => {
            selectedRoomId = e.target.value;
            populateDeviceSelectors();
        });
    }

    // Aktoren-Test Event Listeners
    const dehumidifierOn = document.getElementById('test-dehumidifier-on');
    const dehumidifierOff = document.getElementById('test-dehumidifier-off');
    const heaterUp = document.getElementById('test-heater-up');
    const heaterDown = document.getElementById('test-heater-down');

    if (dehumidifierOn) {
        dehumidifierOn.addEventListener('click', () => controlActuator('dehumidifier', 'on'));
    }
    if (dehumidifierOff) {
        dehumidifierOff.addEventListener('click', () => controlActuator('dehumidifier', 'off'));
    }
    if (heaterUp) {
        heaterUp.addEventListener('click', () => controlActuator('heater', 'temp_up'));
    }
    if (heaterDown) {
        heaterDown.addEventListener('click', () => controlActuator('heater', 'temp_down'));
    }

    // Initialisiere Polling Manager für Tab-Visibility-Handling
    PollingManager.init();

    // Lade Live-Sensor-Status initial
    await loadLiveSensorStatus();

    // Lade verfügbare Duschsensoren wenn auf Sensoren-Tab gewechselt wird
    const sensorTab = document.querySelector('[data-tab="sensors"]');
    if (sensorTab) {
        sensorTab.addEventListener('click', () => {
            loadAvailableShowerSensors();
        });
    }
    
    // Rate Threshold Slider
    const rateThresholdSlider = document.getElementById('rate-threshold-luftentfeuchten');
    if (rateThresholdSlider) {
        rateThresholdSlider.addEventListener('input', function() {
            const value = this.value;
            const valueElement = document.getElementById('rate-threshold-value-luftentfeuchten');
            if (valueElement) {
                valueElement.textContent = value + ' %/min';
            }
        });
    }
    
    // Refresh Shower Stats Button
    const refreshStatsBtn = document.getElementById('refresh-shower-stats-luftentfeuchten');
    if (refreshStatsBtn) {
        refreshStatsBtn.addEventListener('click', loadShowerStats);
    }
    
    // Save Shower Sensors Button
    const saveShowerSensorsBtn = document.getElementById('save-shower-sensors-btn');
    if (saveShowerSensorsBtn) {
        saveShowerSensorsBtn.addEventListener('click', async () => {
            saveShowerSensorsBtn.disabled = true;
            saveShowerSensorsBtn.textContent = '⏳ Speichert...';
            
            try {
                await saveShowerSensorConfig();
                saveShowerSensorsBtn.textContent = '✅ Gespeichert!';
                setTimeout(() => {
                    saveShowerSensorsBtn.textContent = '💾 Sensoren speichern';
                    saveShowerSensorsBtn.disabled = false;
                }, 2000);
            } catch (error) {
                saveShowerSensorsBtn.textContent = '❌ Fehler';
                setTimeout(() => {
                    saveShowerSensorsBtn.textContent = '💾 Sensoren speichern';
                    saveShowerSensorsBtn.disabled = false;
                }, 2000);
            }
        });
    }
    
    // Initialisiere Luftfeuchtigkeits-Chart
    initHumidityChartButtons();
    loadHumidityChart(12); // Lade initial mit 12h

    // Initialisiere Live-Luftfeuchtigkeits-Chart
    initLiveHumidityChart();

    // Starte Auto-Refresh mit Tab-Visibility-Handling
    PollingManager.startInitialPolling();
});

// ===== COUNTDOWN TIMER =====

/**
 * Startet oder aktualisiert den Countdown-Timer
 */
function updateCountdown(seconds) {
    countdownSeconds = seconds;
    
    // Stoppe vorherigen Countdown falls vorhanden
    if (countdownInterval) {
        clearInterval(countdownInterval);
    }
    
    // Zeige initialen Wert
    displayCountdown();
    
    // Starte neuen Countdown
    countdownInterval = setInterval(() => {
        countdownSeconds--;
        
        if (countdownSeconds <= 0) {
            clearInterval(countdownInterval);
            countdownInterval = null;
            document.getElementById('dehumidifier-countdown').style.display = 'none';
        } else {
            displayCountdown();
        }
    }, 1000);
}

/**
 * Zeigt den Countdown-Wert an
 */
function displayCountdown() {
    const minutes = Math.floor(countdownSeconds / 60);
    const seconds = countdownSeconds % 60;
    const timeString = `${minutes}:${seconds.toString().padStart(2, '0')}`;
    document.getElementById('countdown-timer').textContent = timeString;
}

/**
 * Lädt Schimmelprävention-Status für Badezimmer
 */
async function loadMoldPreventionStatusBathroom() {
    try {
        const response = await fetchJSON('/api/status');
        
        if (!response) return; // Null bei Netzwerkfehler
        
        const container = document.getElementById('mold-status-container-bathroom');
        const card = document.getElementById('mold-prevention-card-bathroom');

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

    } catch (error) {
        console.error('Error loading mold prevention status:', error);
        const container = document.getElementById('mold-status-container-bathroom');
        container.innerHTML = `
            <div style="padding: 20px; text-align: center; color: #ef4444;">
                ⚠️ Fehler beim Laden der Schimmelprävention
            </div>
        `;
    }
}
// ===== DUSCHSENSOREN =====

/**
 * Lädt verfügbare Sensoren und füllt die Dropdowns
 */
async function loadAvailableShowerSensors() {
    try {
        const data = await fetchJSON('/api/bathroom/sensors/available');
        
        if (!data) {
            console.log('No sensor data received');
            return;
        }
        
        console.log('Loading available shower sensors:', data);

        // API gibt entweder { sensors: [...] } (neues Format) oder
        // { humidity_sensors: [...], temperature_sensors: [...] } (altes Format)
        const allSensors = data.sensors || [];
        const humiditySensors = data.humidity_sensors ||
            allSensors.filter(s => s.has_humidity).map(s => ({
                entity_id: s.id,
                name: s.name,
                state: s.current_humidity != null ? s.current_humidity.toString() : 'N/A',
                unit: '%',
                zone: s.zone || ''
            }));
        const temperatureSensors = data.temperature_sensors ||
            allSensors.filter(s => s.has_temperature).map(s => ({
                entity_id: s.id,
                name: s.name,
                state: s.current_temperature != null ? s.current_temperature.toString() : 'N/A',
                unit: '°C',
                zone: s.zone || ''
            }));

        // Füllt Humidity-Sensor Dropdown
        const humiditySelect = document.getElementById('shower-humidity-sensor-luftentfeuchten');
        if (humiditySelect) {
            // Speichere aktuell ausgewählten Wert
            const currentValue = humiditySelect.value;
            
            // Behalte erste Option
            const firstOption = humiditySelect.options[0];
            humiditySelect.innerHTML = '';
            humiditySelect.appendChild(firstOption);
            
            humiditySensors.forEach(sensor => {
                const option = document.createElement('option');
                option.value = sensor.entity_id;
                option.textContent = `${sensor.name} (${sensor.state} ${sensor.unit || ''})`;
                humiditySelect.appendChild(option);
            });
            
            // Setze vorherigen Wert wieder, falls vorhanden
            if (currentValue) {
                humiditySelect.value = currentValue;
            }
            
            console.log(`Loaded ${humiditySensors.length} humidity sensors`);
        }
        
        // Füllt Temperature-Sensor Dropdown
        const tempSelect = document.getElementById('shower-temperature-sensor-luftentfeuchten');
        if (tempSelect) {
            const currentValue = tempSelect.value;
            
            const firstOption = tempSelect.options[0];
            tempSelect.innerHTML = '';
            tempSelect.appendChild(firstOption);
            
            temperatureSensors.forEach(sensor => {
                const option = document.createElement('option');
                option.value = sensor.entity_id;
                option.textContent = `${sensor.name} (${sensor.state} ${sensor.unit || ''})`;
                tempSelect.appendChild(option);
            });
            
            if (currentValue) {
                tempSelect.value = currentValue;
            }
            
            console.log(`Loaded ${temperatureSensors.length} temperature sensors`);
        }
    } catch (error) {
        console.error('Error loading available shower sensors:', error);
    }
}

/**
 * Lädt Duschsensor-Konfiguration
 */
async function loadShowerSensorConfig() {
    try {
        // Lade erst verfügbare Sensoren
        await loadAvailableShowerSensors();
        
        const data = await fetchJSON('/api/bathroom/sensors/config');
        
        if (!data || !data.shower_sensors) {
            console.log('No shower sensor config found');
            return;
        }
        
        const showerSensors = data.shower_sensors;
        console.log('Loaded shower sensor config:', showerSensors);
        
        // Setze Werte
        const humiditySelect = document.getElementById('shower-humidity-sensor-luftentfeuchten');
        const tempSelect = document.getElementById('shower-temperature-sensor-luftentfeuchten');
        const rateDetectionCheckbox = document.getElementById('enable-rate-detection-luftentfeuchten');
        const rateThresholdSlider = document.getElementById('rate-threshold-luftentfeuchten');
        
        if (humiditySelect) {
            humiditySelect.value = showerSensors.humidity_sensor || '';
            console.log('Set humidity sensor to:', humiditySelect.value, '(options:', humiditySelect.options.length, ')');
        }
        if (tempSelect) {
            tempSelect.value = showerSensors.temperature_sensor || '';
            console.log('Set temperature sensor to:', tempSelect.value, '(options:', tempSelect.options.length, ')');
        }
        if (rateDetectionCheckbox) rateDetectionCheckbox.checked = showerSensors.enable_rate_detection !== false;
        if (rateThresholdSlider) {
            rateThresholdSlider.value = showerSensors.rate_threshold || 2.0;
            updateSliderValue('rate-threshold-luftentfeuchten');
        }
        
        // Lade auch Statistiken
        await loadShowerStats();
        
    } catch (error) {
        console.error('Error loading shower sensor config:', error);
    }
}

/**
 * Speichert Duschsensor-Konfiguration
 */
async function saveShowerSensorConfig() {
    try {
        const humiditySelect = document.getElementById('shower-humidity-sensor-luftentfeuchten');
        const tempSelect = document.getElementById('shower-temperature-sensor-luftentfeuchten');
        const rateDetectionCheckbox = document.getElementById('enable-rate-detection-luftentfeuchten');
        const rateThresholdSlider = document.getElementById('rate-threshold-luftentfeuchten');
        
        if (!humiditySelect || !tempSelect || !rateDetectionCheckbox || !rateThresholdSlider) {
            console.log('Shower sensor elements not found, skipping save');
            return;
        }
        
        const config = {
            shower_sensors: {
                humidity_sensor: humiditySelect.value,
                temperature_sensor: tempSelect.value,
                enable_rate_detection: rateDetectionCheckbox.checked,
                rate_threshold: parseFloat(rateThresholdSlider.value)
            }
        };
        
        const result = await postJSON('/api/bathroom/sensors/config', config);
        
        if (result && result.success) {
            console.log('Shower sensor config saved');
            // Zeige Erfolgs-Nachricht
            if (result.message) {
                showNotification(result.message, 'success');
            }
            return true;
        } else {
            throw new Error(result?.error || 'Unbekannter Fehler');
        }
    } catch (error) {
        console.error('Error saving shower sensor config:', error);
        showNotification('Fehler beim Speichern: ' + error.message, 'error');
        throw error;
    }
}

/**
 * Lädt Dusch-Statistiken
 */
async function loadShowerStats() {
    try {
        const data = await fetchJSON('/api/bathroom/stats');
        
        if (!data) return;
        
        // Update Statistik-Werte
        const totalElement = document.getElementById('shower-stats-total');
        const durationElement = document.getElementById('shower-stats-duration');
        const increaseElement = document.getElementById('shower-stats-increase');
        
        if (totalElement) totalElement.textContent = data.total_showers || '0';
        if (durationElement) durationElement.textContent = data.avg_duration_minutes ? data.avg_duration_minutes.toFixed(1) : '--';
        if (increaseElement) increaseElement.textContent = data.avg_humidity_increase ? data.avg_humidity_increase.toFixed(1) : '--';
        
    } catch (error) {
        console.error('Error loading shower stats:', error);
    }
}

// ===== LUFTFEUCHTIGKEITS-VERLAUF CHART =====

let humidityChart = null;
let currentHumidityPeriod = 12;

/**
 * Lädt die Luftfeuchtigkeitsdaten und rendert die Grafik
 */
async function loadHumidityChart(hours = 12) {
    try {
        currentHumidityPeriod = hours;
        
        const loadingElement = document.getElementById('humidity-chart-loading');
        const containerElement = document.getElementById('humidity-chart-container');
        
        if (loadingElement) loadingElement.style.display = 'block';
        if (containerElement) containerElement.style.display = 'none';
        
        const data = await fetchJSON(`/api/bathroom/humidity-history?hours=${hours}`);
        
        if (!data) {
            console.error('No humidity history data received');
            if (loadingElement) loadingElement.textContent = 'Keine Daten verfügbar';
            return;
        }
        
        // Hole auch Entfeuchter-Daten von der sensor-timeseries API
        const timeseriesData = await fetchJSON(`/api/luftentfeuchten/sensor-timeseries?hours=${hours}`);
        
        // Verstecke Loading, zeige Chart
        if (loadingElement) loadingElement.style.display = 'none';
        if (containerElement) containerElement.style.display = 'block';
        
        renderHumidityChart(data);
        renderHumidityStats(data, timeseriesData);
        
    } catch (error) {
        console.error('Error loading humidity chart:', error);
        const loadingElement = document.getElementById('humidity-chart-loading');
        if (loadingElement) loadingElement.textContent = 'Fehler beim Laden der Daten';
    }
}

/**
 * Rendert die Luftfeuchtigkeits-Grafik mit Chart.js
 */
function renderHumidityChart(data) {
    const canvas = document.getElementById('humidity-chart');
    if (!canvas) {
        console.error('Canvas element not found');
        return;
    }
    
    const ctx = canvas.getContext('2d');
    
    // Zerstöre existierendes Chart
    if (humidityChart) {
        humidityChart.destroy();
    }
    
    // Bereite Daten vor
    const mainSensorData = data.main_sensor?.data || [];
    const showerSensorData = data.shower_sensor?.data || [];
    
    // Erstelle Datasets
    const datasets = [];
    
    // Hauptsensor (immer anzeigen)
    if (mainSensorData.length > 0) {
        datasets.push({
            label: data.main_sensor.name || 'Hauptsensor',
            data: mainSensorData.map(d => ({
                x: new Date(d.timestamp),
                y: d.humidity
            })),
            borderColor: '#3b82f6',
            backgroundColor: 'rgba(59, 130, 246, 0.1)',
            borderWidth: 2,
            tension: 0.4,
            fill: false,
            pointRadius: 2,
            pointHoverRadius: 5
        });
    }
    
    // Duschsensor (nur wenn konfiguriert)
    if (showerSensorData.length > 0) {
        datasets.push({
            label: data.shower_sensor.name || 'Duschsensor',
            data: showerSensorData.map(d => ({
                x: new Date(d.timestamp),
                y: d.humidity
            })),
            borderColor: '#10b981',
            backgroundColor: 'rgba(16, 185, 129, 0.1)',
            borderWidth: 2,
            tension: 0.4,
            fill: false,
            pointRadius: 2,
            pointHoverRadius: 5
        });
    }
    
    // Erstelle Chart
    humidityChart = new Chart(ctx, {
        type: 'line',
        data: { datasets: datasets },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: {
                intersect: false,
                mode: 'index'
            },
            plugins: {
                legend: {
                    display: true,
                    position: 'top',
                    labels: {
                        usePointStyle: true,
                        padding: 15
                    }
                },
                tooltip: {
                    backgroundColor: 'rgba(0, 0, 0, 0.8)',
                    padding: 12,
                    titleColor: '#fff',
                    bodyColor: '#fff',
                    callbacks: {
                        title: function(context) {
                            const date = context[0].parsed.x;
                            return new Date(date).toLocaleString('de-DE', {
                                day: '2-digit',
                                month: '2-digit',
                                hour: '2-digit',
                                minute: '2-digit'
                            });
                        },
                        label: function(context) {
                            return context.dataset.label + ': ' + context.parsed.y.toFixed(1) + '%';
                        }
                    }
                }
            },
            scales: {
                x: {
                    type: 'time',
                    time: {
                        unit: currentHumidityPeriod <= 12 ? 'hour' : 'hour',
                        displayFormats: {
                            hour: 'HH:mm',
                            day: 'DD.MM'
                        }
                    },
                    title: {
                        display: true,
                        text: 'Zeit'
                    },
                    grid: {
                        color: 'rgba(0, 0, 0, 0.05)'
                    }
                },
                y: {
                    title: {
                        display: true,
                        text: 'Luftfeuchtigkeit (%)'
                    },
                    min: 0,
                    max: 100,
                    grid: {
                        color: 'rgba(0, 0, 0, 0.05)'
                    }
                }
            }
        }
    });
}

/**
 * Initialisiert die Event-Listener für die Zeitraum-Buttons
 */
function initHumidityChartButtons() {
    const buttons = document.querySelectorAll('.humidity-period-btn');
    
    buttons.forEach(btn => {
        btn.addEventListener('click', function() {
            const period = parseInt(this.getAttribute('data-period'));
            
            // Update Button-Styles
            buttons.forEach(b => {
                b.style.background = 'white';
                b.style.color = '#374151';
                b.classList.remove('active');
            });
            this.style.background = 'linear-gradient(135deg, #3b82f6 0%, #2563eb 100%)';
            this.style.color = 'white';
            this.classList.add('active');
            
            // Lade neue Daten
            loadHumidityChart(period);
        });
    });
}

/**
 * Rendert die Statistik-Tabelle mit Entfeuchter-Laufzeit
 */
function renderHumidityStats(data, timeseriesData) {
    const tableBody = document.getElementById('humidity-stats-table');
    if (!tableBody) return;
    
    const mainSensorData = data.main_sensor?.data || [];
    const showerSensorData = data.shower_sensor?.data || [];
    
    // Berechne Entfeuchter-Laufzeit (in Minuten)
    let dehumidifierMinutes = 0;
    if (timeseriesData && timeseriesData.dehumidifier_periods) {
        timeseriesData.dehumidifier_periods.forEach(period => {
            const start = new Date(period.start);
            const end = new Date(period.end);
            const minutes = (end - start) / 1000 / 60;
            dehumidifierMinutes += minutes;
        });
    }
    
    // Formatiere Laufzeit
    const formatRuntime = (minutes) => {
        if (minutes === 0) return '<span style="color: #6b7280;">Nicht aktiv</span>';
        const hours = Math.floor(minutes / 60);
        const mins = Math.round(minutes % 60);
        if (hours > 0) {
            return `<span style="color: #10b981; font-weight: 600;">${hours}h ${mins}min</span>`;
        }
        return `<span style="color: #10b981; font-weight: 600;">${mins}min</span>`;
    };
    
    // Berechne Statistiken für Hauptsensor
    const mainStats = calculateSensorStats(mainSensorData);
    
    // Berechne Statistiken für Duschsensor
    const showerStats = calculateSensorStats(showerSensorData);
    
    let html = '';
    
    // Hauptsensor Zeile
    html += `
        <tr style="border-bottom: 1px solid #e5e7eb;">
            <td style="padding: 12px;">
                <div style="display: flex; align-items: center; gap: 8px;">
                    <div style="width: 12px; height: 12px; background: #3b82f6; border-radius: 50%;"></div>
                    <span style="font-weight: 500;">Hauptsensor</span>
                </div>
            </td>
            <td style="padding: 12px; text-align: center; font-weight: 600; color: #1f2937;">${mainStats.current}%</td>
            <td style="padding: 12px; text-align: center; color: #6b7280;">${mainStats.min}%</td>
            <td style="padding: 12px; text-align: center; color: #6b7280;">${mainStats.max}%</td>
            <td style="padding: 12px; text-align: center; color: #6b7280;">${mainStats.avg}%</td>
            <td style="padding: 12px; text-align: center;">${formatRuntime(dehumidifierMinutes)}</td>
        </tr>
    `;
    
    // Duschsensor Zeile (nur wenn Daten vorhanden)
    if (showerSensorData.length > 0) {
        html += `
            <tr style="border-bottom: 1px solid #e5e7eb;">
                <td style="padding: 12px;">
                    <div style="display: flex; align-items: center; gap: 8px;">
                        <div style="width: 12px; height: 12px; background: #10b981; border-radius: 50%;"></div>
                        <span style="font-weight: 500;">Duschsensor</span>
                    </div>
                </td>
                <td style="padding: 12px; text-align: center; font-weight: 600; color: #1f2937;">${showerStats.current}%</td>
                <td style="padding: 12px; text-align: center; color: #6b7280;">${showerStats.min}%</td>
                <td style="padding: 12px; text-align: center; color: #6b7280;">${showerStats.max}%</td>
                <td style="padding: 12px; text-align: center; color: #6b7280;">${showerStats.avg}%</td>
                <td style="padding: 12px; text-align: center; color: #9ca3af;">-</td>
            </tr>
        `;
    }
    
    tableBody.innerHTML = html;
}

/**
 * Berechnet Statistiken für Sensordaten
 */
function calculateSensorStats(sensorData) {
    if (!sensorData || sensorData.length === 0) {
        return {
            current: '-',
            min: '-',
            max: '-',
            avg: '-'
        };
    }
    
    const values = sensorData.map(d => d.humidity);
    const current = values[values.length - 1];
    const min = Math.min(...values);
    const max = Math.max(...values);
    const avg = values.reduce((sum, v) => sum + v, 0) / values.length;
    
    return {
        current: current.toFixed(1),
        min: min.toFixed(1),
        max: max.toFixed(1),
        avg: avg.toFixed(1)
    };
}

// ===== LIVE HUMIDITY CHART (CANVAS-BASED) =====

let liveHumidityTimeseriesData = null;
let currentLiveHumidityPeriod = 6;

/**
 * Lädt die Live-Luftfeuchtigkeit Daten
 */
async function loadLiveHumidityChart(hours = 6) {
    try {
        currentLiveHumidityPeriod = hours;

        const loadingElement = document.getElementById('live-humidity-chart-loading');
        const containerElement = document.getElementById('live-humidity-chart-container');

        if (loadingElement) loadingElement.style.display = 'block';
        if (containerElement) containerElement.style.display = 'none';

        const response = await fetch(`/api/luftentfeuchten/sensor-timeseries?hours=${hours}`);

        if (response.ok) {
            liveHumidityTimeseriesData = await response.json();
            console.log('✅ Live Humidity Daten geladen:', liveHumidityTimeseriesData.count, 'Messungen');
        } else {
            const errorData = await response.json();
            console.error('❌ Error loading live humidity data:', errorData);
            liveHumidityTimeseriesData = {
                error: errorData.error || 'Unbekannter Fehler',
                data: []
            };
        }

        if (loadingElement) loadingElement.style.display = 'none';
        if (containerElement) containerElement.style.display = 'block';

        renderLiveHumidityTimeseries();

    } catch (error) {
        console.error('❌ Error loading live humidity chart:', error);
        const loadingElement = document.getElementById('live-humidity-chart-loading');
        if (loadingElement) {
            loadingElement.innerHTML = `
                <div style="padding: 20px; background: #fee2e2; border-radius: 8px; color: #991b1b;">
                    ❌ Fehler beim Laden: ${error.message}
                </div>
            `;
        }
    }
}

/**
 * Rendert das Live-Luftfeuchtigkeit Diagramm (Canvas-basiert)
 */
function renderLiveHumidityTimeseries() {
    const chartContainer = document.getElementById('live-humidity-chart-container');

    // Prüfe auf Fehler
    if (liveHumidityTimeseriesData && liveHumidityTimeseriesData.error) {
        console.error('❌ Live Humidity data error:', liveHumidityTimeseriesData.error);
        let errorMessage = '';
        let helpText = '';

        if (liveHumidityTimeseriesData.error.includes('No configuration found')) {
            errorMessage = '⚙️ Badezimmer-Automatisierung nicht konfiguriert';
            helpText = 'Bitte gehen Sie zum Tab "Konfiguration" und konfigurieren Sie die Sensoren.';
        } else if (liveHumidityTimeseriesData.error.includes('Humidity sensor not configured')) {
            errorMessage = '💧 Luftfeuchtigkeits-Sensor nicht konfiguriert';
            helpText = 'Bitte gehen Sie zum Tab "Konfiguration" und wählen Sie einen Raum mit Luftfeuchtigkeits-Sensor aus.';
        } else {
            errorMessage = '❌ Fehler beim Laden der Sensor-Daten';
            helpText = `Fehlerdetails: ${liveHumidityTimeseriesData.error}`;
        }

        chartContainer.innerHTML = `
            <div style="text-align: center; padding: 40px; background: linear-gradient(135deg, #fef3c7 0%, #fde68a 100%); border-radius: 8px; border-left: 4px solid #f59e0b;">
                <div style="font-size: 1.2em; font-weight: 600; color: #92400e; margin-bottom: 10px;">
                    ${errorMessage}
                </div>
                <div style="color: #92400e; font-size: 0.95em;">
                    ${helpText}
                </div>
            </div>
        `;
        return;
    }

    // Prüfe ob Daten vorhanden
    if (!liveHumidityTimeseriesData || !liveHumidityTimeseriesData.data || liveHumidityTimeseriesData.data.length === 0) {
        chartContainer.innerHTML = `
            <div style="text-align: center; padding: 40px; background: #f9fafb; border-radius: 8px; border: 2px dashed #d1d5db;">
                <div style="font-size: 1.2em; font-weight: 600; color: #6b7280; margin-bottom: 10px;">
                    📊 Keine Sensordaten verfügbar
                </div>
                <div style="color: #6b7280; font-size: 0.95em;">
                    Das System sammelt noch Daten. Bitte warten Sie ein paar Minuten und aktualisieren Sie die Seite.
                </div>
            </div>
        `;
        return;
    }

    const canvas = document.getElementById('live-humidity-canvas');
    if (!canvas) {
        console.error('❌ Live humidity canvas element not found');
        return;
    }

    const ctx = canvas.getContext('2d');

    // Setze Canvas-Größe
    canvas.width = canvas.parentElement.clientWidth;
    canvas.height = 350;

    const padding = 50;
    const chartWidth = canvas.width - 2 * padding;
    const chartHeight = canvas.height - 2 * padding;

    const data = liveHumidityTimeseriesData.data;

    // Extrahiere Werte
    const values = data.map(d => parseFloat(d.value));
    const showerValues = data.map(d => d.shower_value ? parseFloat(d.shower_value) : null).filter(v => v !== null);
    const timestamps = data.map(d => new Date(d.timestamp));

    // Moving Average Glättung (5-Punkt)
    const smoothedValues = values.map((val, idx) => {
        const window = 5;
        const start = Math.max(0, idx - Math.floor(window / 2));
        const end = Math.min(values.length, idx + Math.ceil(window / 2));
        const slice = values.slice(start, end);
        return slice.reduce((sum, v) => sum + v, 0) / slice.length;
    });

    // Glätte auch Duschsensor-Werte
    const smoothedShowerValues = data.map((d, idx) => {
        if (!d.shower_value) return null;
        const window = 5;
        const start = Math.max(0, idx - Math.floor(window / 2));
        const end = Math.min(data.length, idx + Math.ceil(window / 2));
        const validValues = [];
        for (let i = start; i < end; i++) {
            if (data[i].shower_value) validValues.push(parseFloat(data[i].shower_value));
        }
        return validValues.length > 0 ? validValues.reduce((sum, v) => sum + v, 0) / validValues.length : null;
    });

    // Finde Min/Max (beide Sensoren berücksichtigen)
    const allValues = [...smoothedValues, ...smoothedShowerValues.filter(v => v !== null)];
    const maxValue = Math.max(...allValues);
    const minValue = Math.min(...allValues);
    const range = maxValue - minValue;
    const yMin = Math.max(0, minValue - range * 0.1);
    const yMax = maxValue + range * 0.1;

    // Clear canvas
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    // Zeichne Achsen
    ctx.strokeStyle = '#e5e7eb';
    ctx.lineWidth = 1;

    // Y-Achse
    ctx.beginPath();
    ctx.moveTo(padding, padding);
    ctx.lineTo(padding, canvas.height - padding);
    ctx.stroke();

    // X-Achse
    ctx.beginPath();
    ctx.moveTo(padding, canvas.height - padding);
    ctx.lineTo(canvas.width - padding, canvas.height - padding);
    ctx.stroke();

    // Zeichne Gitterlinien und Y-Labels
    ctx.strokeStyle = '#f3f4f6';
    ctx.fillStyle = '#6b7280';
    ctx.font = '12px Arial';
    for (let i = 0; i <= 5; i++) {
        const y = padding + (chartHeight / 5) * i;
        ctx.beginPath();
        ctx.moveTo(padding, y);
        ctx.lineTo(canvas.width - padding, y);
        ctx.stroke();

        // Y-Label
        const value = yMax - (yMax - yMin) / 5 * i;
        ctx.textAlign = 'right';
        ctx.fillText(value.toFixed(0) + '%', padding - 10, y + 4);
    }

    // X-Labels (Zeit)
    const numXLabels = 6;
    for (let i = 0; i <= numXLabels; i++) {
        const index = Math.floor((data.length - 1) / numXLabels * i);
        const x = padding + (chartWidth / numXLabels) * i;
        const time = timestamps[index];

        ctx.textAlign = 'center';
        ctx.fillText(
            time.toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit' }),
            x,
            canvas.height - padding + 20
        );
    }

    // Hilfsfunktionen
    const getY = (value) => {
        return canvas.height - padding - ((value - yMin) / (yMax - yMin)) * chartHeight;
    };

    const getX = (index) => {
        return padding + (chartWidth / (data.length - 1)) * index;
    };

    // Zeichne Linie (geglättete Werte - Hauptsensor)
    ctx.strokeStyle = '#3b82f6';
    ctx.lineWidth = 2;
    ctx.beginPath();
    smoothedValues.forEach((value, i) => {
        const x = getX(i);
        const y = getY(value);
        if (i === 0) {
            ctx.moveTo(x, y);
        } else {
            ctx.lineTo(x, y);
        }
    });
    ctx.stroke();

    // Zeichne Originaldaten transparent im Hintergrund
    ctx.strokeStyle = 'rgba(59, 130, 246, 0.2)';
    ctx.lineWidth = 1;
    ctx.beginPath();
    values.forEach((value, i) => {
        const x = getX(i);
        const y = getY(value);
        if (i === 0) {
            ctx.moveTo(x, y);
        } else {
            ctx.lineTo(x, y);
        }
    });
    ctx.stroke();

    // Zeichne Duschsensor (geglättet) in Lila/Pink
    if (smoothedShowerValues.some(v => v !== null)) {
        ctx.strokeStyle = '#a855f7';  // Lila
        ctx.lineWidth = 2;
        ctx.beginPath();
        let firstPoint = true;
        smoothedShowerValues.forEach((value, i) => {
            if (value === null) return;
            const x = getX(i);
            const y = getY(value);
            if (firstPoint) {
                ctx.moveTo(x, y);
                firstPoint = false;
            } else {
                ctx.lineTo(x, y);
            }
        });
        ctx.stroke();

        // Duschsensor Originaldaten transparent
        ctx.strokeStyle = 'rgba(168, 85, 247, 0.2)';
        ctx.lineWidth = 1;
        ctx.beginPath();
        firstPoint = true;
        data.forEach((d, i) => {
            if (!d.shower_value) return;
            const x = getX(i);
            const y = getY(parseFloat(d.shower_value));
            if (firstPoint) {
                ctx.moveTo(x, y);
                firstPoint = false;
            } else {
                ctx.lineTo(x, y);
            }
        });
        ctx.stroke();
    }

    // Zeichne Datenpunkte (nur geglättete Werte)
    smoothedValues.forEach((value, i) => {
        // Nur jeden 10. Punkt zeichnen für bessere Performance
        if (i % 10 !== 0) return;

        const x = getX(i);
        const y = getY(value);

        ctx.fillStyle = '#3b82f6';
        ctx.beginPath();
        ctx.arc(x, y, 3, 0, 2 * Math.PI);
        ctx.fill();
    });

    // Duschsensor Datenpunkte
    if (smoothedShowerValues.some(v => v !== null)) {
        smoothedShowerValues.forEach((value, i) => {
            if (value === null || i % 10 !== 0) return;

            const x = getX(i);
            const y = getY(value);

            ctx.fillStyle = '#a855f7';
            ctx.beginPath();
            ctx.arc(x, y, 3, 0, 2 * Math.PI);
            ctx.fill();
        });
    }

    // Zeichne Entfeuchter-Perioden (grüner Bereich am unteren Rand)
    if (liveHumidityTimeseriesData.dehumidifier_periods && liveHumidityTimeseriesData.dehumidifier_periods.length > 0) {
        liveHumidityTimeseriesData.dehumidifier_periods.forEach(period => {
            const periodStart = new Date(period.start);
            const periodEnd = new Date(period.end);
            const now = new Date();

            // Finde Index der nächstliegenden Zeitstempel
            const startIdx = timestamps.findIndex(t => t >= periodStart);
            let endIdx = timestamps.findIndex(t => t >= periodEnd);

            // Prüfe ob die Periode noch läuft (End-Zeit ist sehr nahe an "jetzt")
            const isStillRunning = Math.abs(periodEnd - now) < 60000; // weniger als 1 Minute Differenz

            if (startIdx >= 0) {
                const startX = getX(startIdx);
                let endX;

                // Wenn kein End-Index gefunden wurde oder läuft noch
                if (endIdx < 0 || isStillRunning) {
                    // Verwende letzten Datenpunkt
                    endX = getX(data.length - 1);
                } else {
                    endX = getX(endIdx);
                }

                // Zeichne grünen Balken am unteren Rand
                const barHeight = 8;
                const barY = canvas.height - padding - barHeight;

                // Wenn noch läuft, verwende halbtransparente Farbe
                if (isStillRunning) {
                    ctx.fillStyle = 'rgba(16, 185, 129, 0.6)'; // Halbtransparent
                } else {
                    ctx.fillStyle = '#10b981'; // Vollfarbe
                }
                ctx.fillRect(startX, barY, endX - startX, barHeight);

                // Rahmen (gestrichelt wenn noch läuft)
                ctx.strokeStyle = '#059669';
                ctx.lineWidth = 1;
                if (isStillRunning) {
                    ctx.setLineDash([4, 4]);
                }
                ctx.strokeRect(startX, barY, endX - startX, barHeight);
                ctx.setLineDash([]); // Reset
            }
        });

        // Legende für Entfeuchter-Balken
        ctx.fillStyle = '#10b981';
        ctx.fillRect(padding + 10, canvas.height - padding + 25, 20, 8);
        ctx.strokeStyle = '#059669';
        ctx.strokeRect(padding + 10, canvas.height - padding + 25, 20, 8);
        ctx.fillStyle = '#1f2937';
        ctx.font = '11px Arial';
        ctx.textAlign = 'left';
        ctx.fillText('Entfeuchter war aktiv', padding + 35, canvas.height - padding + 32);

        // Zusätzliche Legende für "läuft noch"
        ctx.fillStyle = 'rgba(16, 185, 129, 0.6)';
        ctx.fillRect(padding + 160, canvas.height - padding + 25, 20, 8);
        ctx.strokeStyle = '#059669';
        ctx.setLineDash([4, 4]);
        ctx.strokeRect(padding + 160, canvas.height - padding + 25, 20, 8);
        ctx.setLineDash([]);
        ctx.fillStyle = '#1f2937';
        ctx.fillText('Läuft aktuell', padding + 185, canvas.height - padding + 32);
    }

    // Zeichne Event-Markierungen (Dusch-Events)
    if (liveHumidityTimeseriesData.events && liveHumidityTimeseriesData.events.length > 0) {
        liveHumidityTimeseriesData.events.forEach(event => {
            const eventStart = new Date(event.start_time);
            const eventEnd = event.end_time ? new Date(event.end_time) : eventStart;

            // Finde Index der nächstliegenden Zeitstempel
            const startIdx = timestamps.findIndex(t => t >= eventStart);
            const endIdx = timestamps.findIndex(t => t >= eventEnd);

            if (startIdx >= 0) {
                const startX = getX(startIdx);
                const endX = endIdx >= 0 ? getX(endIdx) : startX;

                // Zeichne farbigen Bereich
                ctx.fillStyle = 'rgba(239, 68, 68, 0.1)';
                ctx.fillRect(startX, padding, endX - startX, chartHeight);

                // Zeichne vertikale Linien
                ctx.strokeStyle = 'rgba(239, 68, 68, 0.5)';
                ctx.lineWidth = 2;
                ctx.setLineDash([5, 5]);
                ctx.beginPath();
                ctx.moveTo(startX, padding);
                ctx.lineTo(startX, canvas.height - padding);
                ctx.stroke();
                ctx.setLineDash([]);

                // Label
                ctx.fillStyle = '#ef4444';
                ctx.font = 'bold 12px Arial';
                ctx.textAlign = 'center';
                ctx.fillText('🚿 Dusche', startX, padding - 10);
            }
        });
    }

    // Schwellwert-Linie (High Threshold)
    if (liveHumidityTimeseriesData.threshold_high) {
        const thresholdY = getY(liveHumidityTimeseriesData.threshold_high);
        ctx.strokeStyle = '#f59e0b';
        ctx.lineWidth = 2;
        ctx.setLineDash([10, 5]);
        ctx.beginPath();
        ctx.moveTo(padding, thresholdY);
        ctx.lineTo(canvas.width - padding, thresholdY);
        ctx.stroke();
        ctx.setLineDash([]);

        ctx.fillStyle = '#f59e0b';
        ctx.font = '12px Arial';
        ctx.textAlign = 'right';
        ctx.fillText(`Entfeuchter EIN: ${liveHumidityTimeseriesData.threshold_high}%`, canvas.width - padding - 10, thresholdY - 5);
    }

    // Schwellwert-Linie (Low Threshold)
    if (liveHumidityTimeseriesData.threshold_low) {
        const thresholdY = getY(liveHumidityTimeseriesData.threshold_low);
        ctx.strokeStyle = '#10b981';
        ctx.lineWidth = 2;
        ctx.setLineDash([10, 5]);
        ctx.beginPath();
        ctx.moveTo(padding, thresholdY);
        ctx.lineTo(canvas.width - padding, thresholdY);
        ctx.stroke();
        ctx.setLineDash([]);

        ctx.fillStyle = '#10b981';
        ctx.font = '12px Arial';
        ctx.textAlign = 'right';
        ctx.fillText(`Entfeuchter AUS: ${liveHumidityTimeseriesData.threshold_low}%`, canvas.width - padding - 10, thresholdY + 15);
    }

    // Legende
    ctx.fillStyle = '#1f2937';
    ctx.font = '14px Arial';
    ctx.textAlign = 'left';

    // Badezimmer-Sensor
    ctx.fillStyle = '#3b82f6';
    ctx.fillRect(padding + 10, padding + 10, 15, 3);
    ctx.fillStyle = '#1f2937';
    ctx.fillText(`Badezimmer: ${smoothedValues[smoothedValues.length - 1].toFixed(1)}%`, padding + 32, padding + 15);

    // Duschsensor
    if (smoothedShowerValues.some(v => v !== null)) {
        const lastShowerValue = smoothedShowerValues.filter(v => v !== null).pop();
        ctx.fillStyle = '#a855f7';
        ctx.fillRect(padding + 10, padding + 30, 15, 3);
        ctx.fillStyle = '#1f2937';
        ctx.fillText(`Duschsensor: ${lastShowerValue.toFixed(1)}%`, padding + 32, padding + 35);
    }

    // Zusätzliche Legende für Glättung
    ctx.fillStyle = '#6b7280';
    ctx.font = '11px Arial';
    ctx.fillText(`Durchgezogene Linien: geglättete Werte (5-Punkt Moving Average)`, padding + 10, padding + 52);
    ctx.fillText(`Transparente Linien: Rohdaten`, padding + 10, padding + 65);
}

/**
 * Initialisiert das Live-Humidity-Chart und Event Listener
 */
function initLiveHumidityChart() {
    const hoursSelector = document.getElementById('live-hours-selector');
    if (hoursSelector) {
        hoursSelector.addEventListener('change', (e) => {
            const hours = parseInt(e.target.value);
            loadLiveHumidityChart(hours);
        });
    }

    // Initial laden
    loadLiveHumidityChart(6);

    // Auto-Refresh alle 30 Sekunden
    setInterval(() => {
        if (PollingManager.isPageVisible) {
            loadLiveHumidityChart(currentLiveHumidityPeriod);
        }
    }, 30000);
}
