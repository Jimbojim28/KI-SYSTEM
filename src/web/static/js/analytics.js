// Analytics JavaScript mit Chart.js

let temperatureChart = null;
let humidityChart = null;

// Update Collector Status
async function updateCollectorStatus() {
    try {
        const data = await fetchJSON('/api/collector/status');
        
        // Null-Check: Bei Netzwerkfehler oder Tab-Wechsel kann data null sein
        if (!data) return;

        const statusEl = document.getElementById('collector-status');
        if (data.running) {
            statusEl.textContent = '✅ Aktiv';
            statusEl.style.color = 'var(--secondary-color)';
        } else {
            statusEl.textContent = '⏸️ Gestoppt';
            statusEl.style.color = 'var(--warning-color)';
        }

        document.getElementById('total-readings').textContent =
            (data.total_sensor_readings || 0).toLocaleString('de-DE');

        if (data.last_collection) {
            const lastDate = new Date(data.last_collection);
            document.getElementById('last-collection').textContent =
                lastDate.toLocaleString('de-DE');
        } else {
            document.getElementById('last-collection').textContent = 'Noch keine';
        }

        if (data.interval) {
            const minutes = Math.floor(data.interval / 60);
            document.getElementById('collection-interval').textContent =
                `${minutes} Minuten`;
        }

    } catch (error) {
        console.error('Error updating collector status:', error);
    }
}

// Lade und aktualisiere Temperatur-Daten
async function updateTemperatureChart(hoursBack = 168) {
    try {
        const response = await fetchJSON(`/api/analytics/temperature?hours=${hoursBack}`);
        
        // Null-Check: Bei Netzwerkfehler oder Tab-Wechsel kann response null sein
        if (!response || !response.data || response.data.length === 0) {
            showNoDataMessage();
            return;
        }

        hideNoDataMessage();

        const data = response.data;

        // Berechne Statistiken
        const values = data.map(d => d.avg_value);
        const avg = values.reduce((a, b) => a + b, 0) / values.length;
        const min = Math.min(...values);
        const max = Math.max(...values);

        document.getElementById('temp-avg').textContent = `${avg.toFixed(1)}°C`;
        document.getElementById('temp-min').textContent = `${min.toFixed(1)}°C`;
        document.getElementById('temp-max').textContent = `${max.toFixed(1)}°C`;

        // Erstelle Chart-Daten
        const labels = data.map(d => {
            const date = new Date(d.interval_time);
            return date.toLocaleDateString('de-DE', {
                month: 'short',
                day: 'numeric',
                hour: '2-digit'
            });
        });

        const chartData = {
            labels: labels,
            datasets: [
                {
                    label: 'Durchschnitt',
                    data: data.map(d => d.avg_value),
                    borderColor: 'rgba(75, 192, 192, 1)',
                    backgroundColor: 'rgba(75, 192, 192, 0.1)',
                    fill: true,
                    tension: 0.4
                },
                {
                    label: 'Min/Max Bereich',
                    data: data.map(d => [d.min_value, d.max_value]),
                    borderColor: 'rgba(255, 159, 64, 0.3)',
                    backgroundColor: 'rgba(255, 159, 64, 0.05)',
                    fill: true,
                    pointRadius: 0,
                    borderWidth: 1
                }
            ]
        };

        // Zerstöre alten Chart
        if (temperatureChart) {
            temperatureChart.destroy();
        }

        // Erstelle neuen Chart
        const ctx = document.getElementById('temperature-chart').getContext('2d');
        temperatureChart = new Chart(ctx, {
            type: 'line',
            data: chartData,
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        display: true,
                        position: 'bottom'
                    },
                    tooltip: {
                        mode: 'index',
                        intersect: false,
                        callbacks: {
                            label: function(context) {
                                let label = context.dataset.label || '';
                                if (label) {
                                    label += ': ';
                                }
                                if (Array.isArray(context.parsed.y)) {
                                    label += `${context.parsed.y[0].toFixed(1)}°C - ${context.parsed.y[1].toFixed(1)}°C`;
                                } else {
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
                        title: {
                            display: true,
                            text: 'Temperatur (°C)'
                        }
                    },
                    x: {
                        title: {
                            display: true,
                            text: 'Zeit'
                        }
                    }
                }
            }
        });

    } catch (error) {
        console.error('Error updating temperature chart:', error);
        showNoDataMessage();
    }
}

// Lade und aktualisiere Luftfeuchtigkeit-Daten
async function updateHumidityChart(hoursBack = 168) {
    try {
        const response = await fetchJSON(`/api/analytics/humidity?hours=${hoursBack}`);
        
        // Null-Check: Bei Netzwerkfehler oder Tab-Wechsel kann response null sein
        if (!response || !response.data || response.data.length === 0) {
            showNoDataMessage();
            return;
        }

        const data = response.data;

        // Berechne Statistiken
        const values = data.map(d => d.avg_value);
        const avg = values.reduce((a, b) => a + b, 0) / values.length;
        const min = Math.min(...values);
        const max = Math.max(...values);

        document.getElementById('humid-avg').textContent = `${avg.toFixed(1)}%`;
        document.getElementById('humid-min').textContent = `${min.toFixed(1)}%`;
        document.getElementById('humid-max').textContent = `${max.toFixed(1)}%`;

        // Erstelle Chart-Daten
        const labels = data.map(d => {
            const date = new Date(d.interval_time);
            return date.toLocaleDateString('de-DE', {
                month: 'short',
                day: 'numeric',
                hour: '2-digit'
            });
        });

        const chartData = {
            labels: labels,
            datasets: [{
                label: 'Luftfeuchtigkeit',
                data: data.map(d => d.avg_value),
                borderColor: 'rgba(54, 162, 235, 1)',
                backgroundColor: 'rgba(54, 162, 235, 0.1)',
                fill: true,
                tension: 0.4
            }]
        };

        // Zerstöre alten Chart
        if (humidityChart) {
            humidityChart.destroy();
        }

        // Erstelle neuen Chart
        const ctx = document.getElementById('humidity-chart').getContext('2d');
        humidityChart = new Chart(ctx, {
            type: 'line',
            data: chartData,
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        display: true,
                        position: 'bottom'
                    },
                    tooltip: {
                        callbacks: {
                            label: function(context) {
                                return `Luftfeuchtigkeit: ${context.parsed.y.toFixed(1)}%`;
                            }
                        }
                    }
                },
                scales: {
                    y: {
                        beginAtZero: false,
                        min: 0,
                        max: 100,
                        title: {
                            display: true,
                            text: 'Luftfeuchtigkeit (%)'
                        }
                    },
                    x: {
                        title: {
                            display: true,
                            text: 'Zeit'
                        }
                    }
                }
            }
        });

    } catch (error) {
        console.error('Error updating humidity chart:', error);
    }
}

// Zeige "Keine Daten" Nachricht
function showNoDataMessage() {
    document.getElementById('no-data-message').classList.remove('hidden');
    document.querySelectorAll('.chart-card').forEach(card => {
        card.style.opacity = '0.5';
    });
}

// Verstecke "Keine Daten" Nachricht
function hideNoDataMessage() {
    document.getElementById('no-data-message').classList.add('hidden');
    document.querySelectorAll('.chart-card').forEach(card => {
        card.style.opacity = '1';
    });
}

// === KOMFORT-METRIKEN ===

let presenceChart = null;

async function updateComfortMetrics() {
    try {
        const hoursBack = parseInt(document.getElementById('time-range').value);
        const data = await fetchJSON(`/api/analytics/comfort?hours=${hoursBack}`);
        
        // Null-Check: Bei Netzwerkfehler oder Tab-Wechsel kann data null sein
        if (!data) return;

        // Komfort-Score Circle
        const score = data.comfort_score || 0;
        const scoreText = document.getElementById('comfort-score-text');
        const scoreCircle = document.getElementById('comfort-score-circle');

        scoreText.textContent = score.toFixed(0);

        // Animiere Circle (314 = 2*PI*50)
        const offset = 314 - (314 * score / 100);
        scoreCircle.style.strokeDashoffset = offset;

        // Farbe basierend auf Score
        if (score >= 80) {
            scoreCircle.style.stroke = '#10b981'; // Grün
        } else if (score >= 60) {
            scoreCircle.style.stroke = '#3b82f6'; // Blau
        } else if (score >= 40) {
            scoreCircle.style.stroke = '#f59e0b'; // Orange
        } else {
            scoreCircle.style.stroke = '#ef4444'; // Rot
        }

        // Komfort-Details
        const detailsList = document.getElementById('comfort-details-list');
        if (data.comfort_details && data.comfort_details.length > 0) {
            detailsList.innerHTML = data.comfort_details.map(detail => {
                const isIdeal = detail.includes('ideal');
                const isGood = detail.includes('gut');
                const cssClass = isIdeal ? 'ideal' : (isGood ? 'good' : '');
                return `<div class="comfort-detail-item ${cssClass}">
                    ${isIdeal ? '✅' : (isGood ? '👍' : '⚠️')} ${detail}
                </div>`;
            }).join('');
        } else {
            detailsList.innerHTML = '<div class="info">Keine Daten verfügbar</div>';
        }

        // Schlafqualität
        const sleepContent = document.getElementById('sleep-quality-content');
        if (data.sleep_quality) {
            const sq = data.sleep_quality;
            const ratingClass = sq.rating === 'Ideal' ? 'ideal' : (sq.rating === 'Gut' ? 'good' : 'improve');

            sleepContent.innerHTML = `
                <div class="sleep-quality-card">
                    <div class="sleep-quality-score">
                        <div class="sleep-score-badge ${ratingClass}">${sq.score}</div>
                        <div>
                            <div style="font-weight: 700; font-size: 1.1em; margin-bottom: 5px;">${sq.rating}</div>
                            <div style="color: #6b7280;">Ø Nachttemperatur: ${sq.avg_temp}°C</div>
                        </div>
                    </div>
                    <div style="color: #6b7280; font-size: 0.9em;">${sq.description}</div>
                </div>
            `;
        } else {
            sleepContent.innerHTML = '<div class="info">Nicht genug Nachtdaten verfügbar</div>';
        }

        // Anwesenheits-Muster Chart
        if (data.presence_pattern && data.presence_pattern.length > 0) {
            renderPresenceChart(data.presence_pattern);
        }

    } catch (error) {
        console.error('Error updating comfort metrics:', error);
    }
}

function renderPresenceChart(presenceData) {
    const ctx = document.getElementById('presence-chart');
    if (!ctx) return;

    if (presenceChart) {
        presenceChart.destroy();
    }

    const labels = presenceData.map(p => `${p.hour}:00`);
    const values = presenceData.map(p => p.activity);

    presenceChart = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: labels,
            datasets: [{
                label: 'Aktivität',
                data: values,
                backgroundColor: 'rgba(59, 130, 246, 0.5)',
                borderColor: 'rgba(59, 130, 246, 1)',
                borderWidth: 1
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    display: false
                }
            },
            scales: {
                y: {
                    beginAtZero: true,
                    ticks: {
                        precision: 0
                    }
                }
            }
        }
    });
}

// === ML-PERFORMANCE ===

let confidenceChart = null;
let decisionTypesChart = null;

async function updateMLPerformance() {
    try {
        const daysBack = 30; // Fester Zeitraum für ML-Performance
        const data = await fetchJSON(`/api/analytics/ml-performance?days=${daysBack}`);
        
        // Null-Check: Bei Netzwerkfehler oder Tab-Wechsel kann data null sein
        if (!data) return;

        // Prüfe ob überhaupt ML-Daten vorhanden sind
        const hasMLData = (data.decision_stats && data.decision_stats.total_decisions > 0) || 
                         (data.training_history && data.training_history.length > 0);

        // Statistiken
        document.getElementById('ml-total-decisions').textContent =
            (data.decision_stats.total_decisions || 0).toLocaleString('de-DE');

        document.getElementById('ml-execution-rate').textContent =
            `${data.decision_stats.execution_rate || 0}% ausgeführt`;

        document.getElementById('ml-avg-confidence').textContent =
            (data.decision_stats.avg_confidence || 0).toFixed(3);

        document.getElementById('ml-training-count').textContent =
            (data.training_history.length || 0);

        if (data.training_history.length > 0) {
            const lastTraining = new Date(data.training_history[0].timestamp);
            document.getElementById('ml-last-training').textContent =
                `Letztes: ${lastTraining.toLocaleDateString('de-DE')}`;
        } else {
            document.getElementById('ml-last-training').textContent = 'Letztes: Noch keins';
        }

        // Zeige Info-Nachricht wenn keine ML-Daten vorhanden
        if (!hasMLData) {
            showMLNoDataInfo();
        } else {
            hideMLNoDataInfo();
        }

        // Confidence Trend Chart
        if (data.confidence_trends && data.confidence_trends.length > 0) {
            renderConfidenceChart(data.confidence_trends);
            hideChartNoData('confidence-chart');
        } else {
            showChartNoData('confidence-chart', 'Noch keine Entscheidungen getroffen. Im Auto-Modus werden hier Confidence-Werte angezeigt.');
        }

        // Decision Types Chart
        if (data.decision_stats.by_type && data.decision_stats.by_type.length > 0) {
            renderDecisionTypesChart(data.decision_stats.by_type);
            hideChartNoData('decision-types-chart');
        } else {
            showChartNoData('decision-types-chart', 'Noch keine Entscheidungen getroffen. Im Auto-Modus werden hier Entscheidungstypen angezeigt.');
        }

    } catch (error) {
        console.error('Error updating ML performance:', error);
    }
}

function showMLNoDataInfo() {
    // Finde oder erstelle Info-Box
    let infoBox = document.getElementById('ml-no-data-info');

    if (!infoBox) {
        infoBox = document.createElement('div');
        infoBox.id = 'ml-no-data-info';
        infoBox.className = 'ml-no-data-info';
        infoBox.innerHTML = `
            <div class="info-box" style="background: linear-gradient(135deg, #fef3c7 0%, #ffffff 100%); border-left: 4px solid #f59e0b; padding: 20px; border-radius: 8px; margin: 20px 0;">
                <h4 style="margin-top: 0; color: #92400e;">⏳ ML-Modelle noch nicht trainiert</h4>
                <p style="margin-bottom: 10px;">Das System befindet sich im <strong>Optimierungs-Modus</strong> und sammelt Daten.</p>
                <p style="margin-bottom: 10px;">ML-Modelle werden automatisch trainiert wenn:</p>
                <ul style="margin-left: 20px; margin-bottom: 10px;">
                    <li>Genügend Sensordaten gesammelt wurden (min. 100-200 Datenpunkte)</li>
                    <li>Der automatische Trainer läuft (täglich um 02:00 Uhr)</li>
                    <li>Oder manuell mit <code>python3 main.py train</code> gestartet</li>
                </ul>
                <p style="margin-bottom: 0; font-size: 0.9em; color: #78716c;">
                    💡 <strong>Tipp:</strong> Im Optimierungs-Modus werden keine automatischen Aktionen ausgeführt.
                    Das System analysiert nur und gibt Empfehlungen.
                </p>
            </div>
        `;

        // Füge nach den ml-stats-grid ein
        const mlCard = document.querySelector('.ml-performance-card');
        const statsGrid = mlCard.querySelector('.ml-stats-grid');
        if (statsGrid && statsGrid.nextSibling) {
            mlCard.insertBefore(infoBox, statsGrid.nextSibling);
        } else {
            mlCard.appendChild(infoBox);
        }
    }

    infoBox.style.display = 'block';
}

function hideMLNoDataInfo() {
    const infoBox = document.getElementById('ml-no-data-info');
    if (infoBox) {
        infoBox.style.display = 'none';
    }
}

function showChartNoData(chartId, message) {
    const canvas = document.getElementById(chartId);
    if (!canvas) return;
    
    // Verstecke Canvas
    canvas.style.display = 'none';
    
    // Erstelle oder finde No-Data Nachricht
    let noDataDiv = document.getElementById(chartId + '-no-data');
    if (!noDataDiv) {
        noDataDiv = document.createElement('div');
        noDataDiv.id = chartId + '-no-data';
        noDataDiv.style.cssText = 'text-align: center; padding: 40px 20px; color: #6b7280; background: linear-gradient(135deg, #f3f4f6 0%, #ffffff 100%); border-radius: 8px; margin: 10px 0;';
        canvas.parentNode.insertBefore(noDataDiv, canvas.nextSibling);
    }
    
    noDataDiv.innerHTML = `
        <div style="font-size: 2em; margin-bottom: 10px;">📊</div>
        <p style="margin: 0; font-size: 0.95em;">${message}</p>
        <p style="margin-top: 10px; font-size: 0.85em; color: #9ca3af;">
            💡 Wechsle in den <strong>Auto-Modus</strong> um automatische Entscheidungen zu aktivieren.
        </p>
    `;
    noDataDiv.style.display = 'block';
}

function hideChartNoData(chartId) {
    const canvas = document.getElementById(chartId);
    if (canvas) {
        canvas.style.display = 'block';
    }
    
    const noDataDiv = document.getElementById(chartId + '-no-data');
    if (noDataDiv) {
        noDataDiv.style.display = 'none';
    }
}

function renderConfidenceChart(trendsData) {
    const ctx = document.getElementById('confidence-chart');
    if (!ctx) return;

    if (confidenceChart) {
        confidenceChart.destroy();
    }

    const labels = trendsData.map(t => new Date(t.date).toLocaleDateString('de-DE', {month: 'short', day: 'numeric'}));
    const avgValues = trendsData.map(t => t.avg_confidence);
    const minValues = trendsData.map(t => t.min_confidence);
    const maxValues = trendsData.map(t => t.max_confidence);

    confidenceChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [
                {
                    label: 'Durchschnitt',
                    data: avgValues,
                    borderColor: 'rgba(59, 130, 246, 1)',
                    backgroundColor: 'rgba(59, 130, 246, 0.1)',
                    fill: true,
                    tension: 0.4
                },
                {
                    label: 'Min',
                    data: minValues,
                    borderColor: 'rgba(239, 68, 68, 0.5)',
                    borderDash: [5, 5],
                    pointRadius: 0,
                    tension: 0.4
                },
                {
                    label: 'Max',
                    data: maxValues,
                    borderColor: 'rgba(16, 185, 129, 0.5)',
                    borderDash: [5, 5],
                    pointRadius: 0,
                    tension: 0.4
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    position: 'top'
                },
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            return `${context.dataset.label}: ${context.parsed.y.toFixed(3)}`;
                        }
                    }
                }
            },
            scales: {
                y: {
                    min: 0,
                    max: 1,
                    ticks: {
                        callback: function(value) {
                            return value.toFixed(2);
                        }
                    }
                }
            }
        }
    });
}

function renderDecisionTypesChart(typesData) {
    const ctx = document.getElementById('decision-types-chart');
    if (!ctx) return;

    if (decisionTypesChart) {
        decisionTypesChart.destroy();
    }

    const labels = typesData.map(t => t.decision_type || 'Unbekannt');
    const values = typesData.map(t => t.count_per_type);

    const colors = [
        'rgba(59, 130, 246, 0.7)',   // Blau
        'rgba(16, 185, 129, 0.7)',   // Grün
        'rgba(245, 158, 11, 0.7)',   // Orange
        'rgba(239, 68, 68, 0.7)',    // Rot
        'rgba(139, 92, 246, 0.7)',   // Lila
        'rgba(236, 72, 153, 0.7)'    // Pink
    ];

    decisionTypesChart = new Chart(ctx, {
        type: 'doughnut',
        data: {
            labels: labels,
            datasets: [{
                data: values,
                backgroundColor: colors,
                borderWidth: 2,
                borderColor: '#ffffff'
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    position: 'right'
                },
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            const total = context.dataset.data.reduce((a, b) => a + b, 0);
                            const percentage = ((context.parsed / total) * 100).toFixed(1);
                            return `${context.label}: ${context.parsed} (${percentage}%)`;
                        }
                    }
                }
            }
        }
    });
}

// Aktualisiere alle Charts
function updateAllCharts() {
    const hoursBack = parseInt(document.getElementById('time-range').value);
    updateTemperatureChart(hoursBack);
    updateHumidityChart(hoursBack);
    updateComfortMetrics();
    updateMLPerformance();
}

// Init
document.addEventListener('DOMContentLoaded', () => {
    // Initiales Laden
    updateCollectorStatus();
    updateAllCharts();

    // Event Listeners
    document.getElementById('refresh-charts').addEventListener('click', updateAllCharts);
    document.getElementById('time-range').addEventListener('change', updateAllCharts);

    // Auto-refresh alle 30 Sekunden
    setInterval(() => {
        updateCollectorStatus();
        updateAllCharts();
    }, 30000);
});
