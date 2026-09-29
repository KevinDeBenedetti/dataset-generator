import logging

from fastapi import APIRouter, Depends, HTTPException

from server.jobs.corpus import JobError as CorpusJobError
from server.jobs.qa_dataset import JobError as QADatasetJobError
from server.schemas.jobs import (
    CorpusSyncRequest,
    CorpusSyncResponse,
    JobsStatusResponse,
    QADatasetSyncRequest,
    QADatasetSyncResponse,
)
from server.services.auth import require_admin
from server.services.jobs import jobs_status, run_corpus_sync, run_qa_dataset_sync

router = APIRouter(prefix="/jobs", tags=["jobs"])
logger = logging.getLogger(__name__)


@router.get("/status", response_model=JobsStatusResponse)
async def get_jobs_status():
    """Whether each scheduled job's required server env vars are set."""
    return jobs_status()


@router.post(
    "/corpus-sync",
    response_model=CorpusSyncResponse,
    # Publishes outside the app — admin only, like the Hugging Face export route.
    dependencies=[Depends(require_admin)],
)
async def trigger_corpus_sync(body: CorpusSyncRequest):
    """Run the weekly portfolio knowledge-corpus job on demand.

    Builds every requested split from the GitHub API and, unless `dry_run`,
    publishes them to the configured private Hugging Face dataset in one
    commit — the same job `dataset-sync.yml` runs on its Monday schedule.
    """
    try:
        return await run_corpus_sync(body.sources, body.dry_run)
    except CorpusJobError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logging.error(f"Error running corpus sync job: {str(e)}")
        raise HTTPException(status_code=502, detail=f"Corpus sync failed: {e}")


@router.post(
    "/qa-dataset-sync",
    response_model=QADatasetSyncResponse,
    # Spends Claude subscription usage and publishes outside the app — admin only.
    dependencies=[Depends(require_admin)],
)
async def trigger_qa_dataset_sync(body: QADatasetSyncRequest):
    """Run the GitHub Q&A dataset job on demand.

    Generates pairs via the Claude Agent SDK (billed against the configured
    Claude subscription) and, unless `dry_run`, publishes them to the
    configured private Hugging Face dataset — the same job
    `qa-dataset-sync.yml` runs on its Monday schedule. Set `max_repos` to a
    small number for a cheap test run.
    """
    try:
        return await run_qa_dataset_sync(body.max_repos, body.dry_run)
    except QADatasetJobError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logging.error(f"Error running QA dataset sync job: {str(e)}")
        raise HTTPException(status_code=502, detail=f"QA dataset sync failed: {e}")
