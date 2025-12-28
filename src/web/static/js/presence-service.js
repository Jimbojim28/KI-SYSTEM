/**
 * Zentraler Presence Service
 * Stellt Anwesenheitsdaten für alle Seiten bereit
 */
(function() {
    'use strict';
    
    // Globales Presence-Objekt
    window.PresenceService = {
        // Aktuelle Daten
        data: null,
        lastUpdate: null,
        updateInterval: 30000, // 30 Sekunden
        intervalId: null,
        listeners: [],
        isLoading: false,
        
        // Initialisierung
        init: function() {
            // Initial laden
            this.refresh();
            
            // Auto-Update starten
            this.startAutoUpdate();
            
            // Bei Sichtbarkeit der Seite aktualisieren
            document.addEventListener('visibilitychange', () => {
                if (document.visibilityState === 'visible') {
                    this.refresh();
                }
            });
            
            console.log('PresenceService initialisiert');
        },
        
        // Daten laden
        refresh: async function() {
            // Nicht laden wenn Tab nicht sichtbar
            if (document.visibilityState !== 'visible') {
                return this.data;
            }
            
            if (this.isLoading) return this.data;
            
            this.isLoading = true;
            
            try {
                const controller = new AbortController();
                const timeoutId = setTimeout(() => controller.abort(), 10000);
                
                const response = await fetch('/api/presence', {
                    signal: controller.signal
                });
                
                clearTimeout(timeoutId);
                
                const data = await response.json();
                
                if (data.success) {
                    this.data = data;
                    this.lastUpdate = new Date();
                    
                    // Alle Listener benachrichtigen
                    this.notifyListeners();
                    
                    // Custom Event feuern
                    window.dispatchEvent(new CustomEvent('presenceUpdated', { 
                        detail: this.data 
                    }));
                }
                
                return this.data;
                
            } catch (error) {
                // Bei Tab-Wechsel Netzwerkfehler stille behandeln
                if (error.name === 'AbortError' || 
                    (error.name === 'TypeError' && error.message.includes('NetworkError'))) {
                    return this.data;
                }
                console.error('Fehler beim Laden der Anwesenheitsdaten:', error);
                return this.data;
            } finally {
                this.isLoading = false;
            }
        },
        
        // Auto-Update starten
        startAutoUpdate: function() {
            if (this.intervalId) return;
            
            this.intervalId = setInterval(() => {
                // Nur aktualisieren wenn Tab sichtbar
                if (document.visibilityState === 'visible') {
                    this.refresh();
                }
            }, this.updateInterval);
        },
        
        // Auto-Update stoppen
        stopAutoUpdate: function() {
            if (this.intervalId) {
                clearInterval(this.intervalId);
                this.intervalId = null;
            }
        },
        
        // Listener hinzufügen
        subscribe: function(callback) {
            if (typeof callback === 'function') {
                this.listeners.push(callback);
                
                // Sofort mit aktuellen Daten aufrufen wenn vorhanden
                if (this.data) {
                    callback(this.data);
                }
            }
            
            // Unsubscribe-Funktion zurückgeben
            return () => {
                this.listeners = this.listeners.filter(l => l !== callback);
            };
        },
        
        // Alle Listener benachrichtigen
        notifyListeners: function() {
            this.listeners.forEach(callback => {
                try {
                    callback(this.data);
                } catch (e) {
                    console.error('Fehler in Presence-Listener:', e);
                }
            });
        },
        
        // Hilfsfunktionen für schnellen Zugriff
        
        // Ist jemand zuhause?
        isAnyoneHome: function() {
            return this.data?.anyone_home ?? false;
        },
        
        // Anzahl anwesender Personen
        getHomeCount: function() {
            return this.data?.total_home ?? 0;
        },
        
        // Liste anwesender Personen
        getPresentUsers: function() {
            if (!this.data?.users) return [];
            return this.data.users.filter(u => u.present);
        },
        
        // Liste abwesender Personen
        getAwayUsers: function() {
            if (!this.data?.users) return [];
            return this.data.users.filter(u => !u.present);
        },
        
        // Alle Benutzer
        getAllUsers: function() {
            return this.data?.users ?? [];
        },
        
        // Bestimmten Benutzer finden
        getUser: function(name) {
            if (!this.data?.users) return null;
            return this.data.users.find(u => 
                u.name.toLowerCase().includes(name.toLowerCase())
            );
        },
        
        // Ist bestimmte Person zuhause?
        isUserHome: function(name) {
            const user = this.getUser(name);
            return user?.present ?? false;
        },
        
        // Status-Text generieren
        getStatusText: function() {
            if (!this.data) return 'Lade...';
            
            const home = this.data.total_home || 0;
            const total = this.data.total_users || 0;
            
            if (home === 0) return 'Niemand zuhause';
            if (home === total) return 'Alle zuhause';
            return `${home} von ${total} anwesend`;
        },
        
        // Status-Icon
        getStatusIcon: function() {
            return this.isAnyoneHome() ? '🏠' : '🚪';
        },
        
        // Quellen-Info
        getSourcesInfo: function() {
            if (!this.data?.sources) return '';
            
            const parts = [];
            const sources = this.data.sources;
            
            if (sources.homey?.available) {
                parts.push(`Homey: ${sources.homey.users_home}`);
            }
            if (sources.home_assistant?.available) {
                parts.push(`HA: ${sources.home_assistant.trackers_home}`);
            }
            
            return parts.join(' | ');
        }
    };
    
    // Automatisch initialisieren wenn DOM bereit
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => {
            window.PresenceService.init();
        });
    } else {
        window.PresenceService.init();
    }
})();
