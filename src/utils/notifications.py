"""
Notification Service - Pushover + ChatGPT Integration

Sendet intelligente Benachrichtigungen mit KI-generierten Texten über Pushover.
"""

import os
import requests
from typing import Optional, Dict, Any, List
from datetime import datetime
from loguru import logger


class NotificationService:
    """Benachrichtigungsservice mit Pushover und optionaler ChatGPT-Textgenerierung"""
    
    def __init__(self, config: Optional[Dict] = None):
        """
        Args:
            config: Konfiguration mit pushover und openai Einstellungen
        """
        self.config = config or {}
        
        # Pushover Credentials (aus Config oder Umgebungsvariablen)
        notifications_config = self.config.get('notifications', {})
        pushover_config = notifications_config.get('pushover', {})
        
        self.pushover_token = pushover_config.get('api_token') or os.getenv('PUSHOVER_API_TOKEN')
        self.pushover_user = pushover_config.get('user_key') or os.getenv('PUSHOVER_USER_KEY')
        self.pushover_enabled = pushover_config.get('enabled', True) and bool(self.pushover_token and self.pushover_user)
        
        # OpenAI / ChatGPT Credentials
        openai_config = notifications_config.get('openai', {})
        self.openai_api_key = openai_config.get('api_key') or os.getenv('OPENAI_API_KEY')
        self.openai_enabled = openai_config.get('enabled', True) and bool(self.openai_api_key)
        self.openai_model = openai_config.get('model', 'gpt-4o-mini')
        self.max_text_length = notifications_config.get('max_text_length', 100)
        self.custom_prompt = notifications_config.get('custom_prompt', '')

        # Kosten-Begrenzung: Cache + Tageslimit
        # Cache: (event_type, cache_key) -> (text, timestamp)
        self._gpt_cache: Dict[str, tuple] = {}
        # Tageslimit: max. Anzahl ChatGPT-Aufrufe pro Tag (0 = unbegrenzt)
        self._gpt_daily_limit = openai_config.get('daily_call_limit', 10)
        self._gpt_calls_today = 0
        self._gpt_calls_date = datetime.now().date()
        # Cache-TTL: wie lange ein generierter Text wiederverwendet wird (Sekunden)
        self._gpt_cache_ttl = openai_config.get('cache_ttl_seconds', 3600)  # 1 Stunde default
        
        # Notification Preferences
        self.default_priority = notifications_config.get('default_priority', 0)
        self.quiet_hours_start = notifications_config.get('quiet_hours_start')  # z.B. "22:00"
        self.quiet_hours_end = notifications_config.get('quiet_hours_end')  # z.B. "07:00"
        
        if self.pushover_enabled:
            logger.info("✅ Pushover notifications enabled")
        else:
            logger.warning("⚠️ Pushover notifications disabled (missing credentials)")
            
        if self.openai_enabled:
            logger.info("✅ ChatGPT text generation enabled")
        else:
            logger.info("ℹ️ ChatGPT text generation disabled")
    
    def _is_quiet_hours(self) -> bool:
        """Prüft ob gerade Ruhezeit ist"""
        if not self.quiet_hours_start or not self.quiet_hours_end:
            return False
            
        try:
            now = datetime.now()
            current_time = now.hour * 60 + now.minute
            
            start_parts = self.quiet_hours_start.split(':')
            start_time = int(start_parts[0]) * 60 + int(start_parts[1])
            
            end_parts = self.quiet_hours_end.split(':')
            end_time = int(end_parts[0]) * 60 + int(end_parts[1])
            
            if start_time > end_time:
                # Über Mitternacht (z.B. 22:00 - 07:00)
                return current_time >= start_time or current_time < end_time
            else:
                return start_time <= current_time < end_time
        except:
            return False
    
    def generate_smart_text(self, event_type: str, context: Dict[str, Any], 
                            style: str = "freundlich") -> str:
        """
        Generiert einen intelligenten Text mit ChatGPT.
        
        Args:
            event_type: Art des Events (z.B. "window_open", "temperature_alert", "energy_tip")
            context: Kontext-Daten für die Textgenerierung
            style: Stil des Textes ("freundlich", "kurz", "technisch", "witzig")
            
        Returns:
            Generierter Text oder Fallback-Text
        """
        if not self.openai_enabled:
            return self._get_fallback_text(event_type, context)

        # Tageslimit zurücksetzen wenn neuer Tag
        today = datetime.now().date()
        if today != self._gpt_calls_date:
            self._gpt_calls_today = 0
            self._gpt_calls_date = today

        # Tageslimit prüfen
        if self._gpt_daily_limit > 0 and self._gpt_calls_today >= self._gpt_daily_limit:
            logger.info(f"ChatGPT daily limit ({self._gpt_daily_limit}) reached – using fallback text")
            return self._get_fallback_text(event_type, context)

        # Cache-Key aus Event-Typ + wichtigsten Kontext-Werten (Raum, grobe Temp)
        cache_key = self._build_cache_key(event_type, context)
        cached = self._gpt_cache.get(cache_key)
        if cached:
            cached_text, cached_at = cached
            age = (datetime.now() - cached_at).total_seconds()
            if age < self._gpt_cache_ttl:
                logger.debug(f"ChatGPT cache hit ({int(age)}s old): {cache_key}")
                return cached_text

        try:
            # Baue Prompt basierend auf Event-Typ
            system_prompt = self._build_system_prompt(style)
            user_prompt = self._build_user_prompt(event_type, context)

            response = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.openai_api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": self.openai_model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    "max_tokens": 200 if event_type == 'morning_summary' else 80,
                    "temperature": 0.7
                },
                timeout=10
            )

            if response.status_code == 200:
                data = response.json()
                generated_text = data['choices'][0]['message']['content'].strip()
                # Im Cache speichern + Zähler erhöhen
                self._gpt_cache[cache_key] = (generated_text, datetime.now())
                self._gpt_calls_today += 1
                logger.debug(f"ChatGPT generated ({self._gpt_calls_today}/{self._gpt_daily_limit or 'unlimited'}/day): {generated_text}")
                return generated_text
            else:
                logger.warning(f"OpenAI API error: {response.status_code}")
                return self._get_fallback_text(event_type, context)

        except Exception as e:
            logger.error(f"Error generating text with ChatGPT: {e}")
            return self._get_fallback_text(event_type, context)

    def _build_cache_key(self, event_type: str, context: Dict[str, Any]) -> str:
        """Baut einen Cache-Key aus Event-Typ und den wichtigsten Kontext-Werten.
        Temperatur wird auf ganze Grad gerundet damit ähnliche Werte den gleichen Key erzeugen."""
        room = str(context.get('room', context.get('window_name', '')))
        temp = context.get('current_temp') or context.get('indoor_temp')
        temp_rounded = str(round(temp)) if temp is not None else ''
        status = str(context.get('status', ''))
        return f"{event_type}:{room}:{temp_rounded}:{status}"
    
    def _build_system_prompt(self, style: str) -> str:
        """Baut den System-Prompt für ChatGPT (kurz gehalten um Input-Tokens zu sparen)"""
        styles = {
            "freundlich": "Kurze Smart-Home-Benachrichtigung auf Deutsch. Max 1-2 Sätze.",
            "kurz": "Sehr kurze Smart-Home-Meldung auf Deutsch. 1 Satz, kein Emoji.",
            "technisch": "Technische Smart-Home-Meldung auf Deutsch mit genauen Werten. Max 2 Sätze.",
            "witzig": "Witzige Smart-Home-Meldung auf Deutsch. Max 2 Sätze."
        }
        base_prompt = styles.get(style, styles["freundlich"])
        if self.custom_prompt:
            base_prompt += f" {self.custom_prompt}"
        return base_prompt
    
    def _build_user_prompt(self, event_type: str, context: Dict[str, Any]) -> str:
        """Baut den User-Prompt basierend auf Event-Typ"""
        prompts = {
            "window_open_long": f"""
                Fenster "{context.get('window_name', 'Fenster')}" ist seit {context.get('duration_minutes', '?')} Minuten offen.
                Außentemperatur: {context.get('outdoor_temp', '?')}°C
                Raumtemperatur: {context.get('indoor_temp', '?')}°C
                Erstelle eine Benachrichtigung die den Nutzer erinnert.
            """,
            
            "temperature_alert": f"""
                Temperaturwarnung im {context.get('room', 'Raum')}.
                Aktuelle Temperatur: {context.get('current_temp', '?')}°C
                Solltemperatur: {context.get('target_temp', '?')}°C
                Abweichung: {context.get('deviation', '?')}°C
                Erstelle eine passende Benachrichtigung.
            """,
            
            "humidity_alert": f"""
                Luftfeuchtigkeit im {context.get('room', 'Raum')} ist {context.get('status', 'auffällig')}.
                Aktuelle Feuchtigkeit: {context.get('humidity', '?')}%
                Empfohlener Bereich: 40-60%
                Erstelle eine Benachrichtigung mit Handlungsempfehlung.
            """,
            
            "co2_alert": f"""
                CO2-Wert im {context.get('room', 'Raum')} ist erhöht.
                Aktueller Wert: {context.get('co2', '?')} ppm
                Empfohlen: unter 1000 ppm
                Erstelle eine Lüftungsempfehlung.
            """,
            
            "ventilation_complete": f"""
                Lüftung im {context.get('room', 'Raum')} beendet.
                Dauer: {context.get('duration_minutes', '?')} Minuten
                Temperaturänderung: {context.get('temp_change', '?')}°C
                CO2-Reduktion: {context.get('co2_change', '?')} ppm
                Erstelle eine kurze Zusammenfassung.
            """,
            
            "energy_tip": f"""
                Energie-Spartipp für {context.get('room', 'dein Zuhause')}.
                Aktueller Verbrauch: {context.get('current_consumption', '?')} W
                Tipp-Kategorie: {context.get('tip_category', 'Allgemein')}
                Erstelle einen hilfreichen Energiespartipp.
            """,
            
            "morning_summary": f"""
                Morgenzusammenfassung für Smart Home:
                - Innentemperatur: {context.get('avg_indoor_temp', '?')}°C
                - Außentemperatur: {context.get('outdoor_temp', '?')}°C
                - Aktuelles Wetter: {context.get('weather', 'unbekannt')}
                - Wettervorhersage heute: {context.get('forecast_description', 'keine Vorhersage verfügbar')}
                - Höchsttemperatur heute: {context.get('forecast_high', '?')}°C
                - Tiefsttemperatur heute: {context.get('forecast_low', '?')}°C
                - Regenwahrscheinlichkeit: {context.get('rain_probability', '?')}%
                - Tageswetter 7–18 Uhr: Sonne={'Ja' if context.get('day_has_sun') else 'Nein'}, Regen={'Ja' if context.get('day_has_rain') else 'Nein'}, Starker Wind={'Ja' if context.get('day_has_strong_wind') else 'Nein'}
                - Tageshöchsttemperatur (7–18 Uhr): {context.get('day_max_temp', '?')}°C
                - Kleidungsempfehlung: {context.get('clothing_tip', 'keine')}
                - Sonnenschutz nötig: {'Ja – UV-Schutz empfohlen!' if context.get('sun_protection_needed') else 'Nein'}
                - Offene Fenster: {context.get('open_windows', 0)}
                - Luftfeuchtigkeit: {context.get('humidity_avg', '?')}%
                - Höchster CO2-Wert: {context.get('co2_max', '-')} ppm ({context.get('co2_max_room', '')})
                - Heizung aktiv: {'Ja' if context.get('heating_active') else 'Nein'}
                - Energie-Tipp: {context.get('energy_tip', 'keiner')}
                Erstelle eine freundliche, informative Morgen-Begrüßung mit Wettervorhersage für 7–18 Uhr.
                Erwähne ob man einen Regenschirm braucht, wie man sich kleiden sollte und ob Sonnenschutz nötig ist.
            """,
            
            "heating_recommendation": f"""
                Heizempfehlung für {context.get('room', 'Raum')}.
                Aktuelle Temperatur: {context.get('current_temp', '?')}°C
                Außentemperatur: {context.get('outdoor_temp', '?')}°C
                Empfohlene Aktion: {context.get('action', 'anpassen')}
                Begründung: {context.get('reason', '')}
                Erstelle eine kurze Empfehlung.
            """,
            
            "mold_risk": f"""
                Schimmelrisiko im {context.get('room', 'Raum')} erkannt!
                Luftfeuchtigkeit: {context.get('humidity', '?')}%
                Wandtemperatur: {context.get('wall_temp', '?')}°C
                Risikostufe: {context.get('risk_level', 'erhöht')}
                Erstelle eine Warnung mit Handlungsempfehlung.
            """,
            
            "device_status": f"""
                Gerätestatus-Update:
                Gerät: {context.get('device_name', 'Gerät')}
                Status: {context.get('status', 'geändert')}
                Details: {context.get('details', '')}
                Erstelle eine kurze Statusmeldung.
            """
        }
        
        return prompts.get(event_type, f"Erstelle eine Smart-Home-Benachrichtigung für: {event_type}. Kontext: {context}")
    
    def _get_fallback_text(self, event_type: str, context: Dict[str, Any]) -> str:
        """Fallback-Texte wenn ChatGPT nicht verfügbar"""
        
        # Erweiterte Morning Summary für Fallback
        def build_morning_fallback():
            parts = [f"☀️ Guten Morgen! Innen: {context.get('avg_indoor_temp', '?')}°C, Außen: {context.get('outdoor_temp', '?')}°C"]
            
            if context.get('forecast_description'):
                parts.append(f"Heute: {context.get('forecast_description')}")
            elif context.get('forecast_high') is not None:
                temp_part = f"Temperatur: {context.get('forecast_low', '?')}–{context.get('forecast_high', '?')}°C"
                if context.get('rain_probability') and context.get('rain_probability') >= 30:
                    temp_part += f" ☔ Regen: {int(context.get('rain_probability'))}%"
                parts.append(temp_part)
            
            # Wetter 7–18 Uhr
            weather_icons = []
            if context.get('day_has_sun'):
                weather_icons.append('☀️ Sonne')
            if context.get('day_has_rain'):
                weather_icons.append('🌧️ Regen')
            if context.get('day_has_strong_wind'):
                wind_str = f"💨 Starker Wind"
                if context.get('day_wind_max'):
                    wind_str += f" ({context.get('day_wind_max')} m/s)"
                weather_icons.append(wind_str)
            if weather_icons:
                parts.append(f"Tagsüber (7–18 Uhr): {', '.join(weather_icons)}")
            
            # Kleidung
            if context.get('clothing_tip'):
                parts.append(context.get('clothing_tip'))
            
            # Sonnenschutz
            if context.get('sun_protection_needed'):
                parts.append('🕶️ Sonnenschutz empfohlen!')
            
            if context.get('energy_tip'):
                parts.append(f"💡 {context.get('energy_tip')}")
            
            return ' | '.join(parts)
        
        fallbacks = {
            "window_open_long": f"🪟 {context.get('window_name', 'Fenster')} ist seit {context.get('duration_minutes', '?')} Min. offen. Außen: {context.get('outdoor_temp', '?')}°C",
            "temperature_alert": f"🌡️ {context.get('room', 'Raum')}: {context.get('current_temp', '?')}°C (Soll: {context.get('target_temp', '?')}°C)",
            "humidity_alert": f"💧 {context.get('room', 'Raum')}: Luftfeuchtigkeit {context.get('humidity', '?')}%",
            "co2_alert": f"🌬️ {context.get('room', 'Raum')}: CO2 bei {context.get('co2', '?')} ppm - Lüften empfohlen!",
            "ventilation_complete": f"✅ Lüftung {context.get('room', 'Raum')} beendet ({context.get('duration_minutes', '?')} Min.)",
            "energy_tip": f"💡 Energietipp: {context.get('tip_category', 'Sparen Sie Energie')}",
            "morning_summary": build_morning_fallback(),
            "heating_recommendation": f"🔥 {context.get('room', 'Raum')}: {context.get('action', 'Heizung anpassen')}",
            "mold_risk": f"⚠️ Schimmelrisiko {context.get('room', 'Raum')}! Feuchtigkeit: {context.get('humidity', '?')}%",
            "device_status": f"📱 {context.get('device_name', 'Gerät')}: {context.get('status', 'Status geändert')}"
        }
        
        return fallbacks.get(event_type, f"Smart Home Update: {event_type}")
    
    def send_notification(self, title: str, message: str, 
                         priority: int = None,
                         sound: str = None,
                         url: str = None,
                         url_title: str = None,
                         device: str = None,
                         html: bool = False) -> bool:
        """
        Sendet eine Pushover-Benachrichtigung.
        
        Args:
            title: Titel der Benachrichtigung
            message: Nachrichtentext
            priority: -2 bis 2 (default: 0)
                     -2: Keine Benachrichtigung, nur in App sichtbar
                     -1: Leise (kein Sound)
                      0: Normal
                      1: Hohe Priorität (umgeht Ruhezeit)
                      2: Notfall (erfordert Bestätigung)
            sound: Pushover-Sound (z.B. "pushover", "bike", "bugle", "cashregister", etc.)
            url: Optional: URL die beim Klicken geöffnet wird
            url_title: Titel für die URL
            device: Spezifisches Gerät (oder alle)
            html: HTML-Formatierung erlauben
            
        Returns:
            True bei Erfolg, False bei Fehler
        """
        if not self.pushover_enabled:
            logger.warning("Pushover not configured, notification not sent")
            return False
        
        # Ruhezeit prüfen (außer bei hoher Priorität)
        if priority is None:
            priority = self.default_priority
            
        if self._is_quiet_hours() and priority < 1:
            priority = -1  # Leise während Ruhezeit
        
        try:
            payload = {
                "token": self.pushover_token,
                "user": self.pushover_user,
                "title": title,
                "message": message,
                "priority": priority
            }
            
            if sound:
                payload["sound"] = sound
            if url:
                payload["url"] = url
            if url_title:
                payload["url_title"] = url_title
            if device:
                payload["device"] = device
            if html:
                payload["html"] = 1
            
            response = requests.post(
                "https://api.pushover.net/1/messages.json",
                data=payload,
                timeout=10
            )
            
            if response.status_code == 200:
                logger.info(f"✅ Pushover notification sent: {title}")
                return True
            else:
                logger.error(f"Pushover error: {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"Error sending Pushover notification: {e}")
            return False
    
    def send_notification_with_details(self, title: str, message: str, 
                                       priority: int = None,
                                       sound: str = None,
                                       url: str = None,
                                       url_title: str = None,
                                       device: str = None,
                                       html: bool = False) -> tuple[bool, str]:
        """
        Sendet eine Pushover-Benachrichtigung mit detaillierter Fehlerrückgabe.
        
        Returns:
            Tuple (success, error_message)
        """
        if not self.pushover_enabled:
            return False, "Pushover nicht konfiguriert oder deaktiviert"
        
        if priority is None:
            priority = self.default_priority
            
        if self._is_quiet_hours() and priority < 1:
            priority = -1
        
        try:
            payload = {
                "token": self.pushover_token,
                "user": self.pushover_user,
                "title": title,
                "message": message,
                "priority": priority
            }
            
            if sound:
                payload["sound"] = sound
            if url:
                payload["url"] = url
            if url_title:
                payload["url_title"] = url_title
            if device:
                payload["device"] = device
            if html:
                payload["html"] = 1
            
            response = requests.post(
                "https://api.pushover.net/1/messages.json",
                data=payload,
                timeout=10
            )
            
            if response.status_code == 200:
                logger.info(f"✅ Pushover notification sent: {title}")
                return True, None
            else:
                # Parse Pushover Error
                try:
                    error_data = response.json()
                    errors = error_data.get('errors', [])
                    if errors:
                        error_msg = ', '.join(errors)
                    else:
                        error_msg = f"HTTP {response.status_code}: {response.text}"
                except:
                    error_msg = f"HTTP {response.status_code}: {response.text}"
                
                logger.error(f"Pushover error: {error_msg}")
                return False, f"Pushover API Fehler: {error_msg}"
                
        except requests.exceptions.Timeout:
            return False, "Pushover API Timeout - Server nicht erreichbar"
        except requests.exceptions.ConnectionError:
            return False, "Keine Verbindung zu Pushover - Netzwerkfehler"
        except Exception as e:
            logger.error(f"Error sending Pushover notification: {e}")
            return False, f"Fehler: {str(e)}"
    
    def send_smart_notification_with_details(self, event_type: str, context: Dict[str, Any],
                                             title: str = None,
                                             style: str = "freundlich",
                                             priority: int = None,
                                             sound: str = None,
                                             use_chatgpt: bool = True) -> tuple[bool, str]:
        """
        Sendet eine intelligente Benachrichtigung mit detaillierter Fehlerrückgabe.
        
        Returns:
            Tuple (success, error_message)
        """
        # Generiere Text
        if use_chatgpt and self.openai_enabled:
            message = self.generate_smart_text(event_type, context, style)
        else:
            message = self._get_fallback_text(event_type, context)
        
        if not title:
            title = self._get_default_title(event_type)
        
        if sound is None:
            sound = self._get_default_sound(event_type)
        
        if priority is None:
            priority = self._get_default_priority(event_type)
        
        return self.send_notification_with_details(
            title=title,
            message=message,
            priority=priority,
            sound=sound
        )
    
    def send_smart_notification(self, event_type: str, context: Dict[str, Any],
                                title: str = None,
                                style: str = "freundlich",
                                priority: int = None,
                                sound: str = None,
                                use_chatgpt: bool = True) -> bool:
        """
        Sendet eine intelligente Benachrichtigung mit optionaler ChatGPT-Textgenerierung.
        
        Args:
            event_type: Art des Events
            context: Kontext-Daten
            title: Optionaler Titel (sonst automatisch)
            style: ChatGPT-Stil
            priority: Pushover-Priorität
            sound: Pushover-Sound
            use_chatgpt: ChatGPT für Textgenerierung nutzen
            
        Returns:
            True bei Erfolg
        """
        # Generiere Text
        if use_chatgpt and self.openai_enabled:
            message = self.generate_smart_text(event_type, context, style)
        else:
            message = self._get_fallback_text(event_type, context)
        
        # Generiere Titel falls nicht angegeben
        if not title:
            title = self._get_default_title(event_type)
        
        # Bestimme Sound basierend auf Event-Typ
        if sound is None:
            sound = self._get_default_sound(event_type)
        
        # Bestimme Priorität basierend auf Event-Typ
        if priority is None:
            priority = self._get_default_priority(event_type)
        
        return self.send_notification(
            title=title,
            message=message,
            priority=priority,
            sound=sound
        )
    
    def _get_default_title(self, event_type: str) -> str:
        """Gibt Standard-Titel für Event-Typ zurück"""
        titles = {
            "window_open_long": "🪟 Fenster offen",
            "temperature_alert": "🌡️ Temperaturwarnung",
            "humidity_alert": "💧 Luftfeuchtigkeit",
            "co2_alert": "🌬️ Luftqualität",
            "ventilation_complete": "✅ Lüftung beendet",
            "energy_tip": "💡 Energietipp",
            "morning_summary": "☀️ Guten Morgen",
            "heating_recommendation": "🔥 Heizempfehlung",
            "mold_risk": "⚠️ Schimmelwarnung",
            "device_status": "📱 Gerätestatus"
        }
        return titles.get(event_type, "🏠 Smart Home")
    
    def _get_default_sound(self, event_type: str) -> str:
        """Gibt Standard-Sound für Event-Typ zurück"""
        sounds = {
            "window_open_long": "falling",
            "temperature_alert": "siren",
            "humidity_alert": "intermission",
            "co2_alert": "tugboat",
            "ventilation_complete": "magic",
            "energy_tip": "cashregister",
            "morning_summary": "bugle",
            "heating_recommendation": "climb",
            "mold_risk": "alien",
            "device_status": "pushover"
        }
        return sounds.get(event_type, "pushover")
    
    def _get_default_priority(self, event_type: str) -> int:
        """Gibt Standard-Priorität für Event-Typ zurück"""
        priorities = {
            "window_open_long": 0,
            "temperature_alert": 0,
            "humidity_alert": 0,
            "co2_alert": 0,
            "ventilation_complete": -1,  # Leise
            "energy_tip": -1,
            "morning_summary": -1,
            "heating_recommendation": 0,
            "mold_risk": 1,  # Hohe Priorität
            "device_status": -1
        }
        return priorities.get(event_type, 0)
    
    def test_connection(self) -> Dict[str, Any]:
        """Testet Pushover und OpenAI Verbindung"""
        result = {
            "pushover": {"configured": self.pushover_enabled, "working": False},
            "openai": {"configured": self.openai_enabled, "working": False}
        }
        
        # Test Pushover
        if self.pushover_enabled:
            try:
                response = requests.post(
                    "https://api.pushover.net/1/users/validate.json",
                    data={
                        "token": self.pushover_token,
                        "user": self.pushover_user
                    },
                    timeout=5
                )
                result["pushover"]["working"] = response.status_code == 200
            except:
                pass
        
        # Test OpenAI
        if self.openai_enabled:
            try:
                response = requests.get(
                    "https://api.openai.com/v1/models",
                    headers={"Authorization": f"Bearer {self.openai_api_key}"},
                    timeout=5
                )
                result["openai"]["working"] = response.status_code == 200
            except:
                pass
        
        return result


# Singleton-Instanz
_notification_service: Optional[NotificationService] = None


def get_notification_service(config: Optional[Dict] = None) -> NotificationService:
    """Gibt die Singleton-Instanz des NotificationService zurück"""
    global _notification_service
    if _notification_service is None:
        _notification_service = NotificationService(config)
    return _notification_service
