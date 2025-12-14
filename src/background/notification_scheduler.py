"""
Background Task: Geplante Benachrichtigungen (Morgenzusammenfassung etc.)

Sendet automatisch Benachrichtigungen zu festgelegten Zeiten:
- Morgenzusammenfassung
- Tägliche Energieberichte
- Geplante Erinnerungen
"""

import threading
import time
import json
from datetime import datetime, timedelta
from typing import Dict, Optional, Any, List, TYPE_CHECKING
from pathlib import Path

if TYPE_CHECKING:
    from src.decision_engine.engine import DecisionEngine

import yaml
import requests
from loguru import logger

from src.utils.notifications import NotificationService
from src.data_collector.weather_collector import WeatherCollector


class NotificationScheduler:
    """Scheduler für geplante Benachrichtigungen"""
    
    def __init__(self, engine: Optional["DecisionEngine"] = None, check_interval: int = 60):
        """
        Args:
            engine: DecisionEngine Instanz für Klimadaten
            check_interval: Prüf-Intervall in Sekunden (default: 60)
        """
        self.engine = engine
        self.check_interval = check_interval
        self.running = False
        self.thread = None
        
        # Tracke bereits gesendete Benachrichtigungen (pro Tag)
        self._sent_today: Dict[str, str] = {}  # event_type -> date_sent
        
        logger.info(f"Notification Scheduler initialized ({check_interval}s interval)")
    
    @property
    def _platform(self) -> Any:
        """Sicherer Zugriff auf die Plattform"""
        if self.engine and self.engine.platform:
            return self.engine.platform
        return None

    def _load_notification_config(self) -> dict:
        """Lade Benachrichtigungs-Konfiguration aus config.yaml"""
        config_path = Path('config/config.yaml')
        if config_path.exists():
            try:
                with open(config_path, 'r') as f:
                    full_config = yaml.safe_load(f) or {}
                    return full_config.get('notifications', {})
            except Exception as e:
                logger.error(f"Error loading notification config: {e}")
        return {}
    
    def _get_notification_service(self) -> NotificationService:
        """Erstellt NotificationService mit aktueller Config"""
        config = self._load_notification_config()
        return NotificationService({"notifications": config})

    def start(self):
        """Startet den Scheduler"""
        if self.running:
            logger.warning("Notification Scheduler is already running")
            return

        self.running = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        logger.info(f"Notification Scheduler started (checks every {self.check_interval}s)")

    def stop(self):
        """Stoppt den Scheduler"""
        if not self.running:
            return

        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
        logger.info("Notification Scheduler stopped")

    def _run(self):
        """Haupt-Loop"""
        while self.running:
            try:
                self._check_scheduled_notifications()
            except Exception as e:
                logger.error(f"Error in notification scheduler: {e}")
            
            time.sleep(self.check_interval)

    def _check_scheduled_notifications(self):
        """Prüft und sendet geplante Benachrichtigungen"""
        config = self._load_notification_config()
        events = config.get('events', {})
        
        now = datetime.now()
        today = now.strftime('%Y-%m-%d')
        current_time = now.strftime('%H:%M')
        
        # Reset Tracking um Mitternacht
        if self._sent_today and list(self._sent_today.values())[0] != today:
            self._sent_today = {}
            logger.debug("Reset daily notification tracking")
        
        # === Morgenzusammenfassung ===
        morning_config = events.get('morning_summary', {})
        if morning_config.get('enabled'):
            scheduled_time = morning_config.get('time', '07:00')
            
            # Prüfe ob Zeit erreicht und heute noch nicht gesendet
            if self._should_send_at_time(scheduled_time, 'morning_summary', today):
                self._send_morning_summary(config)
    
    def _should_send_at_time(self, scheduled_time: str, event_type: str, today: str) -> bool:
        """Prüft ob eine Benachrichtigung gesendet werden soll"""
        # Bereits heute gesendet?
        if self._sent_today.get(event_type) == today:
            return False
        
        try:
            now = datetime.now()
            scheduled_hour, scheduled_minute = map(int, scheduled_time.split(':'))
            
            # Prüfe ob aktuelle Zeit im Fenster liegt (scheduled_time bis scheduled_time + 2 Min)
            scheduled = now.replace(hour=scheduled_hour, minute=scheduled_minute, second=0, microsecond=0)
            window_end = scheduled + timedelta(minutes=2)
            
            if scheduled <= now <= window_end:
                return True
                
        except Exception as e:
            logger.error(f"Error parsing scheduled time '{scheduled_time}': {e}")
        
        return False

    def _send_morning_summary(self, config: dict):
        """Sendet die Morgenzusammenfassung"""
        logger.info("Sending morning summary notification...")
        
        try:
            # Sammle Daten für die Zusammenfassung
            context = self._collect_morning_data()
            
            service = self._get_notification_service()
            style = config.get('chatgpt_style', 'freundlich')
            
            # Sende mit ChatGPT wenn aktiviert
            success = service.send_smart_notification(
                event_type='morning_summary',
                context=context,
                style=style,
                use_chatgpt=service.openai_enabled
            )
            
            if success:
                self._sent_today['morning_summary'] = datetime.now().strftime('%Y-%m-%d')
                logger.info("✅ Morning summary sent successfully")
            else:
                logger.error("❌ Failed to send morning summary")
                
        except Exception as e:
            logger.error(f"Error sending morning summary: {e}")

    def _collect_morning_data(self) -> Dict[str, Any]:
        """Sammelt Daten für die Morgenzusammenfassung"""
        context = {
            'avg_indoor_temp': None,
            'outdoor_temp': None,
            'weather': 'unbekannt',
            'open_windows': 0,
            'humidity_avg': None,
            'co2_max': None,
            'co2_max_room': None,
            'heating_active': False,
            'energy_tip': None,
            # Wettervorhersage
            'forecast_high': None,
            'forecast_low': None,
            'rain_probability': None,
            'weather_forecast': None,
            'forecast_description': None
        }
        
        try:
            platform = self._platform
            if not platform:
                return context
            
            # Hole alle Geräte
            if hasattr(platform, '_device_cache'):
                platform._refresh_device_cache()
                devices = list(platform._device_cache.values()) if isinstance(
                    platform._device_cache, dict) else platform._device_cache
            else:
                devices = platform.get_states() or []
            
            # Hole Zone-Mapping
            zones = {}
            try:
                zone_list = platform.get_zones() or []
                zones = {z.get('id'): z.get('name') for z in zone_list}
            except:
                pass
            
            indoor_temps = []
            humidities = []
            co2_values = []
            open_windows_count = 0
            
            for device in devices:
                if not isinstance(device, dict):
                    continue
                
                device_name = device.get('name', '').lower()
                caps = device.get('capabilitiesObj', {})
                zone_id = device.get('zone')
                room_name = zones.get(zone_id, '')
                
                # Außentemperatur
                if any(kw in device_name for kw in ['außen', 'outdoor', 'aussen', 'garten', 'balkon']):
                    if 'measure_temperature' in caps:
                        val = caps['measure_temperature'].get('value')
                        if val is not None:
                            context['outdoor_temp'] = round(val, 1)
                    continue
                
                # Innentemperatur
                if 'measure_temperature' in caps:
                    val = caps['measure_temperature'].get('value')
                    if val is not None and -10 < val < 50:
                        indoor_temps.append(val)
                
                # Luftfeuchtigkeit
                if 'measure_humidity' in caps:
                    val = caps['measure_humidity'].get('value')
                    if val is not None and 0 <= val <= 100:
                        humidities.append(val)
                
                # CO2
                if 'measure_co2' in caps:
                    val = caps['measure_co2'].get('value')
                    if val is not None and 200 < val < 10000:
                        co2_values.append((val, room_name or device.get('name', 'Unbekannt')))
                
                # Offene Fenster
                if 'fenster' in device_name or 'window' in device_name:
                    if 'alarm_contact' in caps:
                        if caps['alarm_contact'].get('value'):
                            open_windows_count += 1
                
                # Heizung aktiv?
                if 'target_temperature' in caps:
                    target = caps['target_temperature'].get('value')
                    current = caps.get('measure_temperature', {}).get('value')
                    if target and current and target > current + 0.5:
                        context['heating_active'] = True
            
            # Berechne Durchschnitte
            if indoor_temps:
                context['avg_indoor_temp'] = round(sum(indoor_temps) / len(indoor_temps), 1)
            
            if humidities:
                context['humidity_avg'] = round(sum(humidities) / len(humidities), 0)
            
            if co2_values:
                max_co2 = max(co2_values, key=lambda x: x[0])
                context['co2_max'] = max_co2[0]
                context['co2_max_room'] = max_co2[1]
            
            context['open_windows'] = open_windows_count
            
            # Wetter-Beschreibung basierend auf Außentemperatur
            if context['outdoor_temp'] is not None:
                temp = context['outdoor_temp']
                if temp < 0:
                    context['weather'] = 'frostig'
                elif temp < 5:
                    context['weather'] = 'kalt'
                elif temp < 10:
                    context['weather'] = 'kühl'
                elif temp < 15:
                    context['weather'] = 'mild'
                elif temp < 20:
                    context['weather'] = 'angenehm'
                elif temp < 25:
                    context['weather'] = 'warm'
                else:
                    context['weather'] = 'heiß'
            
            # Energie-Tipp generieren
            if context['heating_active'] and context['outdoor_temp'] and context['outdoor_temp'] > 12:
                context['energy_tip'] = 'Heizung läuft, aber es wird heute mild. Vielleicht runterdrehen?'
            elif context['co2_max'] and context['co2_max'] > 1000:
                context['energy_tip'] = f'Hoher CO2-Wert im {context["co2_max_room"]} - morgens kurz lüften!'
            elif context['humidity_avg'] and context['humidity_avg'] > 65:
                context['energy_tip'] = 'Luftfeuchtigkeit etwas hoch - regelmäßig lüften.'
            
            # Wettervorhersage von OpenWeatherMap holen
            self._add_weather_forecast(context)
            
        except Exception as e:
            logger.error(f"Error collecting morning data: {e}")
        
        return context

    def _add_weather_forecast(self, context: Dict[str, Any]) -> None:
        """Fügt Wettervorhersage zum Kontext hinzu"""
        try:
            weather_collector = WeatherCollector()
            
            # Prüfe ob API-Key konfiguriert ist
            if not weather_collector.api_key or weather_collector.api_key == 'YOUR_OPENWEATHERMAP_API_KEY':
                logger.info("⚠️ OpenWeatherMap API-Key nicht konfiguriert - keine Wettervorhersage")
                return
            
            # Aktuelle Wetterdaten
            current_weather = weather_collector.get_openweathermap_data()
            if current_weather:
                logger.debug(f"Current weather: {current_weather}")
                # Wetter-Beschreibung von der API nutzen (statt nur Temperatur-basiert)
                if current_weather.get('weather_description'):
                    context['weather'] = current_weather['weather_description']
                if current_weather.get('weather_condition'):
                    context['weather_condition'] = current_weather['weather_condition']
                    
                # Außentemperatur von API wenn nicht von Sensoren
                if context['outdoor_temp'] is None and current_weather.get('temperature'):
                    context['outdoor_temp'] = round(current_weather['temperature'], 1)
            
            # Vorhersage für heute
            forecast = weather_collector.get_forecast()
            if forecast and forecast.get('forecasts'):
                forecasts: List[Dict] = forecast['forecasts']
                
                # Filtere nur die Vorhersagen für heute (nächste 24 Stunden)
                today = datetime.now().date()
                today_forecasts = []
                
                for fc in forecasts:
                    try:
                        fc_time = datetime.fromisoformat(fc['timestamp'].replace('Z', '+00:00'))
                        if fc_time.date() == today or (fc_time.date() == today + timedelta(days=1) and fc_time.hour < 6):
                            today_forecasts.append(fc)
                    except:
                        continue
                
                if today_forecasts:
                    # Temperaturen für heute
                    temps = [fc['temperature'] for fc in today_forecasts if fc.get('temperature') is not None]
                    if temps:
                        context['forecast_high'] = round(max(temps), 0)
                        context['forecast_low'] = round(min(temps), 0)
                    
                    # Regenwahrscheinlichkeit (Maximum über den Tag)
                    rain_probs = [fc['rain_probability'] for fc in today_forecasts if fc.get('rain_probability') is not None]
                    if rain_probs:
                        context['rain_probability'] = round(max(rain_probs), 0)  # Bereits als Prozent vom Collector
                    
                    # Wetter-Vorhersage Beschreibung
                    weather_conditions = [fc['weather'] for fc in today_forecasts if fc.get('weather')]
                    if weather_conditions:
                        # Zähle Wetterbedingungen
                        from collections import Counter
                        weather_counter = Counter(weather_conditions)
                        most_common = weather_counter.most_common(1)[0][0]
                        context['weather_forecast'] = most_common
                        
                        # Erstelle Zusammenfassung
                        forecast_parts = []
                        
                        # Temperatur
                        if context['forecast_high'] is not None and context['forecast_low'] is not None:
                            if context['forecast_high'] == context['forecast_low']:
                                forecast_parts.append(f"ca. {int(context['forecast_high'])}°C")
                            else:
                                forecast_parts.append(f"{int(context['forecast_low'])}°C bis {int(context['forecast_high'])}°C")
                        
                        # Regen
                        if context['rain_probability'] is not None:
                            if context['rain_probability'] >= 70:
                                forecast_parts.append(f"Regen wahrscheinlich ({int(context['rain_probability'])}%)")
                            elif context['rain_probability'] >= 40:
                                forecast_parts.append(f"Regen möglich ({int(context['rain_probability'])}%)")
                            elif context['rain_probability'] >= 20:
                                forecast_parts.append(f"leichte Regenwahrscheinlichkeit ({int(context['rain_probability'])}%)")
                        
                        # Wetterbeschreibung
                        weather_desc_map = {
                            'Clear': 'Sonnig',
                            'Clouds': 'Bewölkt',
                            'Rain': 'Regnerisch',
                            'Drizzle': 'Nieselregen',
                            'Thunderstorm': 'Gewitter',
                            'Snow': 'Schnee',
                            'Mist': 'Neblig',
                            'Fog': 'Neblig',
                            'Haze': 'Diesig'
                        }
                        
                        weather_de = weather_desc_map.get(most_common, most_common or 'Unbekannt')
                        forecast_parts.insert(0, weather_de)
                        
                        context['forecast_description'] = ', '.join(forecast_parts)
                
                logger.debug(f"Weather forecast added: {context.get('forecast_description')}")
                
        except Exception as e:
            logger.warning(f"Could not fetch weather forecast: {e}")

    def get_status(self) -> dict:
        """Gibt den aktuellen Status zurück"""
        config = self._load_notification_config()
        events = config.get('events', {})
        
        return {
            'running': self.running,
            'check_interval': self.check_interval,
            'sent_today': self._sent_today,
            'scheduled_events': {
                'morning_summary': {
                    'enabled': events.get('morning_summary', {}).get('enabled', False),
                    'time': events.get('morning_summary', {}).get('time', '07:00'),
                    'sent_today': 'morning_summary' in self._sent_today
                }
            }
        }

    def send_morning_summary_now(self) -> bool:
        """Sendet die Morgenzusammenfassung sofort (für manuellen Test)"""
        config = self._load_notification_config()
        
        try:
            context = self._collect_morning_data()
            
            # Debug: Zeige gesammelte Daten
            logger.info(f"📊 Morning data collected: indoor={context.get('avg_indoor_temp')}°C, "
                       f"outdoor={context.get('outdoor_temp')}°C, "
                       f"forecast={context.get('forecast_description')}, "
                       f"rain={context.get('rain_probability')}%")
            
            service = self._get_notification_service()
            style = config.get('chatgpt_style', 'freundlich')
            
            success = service.send_smart_notification(
                event_type='morning_summary',
                context=context,
                style=style,
                use_chatgpt=service.openai_enabled
            )
            
            return success
            
        except Exception as e:
            logger.error(f"Error sending morning summary: {e}")
            return False
