
import sys
import json
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from src.utils.config_loader import ConfigLoader
from src.data_collector.platform_factory import PlatformFactory

def check_homey_devices():
    print("Lade Konfiguration...")
    config = ConfigLoader('config/config.yaml')
    
    homey_url = config.get('homey.url')
    homey_token = config.get('homey.token')
    
    if not homey_url or not homey_token:
        print("❌ Keine Homey Zugangsdaten in config.yaml gefunden")
        return

    print(f"Verbinde zu Homey ({homey_url})...")
    collector = PlatformFactory.create_collector('homey', homey_url, homey_token)
    
    if not collector:
        print("❌ Konnte Homey Collector nicht erstellen")
        return

    try:
        devices = collector.get_all_devices()
        print(f"✅ {len(devices)} Geräte gefunden.\n")
        
        print("Suche nach Bluetooth/MAC-Adressen in Geräten...")
        print("-" * 60)
        
        found_macs = 0
        
        for device in devices:
            name = device.get('name', 'Unbekannt')
            zone_id = device.get('zone')
            
            # Suche in Settings und Data nach MAC-ähnlichen Strings
            settings = device.get('settings', {})
            data = device.get('data', {})
            
            # Typische Felder für Adressen
            address = settings.get('address') or data.get('address') or data.get('id') or settings.get('id')
            
            # Prüfe ob es nach einer MAC aussieht (enthält :) oder ist hexadezimal
            is_interesting = False
            if address and (':' in str(address) or len(str(address)) == 12):
                is_interesting = True
            
            # Shelly BLU spezifisch
            if 'shelly' in name.lower() or 'blu' in name.lower():
                is_interesting = True
                
            if is_interesting:
                found_macs += 1
                print(f"Gerät: {name}")
                print(f"  Zone ID: {zone_id}")
                print(f"  Adresse/ID: {address}")
                if settings:
                    print(f"  Settings keys: {list(settings.keys())}")
                    # Zeige relevante Settings
                    for k, v in settings.items():
                        if 'address' in k.lower() or 'mac' in k.lower() or 'id' in k.lower():
                            print(f"    {k}: {v}")
                print("-" * 60)
                
        print(f"\nZusammenfassung: {found_macs} Geräte mit potenziellen Adressen gefunden.")
        
    except Exception as e:
        print(f"❌ Fehler beim Abrufen der Geräte: {e}")

if __name__ == "__main__":
    check_homey_devices()
