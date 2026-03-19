# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

KI-SYSTEM is an AI-powered smart home automation system written in Python that learns from user behavior to control lighting, heating, and other smart home devices. It supports both Home Assistant and Homey Pro platforms and uses machine learning models (scikit-learn) to make intelligent decisions.

**Key Design Philosophy:**
- Multi-platform support via a factory pattern (Home Assistant OR Homey Pro)
- ML models learn from sensor data to optimize energy usage and comfort
- Safety-first approach with configurable rules and thresholds
- Three operational modes: `auto` (executes actions), `learning` (collects data only), `manual` (suggests actions)

**Tech Stack:**
- Python 3.8+ with scikit-learn for ML models
- SQLite for data persistence
- Flask for web interface
- Loguru for logging
- Platform APIs: Home Assistant REST API or Homey API

## Development Commands

### Environment Setup
```bash
# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate  # On macOS/Linux

# Install dependencies
pip install -r requirements.txt
```

### Testing and Validation
```bash
# Quick validation of all components (preferred for rapid testing)
./quick_test.sh

# Full database test
python3 test_database.py

# Test platform connections (requires configured .env)
python3 main.py test

# View current system status
python3 main.py status
```

### Running the System
```bash
# Single cycle execution (collect data + make decisions)
python3 main.py run

# Daemon mode - continuous operation with interval
python3 main.py daemon --interval 300  # Every 5 minutes

# Train ML models manually
python3 main.py train

# Start web interface
python3 main.py web --host 0.0.0.0 --port 5000
```

### Configuration
- **Environment variables**: `.env` file (copy from `.env.example`)
- **Main config**: `config/config.yaml` - platform selection, sensors, ML model settings, decision rules
- **Platform selection**: Set `platform.type` to either `"homeassistant"` or `"homey"` in config.yaml

## Architecture

### Core Components

**1. Decision Engine** (`src/decision_engine/engine.py`)
- **Purpose**: Orchestrates all system components
- **Key responsibilities**:
  - Manages decision-making cycle: collect state → run models → execute actions
  - Enforces safety rules and confidence thresholds
  - Entry point for all main.py commands
- **Important methods**: `run_cycle()`, `collect_current_state()`, `test_connection()`

**2. Platform Abstraction Layer** (`src/data_collector/`)
- **Factory Pattern**: `platform_factory.py` creates the correct collector based on config
- **Base Interface**: `base_collector.py` defines `SmartHomeCollector` abstract class
- **Implementations**:
  - `ha_collector.py`: Home Assistant REST API implementation
  - `homey_collector.py`: Homey Pro API implementation
- **Common Interface**: All collectors implement `get_state()`, `turn_on()`, `turn_off()`, `set_temperature()`, `test_connection()`
- **Key Design**: DecisionEngine uses the abstract interface, making platform switching seamless

**3. ML Models** (`src/models/`)
- `lighting_model.py`: Binary classifier for light on/off predictions
  - Features: hour, day_of_week, brightness, motion, presence, weather
  - Models: RandomForest or GradientBoosting (configurable)
- `temperature_model.py`: Regressor for optimal heating temperature
  - Features: outdoor temp, current temp, presence, time, energy price
  - Includes safety bounds (min/max temperature constraints)
- `energy_optimizer.py`: Multi-objective optimizer balancing cost vs comfort
  - Configurable targets: minimize_cost, minimize_consumption, balance
  - Uses constraint-based optimization
- **Storage**: Trained models saved as .pkl files in `models/` directory
- **Training**: Auto-retrains every 24 hours if enough samples (100+ for lighting, 200+ for heating)

**4. External Data Collectors** (`src/data_collector/`)
- `weather_collector.py`: OpenWeatherMap integration
- `energy_price_collector.py`: Dynamic pricing (aWATTar, Tibber)
- `background_collector.py`: Automated collection every 5 minutes
- All data stored in SQLite for training and analytics

**5. Database** (`src/utils/database.py`)
- SQLite-based with automatic schema initialization
- **Core tables**:
  - `sensor_data`: timestamped sensor readings
  - `external_data`: weather, energy prices
  - `decisions`: logged actions with confidence scores
  - `training_history`: ML model training metrics
- **Bathroom automation tables** (v0.8+):
  - `bathroom_events`: shower/bath events with duration, humidity peaks
  - `bathroom_measurements`: granular measurements during events
  - `bathroom_device_actions`: device control actions
  - `bathroom_learned_parameters`: optimized thresholds from ML
- **Retention**: 90-day retention policy (configurable)

**6. Web Interface** (`src/web/app.py`)
- Flask app with Jinja2 templates (`src/web/templates/`)
- **Routes**: `/`, `/analytics`, `/bathroom`, `/bathroom/analytics`, `/devices`, `/rooms`, `/automations`, `/settings`
- **API endpoints**: RESTful API at `/api/*` for AJAX calls
- **Static assets**: CSS/JS in `src/web/static/`
- **Key feature**: Real-time status updates and interactive charts

**7. Background Processes** (`src/background/`)
- `data_collector.py`: Automated sensor logging (5-minute intervals)
- `bathroom_optimizer.py`: Daily optimization job (3:00 AM)
- `ml_auto_trainer.py`: Automatic model retraining
- These can be run as separate processes or scheduled via cron/systemd

**8. Bathroom Automation System** (`src/decision_engine/`)
- `bathroom_automation.py`: Event detection and device control
  - Auto-detects showers via humidity spikes
  - Controls dehumidifier based on learned thresholds
  - Tracks events for analytics
- `bathroom_analyzer.py`: Analytics and pattern recognition
  - Identifies optimal thresholds from historical data
  - Predicts shower times
  - Generates insights (peak times, duration trends)

### Data Flow

1. **Collection Cycle**: DecisionEngine.run_cycle() is called (manually, daemon, or web)
2. **Gather State**: Collect sensor data from platform + weather + energy prices
3. **Store Data**: Save to database for future training
4. **ML Prediction**: Feed current state to lighting_model and temperature_model
5. **Optimization**: EnergyOptimizer balances predictions against cost/comfort constraints
6. **Safety Check**: Validate against configured rules (e.g., no heating with open windows)
7. **Execution**: If mode is "auto" and confidence > threshold, execute actions via platform
8. **Logging**: All decisions logged to database and logs/ki_system.log

### Key Design Patterns

**Factory Pattern for Platforms**:
- `PlatformFactory.create_collector(platform_type, url, token)` returns the appropriate SmartHomeCollector subclass
- Allows seamless switching between Home Assistant and Homey Pro without changing business logic
- New platforms can be added by implementing SmartHomeCollector and registering in PlatformFactory.PLATFORMS

**Configuration Cascading**:
- `ConfigLoader` loads config/config.yaml and merges with .env variables
- Provides dot-notation access: `config.get('platform.type')`
- Environment variables in .env override config.yaml values
- This allows sensitive credentials in .env (gitignored) while keeping structure in config.yaml (committed)

**Abstract Base Classes**:
- `SmartHomeCollector` (ABC) ensures all platform implementations have consistent interface
- Models inherit from base classes with common training/prediction logic
- Enables polymorphism: DecisionEngine works with any platform without conditional logic

**Safety Mechanisms**:
- Confidence thresholds (default 0.7) prevent low-confidence actions
- Temperature constraints (min/max bounds enforced in models)
- Configurable safety rules in `decision_engine.rules` array
- Window/door sensors can block heating when open
- Learning mode for safe data collection without automation
- All decisions logged before execution for auditing

## Important Notes

**Platform Integration:**
- System can use EITHER Home Assistant OR Homey Pro (configured via platform.type)
- Platform URLs and tokens come from .env file
- Both platforms use the same SmartHomeCollector interface, so decision logic is platform-agnostic

**ML Model Training:**
- Models require minimum samples: 100 for lighting, 200 for heating
- Auto-retraining happens every 24 hours (configurable)
- Initial deployment should run in "learning" mode for 2-3 days
- Models saved to models/ directory as .pkl files

**Energy Price Integration:**
- Optional feature (external_data.energy_prices.enabled in config)
- Disabled by default to avoid external API dependencies
- When enabled, influences heating decisions via EnergyOptimizer

**Logging:**
- Uses loguru for structured logging
- Console and file logging (logs/ki_system.log)
- Rotation at 10MB, 7-day retention
- Log level configurable in config.yaml

**Database Schema:**
- sensor_data: timestamp, sensor_type, value, metadata (JSON)
- external_data: timestamp, data_type, data (JSON)
- decisions: timestamp, decision_type, input_data, output_decision, confidence, executed, result
- training_history: timestamp, model_type, metrics (JSON)
- bathroom_events: comprehensive tracking of shower/bath events with humidity, temperature, duration
- bathroom_measurements: detailed measurements during bathroom events
- bathroom_device_actions: log of all device actions (dehumidifier, fan, etc.)
- bathroom_learned_parameters: stores optimized thresholds learned from historical data

## Testing Strategy

**Quick Test**: Run `./quick_test.sh` for rapid validation of environment, dependencies, imports, and database functionality.

**Integration Test**: Run `python3 main.py test` to verify live connections to configured platform, weather API, and database.

**Manual Testing**: Use `python3 main.py status` to inspect current system state and recommendations without executing actions.

**Safe Deployment**: Always start with `mode: "learning"` in config.yaml to collect data without automation, then switch to "manual" for approval-based automation, finally "auto" for full automation.

## Common Development Workflows

**Adding a New Sensor Type:**
1. Update `config.yaml` under `data_collection.sensors` with new sensor entity IDs
2. If needed, modify platform collector's `get_sensor_data()` to handle special sensor types
3. Update ML model's `prepare_training_data()` to include new features in feature vector
4. Collect data in learning mode for 2-3 days
5. Retrain model with `python3 main.py train`

**Supporting a New Platform (e.g., OpenHAB):**
1. Create new collector in `src/data_collector/` inheriting from `SmartHomeCollector`
2. Implement all abstract methods:
   - `test_connection()`: verify API connectivity
   - `get_state()`, `get_states()`: fetch device states
   - `turn_on()`, `turn_off()`: control switches/lights
   - `set_temperature()`: control thermostats
   - `get_platform_name()`: return display name
3. Register in `PlatformFactory.PLATFORMS` dictionary (e.g., `'openhab': OpenHABCollector`)
4. Add configuration section to config.yaml (URL, token, etc.)
5. Test with `python3 main.py test`
6. Update README.md and documentation

**Modifying Decision Logic:**
1. Decision rules are in `config.yaml` under `decision_engine.rules`
2. Custom logic should be added to `DecisionEngine.run_cycle()` in src/decision_engine/engine.py
3. Safety checks happen in `_apply_safety_checks()` method
4. Confidence thresholds applied before execution (configurable per model)
5. Always log decisions to database for auditability

**Adding a New ML Model (e.g., Window Blinds):**
1. Create new file in `src/models/` (e.g., `blinds_model.py`)
2. Inherit from common base or implement similar interface to existing models
3. Define features needed (e.g., brightness, time_of_day, outside_temp)
4. Implement `train()`, `predict()`, `save()`, `load()` methods
5. Initialize model in `DecisionEngine.__init__()`
6. Add prediction logic to `DecisionEngine.run_cycle()`
7. Add configuration section to config.yaml

**Debugging Platform Connection Issues:**
1. Check `.env` file has correct `PLATFORM_TYPE`, URL, and TOKEN (no trailing slashes in URLs)
2. Run `python3 main.py test` to diagnose connection
3. For Home Assistant:
   - Verify long-lived access token hasn't expired (they don't expire by default, but can be revoked)
   - Test with curl: `curl -H "Authorization: Bearer TOKEN" http://URL:8123/api/`
   - Check Home Assistant logs for rejected requests
4. For Homey:
   - Verify bearer token from athom-cli is current: `athom user --bearer`
   - Tokens expire after some time; re-login with `athom login` if needed
5. Check `logs/ki_system.log` for detailed error messages
6. Verify network connectivity and firewall rules

**Working with the Database:**
- Direct access: `sqlite3 data/ki_system.db`
- Useful queries:
  - Recent sensor data: `SELECT * FROM sensor_data ORDER BY timestamp DESC LIMIT 10;`
  - Decision history: `SELECT * FROM decisions WHERE executed=1 ORDER BY timestamp DESC LIMIT 20;`
  - Bathroom events: `SELECT * FROM bathroom_events ORDER BY start_time DESC LIMIT 10;`
- Schema inspection: `.schema` in sqlite3 REPL
- Backup before major changes: `cp data/ki_system.db data/ki_system.db.backup`

## Configuration System

**Two-tier configuration:**
1. **config/config.yaml**: Structure, sensor mappings, model settings, rules
   - Committed to git (no secrets)
   - Platform type selection
   - Sensor entity IDs
   - ML model configuration
   - Safety rules
2. **.env**: Sensitive credentials (gitignored)
   - Platform URLs and access tokens
   - API keys (weather, energy prices)
   - Loaded via ConfigLoader and merged with config.yaml

**ConfigLoader behavior:**
- Loads YAML first, then overlays .env variables
- Provides dot-notation access: `config.get('platform.type')`
- Returns None or default if key doesn't exist: `config.get('key', default_value)`
- Handles nested keys: `config.get('models.lighting.type')`

**Special configuration files:**
- `data/bathroom_config.json`: Bathroom automation settings (sensor/device IDs, thresholds)
- `data/sensor_config.json`: Sensor whitelist and metadata

## Bathroom Automation System (v0.8+)

The bathroom automation system is a self-learning feature that detects shower/bath events and controls dehumidifiers automatically.

## Workflow Guidelines

### Task Management
- Vor komplexen Änderungen: Plan in `tasks/todo.md` schreiben
- Nach Korrekturen: Muster in `tasks/lessons.md` dokumentieren
- Tasks erst als erledigt markieren wenn verifiziert

### Verification
- Nie "fertig" ohne Beweis dass es funktioniert
- Bei Bugs: Logs/Errors zeigen und direkt fixen, kein Handholding nötig
- Vor jedem Commit: `./quick_test.sh` laufen lassen

### Code Quality
- Jede Änderung so minimal wie möglich halten
- Keine temporären Fixes – immer Ursache finden
- Platform-spezifischer Code gehört NIE in engine.py

## Do NOT
- `.env` Inhalte in Outputs oder Logs zeigen
- Direkt in `data/ki_system.db` schreiben ohne Backup
- Platform-Code außerhalb der Collector-Klassen schreiben
- ML-Modelle unter Mindest-Samples trainieren (100 Lighting / 200 Heating)
- Breaking Changes an laufenden Sensor-IDs ohne Migrationsplan

**Key Components:**
- `src/decision_engine/bathroom_automation.py`: Event detection and device control logic
- `src/decision_engine/bathroom_analyzer.py`: Analytics, pattern recognition, threshold optimization
- `src/background/bathroom_optimizer.py`: Daily background optimization job (runs at 3:00 AM)
- Web UI at `/bathroom` for configuration and `/bathroom/analytics` for visualizations and insights

**How It Works:**
1. **Event Detection**: Monitors humidity sensor for sudden increases (configurable threshold)
   - Detects start when humidity rises above baseline + delta
   - Tracks peak humidity, duration, temperature changes
   - Detects end when humidity drops back to near-baseline
2. **Device Control**: Automatically controls dehumidifier
   - Turns on when humidity exceeds high threshold during/after event
   - Turns off when humidity drops below low threshold + configurable delay
   - Respects window sensor (won't run dehumidifier if window open)
3. **Learning & Optimization**:
   - Collects data from every event (stored in bathroom_events table)
   - Analyzes historical patterns (min. 3 events required)
   - Automatically optimizes thresholds to minimize runtime while maintaining comfort
   - Requires 70% confidence score before applying new thresholds
4. **Analytics & Insights**:
   - Event statistics: count, average duration, humidity peaks
   - Time patterns: most common shower times, day-of-week distribution
   - Predictions: next likely shower time based on historical patterns
   - Trend charts: humidity/temperature over last N events

**Configuration:**
- Primary config: `data/bathroom_config.json` (auto-created on first use)
- Includes: sensor IDs, device IDs, thresholds (high/low humidity, duration, delay)
- Can be configured via web UI at `/bathroom`
- Learned parameters stored in `bathroom_learned_parameters` database table
