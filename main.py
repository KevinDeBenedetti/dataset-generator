import logging
from typing import List

from app.config import config
from app.scraper import WebScraper
from app.llm_client import LLMClient
from app.data_manager import DataManager
from app.models import ScrapingMetrics
from utils import setup_logging, qa_to_dict_list, print_summary

class ScrapingPipeline:
    def __init__(self, use_cache: bool = True):
        self.scraper = WebScraper(use_cache=use_cache)
        self.llm_client = LLMClient()
        self.data_manager = DataManager()
        self.metrics = ScrapingMetrics()
    
    def process_url(self, url: str) -> List:
        """Process a full URL: scrape -> clean -> QA -> save"""
        try:
            # 1. Scraping
            content = self.scraper.scrape_url(url)
            self.metrics.urls_processed += 1
            
            # 2. Save raw markdown
            md_path = self.data_manager.save_markdown(content)
            logging.info(f"Saved markdown: {md_path}")
            
            # 3. LLM cleaning
            cleaned_text = self.llm_client.clean_text(content.text)
            
            # 4. Save cleaned text
            txt_path = self.data_manager.save_cleaned_text(content, cleaned_text)
            logging.info(f"Saved cleaned text: {txt_path}")
            
            # 5. QA generation
            qa_list = self.llm_client.generate_qa(cleaned_text)
            qa_dicts = qa_to_dict_list(qa_list)
            self.metrics.qa_pairs_generated += len(qa_dicts)
            
            # 6. Save datasets
            if qa_dicts:
                dataset_paths = self.data_manager.save_dataset(qa_dicts)
                logging.info(f"Saved datasets: {[str(p) for p in dataset_paths]}")
                return dataset_paths
            
            return []
            
        except Exception as e:
            error_msg = f"Error processing {url}: {str(e)}"
            self.metrics.add_error(error_msg)
            logging.error(error_msg)
            return []
    
    def process_urls(self, urls: List[str]) -> List:
        """Process a list of URLs"""
        all_paths = []
        
        for url in urls:
            logging.info(f"Processing {url}")
            paths = self.process_url(url)
            all_paths.extend(paths)
            
            if paths:
                print(f"✅ {url}: {self.metrics.qa_pairs_generated} QA pairs total")
            else:
                print(f"❌ {url}: Processing failed")
        
        return all_paths

def main():
    # Configure logging
    setup_logging()
    
    urls = config.urls

    # Pipeline
    pipeline = ScrapingPipeline(use_cache=True)
    
    # Processing
    paths = pipeline.process_urls(urls)
    
    # Summary
    print_summary(pipeline.metrics, paths)

if __name__ == "__main__":
    main()