"""
Forgotten Light ML Model - Lernt Muster für vergessene Lampen

Trainiert auf:
- Historischen Lampenzuständen (wann an/aus)
- Bewegungsmuster pro Raum
- Tageszeit und Wochentag
- Anwesenheitsmuster
- Außenhelligkeit

Vorhersage:
- Wahrscheinlichkeit dass eine Lampe "vergessen" wurde
"""

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.model_selection import train_test_split, cross_val_score
from sklearn.metrics import accuracy_score, classification_report, precision_score, recall_score
from sklearn.preprocessing import StandardScaler
from datetime import datetime, timedelta
import joblib
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from loguru import logger

from src.utils.database import Database


class ForgottenLightModel:
    """
    ML-Modell zur Vorhersage, ob eine Lampe vergessen wurde auszuschalten.
    
    Lernt aus:
    - Normalen Ausschaltmustern (wann schalten Benutzer typischerweise aus?)
    - Bewegungsmustern nach dem Einschalten
    - Tageszeit-Korrelationen
    - Raum-spezifischen Mustern
    """
    
    def __init__(self, model_type: str = "gradient_boosting"):
        self.model_type = model_type
        self.model = None
        self.scaler = StandardScaler()
        self.is_trained = False
        self.model_version = "1.0.0"
        self.min_samples = 100  # Mindestens 100 Samples für Training
        
        self.feature_columns = [
            'hour_of_day',
            'day_of_week',
            'is_weekend',
            'is_evening',      # 18-23 Uhr
            'is_night',        # 23-6 Uhr
            'is_morning',      # 6-10 Uhr
            'on_duration_minutes',
            'minutes_since_motion',
            'presence_home',
            'outdoor_light',
            'room_encoded',
            'typical_duration_exceeded',  # Länger als typisch für diesen Raum?
        ]
        
        # Statistiken pro Raum (werden aus Daten gelernt)
        self.room_stats: Dict[str, Dict] = {}
        
    def _create_model(self):
        """Erstellt das ML-Modell"""
        if self.model_type == "gradient_boosting":
            return GradientBoostingClassifier(
                n_estimators=100,
                max_depth=5,
                learning_rate=0.1,
                min_samples_split=5,
                random_state=42
            )
        else:
            return RandomForestClassifier(
                n_estimators=100,
                max_depth=10,
                min_samples_split=5,
                random_state=42,
                class_weight='balanced'  # Wichtig: Vergessene Lampen sind seltener
            )
    
    def _create_features(self, data: pd.DataFrame) -> pd.DataFrame:
        """Erstellt Features für das Modell"""
        features = pd.DataFrame()
        
        # Zeit-Features
        if 'timestamp' in data.columns:
            data['timestamp'] = pd.to_datetime(data['timestamp'])
            features['hour_of_day'] = data['timestamp'].dt.hour
            features['day_of_week'] = data['timestamp'].dt.dayofweek
            features['is_weekend'] = (data['timestamp'].dt.dayofweek >= 5).astype(int)
        else:
            features['hour_of_day'] = data.get('hour_of_day', 12)
            features['day_of_week'] = data.get('day_of_week', 0)
            features['is_weekend'] = data.get('is_weekend', 0)
        
        # Tageszeit-Kategorien
        hour = features['hour_of_day']
        features['is_evening'] = ((hour >= 18) & (hour < 23)).astype(int)
        features['is_night'] = ((hour >= 23) | (hour < 6)).astype(int)
        features['is_morning'] = ((hour >= 6) & (hour < 10)).astype(int)
        
        # Lampen-Zustand Features
        features['on_duration_minutes'] = data.get('on_duration_minutes', 0)
        features['minutes_since_motion'] = data.get('minutes_since_motion', 0)
        features['presence_home'] = data.get('presence_home', 1)
        features['outdoor_light'] = data.get('outdoor_light', 50)
        
        # Raum-Encoding (simple Label-Encoding)
        if 'room_name' in data.columns:
            room_mapping = {room: i for i, room in enumerate(data['room_name'].unique())}
            features['room_encoded'] = data['room_name'].map(room_mapping).fillna(0)
        else:
            features['room_encoded'] = 0
        
        # Vergleich mit typischer Dauer für den Raum
        features['typical_duration_exceeded'] = 0
        if 'room_name' in data.columns and 'on_duration_minutes' in data.columns:
            for room in data['room_name'].unique():
                if room in self.room_stats:
                    typical = self.room_stats[room].get('typical_duration', 60)
                    mask = data['room_name'] == room
                    features.loc[mask, 'typical_duration_exceeded'] = (
                        data.loc[mask, 'on_duration_minutes'] > typical * 1.5
                    ).astype(int)
        
        return features
    
    def learn_room_patterns(self, db: Database):
        """
        Lernt typische Muster pro Raum aus historischen Daten.
        Wird vor dem Training aufgerufen.
        """
        try:
            conn = db._get_connection()
            cursor = conn.cursor()
            
            # Durchschnittliche Einschaltdauer pro Raum aus lighting_events
            cursor.execute("""
                SELECT room_name,
                       AVG(CASE WHEN state = 'on' THEN 1 ELSE 0 END) as avg_on_ratio,
                       COUNT(*) as event_count
                FROM lighting_events
                WHERE room_name IS NOT NULL
                GROUP BY room_name
            """)
            
            for row in cursor.fetchall():
                room = row[0]
                self.room_stats[room] = {
                    'avg_on_ratio': row[1],
                    'event_count': row[2],
                    'typical_duration': 60  # Default, wird später verfeinert
                }
            
            logger.info(f"Learned patterns for {len(self.room_stats)} rooms")
            
        except Exception as e:
            logger.warning(f"Could not learn room patterns: {e}")
    
    def prepare_training_data(self, db: Database) -> Tuple[pd.DataFrame, pd.Series]:
        """
        Bereitet Trainingsdaten aus der Datenbank vor.
        
        Labels:
        - 0 = Normal ausgeschaltet (Benutzer hat aktiv ausgeschaltet)
        - 1 = Vergessen (Lampe war sehr lange an ohne Aktivität)
        """
        try:
            conn = db._get_connection()
            cursor = conn.cursor()
            
            # Hole Lighting Events mit Kontext
            cursor.execute("""
                SELECT 
                    le.timestamp,
                    le.device_id,
                    le.device_name,
                    le.room_name,
                    le.state,
                    le.brightness,
                    le.hour_of_day,
                    le.day_of_week,
                    le.is_weekend,
                    le.outdoor_light,
                    le.presence,
                    le.motion_detected
                FROM lighting_events le
                ORDER BY le.device_id, le.timestamp
            """)
            
            rows = cursor.fetchall()
            if len(rows) < self.min_samples:
                logger.warning(f"Not enough data: {len(rows)} < {self.min_samples}")
                return pd.DataFrame(), pd.Series()
            
            # Konvertiere zu DataFrame
            df = pd.DataFrame(rows, columns=[
                'timestamp', 'device_id', 'device_name', 'room_name',
                'state', 'brightness', 'hour_of_day', 'day_of_week',
                'is_weekend', 'outdoor_light', 'presence', 'motion_detected'
            ])
            
            # Berechne Features für jedes "ON" Event
            training_samples = []
            
            for device_id in df['device_id'].unique():
                device_df = df[df['device_id'] == device_id].sort_values('timestamp')
                
                on_time = None
                last_motion_time = None
                
                for idx, row in device_df.iterrows():
                    if row['state'] == 'on':
                        on_time = pd.to_datetime(row['timestamp'])
                        if row['motion_detected']:
                            last_motion_time = on_time
                    
                    elif row['state'] == 'off' and on_time:
                        off_time = pd.to_datetime(row['timestamp'])
                        duration = (off_time - on_time).total_seconds() / 60
                        
                        # Motion seit Einschalten
                        if last_motion_time:
                            minutes_since_motion = (off_time - last_motion_time).total_seconds() / 60
                        else:
                            minutes_since_motion = duration
                        
                        # Label: Vergessen wenn sehr lange an ohne Motion
                        # Heuristik: > 2h an UND > 1h ohne Bewegung = vergessen
                        is_forgotten = 1 if (duration > 120 and minutes_since_motion > 60) else 0
                        
                        training_samples.append({
                            'timestamp': off_time,
                            'device_id': device_id,
                            'room_name': row['room_name'],
                            'hour_of_day': off_time.hour,
                            'day_of_week': off_time.weekday(),
                            'is_weekend': 1 if off_time.weekday() >= 5 else 0,
                            'on_duration_minutes': duration,
                            'minutes_since_motion': minutes_since_motion,
                            'presence_home': row['presence'] if row['presence'] else 1,
                            'outdoor_light': row['outdoor_light'] if row['outdoor_light'] else 50,
                            'is_forgotten': is_forgotten
                        })
                        
                        on_time = None
            
            if not training_samples:
                return pd.DataFrame(), pd.Series()
            
            samples_df = pd.DataFrame(training_samples)
            
            # Features erstellen
            X = self._create_features(samples_df)
            y = samples_df['is_forgotten']
            
            logger.info(f"Prepared {len(X)} training samples ({y.sum()} forgotten, {len(y) - y.sum()} normal)")
            
            return X, y
            
        except Exception as e:
            logger.error(f"Error preparing training data: {e}")
            return pd.DataFrame(), pd.Series()
    
    def train(self, db: Database = None, X: pd.DataFrame = None, y: pd.Series = None) -> Dict:
        """
        Trainiert das Modell.
        
        Entweder mit Datenbank (automatische Vorbereitung) oder mit vorbereiteten Daten.
        """
        try:
            # Daten vorbereiten
            if X is None or y is None:
                if db is None:
                    return {'success': False, 'error': 'No data provided'}
                
                # Lerne Raum-Muster
                self.learn_room_patterns(db)
                
                # Bereite Trainingsdaten vor
                X, y = self.prepare_training_data(db)
            
            if len(X) < self.min_samples:
                return {
                    'success': False,
                    'error': f'Not enough data: {len(X)} < {self.min_samples}'
                }
            
            # Train/Test Split
            X_train, X_test, y_train, y_test = train_test_split(
                X, y, test_size=0.2, random_state=42, stratify=y if y.sum() > 5 else None
            )
            
            # Skalierung
            X_train_scaled = self.scaler.fit_transform(X_train)
            X_test_scaled = self.scaler.transform(X_test)
            
            # Modell erstellen und trainieren
            self.model = self._create_model()
            self.model.fit(X_train_scaled, y_train)
            
            # Evaluierung
            y_pred = self.model.predict(X_test_scaled)
            accuracy = accuracy_score(y_test, y_pred)
            
            # Precision/Recall für "vergessen" Klasse
            precision = precision_score(y_test, y_pred, zero_division=0)
            recall = recall_score(y_test, y_pred, zero_division=0)
            
            self.is_trained = True
            
            # Feature Importance
            feature_importance = dict(zip(
                X.columns,
                self.model.feature_importances_
            ))
            
            result = {
                'success': True,
                'samples': len(X),
                'forgotten_samples': int(y.sum()),
                'accuracy': round(accuracy, 3),
                'precision': round(precision, 3),
                'recall': round(recall, 3),
                'feature_importance': feature_importance
            }
            
            logger.info(f"Model trained: {result}")
            return result
            
        except Exception as e:
            logger.error(f"Error training model: {e}")
            return {'success': False, 'error': str(e)}
    
    def predict(self, conditions: Dict) -> Tuple[bool, float]:
        """
        Vorhersage ob eine Lampe vergessen wurde.
        
        Args:
            conditions: Dict mit aktuellen Bedingungen
                - hour_of_day
                - day_of_week
                - on_duration_minutes
                - minutes_since_motion
                - presence_home
                - outdoor_light
                - room_name
        
        Returns:
            (is_forgotten, confidence): (True/False, 0.0-1.0)
        """
        if not self.is_trained or self.model is None:
            # Fallback auf Regelbasiert
            return self._rule_based_prediction(conditions)
        
        try:
            # Erstelle Features
            df = pd.DataFrame([conditions])
            X = self._create_features(df)
            
            # Skalieren
            X_scaled = self.scaler.transform(X)
            
            # Vorhersage
            prediction = self.model.predict(X_scaled)[0]
            probabilities = self.model.predict_proba(X_scaled)[0]
            
            # Confidence für "vergessen" Klasse
            confidence = probabilities[1] if len(probabilities) > 1 else probabilities[0]
            
            return bool(prediction), float(confidence)
            
        except Exception as e:
            logger.error(f"Error in prediction: {e}")
            return self._rule_based_prediction(conditions)
    
    def _rule_based_prediction(self, conditions: Dict) -> Tuple[bool, float]:
        """Fallback auf regelbasierte Vorhersage wenn Modell nicht trainiert"""
        score = 0.0
        
        # Keine Bewegung seit langer Zeit
        minutes_since_motion = conditions.get('minutes_since_motion', 0)
        if minutes_since_motion > 60:
            score += 0.3
        elif minutes_since_motion > 30:
            score += 0.15
        
        # Niemand zu Hause
        if not conditions.get('presence_home', True):
            score += 0.4
        
        # Schlafenszeit
        hour = conditions.get('hour_of_day', 12)
        if hour >= 23 or hour < 6:
            score += 0.2
        
        # Tageslicht
        if conditions.get('outdoor_light', 0) > 200:
            score += 0.1
        
        # Sehr lange an
        duration = conditions.get('on_duration_minutes', 0)
        if duration > 180:
            score += 0.2
        elif duration > 120:
            score += 0.1
        
        is_forgotten = score >= 0.5
        return is_forgotten, min(score, 1.0)
    
    def save(self, path: str = "models/forgotten_light_model.pkl"):
        """Speichert das Modell"""
        if not self.is_trained:
            logger.warning("Model not trained, cannot save")
            return False
        
        try:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            
            model_data = {
                'model': self.model,
                'scaler': self.scaler,
                'room_stats': self.room_stats,
                'feature_columns': self.feature_columns,
                'model_version': self.model_version,
                'is_trained': self.is_trained
            }
            
            joblib.dump(model_data, path)
            logger.info(f"Model saved to {path}")
            return True
            
        except Exception as e:
            logger.error(f"Error saving model: {e}")
            return False
    
    def load(self, path: str = "models/forgotten_light_model.pkl"):
        """Lädt das Modell"""
        try:
            if not Path(path).exists():
                logger.warning(f"Model file not found: {path}")
                return False
            
            model_data = joblib.load(path)
            
            self.model = model_data['model']
            self.scaler = model_data['scaler']
            self.room_stats = model_data.get('room_stats', {})
            self.feature_columns = model_data.get('feature_columns', self.feature_columns)
            self.model_version = model_data.get('model_version', '1.0.0')
            self.is_trained = model_data.get('is_trained', True)
            
            logger.info(f"Model loaded from {path}")
            return True
            
        except Exception as e:
            logger.error(f"Error loading model: {e}")
            return False
