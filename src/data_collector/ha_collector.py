"""Home Assistant Datensammler"""

import requests
from typing import Dict, List, Any, Optional
from loguru import logger
from datetime import datetime

from .base_collector import SmartHomeCollector


class HomeAssistantCollector(SmartHomeCollector):
    """Sammelt Daten von Home Assistant via REST API"""

    def __init__(self, url: str, token: str):
        self.url = url.rstrip('/')
        self.token = token
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    def _make_request(self, endpoint: str, method: str = "GET", data: Dict = None) -> Optional[Any]:
        """Macht einen API-Request zu Home Assistant"""
        try:
            url = f"{self.url}/api/{endpoint}"

            if method == "GET":
                response = requests.get(url, headers=self.headers, timeout=10)
            elif method == "POST":
                response = requests.post(url, headers=self.headers, json=data, timeout=10)
            else:
                raise ValueError(f"Unsupported method: {method}")

            response.raise_for_status()
            return response.json()

        except requests.exceptions.RequestException as e:
            logger.error(f"Home Assistant API error: {e}")
            return None

    def get_state(self, entity_id: str) -> Optional[Dict]:
        """Holt den Zustand einer Entity"""
        result = self._make_request(f"states/{entity_id}")

        if result:
            return {
                'entity_id': result.get('entity_id'),
                'state': result.get('state'),
                'attributes': result.get('attributes', {}),
                'last_changed': result.get('last_changed'),
                'last_updated': result.get('last_updated')
            }
        return None

    def get_states(self, entity_ids: List[str] = None) -> Dict[str, Dict]:
        """Holt mehrere Entity States"""
        all_states = self._make_request("states")

        if not all_states:
            return {}

        if entity_ids:
            # Filter für spezifische Entities
            return {
                state['entity_id']: {
                    'state': state.get('state'),
                    'attributes': state.get('attributes', {}),
                    'last_changed': state.get('last_changed')
                }
                for state in all_states
                if state['entity_id'] in entity_ids
            }
        else:
            # Alle States zurückgeben
            return {
                state['entity_id']: {
                    'state': state.get('state'),
                    'attributes': state.get('attributes', {}),
                    'last_changed': state.get('last_changed')
                }
                for state in all_states
            }

    def call_service(self, domain: str, service: str, entity_id: str, **kwargs) -> bool:
        """
        Ruft einen Home Assistant Service auf
        Beispiel: call_service('light', 'turn_on', 'light.living_room', brightness=255)
        """
        data = {
            'entity_id': entity_id,
            **kwargs
        }

        result = self._make_request(
            f"services/{domain}/{service}",
            method="POST",
            data=data
        )

        if result is not None:
            logger.info(f"Service called: {domain}.{service} on {entity_id}")
            return True

        logger.error(f"Failed to call service: {domain}.{service}")
        return False

    def turn_on(self, entity_id: str, **kwargs) -> bool:
        """Schaltet ein Device ein"""
        domain = entity_id.split('.')[0]
        return self.call_service(domain, 'turn_on', entity_id, **kwargs)

    def turn_off(self, entity_id: str) -> bool:
        """Schaltet ein Device aus"""
        domain = entity_id.split('.')[0]
        return self.call_service(domain, 'turn_off', entity_id)

    def set_temperature(self, entity_id: str, temperature: float) -> bool:
        """Setzt die Zieltemperatur für Heizung/Klima"""
        return self.call_service(
            'climate',
            'set_temperature',
            entity_id,
            temperature=temperature
        )

    def set_hvac_mode(self, entity_id: str, hvac_mode: str) -> bool:
        """
        Setzt den HVAC-Modus (heat, cool, auto, off)
        """
        return self.call_service(
            'climate',
            'set_hvac_mode',
            entity_id,
            hvac_mode=hvac_mode
        )

    def get_sensor_history(self, entity_id: str, hours_back: int = 24) -> List[Dict]:
        """
        Holt die Historie eines Sensors
        Hinweis: Benötigt dass die Recorder-Integration in HA aktiv ist
        """
        from datetime import timedelta

        end_time = datetime.now()
        start_time = end_time - timedelta(hours=hours_back)

        # Format: YYYY-MM-DDTHH:MM:SS
        start_str = start_time.strftime('%Y-%m-%dT%H:%M:%S')

        endpoint = f"history/period/{start_str}?filter_entity_id={entity_id}"
        result = self._make_request(endpoint)

        if result and len(result) > 0:
            return [
                {
                    'state': item.get('state'),
                    'last_changed': item.get('last_changed'),
                    'attributes': item.get('attributes', {})
                }
                for item in result[0]
            ]

        return []

    def test_connection(self) -> bool:
        """Testet die Verbindung zu Home Assistant"""
        logger.debug(f"Testing HA connection to {self.url}")
        logger.debug(f"Token length: {len(self.token) if self.token else 0}")
        
        result = self._make_request("")

        if result and 'message' in result:
            logger.info(f"Home Assistant connected: {result['message']}")
            return True

        logger.error("Failed to connect to Home Assistant")
        return False

    def get_all_entities(self, domain: str = None) -> List[str]:
        """
        Holt alle Entity-IDs, optional gefiltert nach Domain
        Domain Beispiele: 'light', 'sensor', 'climate', 'switch'
        """
        all_states = self._make_request("states")

        if not all_states:
            return []

        entity_ids = [state['entity_id'] for state in all_states]

        if domain:
            entity_ids = [eid for eid in entity_ids if eid.startswith(f"{domain}.")]

        return entity_ids

    def get_all_devices(self) -> List[Dict]:
        """
        Holt alle Entities mit ihren vollständigen Informationen
        Kompatibilitätsmethode für Multi-Platform Support

        Returns:
            Liste von Entity-Dictionaries mit allen Informationen
        """
        all_states = self._make_request("states")

        if not all_states:
            return []

        devices = []
        for state in all_states:
            device = {
                'id': state.get('entity_id'),
                'name': state.get('attributes', {}).get('friendly_name', state.get('entity_id')),
                'zone': state.get('attributes', {}).get('area_id', 'Unknown'),
                'class': state.get('entity_id').split('.')[0],  # domain as class
                'virtualClass': None,
                'capabilities': [state.get('entity_id').split('.')[0]],
                'capabilitiesObj': {},
                'available': state.get('state') not in ['unavailable', 'unknown'],
                'state': state.get('state'),
                'attributes': state.get('attributes', {}),
                'last_changed': state.get('last_changed'),
                'last_updated': state.get('last_updated')
            }
            devices.append(device)

        logger.debug(f"Fetched {len(devices)} entities from Home Assistant")
        return devices
