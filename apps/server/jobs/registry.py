"""Catalogue of dataset jobs — one entry per job, shared by the API and the UI.

Each job is defined in code (a :class:`JobSpec`): what it needs from the
environment, the options it accepts (a pydantic model, served as JSON schema
so the Jobs page renders its form), whether it calls a model, and how to run
it. The same code runs on its GitHub Actions schedule (``workflow``) and on
demand from the Jobs page. Adding a job = adding an entry to :data:`JOBS`.

A job either publishes directly (``publisher`` is None), or produces a
*draft*: the run generates and stops, the user reviews the result on the Jobs
page, and ``publisher`` pushes that exact draft — nothing is regenerated.
"""

import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import (
    Any,
    Awaitable,
    Callable,
    Dict,
    List,
    Literal,
    Optional,
    Sequence,
    Tuple,
    Type,
    get_args,
)

from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from server.core.config import _env
from server.jobs import corpus as corpus_job
from server.jobs import qa_dataset as qa_dataset_job

# Both jobs raise their own JobError for anything the caller can act on.
JOB_ERRORS: Tuple[Type[Exception], ...] = (corpus_job.JobError, qa_dataset_job.JobError)

# (done, total, label) — e.g. repos generated so far.
ProgressFn = Callable[[int, int, str], None]


class JobResult(BaseModel):
    """What every job reports back, whatever it does."""

    dry_run: bool
    url: Optional[str] = Field(None, description="Published dataset URL, if any")
    metrics: List[Tuple[str, Any]] = Field(
        default_factory=list, description="(label, value) pairs, in display order"
    )
    errors: List[str] = Field(default_factory=list)


@dataclass
class JobOutcome:
    result: JobResult
    # JSON-safe unpublished output, for jobs with a publisher.
    draft: Optional[Dict[str, Any]] = None


# --- github-personal ----------------------------------------------------------


class GitHubPersonalOptions(BaseModel):
    max_repos: Optional[int] = Field(
        None,
        ge=1,
        description="Leave empty to process every public repo; set 1 or 2 for a "
        "cheap test run (the most-starred ones)",
    )
    full_refresh: bool = Field(
        False, description="Ignore the published version and regenerate every source"
    )


def _qa_metrics(stats: Dict[str, Any]) -> List[Tuple[str, Any]]:
    return [
        ("Pairs", stats["records"]),
        ("Kept", stats["kept"]),
        ("New", stats["new"]),
        ("Dropped", stats["dropped"]),
        ("Rephrasings rejected", stats["semantic_duplicates"]),
        ("To review", stats["review"]),
        ("Model", stats["model"]),
    ]


def _draft_to_dict(draft: qa_dataset_job.Draft) -> Dict[str, Any]:
    return {
        "dataset": draft.dataset.to_dict(),
        "username": draft.username,
        "repo_id": draft.repo_id,
        "full_refresh": draft.full_refresh,
        "model_ref": draft.model_ref,
    }


def _draft_from_dict(data: Dict[str, Any]) -> qa_dataset_job.Draft:
    return qa_dataset_job.Draft(
        dataset=qa_dataset_job.QADataset.from_dict(data["dataset"]),
        username=data["username"],
        repo_id=data["repo_id"],
        full_refresh=data.get("full_refresh", False),
        model_ref=data.get("model_ref", ""),
    )


async def _run_github_personal(
    options: BaseModel, model_ref: Optional[str], progress: ProgressFn
) -> JobOutcome:
    assert isinstance(options, GitHubPersonalOptions)
    draft = await qa_dataset_job.generate(
        max_repos=options.max_repos,
        full_refresh=options.full_refresh,
        model_ref=model_ref,
        on_progress=progress,
    )
    return JobOutcome(
        result=JobResult(
            dry_run=True,
            metrics=_qa_metrics(draft.stats()),
            errors=draft.dataset.errors,
        ),
        draft=_draft_to_dict(draft),
    )


def _preview_github_personal(data: Dict[str, Any]) -> Dict[str, Any]:
    dataset = data["dataset"]
    new_ids = set(dataset.get("new_ids", []))
    return {
        "repo_id": data.get("repo_id"),
        "kept": dataset.get("kept", 0),
        "new": [p for p in dataset.get("pairs", []) if p.get("id") in new_ids],
        "review": list(dataset.get("review", [])),
    }


async def _publish_github_personal(
    data: Dict[str, Any], exclude: Sequence[str], promote: Sequence[str]
) -> JobResult:
    draft = _draft_from_dict(data)
    draft.dataset = draft.dataset.with_selection(exclude, promote)
    result = await qa_dataset_job.publish(draft)
    return JobResult(
        dry_run=False,
        url=result["url"],
        metrics=_qa_metrics(draft.stats()),
        errors=draft.dataset.errors,
    )


# --- knowledge-corpus ---------------------------------------------------------

CorpusSource = Literal["profile", "github", "github_code", "github_docs"]


class KnowledgeCorpusOptions(BaseModel):
    sources: List[CorpusSource] = Field(
        default_factory=lambda: list(get_args(CorpusSource)),
        description="Splits to build",
    )
    dry_run: bool = Field(True, description="Build the corpus but don't publish it")


async def _run_knowledge_corpus(
    options: BaseModel, model_ref: Optional[str], progress: ProgressFn
) -> JobOutcome:
    assert isinstance(options, KnowledgeCorpusOptions)
    username = _env("GITHUB_USERNAME")
    if not username:
        raise corpus_job.JobError("GITHUB_USERNAME is not configured on the server")
    hf_repo = _env("HF_DATASET_REPO")
    with tempfile.TemporaryDirectory() as tmp:
        directory = Path(tmp)
        manifest = await corpus_job.export_corpus(
            directory,
            list(options.sources) or list(corpus_job.KNOWN_SOURCES),
            username,
            _env("GITHUB_TOKEN") or None,
            hf_repo or "",
        )
        url = None
        if not options.dry_run:
            if not hf_repo:
                raise corpus_job.JobError(
                    "HF_DATASET_REPO is not configured on the server"
                )
            url = await run_in_threadpool(corpus_job.push_corpus, directory, hf_repo)
    return JobOutcome(
        JobResult(
            dry_run=options.dry_run,
            url=url,
            metrics=[(f["source"], f["records"]) for f in manifest.get("files", [])],
        )
    )


# --- catalogue ----------------------------------------------------------------


@dataclass(frozen=True)
class JobSpec:
    id: str
    title: str
    description: str
    workflow: str
    schedule: str
    required_env: Tuple[str, ...]
    uses_model: bool
    options: Type[BaseModel]
    runner: Callable[[BaseModel, Optional[str], ProgressFn], Awaitable[JobOutcome]]
    # Set for draft jobs: publishes a reviewed draft (exclude/promote pair ids).
    publisher: Optional[
        Callable[[Dict[str, Any], Sequence[str], Sequence[str]], Awaitable[JobResult]]
    ] = None
    # Set for draft jobs: what the review shows (new pairs, pairs to review).
    preview: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None

    def missing_env(self) -> List[str]:
        """Names only, never values — safe to serve to the dashboard."""
        return [name for name in self.required_env if not _env(name)]


JOBS: Dict[str, JobSpec] = {
    spec.id: spec
    for spec in (
        JobSpec(
            id="github-personal",
            title="GitHub personal Q&A",
            description="Q&A pairs from your GitHub profile, repo READMEs and docs/ "
            "folders. Generate a draft, review it, then publish it to your private "
            "Hugging Face dataset. Incremental: only sources that changed since the "
            "published version are sent to the model.",
            workflow="qa-dataset-sync.yml",
            schedule="Mondays 06:00 UTC",
            required_env=("GITHUB_USERNAME", "HF_TOKEN", "HF_QA_DATASET_REPO"),
            uses_model=True,
            options=GitHubPersonalOptions,
            runner=_run_github_personal,
            publisher=_publish_github_personal,
            preview=_preview_github_personal,
        ),
        JobSpec(
            id="knowledge-corpus",
            title="Knowledge corpus",
            description="Retrieval corpus (profile, repos, code chunks, docs) built from "
            "the GitHub API — no model involved — published to a private Hugging Face "
            "dataset.",
            workflow="dataset-sync.yml",
            schedule="Mondays 04:00 UTC",
            required_env=("GITHUB_USERNAME", "HF_TOKEN", "HF_DATASET_REPO"),
            uses_model=False,
            options=KnowledgeCorpusOptions,
            runner=_run_knowledge_corpus,
        ),
    )
}
