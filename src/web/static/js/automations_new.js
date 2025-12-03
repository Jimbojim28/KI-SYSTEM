// Automatisierungen & Regeln - JavaScript
// Neue Version mit Szenen, Live-Status und Regel-Builder

document.addEventListener('DOMContentLoaded', function() {
    console.log('Automations New initialized');

    // ===========================================
    // SCHNELLAKTIONEN / SZENEN
    // ===========================================

    const scenes = {
        movie: {
            name: 'Kino-Modus',
            icon: '🎬',
            actions: [
                { type: 'lights', action: 'off', devices: 'all' },
                { type: 'blinds', action: 'close' }
            ]
        },
        goodnight: {
            name: 'Gute Nacht',
            icon: '🌙',
            actions: [
                { type: 'lights', action: 'off', devices: 'all' },
                { type: 'sockets', action: 'off', devices: 'all' },
                { type: 'heating', action: 'set', value: 18 }
            ]
        },
        away: {
            name: 'Ich bin weg',
            icon: '🏠',
            actions: [
                { type: 'lights', action: 'off', devices: 'all' },
                { type: 'sockets', action: 'off', devices: 'all' }
            ]
        },
        party: {
            name: 'Party',
            icon: '🎉',
            actions: [
                { type: 'lights', action: 'color', value: 'rainbow' },
                { type: 'music', action: 'on' }
            ]
        },
        morning: {
            name: 'Guten Morgen',
            icon: '☀️',
            actions: [
                { type: 'lights', action: 'on', brightness: 50 },
                { type: 'blinds', action: 'open' },
                { type: 'heating', action: 'set', value: 21 }
            ]
        },
        relax: {
            name: 'Entspannung',
            icon: '🛋️',
            actions: [
                { type: 'lights', action: 'dim', brightness: 30 },
                { type: 'heating', action: 'set', value: 22 }
            ]
        }
    };

    // Scene Card Click Handlers
    document.querySelectorAll('.scene-card').forEach(card => {
        const sceneBtn = card.querySelector('.btn-scene');
        const sceneName = card.dataset.scene;

        sceneBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            activateScene(sceneName);
        });
    });

    function activateScene(sceneName) {
        const scene = scenes[sceneName];
        if (!scene) {
            console.error('Scene not found:', sceneName);
            return;
        }

        console.log('Activating scene:', scene.name);

        // Visual feedback
        const card = document.querySelector(`.scene-card[data-scene="${sceneName}"]`);
        const btn = card.querySelector('.btn-scene');
        btn.textContent = 'Wird ausgeführt...';
        btn.style.opacity = '0.7';

        // Send to backend
        fetch('/api/automation/scene/activate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                scene: sceneName,
                actions: scene.actions
            })
        })
        .then(response => response.json())
        .then(data => {
            console.log('Scene activated:', data);
            btn.textContent = '✓ Aktiviert';
            setTimeout(() => {
                btn.textContent = 'Aktivieren';
                btn.style.opacity = '1';
            }, 2000);

            // Refresh status
            loadLiveStatus();
            loadRecentTriggers();
        })
        .catch(error => {
            console.error('Scene activation failed:', error);
            btn.textContent = '✗ Fehler';
            btn.style.backgroundColor = '#ef4444';
            setTimeout(() => {
                btn.textContent = 'Aktivieren';
                btn.style.opacity = '1';
                btn.style.backgroundColor = '';
            }, 2000);
        });
    }

    // ===========================================
    // LIVE-STATUS DASHBOARD
    // ===========================================

    function loadLiveStatus() {
        fetch('/api/automation/status')
            .then(response => response.json())
            .then(data => {
                // Active rules count
                document.getElementById('active-rules-count').textContent = data.active_rules || 0;

                // Today's triggers
                document.getElementById('today-triggers').textContent = data.today_triggers || 0;

                // Presence status
                const presenceDot = document.querySelector('.presence-dot');
                const presenceText = document.getElementById('presence-text');
                if (data.presence === 'home') {
                    presenceDot.style.background = '#10b981';
                    presenceText.textContent = 'Anwesend';
                } else if (data.presence === 'away') {
                    presenceDot.style.background = '#6b7280';
                    presenceText.textContent = 'Abwesend';
                } else {
                    presenceDot.style.background = '#f59e0b';
                    presenceText.textContent = 'Unbekannt';
                }

                // Current mode
                document.getElementById('current-mode').textContent = data.current_mode || 'Normal';
            })
            .catch(error => {
                console.error('Failed to load status:', error);
            });
    }

    function loadRecentTriggers() {
        fetch('/api/automation/triggers/recent')
            .then(response => response.json())
            .then(data => {
                const triggerList = document.getElementById('trigger-list');

                if (!data.triggers || data.triggers.length === 0) {
                    triggerList.innerHTML = '<p class="empty-state">Noch keine Automatisierungen ausgeführt</p>';
                    return;
                }

                triggerList.innerHTML = data.triggers.map(trigger => `
                    <div class="trigger-item">
                        <span class="trigger-time">${trigger.time}</span>
                        <span>${trigger.rule_name}: ${trigger.action}</span>
                    </div>
                `).join('');
            })
            .catch(error => {
                console.error('Failed to load triggers:', error);
            });
    }

    // Load status every 5 seconds
    loadLiveStatus();
    loadRecentTriggers();
    setInterval(loadLiveStatus, 5000);
    setInterval(loadRecentTriggers, 10000);

    // ===========================================
    // REGELN LADEN UND ANZEIGEN
    // ===========================================

    function loadRules() {
        fetch('/api/automation/rules')
            .then(response => response.json())
            .then(data => {
                const container = document.getElementById('rules-container');

                if (!data.rules || data.rules.length === 0) {
                    container.innerHTML = '<p class="empty-state">Noch keine Regeln erstellt. Klicke auf "+ Neue Regel" um zu beginnen.</p>';
                    return;
                }

                container.innerHTML = data.rules.map(rule => createRuleCard(rule)).join('');

                // Add event listeners
                attachRuleListeners();
            })
            .catch(error => {
                console.error('Failed to load rules:', error);
            });
    }

    function createRuleCard(rule) {
        const activeClass = rule.enabled ? 'active' : '';
        const toggleClass = rule.enabled ? 'active' : '';

        return `
            <div class="rule-card ${activeClass}" data-rule-id="${rule.id}">
                <div class="rule-card-header">
                    <div class="rule-card-title">
                        <div class="rule-icon">${rule.icon || '⚙️'}</div>
                        <div class="rule-info">
                            <h4>${rule.name}</h4>
                            <p>${formatRuleDescription(rule)}</p>
                        </div>
                    </div>
                    <div class="rule-controls">
                        <div class="rule-toggle ${toggleClass}" data-rule-id="${rule.id}"></div>
                        <button class="btn btn-secondary btn-sm btn-edit-rule" data-rule-id="${rule.id}">Bearbeiten</button>
                        <button class="btn-remove" data-rule-id="${rule.id}">Löschen</button>
                    </div>
                </div>
                <div class="rule-card-body">
                    <div style="margin-bottom: 15px;">
                        <strong>Bedingungen:</strong>
                        <ul style="margin: 5px 0; padding-left: 20px;">
                            ${rule.conditions.map(c => `<li>${formatCondition(c)}</li>`).join('')}
                        </ul>
                    </div>
                    <div>
                        <strong>Aktionen:</strong>
                        <ul style="margin: 5px 0; padding-left: 20px;">
                            ${rule.actions.map(a => `<li>${formatAction(a)}</li>`).join('')}
                        </ul>
                    </div>
                </div>
            </div>
        `;
    }

    function formatRuleDescription(rule) {
        const condCount = rule.conditions.length;
        const actionCount = rule.actions.length;
        return `${condCount} Bedingung${condCount !== 1 ? 'en' : ''}, ${actionCount} Aktion${actionCount !== 1 ? 'en' : ''}`;
    }

    function formatCondition(condition) {
        // Format: "Wenn [Gerät] [Operator] [Wert]"
        return `${condition.device} ${condition.operator} ${condition.value}`;
    }

    function formatAction(action) {
        // Format: "[Gerät] [Aktion]"
        return `${action.device}: ${action.action} ${action.value || ''}`;
    }

    function attachRuleListeners() {
        // Toggle switches
        document.querySelectorAll('.rule-toggle').forEach(toggle => {
            toggle.addEventListener('click', (e) => {
                e.stopPropagation();
                const ruleId = toggle.dataset.ruleId;
                toggleRule(ruleId);
            });
        });

        // Edit buttons
        document.querySelectorAll('.btn-edit-rule').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                const ruleId = btn.dataset.ruleId;
                editRule(ruleId);
            });
        });

        // Delete buttons
        document.querySelectorAll('.btn-remove').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                const ruleId = btn.dataset.ruleId;
                deleteRule(ruleId);
            });
        });

        // Card headers (expand/collapse)
        document.querySelectorAll('.rule-card-header').forEach(header => {
            header.addEventListener('click', (e) => {
                // Don't expand if clicking on controls
                if (e.target.closest('.rule-controls')) return;

                const card = header.closest('.rule-card');
                card.classList.toggle('expanded');
            });
        });
    }

    function toggleRule(ruleId) {
        fetch(`/api/automation/rules/${ruleId}/toggle`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        })
        .then(response => response.json())
        .then(data => {
            console.log('Rule toggled:', data);
            loadRules();
            loadLiveStatus();
        })
        .catch(error => {
            console.error('Toggle failed:', error);
            alert('Fehler beim Umschalten der Regel');
        });
    }

    function deleteRule(ruleId) {
        if (!confirm('Möchtest du diese Regel wirklich löschen?')) {
            return;
        }

        fetch(`/api/automation/rules/${ruleId}`, {
            method: 'DELETE'
        })
        .then(response => response.json())
        .then(data => {
            console.log('Rule deleted:', data);
            loadRules();
            loadLiveStatus();
        })
        .catch(error => {
            console.error('Delete failed:', error);
            alert('Fehler beim Löschen der Regel');
        });
    }

    // Load rules on init
    loadRules();

    // ===========================================
    // MODAL: NEUE REGEL ERSTELLEN
    // ===========================================

    const modalNewRule = document.getElementById('modal-new-rule');
    const btnNewRule = document.getElementById('btn-new-rule');
    const btnCancelRule = document.getElementById('btn-cancel-rule');
    const btnSaveRule = document.getElementById('btn-save-rule');

    let currentEditingRuleId = null;

    btnNewRule.addEventListener('click', () => {
        currentEditingRuleId = null;
        resetRuleForm();
        openModal(modalNewRule);
    });

    btnCancelRule.addEventListener('click', () => {
        closeModal(modalNewRule);
    });

    btnSaveRule.addEventListener('click', () => {
        saveRule();
    });

    function resetRuleForm() {
        document.getElementById('rule-name').value = '';
        document.getElementById('rule-icon').value = '';
        document.getElementById('conditions-container').innerHTML = '';
        document.getElementById('actions-container').innerHTML = '';

        // Add initial condition and action
        addCondition();
        addAction();
    }

    // Bedingung hinzufügen
    document.getElementById('btn-add-condition').addEventListener('click', addCondition);

    function addCondition() {
        const container = document.getElementById('conditions-container');
        const conditionId = Date.now();

        const conditionHTML = `
            <div class="condition-item" data-condition-id="${conditionId}">
                <select class="condition-type">
                    <option value="device">Gerät</option>
                    <option value="time">Zeit</option>
                    <option value="sensor">Sensor</option>
                    <option value="presence">Präsenz</option>
                </select>
                <select class="condition-device">
                    <option value="">Gerät wählen...</option>
                </select>
                <select class="condition-operator">
                    <option value="==">=</option>
                    <option value="!=">≠</option>
                    <option value=">">&gt;</option>
                    <option value="<">&lt;</option>
                </select>
                <input type="text" class="condition-value" placeholder="Wert">
                <button class="btn-remove" onclick="this.parentElement.remove()">×</button>
            </div>
        `;

        container.insertAdjacentHTML('beforeend', conditionHTML);
        loadDevicesForCondition(conditionId);
    }

    function loadDevicesForCondition(conditionId) {
        fetch('/api/devices')
            .then(response => response.json())
            .then(data => {
                const select = document.querySelector(`[data-condition-id="${conditionId}"] .condition-device`);
                if (data.devices) {
                    data.devices.forEach(device => {
                        const option = document.createElement('option');
                        option.value = device.id;
                        option.textContent = device.name;
                        select.appendChild(option);
                    });
                }
            })
            .catch(error => console.error('Failed to load devices:', error));
    }

    // Aktion hinzufügen
    document.getElementById('btn-add-action').addEventListener('click', addAction);

    function addAction() {
        const container = document.getElementById('actions-container');
        const actionId = Date.now();

        const actionHTML = `
            <div class="action-item" data-action-id="${actionId}">
                <select class="action-type">
                    <option value="device">Gerät steuern</option>
                    <option value="scene">Szene aktivieren</option>
                    <option value="notification">Benachrichtigung</option>
                </select>
                <select class="action-device">
                    <option value="">Gerät wählen...</option>
                </select>
                <select class="action-command">
                    <option value="on">Einschalten</option>
                    <option value="off">Ausschalten</option>
                    <option value="toggle">Umschalten</option>
                    <option value="set">Wert setzen</option>
                </select>
                <input type="text" class="action-value" placeholder="Wert (optional)">
                <button class="btn-remove" onclick="this.parentElement.remove()">×</button>
            </div>
        `;

        container.insertAdjacentHTML('beforeend', actionHTML);
        loadDevicesForAction(actionId);
    }

    function loadDevicesForAction(actionId) {
        fetch('/api/devices')
            .then(response => response.json())
            .then(data => {
                const select = document.querySelector(`[data-action-id="${actionId}"] .action-device`);
                if (data.devices) {
                    data.devices.forEach(device => {
                        const option = document.createElement('option');
                        option.value = device.id;
                        option.textContent = device.name;
                        select.appendChild(option);
                    });
                }
            })
            .catch(error => console.error('Failed to load devices:', error));
    }

    function saveRule() {
        const name = document.getElementById('rule-name').value.trim();
        const icon = document.getElementById('rule-icon').value.trim();

        if (!name) {
            alert('Bitte gib einen Namen für die Regel ein.');
            return;
        }

        // Collect conditions
        const conditions = [];
        document.querySelectorAll('.condition-item').forEach(item => {
            const type = item.querySelector('.condition-type').value;
            const device = item.querySelector('.condition-device').value;
            const operator = item.querySelector('.condition-operator').value;
            const value = item.querySelector('.condition-value').value;

            if (device && value) {
                conditions.push({ type, device, operator, value });
            }
        });

        // Collect actions
        const actions = [];
        document.querySelectorAll('.action-item').forEach(item => {
            const type = item.querySelector('.action-type').value;
            const device = item.querySelector('.action-device').value;
            const action = item.querySelector('.action-command').value;
            const value = item.querySelector('.action-value').value;

            if (device && action) {
                actions.push({ type, device, action, value });
            }
        });

        if (conditions.length === 0) {
            alert('Bitte füge mindestens eine Bedingung hinzu.');
            return;
        }

        if (actions.length === 0) {
            alert('Bitte füge mindestens eine Aktion hinzu.');
            return;
        }

        const ruleData = {
            name,
            icon: icon || '⚙️',
            conditions,
            actions,
            enabled: true
        };

        const url = currentEditingRuleId
            ? `/api/automation/rules/${currentEditingRuleId}`
            : '/api/automation/rules';
        const method = currentEditingRuleId ? 'PUT' : 'POST';

        fetch(url, {
            method,
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(ruleData)
        })
        .then(response => response.json())
        .then(data => {
            console.log('Rule saved:', data);
            closeModal(modalNewRule);
            loadRules();
            loadLiveStatus();
        })
        .catch(error => {
            console.error('Save failed:', error);
            alert('Fehler beim Speichern der Regel');
        });
    }

    function editRule(ruleId) {
        fetch(`/api/automation/rules/${ruleId}`)
            .then(response => response.json())
            .then(rule => {
                currentEditingRuleId = ruleId;

                // Fill form
                document.getElementById('rule-name').value = rule.name;
                document.getElementById('rule-icon').value = rule.icon || '';

                // Clear containers
                document.getElementById('conditions-container').innerHTML = '';
                document.getElementById('actions-container').innerHTML = '';

                // Load conditions
                rule.conditions.forEach(cond => {
                    addCondition();
                    const items = document.querySelectorAll('.condition-item');
                    const item = items[items.length - 1];
                    item.querySelector('.condition-type').value = cond.type;
                    item.querySelector('.condition-device').value = cond.device;
                    item.querySelector('.condition-operator').value = cond.operator;
                    item.querySelector('.condition-value').value = cond.value;
                });

                // Load actions
                rule.actions.forEach(act => {
                    addAction();
                    const items = document.querySelectorAll('.action-item');
                    const item = items[items.length - 1];
                    item.querySelector('.action-type').value = act.type;
                    item.querySelector('.action-device').value = act.device;
                    item.querySelector('.action-command').value = act.action;
                    item.querySelector('.action-value').value = act.value || '';
                });

                openModal(modalNewRule);
            })
            .catch(error => {
                console.error('Failed to load rule:', error);
                alert('Fehler beim Laden der Regel');
            });
    }

    // ===========================================
    // MODAL: VORLAGEN
    // ===========================================

    const modalTemplates = document.getElementById('modal-templates');
    const btnTemplates = document.getElementById('btn-templates');

    btnTemplates.addEventListener('click', () => {
        loadTemplates();
        openModal(modalTemplates);
    });

    function loadTemplates() {
        const templates = [
            {
                id: 'motion-light',
                icon: '💡',
                name: 'Licht bei Bewegung',
                description: 'Schaltet Licht ein wenn Bewegung erkannt wird',
                conditions: [{ type: 'sensor', device: 'motion', operator: '==', value: 'detected' }],
                actions: [{ type: 'device', device: 'light', action: 'on' }]
            },
            {
                id: 'temp-heating',
                icon: '🌡️',
                name: 'Heizung bei Kälte',
                description: 'Heizung an wenn Temperatur unter 18°C',
                conditions: [{ type: 'sensor', device: 'temperature', operator: '<', value: '18' }],
                actions: [{ type: 'device', device: 'heating', action: 'on' }]
            },
            {
                id: 'humidity-fan',
                icon: '💨',
                name: 'Lüfter bei Feuchtigkeit',
                description: 'Lüfter an wenn Luftfeuchtigkeit > 70%',
                conditions: [{ type: 'sensor', device: 'humidity', operator: '>', value: '70' }],
                actions: [{ type: 'device', device: 'fan', action: 'on' }]
            },
            {
                id: 'evening-lights',
                icon: '🌆',
                name: 'Abend-Beleuchtung',
                description: 'Lichter dimmen ab 20:00 Uhr',
                conditions: [{ type: 'time', device: 'clock', operator: '>=', value: '20:00' }],
                actions: [{ type: 'device', device: 'lights', action: 'set', value: '30' }]
            },
            {
                id: 'away-all-off',
                icon: '🚪',
                name: 'Alles aus bei Abwesenheit',
                description: 'Alle Geräte aus wenn abwesend',
                conditions: [{ type: 'presence', device: 'presence', operator: '==', value: 'away' }],
                actions: [
                    { type: 'device', device: 'lights', action: 'off' },
                    { type: 'device', device: 'sockets', action: 'off' }
                ]
            },
            {
                id: 'morning-routine',
                icon: '☕',
                name: 'Morgen-Routine',
                description: 'Lichter & Heizung an um 7:00',
                conditions: [{ type: 'time', device: 'clock', operator: '==', value: '07:00' }],
                actions: [
                    { type: 'device', device: 'lights', action: 'on', value: '80' },
                    { type: 'device', device: 'heating', action: 'set', value: '21' }
                ]
            }
        ];

        const grid = document.getElementById('templates-grid');
        grid.innerHTML = templates.map(template => `
            <div class="template-card" data-template-id="${template.id}">
                <div class="template-icon">${template.icon}</div>
                <div class="template-name">${template.name}</div>
                <div class="template-description">${template.description}</div>
            </div>
        `).join('');

        // Add click handlers
        document.querySelectorAll('.template-card').forEach(card => {
            card.addEventListener('click', () => {
                const templateId = card.dataset.templateId;
                const template = templates.find(t => t.id === templateId);
                applyTemplate(template);
            });
        });
    }

    function applyTemplate(template) {
        currentEditingRuleId = null;

        document.getElementById('rule-name').value = template.name;
        document.getElementById('rule-icon').value = template.icon;

        // Clear containers
        document.getElementById('conditions-container').innerHTML = '';
        document.getElementById('actions-container').innerHTML = '';

        // Add conditions
        template.conditions.forEach(cond => {
            addCondition();
            const items = document.querySelectorAll('.condition-item');
            const item = items[items.length - 1];
            item.querySelector('.condition-type').value = cond.type;
            item.querySelector('.condition-operator').value = cond.operator;
            item.querySelector('.condition-value').value = cond.value;
        });

        // Add actions
        template.actions.forEach(act => {
            addAction();
            const items = document.querySelectorAll('.action-item');
            const item = items[items.length - 1];
            item.querySelector('.action-type').value = act.type;
            item.querySelector('.action-command').value = act.action;
            if (act.value) {
                item.querySelector('.action-value').value = act.value;
            }
        });

        closeModal(modalTemplates);
        openModal(modalNewRule);
    }

    // ===========================================
    // MODAL HELPER FUNCTIONS
    // ===========================================

    function openModal(modal) {
        modal.classList.add('show');
    }

    function closeModal(modal) {
        modal.classList.remove('show');
    }

    // Close modals on background click
    document.querySelectorAll('.modal').forEach(modal => {
        modal.addEventListener('click', (e) => {
            if (e.target === modal) {
                closeModal(modal);
            }
        });

        const closeBtn = modal.querySelector('.modal-close');
        if (closeBtn) {
            closeBtn.addEventListener('click', () => {
                closeModal(modal);
            });
        }
    });

    // Close modals on ESC key
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            document.querySelectorAll('.modal.show').forEach(modal => {
                closeModal(modal);
            });
        }
    });

    // ===========================================
    // ABWESENHEIT TAB
    // ===========================================

    // Load absence settings on page load
    loadAbsenceSettings();
    loadAbsencePreview();

    // Toggle handler for absence notifications
    const absenceToggle = document.getElementById('absence-enabled');
    if (absenceToggle) {
        absenceToggle.addEventListener('change', function() {
            saveAbsenceSettings();
        });
    }

    // Save button handler
    const saveAbsenceBtn = document.getElementById('save-absence-settings');
    if (saveAbsenceBtn) {
        saveAbsenceBtn.addEventListener('click', saveAbsenceSettings);
    }

    // Test button handler
    const testAbsenceBtn = document.getElementById('test-absence-notification');
    if (testAbsenceBtn) {
        testAbsenceBtn.addEventListener('click', testAbsenceNotification);
    }

    // Refresh preview button
    const refreshPreviewBtn = document.getElementById('refresh-absence-preview');
    if (refreshPreviewBtn) {
        refreshPreviewBtn.addEventListener('click', loadAbsencePreview);
    }
});

// ===========================================
// ABWESENHEIT FUNCTIONS (GLOBAL SCOPE)
// ===========================================

function loadAbsenceSettings() {
    fetch('/api/automations/absence-settings')
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                const settings = data.settings;
                
                const enabledToggle = document.getElementById('absence-enabled');
                if (enabledToggle) {
                    enabledToggle.checked = settings.enabled || false;
                }
                
                const apiKeyInput = document.getElementById('pushover-api-key');
                if (apiKeyInput && settings.pushover_api_key) {
                    apiKeyInput.value = settings.pushover_api_key;
                }
                
                const userKeyInput = document.getElementById('pushover-user-key');
                if (userKeyInput && settings.pushover_user_key) {
                    userKeyInput.value = settings.pushover_user_key;
                }
            }
        })
        .catch(error => {
            console.error('Error loading absence settings:', error);
        });
}

function saveAbsenceSettings() {
    const settings = {
        enabled: document.getElementById('absence-enabled')?.checked || false,
        pushover_api_key: document.getElementById('pushover-api-key')?.value || '',
        pushover_user_key: document.getElementById('pushover-user-key')?.value || ''
    };

    fetch('/api/automations/absence-settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(settings)
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            showNotification('Einstellungen gespeichert', 'success');
        } else {
            showNotification('Fehler beim Speichern: ' + data.error, 'error');
        }
    })
    .catch(error => {
        console.error('Error saving absence settings:', error);
        showNotification('Fehler beim Speichern', 'error');
    });
}

function loadAbsencePreview() {
    const previewContainer = document.getElementById('absence-preview-content');
    if (!previewContainer) return;

    previewContainer.innerHTML = '<div style="text-align: center; padding: 20px;">⏳ Lade Status...</div>';

    fetch('/api/automations/absence-status')
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                renderAbsencePreview(data);
            } else {
                previewContainer.innerHTML = '<div style="text-align: center; padding: 20px; color: #ef4444;">❌ Fehler beim Laden</div>';
            }
        })
        .catch(error => {
            console.error('Error loading absence preview:', error);
            previewContainer.innerHTML = '<div style="text-align: center; padding: 20px; color: #ef4444;">❌ Verbindungsfehler</div>';
        });
}

function renderAbsencePreview(data) {
    const previewContainer = document.getElementById('absence-preview-content');
    if (!previewContainer) return;

    const now = new Date().toLocaleString('de-DE', {
        day: '2-digit',
        month: '2-digit',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit'
    });

    // Count lights and windows
    const lightsOn = data.lights ? data.lights.filter(l => l.on).length : 0;
    const totalLights = data.lights ? data.lights.length : 0;
    const windowsOpen = data.windows ? data.windows.filter(w => w.state === 'open').length : 0;
    const windowsTilted = data.windows ? data.windows.filter(w => w.state === 'tilted').length : 0;
    const totalWindows = data.windows ? data.windows.length : 0;

    // Determine status
    const allGood = lightsOn === 0 && windowsOpen === 0;
    const statusClass = allGood ? 'all-good' : 'warning';
    const statusIcon = allGood ? '✅' : '⚠️';
    const statusText = allGood 
        ? 'Alles in Ordnung - bereit zum Verlassen' 
        : `${lightsOn > 0 ? lightsOn + ' Licht(er) an' : ''}${lightsOn > 0 && windowsOpen > 0 ? ', ' : ''}${windowsOpen > 0 ? windowsOpen + ' Fenster offen' : ''}`;

    let html = `
        <div class="preview-header">
            <h5>🏠 Status-Übersicht</h5>
            <span class="preview-time">${now}</span>
        </div>
        <div class="preview-sections">
            <div class="preview-section">
                <h6>💡 Lichter (${lightsOn}/${totalLights} an)</h6>
                <div class="lights-grid">
    `;

    // Render lights
    if (data.lights && data.lights.length > 0) {
        data.lights.forEach(light => {
            const stateClass = light.on ? 'on' : 'off';
            const icon = light.on ? '💡' : '⚫';
            html += `<div class="light-item ${stateClass}">${icon} ${light.name}</div>`;
        });
    } else {
        html += '<div class="light-item">Keine Lichter gefunden</div>';
    }

    html += `
                </div>
            </div>
            <div class="preview-section">
                <h6>🪟 Fenster (${windowsOpen} offen, ${windowsTilted} gekippt)</h6>
                <div class="windows-grid">
    `;

    // Render windows
    if (data.windows && data.windows.length > 0) {
        data.windows.forEach(window => {
            let stateClass = 'closed';
            let icon = '🟢';
            let stateLabel = 'Zu';
            
            if (window.state === 'open') {
                stateClass = 'open';
                icon = '🔴';
                stateLabel = 'Offen';
            } else if (window.state === 'tilted') {
                stateClass = 'tilted';
                icon = '🟡';
                stateLabel = 'Gekippt';
            }
            
            html += `<div class="window-item ${stateClass}">${icon} ${window.name} <small>(${stateLabel})</small></div>`;
        });
    } else {
        html += '<div class="window-item">Keine Fenster gefunden</div>';
    }

    html += `
                </div>
            </div>
        </div>
        <div class="absence-summary">
            <span class="summary-badge ${statusClass}">${statusIcon} ${statusText}</span>
        </div>
    `;

    previewContainer.innerHTML = html;
}

function testAbsenceNotification() {
    const btn = document.getElementById('test-absence-notification');
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = '⏳ Sende...';
    }

    fetch('/api/automations/absence-test-notification', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' }
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            showNotification('Test-Benachrichtigung gesendet!', 'success');
        } else {
            showNotification('Fehler: ' + (data.error || 'Unbekannter Fehler'), 'error');
        }
    })
    .catch(error => {
        console.error('Error sending test notification:', error);
        showNotification('Fehler beim Senden', 'error');
    })
    .finally(() => {
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = '📤 Test-Benachrichtigung senden';
        }
    });
}

function showNotification(message, type = 'info') {
    // Check if notification function exists from other scripts
    if (typeof showToast === 'function') {
        showToast(message, type);
        return;
    }

    // Simple fallback notification
    const notification = document.createElement('div');
    notification.style.cssText = `
        position: fixed;
        bottom: 20px;
        right: 20px;
        padding: 15px 25px;
        border-radius: 8px;
        color: white;
        font-weight: 500;
        z-index: 10000;
        animation: slideIn 0.3s ease;
        background: ${type === 'success' ? '#10b981' : type === 'error' ? '#ef4444' : '#3b82f6'};
    `;
    notification.textContent = message;
    document.body.appendChild(notification);

    setTimeout(() => {
        notification.style.opacity = '0';
        notification.style.transition = 'opacity 0.3s';
        setTimeout(() => notification.remove(), 300);
    }, 3000);
}
