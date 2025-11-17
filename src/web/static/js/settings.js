// Settings Page JavaScript

// === TAB SWITCHING ===

function initTabs() {
    const tabButtons = document.querySelectorAll('.tab-button');
    const tabContents = document.querySelectorAll('.tab-content');

    tabButtons.forEach(button => {
        button.addEventListener('click', () => {
            const targetTab = button.dataset.tab;

            // Entferne active class von allen Buttons und Contents
            tabButtons.forEach(btn => btn.classList.remove('active'));
            tabContents.forEach(content => content.classList.remove('active'));

            // Setze active class für aktuellen Tab
            button.classList.add('active');
            document.getElementById(`tab-${targetTab}`).classList.add('active');

            // Speichere aktiven Tab in localStorage
            localStorage.setItem('settings-active-tab', targetTab);

            // Lade Daten für den Tab wenn nötig
            if (targetTab === 'connection') {
                loadConnectionConfig();
            } else if (targetTab === 'database') {
                loadDatabaseStatus();
            } else if (targetTab === 'ml') {
                loadMLStatus();
            } else if (targetTab === 'system') {
                loadVersion();
            }
        });
    });

    // Stelle letzten aktiven Tab wieder her
    const savedTab = localStorage.getItem('settings-active-tab');
    if (savedTab) {
        const tabButton = document.querySelector(`[data-tab="${savedTab}"]`);
        if (tabButton) {
            tabButton.click();
        }
    }
}

// Lade Konfiguration
async function loadConfig() {
    try {
        const data = await fetchJSON('/api/config');

        // Platform Type
        document.getElementById('platform-type').value = data.platform_type || 'homeassistant';

        // Data Collection Interval
        document.getElementById('collection-interval').value = data.data_collection_interval || 300;

        // Decision Mode
        document.getElementById('decision-mode').value = data.decision_mode || 'auto';

        // Confidence Threshold
        const threshold = data.confidence_threshold || 0.7;
        document.getElementById('confidence-threshold').value = threshold;
        document.getElementById('confidence-value').textContent = threshold.toFixed(2);

        // Lade gespeicherte Einstellungen aus settings_general.json (falls vorhanden)
        try {
            const settingsResponse = await fetch('/api/settings/general');
            if (settingsResponse.ok) {
                const settings = await settingsResponse.json();

                // Data Collection Settings
                if (settings.data_collection) {
                    if (settings.data_collection.interval) {
                        document.getElementById('collection-interval').value = settings.data_collection.interval;
                    }
                    if (typeof settings.data_collection.weather_enabled !== 'undefined') {
                        document.getElementById('enable-weather').checked = settings.data_collection.weather_enabled;
                    }
                    if (typeof settings.data_collection.energy_prices_enabled !== 'undefined') {
                        document.getElementById('enable-energy-prices').checked = settings.data_collection.energy_prices_enabled;
                    }
                }

                // Decision Engine Settings
                if (settings.decision_engine) {
                    if (settings.decision_engine.mode) {
                        document.getElementById('decision-mode').value = settings.decision_engine.mode;
                    }
                    if (typeof settings.decision_engine.confidence_threshold !== 'undefined') {
                        const threshold = settings.decision_engine.confidence_threshold;
                        document.getElementById('confidence-threshold').value = threshold;
                        document.getElementById('confidence-value').textContent = threshold.toFixed(2);
                    }
                }
            }
        } catch (settingsError) {
            // Kein Problem wenn Datei nicht existiert - verwende defaults
            console.log('No saved settings found, using defaults');
        }

    } catch (error) {
        console.error('Error loading config:', error);
    }
}

// Confidence Slider
document.getElementById('confidence-threshold').addEventListener('input', (e) => {
    document.getElementById('confidence-value').textContent = parseFloat(e.target.value).toFixed(2);
});

// === CONFIG UPDATE API ===

/**
 * Speichert komplette Konfiguration über /api/config/update
 */
async function saveConfigViaAPI(configUpdates) {
    try {
        const response = await fetch('/api/config/update', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(configUpdates)
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.error || 'Fehler beim Speichern der Konfiguration');
        }

        return { success: true, message: data.message };

    } catch (error) {
        console.error('Error saving config:', error);
        return { success: false, error: error.message };
    }
}

// === ALLGEMEIN-TAB SPEICHERN ===

// Speichere Datensammlungs-Einstellungen
document.getElementById('save-data-collection')?.addEventListener('click', async () => {
    const resultEl = document.getElementById('data-collection-result');
    const btn = document.getElementById('save-data-collection');

    const collectionInterval = parseInt(document.getElementById('collection-interval').value);
    const enableWeather = document.getElementById('enable-weather').checked;
    const enableEnergyPrices = document.getElementById('enable-energy-prices').checked;

    try {
        btn.disabled = true;
        resultEl.textContent = 'Speichere Einstellungen...';
        resultEl.className = 'action-result loading';
        resultEl.style.display = 'block';

        const response = await fetch('/api/settings/data-collection', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                collection_interval: collectionInterval,
                enable_weather: enableWeather,
                enable_energy_prices: enableEnergyPrices
            })
        });

        const data = await response.json();

        if (data.success) {
            resultEl.textContent = '✓ Einstellungen erfolgreich gespeichert';
            resultEl.className = 'action-result success';
            setTimeout(() => {
                resultEl.style.display = 'none';
            }, 3000);
        } else {
            throw new Error(data.error || 'Unbekannter Fehler');
        }

    } catch (error) {
        console.error('Error saving data collection settings:', error);
        resultEl.textContent = '✗ Fehler beim Speichern: ' + error.message;
        resultEl.className = 'action-result error';
    } finally {
        btn.disabled = false;
    }
});

// Speichere Entscheidungs-Engine-Einstellungen
document.getElementById('save-decision-engine')?.addEventListener('click', async () => {
    const resultEl = document.getElementById('decision-engine-result');
    const btn = document.getElementById('save-decision-engine');

    const decisionMode = document.getElementById('decision-mode').value;
    const confidenceThreshold = parseFloat(document.getElementById('confidence-threshold').value);

    try {
        btn.disabled = true;
        resultEl.textContent = 'Speichere Einstellungen...';
        resultEl.className = 'action-result loading';
        resultEl.style.display = 'block';

        const response = await fetch('/api/settings/decision-engine', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                decision_mode: decisionMode,
                confidence_threshold: confidenceThreshold
            })
        });

        const data = await response.json();

        if (data.success) {
            resultEl.textContent = '✓ Einstellungen erfolgreich gespeichert';
            resultEl.className = 'action-result success';
            setTimeout(() => {
                resultEl.style.display = 'none';
            }, 3000);
        } else {
            throw new Error(data.error || 'Unbekannter Fehler');
        }

    } catch (error) {
        console.error('Error saving decision engine settings:', error);
        resultEl.textContent = '✗ Fehler beim Speichern: ' + error.message;
        resultEl.className = 'action-result error';
    } finally {
        btn.disabled = false;
    }
});

// Verbindung testen
document.getElementById('test-connection').addEventListener('click', async () => {
    const resultEl = document.getElementById('action-result');
    resultEl.textContent = 'Teste Verbindungen...';
    resultEl.className = 'action-result';
    resultEl.style.display = 'block';

    try {
        const data = await fetchJSON('/api/connection-test');

        let resultHTML = '<h4>Testergebnisse:</h4><ul>';
        for (const [service, status] of Object.entries(data.results)) {
            const icon = status ? '✓' : '✗';
            const statusText = status ? 'OK' : 'FEHLER';
            resultHTML += `<li>${icon} ${service}: ${statusText}</li>`;
        }
        resultHTML += '</ul>';

        resultEl.innerHTML = resultHTML;
        resultEl.className = 'action-result ' + (data.all_ok ? 'success' : 'error');

    } catch (error) {
        resultEl.textContent = 'Fehler beim Testen der Verbindungen: ' + error.message;
        resultEl.className = 'action-result error';
    }
});

// Training Progress Tracking
let trainingProgressInterval = null;

async function pollTrainingProgress() {
    try {
        const response = await fetch('/api/ml/train/status');
        const status = await response.json();

        const container = document.getElementById('training-progress-container');
        const progressBar = document.getElementById('training-progress-bar');
        const progressPercent = document.getElementById('training-progress-percent');
        const modelName = document.getElementById('training-model-name');
        const stepText = document.getElementById('training-step');

        if (status.status === 'training') {
            // Zeige Progress Bar
            container.style.display = 'block';

            // Update UI
            const modelDisplayName = status.model === 'lighting' ? 'Lighting Model' : 'Temperature Model';
            modelName.textContent = `Training: ${modelDisplayName}`;
            stepText.textContent = status.step || 'Bitte warten...';

            const progress = status.progress || 0;
            progressBar.style.width = `${progress}%`;
            progressPercent.textContent = `${progress}%`;

        } else if (status.status === 'completed') {
            // Training fertig - zeige 100% kurz an
            progressBar.style.width = '100%';
            progressPercent.textContent = '100%';
            stepText.textContent = 'Abgeschlossen!';

            // Stoppe Polling
            clearInterval(trainingProgressInterval);
            trainingProgressInterval = null;

            // Verstecke Progress nach 3 Sekunden
            setTimeout(() => {
                container.style.display = 'none';
            }, 3000);

        } else if (status.status === 'error') {
            // Fehler
            stepText.textContent = `Fehler: ${status.error || 'Unbekannter Fehler'}`;
            progressBar.style.background = 'linear-gradient(90deg, #f44336, #d32f2f)';

            // Stoppe Polling
            clearInterval(trainingProgressInterval);
            trainingProgressInterval = null;

        } else if (status.status === 'idle') {
            // Kein Training läuft
            if (trainingProgressInterval) {
                clearInterval(trainingProgressInterval);
                trainingProgressInterval = null;
            }
            container.style.display = 'none';
        }

    } catch (error) {
        console.error('Error polling training progress:', error);
    }
}

// Modelle neu trainieren
document.getElementById('retrain-models').addEventListener('click', async () => {
    const resultEl = document.getElementById('action-result');

    if (!confirm('Möchten Sie die ML-Modelle wirklich neu trainieren? Dies kann einige Minuten dauern.')) {
        return;
    }

    resultEl.textContent = 'Training wird gestartet... Dies kann einige Minuten dauern.';
    resultEl.className = 'action-result';
    resultEl.style.display = 'block';

    // Zeige Progress Bar und starte Polling
    document.getElementById('training-progress-container').style.display = 'block';
    if (trainingProgressInterval) {
        clearInterval(trainingProgressInterval);
    }
    trainingProgressInterval = setInterval(pollTrainingProgress, 500);  // Poll alle 500ms

    try {
        const response = await fetch('/api/ml/train', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ model: 'all' })
        });

        const data = await response.json();

        if (data.success) {
            resultEl.textContent = data.message;
            resultEl.className = 'action-result success';
        } else {
            resultEl.textContent = `Fehler: ${data.message || 'Training fehlgeschlagen'}`;
            resultEl.className = 'action-result error';

            // Stoppe Polling bei Fehler
            if (trainingProgressInterval) {
                clearInterval(trainingProgressInterval);
                trainingProgressInterval = null;
            }
        }
    } catch (error) {
        resultEl.textContent = `Fehler beim Training: ${error.message}`;
        resultEl.className = 'action-result error';

        // Stoppe Polling bei Fehler
        if (trainingProgressInterval) {
            clearInterval(trainingProgressInterval);
            trainingProgressInterval = null;
        }
    }
});

// Daten löschen
document.getElementById('clear-data').addEventListener('click', async () => {
    const resultEl = document.getElementById('action-result');

    if (!confirm('Möchten Sie wirklich ALLE historischen Daten löschen? Diese Aktion kann nicht rückgängig gemacht werden!')) {
        return;
    }

    if (!confirm('Sind Sie ABSOLUT SICHER? Alle Trainingsdaten gehen verloren!')) {
        return;
    }

    resultEl.textContent = 'Daten werden gelöscht... Dies kann nicht rückgängig gemacht werden.';
    resultEl.className = 'action-result';
    resultEl.style.display = 'block';

    try {
        const response = await fetch('/api/data/clear', {
            method: 'DELETE'
        });

        const data = await response.json();

        if (data.success) {
            resultEl.textContent = `Erfolgreich: ${data.message}`;
            resultEl.className = 'action-result success';

            // Reload page nach 2 Sekunden um Stats zu aktualisieren
            setTimeout(() => {
                window.location.reload();
            }, 2000);
        } else {
            resultEl.textContent = `Fehler: ${data.error || 'Löschung fehlgeschlagen'}`;
            resultEl.className = 'action-result error';
        }
    } catch (error) {
        resultEl.textContent = `Fehler beim Löschen: ${error.message}`;
        resultEl.className = 'action-result error';
    }
});

// Sensor Configuration
let availableSensors = { temperature_sensors: [], humidity_sensors: [] };
let selectedSensors = { temperature_sensors: [], humidity_sensors: [] };

async function loadSensorConfig() {
    try {
        // Lade verfügbare Sensoren
        const available = await fetchJSON('/api/sensors/available');
        availableSensors = available;

        // Lade gespeicherte Konfiguration
        const config = await fetchJSON('/api/sensors/config');
        selectedSensors = config;

        // Rendere Sensor-Listen
        renderSensorList('temp', available.temperature_sensors, config.temperature_sensors);
        renderSensorList('humidity', available.humidity_sensors, config.humidity_sensors);

    } catch (error) {
        console.error('Error loading sensor config:', error);
        document.getElementById('temp-sensors-list').innerHTML =
            '<p class="error">Fehler beim Laden der Sensoren</p>';
        document.getElementById('humidity-sensors-list').innerHTML =
            '<p class="error">Fehler beim Laden der Sensoren</p>';
    }
}

function renderSensorList(type, sensors, selectedIds) {
    const containerId = type === 'temp' ? 'temp-sensors-list' : 'humidity-sensors-list';
    const container = document.getElementById(containerId);

    if (sensors.length === 0) {
        container.innerHTML = '<p class="empty-state">Keine Sensoren gefunden</p>';
        return;
    }

    container.innerHTML = sensors.map(sensor => {
        const isSelected = selectedIds.length === 0 || selectedIds.includes(sensor.id);
        const zoneName = sensor.zone ? ` (${sensor.zone})` : '';
        const currentValue = sensor.current_value !== null ?
            (type === 'temp' ? `${sensor.current_value}°C` : `${sensor.current_value}%`) : '';

        return `
            <div class="sensor-item">
                <label>
                    <input type="checkbox"
                           class="sensor-checkbox ${type}-sensor"
                           data-sensor-id="${sensor.id}"
                           ${isSelected ? 'checked' : ''}>
                    <span class="sensor-name">${sensor.name}${zoneName}</span>
                    <span class="sensor-value">${currentValue}</span>
                </label>
            </div>
        `;
    }).join('');
}

// Select/Deselect All
document.getElementById('select-all-temp').addEventListener('click', () => {
    document.querySelectorAll('.temp-sensor').forEach(cb => cb.checked = true);
});

document.getElementById('deselect-all-temp').addEventListener('click', () => {
    document.querySelectorAll('.temp-sensor').forEach(cb => cb.checked = false);
});

document.getElementById('select-all-humidity').addEventListener('click', () => {
    document.querySelectorAll('.humidity-sensor').forEach(cb => cb.checked = true);
});

document.getElementById('deselect-all-humidity').addEventListener('click', () => {
    document.querySelectorAll('.humidity-sensor').forEach(cb => cb.checked = false);
});

// Speichere Sensor-Konfiguration
document.getElementById('save-sensor-config').addEventListener('click', async () => {
    const resultEl = document.getElementById('sensor-save-result');

    // Sammle ausgewählte Sensoren
    const tempSensors = Array.from(document.querySelectorAll('.temp-sensor:checked'))
        .map(cb => cb.dataset.sensorId);
    const humiditySensors = Array.from(document.querySelectorAll('.humidity-sensor:checked'))
        .map(cb => cb.dataset.sensorId);

    try {
        resultEl.textContent = 'Speichere Konfiguration...';
        resultEl.className = 'action-result';
        resultEl.style.display = 'block';

        const response = await fetch('/api/sensors/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                temperature_sensors: tempSensors,
                humidity_sensors: humiditySensors
            })
        });

        const data = await response.json();

        if (data.success) {
            resultEl.textContent = '✓ ' + data.message;
            resultEl.className = 'action-result success';

            // Automatisch nach 3 Sekunden ausblenden
            setTimeout(() => {
                resultEl.style.display = 'none';
            }, 3000);
        } else {
            resultEl.textContent = '✗ Fehler: ' + (data.error || 'Unbekannter Fehler');
            resultEl.className = 'action-result error';
        }

    } catch (error) {
        resultEl.textContent = '✗ Fehler beim Speichern: ' + error.message;
        resultEl.className = 'action-result error';
    }
});

// ===== System Update Functions =====

// Lade aktuelle Version
async function loadVersion() {
    try {
        const data = await fetchJSON('/api/system/version');

        if (data.success) {
            document.getElementById('current-version').textContent = data.version.message;
            document.getElementById('current-commit').textContent = data.version.commit + ' (' + data.version.time + ')';
        } else {
            document.getElementById('current-version').textContent = 'Nicht verfügbar';
            document.getElementById('current-commit').textContent = '--';
        }
    } catch (error) {
        console.error('Error loading version:', error);
        document.getElementById('current-version').textContent = 'Fehler';
    }
}

// Prüfe auf Updates
async function checkForUpdates() {
    const statusEl = document.getElementById('update-status');
    const installBtn = document.getElementById('install-update');
    const commitsList = document.getElementById('new-commits-list');
    const resultEl = document.getElementById('update-result');

    try {
        statusEl.textContent = 'Prüfe...';
        resultEl.textContent = '';
        resultEl.style.display = 'none';

        const data = await fetchJSON('/api/system/check-update');

        if (data.success) {
            if (data.update_available) {
                statusEl.textContent = `Ja (${data.commits_behind} neue${data.commits_behind > 1 ? '' : 's'} Update)`;
                statusEl.style.color = '#ff9800';
                installBtn.style.display = 'inline-block';

                // Zeige neue Commits
                if (data.new_commits && data.new_commits.length > 0) {
                    const list = document.getElementById('commits-list');
                    list.innerHTML = data.new_commits.map(commit =>
                        `<li><code>${commit.hash}</code> ${commit.message}</li>`
                    ).join('');
                    commitsList.style.display = 'block';
                }
            } else {
                statusEl.textContent = 'Nein - System ist aktuell';
                statusEl.style.color = '#4caf50';
                installBtn.style.display = 'none';
                commitsList.style.display = 'none';
            }
        } else {
            statusEl.textContent = 'Fehler: ' + (data.error || 'Unbekannt');
            statusEl.style.color = '#f44336';
        }
    } catch (error) {
        console.error('Error checking for updates:', error);
        statusEl.textContent = 'Fehler beim Prüfen';
        statusEl.style.color = '#f44336';
    }
}

// Installiere Update
async function installUpdate() {
    const resultEl = document.getElementById('update-result');
    const installBtn = document.getElementById('install-update');

    if (!confirm('System-Update wird durchgeführt.\n\nDas System wird neu gestartet.\nDatenbank und Einstellungen bleiben erhalten.\n\nFortfahren?')) {
        return;
    }

    try {
        installBtn.disabled = true;
        resultEl.textContent = 'Update wird durchgeführt... Bitte warten...';
        resultEl.className = 'action-result';
        resultEl.style.display = 'block';

        const response = await fetch('/api/system/update', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });

        const data = await response.json();

        if (data.success) {
            resultEl.textContent = '✓ ' + data.message + '\n\nSeite wird in 10 Sekunden neu geladen...';
            resultEl.className = 'action-result success';

            // Warte 10 Sekunden und reload
            setTimeout(() => {
                window.location.reload();
            }, 10000);
        } else {
            resultEl.textContent = '✗ Fehler: ' + (data.error || 'Unbekannter Fehler');
            resultEl.className = 'action-result error';
            installBtn.disabled = false;
        }

    } catch (error) {
        resultEl.textContent = '✗ Fehler beim Update: ' + error.message;
        resultEl.className = 'action-result error';
        installBtn.disabled = false;
    }
}

// Event Listeners für Update-Buttons
document.getElementById('check-update').addEventListener('click', checkForUpdates);
document.getElementById('install-update').addEventListener('click', installUpdate);

// ===== Server Restart Function =====

// Starte Webserver neu
async function restartServer() {
    const resultEl = document.getElementById('restart-result');
    const restartBtn = document.getElementById('restart-server');

    if (!confirm('Webserver wird neu gestartet.\n\nDie Seite wird in 5 Sekunden automatisch neu geladen.\n\nFortfahren?')) {
        return;
    }

    try {
        restartBtn.disabled = true;
        resultEl.textContent = '🔄 Server wird neu gestartet... Bitte warten...';
        resultEl.className = 'action-result loading';
        resultEl.style.display = 'block';

        const response = await fetch('/api/system/restart', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });

        const data = await response.json();

        if (data.success) {
            resultEl.textContent = '✓ ' + data.message;
            resultEl.className = 'action-result success';

            // Warte 5 Sekunden und reload
            let countdown = 5;
            const countdownInterval = setInterval(() => {
                countdown--;
                if (countdown > 0) {
                    resultEl.textContent = `✓ Server wird neu gestartet... Seite lädt in ${countdown} Sekunden neu.`;
                } else {
                    clearInterval(countdownInterval);
                    resultEl.textContent = '🔄 Lade Seite neu...';
                    window.location.reload();
                }
            }, 1000);
        } else {
            resultEl.textContent = '✗ Fehler: ' + (data.error || 'Unbekannter Fehler');
            resultEl.className = 'action-result error';
            restartBtn.disabled = false;
        }

    } catch (error) {
        // Fehler ist erwartet, da Server neu startet
        resultEl.textContent = '🔄 Server startet neu... Seite wird in 5 Sekunden neu geladen.';
        resultEl.className = 'action-result loading';

        setTimeout(() => {
            window.location.reload();
        }, 5000);
    }
}

// Event Listener für Restart-Button
document.getElementById('restart-server').addEventListener('click', restartServer);

// ===== ML Training Status Functions =====

// Lade ML Status
async function loadMLStatus() {
    try {
        const data = await fetchJSON('/api/ml/status');

        if (data.success) {
            // Lighting Model Status
            const lightingStatus = data.lighting;
            updateModelStatus('lighting', lightingStatus);

            // Temperature Model Status
            const tempStatus = data.temperature;
            updateModelStatus('temp', tempStatus);

            // Auto-Trainer Status
            const trainerStatus = data.auto_trainer;
            const trainerEl = document.getElementById('autotrainer-status');
            if (trainerStatus.enabled) {
                trainerEl.innerHTML = `
                    <span class="status-dot" style="display: inline-block; width: 8px; height: 8px; border-radius: 50%; background: #10b981; margin-right: 6px;"></span>
                    Aktiv
                `;
            } else {
                trainerEl.innerHTML = `
                    <span class="status-dot" style="display: inline-block; width: 8px; height: 8px; border-radius: 50%; background: #ef4444; margin-right: 6px;"></span>
                    Deaktiviert
                `;
            }

            // Next run info
            const nextRunEl = document.getElementById('autotrainer-next-run');
            if (trainerStatus.last_run) {
                nextRunEl.textContent = `Letzter Run: ${trainerStatus.last_run}`;
            } else {
                nextRunEl.textContent = 'Noch nie gelaufen';
            }

            // Update settings
            document.getElementById('autotrainer-enabled').checked = trainerStatus.enabled;
            document.getElementById('training-hour').value = trainerStatus.run_hour;

            // Show info message if data collection is problematic
            showDataCollectionInfo(lightingStatus, tempStatus);

        } else {
            console.error('Error loading ML status:', data.error);
        }
    } catch (error) {
        console.error('Error loading ML status:', error);
    }
}

function showDataCollectionInfo(lightingStatus, tempStatus) {
    const infoBox = document.getElementById('data-collection-info');
    const messageEl = document.getElementById('data-collection-message');
    
    if (!infoBox || !messageEl) return;
    
    let messages = [];
    
    // Check lighting collector issues
    if (lightingStatus.collector) {
        const lc = lightingStatus.collector;
        if (!lc.collectors_available) {
            messages.push('❌ <strong>Lighting:</strong> Keine Platform-Verbindung (Homey/HomeAssistant). Prüfe die Platform-Konfiguration unter "Allgemein".');
        } else if (!lc.running) {
            messages.push('⚠️ <strong>Lighting:</strong> Datensammler ist gestoppt. Wird automatisch beim Serverstart aktiviert.');
        } else if (lc.last_error) {
            messages.push(`❌ <strong>Lighting:</strong> Fehler beim Sammeln: ${lc.last_error}`);
        } else if (lightingStatus.data_count === 0 && lc.last_collection) {
            messages.push('💡 <strong>Lighting:</strong> Collector läuft, aber noch keine Daten. Schalte Lampen ein/aus, um Events zu generieren.');
        }
    }
    
    // Check temperature collector issues
    if (tempStatus.collector) {
        const tc = tempStatus.collector;
        if (!tc.collectors_available) {
            messages.push('❌ <strong>Temperature:</strong> Keine Platform-Verbindung (Homey/HomeAssistant). Prüfe die Platform-Konfiguration unter "Allgemein".');
        } else if (!tc.running) {
            messages.push('⚠️ <strong>Temperature:</strong> Datensammler ist gestoppt. Wird automatisch beim Serverstart aktiviert.');
        } else if (tc.last_error) {
            messages.push(`❌ <strong>Temperature:</strong> Fehler beim Sammeln: ${tc.last_error}`);
        } else if (tempStatus.data_count === 0 && tc.last_collection) {
            messages.push('💡 <strong>Temperature:</strong> Collector läuft, aber noch keine Daten. Stelle sicher, dass Thermostate konfiguriert sind.');
        }
    }
    
    // Show or hide info box
    if (messages.length > 0) {
        messageEl.innerHTML = messages.join('<br><br>');
        infoBox.style.display = 'block';
    } else {
        infoBox.style.display = 'none';
    }
}

function updateModelStatus(modelType, status) {
    const prefix = modelType === 'lighting' ? 'lighting' : 'temp';
    const statusEl = document.getElementById(`${prefix}-model-status`);
    const dataCountEl = document.getElementById(`${prefix}-data-count`);
    const lastTrainedEl = document.getElementById(`${prefix}-last-trained`);
    const collectorStatusEl = document.getElementById(`${prefix}-collector-status`);

    // Status Text und Farbe
    let statusText = 'Warte auf Daten';
    let statusColor = '#fbbf24'; // yellow

    if (status.trained) {
        statusText = 'Trainiert ✓';
        statusColor = '#10b981'; // green
    } else if (status.ready) {
        statusText = 'Bereit zum Training';
        statusColor = '#3b82f6'; // blue
    }

    statusEl.innerHTML = `
        <span class="status-dot" style="display: inline-block; width: 8px; height: 8px; border-radius: 50%; background: ${statusColor}; margin-right: 6px;"></span>
        ${statusText}
    `;

    // Data Count
    const unit = modelType === 'lighting' ? 'Events' : 'Readings';
    dataCountEl.textContent = `${status.data_count} / ${status.required} ${unit}`;

    // Last Trained
    if (status.last_trained) {
        lastTrainedEl.textContent = `Trainiert: ${status.last_trained}`;
    } else {
        lastTrainedEl.textContent = 'Nie trainiert';
    }

    // Collector Status
    if (collectorStatusEl && status.collector) {
        const collector = status.collector;
        let collectorHTML = '';
        
        if (!collector.collectors_available) {
            collectorHTML = `<div style="color: #ef4444; font-size: 12px;">⚠️ Keine Platform-Verbindung</div>`;
        } else if (!collector.running) {
            collectorHTML = `<div style="color: #f59e0b; font-size: 12px;">⚠️ Collector gestoppt</div>`;
        } else if (collector.last_error) {
            collectorHTML = `
                <div style="color: #ef4444; font-size: 12px;">
                    ❌ Fehler: ${collector.last_error.substring(0, 50)}${collector.last_error.length > 50 ? '...' : ''}
                </div>
            `;
        } else if (collector.last_collection) {
            const lastTime = new Date(collector.last_collection);
            const now = new Date();
            const minutesAgo = Math.floor((now - lastTime) / 60000);
            
            const sessionKey = modelType === 'lighting' ? 'events_this_session' : 'measurements_this_session';
            const sessionCount = collector[sessionKey] || 0;
            
            let timeStr = '';
            if (minutesAgo < 1) {
                timeStr = 'Gerade eben';
            } else if (minutesAgo < 60) {
                timeStr = `vor ${minutesAgo} Min`;
            } else {
                const hoursAgo = Math.floor(minutesAgo / 60);
                timeStr = `vor ${hoursAgo}h`;
            }
            
            // Show live indicator if collecting recently
            const isLive = minutesAgo < 5;
            const liveIndicator = isLive ? '<span style="color: #10b981;">🟢</span> ' : '';
            
            collectorHTML = `
                <div style="font-size: 12px; color: #10b981;">
                    ${liveIndicator}${collector.last_success ? '✓' : '⚠️'} Sammelt Daten
                </div>
                <div style="font-size: 11px; color: #6b7280; margin-top: 2px;">
                    ${timeStr} • ${sessionCount} diese Session
                </div>
            `;
        } else {
            collectorHTML = `<div style="color: #6b7280; font-size: 12px;">Warte auf erste Sammlung...</div>`;
        }
        
        collectorStatusEl.innerHTML = collectorHTML;
    } else if (collectorStatusEl) {
        collectorStatusEl.innerHTML = '<div style="color: #6b7280; font-size: 12px;">Status unbekannt</div>';
    }
}

// Lade Training History
async function loadTrainingHistory() {
    const historyEl = document.getElementById('training-history');

    try {
        historyEl.innerHTML = '<div class="loading">Lade Verlauf...</div>';
        const data = await fetchJSON('/api/ml/training-history');

        if (data.success && data.history.length > 0) {
            let historyHTML = '<table style="width: 100%; border-collapse: collapse;">';
            historyHTML += '<thead><tr style="border-bottom: 2px solid #e5e7eb;">';
            historyHTML += '<th style="text-align: left; padding: 8px;">Zeit</th>';
            historyHTML += '<th style="text-align: left; padding: 8px;">Modell</th>';
            historyHTML += '<th style="text-align: right; padding: 8px;">Genauigkeit</th>';
            historyHTML += '<th style="text-align: right; padding: 8px;">Samples</th>';
            historyHTML += '<th style="text-align: right; padding: 8px;">Dauer</th>';
            historyHTML += '</tr></thead><tbody>';

            data.history.forEach((record, index) => {
                const bgColor = index % 2 === 0 ? '#f9fafb' : 'white';
                const accuracy = (record.accuracy * 100).toFixed(1);
                const time = record.training_time ? record.training_time.toFixed(1) + 's' : '--';

                historyHTML += `<tr style="background: ${bgColor};">`;
                historyHTML += `<td style="padding: 8px;">${record.timestamp}</td>`;
                historyHTML += `<td style="padding: 8px;">${record.model_name}</td>`;
                historyHTML += `<td style="padding: 8px; text-align: right;">${accuracy}%</td>`;
                historyHTML += `<td style="padding: 8px; text-align: right;">${record.samples_used}</td>`;
                historyHTML += `<td style="padding: 8px; text-align: right;">${time}</td>`;
                historyHTML += '</tr>';
            });

            historyHTML += '</tbody></table>';
            historyEl.innerHTML = historyHTML;
        } else {
            historyEl.innerHTML = '<p class="empty-state">Noch keine Trainings durchgeführt</p>';
        }
    } catch (error) {
        console.error('Error loading training history:', error);
        historyEl.innerHTML = '<p class="error">Fehler beim Laden der Historie</p>';
    }
}

// Manual Training
document.getElementById('manual-train').addEventListener('click', async () => {
    const resultEl = document.getElementById('ml-training-result');
    const btn = document.getElementById('manual-train');

    if (!confirm('Manuelles Training starten?\n\nDies kann einige Minuten dauern.\nEs werden nur Modelle trainiert, für die genug Daten vorhanden sind.')) {
        return;
    }

    try {
        btn.disabled = true;
        resultEl.textContent = 'Training wird gestartet... Bitte warten...';
        resultEl.className = 'action-result';
        resultEl.style.display = 'block';

        const response = await fetch('/api/ml/train', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ model: 'all' })
        });

        const data = await response.json();

        if (data.success) {
            let resultText = '✓ Training abgeschlossen:\n\n';

            if (data.results && data.results.lighting) {
                if (data.results.lighting.success) {
                    resultText += `• Lighting Model: Erfolgreich (${(data.results.lighting.accuracy * 100).toFixed(1)}% Genauigkeit)\n`;
                } else {
                    resultText += `• Lighting Model: ${data.results.lighting.error || 'Nicht genug Daten'}\n`;
                }
            }

            if (data.results && data.results.temperature) {
                if (data.results.temperature.success) {
                    resultText += `• Temperature Model: Erfolgreich (R² = ${data.results.temperature.r2_score.toFixed(3)})\n`;
                } else {
                    resultText += `• Temperature Model: ${data.results.temperature.error || 'Nicht genug Daten'}\n`;
                }
            }
            
            // Fallback auf message wenn results nicht vorhanden
            if (!data.results && data.message) {
                resultText = '✓ ' + data.message;
            }

            resultEl.textContent = resultText;
            resultEl.className = 'action-result success';

            // Aktualisiere Status
            setTimeout(() => {
                loadMLStatus();
                loadTrainingHistory();
            }, 1000);

        } else {
            resultEl.textContent = '✗ Fehler: ' + (data.error || 'Unbekannter Fehler');
            resultEl.className = 'action-result error';
        }

    } catch (error) {
        resultEl.textContent = '✗ Fehler beim Training: ' + error.message;
        resultEl.className = 'action-result error';
    } finally {
        btn.disabled = false;
    }
});

// Refresh ML Status
document.getElementById('refresh-ml-status').addEventListener('click', () => {
    loadMLStatus();
});

// Training History Details Toggle
const historyDetails = document.querySelector('details');
if (historyDetails) {
    historyDetails.addEventListener('toggle', (e) => {
        if (e.target.open) {
            loadTrainingHistory();
        }
    });
}

// === HEIZUNGS-MODUS FUNKTIONEN ===

// Lade Heizungs-Modus
async function loadHeatingMode() {
    try {
        const data = await fetchJSON('/api/heating/mode');
        const mode = data.mode || 'control';

        const select = document.getElementById('heating-mode');
        if (select) {
            select.value = mode;
            updateHeatingModeDescription(mode);
        }
    } catch (error) {
        console.error('Error loading heating mode:', error);
    }
}

// Update Beschreibung basierend auf Modus
function updateHeatingModeDescription(mode) {
    const descriptionEl = document.getElementById('heating-mode-description');
    if (!descriptionEl) return;

    if (mode === 'control') {
        descriptionEl.innerHTML = `
            <strong>🎮 Steuerungs-Modus:</strong>
            <ul style="margin: 5px 0 0 0; padding-left: 20px;">
                <li>KI-System steuert die Heizung <strong>direkt und automatisch</strong></li>
                <li>Nutzt ML-Modelle für optimale Temperaturen</li>
                <li>Schnellaktionen und Zeitpläne verfügbar</li>
                <li>Für vollautomatische Smart-Home-Steuerung</li>
            </ul>
        `;
    } else {
        descriptionEl.innerHTML = `
            <strong>📊 Optimierungs-Modus:</strong>
            <ul style="margin: 5px 0 0 0; padding-left: 20px;">
                <li><strong>Perfekt für Tado X</strong> und andere externe Steuerungen</li>
                <li>System sammelt Daten über Heizverhalten</li>
                <li>Generiert KI-basierte Optimierungsvorschläge</li>
                <li>Zeigt Einsparpotenziale in € und %</li>
                <li><strong>Keine automatischen Eingriffe</strong> - Sie behalten die Kontrolle</li>
            </ul>
        `;
    }
}

// Heizungs-Modus ändern Event
const heatingModeSelect = document.getElementById('heating-mode');
if (heatingModeSelect) {
    heatingModeSelect.addEventListener('change', (e) => {
        updateHeatingModeDescription(e.target.value);
    });
}

// Heizungs-Modus speichern
const saveHeatingModeBtn = document.getElementById('save-heating-mode');
if (saveHeatingModeBtn) {
    saveHeatingModeBtn.addEventListener('click', async () => {
        const resultEl = document.getElementById('heating-mode-result');
        const mode = document.getElementById('heating-mode').value;

        resultEl.innerHTML = '<div class="loading">Speichere...</div>';
        resultEl.style.display = 'block';

        try {
            const response = await fetch('/api/heating/mode', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ mode })
            });

            if (!response.ok) throw new Error('Failed to save mode');

            const data = await response.json();

            resultEl.innerHTML = `
                <div class="success">
                    ✓ Heizungs-Modus gespeichert: <strong>${mode === 'control' ? '🎮 Steuerung' : '📊 Optimierung'}</strong>
                    <br><small>Die Änderung ist sofort auf der Heizungs-Seite sichtbar.</small>
                </div>
            `;

            setTimeout(() => {
                resultEl.style.display = 'none';
            }, 5000);

        } catch (error) {
            console.error('Error saving heating mode:', error);
            resultEl.innerHTML = '<div class="error">✗ Fehler beim Speichern</div>';
        }
    });
}

// === DATENBANK-WARTUNG FUNKTIONEN ===

// Lade Datenbank-Status
async function loadDatabaseStatus() {
    // Zeige Loading-Indikatoren
    document.getElementById('db-size').textContent = '...';
    document.getElementById('db-size-bytes').textContent = 'Lädt...';
    document.getElementById('db-total-rows').textContent = '...';
    document.getElementById('db-oldest-data').textContent = '...';
    document.getElementById('db-data-age').textContent = 'Lädt...';

    try {
        const response = await fetch('/api/database/status');

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }

        const data = await response.json();

        if (data.success && data.database) {
            const db = data.database;
            const settings = data.settings || {};

            // Dateigröße
            if (db.file_size_mb !== undefined && db.file_size_mb !== null) {
                document.getElementById('db-size').textContent = db.file_size_mb + ' MB';
                document.getElementById('db-size-bytes').textContent = formatBytes(db.file_size_bytes || 0);
            } else {
                document.getElementById('db-size').textContent = 'N/A';
                document.getElementById('db-size-bytes').textContent = '--';
            }

            // Gesamt Zeilen
            if (db.total_rows !== undefined && db.total_rows !== null) {
                document.getElementById('db-total-rows').textContent = formatNumber(db.total_rows);
            } else {
                document.getElementById('db-total-rows').textContent = '0';
            }

            // Ältester Eintrag
            if (db.oldest_data) {
                const oldestDate = new Date(db.oldest_data);
                document.getElementById('db-oldest-data').textContent = formatDate(oldestDate);

                // Berechne Alter in Tagen
                const ageInDays = Math.floor((new Date() - oldestDate) / (1000 * 60 * 60 * 24));
                document.getElementById('db-data-age').textContent = ageInDays + ' Tage alt';
            } else {
                document.getElementById('db-oldest-data').textContent = 'Keine Daten';
                document.getElementById('db-data-age').textContent = '0 Tage alt';
            }

            // Retention Days in Input setzen
            document.getElementById('retention-days').value = settings.retention_days || 90;

            // Letzte Wartung
            if (data.maintenance && data.maintenance.last_cleanup) {
                const lastMaintenance = new Date(data.maintenance.last_cleanup);
                const now = new Date();
                const hoursAgo = Math.floor((now - lastMaintenance) / (1000 * 60 * 60));

                if (hoursAgo < 24) {
                    document.getElementById('db-last-maintenance').textContent =
                        hoursAgo === 0 ? 'Gerade eben' : `Vor ${hoursAgo}h`;
                } else {
                    document.getElementById('db-last-maintenance').textContent = formatDate(lastMaintenance);
                }
            } else {
                document.getElementById('db-last-maintenance').textContent = 'Nie';
            }

            // Tabellen-Details
            if (db.table_counts) {
                renderTableDetails(db.table_counts);
            }

        } else {
            throw new Error(data.error || 'Keine Datenbankdaten verfügbar');
        }
    } catch (error) {
        console.error('Error loading database status:', error);

        // Zeige Fehler dem Benutzer
        document.getElementById('db-size').innerHTML = '<span style="color: #ef4444; font-size: 14px;">Fehler</span>';
        document.getElementById('db-size-bytes').textContent = error.message;
        document.getElementById('db-total-rows').textContent = '--';
        document.getElementById('db-oldest-data').textContent = '--';
        document.getElementById('db-data-age').textContent = 'Fehler beim Laden';
        document.getElementById('db-last-maintenance').textContent = '--';
        document.getElementById('db-table-details').innerHTML = `
            <div style="padding: 15px; background: #fee2e2; border-radius: 6px; color: #991b1b;">
                <strong>❌ Fehler beim Laden der Datenbank-Statistiken</strong>
                <p style="margin-top: 8px; font-size: 12px;">${error.message}</p>
                <button onclick="loadDatabaseStatus()" class="btn btn-secondary" style="margin-top: 10px;">
                    🔄 Erneut versuchen
                </button>
            </div>
        `;
    }
}

// Rendere Tabellen-Details
function renderTableDetails(tableCounts) {
    const container = document.getElementById('db-table-details');

    // Sortiere nach Anzahl (absteigend)
    const sorted = Object.entries(tableCounts)
        .filter(([_, count]) => count > 0)
        .sort((a, b) => b[1] - a[1]);

    if (sorted.length === 0) {
        container.innerHTML = '<div style="padding: 10px; color: #6b7280;">Keine Daten vorhanden</div>';
        return;
    }

    let html = '<table style="width: 100%; border-collapse: collapse;">';
    html += '<tr style="border-bottom: 1px solid #e5e7eb; font-weight: 600;"><th style="text-align: left; padding: 8px;">Tabelle</th><th style="text-align: right; padding: 8px;">Zeilen</th></tr>';

    for (const [table, count] of sorted) {
        html += `
            <tr style="border-bottom: 1px solid #f3f4f6;">
                <td style="padding: 8px;">${table}</td>
                <td style="padding: 8px; text-align: right; font-weight: 600;">${formatNumber(count)}</td>
            </tr>
        `;
    }

    html += '</table>';
    container.innerHTML = html;
}

// Cleanup durchführen
async function runCleanup() {
    const retentionDays = parseInt(document.getElementById('retention-days').value);
    const resultEl = document.getElementById('db-maintenance-result');
    const progressContainer = document.getElementById('db-progress-container');
    const progressBar = document.getElementById('db-progress-bar');
    const progressText = document.getElementById('db-progress-text');

    // Deaktiviere Buttons
    setButtonsDisabled(true);

    // Zeige Progress
    progressContainer.style.display = 'block';
    progressBar.style.width = '30%';
    progressText.textContent = 'Lösche alte Daten...';

    resultEl.innerHTML = '<div class="loading">Cleanup läuft...</div>';
    resultEl.style.display = 'block';

    try {
        const response = await fetch('/api/database/cleanup', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ retention_days: retentionDays })
        });

        const data = await response.json();

        progressBar.style.width = '100%';
        progressText.textContent = 'Abgeschlossen!';

        if (data.success) {
            resultEl.innerHTML = `
                <div class="success">
                    ✓ ${data.message}
                    <br><small>Gelöschte Zeilen: ${formatNumber(data.deleted_rows)}</small>
                </div>
            `;

            // Aktualisiere Status
            setTimeout(() => {
                loadDatabaseStatus();
            }, 1000);
        } else {
            throw new Error(data.error || 'Cleanup fehlgeschlagen');
        }

    } catch (error) {
        console.error('Error during cleanup:', error);
        resultEl.innerHTML = `<div class="error">✗ Fehler: ${error.message}</div>`;
    } finally {
        setButtonsDisabled(false);
        setTimeout(() => {
            progressContainer.style.display = 'none';
            progressBar.style.width = '0%';
            resultEl.style.display = 'none';
        }, 5000);
    }
}

// VACUUM durchführen
async function runVacuum() {
    const resultEl = document.getElementById('db-maintenance-result');
    const progressContainer = document.getElementById('db-progress-container');
    const progressBar = document.getElementById('db-progress-bar');
    const progressText = document.getElementById('db-progress-text');

    setButtonsDisabled(true);

    progressContainer.style.display = 'block';
    progressBar.style.width = '50%';
    progressText.textContent = 'Optimiere Datenbank...';

    resultEl.innerHTML = '<div class="loading">VACUUM läuft (kann einige Sekunden dauern)...</div>';
    resultEl.style.display = 'block';

    try {
        const response = await fetch('/api/database/vacuum', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });

        const data = await response.json();

        progressBar.style.width = '100%';
        progressText.textContent = 'Abgeschlossen!';

        if (data.success) {
            resultEl.innerHTML = `
                <div class="success">
                    ✓ ${data.message}
                    <br><small>Größe vorher: ${data.before_size_mb} MB → nachher: ${data.after_size_mb} MB</small>
                </div>
            `;

            // Aktualisiere Status
            setTimeout(() => {
                loadDatabaseStatus();
            }, 1000);
        } else {
            throw new Error(data.error || 'VACUUM fehlgeschlagen');
        }

    } catch (error) {
        console.error('Error during vacuum:', error);
        resultEl.innerHTML = `<div class="error">✗ Fehler: ${error.message}</div>`;
    } finally {
        setButtonsDisabled(false);
        setTimeout(() => {
            progressContainer.style.display = 'none';
            progressBar.style.width = '0%';
            resultEl.style.display = 'none';
        }, 5000);
    }
}

// Vollständige Wartung (Cleanup + Vacuum)
async function runFullMaintenance() {
    const resultEl = document.getElementById('db-maintenance-result');
    const progressContainer = document.getElementById('db-progress-container');
    const progressBar = document.getElementById('db-progress-bar');
    const progressText = document.getElementById('db-progress-text');

    setButtonsDisabled(true);

    progressContainer.style.display = 'block';
    progressBar.style.width = '0%';
    progressText.textContent = 'Starte Wartung...';

    resultEl.innerHTML = '<div class="loading">Führe vollständige Wartung durch...</div>';
    resultEl.style.display = 'block';

    try {
        // 1. Cleanup
        progressBar.style.width = '25%';
        progressText.textContent = '1/2: Lösche alte Daten...';

        const retentionDays = parseInt(document.getElementById('retention-days').value);
        const cleanupResponse = await fetch('/api/database/cleanup', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ retention_days: retentionDays })
        });

        const cleanupData = await cleanupResponse.json();
        if (!cleanupData.success) throw new Error(cleanupData.error);

        // 2. VACUUM
        progressBar.style.width = '60%';
        progressText.textContent = '2/2: Optimiere Datenbank...';

        const vacuumResponse = await fetch('/api/database/vacuum', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });

        const vacuumData = await vacuumResponse.json();
        if (!vacuumData.success) throw new Error(vacuumData.error);

        // Fertig!
        progressBar.style.width = '100%';
        progressText.textContent = 'Abgeschlossen!';

        resultEl.innerHTML = `
            <div class="success">
                ✓ Vollständige Wartung abgeschlossen!
                <br><small>Gelöschte Zeilen: ${formatNumber(cleanupData.deleted_rows)} | Freigegeben: ${vacuumData.freed_mb} MB</small>
            </div>
        `;

        // Aktualisiere Status
        setTimeout(() => {
            loadDatabaseStatus();
        }, 1000);

    } catch (error) {
        console.error('Error during full maintenance:', error);
        resultEl.innerHTML = `<div class="error">✗ Fehler: ${error.message}</div>`;
    } finally {
        setButtonsDisabled(false);
        setTimeout(() => {
            progressContainer.style.display = 'none';
            progressBar.style.width = '0%';
            resultEl.style.display = 'none';
        }, 5000);
    }
}

// Deaktiviere/Aktiviere Buttons während Wartung
function setButtonsDisabled(disabled) {
    document.getElementById('db-cleanup').disabled = disabled;
    document.getElementById('db-vacuum').disabled = disabled;
    document.getElementById('db-full-maintenance').disabled = disabled;
    document.getElementById('db-refresh-status').disabled = disabled;
}

// Event Listeners für Datenbank-Wartung
if (document.getElementById('db-cleanup')) {
    document.getElementById('db-cleanup').addEventListener('click', runCleanup);
    document.getElementById('db-vacuum').addEventListener('click', runVacuum);
    document.getElementById('db-full-maintenance').addEventListener('click', runFullMaintenance);
    document.getElementById('db-refresh-status').addEventListener('click', loadDatabaseStatus);
}

// Hilfsfunktionen
function formatNumber(num) {
    return num.toLocaleString('de-DE');
}

function formatBytes(bytes) {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return Math.round(bytes / Math.pow(k, i) * 100) / 100 + ' ' + sizes[i];
}

function formatDate(date) {
    const options = { year: 'numeric', month: '2-digit', day: '2-digit' };
    return date.toLocaleDateString('de-DE', options);
}

// Init
document.addEventListener('DOMContentLoaded', () => {
    // Initialisiere Tab-System
    initTabs();

    // "Was ist neu" Banner schließen
    const dismissBtn = document.getElementById('dismiss-whats-new');
    if (dismissBtn) {
        dismissBtn.addEventListener('click', () => {
            const banner = dismissBtn.closest('.card');
            banner.style.display = 'none';
            localStorage.setItem('whats-new-v0.9-dismissed', 'true');
        });

        // Prüfe ob Banner bereits geschlossen wurde
        if (localStorage.getItem('whats-new-v0.9-dismissed') === 'true') {
            const banner = dismissBtn.closest('.card');
            banner.style.display = 'none';
        }
    }

    // Lade initiale Daten
    loadConfig();
    loadSensorConfig();
    loadHeatingMode();

    // Die anderen Daten werden nur geladen wenn der entsprechende Tab aktiv ist
    // oder beim ersten Laden wenn kein Tab gespeichert ist
    const savedTab = localStorage.getItem('settings-active-tab');
    if (!savedTab || savedTab === 'general') {
        // Allgemein-Tab ist aktiv - keine Extra-Daten nötig
    } else if (savedTab === 'connection') {
        loadConnectionConfig();
    } else if (savedTab === 'database') {
        loadDatabaseStatus();
    } else if (savedTab === 'ml') {
        loadMLStatus();
    } else if (savedTab === 'system') {
        loadVersion();
        checkForUpdates();
    }
    
    // Init connection tab event listeners
    initConnectionTab();
});

// ===== CONNECTION TAB FUNCTIONS =====

function initConnectionTab() {
    // Multi-Platform checkbox
    const multiPlatformCheckbox = document.getElementById('enable-multi-platform');
    if (multiPlatformCheckbox) {
        multiPlatformCheckbox.addEventListener('change', (e) => {
            const isMulti = e.target.checked;
            const singlePlatformSelect = document.getElementById('single-platform-select');
            const primaryPlatformSelect = document.getElementById('primary-platform-select');
            const multiPlatformHint = document.getElementById('multi-platform-hint');
            
            if (isMulti) {
                // Multi-Platform Mode: Beide Konfigurationen anzeigen
                singlePlatformSelect.style.display = 'none';
                primaryPlatformSelect.style.display = 'block';
                document.getElementById('homey-config').style.display = 'block';
                document.getElementById('ha-config').style.display = 'block';
                
                if (multiPlatformHint) multiPlatformHint.style.display = 'inline';
                
                // Zeige Device-Mapping Buttons
                document.querySelectorAll('.device-mapping-btn').forEach(btn => {
                    btn.style.display = 'inline-block';
                });
            } else {
                // Single-Platform Mode: Nur eine Plattform auswählbar
                singlePlatformSelect.style.display = 'block';
                primaryPlatformSelect.style.display = 'none';
                const platform = document.getElementById('platform-select').value;
                showPlatformConfig(platform);
                
                if (multiPlatformHint) multiPlatformHint.style.display = 'none';
                
                // Verstecke Device-Mapping Buttons
                document.querySelectorAll('.device-mapping-btn').forEach(btn => {
                    btn.style.display = 'none';
                });
            }
        });
    }

    // Platform selection
    const platformSelect = document.getElementById('platform-select');
    if (platformSelect) {
        platformSelect.addEventListener('change', (e) => {
            const isMulti = document.getElementById('enable-multi-platform').checked;
            if (!isMulti) {
                showPlatformConfig(e.target.value);
            }
        });
    }

    // Homey connection type radio buttons
    const homeyRadios = document.querySelectorAll('input[name="homey-type"]');
    homeyRadios.forEach(radio => {
        radio.addEventListener('change', (e) => {
            const isLocal = e.target.value === 'local';
            document.getElementById('homey-local-config').style.display = isLocal ? 'block' : 'none';
            document.getElementById('homey-cloud-config').style.display = isLocal ? 'none' : 'block';
        });
    });

    // Test connection buttons
    const testHomeyBtn = document.getElementById('test-homey-connection');
    if (testHomeyBtn) {
        testHomeyBtn.addEventListener('click', testHomeyConnection);
    }

    const testHaBtn = document.getElementById('test-ha-connection');
    if (testHaBtn) {
        testHaBtn.addEventListener('click', testHAConnection);
    }

    // Save button
    const saveBtn = document.getElementById('save-connection-config');
    if (saveBtn) {
        saveBtn.addEventListener('click', saveConnectionConfig);
    }

    // Data Collection Config save button
    const saveDataCollectionBtn = document.getElementById('save-data-collection-config');
    if (saveDataCollectionBtn) {
        saveDataCollectionBtn.addEventListener('click', saveDataCollectionConfig);
    }

    // Device Mapping Buttons
    document.querySelectorAll('.device-mapping-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            const dataType = e.target.getAttribute('data-type');
            openDeviceMappingModal(dataType);
        });
    });

    // Modal Controls
    const modal = document.getElementById('device-mapping-modal');
    const closeBtn = modal?.querySelector('.modal-close');
    const cancelBtn = document.getElementById('cancel-mapping');
    const saveBtn2 = document.getElementById('save-mapping');

    if (closeBtn) {
        closeBtn.addEventListener('click', closeDeviceMappingModal);
    }
    if (cancelBtn) {
        cancelBtn.addEventListener('click', closeDeviceMappingModal);
    }
    if (saveBtn2) {
        saveBtn2.addEventListener('click', saveDeviceMapping);
    }

    // Modal click outside to close
    if (modal) {
        modal.addEventListener('click', (e) => {
            if (e.target === modal) {
                closeDeviceMappingModal();
            }
        });
    }

    // Search functionality
    const searchInput = document.getElementById('secondary-device-search');
    if (searchInput) {
        searchInput.addEventListener('input', filterSecondaryDevices);
    }

    // Load and start updating connection status
    loadDataCollectionConfig();
    updateConnectionStatus();
    setInterval(updateConnectionStatus, 10000); // Update every 10 seconds
}

async function updateConnectionStatus() {
    try {
        const data = await fetchJSON('/api/connection/status');
        const statusContent = document.getElementById('connection-status-content');
        const liveIndicator = document.getElementById('connection-live-indicator');
        
        if (!statusContent) return;

        let html = '<div style="display: grid; gap: 15px;">';

        // Multi-Platform Mode
        if (data.multi_platform) {
            html += '<div style="font-size: 14px; font-weight: 600; color: #059669; background: #f0fdf4; padding: 10px; border-radius: 6px; border-left: 4px solid #10b981;">🔀 Multi-Platform Modus aktiv</div>';
            
            // Show status for each platform
            if (data.platforms) {
                for (const [platformName, platformData] of Object.entries(data.platforms)) {
                    const connectedIcon = platformData.connected ? '🟢' : '🔴';
                    const connectedText = platformData.connected ? 'Verbunden' : 'Nicht verbunden';
                    const connectedColor = platformData.connected ? '#10b981' : '#ef4444';
                    const platformLabel = platformName === 'homey' ? 'Homey Pro' : 'Home Assistant';
                    
                    html += `
                        <div style="display: flex; align-items: center; gap: 10px; padding: 10px; background: white; border-radius: 6px; border-left: 4px solid ${connectedColor};">
                            <span style="font-size: 20px;">${connectedIcon}</span>
                            <div style="flex: 1;">
                                <div style="font-weight: 600;">${platformLabel}</div>
                                <div style="font-size: 13px; color: #6b7280;">${connectedText}</div>
                            </div>
                            <div style="text-align: right;">
                                <div style="font-size: 18px; font-weight: 700; color: ${connectedColor};">${platformData.device_count || 0}</div>
                                <div style="font-size: 11px; color: #6b7280;">Geräte</div>
                            </div>
                        </div>
                    `;
                    
                    if (platformData.error) {
                        html += `
                            <div style="padding: 8px 10px; background: #fef2f2; border-left: 3px solid #ef4444; border-radius: 6px; font-size: 12px; color: #991b1b; margin-top: -10px;">
                                ${platformData.error}
                            </div>
                        `;
                    }
                }
            }
        } else {
            // Single Platform Mode
            const connectedIcon = data.connected ? '🟢' : '🔴';
            const connectedText = data.connected ? 'Verbunden' : 'Nicht verbunden';
            const connectedColor = data.connected ? '#10b981' : '#ef4444';
            
            html += `
                <div style="display: flex; align-items: center; gap: 10px; padding: 10px; background: white; border-radius: 6px; border-left: 4px solid ${connectedColor};">
                    <span style="font-size: 20px;">${connectedIcon}</span>
                    <div style="flex: 1;">
                        <div style="font-weight: 600;">${data.platform_type === 'homey' ? 'Homey Pro' : 'Home Assistant'}</div>
                        <div style="font-size: 13px; color: #6b7280;">${connectedText}</div>
                    </div>
                    <div style="text-align: right;">
                        <div style="font-size: 18px; font-weight: 700; color: ${connectedColor};">${data.device_count}</div>
                        <div style="font-size: 11px; color: #6b7280;">Geräte</div>
                    </div>
                </div>
            `;
            
            if (data.error) {
                html += `
                    <div style="padding: 10px; background: #fef2f2; border-left: 4px solid #ef4444; border-radius: 6px; font-size: 13px; color: #991b1b;">
                        <strong>Fehler:</strong> ${data.error}
                    </div>
                `;
            }
        }

        // Data Collectors Status
        if (data.collectors && data.collectors.length > 0) {
            html += '<div style="font-size: 13px; font-weight: 600; margin-top: 10px; color: #374151;">Daten-Sammler:</div>';
            
            data.collectors.forEach(collector => {
                const isActive = collector.running;
                const statusIcon = isActive ? '🟢' : '⚫';
                const statusColor = isActive ? '#10b981' : '#9ca3af';
                
                let lastCollection = 'Noch keine Daten';
                if (collector.last_collection) {
                    const lastTime = new Date(collector.last_collection);
                    const now = new Date();
                    const diffMinutes = Math.floor((now - lastTime) / 1000 / 60);
                    
                    if (diffMinutes < 1) {
                        lastCollection = 'Gerade eben';
                    } else if (diffMinutes < 60) {
                        lastCollection = `vor ${diffMinutes} Min`;
                    } else {
                        const diffHours = Math.floor(diffMinutes / 60);
                        lastCollection = `vor ${diffHours}h ${diffMinutes % 60}m`;
                    }
                }

                const collectedCount = collector.events_collected || collector.measurements_collected || 0;
                
                html += `
                    <div style="display: flex; align-items: center; gap: 10px; padding: 8px 10px; background: white; border-radius: 6px; border-left: 3px solid ${statusColor};">
                        <span>${statusIcon}</span>
                        <div style="flex: 1;">
                            <div style="font-size: 13px; font-weight: 600;">${collector.name} Collector</div>
                            <div style="font-size: 11px; color: #6b7280;">
                                Letzte Sammlung: ${lastCollection}
                            </div>
                        </div>
                        <div style="text-align: right; font-size: 11px;">
                            <div style="font-weight: 600; color: #374151;">${collectedCount}</div>
                            <div style="color: #9ca3af;">Einträge</div>
                        </div>
                    </div>
                `;
            });
        }

        html += '</div>';
        statusContent.innerHTML = html;

        // Show live indicator if connected and collecting data
        const hasActiveCollectors = data.collectors && data.collectors.some(c => c.running);
        const isConnected = data.multi_platform ? 
            Object.values(data.platforms || {}).some(p => p.connected) : 
            data.connected;
            
        if (liveIndicator && isConnected && hasActiveCollectors) {
            liveIndicator.style.display = 'inline-block';
        } else if (liveIndicator) {
            liveIndicator.style.display = 'none';
        }

    } catch (error) {
        console.error('Error updating connection status:', error);
        const statusContent = document.getElementById('connection-status-content');
        if (statusContent) {
            statusContent.innerHTML = '<div style="color: #ef4444;">Fehler beim Laden des Status</div>';
        }
    }
}

function showPlatformConfig(platform) {
    const homeyConfig = document.getElementById('homey-config');
    const haConfig = document.getElementById('ha-config');
    
    if (platform === 'homey') {
        homeyConfig.style.display = 'block';
        haConfig.style.display = 'none';
    } else {
        homeyConfig.style.display = 'none';
        haConfig.style.display = 'block';
    }
}

async function loadConnectionConfig() {
    try {
        const data = await fetchJSON('/api/config');
        
        // Check if multi-platform is enabled
        const isMultiPlatform = data.platforms?.enable_multi_platform || false;
        const multiPlatformCheckbox = document.getElementById('enable-multi-platform');
        
        if (multiPlatformCheckbox) {
            multiPlatformCheckbox.checked = isMultiPlatform;
            
            if (isMultiPlatform) {
                // Multi-Platform Mode
                document.getElementById('single-platform-select').style.display = 'none';
                document.getElementById('primary-platform-select').style.display = 'block';
                document.getElementById('homey-config').style.display = 'block';
                document.getElementById('ha-config').style.display = 'block';
                
                // Set primary platform
                const primaryPlatform = data.platforms?.primary || 'homey';
                document.getElementById('primary-platform').value = primaryPlatform;
            } else {
                // Single-Platform Mode
                document.getElementById('single-platform-select').style.display = 'block';
                document.getElementById('primary-platform-select').style.display = 'none';
                
                const platformSelect = document.getElementById('platform-select');
                const platformType = data.platform_type || 'homey';
                platformSelect.value = platformType;
                showPlatformConfig(platformType);
            }
        }

        // Load Homey config
        if (data.homey) {
            const homeyUrl = data.homey.url || '';
            const homeyToken = data.homey.token || '';
            
            // Detect if local or cloud
            if (homeyUrl.includes('api.athom.com')) {
                document.querySelector('input[name="homey-type"][value="cloud"]').checked = true;
                document.getElementById('homey-local-config').style.display = 'none';
                document.getElementById('homey-cloud-config').style.display = 'block';
                
                // Extract Homey ID from URL if present
                const match = homeyUrl.match(/delegation\/token\/([^\/]+)/);
                if (match) {
                    document.getElementById('homey-cloud-id').value = match[1];
                }
            } else {
                document.querySelector('input[name="homey-type"][value="local"]').checked = true;
                document.getElementById('homey-local-config').style.display = 'block';
                document.getElementById('homey-cloud-config').style.display = 'none';
                document.getElementById('homey-local-url').value = homeyUrl;
            }
            
            document.getElementById('homey-token').value = homeyToken;
        }

        // Load Home Assistant config
        if (data.homeassistant) {
            document.getElementById('ha-url').value = data.homeassistant.url || '';
            document.getElementById('ha-token').value = data.homeassistant.token || '';
        }

        // Load Weather API config
        if (data.platforms && data.platforms.weather) {
            document.getElementById('weather-api-enabled').checked = data.platforms.weather.enabled || false;
            document.getElementById('weather-api-key').value = data.platforms.weather.api_key || '';
            document.getElementById('weather-location').value = data.platforms.weather.location || '';
        }

    } catch (error) {
        console.error('Error loading connection config:', error);
    }
}

async function testHomeyConnection() {
    const resultEl = document.getElementById('homey-test-result');
    const btn = document.getElementById('test-homey-connection');
    
    btn.disabled = true;
    resultEl.innerHTML = '<span style="color: #3b82f6;">Teste Verbindung...</span>';
    
    try {
        const isLocal = document.querySelector('input[name="homey-type"]:checked').value === 'local';
        let url, token;
        
        if (isLocal) {
            url = document.getElementById('homey-local-url').value;
        } else {
            const homeyId = document.getElementById('homey-cloud-id').value;
            url = `https://api.athom.com/delegation/token/${homeyId}`;
        }
        
        token = document.getElementById('homey-token').value;
        
        if (!url || !token) {
            resultEl.innerHTML = '<span style="color: #ef4444;">[FEHLER] Bitte fülle alle Felder aus</span>';
            btn.disabled = false;
            return;
        }

        const response = await fetch('/api/test-connection', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                platform: 'homey',
                url: url,
                token: token
            })
        });

        const data = await response.json();
        
        if (data.success) {
            resultEl.innerHTML = `<span style="color: #10b981;">[OK] Verbindung erfolgreich! ${data.devices || 0} Geräte gefunden.</span>`;
        } else {
            resultEl.innerHTML = `<span style="color: #ef4444;">[FEHLER] Verbindung fehlgeschlagen: ${data.error}</span>`;
        }
    } catch (error) {
        resultEl.innerHTML = `<span style="color: #ef4444;">[FEHLER] ${error.message}</span>`;
    } finally {
        btn.disabled = false;
    }
}

async function testHAConnection() {
    const resultEl = document.getElementById('ha-test-result');
    const btn = document.getElementById('test-ha-connection');
    
    btn.disabled = true;
    resultEl.innerHTML = '<span style="color: #3b82f6;">Teste Verbindung...</span>';
    
    try {
        const url = document.getElementById('ha-url').value;
        const token = document.getElementById('ha-token').value;
        
        if (!url || !token) {
            resultEl.innerHTML = '<span style="color: #ef4444;">[FEHLER] Bitte fülle alle Felder aus</span>';
            btn.disabled = false;
            return;
        }

        const response = await fetch('/api/test-connection', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                platform: 'homeassistant',
                url: url,
                token: token
            })
        });

        const data = await response.json();
        
        if (data.success) {
            resultEl.innerHTML = `<span style="color: #10b981;">[OK] Verbindung erfolgreich! ${data.devices || 0} Geräte gefunden.</span>`;
        } else {
            resultEl.innerHTML = `<span style="color: #ef4444;">[FEHLER] Verbindung fehlgeschlagen: ${data.error}</span>`;
        }
    } catch (error) {
        resultEl.innerHTML = `<span style="color: #ef4444;">[FEHLER] ${error.message}</span>`;
    } finally {
        btn.disabled = false;
    }
}

async function saveConnectionConfig() {
    const resultEl = document.getElementById('connection-save-result');
    const btn = document.getElementById('save-connection-config');
    
    btn.disabled = true;
    resultEl.textContent = 'Speichere...';
    resultEl.className = 'action-result';
    resultEl.style.display = 'block';
    
    try {
        const isMultiPlatform = document.getElementById('enable-multi-platform').checked;
        const config = { enable_multi_platform: isMultiPlatform };
        
        if (isMultiPlatform) {
            // Multi-Platform Mode: Beide Konfigurationen senden
            config.primary_platform = document.getElementById('primary-platform').value;
            
            // Homey Config
            const isLocal = document.querySelector('input[name="homey-type"]:checked').value === 'local';
            let homeyUrl;
            
            if (isLocal) {
                homeyUrl = document.getElementById('homey-local-url').value;
            } else {
                const homeyId = document.getElementById('homey-cloud-id').value;
                homeyUrl = `https://api.athom.com/delegation/token/${homeyId}`;
            }
            
            config.homey = {
                url: homeyUrl,
                token: document.getElementById('homey-token').value
            };
            
            // Home Assistant Config
            config.homeassistant = {
                url: document.getElementById('ha-url').value,
                token: document.getElementById('ha-token').value
            };
        } else {
            // Single-Platform Mode: Nur eine Plattform
            const platform = document.getElementById('platform-select').value;
            config.platform_type = platform;
            
            if (platform === 'homey') {
                const isLocal = document.querySelector('input[name="homey-type"]:checked').value === 'local';
                let url;
                
                if (isLocal) {
                    url = document.getElementById('homey-local-url').value;
                } else {
                    const homeyId = document.getElementById('homey-cloud-id').value;
                    url = `https://api.athom.com/delegation/token/${homeyId}`;
                }
                
                config.homey = {
                    url: url,
                    token: document.getElementById('homey-token').value
                };
            } else {
                config.homeassistant = {
                    url: document.getElementById('ha-url').value,
                    token: document.getElementById('ha-token').value
                };
            }
        }

        // Weather API Config
        config.weather = {
            enabled: document.getElementById('weather-api-enabled').checked,
            api_key: document.getElementById('weather-api-key').value,
            location: document.getElementById('weather-location').value
        };

        const response = await fetch('/api/config/connection', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(config)
        });

        const data = await response.json();
        
        
        if (data.success) {
            resultEl.textContent = '[OK] Konfiguration gespeichert! Server wird neu gestartet...';
            resultEl.className = 'action-result success';
            
            // Warte kurz und lade dann die Seite neu
            setTimeout(() => {
                window.location.reload();
            }, 2000);
        } else {
            resultEl.textContent = `[FEHLER] ${data.error}`;
            resultEl.className = 'action-result error';
        }
    } catch (error) {
        resultEl.textContent = `[FEHLER] Beim Speichern: ${error.message}`;
        resultEl.className = 'action-result error';
    } finally {
        btn.disabled = false;
    }
}

// === DATA COLLECTION CONFIG ===

async function loadDataCollectionConfig() {
    try {
        const data = await fetchJSON('/api/config');
        
        // Lade collect_types wenn vorhanden
        if (data.data_collection && data.data_collection.collect_types) {
            const types = data.data_collection.collect_types;
            
            document.getElementById('collect-lighting').checked = types.lighting_events !== false;
            document.getElementById('collect-temperature').checked = types.temperature_data !== false;
            document.getElementById('collect-heating').checked = types.heating_observations !== false;
            document.getElementById('collect-windows').checked = types.window_states !== false;
            document.getElementById('collect-bathroom').checked = types.bathroom_data !== false;
            document.getElementById('collect-sensors').checked = types.sensor_data !== false;
            document.getElementById('collect-weather').checked = types.weather_data !== false;
        }
        
        // Lade platform_sources wenn Multi-Platform aktiv
        if (data.data_collection && data.data_collection.platform_sources) {
            const sources = data.data_collection.platform_sources;
            
            // Lighting
            if (sources.lighting_events) {
                document.getElementById('lighting-source-homey').checked = sources.lighting_events.homey !== false;
                document.getElementById('lighting-source-ha').checked = sources.lighting_events.homeassistant !== false;
            }
            
            // Temperature
            if (sources.temperature_data) {
                document.getElementById('temperature-source-homey').checked = sources.temperature_data.homey !== false;
                document.getElementById('temperature-source-ha').checked = sources.temperature_data.homeassistant !== false;
            }
            
            // Heating
            if (sources.heating_observations) {
                document.getElementById('heating-source-homey').checked = sources.heating_observations.homey !== false;
                document.getElementById('heating-source-ha').checked = sources.heating_observations.homeassistant !== false;
            }
            
            // Windows
            if (sources.window_states) {
                document.getElementById('windows-source-homey').checked = sources.window_states.homey !== false;
                document.getElementById('windows-source-ha').checked = sources.window_states.homeassistant !== false;
            }
            
            // Bathroom
            if (sources.bathroom_data) {
                document.getElementById('bathroom-source-homey').checked = sources.bathroom_data.homey !== false;
                document.getElementById('bathroom-source-ha').checked = sources.bathroom_data.homeassistant !== false;
            }
        }
    } catch (error) {
        console.error('Error loading data collection config:', error);
    }
}

async function saveDataCollectionConfig() {
    const resultEl = document.getElementById('data-collection-save-result');
    const btn = document.getElementById('save-data-collection-config');
    
    btn.disabled = true;
    resultEl.textContent = 'Speichere...';
    resultEl.className = 'action-result';
    resultEl.style.display = 'block';
    
    try {
        const isMultiPlatform = document.getElementById('enable-multi-platform').checked;
        
        const config = {
            collect_types: {
                lighting_events: document.getElementById('collect-lighting').checked,
                temperature_data: document.getElementById('collect-temperature').checked,
                heating_observations: document.getElementById('collect-heating').checked,
                window_states: document.getElementById('collect-windows').checked,
                bathroom_data: document.getElementById('collect-bathroom').checked,
                sensor_data: document.getElementById('collect-sensors').checked,
                weather_data: document.getElementById('collect-weather').checked
            }
        };
        
        // Platform sources nur bei Multi-Platform
        if (isMultiPlatform) {
            config.platform_sources = {
                lighting_events: {
                    homey: document.getElementById('lighting-source-homey').checked,
                    homeassistant: document.getElementById('lighting-source-ha').checked
                },
                temperature_data: {
                    homey: document.getElementById('temperature-source-homey').checked,
                    homeassistant: document.getElementById('temperature-source-ha').checked
                },
                heating_observations: {
                    homey: document.getElementById('heating-source-homey').checked,
                    homeassistant: document.getElementById('heating-source-ha').checked
                },
                window_states: {
                    homey: document.getElementById('windows-source-homey').checked,
                    homeassistant: document.getElementById('windows-source-ha').checked
                },
                bathroom_data: {
                    homey: document.getElementById('bathroom-source-homey').checked,
                    homeassistant: document.getElementById('bathroom-source-ha').checked
                }
            };
        }

        const response = await fetch('/api/config/data-collection', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(config)
        });

        const data = await response.json();
        
        if (data.success) {
            resultEl.textContent = '[OK] Datensammlungs-Konfiguration gespeichert!';
            resultEl.className = 'action-result success';
            
            setTimeout(() => {
                resultEl.style.display = 'none';
            }, 3000);
        } else {
            resultEl.textContent = `[FEHLER] ${data.error}`;
            resultEl.className = 'action-result error';
        }
    } catch (error) {
        resultEl.textContent = `[FEHLER] Beim Speichern: ${error.message}`;
        resultEl.className = 'action-result error';
    } finally {
        btn.disabled = false;
    }
}

