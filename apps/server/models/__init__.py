# Initialization file to ensure all models are properly imported, so that
# SQLAlchemy's Base.metadata is fully populated (used by Alembic migrations).
from server.models import quality_rules, user  # noqa: F401
