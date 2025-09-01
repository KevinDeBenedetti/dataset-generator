import logging
from typing import Dict, Any, List
from sqlalchemy.orm import Session

from app.services.scraper import ScraperService
from app.services.llm import LLMService
from app.services.dataset import DatasetService
from app.services.qa import QAService
from app.schemas.dataset import TargetLanguage, ModelName

class DatasetPipeline:
    """Pipeline pour traiter une URL et générer un dataset de QA"""
    
    def __init__(self, db: Session):
        self.db = db
        self.scraper_service = ScraperService(db)
        self.llm_service = LLMService()
        self.dataset_service = DatasetService(db)
        self.qa_service = QAService(db)
    
    async def process_url(self, 
                         url: str,
                         dataset_name: str,
                         model_cleaning: ModelName,
                         target_language: TargetLanguage,
                         model_qa: ModelName,
                         similarity_threshold: float = 0.9) -> Dict[str, Any]:
        """Exécute le pipeline complet pour une URL"""
        try:
            # 1. Récupérer ou créer le dataset
            dataset = self.dataset_service.get_or_create_dataset(
                name=dataset_name, 
                description=f"Dataset créé automatiquement pour {url}"
            )
            
            # 2. Scraper l'URL
            page_snapshot = self.scraper_service.scrape_url(url, dataset.id)
            
            # 3. Nettoyer le texte avec LLM
            cleaned_text = self.llm_service.clean_text(page_snapshot.content, model_cleaning)
            
            # 4. Sauvegarder le texte nettoyé
            cleaned_text_record = self.scraper_service.save_cleaned_text(
                page_snapshot_id=page_snapshot.id,
                content=cleaned_text,
                language=target_language,
                model=model_cleaning
            )
            
            # 5. Générer les paires QA
            qa_list = self.llm_service.generate_qa(cleaned_text, target_language, model_qa)
            
            # 6. Traiter et sauvegarder les paires QA
            qa_stats = self.qa_service.process_qa_pairs(
                qa_list=qa_list,
                cleaned_text=cleaned_text,
                url=url,
                page_snapshot_id=page_snapshot.id,
                dataset_name=dataset_name,
                model=model_qa,
                similarity_threshold=similarity_threshold
            )
            
            # 7. Retourner les résultats
            return {
                "qa_pairs": qa_list,
                **qa_stats,
                "similarity_threshold": similarity_threshold
            }
            
        except Exception as e:
            logging.error(f"Error in dataset pipeline: {str(e)}")
            raise e
