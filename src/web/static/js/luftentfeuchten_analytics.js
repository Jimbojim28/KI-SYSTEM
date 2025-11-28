// Bathroom Analytics Dashboard JavaScript

let analyticsData = null;
let eventsData = null;
let humidityTimeseriesData = null;

// Helper functions
async function fetchJSON(url) {
    const response = await fetch(url);
    if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
    }
    return await response.json();
}

async function postJSON(url, data) {
    const response = await fetch(url, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify(data)
    });
    if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
    }
    return await response.json();
}

// Lade alle Daten
async function loadAllData() {
    try {
        // Lade Analytics parallel
        const hours = parseInt(document.getElementById('hours-selector')?.value || 6);
        const [analytics, events, humidityResponse] = await Promise.all([
            fetchJSON('/api/luftentfeuchten/analytics?days=30'),
            fetchJSON('/api/luftentfeuchten/events?days=30&limit=50'),
            fetch(`/api/luftentfeuchten/sensor-timeseries?hours=${hours}`)
        ]);

        analyticsData = analytics;
        eventsData = events;

        // Prüfe Humidity-Response
        if (humidityResponse.ok) {
            humidityTimeseriesData = await humidityResponse.json();
        } else {
            const errorData = await humidityResponse.json();
            console.error('Error loading humidity data:', errorData);
            humidityTimeseriesData = {
                error: errorData.error || 'Unbekannter Fehler',
                data: []
            };
        }

        renderDashboard();
    } catch (error) {
        console.error('Error loading analytics data:', error);
        humidityTimeseriesData = {
            error: error.message,
            data: []
        };
        renderDashboard();
    }
}

function renderDashboard() {
    if (!analyticsData || !analyticsData.available) {
        showNoData();
        return;
    }

    renderHumidityTimeseries();
    renderLearningStatus();
    renderStatistics();
    renderPrediction();
    renderTrendChart();
    renderPeakHours();
    renderWeekdayDistribution();
    renderEventHistory();

    // Lade Wochenübersicht (separat, da es einen eigenen API-Call macht)
    loadWeeklyOverview();
}

function renderLearningStatus() {
    const container = document.getElementById('learning-status');

    if (!analyticsData.learning_enabled) {
        container.innerHTML = `
            <div class="learning-warning">
                <strong>⚠️ Lernsystem deaktiviert</strong>
                <p>Das selbstlernende System ist aktuell deaktiviert.</p>
            </div>
        `;
        return;
    }

    const patterns = analyticsData.patterns;

    if (!patterns.sufficient_data) {
        container.innerHTML = `
            <div class="learning-warning">
                <strong>📊 Sammle Daten...</strong>
                <p>${patterns.message}</p>
                <p style="margin-top: 10px;">Events: <strong>${patterns.events_count}</strong> / 3 benötigt</p>
            </div>
        `;
        return;
    }

    container.innerHTML = `
        <div class="learning-info">
            <strong>✅ Lernsystem aktiv</strong>
            <p>Basierend auf <strong>${patterns.events_count} Events</strong> der letzten ${patterns.period_days} Tage</p>
            <p style="margin-top: 10px; color: #059669;">
                Das System lernt kontinuierlich und optimiert Schwellwerte automatisch.
            </p>
        </div>
    `;
}

function renderStatistics() {
    const stats = analyticsData.statistics.event_stats;

    document.getElementById('stat-events').textContent = stats.event_count || 0;

    if (stats.avg_duration !== null && stats.avg_duration !== undefined) {
        document.getElementById('stat-avg-duration').textContent =
            `${stats.avg_duration.toFixed(1)} Min`;
    } else {
        document.getElementById('stat-avg-duration').textContent = '-';
    }

    if (stats.avg_peak_humidity !== null && stats.avg_peak_humidity !== undefined) {
        document.getElementById('stat-avg-humidity').textContent =
            `${stats.avg_peak_humidity.toFixed(1)}%`;
    } else {
        document.getElementById('stat-avg-humidity').textContent = '-';
    }

    if (stats.avg_dehumidifier_runtime !== null && stats.avg_dehumidifier_runtime !== undefined) {
        document.getElementById('stat-dehumidifier').textContent =
            `${stats.avg_dehumidifier_runtime.toFixed(1)} Min`;
    } else {
        document.getElementById('stat-dehumidifier').textContent = '-';
    }
}

function renderPrediction() {
    const prediction = analyticsData.prediction;

    if (!prediction || !prediction.most_likely) {
        document.getElementById('prediction-card').style.display = 'none';
        return;
    }

    const most_likely = prediction.most_likely;
    const predTime = new Date(most_likely.time);

    const content = document.getElementById('prediction-content');
    content.innerHTML = `
        <div class="prediction-box">
            <div style="color: #6b7280; font-size: 0.9em;">Nächste wahrscheinliche Duschzeit:</div>
            <div class="prediction-time">${predTime.toLocaleString('de-DE', {
                weekday: 'short',
                day: '2-digit',
                month: '2-digit',
                hour: '2-digit',
                minute: '2-digit'
            })}</div>
            <div class="prediction-probability">
                Wahrscheinlichkeit: ${(most_likely.probability * 100).toFixed(0)}%
                (in ca. ${most_likely.hours_until.toFixed(1)} Stunden)
            </div>
        </div>
    `;

    document.getElementById('prediction-card').style.display = 'block';
}

function renderTrendChart() {
    if (!eventsData || !eventsData.events || eventsData.events.length < 2) {
        document.getElementById('trend-chart').innerHTML =
            '<p style="color: #6b7280;">Nicht genug Daten für Trend-Chart (mindestens 2 Events benötigt)</p>';
        return;
    }

    // Nimm die letzten 10 Events
    const events = eventsData.events.slice(0, 10).reverse();

    const canvas = document.getElementById('trend-canvas');
    const ctx = canvas.getContext('2d');

    // Setze Canvas-Größe
    canvas.width = canvas.parentElement.clientWidth;
    canvas.height = 300;

    const padding = 40;
    const chartWidth = canvas.width - 2 * padding;
    const chartHeight = canvas.height - 2 * padding;

    // Extrahiere Daten
    const peakValues = events.map(e => e.peak_humidity || 0);
    const avgValues = events.map(e => e.avg_humidity || 0);
    const labels = events.map((e, i) => `Event ${events.length - i}`);

    // Finde Min/Max für Skalierung
    const allValues = [...peakValues, ...avgValues];
    const maxValue = Math.max(...allValues);
    const minValue = Math.min(...allValues.filter(v => v > 0));
    const range = maxValue - minValue;
    const yMin = Math.max(0, minValue - range * 0.1);
    const yMax = maxValue + range * 0.1;

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

    // Zeichne Gitterlinien
    ctx.strokeStyle = '#f3f4f6';
    for (let i = 0; i <= 5; i++) {
        const y = padding + (chartHeight / 5) * i;
        ctx.beginPath();
        ctx.moveTo(padding, y);
        ctx.lineTo(canvas.width - padding, y);
        ctx.stroke();

        // Y-Achsen-Labels
        const value = yMax - (yMax - yMin) / 5 * i;
        ctx.fillStyle = '#6b7280';
        ctx.font = '12px Arial';
        ctx.textAlign = 'right';
        ctx.fillText(value.toFixed(0) + '%', padding - 10, y + 4);
    }

    // Hilfsfunktion für Y-Koordinate
    const getY = (value) => {
        return canvas.height - padding - ((value - yMin) / (yMax - yMin)) * chartHeight;
    };

    // Hilfsfunktion für X-Koordinate
    const getX = (index) => {
        return padding + (chartWidth / (events.length - 1)) * index;
    };

    // Zeichne Peak-Linie (Blau)
    ctx.strokeStyle = '#3b82f6';
    ctx.lineWidth = 2;
    ctx.beginPath();
    peakValues.forEach((value, i) => {
        const x = getX(i);
        const y = getY(value);
        if (i === 0) {
            ctx.moveTo(x, y);
        } else {
            ctx.lineTo(x, y);
        }
    });
    ctx.stroke();

    // Zeichne Average-Linie (Grün)
    ctx.strokeStyle = '#10b981';
    ctx.lineWidth = 2;
    ctx.setLineDash([5, 5]);
    ctx.beginPath();
    avgValues.forEach((value, i) => {
        const x = getX(i);
        const y = getY(value);
        if (i === 0) {
            ctx.moveTo(x, y);
        } else {
            ctx.lineTo(x, y);
        }
    });
    ctx.stroke();
    ctx.setLineDash([]);

    // Zeichne Datenpunkte
    peakValues.forEach((value, i) => {
        const x = getX(i);
        const y = getY(value);

        // Peak Punkt (Blau)
        ctx.fillStyle = '#3b82f6';
        ctx.beginPath();
        ctx.arc(x, y, 4, 0, 2 * Math.PI);
        ctx.fill();

        // Average Punkt (Grün)
        const avgY = getY(avgValues[i]);
        ctx.fillStyle = '#10b981';
        ctx.beginPath();
        ctx.arc(x, avgY, 4, 0, 2 * Math.PI);
        ctx.fill();
    });

    // Legende
    const legendX = padding + 20;
    const legendY = padding + 20;

    ctx.fillStyle = '#3b82f6';
    ctx.fillRect(legendX, legendY, 15, 3);
    ctx.fillStyle = '#1f2937';
    ctx.font = '12px Arial';
    ctx.textAlign = 'left';
    ctx.fillText('Peak Luftfeuchtigkeit', legendX + 20, legendY + 4);

    ctx.fillStyle = '#10b981';
    ctx.fillRect(legendX, legendY + 20, 15, 3);
    ctx.fillStyle = '#1f2937';
    ctx.fillText('Durchschnitt', legendX + 20, legendY + 24);
}

function renderPeakHours() {
    // Sichere Prüfung auf hourly_pattern
    if (!analyticsData.patterns.hourly_pattern || !analyticsData.patterns.hourly_pattern.peak_hours) {
        document.getElementById('peak-hours-chart').innerHTML =
            '<p style="color: #6b7280;">Nicht genug Daten für Analyse</p>';
        return;
    }

    const peakHours = analyticsData.patterns.hourly_pattern.peak_hours;

    if (peakHours.length === 0) {
        document.getElementById('peak-hours-chart').innerHTML =
            '<p style="color: #6b7280;">Nicht genug Daten für Analyse</p>';
        return;
    }

    // Finde Maximum für Skalierung
    const maxCount = Math.max(...peakHours.map(h => h.count));

    const html = `
        <div class="bar-chart">
            ${peakHours.map(hour => `
                <div class="bar-item">
                    <div class="bar-label">${hour.hour}:00 Uhr</div>
                    <div class="bar-container">
                        <div class="bar-fill" style="width: ${(hour.count / maxCount * 100)}%">
                            ${hour.count} (${hour.percentage}%)
                        </div>
                    </div>
                </div>
            `).join('')}
        </div>
    `;

    document.getElementById('peak-hours-chart').innerHTML = html;
}

function renderWeekdayDistribution() {
    // Sichere Prüfung auf weekly_pattern
    if (!analyticsData.patterns.weekly_pattern || !analyticsData.patterns.weekly_pattern.distribution) {
        document.getElementById('weekday-chart').innerHTML =
            '<p style="color: #6b7280;">Nicht genug Daten für Analyse</p>';
        return;
    }

    const weekdayDist = analyticsData.patterns.weekly_pattern.distribution;

    if (weekdayDist.length === 0) {
        document.getElementById('weekday-chart').innerHTML =
            '<p style="color: #6b7280;">Nicht genug Daten für Analyse</p>';
        return;
    }

    // Finde Maximum für Skalierung
    const maxCount = Math.max(...weekdayDist.map(d => d.count));

    const html = `
        <div class="bar-chart">
            ${weekdayDist.map(day => `
                <div class="bar-item">
                    <div class="bar-label">${day.name}</div>
                    <div class="bar-container">
                        <div class="bar-fill" style="width: ${maxCount > 0 ? (day.count / maxCount * 100) : 0}%">
                            ${day.count > 0 ? `${day.count} (${day.percentage}%)` : '0'}
                        </div>
                    </div>
                </div>
            `).join('')}
        </div>
    `;

    document.getElementById('weekday-chart').innerHTML = html;
}

function renderEventHistory() {
    if (!eventsData || !eventsData.events || eventsData.events.length === 0) {
        document.querySelector('#events-table tbody').innerHTML = `
            <tr>
                <td colspan="4" style="text-align: center; color: #6b7280;">
                    Keine Events gefunden
                </td>
            </tr>
        `;
        return;
    }

    const tbody = document.querySelector('#events-table tbody');
    tbody.innerHTML = eventsData.events.map(event => {
        const startTime = new Date(event.start_time);
        return `
            <tr>
                <td>${startTime.toLocaleString('de-DE')}</td>
                <td>${event.duration_minutes ? event.duration_minutes.toFixed(1) + ' Min' : '-'}</td>
                <td>${event.peak_humidity ? event.peak_humidity.toFixed(1) + '%' : '-'}</td>
                <td>${event.dehumidifier_runtime_minutes ? event.dehumidifier_runtime_minutes.toFixed(1) + ' Min' : '-'}</td>
            </tr>
        `;
    }).join('');
}

function showNoData() {
    document.getElementById('learning-status').innerHTML = `
        <div class="learning-warning">
            <strong>⚠️ Keine Daten verfügbar</strong>
            <p>Das Analytics-System konnte nicht geladen werden.</p>
        </div>
    `;
}

// Optimierungs-Funktion
async function optimizeNow() {
    const btn = document.getElementById('optimize-now');
    const resultSpan = document.getElementById('optimize-result');

    btn.disabled = true;
    btn.textContent = 'Optimiere...';
    resultSpan.textContent = '';

    try {
        const result = await postJSON('/api/luftentfeuchten/optimize', {
            days_back: 30,
            min_confidence: 0.7
        });

        if (result.success) {
            resultSpan.textContent = `✅ Erfolgreich optimiert! High: ${result.old_values.humidity_high}% → ${result.new_values.humidity_high}%, Low: ${result.old_values.humidity_low}% → ${result.new_values.humidity_low}%`;
            resultSpan.style.color = '#10b981';

            // Reload nach 2 Sekunden
            setTimeout(() => {
                location.reload();
            }, 2000);
        } else {
            resultSpan.textContent = `⚠️ ${result.reason || 'Optimierung fehlgeschlagen'}`;
            resultSpan.style.color = '#f59e0b';
        }
    } catch (error) {
        console.error('Error optimizing:', error);
        resultSpan.textContent = '❌ Fehler bei der Optimierung';
        resultSpan.style.color = '#ef4444';
    } finally {
        btn.disabled = false;
        btn.textContent = 'Jetzt optimieren';
    }
}

// Render Live Humidity Timeseries
function renderHumidityTimeseries() {
    const chartContainer = document.getElementById('humidity-chart');

    // Prüfe auf Fehler
    if (humidityTimeseriesData && humidityTimeseriesData.error) {
        let errorMessage = '';
        let helpText = '';

        if (humidityTimeseriesData.error.includes('No configuration found')) {
            errorMessage = '⚙️ Badezimmer-Automatisierung nicht konfiguriert';
            helpText = 'Bitte gehen Sie zu <a href="/luftentfeuchten" style="color: #3b82f6; text-decoration: underline;">Badezimmer Automatisierung</a> und konfigurieren Sie die Sensoren.';
        } else if (humidityTimeseriesData.error.includes('Humidity sensor not configured')) {
            errorMessage = '💧 Luftfeuchtigkeits-Sensor nicht konfiguriert';
            helpText = 'Bitte gehen Sie zu <a href="/luftentfeuchten" style="color: #3b82f6; text-decoration: underline;">Badezimmer Automatisierung</a> und wählen Sie einen Luftfeuchtigkeits-Sensor aus.';
        } else {
            errorMessage = '❌ Fehler beim Laden der Sensor-Daten';
            helpText = `Fehlerdetails: ${humidityTimeseriesData.error}`;
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
    if (!humidityTimeseriesData || !humidityTimeseriesData.data || humidityTimeseriesData.data.length === 0) {
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

    const canvas = document.getElementById('humidity-canvas');
    if (!canvas) {
        console.error('Canvas element not found');
        return;
    }
    const ctx = canvas.getContext('2d');

    // Setze Canvas-Größe
    canvas.width = canvas.parentElement.clientWidth;
    canvas.height = 300;

    const padding = 50;
    const chartWidth = canvas.width - 2 * padding;
    const chartHeight = canvas.height - 2 * padding;

    const data = humidityTimeseriesData.data;

    // Extrahiere Werte
    const values = data.map(d => parseFloat(d.value));
    const timestamps = data.map(d => new Date(d.timestamp));

    // Finde Min/Max
    const maxValue = Math.max(...values);
    const minValue = Math.min(...values);
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

    // Zeichne Linie
    ctx.strokeStyle = '#3b82f6';
    ctx.lineWidth = 2;
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

    // Zeichne Datenpunkte
    values.forEach((value, i) => {
        const x = getX(i);
        const y = getY(value);

        ctx.fillStyle = '#3b82f6';
        ctx.beginPath();
        ctx.arc(x, y, 3, 0, 2 * Math.PI);
        ctx.fill();
    });

    // Legende
    ctx.fillStyle = '#1f2937';
    ctx.font = '14px Arial';
    ctx.textAlign = 'left';
    ctx.fillText(`Aktuelle Luftfeuchtigkeit: ${values[values.length - 1].toFixed(1)}%`, padding + 10, padding + 20);
}

// === CHART MARKIER-FUNKTIONALITÄT ===

let isMarkingMode = false;
let isSelecting = false;
let selectionStart = null;
let selectionEnd = null;
let selectedData = null;

function toggleMarkingMode() {
    isMarkingMode = !isMarkingMode;
    const btn = document.getElementById('toggle-marking-mode');
    const canvas = document.getElementById('humidity-canvas');
    const instructionNormal = document.getElementById('marking-instruction');
    const instructionActive = document.getElementById('marking-active-instruction');

    if (!canvas) {
        console.error('Canvas element not found in toggleMarkingMode');
        return;
    }

    if (isMarkingMode) {
        btn.textContent = '❌ Abbrechen';
        btn.classList.remove('btn-primary');
        btn.classList.add('btn-danger');
        canvas.style.cursor = 'crosshair';
        instructionNormal.style.display = 'none';
        instructionActive.style.display = 'inline';
    } else {
        btn.textContent = '✏️ Markier-Modus';
        btn.classList.remove('btn-danger');
        btn.classList.add('btn-primary');
        canvas.style.cursor = 'default';
        instructionNormal.style.display = 'inline';
        instructionActive.style.display = 'none';
        clearSelection();
    }
}

function handleCanvasMouseDown(e) {
    if (!isMarkingMode) return;

    const canvas = document.getElementById('humidity-canvas');
    const rect = canvas.getBoundingClientRect();
    const x = e.clientX - rect.left;

    isSelecting = true;
    selectionStart = x;
    selectionEnd = x;

    updateSelectionVisual();
}

function handleCanvasMouseMove(e) {
    if (!isMarkingMode || !isSelecting) return;

    const canvas = document.getElementById('humidity-canvas');
    const rect = canvas.getBoundingClientRect();
    const x = e.clientX - rect.left;

    selectionEnd = x;
    updateSelectionVisual();
}

function handleCanvasMouseUp(e) {
    if (!isMarkingMode || !isSelecting) return;

    isSelecting = false;

    // Berechne Start- und End-Zeiten basierend auf der Auswahl
    const canvas = document.getElementById('humidity-canvas');
    const rect = canvas.getBoundingClientRect();

    const startX = Math.min(selectionStart, selectionEnd);
    const endX = Math.max(selectionStart, selectionEnd);

    // Zu klein? Abbrechen
    if (Math.abs(endX - startX) < 20) {
        clearSelection();
        return;
    }

    // Berechne Zeiten aus X-Koordinaten
    calculateTimesFromSelection(startX, endX, rect.width);
}

function updateSelectionVisual() {
    const overlay = document.getElementById('selection-overlay');
    const box = document.getElementById('selection-box');

    if (!isSelecting) {
        overlay.style.display = 'none';
        return;
    }

    overlay.style.display = 'block';

    const startX = Math.min(selectionStart, selectionEnd);
    const width = Math.abs(selectionEnd - selectionStart);

    box.style.left = startX + 'px';
    box.style.top = '0';
    box.style.width = width + 'px';
    box.style.height = '100%';
}

function calculateTimesFromSelection(startX, endX, canvasWidth) {
    if (!humidityTimeseriesData || !humidityTimeseriesData.data) return;

    const data = humidityTimeseriesData.data;
    if (data.length === 0) return;

    // Konvertiere X-Position zu Daten-Index
    const startIndex = Math.floor((startX / canvasWidth) * data.length);
    const endIndex = Math.floor((endX / canvasWidth) * data.length);

    const startTime = new Date(data[startIndex].timestamp);
    const endTime = new Date(data[endIndex].timestamp);

    // Finde maximale Luftfeuchtigkeit im Bereich
    let maxHumidity = 0;
    for (let i = startIndex; i <= endIndex; i++) {
        if (data[i].humidity > maxHumidity) {
            maxHumidity = data[i].humidity;
        }
    }

    selectedData = {
        startTime,
        endTime,
        peakHumidity: maxHumidity
    };

    showSelectionConfirm();
}

function showSelectionConfirm() {
    const confirmBox = document.getElementById('selection-confirm');
    const overlay = document.getElementById('selection-overlay');

    // Zeige Confirmation Box
    confirmBox.style.display = 'block';
    overlay.style.display = 'block';

    // Fülle Daten
    const duration = (selectedData.endTime - selectedData.startTime) / 1000 / 60;

    document.getElementById('selection-start-time').textContent = formatTime(selectedData.startTime);
    document.getElementById('selection-end-time').textContent = formatTime(selectedData.endTime);
    document.getElementById('selection-duration').textContent = Math.round(duration) + ' Min';
    document.getElementById('selection-peak-humidity').textContent = selectedData.peakHumidity.toFixed(1) + '%';
}

function formatTime(date) {
    const hours = String(date.getHours()).padStart(2, '0');
    const minutes = String(date.getMinutes()).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');
    const month = String(date.getMonth() + 1).padStart(2, '0');
    return `${day}.${month}. ${hours}:${minutes}`;
}

function clearSelection() {
    selectionStart = null;
    selectionEnd = null;
    selectedData = null;
    isSelecting = false;

    document.getElementById('selection-overlay').style.display = 'none';
    document.getElementById('selection-confirm').style.display = 'none';
    document.getElementById('selection-result').style.display = 'none';
}

async function confirmSelection() {
    if (!selectedData) return;

    const resultEl = document.getElementById('selection-result');
    const confirmBtn = document.getElementById('confirm-selection');

    try {
        confirmBtn.disabled = true;
        resultEl.innerHTML = '<div style="padding: 10px; background: #dbeafe; border-radius: 4px; color: #1e40af;">📤 Speichere Event...</div>';
        resultEl.style.display = 'block';

        const response = await fetch('/api/luftentfeuchten/manual-event', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                start_time: selectedData.startTime.toISOString(),
                end_time: selectedData.endTime.toISOString(),
                peak_humidity: selectedData.peakHumidity,
                notes: 'Manuell im Diagramm markiert'
            })
        });

        const data = await response.json();

        if (data.success) {
            resultEl.innerHTML = `<div style="padding: 10px; background: #d1fae5; border-radius: 4px; color: #065f46;">✅ ${data.message}</div>`;

            // Reload nach 1 Sekunde
            setTimeout(async () => {
                clearSelection();
                toggleMarkingMode();
                await loadAllData();
            }, 1500);
        } else {
            throw new Error(data.error || 'Unbekannter Fehler');
        }

    } catch (error) {
        console.error('Error saving event:', error);
        resultEl.innerHTML = `<div style="padding: 10px; background: #fee2e2; border-radius: 4px; color: #991b1b;">❌ Fehler: ${error.message}</div>`;
    } finally {
        confirmBtn.disabled = false;
    }
}

// === Wochenübersicht: Tatsächlich vs. Vorhergesagt ===

let weeklyOverviewData = null;

async function loadWeeklyOverview() {
    try {
        const response = await fetchJSON('/api/luftentfeuchten/weekly-overview');
        weeklyOverviewData = response;
        renderWeeklyOverview();
    } catch (error) {
        console.error('Error loading weekly overview:', error);
        document.getElementById('weekly-heatmap').innerHTML = `
            <div style="color: #ef4444; padding: 20px; text-align: center;">
                ⚠️ Fehler beim Laden der Wochenübersicht: ${error.message}
            </div>
        `;
    }
}

function renderWeeklyOverview() {
    if (!weeklyOverviewData || !weeklyOverviewData.success) {
        document.getElementById('weekly-heatmap').innerHTML = `
            <div style="color: #6b7280; padding: 20px; text-align: center;">
                Keine Daten verfügbar
            </div>
        `;
        return;
    }

    const { actual_events, predictions_by_day, actual_by_day_hour, accuracy_metrics, sufficient_data } = weeklyOverviewData;

    // Aktualisiere Genauigkeitsmetriken
    document.getElementById('day-accuracy').textContent =
        sufficient_data ? `${accuracy_metrics.overall_accuracy}%` : 'N/A';
    document.getElementById('hour-accuracy').textContent =
        sufficient_data ? `${accuracy_metrics.hour_accuracy}%` : 'N/A';
    document.getElementById('analyzed-events').textContent =
        accuracy_metrics.total_events || 0;

    // Erstelle Heatmap
    renderWeeklyHeatmap(actual_by_day_hour, predictions_by_day);
}

function renderWeeklyHeatmap(actualByDayHour, predictionsByDay) {
    const weekdayNames = ['Montag', 'Dienstag', 'Mittwoch', 'Donnerstag', 'Freitag', 'Samstag', 'Sonntag'];
    const container = document.getElementById('weekly-heatmap');

    // Erstelle Heatmap-HTML
    let html = '<div style="display: grid; grid-template-columns: auto repeat(24, 1fr); gap: 2px; font-size: 0.8em;">';

    // Header-Zeile (Stunden)
    html += '<div style="padding: 5px; font-weight: bold;"></div>'; // Ecke oben links

    for (let hour = 0; hour < 24; hour++) {
        html += `<div style="padding: 5px; text-align: center; font-weight: bold; font-size: 0.75em; color: #6b7280;">
            ${hour}
        </div>`;
    }

    // Zeilen für jeden Wochentag
    for (let day = 0; day < 7; day++) {
        // Wochentagsname
        html += `<div style="padding: 8px; font-weight: 600; color: #374151; display: flex; align-items: center;">
            ${weekdayNames[day]}
        </div>`;

        // Stunden-Zellen
        for (let hour = 0; hour < 24; hour++) {
            const key = `${day}_${hour}`;
            const hasActual = actualByDayHour[key] && actualByDayHour[key].length > 0;
            const prediction = predictionsByDay[day];

            // Prüfe ob diese Stunde vorhergesagt wurde
            let hasPrediction = false;
            if (prediction && prediction.predicted_times) {
                hasPrediction = prediction.predicted_times.some(p =>
                    Math.abs(p.hour - hour) <= 1  // ±1 Stunde Toleranz
                );
            }

            // Farbe basierend auf Status
            let bgColor = '#f3f4f6';  // Grau (leer)
            let borderColor = '#e5e7eb';
            let content = '';
            let tooltip = `${weekdayNames[day]} ${hour}:00`;

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
                tooltip = `${weekdayNames[day]} ${hour}:00\nTatsächlich: ${events.length} Event(s)\nØ Dauer: ${Math.round(events.reduce((sum, e) => sum + (e.duration || 0), 0) / events.length)} min`;
            } else if (hasPrediction) {
                // Nur vorhergesagt (Gelb/Orange)
                bgColor = '#fbbf24';
                borderColor = '#f59e0b';
                content = '?';
                const predTime = prediction.predicted_times.find(p => Math.abs(p.hour - hour) <= 1);
                tooltip = `${weekdayNames[day]} ${hour}:00\nVorhergesagt (${predTime ? predTime.probability : 0}% Wahrscheinlichkeit)`;
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
                        color: ${hasActual || hasPrediction ? 'white' : '#9ca3af'};
                        font-weight: bold;
                        cursor: pointer;
                        transition: transform 0.1s ease;
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

    // Info-Box falls nicht genug Daten
    if (!weeklyOverviewData.sufficient_data) {
        html += `
            <div style="margin-top: 15px; padding: 15px; background: #fef3c7; border-left: 4px solid #f59e0b; border-radius: 6px;">
                <strong>⚠️ Nicht genug Daten</strong>
                <p style="margin: 5px 0 0 0; font-size: 0.9em;">
                    Mindestens 3 Events benötigt für zuverlässige Vorhersagen.
                    Aktuell: ${weeklyOverviewData.events_count} Events.
                </p>
            </div>
        `;
    } else if (weeklyOverviewData.accuracy_metrics && weeklyOverviewData.accuracy_metrics.message) {
        // Zeige Genauigkeitsnachricht
        html += `
            <div style="margin-top: 15px; padding: 12px; background: #eff6ff; border-left: 4px solid #3b82f6; border-radius: 6px; font-size: 0.9em;">
                ${weeklyOverviewData.accuracy_metrics.message}
            </div>
        `;
    }

    container.innerHTML = html;
}

// Init
document.addEventListener('DOMContentLoaded', () => {
    loadAllData();

    // Event Listener für Optimierungs-Button
    document.getElementById('optimize-now').addEventListener('click', optimizeNow);

    // Event Listener für Hours-Selector
    const hoursSelector = document.getElementById('hours-selector');
    if (hoursSelector) {
        hoursSelector.addEventListener('change', loadAllData);
    }

    // Event Listener für Markier-Modus
    document.getElementById('toggle-marking-mode').addEventListener('click', toggleMarkingMode);

    // Canvas Event Listeners - nur wenn Canvas existiert
    const canvas = document.getElementById('humidity-canvas');
    if (canvas) {
        canvas.addEventListener('mousedown', handleCanvasMouseDown);
        canvas.addEventListener('mousemove', handleCanvasMouseMove);
        canvas.addEventListener('mouseup', handleCanvasMouseUp);
        canvas.addEventListener('mouseleave', () => {
            if (isSelecting) {
                handleCanvasMouseUp();
            }
        });
    }

    // Selection Confirm Event Listeners
    document.getElementById('confirm-selection').addEventListener('click', confirmSelection);
    document.getElementById('cancel-selection').addEventListener('click', () => {
        clearSelection();
        toggleMarkingMode();
    });
    document.getElementById('adjust-selection').addEventListener('click', clearSelection);

    // Auto-Refresh alle 30 Sekunden
    setInterval(loadAllData, 30000);
});
