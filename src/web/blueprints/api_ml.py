"""
API Blueprint für Machine Learning
Enthält alle Endpoints für ML-Training, Vorhersagen und Modellstatus
"""

from flask import Blueprint, jsonify, request
from loguru import logger
from pathlib import Path
import json
from datetime import datetime
from typing import Optional

from .validators import validate_request, Validators, FieldValidator

ml_bp = Blueprint('ml', __name__, url_prefix='/api')


def init_ml_blueprint(engine, db, model_path: str = 'models'):
    """Initialisiert den Blueprint mit Engine und Database Referenzen"""
    
    @ml_bp.route('/ml/models', methods=['GET'])
    def get_models():
        """Hole Liste aller ML-Modelle"""
        try:
            models = []
            models_dir = Path(model_path)
            
            if models_dir.exists():
                for ext in ['*.pkl', '*.joblib']:
                    for model_file in models_dir.glob(ext):
                        stat = model_file.stat()
                        models.append({
                            'name': model_file.stem,
                            'filename': model_file.name,
                            'size_bytes': stat.st_size,
                            'modified': datetime.fromtimestamp(stat.st_mtime).isoformat()
                        })
            
            return jsonify({
                'success': True,
                'models': models,
                'count': len(models)
            })
        except Exception as e:
            logger.error(f"Error getting models: {e}")
            return jsonify({'error': str(e)}), 500

    @ml_bp.route('/ml/train', methods=['POST'])
    @validate_request({
        'model_type': FieldValidator(
            required=True,
            allowed_values=['heating', 'bathroom', 'ventilation', 'lighting', 'all']
        ),
        'force': Validators.boolean(required=False, default=False)
    })
    def train_model():
        """Starte Training eines ML-Modells"""
        try:
            data = request.validated_data
            model_type = data.get('model_type', 'all')
            force = data.get('force', False)
            
            results = {}
            
            if model_type in ['heating', 'all']:
                try:
                    if hasattr(engine, 'heating_optimizer') and engine.heating_optimizer:
                        success = engine.heating_optimizer.train(force=force)
                        results['heating'] = {
                            'success': success,
                            'message': 'Training abgeschlossen' if success else 'Training fehlgeschlagen'
                        }
                    else:
                        results['heating'] = {'success': False, 'message': 'Nicht verfügbar'}
                except Exception as e:
                    results['heating'] = {'success': False, 'message': str(e)}
            
            if model_type in ['bathroom', 'all']:
                try:
                    if hasattr(engine, 'bathroom_analyzer') and engine.bathroom_analyzer:
                        success = engine.bathroom_analyzer.train()
                        results['bathroom'] = {
                            'success': success,
                            'message': 'Training abgeschlossen' if success else 'Training fehlgeschlagen'
                        }
                    else:
                        results['bathroom'] = {'success': False, 'message': 'Nicht verfügbar'}
                except Exception as e:
                    results['bathroom'] = {'success': False, 'message': str(e)}
            
            if model_type in ['ventilation', 'all']:
                try:
                    if hasattr(engine, 'ventilation_optimizer') and engine.ventilation_optimizer:
                        success = engine.ventilation_optimizer.train()
                        results['ventilation'] = {
                            'success': success,
                            'message': 'Training abgeschlossen' if success else 'Training fehlgeschlagen'
                        }
                    else:
                        results['ventilation'] = {'success': False, 'message': 'Nicht verfügbar'}
                except Exception as e:
                    results['ventilation'] = {'success': False, 'message': str(e)}
            
            all_success = all(r.get('success', False) for r in results.values()) if results else False
            
            return jsonify({
                'success': all_success,
                'results': results
            })
        except Exception as e:
            logger.error(f"Error training model: {e}")
            return jsonify({'error': str(e)}), 500

    @ml_bp.route('/ml/status', methods=['GET'])
    def get_ml_status():
        """Hole Status aller ML-Komponenten"""
        try:
            status = {
                'heating_optimizer': {
                    'available': hasattr(engine, 'heating_optimizer') and engine.heating_optimizer is not None,
                    'trained': False
                },
                'bathroom_analyzer': {
                    'available': hasattr(engine, 'bathroom_analyzer') and engine.bathroom_analyzer is not None,
                    'trained': False
                },
                'ventilation_optimizer': {
                    'available': hasattr(engine, 'ventilation_optimizer') and engine.ventilation_optimizer is not None,
                    'trained': False
                }
            }
            
            # Prüfe ob Modelle trainiert sind
            for key in status:
                if status[key]['available']:
                    try:
                        component = getattr(engine, key.replace('_optimizer', '_optimizer').replace('_analyzer', '_analyzer'), None)
                        if component and hasattr(component, 'is_trained'):
                            status[key]['trained'] = component.is_trained()
                    except Exception:
                        pass
            
            return jsonify({'success': True, 'status': status})
        except Exception as e:
            logger.error(f"Error getting ML status: {e}")
            return jsonify({'error': str(e)}), 500

    @ml_bp.route('/ml/training-data/stats', methods=['GET'])
    def get_training_data_stats():
        """Hole Statistiken über verfügbare Trainingsdaten"""
        try:
            stats = {}
            
            if db:
                tables = ['heating_data', 'bathroom_data', 'temperature_data']
                for table in tables:
                    try:
                        cursor = db.execute(f'''
                            SELECT COUNT(*) as count, 
                                   MIN(timestamp) as first_record,
                                   MAX(timestamp) as last_record
                            FROM {table}
                        ''')
                        row = cursor.fetchone()
                        if row:
                            stats[table.replace('_data', '')] = {
                                'count': row[0],
                                'first_record': row[1],
                                'last_record': row[2]
                            }
                    except Exception as e:
                        logger.debug(f"Could not get {table} stats: {e}")
            
            return jsonify({'success': True, 'stats': stats})
        except Exception as e:
            logger.error(f"Error getting training data stats: {e}")
            return jsonify({'error': str(e)}), 500

    return ml_bp
