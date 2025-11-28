"""Machine Learning Modell für intelligente Beleuchtungssteuerung"""

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.model_selection import train_test_split, cross_val_score
from sklearn.metrics import accuracy_score, classification_report
from datetime import datetime
import joblib
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from loguru import logger


class LightingModel:
    """
    ML-Modell zur Vorhersage, ob Licht an oder aus sein sollte
    Lernt aus Verhaltensmustern und Umgebungsbedingungen
    """

    def __init__(self, model_type: str = "random_forest"):
        self.model_type = model_type
        self.model = None
        self.feature_columns = [
            'hour_of_day',
            'day_of_week',
            'brightness',
            'motion_detected',
            'presence_home',
            'weather_condition_clear',
            'weather_condition_cloudy',
            'weather_condition_rainy',
            'is_weekend',
            'is_evening',
            'is_night'
        ]
        self.model_version = "1.0.0"

    def _create_features(self, data: pd.DataFrame) -> pd.DataFrame:
        """
        Erstellt Features aus Rohdaten
        """
        features = pd.DataFrame()

        # Zeit-basierte Features
        if 'timestamp' in data.columns:
            data['timestamp'] = pd.to_datetime(data['timestamp'])
            features['hour_of_day'] = data['timestamp'].dt.hour
            features['day_of_week'] = data['timestamp'].dt.dayofweek
            features['is_weekend'] = (data['timestamp'].dt.dayofweek >= 5).astype(int)
            features['is_evening'] = ((data['timestamp'].dt.hour >= 18) &
                                     (data['timestamp'].dt.hour < 23)).astype(int)
            features['is_night'] = ((data['timestamp'].dt.hour >= 23) |
                                   (data['timestamp'].dt.hour < 6)).astype(int)
        elif 'hour_of_day' in data.columns:
            # Bereits vorberechnete Zeit-Features aus der Datenbank
            features['hour_of_day'] = data['hour_of_day'].fillna(0).astype(int)
            features['day_of_week'] = data.get('day_of_week', pd.Series([0] * len(data))).fillna(0).astype(int)
            features['is_weekend'] = data.get('is_weekend', pd.Series([0] * len(data))).fillna(0).astype(int)
            features['is_evening'] = ((data['hour_of_day'] >= 18) & (data['hour_of_day'] < 23)).astype(int)
            features['is_night'] = ((data['hour_of_day'] >= 23) | (data['hour_of_day'] < 6)).astype(int)

        # Sensor-Features - sichere Extraktion
        if 'brightness' in data.columns:
            features['brightness'] = data['brightness'].fillna(0).astype(float)
        else:
            features['brightness'] = 0
            
        if 'motion_detected' in data.columns:
            features['motion_detected'] = data['motion_detected'].fillna(0).astype(int)
        else:
            features['motion_detected'] = 0
            
        if 'presence' in data.columns:
            features['presence_home'] = data['presence'].fillna(1).astype(int)
        elif 'presence_home' in data.columns:
            features['presence_home'] = data['presence_home'].fillna(1).astype(int)
        else:
            features['presence_home'] = 1
            
        # Außenlicht
        if 'outdoor_light' in data.columns:
            features['outdoor_light'] = data['outdoor_light'].fillna(50).astype(float)
        else:
            features['outdoor_light'] = 50

        # Wetter-Features - vereinfacht für DB ohne Wetterdaten
        features['weather_condition_clear'] = 1
        features['weather_condition_cloudy'] = 0
        features['weather_condition_rainy'] = 0
        
        # Feature Engineering: Rolling Averages (nur wenn genug Daten)
        if len(data) >= 3 and 'brightness' in data.columns:
            features['brightness_rolling_3'] = data['brightness'].fillna(0).rolling(window=3, min_periods=1).mean()
            if 'motion_detected' in data.columns:
                features['motion_rolling_3'] = data['motion_detected'].fillna(0).rolling(window=3, min_periods=1).mean()
            else:
                features['motion_rolling_3'] = 0
        else:
            features['brightness_rolling_3'] = features.get('brightness', 0)
            features['motion_rolling_3'] = 0
        
        # Feature Engineering: Trends
        if len(data) >= 2 and 'brightness' in data.columns:
            features['brightness_trend'] = data['brightness'].fillna(0).diff().fillna(0)
        else:
            features['brightness_trend'] = 0
        
        # Feature Engineering: Saisonale Features
        if 'timestamp' in data.columns:
            features['month'] = data['timestamp'].dt.month
            features['is_winter'] = data['timestamp'].dt.month.isin([12, 1, 2]).astype(int)
            features['is_summer'] = data['timestamp'].dt.month.isin([6, 7, 8]).astype(int)

        return features

    def _remove_outliers(self, data: pd.DataFrame, column: str) -> pd.DataFrame:
        """
        Entfernt Ausreißer mittels IQR-Methode
        
        Args:
            data: DataFrame mit den Daten
            column: Spaltenname für Ausreißer-Erkennung
        
        Returns:
            DataFrame ohne Ausreißer
        """
        if column not in data.columns or data[column].isnull().all():
            return data
        
        Q1 = data[column].quantile(0.25)
        Q3 = data[column].quantile(0.75)
        IQR = Q3 - Q1
        
        lower_bound = Q1 - 1.5 * IQR
        upper_bound = Q3 + 1.5 * IQR
        
        outliers_before = len(data)
        data = data[(data[column] >= lower_bound) & (data[column] <= upper_bound)]
        outliers_removed = outliers_before - len(data)
        
        if outliers_removed > 0:
            logger.info(f"Removed {outliers_removed} outliers from {column} ({outliers_removed/outliers_before*100:.1f}%)")
        
        return data

    def prepare_training_data(self, sensor_data: List[Dict],
                            light_states: List[Dict]) -> Tuple[pd.DataFrame, pd.Series]:
        """
        Bereitet Trainingsdaten vor

        Args:
            sensor_data: Liste von Sensor-Readings
            light_states: Liste von tatsächlichen Lichtzuständen (Labels)
        """
        # Konvertiere zu DataFrames
        df_sensors = pd.DataFrame(sensor_data)
        df_lights = pd.DataFrame(light_states)

        # Merge basierend auf Zeitstempel (mit Toleranz)
        df_sensors['timestamp'] = pd.to_datetime(df_sensors['timestamp'])
        df_lights['timestamp'] = pd.to_datetime(df_lights['timestamp'])

        # Sortiere nach Zeit
        df_sensors = df_sensors.sort_values('timestamp')
        df_lights = df_lights.sort_values('timestamp')

        # Merge mit nearest timestamp
        merged = pd.merge_asof(
            df_sensors,
            df_lights[['timestamp', 'light_state']],
            on='timestamp',
            direction='nearest',
            tolerance=pd.Timedelta('5min')
        )

        # Entferne NaN-Werte
        merged = merged.dropna()
        
        # Ausreißer-Erkennung für Brightness
        if 'brightness' in merged.columns:
            merged = self._remove_outliers(merged, 'brightness')

        # Erstelle Features
        X = self._create_features(merged)
        y = merged['light_state'].astype(int)

        return X, y

    def prepare_training_data_direct(self, light_events: List[Dict]) -> Tuple[pd.DataFrame, pd.Series]:
        """
        Bereitet Trainingsdaten direkt aus lighting_events vor (ohne Merge)
        
        Diese Methode wird verwendet wenn die lighting_events Tabelle bereits
        alle nötigen Daten enthält (brightness, motion_detected, ambient_light, etc.)

        Args:
            light_events: Liste von Events aus der lighting_events Tabelle
        
        Returns:
            X (Features), y (Labels)
        """
        if not light_events:
            return pd.DataFrame(), pd.Series()
            
        df = pd.DataFrame(light_events)
        
        # Timestamp konvertieren
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        
        # Sortieren
        df = df.sort_values('timestamp')
        
        # Normalisiere Spaltennamen - DB kann 'state' oder 'light_state' haben
        if 'state' in df.columns and 'light_state' not in df.columns:
            df['light_state'] = df['state'].apply(lambda x: 1 if x in ['on', 1, '1', True] else 0)
        elif 'light_state' in df.columns:
            df['light_state'] = df['light_state'].apply(lambda x: 1 if x in ['on', 1, '1', True] else 0)
        else:
            logger.error("Neither 'state' nor 'light_state' column found in data")
            return pd.DataFrame(), pd.Series()
            
        df = df.dropna(subset=['light_state'])
        
        if len(df) < 50:
            logger.warning(f"Not enough data after cleaning: {len(df)} samples")
            return pd.DataFrame(), pd.Series()
        
        # Erstelle Features direkt aus den vorhandenen Daten
        X = self._create_features(df)
        y = df['light_state'].astype(int)

        logger.info(f"Prepared {len(X)} training samples from direct data")
        return X, y

    def train(self, X: pd.DataFrame, y: pd.Series) -> Dict:
        """
        Trainiert das Modell

        Returns:
            Metriken als Dictionary
        """
        if len(X) < 50:
            logger.warning(f"Not enough training data: {len(X)} samples")
            return {'error': 'insufficient_data', 'samples': len(X)}

        # Train-Test Split
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.2, random_state=42
        )

        # Modell erstellen
        if self.model_type == "random_forest":
            self.model = RandomForestClassifier(
                n_estimators=100,
                max_depth=10,
                min_samples_split=5,
                random_state=42
            )
        elif self.model_type == "gradient_boosting":
            self.model = GradientBoostingClassifier(
                n_estimators=100,
                max_depth=5,
                learning_rate=0.1,
                random_state=42
            )
        else:
            raise ValueError(f"Unknown model type: {self.model_type}")

        # Training
        logger.info(f"Training {self.model_type} with {len(X_train)} samples")
        
        # Cross-Validation vor finalem Training
        logger.info(f"Running 5-Fold Cross-Validation...")
        cv_scores = cross_val_score(self.model, X, y, cv=5, scoring='accuracy')
        cv_mean = cv_scores.mean()
        cv_std = cv_scores.std()
        logger.info(f"Cross-Validation Accuracy: {cv_mean:.4f} (+/- {cv_std:.4f})")
        
        self.model.fit(X_train, y_train)

        # Evaluation
        y_pred = self.model.predict(X_test)
        accuracy = accuracy_score(y_test, y_pred)

        # Feature Importance
        feature_importance = dict(zip(
            self.feature_columns,
            self.model.feature_importances_
        ))

        logger.info(f"Model trained with accuracy: {accuracy:.2%}")

        return {
            'accuracy': float(accuracy),
            'cv_accuracy_mean': float(cv_mean),
            'cv_accuracy_std': float(cv_std),
            'samples_train': len(X_train),
            'samples_test': len(X_test),
            'feature_importance': feature_importance,
            'model_type': self.model_type,
            'version': self.model_version
        }

    def predict(self, current_conditions: Dict) -> Tuple[int, float]:
        """
        Vorhersage ob Licht an sein sollte

        Args:
            current_conditions: Aktuelle Bedingungen (Sensordaten)

        Returns:
            (prediction, confidence): (0=aus, 1=an), confidence (0-1)
        """
        if self.model is None:
            raise ValueError("Model not trained yet")

        # Erstelle Feature-DataFrame
        df = pd.DataFrame([current_conditions])
        X = self._create_features(df)

        # Stelle sicher, dass alle Features vorhanden sind
        for col in self.feature_columns:
            if col not in X.columns:
                X[col] = 0

        X = X[self.feature_columns]

        # Vorhersage
        prediction = self.model.predict(X)[0]
        probabilities = self.model.predict_proba(X)[0]
        confidence = probabilities[prediction]

        return int(prediction), float(confidence)

    def save(self, path: str = "models/lighting_model.pkl"):
        """Speichert das trainierte Modell"""
        if self.model is None:
            raise ValueError("No model to save")

        Path(path).parent.mkdir(parents=True, exist_ok=True)

        model_data = {
            'model': self.model,
            'model_type': self.model_type,
            'feature_columns': self.feature_columns,
            'version': self.model_version,
            'trained_at': datetime.now().isoformat()
        }

        joblib.dump(model_data, path)
        logger.info(f"Model saved to {path}")

    def load(self, path: str = "models/lighting_model.pkl"):
        """Lädt ein trainiertes Modell"""
        if not Path(path).exists():
            raise FileNotFoundError(f"Model file not found: {path}")

        model_data = joblib.load(path)

        self.model = model_data['model']
        self.model_type = model_data['model_type']
        self.feature_columns = model_data['feature_columns']
        self.model_version = model_data['version']

        logger.info(f"Model loaded from {path}")

    def explain_prediction(self, current_conditions: Dict) -> Dict:
        """
        Erklärt eine Vorhersage durch Feature-Importance
        """
        prediction, confidence = self.predict(current_conditions)

        # Hol Feature-Importance
        feature_importance = dict(zip(
            self.feature_columns,
            self.model.feature_importances_
        ))

        # Sortiere nach Wichtigkeit
        sorted_features = sorted(
            feature_importance.items(),
            key=lambda x: x[1],
            reverse=True
        )[:5]

        return {
            'prediction': 'ON' if prediction == 1 else 'OFF',
            'confidence': confidence,
            'top_factors': [
                {'feature': feat, 'importance': imp}
                for feat, imp in sorted_features
            ],
            'current_conditions': current_conditions
        }
