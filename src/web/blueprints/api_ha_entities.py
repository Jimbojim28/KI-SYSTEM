"""
API Blueprint für Home Assistant Entitäten-Verwaltung
"""

import json
import logging
import unicodedata
import requests
from pathlib import Path
from flask import Blueprint, jsonify, request, current_app
from datetime import datetime
import yaml

logger = logging.getLogger(__name__)

ha_entities_bp = Blueprint('api_ha_entities', __name__)


def get_homey_device_details(device_id: str) -> dict:
    """Holt vollständige Device-Details direkt von der Homey API (inkl. MAC-Adresse in data.id)"""
    try:
        config_path = Path(__file__).parent.parent.parent.parent / 'config' / 'config.yaml'
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
        
        homey_config = config.get('homey', {})
        url = homey_config.get('url', '').rstrip('/')
        token = homey_config.get('token', '')
        
        if not url or not token:
            return {}
            
        api_url = f"{url}/api/manager/devices/device/{device_id}"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        
        response = requests.get(api_url, headers=headers, timeout=10)
        if response.status_code == 200:
            return response.json()
    except Exception as e:
        logger.error(f"Error fetching Homey device details: {e}")
    return {}

# Globale Engine Referenz
engine = None

# Pfad zur JSON-Datei
HA_ENTITIES_FILE = Path(__file__).parent.parent.parent.parent / 'data' / 'ha_entities.json'


def load_ha_entities() -> dict:
    """Lädt die gespeicherten HA-Entitäten"""
    if HA_ENTITIES_FILE.exists():
        try:
            with open(HA_ENTITIES_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Fehler beim Laden der HA-Entitäten: {e}")
    return {"entities": []}


def save_ha_entities(data: dict) -> bool:
    """Speichert die HA-Entitäten"""
    try:
        HA_ENTITIES_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(HA_ENTITIES_FILE, 'w') as f:
            json.dump(data, f, indent=2)
        return True
    except Exception as e:
        logger.error(f"Fehler beim Speichern der HA-Entitäten: {e}")
        return False


def get_ha_collector():
    """Holt den Home Assistant Collector aus der App"""
    try:
        from src.data_collector.ha_collector import HomeAssistantCollector
        import yaml
        
        config_path = Path(__file__).parent.parent.parent.parent / 'config' / 'config.yaml'
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
        
        ha_config = config.get('homeassistant', {})
        if not ha_config.get('url') or not ha_config.get('token'):
            return None
            
        return HomeAssistantCollector(
            ha_config.get('url'),
            ha_config.get('token')
        )
    except Exception as e:
        logger.error(f"Fehler beim Erstellen des HA Collectors: {e}")
        return None


def get_entity_state(collector, entity_id: str) -> dict:
    """Holt den Status einer einzelnen Entität von Home Assistant"""
    try:
        if not collector:
            return {"state": "unknown", "error": "Keine HA-Verbindung"}
        
        # Versuche direkt die Entity abzufragen
        import requests
        
        url = f"{collector.url}/api/states/{entity_id}"
        headers = {
            "Authorization": f"Bearer {collector.token}",
            "Content-Type": "application/json"
        }
        
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            return {
                "state": data.get("state", "unknown"),
                "attributes": data.get("attributes", {}),
                "last_changed": data.get("last_changed"),
                "last_updated": data.get("last_updated"),
                "friendly_name": data.get("attributes", {}).get("friendly_name", entity_id),
                "available": True
            }
        elif response.status_code == 404:
            return {
                "state": "not_found",
                "error": "Entität nicht gefunden",
                "available": False
            }
        else:
            return {
                "state": "error",
                "error": f"HTTP {response.status_code}",
                "available": False
            }
            
    except Exception as e:
        logger.error(f"Fehler beim Abrufen des Status für {entity_id}: {e}")
        return {
            "state": "error",
            "error": str(e),
            "available": False
        }


@ha_entities_bp.route('/api/ha/entities', methods=['GET'])
def get_entities():
    """Gibt alle gespeicherten HA-Entitäten mit aktuellem Status zurück"""
    try:
        data = load_ha_entities()
        entities = data.get('entities', [])
        
        # Hole aktuellen Status für jede Entität
        collector = get_ha_collector()
        
        result = []
        for entity in entities:
            entity_id = entity.get('entity_id')
            state_info = get_entity_state(collector, entity_id)
            
            result.append({
                **entity,
                "current_state": state_info.get("state"),
                "attributes": state_info.get("attributes", {}),
                "last_changed": state_info.get("last_changed"),
                "last_updated": state_info.get("last_updated"),
                "friendly_name": state_info.get("friendly_name", entity.get("name", entity_id)),
                "available": state_info.get("available", False),
                "error": state_info.get("error")
            })
        
        return jsonify({
            "success": True,
            "entities": result,
            "count": len(result)
        })
        
    except Exception as e:
        logger.error(f"Fehler beim Abrufen der HA-Entitäten: {e}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@ha_entities_bp.route('/api/ha/entities', methods=['POST'])
def add_entity():
    """Fügt eine neue HA-Entität hinzu"""
    try:
        req_data = request.get_json()
        
        entity_id = req_data.get('entity_id', '').strip()
        entity_type = req_data.get('type', 'switch')
        custom_name = req_data.get('name', '').strip()
        
        if not entity_id:
            return jsonify({
                "success": False,
                "error": "Entity-ID ist erforderlich"
            }), 400
        
        # Validiere Entity-ID Format
        if '.' not in entity_id:
            return jsonify({
                "success": False,
                "error": "Ungültiges Entity-ID Format. Erwartet: domain.entity_name (z.B. switch.steckdose)"
            }), 400
        
        # Lade bestehende Entitäten
        data = load_ha_entities()
        entities = data.get('entities', [])
        
        # Prüfe ob Entity bereits existiert
        for entity in entities:
            if entity.get('entity_id') == entity_id:
                return jsonify({
                    "success": False,
                    "error": f"Entität {entity_id} ist bereits hinzugefügt"
                }), 400
        
        # Hole initialen Status
        collector = get_ha_collector()
        initial_state = get_entity_state(collector, entity_id)
        
        # Neue Entität erstellen
        new_entity = {
            "entity_id": entity_id,
            "type": entity_type,
            "name": custom_name or initial_state.get("friendly_name", entity_id),
            "added_at": datetime.now().isoformat(),
            "domain": entity_id.split('.')[0] if '.' in entity_id else "unknown"
        }
        
        entities.append(new_entity)
        data['entities'] = entities
        
        if save_ha_entities(data):
            return jsonify({
                "success": True,
                "message": f"Entität {entity_id} wurde hinzugefügt",
                "entity": {
                    **new_entity,
                    "current_state": initial_state.get("state"),
                    "attributes": initial_state.get("attributes", {}),
                    "available": initial_state.get("available", False),
                    "error": initial_state.get("error")
                }
            })
        else:
            return jsonify({
                "success": False,
                "error": "Fehler beim Speichern"
            }), 500
            
    except Exception as e:
        logger.error(f"Fehler beim Hinzufügen der HA-Entität: {e}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@ha_entities_bp.route('/api/ha/entities/<path:entity_id>', methods=['DELETE'])
def delete_entity(entity_id: str):
    """Löscht eine HA-Entität"""
    try:
        data = load_ha_entities()
        entities = data.get('entities', [])
        
        # Finde und entferne die Entität
        original_count = len(entities)
        entities = [e for e in entities if e.get('entity_id') != entity_id]
        
        if len(entities) == original_count:
            return jsonify({
                "success": False,
                "error": f"Entität {entity_id} nicht gefunden"
            }), 404
        
        data['entities'] = entities
        
        if save_ha_entities(data):
            return jsonify({
                "success": True,
                "message": f"Entität {entity_id} wurde entfernt"
            })
        else:
            return jsonify({
                "success": False,
                "error": "Fehler beim Speichern"
            }), 500
            
    except Exception as e:
        logger.error(f"Fehler beim Löschen der HA-Entität: {e}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@ha_entities_bp.route('/api/ha/entities/<path:entity_id>/state', methods=['GET'])
def get_entity_status(entity_id: str):
    """Holt den aktuellen Status einer einzelnen Entität"""
    try:
        collector = get_ha_collector()
        state_info = get_entity_state(collector, entity_id)
        
        return jsonify({
            "success": True,
            "entity_id": entity_id,
            **state_info
        })
        
    except Exception as e:
        logger.error(f"Fehler beim Abrufen des Status für {entity_id}: {e}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@ha_entities_bp.route('/api/ha/entities/<path:entity_id>/toggle', methods=['POST'])
def toggle_entity(entity_id: str):
    """Schaltet eine Entität um (on/off)"""
    try:
        collector = get_ha_collector()
        if not collector:
            return jsonify({
                "success": False,
                "error": "Keine Home Assistant Verbindung"
            }), 503
        
        import requests
        
        # Bestimme den Service basierend auf der Domain
        domain = entity_id.split('.')[0] if '.' in entity_id else 'switch'
        
        # Hole aktuellen Status
        current_state = get_entity_state(collector, entity_id)
        
        # Bestimme die Aktion
        if current_state.get('state') in ['on', 'playing', 'open']:
            service = 'turn_off'
        else:
            service = 'turn_on'
        
        # Für bestimmte Domains den korrekten Service verwenden
        if domain == 'cover':
            service = 'close_cover' if current_state.get('state') == 'open' else 'open_cover'
        
        url = f"{collector.url}/api/services/{domain}/{service}"
        headers = {
            "Authorization": f"Bearer {collector.token}",
            "Content-Type": "application/json"
        }
        
        response = requests.post(
            url,
            headers=headers,
            json={"entity_id": entity_id},
            timeout=10
        )
        
        if response.status_code in [200, 201]:
            # Warte kurz und hole neuen Status
            import time
            time.sleep(0.5)
            new_state = get_entity_state(collector, entity_id)
            
            return jsonify({
                "success": True,
                "entity_id": entity_id,
                "previous_state": current_state.get('state'),
                "new_state": new_state.get('state'),
                "action": service
            })
        else:
            return jsonify({
                "success": False,
                "error": f"Home Assistant Fehler: {response.status_code}"
            }), 500
            
    except Exception as e:
        logger.error(f"Fehler beim Umschalten von {entity_id}: {e}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@ha_entities_bp.route('/api/ha/connection', methods=['GET'])
def check_connection():
    """Prüft die Home Assistant Verbindung"""
    try:
        import yaml
        import requests
        
        config_path = Path(__file__).parent.parent.parent.parent / 'config' / 'config.yaml'
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
        
        ha_config = config.get('homeassistant', {})
        ha_url = ha_config.get('url', '')
        ha_token = ha_config.get('token', '')
        
        if not ha_url or not ha_token:
            return jsonify({
                "success": True,
                "connected": False,
                "configured": False,
                "message": "Home Assistant ist nicht konfiguriert. Bitte URL und Token in den Verbindungseinstellungen eingeben."
            })
        
        # Teste die Verbindung
        try:
            headers = {
                "Authorization": f"Bearer {ha_token}",
                "Content-Type": "application/json"
            }
            response = requests.get(f"{ha_url}/api/", headers=headers, timeout=5)
            
            if response.status_code == 200:
                api_info = response.json()
                return jsonify({
                    "success": True,
                    "connected": True,
                    "configured": True,
                    "url": ha_url,
                    "version": api_info.get("version", "Unbekannt"),
                    "message": f"Verbunden mit Home Assistant {api_info.get('version', '')}"
                })
            elif response.status_code == 401:
                return jsonify({
                    "success": True,
                    "connected": False,
                    "configured": True,
                    "message": "Authentifizierung fehlgeschlagen. Bitte Token überprüfen."
                })
            else:
                return jsonify({
                    "success": True,
                    "connected": False,
                    "configured": True,
                    "message": f"Verbindungsfehler: HTTP {response.status_code}"
                })
                
        except requests.exceptions.Timeout:
            return jsonify({
                "success": True,
                "connected": False,
                "configured": True,
                "message": "Zeitüberschreitung beim Verbinden mit Home Assistant"
            })
        except requests.exceptions.ConnectionError:
            return jsonify({
                "success": True,
                "connected": False,
                "configured": True,
                "message": f"Verbindung zu {ha_url} nicht möglich"
            })
            
    except Exception as e:
        logger.error(f"Fehler beim Prüfen der HA-Verbindung: {e}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@ha_entities_bp.route('/api/presence', methods=['GET'])
def get_combined_presence():
    """
    Kombinierte Anwesenheitserkennung aus Homey UND Home Assistant Device Trackern.
    Nutzt beide Quellen für maximale Zuverlässigkeit.
    """
    try:
        import yaml
        from src.data_collector.homey_collector import HomeyCollector
        
        result = {
            "anyone_home": False,
            "users": [],
            "sources": {
                "homey": {"available": False, "users_home": 0},
                "home_assistant": {"available": False, "trackers_home": 0}
            }
        }
        
        # 1. Homey Presence (User-basiert)
        try:
            config_path = Path(__file__).parent.parent.parent.parent / 'config' / 'config.yaml'
            with open(config_path, 'r') as f:
                config = yaml.safe_load(f)
            
            homey_config = config.get('homey', {})
            if homey_config.get('url') and homey_config.get('token'):
                homey = HomeyCollector(homey_config['url'], homey_config['token'])
                homey_presence = homey.get_presence_status()
                
                result["sources"]["homey"]["available"] = True
                result["sources"]["homey"]["users_home"] = homey_presence.get("users_home", 0)
                
                for user in homey_presence.get("users", []):
                    result["users"].append({
                        "name": user.get("name", "Unbekannt"),
                        "present": user.get("present", False),
                        "source": "homey",
                        "type": "user"
                    })
                    
        except Exception as e:
            logger.warning(f"Homey Presence nicht verfügbar: {e}")
        
        # 2. Home Assistant Device Tracker
        try:
            data = load_ha_entities()
            entities = data.get('entities', [])
            
            # Filtere nur device_tracker und person Entitäten
            trackers = [e for e in entities if e.get('type') in ['device_tracker', 'person']]
            
            if trackers:
                collector = get_ha_collector()
                if collector:
                    result["sources"]["home_assistant"]["available"] = True
                    trackers_home = 0
                    
                    for tracker in trackers:
                        entity_id = tracker.get('entity_id')
                        state_info = get_entity_state(collector, entity_id)
                        
                        # Status bestimmen: 'home', 'not_home', Zone-Name
                        state = state_info.get("state", "unknown")
                        is_home = state.lower() in ['home', 'zu hause', 'zuhause'] or \
                                  (state.lower() not in ['not_home', 'away', 'unterwegs', 'unknown', 'unavailable'])
                        
                        # Raumname aus State (für iBeacon Tracker)
                        location = state if state not in ['home', 'not_home', 'unknown', 'unavailable'] else None
                        
                        if is_home and state not in ['unknown', 'unavailable', 'not_home']:
                            trackers_home += 1
                        
                        result["users"].append({
                            "name": tracker.get("name", entity_id),
                            "present": is_home and state not in ['unknown', 'unavailable'],
                            "source": "home_assistant",
                            "type": tracker.get("type", "device_tracker"),
                            "entity_id": entity_id,
                            "state": state,
                            "location": location,  # z.B. "Küche", "Flur"
                            "last_changed": state_info.get("last_changed"),
                            "available": state_info.get("available", False)
                        })
                    
                    result["sources"]["home_assistant"]["trackers_home"] = trackers_home
                    
        except Exception as e:
            logger.warning(f"HA Device Tracker nicht verfügbar: {e}")
        
        # 3. Gesamtergebnis berechnen
        # Jemand ist zu Hause wenn MINDESTENS eine Quelle "anwesend" meldet
        homey_home = result["sources"]["homey"].get("users_home", 0) > 0
        ha_home = result["sources"]["home_assistant"].get("trackers_home", 0) > 0
        
        result["anyone_home"] = homey_home or ha_home
        result["total_home"] = sum(1 for u in result["users"] if u.get("present", False))
        result["total_users"] = len(result["users"])
        
        # Dedupliziere nach Name (falls gleiche Person in beiden Systemen)
        seen_names = {}
        deduplicated_users = []
        for user in result["users"]:
            name = user.get("name", "").lower().replace("-", " ").replace("_", " ")
            if name not in seen_names:
                seen_names[name] = user
                deduplicated_users.append(user)
            else:
                # Merge: bevorzuge "present=True"
                if user.get("present") and not seen_names[name].get("present"):
                    seen_names[name]["present"] = True
                # Füge Location hinzu wenn vorhanden
                if user.get("location"):
                    seen_names[name]["location"] = user.get("location")
        
        result["users"] = deduplicated_users
        result["total_home"] = sum(1 for u in deduplicated_users if u.get("present", False))
        result["total_users"] = len(deduplicated_users)
        
        return jsonify({
            "success": True,
            **result
        })
        
    except Exception as e:
        logger.error(f"Fehler bei kombinierter Anwesenheitserkennung: {e}")
        return jsonify({
            "success": False,
            "error": str(e),
            "anyone_home": True  # Fallback: anwesend
        }), 500


@ha_entities_bp.route('/api/presence/tracking', methods=['GET'])
def get_presence_tracking():
    """
    Holt Presence Tracking Statistiken.
    
    Query-Parameter:
    - date: Datum für Tagesstatistik (YYYY-MM-DD), Standard: heute
    - type: 'daily', 'alltime', 'current' (Standard: 'daily')
    """
    try:
        from src.background.presence_tracker import get_presence_tracker
        
        tracker = get_presence_tracker()
        stat_type = request.args.get('type', 'daily')
        date = request.args.get('date')
        
        if stat_type == 'current':
            # Aktuelle Positionen
            positions = tracker.get_current_positions()
            return jsonify({
                "success": True,
                "type": "current",
                "positions": positions
            })
            
        elif stat_type == 'alltime':
            # Gesamtstatistik
            stats = tracker.get_all_time_stats()
            return jsonify({
                "success": True,
                "type": "alltime",
                "stats": stats
            })
            
        else:
            # Tagesstatistik (Standard)
            stats = tracker.get_daily_stats(date)
            return jsonify({
                "success": True,
                "type": "daily",
                "date": date or datetime.now().strftime('%Y-%m-%d'),
                "stats": stats
            })
            
    except Exception as e:
        logger.error(f"Fehler beim Abrufen der Tracking-Statistiken: {e}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@ha_entities_bp.route('/api/presence/tracking/history', methods=['GET'])
def get_presence_history():
    """
    Holt die Tracking-Historie für einen bestimmten Zeitraum.
    
    Query-Parameter:
    - days: Anzahl Tage zurück (Standard: 7)
    - entity_id: Optional - Filter für bestimmtes Gerät
    """
    try:
        from src.background.presence_tracker import get_presence_tracker
        
        tracker = get_presence_tracker()
        days = int(request.args.get('days', 7))
        entity_id = request.args.get('entity_id')
        
        # Sammle Statistiken für jeden Tag
        history = []
        for i in range(days):
            date = (datetime.now() - timedelta(days=i)).strftime('%Y-%m-%d')
            daily_stats = tracker.get_daily_stats(date)
            
            if entity_id:
                # Filtere für bestimmtes Gerät
                if entity_id in daily_stats:
                    history.append({
                        "date": date,
                        "stats": {entity_id: daily_stats[entity_id]}
                    })
            else:
                if daily_stats:
                    history.append({
                        "date": date,
                        "stats": daily_stats
                    })
        
        return jsonify({
            "success": True,
            "days": days,
            "entity_id": entity_id,
            "history": history
        })
        
    except Exception as e:
        logger.error(f"Fehler beim Abrufen der Tracking-Historie: {e}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


def init_ha_entities_blueprint(engine_instance):
    """Initialisiert den Blueprint mit Engine Referenz"""
    global engine
    engine = engine_instance
    logger.info("HA Entities Blueprint initialized with engine")


@ha_entities_bp.route('/api/ha/search-integration', methods=['POST'])
def search_integration():
    """
    Sucht alle Entities einer bestimmten Integration in Home Assistant.
    
    Body-Parameter:
    - integration: Name der Integration (z.B. 'bthome', 'shelly', 'zigbee2mqtt')
    - domain: Optional - Filter für Domain (z.B. 'binary_sensor', 'sensor')
    """
    try:
        req_data = request.get_json() or {}
        integration = req_data.get('integration', '').strip().lower()
        domain_filter = req_data.get('domain', '').strip().lower()
        
        if not integration:
            return jsonify({
                "success": False,
                "error": "Integration name ist erforderlich"
            }), 400
        
        collector = get_ha_collector()
        if not collector:
            return jsonify({
                "success": False,
                "error": "Keine Home Assistant Verbindung"
            }), 503
        
        import requests
        
        # Hole alle States von Home Assistant
        url = f"{collector.url}/api/states"
        headers = {
            "Authorization": f"Bearer {collector.token}",
            "Content-Type": "application/json"
        }
        
        response = requests.get(url, headers=headers, timeout=15)
        
        if response.status_code != 200:
            return jsonify({
                "success": False,
                "error": f"Home Assistant Fehler: {response.status_code}"
            }), 500
        
        all_states = response.json()
        
        # Filtere nach Integration
        # Suche in entity_id, friendly_name und attributes
        found_entities = []
        search_terms = [integration, integration.replace('_', ''), integration.replace('-', '')]
        
        for state in all_states:
            entity_id = state.get('entity_id', '')
            friendly_name = state.get('attributes', {}).get('friendly_name', '')
            device_class = state.get('attributes', {}).get('device_class', '')
            
            # Domain-Filter anwenden
            if domain_filter:
                entity_domain = entity_id.split('.')[0] if '.' in entity_id else ''
                if entity_domain != domain_filter:
                    continue
            
            # Suche nach Integration im entity_id oder friendly_name
            match = False
            for term in search_terms:
                if term in entity_id.lower() or term in friendly_name.lower():
                    match = True
                    break
            
            if match:
                domain = entity_id.split('.')[0] if '.' in entity_id else 'unknown'
                
                # Bestimme den Typ basierend auf domain und device_class
                entity_type = domain
                if device_class:
                    entity_type = f"{domain} ({device_class})"
                
                found_entities.append({
                    "entity_id": entity_id,
                    "friendly_name": friendly_name,
                    "domain": domain,
                    "device_class": device_class,
                    "state": state.get('state'),
                    "type": domain,
                    "attributes": {
                        k: v for k, v in state.get('attributes', {}).items() 
                        if k in ['friendly_name', 'device_class', 'unit_of_measurement', 'icon']
                    },
                    "available": state.get('state') not in ['unavailable', 'unknown']
                })
        
        # Sortiere nach domain und dann nach name
        found_entities.sort(key=lambda x: (x['domain'], x['friendly_name']))
        
        return jsonify({
            "success": True,
            "integration": integration,
            "domain_filter": domain_filter,
            "count": len(found_entities),
            "entities": found_entities
        })
        
    except Exception as e:
        logger.error(f"Fehler beim Suchen der Integration: {e}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@ha_entities_bp.route('/api/ha/add-multiple', methods=['POST'])
def add_multiple_entities():
    """
    Fügt mehrere HA-Entitäten gleichzeitig hinzu.
    
    Body-Parameter:
    - entities: Liste von {entity_id, type, name} Objekten
    """
    try:
        req_data = request.get_json() or {}
        entities_to_add = req_data.get('entities', [])
        
        if not entities_to_add:
            return jsonify({
                "success": False,
                "error": "Keine Entitäten zum Hinzufügen"
            }), 400
        
        data = load_ha_entities()
        existing_entities = data.get('entities', [])
        existing_ids = {e.get('entity_id') for e in existing_entities}
        
        added = []
        skipped = []
        
        for entity_info in entities_to_add:
            entity_id = entity_info.get('entity_id', '').strip()
            entity_type = entity_info.get('type', 'sensor')
            custom_name = entity_info.get('name', '').strip()
            
            if not entity_id:
                continue
            
            if entity_id in existing_ids:
                skipped.append(entity_id)
                continue
            
            # Erstelle neuen Eintrag
            new_entity = {
                "entity_id": entity_id,
                "type": entity_type,
                "name": custom_name or entity_info.get('friendly_name', entity_id),
                "added_at": datetime.now().isoformat(),
                "domain": entity_id.split('.')[0] if '.' in entity_id else "unknown"
            }
            
            existing_entities.append(new_entity)
            existing_ids.add(entity_id)
            added.append(entity_id)
        
        data['entities'] = existing_entities
        
        if save_ha_entities(data):
            return jsonify({
                "success": True,
                "added": added,
                "added_count": len(added),
                "skipped": skipped,
                "skipped_count": len(skipped),
                "message": f"{len(added)} Entitäten hinzugefügt" + (f", {len(skipped)} übersprungen (bereits vorhanden)" if skipped else "")
            })
        else:
            return jsonify({
                "success": False,
                "error": "Fehler beim Speichern"
            }), 500
        
    except Exception as e:
        logger.error(f"Fehler beim Hinzufügen mehrerer Entitäten: {e}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


# === HA Window Mapping Endpoints ===

HA_MAPPING_FILE = Path(__file__).parent.parent.parent.parent / 'config' / 'ha_window_mapping.json'

def load_ha_mapping() -> dict:
    """Lädt das HA Window Mapping"""
    if HA_MAPPING_FILE.exists():
        try:
            with open(HA_MAPPING_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Fehler beim Laden des HA Mappings: {e}")
    return {"mappings": {}}

def save_ha_mapping(data: dict) -> bool:
    """Speichert das HA Window Mapping"""
    try:
        HA_MAPPING_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(HA_MAPPING_FILE, 'w') as f:
            json.dump(data, f, indent=2)
        return True
    except Exception as e:
        logger.error(f"Fehler beim Speichern des HA Mappings: {e}")
        return False

@ha_entities_bp.route('/api/ha/mappings', methods=['GET'])
def get_mappings():
    """Gibt alle konfigurierten Mappings zurück, angereichert mit aktuellem Status"""
    data = load_ha_mapping()
    
    # Versuche Status zu holen
    try:
        collector = get_ha_collector()
        if collector:
            mappings = data.get('mappings', {})
            for m_id, mapping in mappings.items():
                entities = mapping.get('entities', {})
                contact_id = entities.get('contact')
                if contact_id:
                    state = get_entity_state(collector, contact_id)
                    mapping['current_state'] = state.get('state')
                    mapping['contact_entity'] = contact_id
    except Exception as e:
        logger.warning(f"Konnte Status für Mappings nicht laden: {e}")
        
    return jsonify(data)

@ha_entities_bp.route('/api/ha/mappings', methods=['POST'])
def save_mapping():
    """Speichert ein neues Mapping oder aktualisiert ein bestehendes"""
    try:
        req_data = request.json
        mapping_id = req_data.get('id')
        
        if not mapping_id:
            import uuid
            mapping_id = str(uuid.uuid4())
            
        mapping_data = {
            "name": req_data.get('name'),
            "room": req_data.get('room'),
            "type": req_data.get('type', 'window'),
            "source": req_data.get('source', 'ha'),
            "entities": req_data.get('entities', {})
        }
        
        # Validierung
        if not mapping_data['name'] or not mapping_data['room']:
            return jsonify({"success": False, "error": "Name und Raum sind erforderlich"}), 400
            
        current_data = load_ha_mapping()
        current_data['mappings'][mapping_id] = mapping_data
        
        if save_ha_mapping(current_data):
            return jsonify({"success": True, "id": mapping_id, "mapping": mapping_data})
        else:
            return jsonify({"success": False, "error": "Fehler beim Speichern"}), 500
            
    except Exception as e:
        logger.error(f"Fehler beim Speichern des Mappings: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@ha_entities_bp.route('/api/ha/mappings/<mapping_id>', methods=['DELETE'])
def delete_mapping(mapping_id):
    """Löscht ein Mapping"""
    try:
        current_data = load_ha_mapping()
        if mapping_id in current_data['mappings']:
            del current_data['mappings'][mapping_id]
            if save_ha_mapping(current_data):
                return jsonify({"success": True})
            else:
                return jsonify({"success": False, "error": "Fehler beim Speichern"}), 500
        else:
            return jsonify({"success": False, "error": "Mapping nicht gefunden"}), 404
    except Exception as e:
        logger.error(f"Fehler beim Löschen des Mappings: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@ha_entities_bp.route('/api/ha/available', methods=['GET'])
def get_available_entities():
    """Holt alle verfügbaren Entitäten von HA"""
    collector = get_ha_collector()
    if not collector:
        return jsonify({"success": False, "error": "Keine Verbindung zu Home Assistant"}), 503
        
    try:
        states = collector.get_states()
        entities = []
        for entity_id, state in states.items():
            entities.append({
                "entity_id": entity_id,
                "name": state.get('attributes', {}).get('friendly_name', entity_id),
                "domain": entity_id.split('.')[0],
                "state": state.get('state')
            })
        return jsonify({"success": True, "entities": entities})
    except Exception as e:
        logger.error(f"Fehler beim Abrufen der HA Entitäten: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@ha_entities_bp.route('/api/ha/match-room', methods=['POST'])
def match_room():
    """Versucht den Raum anhand der MAC-Adresse in Homey zu finden"""
    try:
        req_data = request.json
        entity_name = req_data.get('name', '')
        
        if not entity_name:
            return jsonify({"success": False, "error": "Kein Name übergeben"})
            
        # Extrahiere MAC (z.B. "9F3D" aus "BTHome sensor 9F3D")
        import re
        # Suche nach 4 Hex-Zeichen, die oft am Ende von Namen stehen oder Teil einer MAC sind
        # Shelly BLU devices haben oft die letzten 4 Zeichen der MAC im Namen
        mac_match = re.search(r'([0-9A-Fa-f]{4})', entity_name)
        
        if not mac_match:
             return jsonify({"success": False, "error": "Keine MAC-ID im Namen gefunden"})
             
        mac_part = mac_match.group(1).lower()
        logger.info(f"Searching for device with MAC part: {mac_part} (extracted from '{entity_name}')")
        
        if not engine:
             logger.error("Engine is None in match_room")
             return jsonify({"success": False, "error": "Interner Fehler: Engine nicht initialisiert"})

        if not engine.platform:
             logger.error("Engine.platform is None in match_room")
             return jsonify({"success": False, "error": "Keine Homey Verbindung (Platform nicht initialisiert)"})
             
        # Suche in Homey Devices
        devices = engine.platform.get_all_devices()
        logger.info(f"Searching in {len(devices)} Homey devices")
        
        zones = engine.platform.get_zones()
        
        found_device = None
        found_room = None
        
        for device in devices:
            # Sammle alle relevanten Werte zum Durchsuchen
            candidates = []
            
            # Name
            candidates.append(device.get('name', ''))
            
            # Settings Werte (z.B. address)
            if 'settings' in device and isinstance(device['settings'], dict):
                candidates.extend([str(v) for v in device['settings'].values()])
                
            # Data Werte
            if 'data' in device and isinstance(device['data'], dict):
                candidates.extend([str(v) for v in device['data'].values()])
            
            # Prüfe jeden Kandidaten
            for val in candidates:
                # Normalisiere: Kleinbuchstaben und Doppelpunkte entfernen
                # Aus "7C:C6:B6:71:9F:3D" wird "7cc6b6719f3d"
                val_norm = val.lower().replace(':', '')
                
                if mac_part in val_norm:
                    found_device = device
                    logger.info(f"Match found! Device: {device.get('name')}, Value: {val}, Norm: {val_norm}, Search: {mac_part}")
                    break
            
            if found_device:
                break
        
        if found_device:
            zone_id = found_device.get('zone')
            if zone_id and zone_id in zones:
                found_room = zones[zone_id]
                return jsonify({
                    "success": True, 
                    "room": found_room, 
                    "device_name": found_device.get('name'),
                    "match_type": "mac_address"
                })
            else:
                return jsonify({"success": False, "error": f"Gerät '{found_device.get('name')}' gefunden, aber keinem Raum zugeordnet"})
        
        logger.warning(f"No match found for {mac_part} in {len(devices)} devices")
        return jsonify({"success": False, "error": f"Kein Gerät mit ID {mac_part} in Homey gefunden"})
        
    except Exception as e:
        logger.error(f"Fehler bei Raum-Suche: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@ha_entities_bp.route('/api/ha/find-sensor-for-room', methods=['POST'])
def find_sensor_for_room():
    """Findet einen HA Sensor passend zu einem Raum (via Homey MAC)"""
    try:
        req_data = request.json
        room_name = req_data.get('room')
        search_term = req_data.get('search_term', '').strip()
        logger.info(f"DEBUG: find_sensor_for_room called for room: {room_name}, search_term: {search_term}")
        
        if not room_name:
            return jsonify({"success": False, "error": "Kein Raum angegeben"})
            
        if not engine or not engine.platform:
             return jsonify({"success": False, "error": "Keine Homey Verbindung"})
        
        # Bereits verwendete Sensoren aus dem Mapping laden
        used_sensors = set()
        mapping_file = Path(__file__).parent.parent.parent.parent / 'config' / 'ha_window_mapping.json'
        if mapping_file.exists():
            try:
                with open(mapping_file, 'r') as f:
                    mapping_data = json.load(f)
                    for mapping in mapping_data.get('mappings', {}).values():
                        if mapping.get('entities', {}).get('contact'):
                            used_sensors.add(mapping['entities']['contact'])
                logger.info(f"DEBUG: Already used sensors: {used_sensors}")
            except Exception as e:
                logger.warning(f"Could not load used sensors: {e}")
             
        search_criteria = [] # List of dicts: {'type': 'mac'|'name', 'value': str, 'device_name': str}

        # If search term is provided, use it directly
        if search_term:
            search_criteria.append({
                'type': 'name',
                'value': search_term.lower(),
                'device_name': search_term
            })
            # Also try to interpret as MAC if it looks like one
            clean_term = search_term.replace(':', '').lower()
            if len(clean_term) >= 4 and all(c in '0123456789abcdef' for c in clean_term):
                 search_criteria.append({
                     'type': 'mac', 
                     'value': clean_term[-4:], 
                     'device_name': search_term
                 })
        
        # Otherwise (or additionally?), try to find devices in Homey Zone
        # Let's only do Zone lookup if no search term, OR if we want to combine results
        # For now, if search term is given, we prioritize it, but maybe we should still look in the room?
        # The user might want to search for something specific because the room lookup failed.
        
        if not search_term:
            # Normalize room name
            room_name_norm = unicodedata.normalize('NFC', room_name).strip().lower()

            # 1. Finde Zone ID für Raum
            zones = engine.platform.get_zones()
            zone_id = None
            
            # zones is a dict of dicts: {id: {id:..., name:..., ...}}
            for z_id, z_data in zones.items():
                z_name = z_data.get('name', '')
                if unicodedata.normalize('NFC', z_name).strip().lower() == room_name_norm:
                    zone_id = z_data.get('id', z_id)
                    break
            
            if not zone_id:
                logger.warning(f"DEBUG: Room '{room_name}' not found in zones. Available: {[z.get('name') for z in zones.values()]}")
                # If room not found in Homey, we can't do auto-detect based on room content.
                # But if we had a search term, we wouldn't be here.
                return jsonify({"success": False, "error": f"Raum '{room_name}' in Homey nicht gefunden"})
                
            logger.info(f"DEBUG: Found Zone ID {zone_id} for room {room_name}")

            # 2. Finde Geräte in Zone
            devices = engine.platform.get_all_devices()
            
            if isinstance(devices, dict):
                devices_list = list(devices.values())
            else:
                devices_list = devices
                
            room_devices = [d for d in devices_list if d.get('zone') == zone_id]
            
            logger.info(f"DEBUG: Found {len(room_devices)} devices in room {room_name}")
            
            if not room_devices:
                return jsonify({"success": False, "error": f"Keine Geräte im Raum '{room_name}' gefunden"})
                
            # 3. Extrahiere MACs und Namen aus Homey Geräten
            for device in room_devices:
                device_name = device.get('name', '')
                device_id = device.get('id', '')
                
                # Add Name Search Criteria
                if device_name:
                    search_criteria.append({
                        'type': 'name',
                        'value': device_name.lower(),
                        'device_name': device_name
                    })
                
                # Hole vollständige Device-Details direkt von Homey API
                # Die lokale API gibt settings/data oft leer zurück, aber die direkte API hat die MAC in data.id
                if device_id:
                    full_device = get_homey_device_details(device_id)
                    if full_device:
                        # MAC-Adresse ist in data.id für Shelly BLU Geräte
                        mac_from_data = full_device.get('data', {}).get('id', '')
                        if mac_from_data and ':' in str(mac_from_data):
                            clean_mac = str(mac_from_data).replace(':', '').lower()
                            if len(clean_mac) >= 4 and all(c in '0123456789abcdef' for c in clean_mac):
                                mac = clean_mac[-4:]
                                search_criteria.append({'type': 'mac', 'value': mac, 'device_name': device_name})
                                logger.info(f"DEBUG: Found MAC {mac} from Homey API for device {device_name}")
                                continue  # Prioritize direct API MAC, skip local cache lookup
                # Add MAC Search Criteria
                candidates = []
                if 'settings' in device and isinstance(device['settings'], dict):
                    candidates.extend([str(v) for v in device['settings'].values()])
                if 'data' in device and isinstance(device['data'], dict):
                    candidates.extend([str(v) for v in device['data'].values()])
                    
                for val in candidates:
                    val_str = str(val).strip()
                    # Check for MAC format XX:XX:XX...
                    if ':' in val_str and len(val_str) >= 11:
                         clean = val_str.replace(':', '').lower()
                         if all(c in '0123456789abcdef' for c in clean):
                             mac = clean[-4:]
                             search_criteria.append({'type': 'mac', 'value': mac, 'device_name': device_name})
                             logger.info(f"DEBUG: Found MAC candidate {mac} in device {device_name}")
                             continue
                    
                    # Check for raw hex string (12 chars)
                    if len(val_str) == 12 and all(c in '0123456789abcdefABCDEF' for c in val_str):
                         mac = val_str[-4:].lower()
                         search_criteria.append({'type': 'mac', 'value': mac, 'device_name': device_name})
                         logger.info(f"DEBUG: Found MAC candidate {mac} in device {device_name}")
        
        if not search_criteria:
             logger.warning(f"DEBUG: No search criteria found in {len(room_devices)} devices")
             return jsonify({"success": False, "error": "Keine suchbaren Merkmale (MAC/Name) gefunden"})
             
        # 4. Suche in HA Entities
        collector = get_ha_collector()
        if not collector:
            return jsonify({"success": False, "error": "Keine HA Verbindung"})
            
        ha_states = collector.get_states()
        logger.info(f"DEBUG: Checking {len(ha_states)} HA entities against criteria")
        
        # Collect all matches first
        matches = {}  # key (mac or name) -> {name: str, entities: list, score_bonus: int}
        available_devices = {} # Group all valid BTHome devices found (for fallback)

        for entity_id, state in ha_states.items():
            # NUR BTHome/Shelly BLU Sensoren berücksichtigen!
            entity_id_lower = entity_id.lower()
            friendly_name = state.get('attributes', {}).get('friendly_name', '').lower()
            
            # Strict Filter: Must be BTHome/Shelly BLU
            if not ('bthome' in entity_id_lower or 'shelly_blu' in entity_id_lower):
                continue
                
            # Strict Filter: Must be a Window/Door/Contact sensor
            # Check domain and device_class/name
            domain = entity_id.split('.')[0]
            device_class = state.get('attributes', {}).get('device_class', '')
            
            is_window_door = False
            if domain == 'binary_sensor':
                if device_class in ['window', 'door', 'garage_door', 'opening', 'lock']:
                    is_window_door = True
                elif any(x in entity_id_lower or x in friendly_name for x in ['window', 'door', 'fenster', 'tür', 'contact', 'kontakt']):
                    is_window_door = True
            
            # Also allow sensors that belong to a window device (battery, rotation, etc.)
            # But we only want to MATCH on the main sensor or if we are sure it's a window device
            if not is_window_door:
                # If it's not a binary sensor, check if it's part of a device that IS a window sensor
                # This is hard without device registry. 
                # So we rely on naming convention: "shelly_blu_door_window"
                if 'door_window' in entity_id_lower or 'door_window' in friendly_name:
                    is_window_door = True
            
            if not is_window_door:
                continue

            # Überspringe bereits verwendete Sensoren!
            if entity_id in used_sensors:
                logger.info(f"DEBUG: Skipping already used sensor: {entity_id}")
                continue
            
            # Add to available devices list (for fallback)
            # Group by a simplified name (remove suffixes)
            # e.g. "BTHome sensor 1E9B Window" -> "BTHome sensor 1E9B"
            simple_name = state.get('attributes', {}).get('friendly_name', entity_id)
            for suffix in [' Window', ' Door', ' Contact', ' Battery', ' Illuminance', ' Rotation', ' Button']:
                if simple_name.endswith(suffix):
                    simple_name = simple_name[:-len(suffix)]
                    break
            
            if simple_name not in available_devices:
                available_devices[simple_name] = {
                    "device_name": simple_name,
                    "entities": []
                }
            
            available_devices[simple_name]["entities"].append({
                "entity_id": entity_id,
                "friendly_name": state.get('attributes', {}).get('friendly_name', ''),
                "domain": domain,
                "state": state.get('state'),
                "attributes": state.get('attributes', {})
            })
                
            for criteria in search_criteria:
                match_found = False
                score_bonus = 0
                
                if criteria['type'] == 'mac':
                    if criteria['value'] in friendly_name or criteria['value'] in entity_id_lower:
                        match_found = True
                        score_bonus = 20 # MAC match is very strong
                
                elif criteria['type'] == 'name':
                    # Token based matching with normalization
                    # Replace special chars with spaces to handle "Fenster-Küche" vs "Fenster Küche"
                    def normalize_tokens(text):
                        text = text.lower()
                        for char in ['-', '_', '.', '(', ')', '[', ']', ':']:
                            text = text.replace(char, ' ')
                        return set(text.split())

                    dev_tokens = normalize_tokens(criteria['value'])
                    ha_tokens = normalize_tokens(friendly_name)
                    
                    # Also check entity_id for tokens
                    ha_tokens.update(normalize_tokens(entity_id_lower))
                    
                    common_tokens = dev_tokens.intersection(ha_tokens)
                    
                    # Calculate match ratio
                    if len(dev_tokens) > 0:
                        match_ratio = len(common_tokens) / len(dev_tokens)
                    else:
                        match_ratio = 0
                    
                    # Debug logging for specific room
                    if 'küche' in criteria['value'] and 'fenster' in criteria['value']:
                         print(f"DEBUG MATCH: Dev='{criteria['value']}' HA='{friendly_name}' Tokens={dev_tokens} HA_Tokens={ha_tokens} Common={common_tokens} Ratio={match_ratio}")

                    # Strict matching: All tokens must be present (or at least most of them)
                    if len(dev_tokens) > 1 and match_ratio >= 0.8:
                        match_found = True
                        score_bonus = 15 # Name match is strong if tokens match
                    elif len(dev_tokens) == 1 and criteria['value'] in friendly_name:
                         # Single word match
                         pass

                if match_found:
                    key = criteria['value'] # Use the search value as key
                    if key not in matches:
                        matches[key] = {
                            "name": state.get('attributes', {}).get('friendly_name', entity_id),
                            "entities": [],
                            "score_bonus": score_bonus,
                            "device_name": criteria['device_name']
                        }
                    
                    matches[key]["entities"].append({
                        "entity_id": entity_id,
                        "friendly_name": state.get('attributes', {}).get('friendly_name', ''),
                        "domain": entity_id.split('.')[0],
                        "state": state.get('state'),
                        "attributes": state.get('attributes', {})
                    })

        if not matches:
            logger.warning(f"DEBUG: No matching HA entity found")
            
            # Erstelle detaillierte Fehlermeldung
            mac_searched = None
            for c in search_criteria:
                if c['type'] == 'mac':
                    mac_searched = c['value']
                    break
            
            error_msg = "Kein passendes BTHome/Shelly Gerät in Home Assistant gefunden"
            if mac_searched:
                error_msg += f" (MAC: ...{mac_searched})"
            
            # Add available devices to the response for debugging/selection
            available_list = []
            for name, data in available_devices.items():
                # Pick the first entity to show ID
                first_entity = data['entities'][0]['entity_id'] if data['entities'] else "unknown"
                available_list.append({
                    "name": name,
                    "id": first_entity
                })
                
            return jsonify({
                "success": False, 
                "error": error_msg,
                "available_devices": available_list
            })

        # Select best match (prioritize binary_sensor for contact)
        candidates = []
        
        for key, data in matches.items():
            score = data['score_bonus']
            has_binary = any(e['domain'] == 'binary_sensor' for e in data['entities'])
            has_battery = any('battery' in e['entity_id'] or 'battery' in e['friendly_name'].lower() for e in data['entities'])
            
            if has_binary: score += 10
            if has_battery: score += 1
            
            # Store candidate with score
            candidates.append({
                "key": key,
                "score": score,
                "data": data
            })
            
        # Sort candidates by score descending
        candidates.sort(key=lambda x: x['score'], reverse=True)
        
        if not candidates:
             return jsonify({"success": False, "error": "Keine geeigneten Kandidaten gefunden"})

        # If we have multiple good candidates (score > 10), return them all
        # Or if the top 2 have similar scores
        top_candidates = [c for c in candidates if c['score'] >= 10]
        if not top_candidates:
            top_candidates = candidates[:1] # Fallback to best one
            
        # If we have multiple candidates, we might want to let the user choose
        # But for now, let's just return the best one, but include others in the response
        
        best_candidate = candidates[0]
        best_key = best_candidate['key']
        best_score = best_candidate['score']
        
        result = matches[best_key]
        logger.info(f"DEBUG: Selected best match {best_key} with score {best_score}")
        
        # 5. Sibling Search (Expand Device)
        # Try to find other entities that belong to the same device based on ID/Name similarity
        
        final_entities = {e['entity_id']: e for e in result['entities']} # Use dict to avoid duplicates
        
        # Use the "best" entity from the group to find siblings (prefer binary_sensor)
        best_entity = next((e for e in result['entities'] if e['domain'] == 'binary_sensor'), result['entities'][0])
        
        # Strategy 1: Entity ID Prefix
        # binary_sensor.kitchen_window_contact -> kitchen_window
        entity_id_parts = best_entity['entity_id'].split('.')
        if len(entity_id_parts) == 2:
            obj_id = entity_id_parts[1]
            # Common suffixes to strip
            suffixes = ['_contact', '_battery', '_temperature', '_humidity', '_illuminance', '_lux', 
                        '_pressure', '_power', '_energy', '_voltage', '_current', '_opening', 
                        '_motion', '_occupancy', '_vibration', '_tilt', '_rotation', '_state', '_status',
                        '_window', '_door', '_button']
            
            base_id = obj_id
            for suffix in suffixes:
                if base_id.endswith(suffix):
                    base_id = base_id[:-len(suffix)]
                    break
            
            # If base_id is too short (e.g. just "sensor"), ignore
            if len(base_id) > 3:
                logger.info(f"DEBUG: Searching siblings for base_id: {base_id}")
                for eid, state in ha_states.items():
                    # NUR BTHome/Shelly BLU Sensoren!
                    if not ('bthome' in eid.lower() or 'shelly_blu' in eid.lower()):
                        continue
                    if base_id in eid and eid not in final_entities:
                         final_entities[eid] = {
                            "entity_id": eid,
                            "friendly_name": state.get('attributes', {}).get('friendly_name', ''),
                            "domain": eid.split('.')[0],
                            "state": state.get('state'),
                            "attributes": state.get('attributes', {})
                        }

        # Strategy 2: Friendly Name Prefix
        # "Kitchen Window Contact" -> "Kitchen Window"
        friendly_name = best_entity['friendly_name']
        if friendly_name:
            name_suffixes = [' Contact', ' Battery', ' Temperature', ' Humidity', ' Illuminance', 
                             ' Lux', ' Power', ' Energy', ' Opening', ' Motion', ' Occupancy', 
                             ' Vibration', ' Tilt', ' Rotation', ' Status', ' State',
                             ' Window', ' Door', ' Button']
            
            base_name = friendly_name
            for suffix in name_suffixes:
                if base_name.lower().endswith(suffix.lower()):
                    base_name = base_name[:-len(suffix)]
                    break
            
            if len(base_name) > 3 and base_name != friendly_name:
                 logger.info(f"DEBUG: Searching siblings for base_name: {base_name}")
                 for eid, state in ha_states.items():
                    # NUR BTHome/Shelly BLU Sensoren!
                    if not ('bthome' in eid.lower() or 'shelly_blu' in eid.lower()):
                        continue
                    f_name = state.get('attributes', {}).get('friendly_name', '')
                    if base_name.lower() in f_name.lower() and eid not in final_entities:
                         final_entities[eid] = {
                            "entity_id": eid,
                            "friendly_name": f_name,
                            "domain": eid.split('.')[0],
                            "state": state.get('state'),
                            "attributes": state.get('attributes', {})
                        }
        
        # Prepare list of alternative candidates for frontend
        alternatives = []
        for c in candidates:
            if c['key'] != best_key:
                alternatives.append({
                    "device_name": c['data']['device_name'],  # Use Homey device name, not HA friendly_name
                    "score": c['score'],
                    "entities": c['data']['entities'] # Note: These are not expanded with siblings yet
                })

        return jsonify({
            "success": True,
            "device_name": result["device_name"],  # Homey device name
            "ha_friendly_name": result["name"],    # HA friendly name
            "entities": list(final_entities.values()),
            "alternatives": alternatives
        })

    except Exception as e:
        logger.error(f"Error finding device for room: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

