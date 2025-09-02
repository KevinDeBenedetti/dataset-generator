import logging
from fastapi import APIRouter, HTTPException, Query, Depends
from typing import Optional
from enum import Enum
from sqlalchemy.orm import Session
from langfuse import get_client

from app.models.dataset import Dataset, QASource
from app.services.database import get_db
from app.services.langfuse import (
    prepare_langfuse_dataset,
    get_langfuse_client,
    normalize_dataset_name,
    create_langfuse_dataset_with_items,
)

router = APIRouter(
    prefix="/langfuse",
    tags=["langfuse"],
)

def get_dataset_enum(db: Session):
    """Crée une énumération dynamique des noms de datasets disponibles"""
    datasets = db.query(Dataset.name).distinct().all()
    dataset_names = [d.name for d in datasets]
    
    if not dataset_names:
        return type('DatasetEnum', (str, Enum), {'__empty__': 'Aucun dataset disponible'})
    
    enum_dict = {name.replace('-', '_').replace(' ', '_'): name for name in dataset_names}
    return type('DatasetEnum', (str, Enum), enum_dict)

@router.get("/dataset/preview")
async def preview_dataset_transformation(
    db: Session = Depends(get_db),
    dataset_name: str = Query(..., description="Nom du dataset en base de données")
):
    """Prévisualise la transformation du dataset pour Langfuse sans l'envoyer"""
    try:
        # Vérifier que le dataset existe
        dataset = db.query(Dataset).filter(Dataset.name == dataset_name).first()
        if not dataset:
            # Récupérer les datasets disponibles pour le message d'erreur
            available_datasets = [d.name for d in db.query(Dataset.name).distinct().all()]
            raise HTTPException(
                status_code=404, 
                detail=f"Dataset '{dataset_name}' introuvable. Datasets disponibles: {available_datasets}"
            )
        
        # Récupérer les QA pairs associées au dataset
        qa_records = db.query(QASource).filter(QASource.dataset_id == dataset.id).all()
        
        if not qa_records:
            raise HTTPException(status_code=404, detail=f"Aucune donnée QA trouvée pour le dataset '{dataset_name}'")
        
        # Convertir les enregistrements en format approprié pour Langfuse
        data_list = [qa.to_langfuse_dataset_item() for qa in qa_records]
        
        dataset_config, dataset_items = prepare_langfuse_dataset(data_list, dataset_name)
         
        preview_items = dataset_items[:3]
        
        return {
            "dataset_config": dataset_config,
            "sample_items": preview_items,
            "total_items": len(dataset_items),
            "preview_note": f"Affichage de {len(preview_items)} éléments sur un total de {len(dataset_items)}"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logging.exception("Erreur lors de la prévisualisation")
        raise HTTPException(status_code=500, detail=f"Erreur lors de la prévisualisation: {str(e)}")

@router.post("/dataset/export")
async def export_dataset(
    db: Session = Depends(get_db),
    dataset_name: str = Query(..., description="Nom du dataset en base de données"),
    langfuse_dataset_name: Optional[str] = Query(None, description="Nom personnalisé pour le dataset dans Langfuse")
):
    """Exporte un dataset depuis la base de données vers Langfuse"""
    try:
        # Vérifier que le dataset existe
        dataset = db.query(Dataset).filter(Dataset.name == dataset_name).first()
        if not dataset:
            # Récupérer les datasets disponibles pour le message d'erreur
            available_datasets = [d.name for d in db.query(Dataset.name).distinct().all()]
            raise HTTPException(
                status_code=404, 
                detail=f"Dataset '{dataset_name}' introuvable. Datasets disponibles: {available_datasets}"
            )
        
        # Récupérer les QA pairs associées au dataset
        qa_records = db.query(QASource).filter(QASource.dataset_id == dataset.id).all()
        
        if not qa_records:
            raise HTTPException(status_code=404, detail=f"Aucune donnée QA trouvée pour le dataset '{dataset_name}'")
        
        # Résoudre le nom du dataset pour Langfuse
        langfuse_name = langfuse_dataset_name if langfuse_dataset_name else normalize_dataset_name(dataset_name)
        
        # Convertir les enregistrements en format approprié pour Langfuse
        data_list = [qa.to_langfuse_dataset_item() for qa in qa_records]
        
        dataset_config, dataset_items = prepare_langfuse_dataset(data_list, langfuse_name)
        
        result = create_langfuse_dataset_with_items(dataset_config, dataset_items)
        
        logging.info(f"Dataset {dataset_name} exporté avec succès vers Langfuse sous le nom {langfuse_name}")
        
        return {
            "message": "Dataset exporté avec succès",
            "dataset_name": dataset_name,
            "langfuse_dataset_name": langfuse_name,
            **result
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logging.exception("Erreur lors de l'export vers Langfuse")
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors de l'export vers Langfuse: {str(e)}"
        )
