#!/usr/bin/env python3
"""
Script de test manuel pour la configuration
Usage: python scripts/test_config_manual.py
"""

import sys
import os
from pathlib import Path

# Ajouter le répertoire parent au PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent.parent))

def test_current_config():
    """Test de la configuration actuelle"""
    try:
        from app.config import config
        
        print("🔧 Configuration actuelle")
        print("=" * 50)
        
        print(f"📂 Répertoire de travail: {os.getcwd()}")
        print(f"🔑 API Key présente: {'✅' if config.openai_api_key else '❌'}")
        print(f"🌍 Langue cible: {config.target_language}")
        print(f"📄 Variable URLS: {os.getenv('URLS', 'Non définie')}")
        print()
        
        print("📋 Configuration URLs hiérarchique:")
        if config.urls_config:
            import json
            print(json.dumps(config.urls_config, indent=2, ensure_ascii=False))
        else:
            print("  Aucune configuration hiérarchique")
        print()
        
        print("🔗 Liste des URLs:")
        if config.urls:
            for i, url in enumerate(config.urls, 1):
                print(f"  {i}. {url}")
        else:
            print("  Aucune URL trouvée")
        print()
        
        print("📊 Noms de datasets générés:")
        if config.urls_config:
            def show_datasets(data, path_parts=[]):
                for key, value in data.items():
                    current_path = path_parts + [key]
                    if isinstance(value, dict):
                        if "url" in value:
                            dataset_name = "-".join(current_path)
                            print(f"  📁 {dataset_name}")
                            print(f"     🔗 {value['url']}")
                            if 'description' in value:
                                print(f"     📝 {value['description']}")
                        else:
                            show_datasets(value, current_path)
            
            show_datasets(config.urls_config)
        else:
            print("  Aucun dataset généré (pas de config hiérarchique)")
        
        print("\n✅ Test terminé avec succès!")
        
    except Exception as e:
        print(f"❌ Erreur lors du test: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_current_config()