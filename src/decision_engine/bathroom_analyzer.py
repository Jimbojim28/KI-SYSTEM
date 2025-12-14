"""
Badezimmer Automatisierung - Analyse & Lern-Modul
Analysiert historische Daten und erkennt Muster
"""

from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from loguru import logger
from src.utils.database import Database
import statistics


class BathroomAnalyzer:
    """
    Analysiert Badezimmer-Events und lernt Muster

    Features:
    - Zeitliche Muster-Erkennung (typische Duschzeiten)
    - Optimierung von Schwellwerten
    - Anomalie-Erkennung
    - Vorhersagen
    - Unterscheidung Dusche/Bad
    """

    def __init__(self, db: Database = None):
        self.db = db or Database()

    def classify_event_type(self, event: Dict) -> Dict:
        """
        Klassifiziert ein Event als Dusche, Bad oder anderes
        
        Heuristiken:
        - Dusche: 5-20 Min, starker Feuchtigkeitsanstieg (>20%)
        - Bad: 20-90 Min, moderater Feuchtigkeitsanstieg
        - Langes Bad: >45 Min mit moderatem Anstieg
        - Händewaschen/kurz: <5 Min
        
        Returns:
            Dict mit type, confidence, description
        """
        duration = event.get('duration_minutes') or 0
        peak_humidity = event.get('peak_humidity') or 0
        start_humidity = event.get('start_humidity') or 0
        humidity_rise = peak_humidity - start_humidity if peak_humidity and start_humidity else 0
        
        # Klassifikation basierend auf Dauer und Feuchtigkeitsanstieg
        if duration < 5:
            return {
                'type': 'kurz',
                'icon': '🚰',
                'label': 'Kurze Nutzung',
                'description': 'Händewaschen oder kurze Nutzung',
                'confidence': 0.8
            }
        elif duration <= 15 and humidity_rise > 15:
            return {
                'type': 'dusche',
                'icon': '🚿',
                'label': 'Dusche',
                'description': f'Typische Dusche ({duration:.0f} Min)',
                'confidence': 0.9
            }
        elif duration <= 25 and humidity_rise > 10:
            return {
                'type': 'dusche',
                'icon': '🚿',
                'label': 'Längere Dusche',
                'description': f'Längere Dusche ({duration:.0f} Min)',
                'confidence': 0.7
            }
        elif 20 <= duration <= 60:
            return {
                'type': 'bad',
                'icon': '🛁',
                'label': 'Bad',
                'description': f'Wahrscheinlich Baden ({duration:.0f} Min)',
                'confidence': 0.75
            }
        elif duration > 60:
            return {
                'type': 'langes_bad',
                'icon': '🛁',
                'label': 'Ausgedehntes Bad',
                'description': f'Langes Bad oder Entspannung ({duration:.0f} Min)',
                'confidence': 0.7
            }
        else:
            return {
                'type': 'unbekannt',
                'icon': '❓',
                'label': 'Badezimmer-Nutzung',
                'description': f'Unklare Nutzung ({duration:.0f} Min)',
                'confidence': 0.5
            }

    def analyze_patterns(self, days_back: int = 30) -> Dict:
        """
        Analysiert zeitliche Muster in den letzten X Tagen

        Returns:
            Dict mit Analyse-Ergebnissen
        """
        events = self.db.get_bathroom_events(days_back=days_back)

        if not events or len(events) < 3:
            logger.warning("Nicht genug Events für Analyse")
            return {
                'events_count': len(events) if events else 0,
                'sufficient_data': False,
                'message': 'Mindestens 3 Events benötigt'
            }

        # Zeitliche Muster
        hourly_pattern = self._analyze_hourly_pattern(events)
        weekly_pattern = self._analyze_weekly_pattern(events)

        # Statistiken
        duration_stats = self._analyze_durations(events)
        humidity_stats = self._analyze_humidity(events)

        return {
            'events_count': len(events),
            'sufficient_data': True,
            'period_days': days_back,
            'hourly_pattern': hourly_pattern,
            'weekly_pattern': weekly_pattern,
            'duration_stats': duration_stats,
            'humidity_stats': humidity_stats,
            'analyzed_at': datetime.now().isoformat()
        }

    def _analyze_hourly_pattern(self, events: List[Dict]) -> Dict:
        """Analysiert Muster nach Tageszeit"""
        hourly_counts = {}

        for event in events:
            hour = event.get('hour_of_day')
            if hour is not None:
                hourly_counts[hour] = hourly_counts.get(hour, 0) + 1

        # Finde Peak-Zeiten (häufigste Stunden)
        peak_hours = sorted(
            hourly_counts.items(),
            key=lambda x: x[1],
            reverse=True
        )[:3]

        return {
            'distribution': hourly_counts,
            'peak_hours': [
                {
                    'hour': hour,
                    'count': count,
                    'percentage': round((count / len(events)) * 100, 1)
                }
                for hour, count in peak_hours
            ]
        }

    def _analyze_weekly_pattern(self, events: List[Dict]) -> Dict:
        """Analysiert Muster nach Wochentag"""
        weekday_counts = {}
        weekday_names = ['Montag', 'Dienstag', 'Mittwoch', 'Donnerstag',
                        'Freitag', 'Samstag', 'Sonntag']

        for event in events:
            day = event.get('day_of_week')
            if day is not None:
                weekday_counts[day] = weekday_counts.get(day, 0) + 1

        # Erstelle Wochenverteilung
        distribution = [
            {
                'day': day,
                'name': weekday_names[day],
                'count': weekday_counts.get(day, 0),
                'percentage': round((weekday_counts.get(day, 0) / len(events)) * 100, 1)
            }
            for day in range(7)
        ]

        # Unterscheide Werktag vs. Wochenende
        weekday_events = sum(weekday_counts.get(day, 0) for day in range(5))
        weekend_events = sum(weekday_counts.get(day, 0) for day in range(5, 7))

        return {
            'distribution': distribution,
            'weekday_vs_weekend': {
                'weekday_count': weekday_events,
                'weekend_count': weekend_events,
                'weekday_percentage': round((weekday_events / len(events)) * 100, 1),
                'weekend_percentage': round((weekend_events / len(events)) * 100, 1)
            }
        }

    def _analyze_durations(self, events: List[Dict]) -> Dict:
        """Analysiert Dusch-Dauern"""
        durations = [
            event['duration_minutes']
            for event in events
            if event.get('duration_minutes') is not None
        ]

        if not durations:
            return {'available': False}

        return {
            'available': True,
            'count': len(durations),
            'avg_minutes': round(statistics.mean(durations), 1),
            'median_minutes': round(statistics.median(durations), 1),
            'min_minutes': round(min(durations), 1),
            'max_minutes': round(max(durations), 1),
            'std_dev': round(statistics.stdev(durations), 1) if len(durations) > 1 else 0
        }

    def _analyze_humidity(self, events: List[Dict]) -> Dict:
        """Analysiert Luftfeuchtigkeits-Muster"""
        peak_humidities = [
            event['peak_humidity']
            for event in events
            if event.get('peak_humidity') is not None
        ]

        avg_humidities = [
            event['avg_humidity']
            for event in events
            if event.get('avg_humidity') is not None
        ]

        if not peak_humidities:
            return {'available': False}

        return {
            'available': True,
            'peak': {
                'avg': round(statistics.mean(peak_humidities), 1),
                'median': round(statistics.median(peak_humidities), 1),
                'min': round(min(peak_humidities), 1),
                'max': round(max(peak_humidities), 1)
            },
            'average': {
                'avg': round(statistics.mean(avg_humidities), 1),
                'median': round(statistics.median(avg_humidities), 1)
            } if avg_humidities else None
        }

    def suggest_optimal_thresholds(self, days_back: int = 30) -> Optional[Dict]:
        """
        Schlägt optimale Schwellwerte basierend auf historischen Daten vor

        Returns:
            Dict mit vorgeschlagenen Schwellwerten und Confidence
        """
        events = self.db.get_bathroom_events(days_back=days_back)

        if not events or len(events) < 5:
            logger.warning("Nicht genug Events für Schwellwert-Optimierung (mindestens 5 benötigt)")
            return None

        # Analysiere Luftfeuchtigkeit während Events
        peak_humidities = [
            event['peak_humidity']
            for event in events
            if event.get('peak_humidity') is not None
        ]

        start_humidities = [
            event['start_humidity']
            for event in events
            if event.get('start_humidity') is not None
        ]

        end_humidities = [
            event['end_humidity']
            for event in events
            if event.get('end_humidity') is not None
        ]

        if not peak_humidities or not start_humidities:
            return None

        # Berechne optimale Schwellwerte
        # High: Sollte unter dem durchschnittlichen Peak liegen, aber über dem Start
        avg_peak = statistics.mean(peak_humidities)
        avg_start = statistics.mean(start_humidities)

        # Verwende 75% Perzentil des Starts als High-Schwellwert
        sorted_starts = sorted(start_humidities)
        percentile_75_index = int(len(sorted_starts) * 0.75)
        optimal_high = sorted_starts[percentile_75_index]

        # Low: Sollte über dem durchschnittlichen End-Wert liegen
        if end_humidities:
            avg_end = statistics.mean(end_humidities)
            # Verwende 25% Perzentil des Endes als Low-Schwellwert
            sorted_ends = sorted(end_humidities)
            percentile_25_index = int(len(sorted_ends) * 0.25)
            optimal_low = sorted_ends[percentile_25_index]
        else:
            # Fallback: 10% unter High-Schwellwert
            optimal_low = optimal_high - 10

        # Berechne Confidence basierend auf Datenmenge und Varianz
        confidence = min(0.95, 0.5 + (len(events) / 100))
        std_dev_peak = statistics.stdev(peak_humidities) if len(peak_humidities) > 1 else 0
        if std_dev_peak > 15:  # Hohe Varianz = niedrigere Confidence
            confidence *= 0.8

        return {
            'humidity_threshold_high': round(optimal_high, 1),
            'humidity_threshold_low': round(optimal_low, 1),
            'confidence': round(confidence, 2),
            'based_on_events': len(events),
            'statistics': {
                'avg_peak': round(avg_peak, 1),
                'avg_start': round(avg_start, 1),
                'avg_end': round(avg_end, 1) if end_humidities else None,
                'std_dev_peak': round(std_dev_peak, 1)
            },
            'reason': 'Calculated from historical data using percentile method'
        }

    def detect_anomalies(self, event_id: int) -> Dict:
        """
        Erkennt Anomalien in einem Event
        (z.B. ungewöhnlich lange Dauer, sehr hohe Luftfeuchtigkeit)

        Returns:
            Dict mit Anomalie-Informationen
        """
        # Hole das Event
        events = self.db.get_bathroom_events(days_back=90)

        current_event = None
        for event in events:
            if event['id'] == event_id:
                current_event = event
                break

        if not current_event:
            return {'anomaly_detected': False, 'reason': 'Event not found'}

        # Vergleiche mit historischen Daten
        historical_events = [e for e in events if e['id'] != event_id and e.get('duration_minutes')]

        if len(historical_events) < 3:
            return {'anomaly_detected': False, 'reason': 'Not enough historical data'}

        anomalies = []

        # Prüfe Dauer
        if current_event.get('duration_minutes'):
            durations = [e['duration_minutes'] for e in historical_events if e.get('duration_minutes')]
            avg_duration = statistics.mean(durations)
            std_dev = statistics.stdev(durations) if len(durations) > 1 else 0

            # Anomalie wenn > 2 Standardabweichungen
            if std_dev > 0 and abs(current_event['duration_minutes'] - avg_duration) > (2 * std_dev):
                anomalies.append({
                    'type': 'duration',
                    'value': current_event['duration_minutes'],
                    'expected_range': [
                        round(avg_duration - 2 * std_dev, 1),
                        round(avg_duration + 2 * std_dev, 1)
                    ],
                    'severity': 'high' if current_event['duration_minutes'] > (avg_duration + 3 * std_dev) else 'medium'
                })

        # Prüfe Luftfeuchtigkeit
        if current_event.get('peak_humidity'):
            peaks = [e['peak_humidity'] for e in historical_events if e.get('peak_humidity')]
            avg_peak = statistics.mean(peaks)
            std_dev_peak = statistics.stdev(peaks) if len(peaks) > 1 else 0

            if std_dev_peak > 0 and abs(current_event['peak_humidity'] - avg_peak) > (2 * std_dev_peak):
                anomalies.append({
                    'type': 'humidity',
                    'value': current_event['peak_humidity'],
                    'expected_range': [
                        round(avg_peak - 2 * std_dev_peak, 1),
                        round(avg_peak + 2 * std_dev_peak, 1)
                    ],
                    'severity': 'high' if current_event['peak_humidity'] > 90 else 'medium'
                })

        return {
            'anomaly_detected': len(anomalies) > 0,
            'anomalies': anomalies,
            'event_id': event_id
        }

    def predict_next_shower(self) -> Optional[Dict]:
        """
        Sagt die wahrscheinlichste Zeit für die nächste Dusche vorher
        basierend auf historischen Mustern
        """
        analysis = self.analyze_patterns(days_back=30)

        if not analysis.get('sufficient_data'):
            return None

        # Finde die häufigsten Duschzeiten
        peak_hours = analysis['hourly_pattern']['peak_hours']

        if not peak_hours:
            return None

        # Aktuelle Zeit
        now = datetime.now()
        current_hour = now.hour
        current_weekday = now.weekday()

        # Finde die nächste wahrscheinliche Zeit
        next_predictions = []

        for peak in peak_hours:
            hour = peak['hour']
            probability = peak['percentage'] / 100

            # Berechne nächstes Vorkommen dieser Stunde
            if hour > current_hour:
                # Heute
                next_time = now.replace(hour=hour, minute=0, second=0, microsecond=0)
                hours_until = (next_time - now).seconds / 3600
            else:
                # Morgen
                next_time = (now + timedelta(days=1)).replace(hour=hour, minute=0, second=0, microsecond=0)
                hours_until = (next_time - now).seconds / 3600 + 24

            next_predictions.append({
                'time': next_time.isoformat(),
                'hour': hour,
                'hours_until': round(hours_until, 1),
                'probability': round(probability, 2)
            })

        # Sortiere nach Zeit
        next_predictions.sort(key=lambda x: x['hours_until'])

        return {
            'predictions': next_predictions[:3],  # Top 3 Vorhersagen
            'most_likely': next_predictions[0] if next_predictions else None
        }

    def check_system_health(self, days_back: int = 7, config: dict = None) -> List[Dict]:
        """
        Prüft System-Gesundheit und erkennt potenzielle Probleme

        Args:
            days_back: Tage zurück für Event-Analyse
            config: Optionale Konfiguration für intelligentere Prüfungen

        Returns:
            List von Alerts/Warnungen
        """
        alerts = []
        events = self.db.get_bathroom_events(days_back=days_back)

        if not events or len(events) < 2:
            return alerts
        
        # Lade Konfiguration falls nicht übergeben
        if config is None:
            try:
                from src.utils.sensor_helper import get_bathroom_config
                config = get_bathroom_config()
                if not config:
                    config = {}
            except Exception:
                config = {}
        
        # Prüfe ob Automation aktiviert und Luftentfeuchter konfiguriert
        automation_enabled = config.get('enabled', False)
        dehumidifier_configured = bool(config.get('dehumidifier_id'))
        humidity_threshold_high = config.get('humidity_threshold_high', 65)

        # 1. Luftentfeuchter läuft ungewöhnlich lange
        for event in events[:5]:  # Letzte 5 Events prüfen
            runtime = event.get('dehumidifier_runtime_minutes') or 0
            if runtime > 240:  # > 4 Stunden
                alerts.append({
                    'severity': 'high',
                    'type': 'long_dehumidifier_runtime',
                    'title': '⚠️ Luftentfeuchter läuft sehr lange',
                    'message': f'Luftentfeuchter lief {runtime} Minuten (Event: {event["start_time"]}). Möglicherweise Filter verstopft oder Gerät defekt?',
                    'timestamp': event['start_time'],
                    'event_id': event['id']
                })

        # 2. Luftfeuchtigkeit wird nicht reduziert
        # Nur Events mit Luftentfeuchter-Laufzeit prüfen (sonst ist es normal dass nichts reduziert wird)
        ineffective_events = [e for e in events 
                             if (e.get('peak_humidity') or 0) > 0 
                             and (e.get('end_humidity') or 0) > 0
                             and (e.get('dehumidifier_runtime_minutes') or 0) > 10  # Min. 10 Min gelaufen
                             and ((e.get('peak_humidity') or 0) - (e.get('end_humidity') or 0)) < 5]
        if len(ineffective_events) >= 3:
            alerts.append({
                'severity': 'medium',
                'type': 'ineffective_dehumidification',
                'title': '⚠️ Entfeuchtung nicht effektiv',
                'message': f'{len(ineffective_events)} Events bei denen der Luftentfeuchter lief, aber die Feuchtigkeit kaum sank. Filter prüfen oder Fenster zu?',
                'timestamp': datetime.now().isoformat()
            })

        # 3. Ungewöhnlich lange Events (unterscheide zwischen Duschen und Baden)
        for event in events[:10]:
            duration = event.get('duration_minutes') or 0
            peak_humidity = event.get('peak_humidity') or 0
            
            if duration > 30:  # Längere Events analysieren
                # Baden erkennen: längere Dauer + moderater Feuchtigkeitsanstieg
                # Duschen: kürzere Dauer + starker Feuchtigkeitsanstieg
                is_likely_bath = duration >= 30 and peak_humidity < 85
                is_very_long = duration > 60
                
                if is_very_long and is_likely_bath:
                    # Wahrscheinlich ausgedehntes Bad - kein Alert, nur Info wenn > 90 Min
                    if duration > 90:
                        alerts.append({
                            'severity': 'low',
                            'type': 'long_bath_session',
                            'title': '🛁 Ausgedehntes Bad erkannt',
                            'message': f'Bad dauerte {duration:.0f} Minuten am {event["start_time"][:10]}. Das ist normal und kein Problem.',
                            'timestamp': event['start_time'],
                            'event_id': event['id']
                        })
                elif is_very_long and not is_likely_bath:
                    # Lange hohe Feuchtigkeit - möglicherweise Tür offen
                    alerts.append({
                        'severity': 'low',
                        'type': 'long_humidity_event',
                        'title': 'ℹ️ Lange hohe Luftfeuchtigkeit',
                        'message': f'Feuchtigkeit war {duration:.0f} Minuten erhöht (Peak: {peak_humidity:.0f}%). Tür/Fenster geöffnet lassen für bessere Belüftung?',
                        'timestamp': event['start_time'],
                        'event_id': event['id']
                    })
                elif 30 <= duration <= 60 and is_likely_bath:
                    # Normales Bad - kein Alert
                    pass

        # 4. Sehr hohe Luftfeuchtigkeit erreicht
        extreme_humidity_events = [e for e in events[:10] if (e.get('peak_humidity') or 0) > 90]
        if extreme_humidity_events:
            for event in extreme_humidity_events:
                alerts.append({
                    'severity': 'medium',
                    'type': 'extreme_humidity',
                    'title': '⚠️ Sehr hohe Luftfeuchtigkeit',
                    'message': f'Luftfeuchtigkeit erreichte {event.get("peak_humidity", 0)}% (Kondenswasser-Risiko)',
                    'timestamp': event['start_time'],
                    'event_id': event['id']
                })

        # 5. Keine Events seit längerer Zeit (mögliches Problem mit Sensoren)
        if events:
            try:
                start_time_str = str(events[0].get('start_time', '')).replace('Z', '+00:00')
                last_event_time = datetime.fromisoformat(start_time_str)
                # Entferne Timezone für konsistente Berechnung
                if last_event_time.tzinfo is not None:
                    last_event_time = last_event_time.replace(tzinfo=None)
                days_since_last = (datetime.now() - last_event_time).days
            except (ValueError, TypeError):
                days_since_last = 0
            if days_since_last > 7:
                alerts.append({
                    'severity': 'medium',
                    'type': 'no_recent_events',
                    'title': '⚠️ Keine Events seit längerer Zeit',
                    'message': f'Letztes Event vor {days_since_last} Tagen. Sensoren prüfen?',
                    'timestamp': datetime.now().isoformat()
                })

        # 6. Dehumidifier läuft nie - NUR warnen wenn sinnvoll
        # Prüfe ob es Events gab wo der Luftentfeuchter hätte laufen SOLLEN
        no_dehumidifier_events = [e for e in events[:10] if (e.get('dehumidifier_runtime_minutes') or 0) == 0]
        
        if len(no_dehumidifier_events) >= 5:
            # Prüfe ob diese Events hohe Luftfeuchtigkeit hatten (über Schwellwert)
            high_humidity_events = [
                e for e in no_dehumidifier_events 
                if (e.get('peak_humidity') or 0) > humidity_threshold_high
            ]
            
            # Nur warnen wenn:
            # 1. Automation aktiviert UND Luftentfeuchter konfiguriert
            # 2. ODER es gab Events mit hoher Luftfeuchtigkeit (hätte laufen sollen)
            should_warn = False
            warning_reason = ""
            
            if automation_enabled and dehumidifier_configured and len(high_humidity_events) >= 3:
                # Automation ist an, Gerät konfiguriert, aber läuft nie trotz hoher Feuchtigkeit
                should_warn = True
                warning_reason = f'{len(high_humidity_events)} Events mit Luftfeuchtigkeit über {humidity_threshold_high}% - aber Luftentfeuchter lief nie. Gerät erreichbar?'
            elif not automation_enabled and len(high_humidity_events) >= 3:
                # Automation aus, aber hohe Luftfeuchtigkeit erkannt - Hinweis geben
                alerts.append({
                    'severity': 'low',
                    'type': 'automation_disabled_high_humidity',
                    'title': 'ℹ️ Hohe Luftfeuchtigkeit erkannt',
                    'message': f'{len(high_humidity_events)} Events mit Luftfeuchtigkeit über {humidity_threshold_high}%. Tipp: Automation aktivieren für automatische Entfeuchtung.',
                    'timestamp': datetime.now().isoformat()
                })
            elif not dehumidifier_configured and automation_enabled:
                # Automation an, aber kein Luftentfeuchter konfiguriert
                alerts.append({
                    'severity': 'medium',
                    'type': 'dehumidifier_not_configured',
                    'title': '⚠️ Kein Luftentfeuchter konfiguriert',
                    'message': 'Automation ist aktiviert, aber kein Luftentfeuchter wurde zugewiesen. Bitte in den Einstellungen konfigurieren.',
                    'timestamp': datetime.now().isoformat()
                })
            
            if should_warn:
                alerts.append({
                    'severity': 'high',
                    'type': 'dehumidifier_never_runs',
                    'title': '⚠️ Luftentfeuchter läuft nie',
                    'message': warning_reason,
                    'timestamp': datetime.now().isoformat()
                })

        return alerts
