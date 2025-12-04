"""
API Blueprint für Home Assistant Entitäten-Verwaltung
"""

import json
import logging
from pathlib import Path
from flask import Blueprint, jsonify, request, current_app
from datetime import datetime

logger = logging.getLogger(__name__)

ha_entities_bp = Blueprint('api_ha_entities', __name__)

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


def init_ha_entities_blueprint(app):
    """Initialisiert den Blueprint - nichts zu initialisieren, Blueprint wird in app.py registriert"""
    logger.info("HA Entities Blueprint bereit")
