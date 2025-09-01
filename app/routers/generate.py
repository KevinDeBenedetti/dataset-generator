import logging

from fastapi import APIRouter, Depends, HTTPException, Body, Query
from enum import Enum
from sqlalchemy.orm import Session

from app.utils.common import print_summary, qa_to_dict_list, flatten_urls, is_valid_url
from app.schemas.dataset import TargetLanguage, ModelName
from app.services.database import get_db
from app.pipelines.dataset import DatasetPipeline

router = APIRouter(
    prefix="/generate",
    tags=["generate"],
)

@router.post("/dataset/url")
async def create_dataset_for_url(
    url: str,
    dataset_name: str = Query(..., description="Nom du dataset (utilisez GET /datasets pour voir les options disponibles)"),
    db: Session = Depends(get_db),
    model_cleaning: ModelName = Query(),
    target_language: TargetLanguage = Query(),
    model_qa: ModelName = Query(),
    similarity_threshold: float = Query(0.9, description="Seuil de similarité pour détecter les doublons (0.0-1.0)")
):
    try:
        # Utilisation de la pipeline pour traiter l'URL
        pipeline = DatasetPipeline(db)
        result = await pipeline.process_url(
            url=url,
            dataset_name=dataset_name,
            model_cleaning=model_cleaning,
            target_language=target_language,
            model_qa=model_qa,
            similarity_threshold=similarity_threshold
        )
        
        return result
    
    except Exception as e:
        logging.error(f"Error creating dataset: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# @router.post("/dataset")
# # @router.post("/dataset", response_model=DatasetResult)
# async def create_dataset(
#     urls_config: UrlsConfig = Body(
#         ..., 
#         description="Structured configuration for URLs to scrape (any structure)",
#         openapi_examples={
#             "Example": {
#                 "summary": "Full example configuration",
#                 "description": "Typical configuration based on urls.json.example",
#                 "value": {
#                     "official_sources": {
#                         "main_site": {
#                             "url": "https://example-official.gov",
#                             "description": "Main official website of the organization"
#                         }
#                     }
#                 }
#             }
#         }),
#     target_language: TargetLanguage = Query(),
#     model_cleaning: ModelName = Query(),
#     model_qa: ModelName = Query(),
# ):
#     try:
#         logging.info("Received dataset creation request")

#         scraper = WebScraper()
#         llm_client = LLMClient()
#         data_manager = DataManager()
#         metrics = ScrapingMetrics()
#         metrics.start_timer()

#         all_paths: List[str] = []

#         def process_single_url(url: str, dataset_name: str) -> List[str]:
#             """Processing a single URL: scraping, cleaning, QA generation, saving."""
#             try:
#                 page_snapshot = scraper.scrape_url(url)
#                 metrics.urls_processed += 1

#                 logging.info(f"Processed URL: {url}")

#                 # save raw markdown
#                 md_path = data_manager.save_markdown(page_snapshot)
#                 logging.info(f"Saved markdown: {md_path}")

#                 # cleaning via LLM
#                 cleaned_text = llm_client.clean_text(page_snapshot.content, model_cleaning)

#                 # save cleaned text
#                 txt_path = data_manager.save_cleaned_text(page_snapshot, cleaned_text)
#                 logging.info(f"Saved cleaned text: {txt_path}")

#                 # QA generation
#                 qa_list = llm_client.generate_qa(cleaned_text, target_language, model_qa)
#                 qa_dicts = qa_to_dict_list(qa_list)
#                 metrics.qa_pairs_generated += len(qa_dicts)

#                 # Sauvegarder les paires QA dans la base de données
#                 for i, qa_item in enumerate(qa_list):
#                     qa_record = QASource.from_qa_generation(
#                         question=qa_item.question,
#                         answer=qa_item.answer,
#                         context=cleaned_text,
#                         confidence=getattr(qa_item, 'confidence', 1.0),
#                         source_url=url,
#                         page_snapshot_id=page_snapshot.id,
#                         index=i
#                     )
                    
#                     # Vérifier si l'enregistrement existe déjà
#                     existing = db.query(QASource).filter(QASource.id == qa_record.id).first()
#                     if not existing:
#                         qa_record.dataset_name = dataset_name
#                         qa_record.model = model_qa
#                         db.add(qa_record)
#                     else:
#                         logging.info(f"QA pair already exists, skipping: {qa_record.id}")

#                 # save datasets if present
#                 if qa_dicts:
#                     dataset_structure = {
#                         dataset_name or "general": {
#                             f"qa_{i}": qa_dict for i, qa_dict in enumerate(qa_dicts)
#                         }
#                     }
#                     dataset_paths = data_manager.save_dataset(dataset_structure)
#                     logging.info(f"Saved datasets: {[str(p) for p in dataset_paths]}")
#                     return dataset_paths

#                 return []

#             except Exception as e:
#                 error_msg = f"Error processing {url}: {str(e)}"
#                 metrics.add_error(error_msg)
#                 logging.error(error_msg)
#                 return []


#         urls_items = flatten_urls(urls_config.model_dump())
#         logging.info(f"Flattened URLs: {urls_items}")

#         for dataset_name, url in urls_items:
#             if not is_valid_url(url):
#                 msg = f"Invalid URL skipped: {url} (dataset={dataset_name})"
#                 metrics.add_error(msg)
#                 logging.warning(msg)
#                 print(f"❌ {dataset_name}: {url} (invalid)")
#                 continue

#             logging.info(f"Processing {url} for dataset '{dataset_name}'")
#             paths = process_single_url(url, dataset_name)
#             if paths:
#                 all_paths.extend(paths)
#                 print(f"✅ {dataset_name}: {url}")
#             else:
#                 print(f"❌ {dataset_name}: Processing failed for {url}")

#         metrics.stop_timer()
#         metrics.calculate_rate()

#         print_summary(metrics, all_paths)

#         files = [str(p) for p in all_paths] if all_paths else []

#         return DatasetResult(
#             task_id="dataset-creation",
#             status="completed",
#             urls_processed=metrics.urls_processed,
#             qa_pairs_generated=metrics.qa_pairs_generated,
#             files_generated=files,
#             errors=metrics.errors,
#             duration=metrics.duration,
#             rate=metrics.rate
#         )

#     except Exception as e:
#         logging.error(f"Error creating dataset: {str(e)}")
#         raise HTTPException(status_code=500, detail=str(e))
#                 # QA generation
#                 qa_list = llm_client.generate_qa(cleaned_text, target_language, model_qa)
#                 qa_dicts = qa_to_dict_list(qa_list)
#                 metrics.qa_pairs_generated += len(qa_dicts)

#                 # Sauvegarder les paires QA dans la base de données
#                 for i, qa_item in enumerate(qa_list):
#                     qa_record = QASource.from_qa_generation(
#                         question=qa_item.question,
#                         answer=qa_item.answer,
#                         context=cleaned_text,
#                         confidence=getattr(qa_item, 'confidence', 1.0),
#                         source_url=url,
#                         page_snapshot_id=page_snapshot.id,
#                         index=i
#                     )
                    
#                     # Vérifier si l'enregistrement existe déjà
#                     existing = db.query(QASource).filter(QASource.id == qa_record.id).first()
#                     if not existing:
#                         qa_record.dataset_name = dataset_name
#                         qa_record.model = model_qa
#                         db.add(qa_record)
#                     else:
#                         logging.info(f"QA pair already exists, skipping: {qa_record.id}")

#                 # save datasets if present
#                 if qa_dicts:
#                     dataset_structure = {
#                         dataset_name or "general": {
#                             f"qa_{i}": qa_dict for i, qa_dict in enumerate(qa_dicts)
#                         }
#                     }
#                     dataset_paths = data_manager.save_dataset(dataset_structure)
#                     logging.info(f"Saved datasets: {[str(p) for p in dataset_paths]}")
#                     return dataset_paths

#                 return []

#             except Exception as e:
#                 error_msg = f"Error processing {url}: {str(e)}"
#                 metrics.add_error(error_msg)
#                 logging.error(error_msg)
#                 return []


#         urls_items = flatten_urls(urls_config.model_dump())
#         logging.info(f"Flattened URLs: {urls_items}")

#         for dataset_name, url in urls_items:
#             if not is_valid_url(url):
#                 msg = f"Invalid URL skipped: {url} (dataset={dataset_name})"
#                 metrics.add_error(msg)
#                 logging.warning(msg)
#                 print(f"❌ {dataset_name}: {url} (invalid)")
#                 continue

#             logging.info(f"Processing {url} for dataset '{dataset_name}'")
#             paths = process_single_url(url, dataset_name)
#             if paths:
#                 all_paths.extend(paths)
#                 print(f"✅ {dataset_name}: {url}")
#             else:
#                 print(f"❌ {dataset_name}: Processing failed for {url}")

#         metrics.stop_timer()
#         metrics.calculate_rate()

#         print_summary(metrics, all_paths)

#         files = [str(p) for p in all_paths] if all_paths else []

#         return DatasetResult(
#             task_id="dataset-creation",
#             status="completed",
#             urls_processed=metrics.urls_processed,
#             qa_pairs_generated=metrics.qa_pairs_generated,
#             files_generated=files,
#             errors=metrics.errors,
#             duration=metrics.duration,
#             rate=metrics.rate
#         )

#     except Exception as e:
#         logging.error(f"Error creating dataset: {str(e)}")
#         raise HTTPException(status_code=500, detail=str(e))
