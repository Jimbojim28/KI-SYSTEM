
import sys
import json
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from src.utils.config_loader import ConfigLoader
from src.data_collector.ha_collector import HomeAssistantCollector

def check_ha_entities():
    print("Lade Konfiguration...")
    config = ConfigLoader('config/config.yaml')
    
    ha_url = config.get('homeassistant.url')
    ha_token = config.get('homeassistant.token')
    
    if not ha_url or not ha_token:
        print("❌ Keine HA Zugangsdaten in config.yaml gefunden")
        return

    print(f"Verbinde zu HA ({ha_url})...")
    collector = HomeAssistantCollector(ha_url, ha_token)
    states = collector.get_states()
    
    print(f"✅ {len(states)} Entities gefunden.")
    
    print("\nSuche nach 'Küche'...")
    for entity_id, state in states.items():
        name = state.get('attributes', {}).get('friendly_name', '')
        if 'küche' in entity_id.lower() or 'küche' in name.lower():
            print(f"  - {entity_id} ({name})")

    print("\nSuche nach MAC 'D4CD'...")
    for entity_id, state in states.items():
        name = state.get('attributes', {}).get('friendly_name', '')
        if 'd4cd' in entity_id.lower() or 'd4cd' in name.lower():
            print(f"  - {entity_id} ({name})")

    print("\nSuche nach MAC '9F3D'...")
    for entity_id, state in states.items():
        name = state.get('attributes', {}).get('friendly_name', '')
        if '9f3d' in entity_id.lower() or '9f3d' in name.lower():
            print(f"  - {entity_id} ({name})")

if __name__ == "__main__":
    check_ha_entities()
