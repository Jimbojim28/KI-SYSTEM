"""Machine Learning Modell für intelligente Temperaturregelung"""

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
from sklearn.model_selection import train_test_split, cross_val_score
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from datetime import datetime, timedelta
import joblib
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from loguru import logger


class TemperatureModel:
    """
    ML-Modell zur Vorhersage der optimalen Temperatur
    Lernt aus Nutzerverhalten, Wetter und Energiepreisen
    """

    def __init__(self, model_type: str = "gradient_boosting"):
        self.model_type = model_type
        self.model = None
        self.feature_columns = [
            'hour_of_day',
            'day_of_week',
            'outdoor_temperature',
            'current_temperature',
            'presence_home',
            'is_sleeping_hours',
            'is_work_hours',
            'weather_condition',
            'energy_price_level',
            'is_weekend',
            'humidity'
        ]
        self.model_version = "1.0.0"

    def _create_features(self, data: pd.DataFrame) -> pd.DataFrame:
        """Erstellt Features aus Rohdaten"""
        features = pd.DataFrame()

        # Zeit-basierte Features
        if 'timestamp' in data.columns:
            data['timestamp'] = pd.to_datetime(data['timestamp'])
            features['hour_of_day'] = data['timestamp'].dt.hour
            features['day_of_week'] = data['timestamp'].dt.dayofweek
            features['is_weekend'] = (data['timestamp'].dt.dayofweek >= 5).astype(int)

            # Schlafenszeit (22:00 - 07:00)
            features['is_sleeping_hours'] = (
                (data['timestamp'].dt.hour >= 22) |
                (data['timestamp'].dt.hour < 7)
            ).astype(int)

            # Arbeitszeit (08:00 - 18:00 an Werktagen)
            features['is_work_hours'] = (
                (data['timestamp'].dt.hour >= 8) &
                (data['timestamp'].dt.hour < 18) &
                (data['timestamp'].dt.dayofweek < 5)
            ).astype(int)

        # Temperatur-Features
        features['outdoor_temperature'] = data.get('outdoor_temperature', 15.0)
        features['current_temperature'] = data.get('current_temperature', 20.0)
        features['humidity'] = data.get('humidity', 50.0)

        # Anwesenheit
        features['presence_home'] = data.get('presence_home', 1).astype(int)

        # Wetter (kodiert als Zahl)
        weather_mapping = {
            'clear': 1,
            'clouds': 2,
            'rain': 3,
            'snow': 4,
            'storm': 5
        }
        weather = data.get('weather_condition', 'clear').str.lower()
        features['weather_condition'] = weather.map(weather_mapping).fillna(1)

        # Energiepreis Level (1=günstig, 2=mittel, 3=teuer)
        features['energy_price_level'] = data.get('energy_price_level', 2)
        
        # Feature Engineering: Rolling Averages
        if len(data) >= 6:
            features['temp_rolling_6h'] = data.get('current_temperature', 20.0).rolling(window=6, min_periods=1).mean()
            features['outdoor_temp_rolling_6h'] = data.get('outdoor_temperature', 15.0).rolling(window=6, min_periods=1).mean()
        
        if len(data) >= 24:
            features['temp_rolling_24h'] = data.get('current_temperature', 20.0).rolling(window=24, min_periods=1).mean()
        
        # Feature Engineering: Trends
        if len(data) >= 2:
            features['temp_trend'] = data.get('current_temperature', 20.0).diff().fillna(0)
            features['outdoor_temp_trend'] = data.get('outdoor_temperature', 15.0).diff().fillna(0)
        
        # Feature Engineering: Saisonale Features
        if 'timestamp' in data.columns:
            features['month'] = data['timestamp'].dt.month
            features['is_winter'] = data['timestamp'].dt.month.isin([12, 1, 2]).astype(int)
            features['is_summer'] = data['timestamp'].dt.month.isin([6, 7, 8]).astype(int)
            features['is_transition'] = data['timestamp'].dt.month.isin([3, 4, 5, 9, 10, 11]).astype(int)
        
        # Feature Engineering: Temperatur-Differenz
        features['temp_diff'] = data.get('current_temperature', 20.0) - data.get('outdoor_temperature', 15.0)

        return features

    def _remove_outliers(self, data: pd.DataFrame, columns: List[str]) -> pd.DataFrame:
        """
        Entfernt Ausreißer mittels IQR-Methode für mehrere Spalten
        
        Args:
            data: DataFrame mit den Daten
            columns: Liste von Spaltennamen für Ausreißer-Erkennung
        
        Returns:
            DataFrame ohne Ausreißer
        """
        original_len = len(data)
        
        for column in columns:
            if column not in data.columns or data[column].isnull().all():
                continue
            
            Q1 = data[column].quantile(0.25)
            Q3 = data[column].quantile(0.75)
            IQR = Q3 - Q1
            
            lower_bound = Q1 - 1.5 * IQR
            upper_bound = Q3 + 1.5 * IQR
            
            data = data[(data[column] >= lower_bound) & (data[column] <= upper_bound)]
        
        outliers_removed = original_len - len(data)
        if outliers_removed > 0:
            logger.info(f"Removed {outliers_removed} outliers total ({outliers_removed/original_len*100:.1f}%)")
        
        return data

    def prepare_training_data(self, sensor_data: List[Dict],
                            temperature_settings: List[Dict]) -> Tuple[pd.DataFrame, pd.Series]:
        """
        Bereitet Trainingsdaten vor

        Args:
            sensor_data: Sensor-Daten (Temperatur, Wetter, etc.)
            temperature_settings: Tatsächliche Temperatur-Sollwerte (vom Nutzer gesetzt)
        """
        df_sensors = pd.DataFrame(sensor_data)
        df_settings = pd.DataFrame(temperature_settings)

        df_sensors['timestamp'] = pd.to_datetime(df_sensors['timestamp'])
        df_settings['timestamp'] = pd.to_datetime(df_settings['timestamp'])

        # Merge
        merged = pd.merge_asof(
            df_sensors.sort_values('timestamp'),
            df_settings[['timestamp', 'target_temperature']].sort_values('timestamp'),
            on='timestamp',
            direction='nearest',
            tolerance=pd.Timedelta('10min')
        )

        merged = merged.dropna()
        
        # Ausreißer-Erkennung für Temperaturwerte und Humidity
        outlier_columns = ['current_temperature', 'target_temperature', 'outdoor_temperature', 'humidity']
        merged = self._remove_outliers(merged, outlier_columns)

        # Features und Labels
        X = self._create_features(merged)
        y = merged['target_temperature']

        return X, y

    def prepare_training_data_direct(self, measurements: List[Dict]) -> Tuple[pd.DataFrame, pd.Series]:
        """
        Bereitet Trainingsdaten direkt aus continuous_measurements vor.
        Diese Methode funktioniert mit der neuen Tabellenstruktur.

        Args:
            measurements: Liste von Messungen mit allen notwendigen Feldern

        Returns:
            X (Features DataFrame), y (Target Series)
        """
        if not measurements:
            return pd.DataFrame(), pd.Series()

        df = pd.DataFrame(measurements)

        # Timestamp konvertieren
        df['timestamp'] = pd.to_datetime(df['timestamp'])

        # Prüfe, ob wir target_temp haben (sonst können wir nicht trainieren)
        if 'target_temp' not in df.columns or df['target_temp'].isna().all():
            # Versuche heating_active als Proxy zu verwenden
            if 'heating_active' in df.columns:
                # Wenn Heizung aktiv war, nehme aktuellen Wert + 1 als Ziel
                # Das ist ein einfacher Heuristik-Ansatz
                df['target_temp'] = df.apply(
                    lambda row: row['value'] + 1.0 if row.get('heating_active') else row['value'],
                    axis=1
                )
            else:
                logger.warning("No target_temp or heating_active available for training")
                return pd.DataFrame(), pd.Series()

        # Kopiere Werte für _create_features
        df['current_temperature'] = df['value']
        df['outdoor_temperature'] = df.get('outdoor_temp', df['outdoor_temp'] if 'outdoor_temp' in df.columns else 15.0)
        df['humidity'] = df.get('humidity', 50.0)
        df['target_temperature'] = df['target_temp']

        # Fülle fehlende Werte
        df['outdoor_temperature'] = df['outdoor_temperature'].fillna(15.0)
        df['humidity'] = df['humidity'].fillna(50.0)
        df['current_temperature'] = df['current_temperature'].fillna(20.0)

        # Presence - schätze anhand der Zeit
        df['presence_home'] = df['timestamp'].dt.hour.apply(
            lambda h: 1 if h < 8 or h >= 18 else 0
        )

        # Weather condition (default: bewölkt = 1)
        df['weather_condition'] = 1

        # Energy price level (default: mittel = 2)
        df['energy_price_level'] = 2

        # Entferne Zeilen ohne target_temp
        df = df.dropna(subset=['target_temperature'])

        if len(df) < 10:
            logger.warning(f"Not enough valid samples: {len(df)}")
            return pd.DataFrame(), pd.Series()

        # Ausreißer-Erkennung
        outlier_columns = ['current_temperature', 'target_temperature', 'outdoor_temperature', 'humidity']
        df = self._remove_outliers(df, [c for c in outlier_columns if c in df.columns])

        # Features erstellen
        X = self._create_features(df)
        y = df['target_temperature']

        return X, y

    def train(self, X: pd.DataFrame, y: pd.Series) -> Dict:
        """Trainiert das Modell"""
        if len(X) < 100:
            logger.warning(f"Not enough training data: {len(X)} samples")
            return {'error': 'insufficient_data', 'samples': len(X)}

        # Train-Test Split
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.2, random_state=42
        )

        # Modell erstellen
        if self.model_type == "gradient_boosting":
            self.model = GradientBoostingRegressor(
                n_estimators=150,
                max_depth=5,
                learning_rate=0.1,
                min_samples_split=5,
                random_state=42
            )
        elif self.model_type == "random_forest":
            self.model = RandomForestRegressor(
                n_estimators=100,
                max_depth=10,
                min_samples_split=5,
                random_state=42
            )
        else:
            raise ValueError(f"Unknown model type: {self.model_type}")

        # Training
        logger.info(f"Training {self.model_type} with {len(X_train)} samples")
        
        # Cross-Validation vor finalem Training
        logger.info(f"Running 5-Fold Cross-Validation...")
        cv_scores_mae = -cross_val_score(self.model, X, y, cv=5, scoring='neg_mean_absolute_error')
        cv_scores_r2 = cross_val_score(self.model, X, y, cv=5, scoring='r2')
        cv_mae_mean = cv_scores_mae.mean()
        cv_mae_std = cv_scores_mae.std()
        cv_r2_mean = cv_scores_r2.mean()
        cv_r2_std = cv_scores_r2.std()
        logger.info(f"Cross-Validation MAE: {cv_mae_mean:.4f} (+/- {cv_mae_std:.4f})")
        logger.info(f"Cross-Validation R²: {cv_r2_mean:.4f} (+/- {cv_r2_std:.4f})")
        
        self.model.fit(X_train, y_train)

        # Evaluation
        y_pred = self.model.predict(X_test)
        mae = mean_absolute_error(y_test, y_pred)
        rmse = np.sqrt(mean_squared_error(y_test, y_pred))
        r2 = r2_score(y_test, y_pred)

        # Feature Importance
        feature_importance = dict(zip(
            self.feature_columns,
            self.model.feature_importances_
        ))

        logger.info(f"Model trained - MAE: {mae:.2f}°C, RMSE: {rmse:.2f}°C, R²: {r2:.3f}")

        return {
            'mae': float(mae),
            'rmse': float(rmse),
            'r2_score': float(r2),
            'cv_mae_mean': float(cv_mae_mean),
            'cv_mae_std': float(cv_mae_std),
            'cv_r2_mean': float(cv_r2_mean),
            'cv_r2_std': float(cv_r2_std),
            'samples_train': len(X_train),
            'samples_test': len(X_test),
            'feature_importance': feature_importance,
            'model_type': self.model_type,
            'version': self.model_version
        }

    def predict(self, current_conditions: Dict) -> Tuple[float, Dict]:
        """
        Vorhersage der optimalen Temperatur

        Returns:
            (temperature, metadata): Empfohlene Temperatur und zusätzliche Info
        """
        if self.model is None:
            raise ValueError("Model not trained yet")

        # Feature-DataFrame erstellen
        df = pd.DataFrame([current_conditions])
        X = self._create_features(df)

        # Stelle sicher, dass alle Features vorhanden sind
        for col in self.feature_columns:
            if col not in X.columns:
                X[col] = 0

        X = X[self.feature_columns]

        # Vorhersage
        temperature = self.model.predict(X)[0]

        # Runde auf 0.5°C
        temperature = round(temperature * 2) / 2

        # Sichere Grenzen
        temperature = max(16.0, min(25.0, temperature))

        metadata = {
            'raw_prediction': float(self.model.predict(X)[0]),
            'rounded_temperature': float(temperature),
            'conditions': current_conditions
        }

        return float(temperature), metadata

    def predict_with_energy_optimization(self, current_conditions: Dict,
                                        energy_price_level: int) -> Tuple[float, Dict]:
        """
        Vorhersage mit Energieoptimierung

        Args:
            current_conditions: Aktuelle Bedingungen
            energy_price_level: 1=günstig, 2=mittel, 3=teuer

        Returns:
            Angepasste Temperatur basierend auf Energiepreis
        """
        # Normale Vorhersage
        base_temp, metadata = self.predict(current_conditions)

        # Anpassung basierend auf Energiepreis
        adjustments = {
            1: 0.0,    # Günstig: keine Anpassung
            2: -0.5,   # Mittel: leicht reduzieren
            3: -1.0    # Teuer: stärker reduzieren
        }

        adjustment = adjustments.get(energy_price_level, 0)

        # Bei Anwesenheit weniger stark anpassen
        if current_conditions.get('presence_home', 1) == 1:
            adjustment *= 0.5

        optimized_temp = base_temp + adjustment

        # Sichere Grenzen
        optimized_temp = max(18.0, min(23.0, optimized_temp))

        metadata['base_temperature'] = base_temp
        metadata['energy_adjustment'] = adjustment
        metadata['optimized_temperature'] = optimized_temp
        metadata['energy_price_level'] = energy_price_level

        return float(optimized_temp), metadata

    def predict_schedule(self, forecast_data: List[Dict],
                        hours_ahead: int = 24) -> List[Dict]:
        """
        Erstellt einen Temperatur-Plan für die nächsten Stunden

        Args:
            forecast_data: Wetter- und Preis-Vorhersagen
            hours_ahead: Anzahl Stunden im Voraus

        Returns:
            Liste von {timestamp, temperature, reasoning}
        """
        schedule = []

        for hour_data in forecast_data[:hours_ahead]:
            temp, metadata = self.predict_with_energy_optimization(
                hour_data,
                hour_data.get('energy_price_level', 2)
            )

            schedule.append({
                'timestamp': hour_data.get('timestamp'),
                'target_temperature': temp,
                'outdoor_temp': hour_data.get('outdoor_temperature'),
                'energy_level': hour_data.get('energy_price_level'),
                'reasoning': metadata
            })

        return schedule

    def save(self, path: str = "models/temperature_model.pkl"):
        """Speichert das Modell"""
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

    def load(self, path: str = "models/temperature_model.pkl"):
        """Lädt ein trainiertes Modell"""
        if not Path(path).exists():
            raise FileNotFoundError(f"Model file not found: {path}")

        model_data = joblib.load(path)

        self.model = model_data['model']
        self.model_type = model_data['model_type']
        self.feature_columns = model_data['feature_columns']
        self.model_version = model_data['version']

        logger.info(f"Model loaded from {path}")
