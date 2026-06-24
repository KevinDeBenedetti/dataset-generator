# Initialization file to ensure all models are properly imported, so that
# SQLAlchemy's Base.metadata is fully populated (used by Alembic migrations).
from server.models import dataset, scraper, user  # noqa: F401
