"""
Flask Blueprints für KI-System Web Interface
Aufgeteilt für bessere Wartbarkeit und Übersichtlichkeit
"""

# Validators zuerst importieren (werden von anderen Modulen verwendet)
from .validators import validate_request, validate_json_body, FieldValidator, Validators

# Import der Blueprints mit Init-Funktionen
from .api_config import config_bp, init_config_blueprint
from .api_ml import ml_bp, init_ml_blueprint
from .api_ventilation import ventilation_bp, init_ventilation_blueprint
from .api_bathroom import bathroom_bp, init_bathroom_blueprint

__all__ = [
    # Blueprints
    'config_bp',
    'ml_bp',
    'ventilation_bp',
    'bathroom_bp',
    # Init-Funktionen
    'init_config_blueprint',
    'init_ml_blueprint',
    'init_ventilation_blueprint',
    'init_bathroom_blueprint',
    # Validators
    'validate_request',
    'validate_json_body',
    'FieldValidator',
    'Validators'
]
