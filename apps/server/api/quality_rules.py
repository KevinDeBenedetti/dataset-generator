import logging

from fastapi import APIRouter, Depends, HTTPException

from server.schemas.quality_rules import QualityRulesResponse, QualityRulesUpdate
from server.services.auth import require_admin
from server.services.quality_rules import get_quality_rules, update_quality_rules

router = APIRouter(
    prefix="/quality-rules",
    tags=["quality-rules"],
)


@router.get("", response_model=QualityRulesResponse)
async def read_quality_rules() -> QualityRulesResponse:
    """The persisted generation-time quality rules (defaults when unset)."""
    return QualityRulesResponse(**get_quality_rules())


@router.put(
    "",
    response_model=QualityRulesResponse,
    dependencies=[Depends(require_admin)],
)
async def put_quality_rules(body: QualityRulesUpdate) -> QualityRulesResponse:
    """Update the quality rules (admin only). Partial: omitted fields keep
    their current value."""
    try:
        return QualityRulesResponse(
            **update_quality_rules(
                min_answer_words=body.min_answer_words,
                reject_below_confidence=body.reject_below_confidence,
                auto_reject_enabled=body.auto_reject_enabled,
            )
        )
    except Exception as e:
        logging.exception("Error updating quality rules")
        raise HTTPException(status_code=500, detail=str(e))
