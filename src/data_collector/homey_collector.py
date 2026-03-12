"""Homey Pro Datensammler"""

import requests
from typing import Dict, List, Optional, Any
from loguru import logger
from datetime import datetime

from .base_collector import SmartHomeCollector


class HomeyCollector(SmartHomeCollector):
    """
    Sammelt Daten von Homey Pro via Web API
    API Dokumentation: https://api.developer.homey.app/
    """

    def __init__(self, url: str, token: str):
        """
        Args:
            url: Homey Cloud API URL oder lokale IP (https://api.athom.com oder http://192.168.x.x)
            token: Bearer Token von Homey
        """
        self.url = url.rstrip('/')
        self.token = token
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        
        # Erkenne ob Cloud oder lokale API
        self.is_cloud_api = 'api.athom.com' in self.url
        
        # Wenn Cloud API ohne delegation path, extrahiere Homey ID aus Token
        if self.is_cloud_api and '/delegation/token/' not in self.url:
            logger.warning("Cloud API URL should include /delegation/token/{HOMEY_ID}")
            logger.info("Trying to use direct cloud API endpoints (may have limited functionality)")

        # Device-Cache für Performance
        self._device_cache = {}
        self._cache_timestamp = None

        # Circuit Breaker: Endpunkte die dauerhaft 401 zurückgeben überspringen
        self._endpoint_failures: Dict[str, int] = {}  # endpoint -> failure count
        self._endpoint_skip_until: Dict[str, datetime] = {}  # endpoint -> skip until

    def _make_request(self, endpoint: str, method: str = "GET",
                     data: Dict = None) -> Optional[Any]:
        """Macht einen API-Request zu Homey"""
        # Circuit Breaker: Endpunkt überspringen wenn er dauerhaft fehlschlägt
        skip_until = self._endpoint_skip_until.get(endpoint)
        if skip_until and datetime.now() < skip_until:
            logger.debug(f"Skipping {endpoint} (circuit open until {skip_until.strftime('%H:%M:%S')})")
            return None

        try:
            # Für Cloud API: verwende die korrekte URL-Struktur
            if self.is_cloud_api and '/delegation/token/' in self.url:
                url = f"{self.url}/{endpoint.lstrip('/')}"
            elif self.is_cloud_api:
                url = f"{self.url}/{endpoint.lstrip('/')}"
                logger.debug(f"Using direct cloud API endpoint: {endpoint}")
            else:
                url = f"{self.url}/{endpoint.lstrip('/')}"

            if method == "GET":
                response = requests.get(url, headers=self.headers, timeout=10)
            elif method == "POST":
                response = requests.post(url, headers=self.headers,
                                        json=data, timeout=10)
            elif method == "PUT":
                response = requests.put(url, headers=self.headers,
                                       json=data, timeout=10)
            else:
                raise ValueError(f"Unsupported method: {method}")

            # Bei Erfolg: Failure-Zähler zurücksetzen
            if endpoint in self._endpoint_failures:
                del self._endpoint_failures[endpoint]
            if endpoint in self._endpoint_skip_until:
                del self._endpoint_skip_until[endpoint]

            response.raise_for_status()
            return response.json()

        except requests.exceptions.HTTPError as e:
            status_code = e.response.status_code if e.response is not None else 0
            if status_code == 401:
                # 401: Berechtigungsfehler – Circuit Breaker aktivieren
                count = self._endpoint_failures.get(endpoint, 0) + 1
                self._endpoint_failures[endpoint] = count
                if count == 1:
                    logger.warning(f"Homey API 401 Unauthorized: {endpoint} (Token hat keine Berechtigung für diesen Endpunkt)")
                elif count == 3:
                    from datetime import timedelta
                    self._endpoint_skip_until[endpoint] = datetime.now() + timedelta(hours=1)
                    logger.warning(f"Homey API 401 für {endpoint} – Circuit Breaker aktiv, pausiere 1 Stunde")
                else:
                    logger.debug(f"Homey API 401: {endpoint} (Fehler #{count})")
            else:
                logger.error(f"Homey API error: {e}")
                if self.is_cloud_api and '/delegation/token/' not in self.url:
                    logger.error("Hint: For Homey Cloud, configure URL as: https://api.athom.com/delegation/token/YOUR_HOMEY_ID")
            return None

        except requests.exceptions.RequestException as e:
            logger.error(f"Homey API error: {e}")
            if self.is_cloud_api and '/delegation/token/' not in self.url:
                logger.error("Hint: For Homey Cloud, configure URL as: https://api.athom.com/delegation/token/YOUR_HOMEY_ID")
            return None

    def _refresh_device_cache(self):
        """Aktualisiert den Device-Cache"""
        devices = self._make_request("/api/manager/devices/device")

        if devices:
            self._device_cache = devices
            self._cache_timestamp = datetime.now()
            logger.debug(f"Device cache refreshed: {len(devices)} devices")
        else:
            logger.warning("No devices found")
            if self.is_cloud_api and '/delegation/token/' not in self.url:
                logger.warning("TIPP: Fuer Homey Cloud API, konfiguriere die URL so:")
                logger.warning("   url: https://api.athom.com/delegation/token/DEINE_HOMEY_ID")
                logger.warning("   (Homey ID findest du in der Homey App unter Einstellungen -> Allgemein)")

    def _get_device(self, device_id: str) -> Optional[Dict]:
        """Holt ein Device aus dem Cache oder API"""
        # Refresh cache wenn älter als 120 Sekunden (2 Minuten)
        if (not self._cache_timestamp or
            (datetime.now() - self._cache_timestamp).seconds > 120):
            self._refresh_device_cache()

        # Suche in Cache
        if isinstance(self._device_cache, dict):
            return self._device_cache.get(device_id)
        elif isinstance(self._device_cache, list):
            for device in self._device_cache:
                if device.get('id') == device_id:
                    return device

        return None

    def test_connection(self) -> bool:
        """Testet Verbindung zu Homey"""
        result = self._make_request("/api/manager/system/")

        if result:
            logger.info(f"Successfully connected to Homey: {result.get('cloudId', 'Homey')}")
            return True
        else:
            logger.error("Failed to connect to Homey")
            return False

    def get_state(self, entity_id: str) -> Optional[Dict]:
        """
        Holt den Status eines Homey Devices

        Args:
            entity_id: Device ID in Homey

        Returns:
            Normalisiertes State-Dictionary
        """
        device = self._get_device(entity_id)

        if not device:
            # Fallback: Direkt von API holen
            device = self._make_request(f"/api/manager/devices/device/{entity_id}")

        if not device:
            return None

        # Konvertiere Homey Format zu normalisiertem Format
        capabilities = device.get('capabilitiesObj', {})

        # Hauptstatus (on/off für Switches/Lights)
        main_state = 'unknown'
        if 'onoff' in capabilities:
            main_state = 'on' if capabilities['onoff'].get('value') else 'off'
        elif 'measure_temperature' in capabilities:
            main_state = str(capabilities['measure_temperature'].get('value', 'unknown'))
        elif 'target_temperature' in capabilities:
            main_state = str(capabilities['target_temperature'].get('value', 'unknown'))

        return {
            'entity_id': entity_id,
            'state': main_state,
            'attributes': {
                'friendly_name': device.get('name'),
                'device_class': device.get('class'),
                'zone': device.get('zone'),
                'capabilities': capabilities,
                'available': device.get('available', True)
            },
            'last_changed': device.get('lastUpdated'),
            'last_updated': device.get('lastUpdated')
        }

    def get_states(self, entity_ids: List[str] = None) -> Dict[str, Dict]:
        """Holt Status mehrerer Devices"""
        self._refresh_device_cache()

        states = {}

        devices_list = self._device_cache
        if isinstance(devices_list, dict):
            devices_list = list(devices_list.values())

        for device in devices_list:
            device_id = device.get('id')

            # Filter wenn spezifische IDs angegeben
            if entity_ids and device_id not in entity_ids:
                continue

            state = self.get_state(device_id)
            if state:
                states[device_id] = state

        return states

    def turn_on(self, entity_id: str, **kwargs) -> bool:
        """Schaltet ein Homey Device ein"""
        # Setze onoff capability auf true
        data = {"capability": "onoff", "value": True}

        # Brightness für Lampen
        if 'brightness' in kwargs:
            # Homey nutzt 0-1, nicht 0-255
            brightness = kwargs['brightness'] / 255.0
            dim_result = self._make_request(
                f"/api/manager/devices/device/{entity_id}/capability/dim",
                method="PUT",
                data={"value": brightness}
            )

        result = self._make_request(
            f"/api/manager/devices/device/{entity_id}/capability/onoff",
            method="PUT",
            data={"value": True}
        )

        if result is not None:
            logger.info(f"Turned on device: {entity_id}")
            return True

        return False

    def turn_off(self, entity_id: str) -> bool:
        """Schaltet ein Homey Device aus"""
        result = self._make_request(
            f"/api/manager/devices/device/{entity_id}/capability/onoff",
            method="PUT",
            data={"value": False}
        )

        if result is not None:
            logger.info(f"Turned off device: {entity_id}")
            return True

        return False

    def set_temperature(self, entity_id: str, temperature: float) -> bool:
        """Setzt Zieltemperatur für Homey Thermostat"""
        result = self._make_request(
            f"/api/manager/devices/device/{entity_id}/capability/target_temperature",
            method="PUT",
            data={"value": temperature}
        )

        if result is not None:
            logger.info(f"Set temperature {temperature}°C for {entity_id}")
            return True

        return False

    def set_hvac_mode(self, entity_id: str, hvac_mode: str) -> bool:
        """
        Setzt Homey Thermostat-Modus

        Homey nutzt andere Modi als Home Assistant:
        - 'heat', 'cool', 'auto', 'off' müssen gemappt werden
        """
        # Mapping zu Homey Modi
        mode_mapping = {
            'heat': 'heat',
            'cool': 'cool',
            'auto': 'auto',
            'off': 'off'
        }

        homey_mode = mode_mapping.get(hvac_mode.lower())

        if not homey_mode:
            logger.error(f"Unknown HVAC mode: {hvac_mode}")
            return False

        # Prüfe ob Device thermostat_mode capability hat
        device = self._get_device(entity_id)
        if not device:
            return False

        capabilities = device.get('capabilitiesObj', {})

        if 'thermostat_mode' in capabilities:
            result = self._make_request(
                f"/api/manager/devices/device/{entity_id}/capability/thermostat_mode",
                method="PUT",
                data={"value": homey_mode}
            )

            if result is not None:
                logger.info(f"Set HVAC mode {homey_mode} for {entity_id}")
                return True

        return False

    def get_all_devices(self) -> List[Dict]:
        """
        Holt alle Geräte mit ihren vollständigen Informationen

        Returns:
            Liste von Device-Dictionaries mit allen Capabilities und States
        """
        self._refresh_device_cache()

        devices_list = self._device_cache

        # Debug: Log the structure we're getting
        if devices_list:
            logger.debug(f"Device cache type: {type(devices_list)}")
            if isinstance(devices_list, dict) and devices_list:
                first_key = list(devices_list.keys())[0]
                first_value = devices_list[first_key]
                logger.debug(f"First device - key type: {type(first_key)}, value type: {type(first_value)}")

        if isinstance(devices_list, dict):
            devices_list = list(devices_list.values())
        elif not isinstance(devices_list, list):
            devices_list = []

        # Filter out non-dict items (safety check)
        original_count = len(devices_list)
        devices_list = [d for d in devices_list if isinstance(d, dict)]
        filtered_count = original_count - len(devices_list)

        if filtered_count > 0:
            logger.warning(f"Filtered out {filtered_count} non-dict items from device list")

        return devices_list

    def get_all_entities(self, domain: str = None) -> List[str]:
        """
        Holt alle Device-IDs

        Args:
            domain: Filter nach Device-Class (light, sensor, thermostat, etc.)
        """
        self._refresh_device_cache()

        devices_list = self._device_cache
        if isinstance(devices_list, dict):
            devices_list = list(devices_list.values())

        entity_ids = []

        # Mapping von Home Assistant Domains zu Homey Classes
        domain_mapping = {
            'light': ['light', 'socket'],
            'sensor': ['sensor', 'other'],
            'climate': ['thermostat', 'heater', 'radiator', 'boiler'],
            'switch': ['socket', 'switch'],
            'binary_sensor': ['sensor']
        }

        for device in devices_list:
            device_id = device.get('id')
            device_class = device.get('class', '').lower()
            capabilities = device.get('capabilitiesObj', {}) or {}

            if domain:
                # Filter nach Domain
                valid_classes = domain_mapping.get(domain, [])
                if device_class not in valid_classes:
                    # Fallback: Capability-basierte Erkennung für climate-Geräte
                    if domain == 'climate' and (
                        'target_temperature' in capabilities or
                        'thermostat_mode' in capabilities
                    ):
                        pass  # Trotzdem aufnehmen
                    # Fallback: temperature-Capability für sensor-Domain
                    elif domain == 'sensor' and 'measure_temperature' in capabilities:
                        pass  # Trotzdem aufnehmen
                    else:
                        continue

            entity_ids.append(device_id)

        return entity_ids

    def call_service(self, domain: str, service: str, entity_id: str, **kwargs) -> bool:
        """Generischer Service-Call"""
        if service == 'turn_on':
            return self.turn_on(entity_id, **kwargs)
        elif service == 'turn_off':
            return self.turn_off(entity_id)
        elif service == 'set_temperature':
            temp = kwargs.get('temperature')
            if temp:
                return self.set_temperature(entity_id, temp)
        elif service == 'set_hvac_mode':
            mode = kwargs.get('hvac_mode')
            if mode:
                return self.set_hvac_mode(entity_id, mode)

        logger.error(f"Unknown service: {domain}.{service}")
        return False

    def get_zones(self) -> Dict[str, Dict]:
        """
        Holt alle Homey Zones (Räume)
        Spezifisch für Homey
        """
        zones = self._make_request("/api/manager/zones/zone/")
        return zones if zones else {}

    def trigger_flow(self, flow_id: str) -> bool:
        """
        Triggert einen Homey Flow
        Spezifisch für Homey

        Hinweis: Flow-Triggering über API könnte eingeschränkt sein.
        Alternative: Nutze Logic Variables oder Virtual Devices als Trigger.
        """
        # Versuche Flow zu triggern (funktioniert möglicherweise nur mit Advanced Flows)
        result = self._make_request(
            f"/api/manager/flow/flow/{flow_id}/trigger",
            method="POST"
        )

        if result is not None:
            logger.info(f"Triggered flow: {flow_id}")
            return True

        logger.warning(f"Flow triggering may not be supported via REST API for flow {flow_id}")
        return False

    def get_weather_data(self) -> Optional[Dict]:
        """
        Sammelt Wetterdaten von Homey-Geräten
        Kombiniert: Temperatur/Luftfeuchtigkeit von Sensoren + DWD Warnungen
        """
        from datetime import datetime

        weather_data = {
            'timestamp': datetime.now().isoformat(),
            'source': 'homey',
            'temperature': None,
            'humidity': None,
            'warnings': [],
            'sensors': []
        }

        try:
            # Hole alle Sensoren und Thermostate
            devices = self._make_request("/api/manager/devices/device")
            if not devices:
                return None

            temperatures = []
            humidities = []

            for device_id, device in devices.items():
                capabilities = device.get('capabilitiesObj', {})

                # Sammle Temperatur-Messwerte (filtere unrealistische Werte)
                if 'measure_temperature' in capabilities:
                    temp_cap = capabilities['measure_temperature']
                    temp_value = temp_cap.get('value')
                    # Filtere offensichtlich fehlerhafte Werte (z.B. von Licht-Sensoren)
                    if temp_value is not None and -20 <= temp_value <= 40:
                        temperatures.append(temp_value)
                        weather_data['sensors'].append({
                            'name': device.get('name'),
                            'temperature': temp_value,
                            'zone': device.get('zone')
                        })

                # Sammle Luftfeuchtigkeit
                if 'measure_humidity' in capabilities:
                    humid_cap = capabilities['measure_humidity']
                    humid_value = humid_cap.get('value')
                    if humid_value is not None:
                        humidities.append(humid_value)

                # Sammle DWD Wetterwarnungen
                if device.get('driverUri') == 'homey:app:de.ronnywinkler.homey.dwdwarnings':
                    warnings_cap = capabilities.get('measure_warnings', {})
                    if warnings_cap.get('value'):
                        weather_data['warnings'].append({
                            'location': device.get('name'),
                            'warnings': warnings_cap.get('value'),
                            'level': capabilities.get('measure_highest_level', {}).get('value'),
                            'count': capabilities.get('measure_number_of_warnings', {}).get('value')
                        })

            # Berechne Durchschnittswerte
            if temperatures:
                weather_data['temperature'] = sum(temperatures) / len(temperatures)
                weather_data['temperature_sensors_count'] = len(temperatures)

            if humidities:
                weather_data['humidity'] = sum(humidities) / len(humidities)
                weather_data['humidity_sensors_count'] = len(humidities)

            logger.info(f"Weather data from Homey: {weather_data['temperature']}°C, {weather_data['humidity']}% humidity, {len(weather_data['warnings'])} warnings")
            return weather_data

        except Exception as e:
            error_msg = str(e).encode('ascii', 'ignore').decode('ascii')
            logger.error(f"Error getting weather data from Homey: {error_msg}")
            return None

    def get_presence_status(self) -> Dict:
        """
        Holt Anwesenheits-Status aus Homey
        Nutzt User-Presence (Smartphone-Tracking)

        Returns:
            {
                'anyone_home': bool,
                'users': [{'name': str, 'present': bool}],
                'total_users': int,
                'users_home': int
            }
        """
        try:
            users_data = self._make_request("/api/manager/users/user")

            if not users_data:
                return {
                    'anyone_home': False,
                    'users': [],
                    'total_users': 0,
                    'users_home': 0
                }

            users = []
            users_home = 0

            for user_id, user in users_data.items():
                name = user.get('name', 'Unknown')
                present = user.get('present', False)

                users.append({
                    'id': user_id,
                    'name': name,
                    'present': present
                })

                if present:
                    users_home += 1

            anyone_home = users_home > 0

            logger.info(f"Presence status: {users_home}/{len(users)} users home")

            return {
                'anyone_home': anyone_home,
                'users': users,
                'total_users': len(users),
                'users_home': users_home
            }

        except Exception as e:
            error_msg = str(e).encode('ascii', 'ignore').decode('ascii')
            logger.error(f"Error getting presence status: {error_msg}")
            return {
                'anyone_home': False,
                'users': [],
                'total_users': 0,
                'users_home': 0
            }

    def supports_capability(self, capability: str) -> bool:
        """Prüft Homey-spezifische Capabilities"""
        supported = [
            'basic_control',
            'state_query',
            'zones',
            'flows',
            'apps',
            'advanced_flows',
            'weather_data',
            'presence_detection'
        ]
        return capability in supported
