import logging
from typing import List, Dict

from app.scraper import WebScraper
from app.llm_client import LLMClient
from app.data_manager import DataManager
from app.models.scraping import ScrapingMetrics
from app.utils import qa_to_dict_list

class ScrapingPipeline:
    def __init__(self, use_cache: bool = True):
        self.scraper = WebScraper(use_cache=use_cache)
        self.llm_client = LLMClient()
        self.data_manager = DataManager()
        self.metrics = ScrapingMetrics()
        # Démarrer le timer pour la durée
        self.metrics.start_timer()
    
    def process_url(self, url: str, dataset_name: str = None) -> List:
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
                # Créer la structure de catégories pour save_dataset
                dataset_structure = {
                    dataset_name or "general": {
                        f"qa_{i}": qa_dict for i, qa_dict in enumerate(qa_dicts)
                    }
                }
                dataset_paths = self.data_manager.save_dataset(dataset_structure)
                logging.info(f"Saved datasets: {[str(p) for p in dataset_paths]}")
                return dataset_paths
            
            return []
            
        except Exception as e:
            error_msg = f"Error processing {url}: {str(e)}"
            self.metrics.add_error(error_msg)
            logging.error(error_msg)
            return []
    
    def process_urls(self, urls_config: Dict) -> List:
        """Process a list of URLs"""
        all_paths = []
        
        def process_nested_urls(data: Dict, path_parts: List[str] = []):
            for key, value in data.items():
                current_path = path_parts + [key]
                 
                if isinstance(value, dict):
                    if "url" in value:
                        # Valid URL entry
                        url = value["url"]
                        dataset_name = "-".join(current_path)

                        logging.info(f"Processing {url} for dataset '{dataset_name}'")
                        paths = self.process_url(url, dataset_name)
                        all_paths.extend(paths)

                        if paths:
                            print(f"✅ {dataset_name}: {url}")
                        else:
                            print(f"❌ {dataset_name}: Processing failed for {url}")
                    else:
                        # New hierarchical level - recurse into nested dictionary
                        process_nested_urls(value, current_path)

        process_nested_urls(urls_config)
        # Arrêter le timer à la fin du traitement
        self.metrics.stop_timer()
        # Calculer le taux (rate)
        self.metrics.calculate_rate()
        return all_paths
    