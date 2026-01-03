/**
 * Badezimmer-Sensoren Konfiguration
 * Verwaltet zusätzliche Sensoren für verbesserte Duscherkennung
 */

(function() {
    'use strict';

    // Cache für verfügbare Sensoren
    let availableSensors = {
        humidity: [],
        temperature: []
    };

    /**
     * Initialisierung beim Laden der Seite
     */
    document.addEventListener('DOMContentLoaded', function() {
        initBathroomSensors();
    });

    /**
     * Hauptinitialisierung
     */
    function initBathroomSensors() {
        // Event Listeners
        document.getElementById('save-bathroom-sensors')?.addEventListener('click', saveBathroomSensors);
        document.getElementById('refresh-bathroom-stats')?.addEventListener('click', loadBathroomStats);
        
        // Rate Threshold Slider
        const rateThresholdSlider = document.getElementById('rate-threshold');
        const rateThresholdValue = document.getElementById('rate-threshold-value');
        
        if (rateThresholdSlider && rateThresholdValue) {
            rateThresholdSlider.addEventListener('input', function() {
                rateThresholdValue.textContent = this.value + ' %/min';
            });
        }

        // Lade Daten wenn Bathroom-Tab aktiv wird
        const bathroomTab = document.querySelector('[data-tab="bathroom"]');
        if (bathroomTab) {
            bathroomTab.addEventListener('click', function() {
                loadAvailableSensors();
                loadBathroomConfig();
                loadBathroomStats();
            });
        }
    }

    /**
     * Lade verfügbare Sensoren von Home Assistant
     */
    async function loadAvailableSensors() {
        try {
            const response = await fetch('/api/bathroom/sensors/available');
            if (!response.ok) {
                throw new Error('Failed to load sensors');
            }

            const data = await response.json();
            availableSensors = data;

            // Fülle Dropdown-Listen
            populateSensorDropdown('shower-humidity-sensor', data.humidity_sensors);
            populateSensorDropdown('shower-temperature-sensor', data.temperature_sensors);

        } catch (error) {
            console.error('Error loading sensors:', error);
            showResult('bathroom-save-result', 'Fehler beim Laden der Sensoren: ' + error.message, 'error');
        }
    }

    /**
     * Füllt ein Sensor-Dropdown mit verfügbaren Sensoren
     */
    function populateSensorDropdown(elementId, sensors) {
        const select = document.getElementById(elementId);
        if (!select) return;

        // Behalte die erste Option ("-- Sensor wählen --")
        const firstOption = select.options[0];
        select.innerHTML = '';
        select.appendChild(firstOption);

        // Füge Sensoren hinzu
        sensors.forEach(sensor => {
            const option = document.createElement('option');
            option.value = sensor.entity_id;
            option.textContent = `${sensor.name} (${sensor.state} ${sensor.unit || ''})`;
            select.appendChild(option);
        });
    }

    /**
     * Lade aktuelle Badezimmer-Konfiguration
     */
    async function loadBathroomConfig() {
        try {
            const response = await fetch('/api/bathroom/sensors/config');
            if (!response.ok) {
                throw new Error('Failed to load config');
            }

            const data = await response.json();
            const showerSensors = data.shower_sensors || {};

            // Setze Werte in Formular
            document.getElementById('shower-humidity-sensor').value = showerSensors.humidity_sensor || '';
            document.getElementById('shower-temperature-sensor').value = showerSensors.temperature_sensor || '';
            document.getElementById('enable-rate-detection').checked = showerSensors.enable_rate_detection !== false;
            
            const rateThreshold = showerSensors.rate_threshold || 2.0;
            document.getElementById('rate-threshold').value = rateThreshold;
            document.getElementById('rate-threshold-value').textContent = rateThreshold + ' %/min';

        } catch (error) {
            console.error('Error loading bathroom config:', error);
            showResult('bathroom-save-result', 'Fehler beim Laden der Konfiguration: ' + error.message, 'error');
        }
    }

    /**
     * Speichere Badezimmer-Sensoren Konfiguration
     */
    async function saveBathroomSensors() {
        const button = document.getElementById('save-bathroom-sensors');
        const originalText = button.textContent;
        button.disabled = true;
        button.textContent = '💾 Speichern...';

        try {
            const config = {
                shower_sensors: {
                    humidity_sensor: document.getElementById('shower-humidity-sensor').value,
                    temperature_sensor: document.getElementById('shower-temperature-sensor').value,
                    enable_rate_detection: document.getElementById('enable-rate-detection').checked,
                    rate_threshold: parseFloat(document.getElementById('rate-threshold').value)
                }
            };

            const response = await fetch('/api/bathroom/sensors/config', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(config)
            });

            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.error || 'Speichern fehlgeschlagen');
            }

            const result = await response.json();
            showResult('bathroom-save-result', result.message || 'Konfiguration erfolgreich gespeichert!', 'success');

        } catch (error) {
            console.error('Error saving bathroom config:', error);
            showResult('bathroom-save-result', 'Fehler beim Speichern: ' + error.message, 'error');
        } finally {
            button.disabled = false;
            button.textContent = originalText;
        }
    }

    /**
     * Lade Badezimmer-Statistiken
     */
    async function loadBathroomStats() {
        try {
            const response = await fetch('/api/bathroom/stats');
            if (!response.ok) {
                throw new Error('Failed to load stats');
            }

            const data = await response.json();

            // Update Statistik-Karten
            document.getElementById('bathroom-total-showers').textContent = data.total_showers || '0';
            document.getElementById('bathroom-avg-duration').textContent = 
                data.avg_duration_minutes ? data.avg_duration_minutes.toFixed(1) : '--';
            document.getElementById('bathroom-avg-increase').textContent = 
                data.avg_humidity_increase ? data.avg_humidity_increase.toFixed(1) : '--';

        } catch (error) {
            console.error('Error loading bathroom stats:', error);
            // Stille Fehler, keine Nutzer-Benachrichtigung
        }
    }

    /**
     * Zeige Ergebnis-Nachricht
     */
    function showResult(elementId, message, type = 'info') {
        const resultDiv = document.getElementById(elementId);
        if (!resultDiv) return;

        resultDiv.className = 'action-result ' + type;
        resultDiv.textContent = message;
        resultDiv.style.display = 'block';

        // Nach 10 Sekunden ausblenden
        setTimeout(() => {
            resultDiv.style.display = 'none';
        }, 10000);
    }

})();
