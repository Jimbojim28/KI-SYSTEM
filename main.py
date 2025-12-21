#!/usr/bin/env python3
"""
KI-System für Smart Home Automatisierung
Hauptprogramm
"""

import sys
import argparse
import schedule
import time
from pathlib import Path
from loguru import logger

# Füge src zum Python-Path hinzu
sys.path.insert(0, str(Path(__file__).parent))

from src.decision_engine.engine import DecisionEngine
from src.utils.config_loader import ConfigLoader


def setup_logging(config: ConfigLoader):
    """Konfiguriert Logging"""
    log_level = config.get('logging.level', 'INFO')
    log_path = config.get('logging.path', 'logs/ki_system.log')

    # Erstelle logs Verzeichnis
    Path(log_path).parent.mkdir(parents=True, exist_ok=True)

    # Entferne Standard-Handler
    logger.remove()

    # Console Handler
    logger.add(
        sys.stderr,
        level=log_level,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>"
    )

    # File Handler
    logger.add(
        log_path,
        level=log_level,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {message}",
        rotation="10 MB",
        retention="7 days"
    )

    logger.info("Logging configured")


def run_daemon(engine: DecisionEngine, interval: int = 300):
    """
    Daemon-Modus: Führt automatisch alle X Sekunden einen Zyklus aus

    Args:
        engine: DecisionEngine Instanz
        interval: Intervall in Sekunden (default: 300 = 5 Minuten)
    """
    logger.info(f"Starting daemon mode with {interval}s interval")

    def job():
        engine.run_cycle()

    # Führe sofort einmal aus
    job()

    # Plane regelmäßige Ausführung
    schedule.every(interval).seconds.do(job)

    # Main Loop
    try:
        while True:
            schedule.run_pending()
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Daemon stopped by user")


def cmd_test(engine: DecisionEngine):
    """Testet die Verbindungen"""
    logger.info("Testing connections...")
    results = engine.test_connection()

    print("\n=== Connection Test Results ===")
    for service, status in results.items():
        status_icon = "✓" if status else "✗"
        print(f"{status_icon} {service}: {'OK' if status else 'FAILED'}")

    all_ok = all(results.values())
    print(f"\nOverall: {'✓ All systems operational' if all_ok else '✗ Some systems failed'}\n")

    return 0 if all_ok else 1


def cmd_run(engine: DecisionEngine):
    """Führt einen einzelnen Entscheidungs-Zyklus aus"""
    logger.info("Running single cycle...")
    result = engine.run_cycle()

    if result:
        print("\n=== Cycle Results ===")
        print(f"Timestamp: {result['timestamp']}")
        print(f"Lighting actions: {result['lighting_actions']}")
        print(f"Heating actions: {result['heating_actions']}")
        print(f"Total actions: {result['total_actions']}")
        print()
        return 0
    else:
        print("Cycle failed!")
        return 1


def cmd_status(engine: DecisionEngine):
    """Zeigt aktuellen Status an"""
    logger.info("Collecting current status...")

    state = engine.collect_current_state()

    print("\n=== Current System Status ===")
    print(f"Timestamp: {state.get('timestamp')}")
    print(f"\nTemperature:")
    print(f"  Indoor: {state.get('current_temperature', 'N/A')}°C")
    print(f"  Outdoor: {state.get('outdoor_temperature', 'N/A')}°C")
    print(f"  Humidity: {state.get('humidity', 'N/A')}%")

    print(f"\nEnvironment:")
    print(f"  Brightness: {state.get('brightness', 'N/A')} lux")
    print(f"  Motion: {'Detected' if state.get('motion_detected') else 'None'}")
    print(f"  Weather: {state.get('weather_condition', 'N/A')}")

    if 'energy_price' in state:
        print(f"\nEnergy:")
        print(f"  Current price: {state.get('energy_price', 'N/A')} EUR/kWh")
        level_names = {1: 'Low (Good)', 2: 'Medium', 3: 'High (Expensive)'}
        price_level = state.get('energy_price_level', 2)
        print(f"  Price level: {level_names.get(price_level, 'Unknown')}")

    if 'power_consumption' in state:
        print(f"  Power consumption: {state.get('power_consumption')} W")

    # Empfehlungen
    recommendations = engine.get_recommendations()
    if recommendations:
        print(f"\n=== Recommendations ===")
        for rec in recommendations:
            print(f"  {rec}")

    print()
    return 0


def cmd_train(engine: DecisionEngine):
    """Trainiert die ML-Modelle mit historischen Daten"""
    logger.info("Starting model training...")

    print("\n=== Training ML Models ===\n")

    # Hole verfügbare Daten
    lighting_events_count = engine.db.get_lighting_events_count()
    heating_observations = engine.db.get_heating_observations(days_back=30)

    print(f"Available data:")
    print(f"  Lighting events: {lighting_events_count}")
    print(f"  Heating observations: {len(heating_observations)}")
    print()

    success_count = 0
    total_models = 2

    # ===== TRAIN LIGHTING MODEL =====
    print("1. Training Lighting Model...")
    print("-" * 50)

    MIN_LIGHTING_SAMPLES = 100

    if lighting_events_count >= MIN_LIGHTING_SAMPLES:
        try:
            # Hole Daten
            lighting_events = engine.db.get_lighting_events(days_back=30)
            sensor_data = engine.db.get_sensor_data(hours_back=30*24)

            # Bereite Trainingsdaten vor
            X, y = engine.lighting_model.prepare_training_data(
                sensor_data=sensor_data,
                light_states=lighting_events
            )

            # Trainiere Modell
            metrics = engine.lighting_model.train(X, y)

            if 'error' not in metrics:
                # Speichere Modell
                model_path = "models/lighting_model.pkl"
                engine.lighting_model.save(model_path)

                # Speichere Training-Historie
                engine.db.insert_training_history(
                    model_name="lighting_model",
                    model_type=metrics['model_type'],
                    metrics=metrics,
                    model_path=model_path
                )

                print(f"✓ Success!")
                print(f"  Accuracy: {metrics['accuracy']:.2%}")
                print(f"  Samples (train/test): {metrics['samples_train']}/{metrics['samples_test']}")
                print(f"  Model saved to: {model_path}")
                success_count += 1
            else:
                print(f"✗ Failed: {metrics['error']}")

        except Exception as e:
            logger.exception("Lighting model training failed")
            print(f"✗ Error: {e}")
    else:
        print(f"✗ Insufficient data: {lighting_events_count}/{MIN_LIGHTING_SAMPLES} samples")
        print(f"  Need {MIN_LIGHTING_SAMPLES - lighting_events_count} more samples")

    print()

    # ===== TRAIN TEMPERATURE MODEL =====
    print("2. Training Temperature Model...")
    print("-" * 50)

    MIN_HEATING_SAMPLES = 200

    if len(heating_observations) >= MIN_HEATING_SAMPLES:
        try:
            # Hole zusätzliche Sensordaten
            sensor_data = engine.db.get_sensor_data(hours_back=30*24)

            # Bereite Trainingsdaten vor (verwende heating_observations direkt)
            X, y = engine.temperature_model.prepare_training_data(
                sensor_data=sensor_data,
                temperature_settings=heating_observations
            )

            # Trainiere Modell
            metrics = engine.temperature_model.train(X, y)

            if 'error' not in metrics:
                # Speichere Modell
                model_path = "models/temperature_model.pkl"
                engine.temperature_model.save(model_path)

                # Speichere Training-Historie
                engine.db.insert_training_history(
                    model_name="temperature_model",
                    model_type=metrics['model_type'],
                    metrics=metrics,
                    model_path=model_path
                )

                print(f"✓ Success!")
                print(f"  MAE: {metrics['mae']:.2f}°C")
                print(f"  RMSE: {metrics['rmse']:.2f}°C")
                print(f"  R² Score: {metrics['r2_score']:.3f}")
                print(f"  Samples (train/test): {metrics['samples_train']}/{metrics['samples_test']}")
                print(f"  Model saved to: {model_path}")
                success_count += 1
            else:
                print(f"✗ Failed: {metrics['error']}")

        except Exception as e:
            logger.exception("Temperature model training failed")
            print(f"✗ Error: {e}")
    else:
        print(f"✗ Insufficient data: {len(heating_observations)}/{MIN_HEATING_SAMPLES} samples")
        print(f"  Need {MIN_HEATING_SAMPLES - len(heating_observations)} more samples")

    print()
    print("=" * 50)
    print(f"Training complete: {success_count}/{total_models} models trained successfully")
    print()

    if success_count == 0:
        print("⚠ No models were trained. System needs more data.")
        print("  Recommendation: Run in 'learning' mode for at least 3-7 days")
        return 1
    elif success_count < total_models:
        print("⚠ Some models failed to train. Check logs for details.")
        return 0
    else:
        print("✓ All models trained successfully!")
        return 0


def cmd_web(args):
    """Startet das Web-Interface"""
    from src.web.app import WebInterface

    debug_mode = getattr(args, 'debug', False)
    logger.info(f"Starting web interface on http://{args.host}:{args.port} (debug={debug_mode})")

    web = WebInterface(args.config)
    web.run(host=args.host, port=args.port, debug=debug_mode)

    return 0


def main():
    """Hauptfunktion"""
    parser = argparse.ArgumentParser(
        description='KI-System für Smart Home Automatisierung',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Beispiele:
  %(prog)s test              # Teste Verbindungen
  %(prog)s run               # Führe einen Zyklus aus
  %(prog)s daemon            # Starte im Daemon-Modus
  %(prog)s status            # Zeige aktuellen Status
  %(prog)s train             # Trainiere ML-Modelle
  %(prog)s web               # Starte Web-Interface

Konfiguration:
  Bearbeite config/config.yaml und .env für deine Einstellungen
        """
    )

    parser.add_argument(
        'command',
        choices=['test', 'run', 'daemon', 'status', 'train', 'web'],
        help='Befehl zum Ausführen'
    )

    parser.add_argument(
        '--config',
        type=str,
        default=None,
        help='Pfad zur Konfigurationsdatei'
    )

    parser.add_argument(
        '--interval',
        type=int,
        default=300,
        help='Intervall für Daemon-Modus in Sekunden (default: 300)'
    )

    parser.add_argument(
        '--port',
        type=int,
        default=8080,
        help='Port für Web-Interface (default: 8080)'
    )

    parser.add_argument(
        '--host',
        type=str,
        default='0.0.0.0',
        help='Host für Web-Interface (default: 0.0.0.0)'
    )

    parser.add_argument(
        '--debug',
        action='store_true',
        help='Aktiviert Debug-Modus mit Auto-Reload bei Code-Änderungen'
    )

    args = parser.parse_args()

    # Lade Konfiguration
    try:
        config = ConfigLoader(args.config)
        setup_logging(config)
    except Exception as e:
        print(f"Error loading config: {e}")
        return 1

    # Führe Befehl aus
    try:
        # Web command doesn't need DecisionEngine (creates its own in WebInterface)
        if args.command == 'web':
            return cmd_web(args)

        # Initialize Engine for all other commands
        try:
            engine = DecisionEngine(args.config)
        except Exception as e:
            logger.error(f"Failed to initialize engine: {e}")
            return 1

        if args.command == 'test':
            return cmd_test(engine)
        elif args.command == 'run':
            return cmd_run(engine)
        elif args.command == 'daemon':
            run_daemon(engine, args.interval)
            return 0
        elif args.command == 'status':
            return cmd_status(engine)
        elif args.command == 'train':
            return cmd_train(engine)
        else:
            parser.print_help()
            return 1

    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        return 0
    except Exception as e:
        logger.exception(f"Unexpected error: {e}")
        return 1


if __name__ == '__main__':
    sys.exit(main())
