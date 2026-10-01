# Initialization file to ensure all models are properly imported, so that
# SQLAlchemy's Base.metadata is fully populated (used by Alembic migrations).
from server.models import (  # noqa: F401
    dataset,
    identity,
    job_run,
    model_defaults,
    platform_settings,
    quality_rules,
    user,
    user_secret,
)
