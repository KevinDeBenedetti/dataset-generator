import logging
from typing import List, Dict, Any, Tuple
from sqlalchemy.orm import Session
from app.models.dataset import QASource

class QAService:
    def __init__(self, db: Session):
        self.db = db
    
    def process_qa_pairs(self, qa_list: List[Any], cleaned_text: str, url: str, 
                        page_snapshot_id: int, dataset_name: str, model: str, 
                        dataset_id: str = None,
                        similarity_threshold: float = 0.9) -> Dict[str, int]:
        """Processes and saves QA pairs, checking for duplicates"""
        qa_records = []
        exact_duplicates = 0
        similar_duplicates = 0
        
        for i, qa_item in enumerate(qa_list):
            duplicate_check = QASource.check_for_duplicates(
                db=self.db,
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
                
            else:  # new
                qa_record = QASource.from_qa_generation(
                    question=qa_item.question,
                    answer=qa_item.answer,
                    context=cleaned_text,
                    confidence=getattr(qa_item, 'confidence', 1.0),
                    source_url=url,
                    page_snapshot_id=page_snapshot_id,
                    dataset_id=dataset_id,  # Passage du dataset_id
                    index=i
                )
                
                qa_record.dataset_name = dataset_name
                qa_record.model = model
                qa_records.append(qa_record)
                self.db.add(qa_record)
        
        self.db.commit()

        logging.info(f"Added {len(qa_records)} new QA pairs, "
            f"skipped {exact_duplicates} exact duplicates, "
            f"skipped {similar_duplicates} similar duplicates")
            
        return {
            "new_pairs": len(qa_records),
            "exact_duplicates_skipped": exact_duplicates,
            "similar_duplicates_skipped": similar_duplicates
        }
