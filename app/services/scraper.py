import logging
from typing import List, Dict, Any, Optional
from app.utils.scraper import WebScraper
from app.models.scraper import PageSnapshot, CleanedText
from sqlalchemy.orm import Session

class ScraperService:
    def __init__(self, db: Session):
        self.db = db
        self.scraper = WebScraper()
    
    def scrape_url(self, url: str, dataset_id: int) -> PageSnapshot:
        """Scrape une URL et enregistre le résultat dans la base de données"""
        logging.info(f"Scraping URL: {url}")
        page_snapshot = self.scraper.scrape_url(url)
        page_snapshot.dataset_id = dataset_id
        
        self.db.add(page_snapshot)
        self.db.commit()
        self.db.refresh(page_snapshot)
        
        return page_snapshot
    
    def save_cleaned_text(self, page_snapshot_id: int, content: str, language: str, model: str) -> CleanedText:
        """Enregistre le texte nettoyé dans la base de données"""
        cleaned_text_record = CleanedText(
            page_snapshot_id=page_snapshot_id,
            content=content,
            language=language,
            model=model
        )
        self.db.add(cleaned_text_record)
        self.db.commit()
        self.db.refresh(cleaned_text_record)
        
        return cleaned_text_record
