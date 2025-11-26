"""
Input Validierung für API-Requests
Bietet Type-Safety und Sicherheit durch Validierung
"""

from functools import wraps
from flask import request, jsonify
from typing import Dict, Any, List, Optional, Callable, Type, Union
from dataclasses import dataclass
from loguru import logger
import re


class ValidationError(Exception):
    """Custom Exception für Validierungsfehler"""
    def __init__(self, message: str, field: Optional[str] = None):
        self.message = message
        self.field = field
        super().__init__(message)


@dataclass
class FieldValidator:
    """Validator für einzelne Felder"""
    field_type: Type = str
    required: bool = True
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    min_length: Optional[int] = None
    max_length: Optional[int] = None
    pattern: Optional[str] = None
    allowed_values: Optional[List[Any]] = None
    default: Any = None
    
    def validate(self, value: Any, field_name: str) -> Any:
        """Validiert einen Wert gegen die Regeln"""
        
        # Prüfe ob Pflichtfeld fehlt
        if value is None:
            if self.required:
                raise ValidationError(f"Pflichtfeld '{field_name}' fehlt", field_name)
            return self.default
        
        # Type-Konvertierung
        try:
            if self.field_type == bool:
                if isinstance(value, bool):
                    converted = value
                elif isinstance(value, str):
                    converted = value.lower() in ('true', '1', 'yes', 'ja')
                else:
                    converted = bool(value)
            elif self.field_type == int:
                converted = int(value)
            elif self.field_type == float:
                converted = float(value)
            elif self.field_type == str:
                converted = str(value)
            elif self.field_type == list:
                if not isinstance(value, list):
                    raise ValidationError(f"Feld '{field_name}' muss eine Liste sein", field_name)
                converted = value
            elif self.field_type == dict:
                if not isinstance(value, dict):
                    raise ValidationError(f"Feld '{field_name}' muss ein Objekt sein", field_name)
                converted = value
            else:
                converted = value
        except (ValueError, TypeError):
            raise ValidationError(
                f"Feld '{field_name}' hat ungültigen Typ. Erwartet: {self.field_type.__name__}", 
                field_name
            )
        
        # Wertebereich-Validierung (für Zahlen)
        if self.field_type in (int, float) and isinstance(converted, (int, float)):
            if self.min_value is not None and converted < self.min_value:
                raise ValidationError(
                    f"Feld '{field_name}' muss mindestens {self.min_value} sein", 
                    field_name
                )
            if self.max_value is not None and converted > self.max_value:
                raise ValidationError(
                    f"Feld '{field_name}' darf maximal {self.max_value} sein", 
                    field_name
                )
        
        # Längen-Validierung (für Strings)
        if self.field_type == str and isinstance(converted, str):
            if self.min_length is not None and len(converted) < self.min_length:
                raise ValidationError(
                    f"Feld '{field_name}' muss mindestens {self.min_length} Zeichen haben", 
                    field_name
                )
            if self.max_length is not None and len(converted) > self.max_length:
                raise ValidationError(
                    f"Feld '{field_name}' darf maximal {self.max_length} Zeichen haben", 
                    field_name
                )
        
        # Pattern-Validierung (für Strings)
        if self.pattern and self.field_type == str and isinstance(converted, str):
            if not re.match(self.pattern, converted):
                raise ValidationError(
                    f"Feld '{field_name}' entspricht nicht dem erwarteten Format", 
                    field_name
                )
        
        # Erlaubte Werte prüfen
        if self.allowed_values is not None:
            if converted not in self.allowed_values:
                raise ValidationError(
                    f"Feld '{field_name}' muss einer der Werte sein: {self.allowed_values}", 
                    field_name
                )
        
        return converted


class Validators:
    """Vordefinierte Validatoren für häufige Anwendungsfälle"""
    
    @staticmethod
    def temperature(required: bool = True) -> FieldValidator:
        """Temperatur-Validator (5-35°C)"""
        return FieldValidator(
            field_type=float,
            required=required,
            min_value=5.0,
            max_value=35.0
        )
    
    @staticmethod
    def humidity(required: bool = True) -> FieldValidator:
        """Luftfeuchtigkeit-Validator (0-100%)"""
        return FieldValidator(
            field_type=float,
            required=required,
            min_value=0.0,
            max_value=100.0
        )
    
    @staticmethod
    def brightness(required: bool = True) -> FieldValidator:
        """Helligkeit-Validator (0-100% oder 0-255)"""
        return FieldValidator(
            field_type=int,
            required=required,
            min_value=0,
            max_value=255
        )
    
    @staticmethod
    def percentage(required: bool = True) -> FieldValidator:
        """Prozent-Validator (0-100)"""
        return FieldValidator(
            field_type=float,
            required=required,
            min_value=0.0,
            max_value=100.0
        )
    
    @staticmethod
    def device_id(required: bool = True) -> FieldValidator:
        """Geräte-ID Validator (nicht leer, max 100 Zeichen)"""
        return FieldValidator(
            field_type=str,
            required=required,
            min_length=1,
            max_length=100
        )
    
    @staticmethod
    def entity_id(required: bool = True) -> FieldValidator:
        """Home Assistant Entity-ID Validator"""
        return FieldValidator(
            field_type=str,
            required=required,
            min_length=1,
            max_length=200,
            pattern=r'^[a-z_]+\.[a-z0-9_]+$'
        )
    
    @staticmethod
    def action(allowed_actions: List[str], required: bool = True) -> FieldValidator:
        """Action-Validator mit erlaubten Werten"""
        return FieldValidator(
            field_type=str,
            required=required,
            allowed_values=allowed_actions
        )
    
    @staticmethod
    def boolean(required: bool = False, default: bool = False) -> FieldValidator:
        """Boolean-Validator"""
        return FieldValidator(
            field_type=bool,
            required=required,
            default=default
        )
    
    @staticmethod
    def positive_int(required: bool = True, max_value: int = None) -> FieldValidator:
        """Positive Ganzzahl-Validator"""
        return FieldValidator(
            field_type=int,
            required=required,
            min_value=0,
            max_value=max_value
        )
    
    @staticmethod
    def string(required: bool = True, min_length: int = 1, max_length: int = 500) -> FieldValidator:
        """String-Validator"""
        return FieldValidator(
            field_type=str,
            required=required,
            min_length=min_length,
            max_length=max_length
        )
    
    @staticmethod
    def url(required: bool = True) -> FieldValidator:
        """URL-Validator"""
        return FieldValidator(
            field_type=str,
            required=required,
            pattern=r'^https?://[^\s/$.?#].[^\s]*$',
            max_length=500
        )
    
    @staticmethod
    def token(required: bool = True) -> FieldValidator:
        """Token/API-Key Validator"""
        return FieldValidator(
            field_type=str,
            required=required,
            min_length=10,
            max_length=1000
        )


def validate_request(schema: Dict[str, FieldValidator]) -> Callable:
    """
    Decorator für Request-Validierung
    
    Verwendung:
        @app.route('/api/device/control', methods=['POST'])
        @validate_request({
            'action': Validators.action(['turn_on', 'turn_off', 'set_temperature']),
            'temperature': Validators.temperature(required=False),
            'brightness': Validators.brightness(required=False)
        })
        def control_device():
            data = request.validated_data  # Validierte Daten
            ...
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            # Hole JSON-Daten
            if request.method in ('POST', 'PUT', 'PATCH'):
                data = request.get_json(silent=True) or {}
            else:
                data = request.args.to_dict()
            
            validated_data = {}
            errors = []
            
            # Validiere jedes Feld
            for field_name, validator in schema.items():
                try:
                    value = data.get(field_name)
                    validated_data[field_name] = validator.validate(value, field_name)
                except ValidationError as e:
                    errors.append({
                        'field': e.field,
                        'message': e.message
                    })
            
            if errors:
                return jsonify({
                    'success': False,
                    'errors': errors,
                    'error': 'Validierungsfehler'
                }), 400
            
            # Speichere validierte Daten im Request-Kontext
            request.validated_data = validated_data
            
            return func(*args, **kwargs)
        
        return wrapper
    return decorator


def validate_json_body(
    required_fields: Optional[List[str]] = None, 
    optional_fields: Optional[List[str]] = None
) -> Callable:
    """
    Einfacher Decorator der nur prüft ob JSON-Body vorhanden ist
    und optionale/erforderliche Felder enthält
    """
    _required_fields: List[str] = required_fields or []
    
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            if request.method in ('POST', 'PUT', 'PATCH'):
                data = request.get_json(silent=True)
                
                if data is None:
                    return jsonify({
                        'success': False,
                        'error': 'JSON-Body erforderlich'
                    }), 400
                
                # Prüfe Pflichtfelder
                missing = [f for f in _required_fields if f not in data or data[f] is None]
                if missing:
                    return jsonify({
                        'success': False,
                        'error': f"Pflichtfelder fehlen: {', '.join(missing)}",
                        'missing_fields': missing
                    }), 400
            
            return func(*args, **kwargs)
        return wrapper
    return decorator


__all__ = [
    'validate_request',
    'validate_json_body',
    'Validators',
    'FieldValidator',
    'ValidationError'
]
