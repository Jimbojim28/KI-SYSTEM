// KI Smart Home - Haupt JavaScript

// API Base URL
const API_BASE = window.location.origin;

// Tab Visibility State - vermeide Netzwerkfehler bei inaktivem Tab
const TabVisibility = {
    isVisible: true,
    lastHiddenTime: null,
    
    init() {
        document.addEventListener('visibilitychange', () => {
            this.isVisible = document.visibilityState === 'visible';
            if (!this.isVisible) {
                this.lastHiddenTime = Date.now();
            }
        });
    },
    
    // Prüfe ob Tab sichtbar ist oder kürzlich sichtbar war
    shouldFetch() {
        return this.isVisible;
    },
    
    // Zeit seit Tab versteckt wurde (in ms)
    getHiddenDuration() {
        if (this.isVisible || !this.lastHiddenTime) return 0;
        return Date.now() - this.lastHiddenTime;
    }
};

// Initialisiere Tab Visibility Tracking
TabVisibility.init();

// Utility: Fetch JSON mit Tab-Visibility-Check und Retry-Logik
async function fetchJSON(endpoint, options = {}) {
    const { skipVisibilityCheck = false, silent = false } = options;
    
    // Wenn Tab nicht sichtbar ist und kein Skip-Flag gesetzt, überspringe Fetch
    if (!skipVisibilityCheck && !TabVisibility.shouldFetch()) {
        // Stille Rückgabe statt Fehler bei inaktivem Tab
        return null;
    }
    
    try {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 10000); // 10s Timeout
        
        const response = await fetch(`${API_BASE}${endpoint}`, {
            signal: controller.signal
        });
        
        clearTimeout(timeoutId);
        
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        return await response.json();
    } catch (error) {
        // Bei Tab-Wechsel verursachte Netzwerkfehler nicht loggen
        if (error.name === 'AbortError') {
            if (!silent) console.log('Fetch abgebrochen (Timeout oder Tab-Wechsel)');
            return null;
        }
        if (error.name === 'TypeError' && error.message.includes('NetworkError')) {
            // Stille Behandlung bei Tab-Wechsel Netzwerkfehlern
            if (!silent) console.log('Netzwerkfehler (möglicherweise Tab-Wechsel)');
            return null;
        }
        if (!silent) console.error('Fetch error:', error);
        throw error;
    }
}

// Utility: POST JSON mit verbesserter Fehlerbehandlung
async function postJSON(endpoint, data, options = {}) {
    const { silent = false } = options;
    
    try {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 15000); // 15s Timeout für POST
        
        const response = await fetch(`${API_BASE}${endpoint}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(data),
            signal: controller.signal
        });
        
        clearTimeout(timeoutId);
        
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        return await response.json();
    } catch (error) {
        if (error.name === 'AbortError') {
            if (!silent) console.log('POST abgebrochen (Timeout)');
            return null;
        }
        if (!silent) console.error('POST error:', error);
        throw error;
    }
}

// Formatiere Temperatur
function formatTemperature(temp) {
    if (temp === null || temp === undefined) return '--';
    return `${temp.toFixed(1)}°C`;
}

// Formatiere Prozent
function formatPercent(value) {
    if (value === null || value === undefined) return '--';
    return `${Math.round(value)}%`;
}

// Zeige Benachrichtigung
function showNotification(message, type = 'info') {
    // Einfache Console-Benachrichtigung (kann später erweitert werden)
    console.log(`[${type.toUpperCase()}] ${message}`);
}
// ===== SMART INTERVAL HELPER =====
// Erstellt ein Interval das nur läuft wenn der Tab sichtbar ist

function createSmartInterval(callback, intervalMs) {
    let intervalId = null;
    let isRunning = false;
    
    const start = () => {
        if (intervalId) return;
        isRunning = true;
        intervalId = setInterval(() => {
            if (document.visibilityState === 'visible') {
                callback();
            }
        }, intervalMs);
    };
    
    const stop = () => {
        if (intervalId) {
            clearInterval(intervalId);
            intervalId = null;
        }
        isRunning = false;
    };
    
    const restart = () => {
        stop();
        // Sofort ausführen wenn Tab sichtbar
        if (document.visibilityState === 'visible') {
            callback();
        }
        start();
    };
    
    // Auto-Restart bei Tab-Sichtbarkeit
    document.addEventListener('visibilitychange', () => {
        if (document.visibilityState === 'visible' && isRunning) {
            // Tab wieder sichtbar - sofort Callback ausführen
            callback();
        }
    });
    
    return { start, stop, restart, isRunning: () => isRunning };
}