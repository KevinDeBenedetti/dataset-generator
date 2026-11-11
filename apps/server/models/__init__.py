# Initialization file to ensure all models are properly imported, so that
# SQLAlchemy's Base.metadata is fully populated (used by Alembic migrations).
from server.models import (  # noqa: F401
    dataset,
    dataset_recipe,
    embedding_calibration,
    identity,
    job_run,
    job_schedule,
    model_defaults,
    platform_settings,
    quality_rules,
    user,
    user_secret,
    vector_collection,
)
