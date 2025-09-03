import logging
from typing import Dict, Any, Union
from sqlalchemy.orm import Session

from services.scraper import ScraperService
from services.llm import LLMService
from services.dataset import DatasetService
from services.qa import QAService
from schemas.dataset import TargetLanguage, ModelName

class DatasetPipeline:
    """Pipeline to process a URL and generate a QA dataset"""
    
    def __init__(self, db: Session):
        self.db = db
        self.scraper_service = ScraperService(db)
        self.llm_service = LLMService()
        self.dataset_service = DatasetService(db)
        self.qa_service = QAService(db)
    
    async def process_url(self, 
                         url: str,
                         dataset_name: str,
                         model_cleaning: Union[str, ModelName],
                         target_language: Union[str, TargetLanguage],
                         model_qa: Union[str, ModelName],
                         similarity_threshold: float = 0.9) -> Dict[str, Any]:
        """Executes the complete pipeline for a URL"""
        try:
            # Extract string values from enum objects
            model_cleaning_str = model_cleaning.value if hasattr(model_cleaning, 'value') else str(model_cleaning)
            target_language_str = target_language.value if hasattr(target_language, 'value') else str(target_language)
            model_qa_str = model_qa.value if hasattr(model_qa, 'value') else str(model_qa)
            
            # 1. Get or create the dataset
            dataset = self.dataset_service.get_or_create_dataset(
                name=dataset_name, 
                description=f"Dataset automatically created for {url}"
            )
            
            # 2. Scrape the URL
            page_snapshot = self.scraper_service.scrape_url(url, dataset.id)
            
            # 3. Clean the text with LLM (modification ici pour utiliser llm_service au lieu de scraper_service)
            cleaned_text = self.llm_service.clean_text(page_snapshot.content, model_cleaning_str)
            
            # 4. Save the cleaned text
            cleaned_text_record = self.scraper_service.save_cleaned_text(
                page_snapshot_id=page_snapshot.id,
                content=cleaned_text,
                language=target_language_str,
                model=model_cleaning_str
            )
            
            # 5. Generate QA pairs
            qa_list = self.llm_service.generate_qa(cleaned_text, target_language_str, model_qa_str)
            
            # 6. Process and save QA pairs
            qa_stats = self.qa_service.process_qa_pairs(
                qa_list=qa_list,
                cleaned_text=cleaned_text,
                url=url,
                page_snapshot_id=page_snapshot.id,
                dataset_name=dataset_name,
                model=model_qa_str,
                dataset_id=dataset.id,
                similarity_threshold=similarity_threshold
            )
            
            # 7. Return results
            return {
                "qa_pairs": qa_list,
                **qa_stats,
                "similarity_threshold": similarity_threshold
            }
            
        except Exception as e:
            logging.error(f"Error in dataset pipeline: {str(e)}")
            raise e
