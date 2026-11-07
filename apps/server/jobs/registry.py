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

from server.services.credentials import GITHUB_TOKEN, HF_TOKEN, Credentials
from server.jobs import corpus as corpus_job
from server.jobs import qa_dataset as qa_dataset_job
from server.schemas.recipes import RecipeIn
from server.services import collections as vector_collections
from server.services.collections import COLLECTION_JOB_ID
from server.services.drafts import GENERATION_JOB_ID
from server.services.recipes import RECIPE_JOB_ID

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
        ("Removed", stats.get("removed", 0)),
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
    creds: Credentials,
    options: BaseModel,
    model_ref: Optional[str],
    progress: ProgressFn,
) -> JobOutcome:
    if not isinstance(options, GitHubPersonalOptions):
        raise TypeError(f"Expected GitHubPersonalOptions, got {type(options).__name__}")
    draft = await qa_dataset_job.generate(
        creds,
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
        "removed": list(dataset.get("removed", [])),
    }


async def _publish_github_personal(
    creds: Credentials,
    data: Dict[str, Any],
    exclude: Sequence[str],
    promote: Sequence[str],
    edits: Dict[str, Dict[str, str]],
) -> JobResult:
    draft = _draft_from_dict(data)
    draft.dataset = draft.dataset.with_selection(exclude, promote, edits)
    result = await qa_dataset_job.publish(creds, draft)
    return JobResult(
        dry_run=False,
        url=result["url"],
        metrics=_qa_metrics(draft.stats()),
        errors=draft.dataset.errors,
    )


# --- github-recipe -------------------------------------------------------------


class RecipeRunOptions(BaseModel):
    """Filled by POST /recipes/{id}/run: the recipe as it was when run."""

    recipe_id: str = Field(..., max_length=64)
    recipe: RecipeIn
    full_refresh: bool = Field(
        False, description="Ignore the published version and regenerate every source"
    )


async def _run_github_recipe(
    creds: Credentials,
    options: BaseModel,
    model_ref: Optional[str],
    progress: ProgressFn,
) -> JobOutcome:
    if not isinstance(options, RecipeRunOptions):
        raise TypeError(f"Expected RecipeRunOptions, got {type(options).__name__}")
    draft = await qa_dataset_job.generate_from_recipe(
        creds,
        options.recipe.model_dump(),
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


# --- generation-draft ---------------------------------------------------------
# A file or URL generation kept as a draft (services/drafts.py): inserted
# finished by the generate routes, never queued — only reviewed and published.


class GenerationDraftOptions(BaseModel):
    title: str = ""
    target_repo: str = ""
    source: str = ""


async def _run_generation_draft(
    creds: Credentials,
    options: BaseModel,
    model_ref: Optional[str],
    progress: ProgressFn,
) -> JobOutcome:  # pragma: no cover — these runs are created finished
    raise qa_dataset_job.JobError(
        "A generation draft is created by the generate routes"
    )


def _preview_generation(data: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "repo_id": data.get("repo_id"),
        "kept": data.get("kept", 0),
        "new": list(data.get("pairs") or []),
        "review": [],
        "removed": [],
    }


async def _publish_generation(
    creds: Credentials,
    data: Dict[str, Any],
    exclude: Sequence[str],
    promote: Sequence[str],
    edits: Dict[str, Dict[str, str]],
) -> JobResult:
    from server.services.huggingface import publish_generation_draft

    try:
        result = await run_in_threadpool(
            publish_generation_draft, creds, data, list(exclude), edits
        )
    except ValueError as exc:
        raise qa_dataset_job.JobError(str(exc)) from exc
    return JobResult(
        dry_run=False,
        url=result["url"],
        metrics=[("Published", result["pairs"]), ("New", result["new"])],
    )


# --- vector-collection --------------------------------------------------------
# Embeds a split of a Hub dataset into Qdrant (services/collections.py): queued
# by POST /collections and /collections/{id}/build, never from the Jobs page.


class VectorCollectionOptions(BaseModel):
    collection_id: str = Field(..., max_length=64)


async def _run_vector_collection(
    creds: Credentials,
    options: BaseModel,
    model_ref: Optional[str],
    progress: ProgressFn,
) -> JobOutcome:
    if not isinstance(options, VectorCollectionOptions):
        raise TypeError(
            f"Expected VectorCollectionOptions, got {type(options).__name__}"
        )
    built = await vector_collections.build(creds, options.collection_id, progress)
    return JobOutcome(
        JobResult(
            dry_run=False,
            metrics=[
                ("Points", built["points"]),
                ("Empty rows skipped", built["skipped"]),
                ("Dimensions", built["vector_size"]),
                ("Model", built["model"]),
                ("Commit", built["sha"][:7]),
            ],
        )
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
    creds: Credentials,
    options: BaseModel,
    model_ref: Optional[str],
    progress: ProgressFn,
) -> JobOutcome:
    if not isinstance(options, KnowledgeCorpusOptions):
        raise TypeError(
            f"Expected KnowledgeCorpusOptions, got {type(options).__name__}"
        )
    username = creds.github_username
    if not username:
        raise corpus_job.JobError(
            "Your GitHub username is required (set it in Settings)"
        )
    hf_repo = creds.hf_corpus_repo
    with tempfile.TemporaryDirectory() as tmp:
        directory = Path(tmp)
        manifest = await corpus_job.export_corpus(
            directory,
            list(options.sources) or list(corpus_job.KNOWN_SOURCES),
            username,
            creds.secret(GITHUB_TOKEN) or None,
            hf_repo or "",
        )
        url = None
        if not options.dry_run:
            if not hf_repo:
                raise corpus_job.JobError(
                    "The corpus dataset repo is required in Settings"
                )
            url = await run_in_threadpool(
                corpus_job.push_corpus, creds, directory, hf_repo
            )
    return JobOutcome(
        JobResult(
            dry_run=options.dry_run,
            url=url,
            metrics=[(f["source"], f["records"]) for f in manifest.get("files", [])],
        )
    )


# --- catalogue ----------------------------------------------------------------

_GITHUB_USERNAME = ("your GitHub username", lambda c: bool(c.github_username))
_HF_TOKEN = ("your Hugging Face token", lambda c: c.has(HF_TOKEN))
_HF_QA_REPO = ("the Q&A dataset repo", lambda c: bool(c.hf_qa_repo))
_HF_CORPUS_REPO = ("the corpus dataset repo", lambda c: bool(c.hf_corpus_repo))


@dataclass(frozen=True)
class JobSpec:
    id: str
    title: str
    description: str
    workflow: str
    schedule: str
    # What the job needs from the user's settings: (label, predicate) — shown as
    # "add X in Settings" when the predicate is false for the user's credentials.
    requires: Tuple[Tuple[str, Callable[[Credentials], bool]], ...]
    uses_model: bool
    options: Type[BaseModel]
    runner: Callable[
        [Credentials, BaseModel, Optional[str], ProgressFn], Awaitable[JobOutcome]
    ]
    # Set for draft jobs: publishes a reviewed draft (exclude/promote pair ids,
    # edits of pairs by id).
    publisher: Optional[
        Callable[
            [
                Credentials,
                Dict[str, Any],
                Sequence[str],
                Sequence[str],
                Dict[str, Dict[str, str]],
            ],
            Awaitable[JobResult],
        ]
    ] = None
    # Set for draft jobs: what the review shows (new pairs, pairs to review).
    preview: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None
    # Off the Jobs page (and its POST /jobs/{id}/run) when started elsewhere.
    listed: bool = True

    def missing(self, creds: Credentials) -> List[str]:
        """Labels only, never values — safe to serve to the dashboard."""
        return [label for label, present in self.requires if not present(creds)]


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
            requires=(_GITHUB_USERNAME, _HF_TOKEN, _HF_QA_REPO),
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
            requires=(_GITHUB_USERNAME, _HF_TOKEN, _HF_CORPUS_REPO),
            uses_model=False,
            options=KnowledgeCorpusOptions,
            runner=_run_knowledge_corpus,
        ),
        JobSpec(
            id=RECIPE_JOB_ID,
            title="GitHub recipe",
            description="Q&A pairs from what a dataset recipe selects on GitHub: "
            "its repos, READMEs, docs/ files and profile facts. Started from the "
            "GitHub page; stops at a draft to review, then publishes it to the "
            "recipe's private Hugging Face dataset.",
            workflow="",
            schedule="On demand",
            requires=(_GITHUB_USERNAME, _HF_TOKEN),
            uses_model=True,
            options=RecipeRunOptions,
            runner=_run_github_recipe,
            publisher=_publish_github_personal,
            preview=_preview_github_personal,
            listed=False,
        ),
        JobSpec(
            id=GENERATION_JOB_ID,
            title="File or web page draft",
            description="Q&A pairs generated from an uploaded file or a web page, "
            "kept for review, then merged into a private Hugging Face dataset.",
            workflow="",
            schedule="On demand",
            requires=(_HF_TOKEN,),
            uses_model=False,
            options=GenerationDraftOptions,
            runner=_run_generation_draft,
            publisher=_publish_generation,
            preview=_preview_generation,
            listed=False,
        ),
        JobSpec(
            id=COLLECTION_JOB_ID,
            title="Vector collection",
            description="Embeds a split of one of your Hugging Face datasets into "
            "Qdrant with a local model, so the Collections page can search and "
            "test it. Started from the Collections page.",
            workflow="",
            schedule="On demand",
            requires=(_HF_TOKEN,),
            uses_model=False,
            options=VectorCollectionOptions,
            runner=_run_vector_collection,
            listed=False,
        ),
    )
}
