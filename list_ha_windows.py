
import sys
import os
import json
import yaml
from pathlib import Path

# Add src to path
sys.path.append(os.path.join(os.getcwd(), 'src'))

from data_collector.ha_collector import HomeAssistantCollector

def main():
    # Load config
    try:
        with open('config/config.yaml', 'r') as f:
            config = yaml.safe_load(f)
    except Exception as e:
        print(f"Error loading config: {e}")
        return

    ha_config = config.get('homeassistant', {})
    if not ha_config.get('url') or not ha_config.get('token'):
        print("No HA config found")
        return

    collector = HomeAssistantCollector(
        ha_config.get('url'),
        ha_config.get('token')
    )

    print("Fetching entities...")
    states = collector.get_states()
    
    windows = []
    for entity_id, data in states.items():
        if entity_id.startswith('binary_sensor.') and ('window' in entity_id or 'fenster' in entity_id or 'door' in entity_id):
            windows.append({
                'id': entity_id,
                'name': data.get('attributes', {}).get('friendly_name', entity_id),
                'state': data.get('state')
            })
            
    print(f"\nFound {len(windows)} potential window sensors:")
    for w in windows:
        print(f"- {w['name']} ({w['id']})")

if __name__ == "__main__":
    main()
