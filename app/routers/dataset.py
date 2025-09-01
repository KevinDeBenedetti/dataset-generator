import logging
from difflib import SequenceMatcher

from fastapi import Depends

from fastapi import APIRouter, Depends, HTTPException, Body, Query
from typing import List
from enum import Enum
from sqlalchemy.orm import Session

from app.utils.common import print_summary, qa_to_dict_list, flatten_urls, is_valid_url
from app.utils.scraper import WebScraper
from app.utils.llm_client import LLMClient
from app.utils.data_manager import DataManager
from app.schemas.scraper import ScrapingMetrics, UrlsConfig
from app.schemas.dataset import TargetLanguage, ModelName, DatasetResult
from app.models.scraper import CleanedText
from app.models.dataset import Dataset, QASource

router = APIRouter(
    tags=["dataset"],
)

from app.services.database import get_db

def get_dataset_names(db: Session) -> List[str]:
    """Récupère la liste des noms de datasets pour la validation"""
    try:
        datasets = db.query(Dataset).all()
        return [dataset.name for dataset in datasets]
    except Exception:
        return []

@router.get("/datasets")
async def get_datasets(db: Session = Depends(get_db)):
    """Récupère la liste de tous les datasets disponibles"""
    try:
        datasets = db.query(Dataset).order_by(Dataset.created_at.desc()).all()
        return [{"id": dataset.id, "name": dataset.name, "description": dataset.description} for dataset in datasets]
    except Exception as e:
        logging.error(f"Error fetching datasets: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

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
        # Vérifier que le dataset existe, sinon le créer
        existing_dataset = db.query(Dataset).filter(Dataset.name == dataset_name).first()
        if not existing_dataset:
            # Créer le dataset automatiquement
            dataset = Dataset(name=dataset_name, description=f"Dataset créé automatiquement pour {url}")
            db.add(dataset)
            db.commit()
            db.refresh(dataset)
            logging.info(f"Created new dataset: {dataset_name}")
        else:
            dataset = existing_dataset
            
        page_snapshot = WebScraper().scrape_url(url)
        page_snapshot.dataset_id = dataset.id

        db.add(page_snapshot)
        db.commit()
        db.refresh(page_snapshot)

        cleaned_text = LLMClient().clean_text(page_snapshot.content, model_cleaning)

        cleaned_text_record = CleanedText(
            page_snapshot_id=page_snapshot.id,
            content=cleaned_text,
            language=target_language,
            model=model_cleaning
        )
        db.add(cleaned_text_record)
        db.commit()

        qa_list = LLMClient().generate_qa(cleaned_text, target_language, model_qa)
        
        qa_records = []
        exact_duplicates = 0
        similar_duplicates = 0
        duplicates_found = 0
        updates = 0

        for i, qa_item in enumerate(qa_list):
            duplicate_check = QASource.check_for_duplicates(
                db=db,
                question=qa_item.question,
                answer=qa_item.answer,
                context=cleaned_text,
                source_url=url,
                similarity_threshold=similarity_threshold
            )

            if duplicate_check["type"] == "exact":
                exact_duplicates += 1
                logging.info(f"Exact duplicate found (ID: {duplicate_check['duplicate_id'][:8]}...), skipping")
             
            elif duplicate_check["type"] == "similar":
                similar_duplicates += 1
                similarity_score = duplicate_check["similarity_score"]
                logging.info(f"Similar question found (similarity: {similarity_score:.2f}, ID: {duplicate_check['duplicate_id'][:8]}...), skipping")
                
                # Optionnel : mettre à jour avec une meilleure réponse
                # existing_record = db.query(QASource).filter(QASource.id == duplicate_check['duplicate_id']).first()
                # if self.is_better_answer(qa_item, existing_record):
                #     existing_record.expected_output = {"answer": qa_item.answer, "confidence": getattr(qa_item, 'confidence', 1.0)}
                #     existing_record.updated_at = datetime.now(timezone.utc)
                #     updates += 1
                
            else:  # nouveau
                qa_record = QASource.from_qa_generation(
                    question=qa_item.question,
                    answer=qa_item.answer,
                    context=cleaned_text,
                    confidence=getattr(qa_item, 'confidence', 1.0),
                    source_url=url,
                    page_snapshot_id=page_snapshot.id,
                    index=i
                )
                
                qa_record.dataset_name = dataset_name
                qa_record.model = model_qa
                qa_records.append(qa_record)
                db.add(qa_record)
        db.commit()

        logging.info(f"Added {len(qa_records)} new QA pairs, "
            f"skipped {exact_duplicates} exact duplicates, "
            f"skipped {similar_duplicates} similar duplicates")

        return {
            "qa_pairs": qa_list,
            "new_pairs": len(qa_records),
            "exact_duplicates_skipped": exact_duplicates,
            "similar_duplicates_skipped": similar_duplicates,
            "similarity_threshold": similarity_threshold
        }
    
    except Exception as e:
        logging.error(f"Error creating dataset: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/dataset/{dataset_name}/analyze-similarities")
async def analyze_similarities(
    dataset_name: str,
    threshold: float = Query(0.8, description="Seuil de similarité"),
    db: Session = Depends(get_db)
):
    """Analyse les questions similaires dans un dataset"""
    records = db.query(QASource).filter(QASource.dataset_name == dataset_name).all()
    
    similarities = []
    processed_pairs = set()
    
    for i, record1 in enumerate(records):
        for j, record2 in enumerate(records[i+1:], i+1):
            pair_key = tuple(sorted([record1.id, record2.id]))
            if pair_key in processed_pairs:
                continue
            
            question1 = record1.input.get('question', '')
            question2 = record2.input.get('question', '')
            
            similarity = SequenceMatcher(None, question1, question2).ratio()
            
            if similarity >= threshold:
                similarities.append({
                    "record1_id": record1.id[:8],
                    "record2_id": record2.id[:8],
                    "similarity": round(similarity, 3),
                    "question1": question1[:100] + "..." if len(question1) > 100 else question1,
                    "question2": question2[:100] + "..." if len(question2) > 100 else question2
                })
            
            processed_pairs.add(pair_key)
    
    return {
        "dataset": dataset_name,
        "threshold": threshold,
        "total_records": len(records),
        "similar_pairs_found": len(similarities),
        "similarities": sorted(similarities, key=lambda x: x["similarity"], reverse=True)
    }

@router.post("/dataset/create")
async def create_new_dataset(
    name: str = Query(..., description="Nom du nouveau dataset"),
    description: str = Query(None, description="Description optionnelle du dataset"),
    db: Session = Depends(get_db)
):
    """Crée un nouveau dataset"""
    try:
        # Vérifier que le nom n'existe pas déjà
        existing = db.query(Dataset).filter(Dataset.name == name).first()
        if existing:
            raise HTTPException(status_code=400, detail=f"Dataset with name '{name}' already exists")
        
        dataset = Dataset(name=name, description=description)
        db.add(dataset)
        db.commit()
        db.refresh(dataset)
        
        return {"id": dataset.id, "name": dataset.name, "description": dataset.description, "message": "Dataset created successfully"}
    
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Error creating new dataset: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/dataset")
# @router.post("/dataset", response_model=DatasetResult)
async def create_dataset(
    urls_config: UrlsConfig = Body(
        ..., 
        description="Structured configuration for URLs to scrape (any structure)",
        openapi_examples={
            "Example": {
                "summary": "Full example configuration",
                "description": "Typical configuration based on urls.json.example",
                "value": {
                    "official_sources": {
                        "main_site": {
                            "url": "https://example-official.gov",
                            "description": "Main official website of the organization"
                        }
                    }
                }
            }
        }),
    target_language: TargetLanguage = Query(),
    model_cleaning: ModelName = Query(),
    model_qa: ModelName = Query(),
):
    try:
        logging.info("Received dataset creation request")

        scraper = WebScraper()
        llm_client = LLMClient()
        data_manager = DataManager()
        metrics = ScrapingMetrics()
        metrics.start_timer()

        all_paths: List[str] = []

        def process_single_url(url: str, dataset_name: str) -> List[str]:
            """Processing a single URL: scraping, cleaning, QA generation, saving."""
            try:
                page_snapshot = scraper.scrape_url(url)
                metrics.urls_processed += 1

                logging.info(f"Processed URL: {url}")

                # save raw markdown
                md_path = data_manager.save_markdown(page_snapshot)
                logging.info(f"Saved markdown: {md_path}")

                # cleaning via LLM
                cleaned_text = llm_client.clean_text(page_snapshot.content, model_cleaning)

                # save cleaned text
                txt_path = data_manager.save_cleaned_text(page_snapshot, cleaned_text)
                logging.info(f"Saved cleaned text: {txt_path}")

                # QA generation
                qa_list = llm_client.generate_qa(cleaned_text, target_language, model_qa)
                qa_dicts = qa_to_dict_list(qa_list)
                metrics.qa_pairs_generated += len(qa_dicts)

                # Sauvegarder les paires QA dans la base de données
                for i, qa_item in enumerate(qa_list):
                    qa_record = QASource.from_qa_generation(
                        question=qa_item.question,
                        answer=qa_item.answer,
                        context=cleaned_text,
                        confidence=getattr(qa_item, 'confidence', 1.0),
                        source_url=url,
                        page_snapshot_id=page_snapshot.id,
                        index=i
                    )
                    
                    # Vérifier si l'enregistrement existe déjà
                    existing = db.query(QASource).filter(QASource.id == qa_record.id).first()
                    if not existing:
                        qa_record.dataset_name = dataset_name
                        qa_record.model = model_qa
                        db.add(qa_record)
                    else:
                        logging.info(f"QA pair already exists, skipping: {qa_record.id}")

                # save datasets if present
                if qa_dicts:
                    dataset_structure = {
                        dataset_name or "general": {
                            f"qa_{i}": qa_dict for i, qa_dict in enumerate(qa_dicts)
                        }
                    }
                    dataset_paths = data_manager.save_dataset(dataset_structure)
                    logging.info(f"Saved datasets: {[str(p) for p in dataset_paths]}")
                    return dataset_paths

                return []

            except Exception as e:
                error_msg = f"Error processing {url}: {str(e)}"
                metrics.add_error(error_msg)
                logging.error(error_msg)
                return []


        urls_items = flatten_urls(urls_config.model_dump())
        logging.info(f"Flattened URLs: {urls_items}")

        for dataset_name, url in urls_items:
            if not is_valid_url(url):
                msg = f"Invalid URL skipped: {url} (dataset={dataset_name})"
                metrics.add_error(msg)
                logging.warning(msg)
                print(f"❌ {dataset_name}: {url} (invalid)")
                continue

            logging.info(f"Processing {url} for dataset '{dataset_name}'")
            paths = process_single_url(url, dataset_name)
            if paths:
                all_paths.extend(paths)
                print(f"✅ {dataset_name}: {url}")
            else:
                print(f"❌ {dataset_name}: Processing failed for {url}")

        metrics.stop_timer()
        metrics.calculate_rate()

        print_summary(metrics, all_paths)

        files = [str(p) for p in all_paths] if all_paths else []

        return DatasetResult(
            task_id="dataset-creation",
            status="completed",
            urls_processed=metrics.urls_processed,
            qa_pairs_generated=metrics.qa_pairs_generated,
            files_generated=files,
            errors=metrics.errors,
            duration=metrics.duration,
            rate=metrics.rate
        )

    except Exception as e:
        logging.error(f"Error creating dataset: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))