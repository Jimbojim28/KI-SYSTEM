"""
Predictive Shower Detection
ML-basierte Vorhersage von Duschzeiten basierend auf historischen Mustern
"""

from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from loguru import logger
from src.utils.database import Database
import statistics


class ShowerPredictor:
    """
    Vorhersage-System für Dusch-Events

    Features:
    - Erkennt zeitliche Muster (typische Duschzeiten)
    - Wochentag-spezifische Vorhersagen
    - Confidence-Scores basierend auf Muster-Stabilität
    - Präventives Vorheizen des Badezimmers
    """

    def __init__(self, db: Database = None):
        self.db = db or Database()
        self.min_samples_for_prediction = 5  # Mindestens 5 Duschen für Vorhersage

    def analyze_shower_patterns(self, days_back: int = 30) -> Dict:
        """
        Analysiert Duschmuster der letzten X Tage

        Returns:
            Dict mit zeitlichen Mustern und Statistiken
        """
        # Hole historische Badezimmer-Events
        events = self.db.get_bathroom_events(days_back=days_back)

        if not events or len(events) < self.min_samples_for_prediction:
            return {
                'sufficient_data': False,
                'events_count': len(events) if events else 0,
                'min_required': self.min_samples_for_prediction,
                'message': f'Mindestens {self.min_samples_for_prediction} Duschen benötigt für Vorhersage'
            }

        # Analysiere zeitliche Muster
        hourly_pattern = self._analyze_hourly_shower_pattern(events)
        weekday_pattern = self._analyze_weekday_shower_pattern(events)

        # Erkenne häufigste Duschzeiten
        typical_times = self._find_typical_shower_times(events, hourly_pattern)

        # Berechne Muster-Stabilität (wie regelmäßig?)
        pattern_stability = self._calculate_pattern_stability(events)

        return {
            'sufficient_data': True,
            'events_count': len(events),
            'period_days': days_back,
            'hourly_pattern': hourly_pattern,
            'weekday_pattern': weekday_pattern,
            'typical_times': typical_times,
            'pattern_stability': pattern_stability,
            'analyzed_at': datetime.now().isoformat()
        }

    def _analyze_hourly_shower_pattern(self, events: List[Dict]) -> Dict:
        """Analysiert Duschmuster nach Tageszeit"""
        hourly_counts = {}

        for event in events:
            hour = event.get('hour_of_day')
            if hour is not None:
                hourly_counts[hour] = hourly_counts.get(hour, 0) + 1

        # Finde Peak-Zeiten
        if hourly_counts:
            peak_hours = sorted(
                hourly_counts.items(),
                key=lambda x: x[1],
                reverse=True
            )[:3]  # Top 3 Zeiten
        else:
            peak_hours = []

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

    def _analyze_weekday_shower_pattern(self, events: List[Dict]) -> Dict:
        """Analysiert Duschmuster nach Wochentag"""
        weekday_counts = {}
        weekday_names = ['Montag', 'Dienstag', 'Mittwoch', 'Donnerstag',
                        'Freitag', 'Samstag', 'Sonntag']

        for event in events:
            day = event.get('day_of_week')
            if day is not None:
                weekday_counts[day] = weekday_counts.get(day, 0) + 1

        distribution = []
        for day in range(7):
            count = weekday_counts.get(day, 0)
            distribution.append({
                'day': day,
                'name': weekday_names[day],
                'count': count,
                'avg_per_week': round(count / 4, 1) if len(events) >= 28 else None
            })

        return {
            'distribution': distribution,
            'weekday_counts': weekday_counts
        }

    def _find_typical_shower_times(self, events: List[Dict],
                                   hourly_pattern: Dict) -> List[Dict]:
        """Findet typische Duschzeiten mit Confidence"""
        peak_hours = hourly_pattern.get('peak_hours', [])
        typical_times = []

        for peak in peak_hours:
            hour = peak['hour']
            count = peak['count']

            # Confidence basierend auf Häufigkeit
            confidence = min(1.0, count / (len(events) * 0.5))  # 50% = perfekt

            # Finde typische Minuten innerhalb der Stunde
            hour_events = [e for e in events if e.get('hour_of_day') == hour]
            if hour_events:
                minutes = [e.get('minute_of_hour', 0) for e in hour_events if e.get('minute_of_hour') is not None]
                avg_minute = int(statistics.mean(minutes)) if minutes else 0
            else:
                avg_minute = 0

            typical_times.append({
                'hour': hour,
                'minute': avg_minute,
                'time_string': f'{hour:02d}:{avg_minute:02d}',
                'count': count,
                'confidence': round(confidence, 2),
                'label': self._get_time_label(hour)
            })

        return typical_times

    def _get_time_label(self, hour: int) -> str:
        """Gibt Label für Tageszeit"""
        if 5 <= hour < 9:
            return "Morgens"
        elif 9 <= hour < 12:
            return "Vormittags"
        elif 12 <= hour < 14:
            return "Mittags"
        elif 14 <= hour < 18:
            return "Nachmittags"
        elif 18 <= hour < 22:
            return "Abends"
        else:
            return "Nachts"

    def _calculate_pattern_stability(self, events: List[Dict]) -> Dict:
        """
        Berechnet wie stabil/regelmäßig das Duschmuster ist

        Returns:
            Score 0-1 (1 = sehr regelmäßig, 0 = zufällig)
        """
        if len(events) < 3:
            return {'score': 0.0, 'description': 'Zu wenige Daten'}

        # Berechne Zeitabstände zwischen Duschen
        times = [e.get('start_time') for e in events if e.get('start_time')]
        times.sort()

        if len(times) < 2:
            return {'score': 0.0, 'description': 'Unzureichende Zeitdaten'}

        # Berechne Intervalle (in Stunden)
        intervals = []
        for i in range(len(times) - 1):
            t1 = datetime.fromisoformat(str(times[i]).replace('Z', '+00:00'))
            t2 = datetime.fromisoformat(str(times[i + 1]).replace('Z', '+00:00'))
            # Entferne Timezone-Info für konsistente Berechnung
            if t1.tzinfo is not None:
                t1 = t1.replace(tzinfo=None)
            if t2.tzinfo is not None:
                t2 = t2.replace(tzinfo=None)
            interval_hours = (t2 - t1).total_seconds() / 3600
            intervals.append(interval_hours)

        # Standardabweichung der Intervalle (niedriger = regelmäßiger)
        if len(intervals) >= 2:
            std_dev = statistics.stdev(intervals)
            mean_interval = statistics.mean(intervals)

            # Normalisiere: Coefficient of Variation
            cv = (std_dev / mean_interval) if mean_interval > 0 else 1.0

            # Score: 1 - normalisiertes CV (je niedriger CV, desto höher Score)
            stability_score = max(0.0, min(1.0, 1.0 - (cv / 2.0)))

            if stability_score >= 0.7:
                description = "Sehr regelmäßig"
            elif stability_score >= 0.5:
                description = "Regelmäßig"
            elif stability_score >= 0.3:
                description = "Moderat regelmäßig"
            else:
                description = "Unregelmäßig"

            return {
                'score': round(stability_score, 2),
                'description': description,
                'mean_interval_hours': round(mean_interval, 1),
                'std_dev_hours': round(std_dev, 1)
            }

        return {'score': 0.5, 'description': 'Zu wenige Intervalle'}

    def predict_next_shower(self, min_confidence: float = 0.5) -> Optional[Dict]:
        """
        Sagt die nächste wahrscheinliche Duschzeit vorher

        Args:
            min_confidence: Mindest-Confidence für Vorhersage

        Returns:
            Dict mit Vorhersage oder None
        """
        patterns = self.analyze_shower_patterns(days_back=30)

        if not patterns.get('sufficient_data'):
            logger.info("Not enough data for shower prediction")
            return None

        typical_times = patterns.get('typical_times', [])

        if not typical_times:
            logger.info("No typical shower times found")
            return None

        # Finde nächste typische Zeit
        now = datetime.now()
        current_weekday = now.weekday()

        predictions = []

        for time_slot in typical_times:
            hour = time_slot['hour']
            minute = time_slot['minute']
            confidence = time_slot['confidence']

            if confidence < min_confidence:
                continue

            # Berechne nächsten Zeitpunkt für diese Uhrzeit
            prediction_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)

            # Wenn schon vorbei heute, nehme morgen
            if prediction_time < now:
                prediction_time += timedelta(days=1)

            predictions.append({
                'predicted_time': prediction_time,
                'hour': hour,
                'minute': minute,
                'time_string': time_slot['time_string'],
                'confidence': confidence,
                'label': time_slot['label'],
                'pattern_strength': patterns['pattern_stability']['score'],
                'samples_used': patterns['events_count']
            })

        if not predictions:
            return None

        # Sortiere nach nächster Zeit
        predictions.sort(key=lambda x: x['predicted_time'])

        next_prediction = predictions[0]

        # Speichere Vorhersage in DB
        self.db.save_shower_prediction(
            predicted_time=next_prediction['predicted_time'],
            confidence=next_prediction['confidence'],
            typical_hour=next_prediction['hour'],
            typical_weekday=current_weekday,
            pattern_strength=next_prediction['pattern_strength'],
            samples=next_prediction['samples_used']
        )

        logger.info(
            f"Predicted next shower at {next_prediction['time_string']} "
            f"(confidence: {next_prediction['confidence']:.0%})"
        )

        return next_prediction

    def get_predictions_for_today(self) -> List[Dict]:
        """
        Holt alle Vorhersagen für heute

        Returns:
            Liste von vorhergesagten Duschzeiten
        """
        patterns = self.analyze_shower_patterns(days_back=30)

        if not patterns.get('sufficient_data'):
            return []

        typical_times = patterns.get('typical_times', [])
        now = datetime.now()
        today_predictions = []

        for time_slot in typical_times:
            hour = time_slot['hour']
            minute = time_slot['minute']
            confidence = time_slot['confidence']

            prediction_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)

            # Nur zukünftige Zeiten heute
            if prediction_time > now:
                today_predictions.append({
                    'predicted_time': prediction_time.isoformat(),
                    'time_string': time_slot['time_string'],
                    'confidence': confidence,
                    'label': time_slot['label'],
                    'icon': self._get_time_icon(time_slot['label'])
                })

        return sorted(today_predictions, key=lambda x: x['predicted_time'])

    def _get_time_icon(self, label: str) -> str:
        """Gibt Emoji für Tageszeit"""
        icons = {
            "Morgens": "🌅",
            "Vormittags": "☀️",
            "Mittags": "🌤️",
            "Nachmittags": "🌞",
            "Abends": "🌆",
            "Nachts": "🌙"
        }
        return icons.get(label, "🚿")

    def should_preheat_bathroom(self, target_time: datetime,
                               preheat_minutes: int = 10) -> Dict:
        """
        Entscheidet ob Badezimmer vorgeheizt werden soll

        Args:
            target_time: Vorhergesagte Duschzeit
            preheat_minutes: Wie lange vorher vorheizen

        Returns:
            Dict mit Entscheidung und Timing
        """
        now = datetime.now()
        preheat_start_time = target_time - timedelta(minutes=preheat_minutes)

        time_until_preheat = (preheat_start_time - now).total_seconds() / 60  # Minuten

        if time_until_preheat <= 0 and time_until_preheat >= -preheat_minutes:
            # Wir sind im Vorheiz-Fenster
            return {
                'should_preheat': True,
                'action': 'START_HEATING',
                'reason': f'Vorheizen für vorhergesagte Dusche um {target_time.strftime("%H:%M")}',
                'target_time': target_time.isoformat(),
                'minutes_until_shower': abs(time_until_preheat)
            }
        elif time_until_preheat > 0 and time_until_preheat <= 30:
            # Bald vorheizen
            return {
                'should_preheat': False,
                'action': 'WAIT',
                'reason': f'Vorheizen in {int(time_until_preheat)} Minuten',
                'target_time': target_time.isoformat(),
                'wait_minutes': int(time_until_preheat)
            }
        else:
            # Zu früh oder zu spät
            return {
                'should_preheat': False,
                'action': 'NO_ACTION',
                'reason': 'Außerhalb des Vorheiz-Fensters',
                'target_time': target_time.isoformat()
            }
