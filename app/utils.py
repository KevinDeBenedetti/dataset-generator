import logging
from typing import List, Dict
from app.models import QA

def setup_logging(level: int = logging.INFO):
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s - %(filename)s:%(lineno)d',
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler('scraper.log')
        ]
    )

def qa_to_dict_list(qa_list: List[QA]) -> List[Dict]:
    """Convertit une liste de QA en dictionnaires"""
    return [qa.model_dump() for qa in qa_list]

def print_summary(metrics, paths: List):
    print("\n" + "="*50)
    print("SCRAPING COMPLETED")
    print("="*50)
    print(metrics.get_summary())
    
    if paths:
        print("\nFiles generated:")
        for path in paths:
            print(f"  - {path}")
    
    if metrics.errors:
        print(f"\nErrors ({len(metrics.errors)}):")
        for error in metrics.errors[-5:]:  # Dernières 5 erreurs
            print(f"  - {error}")