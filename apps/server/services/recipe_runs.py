"""Running a recipe: fetch its data source, load it, apply its steps.

A run (``job_id="recipe"``, jobs/registry.py) writes its rows to the draft
store (``<owner>/<run_id>/data.parquet``) and returns the draft's metadata:
schema, profile, per-step row counts, provenance, fingerprint — never the rows.
A **preview** does the same on the data source's first rows, in a folder of
its own (``<owner>/preview-<recipe_id>/``), with a shorter timeout; the loaded
table is kept there as Parquet so the next preview skips the fetch.
"""

import asyncio
import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from server.connectors import get_connector
from server.connectors.base import ConnectorError, FetchResult, Limits
from server.core.config import config
from server.core.database import get_scoped_db
from server.engine.load import TABLE, load, load_cached
from server.engine.profile import preview_rows, profile, write_parquet
from server.engine.session import EngineError, session
from server.engine.steps import StepError, apply_steps, table_schema
from server.models.data_source import DataSource, OutputKind
from server.services import data_sources as service
from server.services.credentials import Credentials

logger = logging.getLogger(__name__)

PREVIEW_ROWS = 100
PREVIEW_TIMEOUT_S = 20.0
RESULT = "result"


class RecipeRunError(ValueError):
    """What stops a recipe run, in words for the user."""


@dataclass
class _Loaded:
    recipe: Dict[str, Any]
    source: Dict[str, Any]


def _load_rows(owner_id: str, recipe_id: str) -> _Loaded:
    with get_scoped_db() as db:
        recipe = service.get_recipe(db, owner_id, recipe_id)
        source = service.get_source(db, owner_id, recipe["data_source_id"])
    return _Loaded(recipe, source)


async def _fetch(
    owner_id: str, source: Dict[str, Any], creds: Credentials, dest: Path
) -> FetchResult:
    connector = get_connector(source["connector"])
    if connector is None:
        raise RecipeRunError(f"Unknown connector '{source['connector']}'")
    from server.services.draft_store import get_store

    get_store().ensure_quota(owner_id)
    result = await connector.fetch(
        owner_id,
        source["id"],
        source["config"],
        creds,
        dest,
        Limits(
            max_bytes=config.data_upload_max_bytes, timeout_s=config.engine_timeout_s
        ),
    )
    if source.get("licence") and not result.provenance.licence:
        result.provenance.licence = source["licence"]
    return result


def _record_fetch(owner_id: str, source_id: str, fingerprint: str) -> None:
    with get_scoped_db() as db:
        row = db.get(DataSource, source_id)
        if row is not None and row.owner_id == owner_id:
            row.last_fingerprint = fingerprint
            row.last_fetched_at = datetime.now(timezone.utc)
            db.commit()


def _previous_rows(owner_id: str, recipe_id: str) -> Optional[int]:
    """The row count of the recipe's last published draft, if any."""
    from sqlalchemy import select

    from server.models.job_run import JobRun

    with get_scoped_db() as db:
        rows = db.scalars(
            select(JobRun)
            .where(
                JobRun.owner_id == owner_id,
                JobRun.job_id == "recipe",
                JobRun.status == "published",
            )
            .order_by(JobRun.started_at.desc())
        )
        for run in rows:
            if (run.options or {}).get("recipe_id") == recipe_id and run.draft:
                count = run.draft.get("rows")
                return int(count) if isinstance(count, int) else None
    return None


def _build(
    run_dir: Path,
    fetched: FetchResult,
    steps: List[Dict[str, Any]],
    *,
    rules: Optional[Dict[str, Any]] = None,
    public: bool = False,
    previous_rows: Optional[int] = None,
    facts_options: Any = None,
    recipe_id: str = "",
    source_url: str = "",
) -> Dict[str, Any]:
    """Load, apply the steps, write ``data.parquet``; the draft's metadata,
    with its quality report — and its Q&A pairs for a facts recipe."""
    from server.review.tabular_quality import quality_report

    with session(run_dir) as s:
        loaded = load(s, fetched)
        applied = apply_steps(s, steps, source=TABLE, target=RESULT)
        size = write_parquet(s, RESULT, run_dir / "data.parquet")
        result_profile = profile(s, RESULT)
        report = quality_report(
            s,
            RESULT,
            result_profile,
            steps,
            rules,
            public=public,
            previous_rows=previous_rows,
        )
        pairs = None
        if facts_options is not None:
            from server.engine.profile import iter_rows
            from server.generators.facts import TemplateError, check_columns, facts

            try:
                check_columns(facts_options, [n for n, _ in applied.schema])
            except TemplateError as exc:
                raise EngineError(str(exc)) from None
            pairs = facts(
                facts_options,
                iter_rows(s, RESULT),
                source=source_url,
                recipe_id=recipe_id,
                created_at=datetime.now(timezone.utc).isoformat(),
            )
        return {
            **(
                {"pairs": pairs, "language": facts_options.language}
                if pairs is not None
                else {}
            ),
            "source_rows": loaded.rows,
            "source_schema": loaded.schema(),
            "rows": applied.rows,
            "schema": [{"name": n, "type": t} for n, t in applied.schema],
            "step_rows": applied.step_rows,
            "profile": result_profile,
            "quality_report": report,
            "data_path": "data.parquet",
            "data_bytes": size,
        }


async def run_recipe(
    creds: Credentials,
    recipe_id: str,
    run_id: str,
    progress: Callable[[int, int, str], None],
) -> Dict[str, Any]:
    """One recipe run: the draft's metadata (``job_runs.draft``)."""
    from server.services.draft_store import DraftQuotaExceeded, get_store

    owner_id = creds.user_id
    if not owner_id or not run_id:
        raise RecipeRunError("A recipe runs for a user, in a run")
    try:
        loaded = await asyncio.to_thread(_load_rows, owner_id, recipe_id)
    except service.NotFound as exc:
        raise RecipeRunError(str(exc)) from None
    recipe, source = loaded.recipe, loaded.source
    facts_options = None
    llm_options = None
    if recipe["output_kind"] == OutputKind.QA:
        from pydantic import ValidationError

        from server.generators.facts import FactsOptions

        generator = (recipe.get("output_options") or {}).get("generator", "facts")
        if generator not in ("facts", "llm"):
            raise RecipeRunError(f"Unknown Q&A generator '{generator}'")
        try:
            if generator == "llm":
                from server.generators.qa_llm import LlmOptions

                llm_options = LlmOptions.model_validate(recipe["output_options"])
            else:
                facts_options = FactsOptions.model_validate(recipe["output_options"])
        except ValidationError as exc:
            first = exc.errors()[0]
            raise RecipeRunError(
                "output_options: " + str(first.get("msg", "invalid"))
            ) from None
    corpus_options = None
    if recipe["output_kind"] == OutputKind.CORPUS:
        from pydantic import ValidationError

        from server.generators.corpus import CorpusOptions

        try:
            corpus_options = CorpusOptions.model_validate(
                recipe.get("output_options") or {}
            )
        except ValidationError as exc:
            first = exc.errors()[0]
            raise RecipeRunError(
                "output_options: " + str(first.get("msg", "invalid"))
            ) from None
    store = get_store()
    run_dir = store.run_dir(owner_id, run_id)
    try:
        progress(0, 3, "Fetching the data source")
        fetched = await _fetch(owner_id, source, creds, store.raw_dir(owner_id, run_id))
        connector = get_connector(source["connector"])
        fingerprint = (
            connector.fingerprint(fetched) if connector else fetched.provenance.sha256
        )
        progress(1, 3, "Loading and applying the steps")
        from server.services.quality_rules import get_quality_rules

        rules = (await asyncio.to_thread(get_quality_rules, owner_id)).get("tabular")
        previous = await asyncio.to_thread(_previous_rows, owner_id, recipe["id"])
        meta = await asyncio.to_thread(
            lambda: _build(
                run_dir,
                fetched,
                recipe["steps"],
                rules=rules,
                public=recipe["visibility"] == "public",
                previous_rows=previous,
                facts_options=facts_options,
                recipe_id=recipe["id"],
                source_url=fetched.provenance.url or "",
            )
        )
        progress(2, 3, "Profiling")
        store.ensure_quota(owner_id)
    except DraftQuotaExceeded:
        store.delete(owner_id, run_id)
        raise RecipeRunError(
            "Your storage for data is full: delete some drafts"
        ) from None
    except (ConnectorError, EngineError) as exc:
        store.delete(owner_id, run_id)
        raise RecipeRunError(str(exc)) from None
    if corpus_options is not None:
        meta = {
            **meta,
            **await asyncio.to_thread(_corpus_docs, run_dir, corpus_options),
        }
    previous = source.get("last_fingerprint")
    llm_draft: Optional[Dict[str, Any]] = None
    if llm_options is not None:
        llm_draft = await _llm_draft(
            creds, recipe, run_dir, llm_options, fetched, progress
        )
    await asyncio.to_thread(_record_fetch, owner_id, source["id"], fingerprint)
    progress(3, 3, "Done")
    kind = "qa" if facts_options is not None else "table"
    if llm_draft is not None:
        kind = "qa_llm"
    if corpus_options is not None:
        kind = "corpus"
    return {
        **(llm_draft or {}),
        "previous_fingerprint": previous,
        "kind": kind,
        # What a Q&A draft's review and publication read (services/drafts.py).
        "repo_id": _complete_repo(creds, recipe["target_repo"]),
        "title": recipe["name"],
        "source": fetched.provenance.url or source["name"],
        "kept": 0,
        "recipe_id": recipe["id"],
        "data_source_id": source["id"],
        "target_repo": recipe["target_repo"],
        "visibility": recipe["visibility"],
        "steps": recipe["steps"],
        "fingerprint": fingerprint,
        "provenance": fetched.provenance.to_dict(),
        "format": fetched.format,
        "warnings": list(fetched.warnings),
        **meta,
    }


def _corpus_docs(run_dir: Path, options: Any) -> Dict[str, Any]:
    """The run's table as corpus documents: ``data.parquet`` rewritten with
    them, and the schema and profile of the documents."""
    from server.engine.load import load_cached
    from server.engine.profile import iter_rows
    from server.engine.steps import table_schema
    from server.generators.corpus import check_columns, documents, write_documents
    from server.generators.facts import TemplateError

    data = run_dir / "data.parquet"
    docs = run_dir / "documents.parquet"
    with session(run_dir) as s:
        load_cached(s, data)
        try:
            check_columns(options, [n for n, _ in table_schema(s, TABLE)])
            count = write_documents(docs, documents(options, iter_rows(s, TABLE)))
        except TemplateError as exc:
            raise RecipeRunError(str(exc)) from None
    docs.replace(data)
    with session(run_dir) as s:
        load_cached(s, data)
        return {
            "rows": count,
            "schema": [{"name": n, "type": t} for n, t in table_schema(s, TABLE)],
            "profile": profile(s, TABLE),
            "data_bytes": data.stat().st_size,
        }


def _row_sources(run_dir: Path, options: Any, recipe_id: str):
    """The text sources of the run's table (data.parquet), in a sandboxed session."""
    from server.engine.load import load_cached
    from server.engine.profile import iter_rows
    from server.engine.steps import table_schema
    from server.generators.facts import TemplateError
    from server.generators.qa_llm import check_columns, sources_of_rows

    with session(run_dir) as s:
        load_cached(s, run_dir / "data.parquet")
        try:
            check_columns(options, [n for n, _ in table_schema(s, TABLE)])
        except TemplateError as exc:
            raise RecipeRunError(str(exc)) from None
        return sources_of_rows(options, iter_rows(s, TABLE), recipe_id)


async def _llm_draft(
    creds: Credentials,
    recipe: Dict[str, Any],
    run_dir: Path,
    options: Any,
    fetched: FetchResult,
    progress: Callable[[int, int, str], None],
) -> Dict[str, Any]:
    """A Q&A draft by the user's model over the table's rows (#316)."""
    from server.generators.qa_llm import (
        build_rows_dataset,
        estimate_tokens,
        own_recipe_pair,
    )
    from server.jobs.qa_build import JobError, generate_draft

    sources = await asyncio.to_thread(_row_sources, run_dir, options, recipe["id"])
    estimate = estimate_tokens(options, sources)
    if estimate > config.quota_tokens_per_run:
        raise RecipeRunError(
            f"This run could spend about {estimate} tokens, more than the "
            f"{config.quota_tokens_per_run} allowed: group fewer rows, or filter them"
        )
    calls = {"n": 0}

    async def make(run):
        dataset, made = await build_rows_dataset(
            run,
            options,
            sources,
            on_progress=lambda done, total, label: progress(
                1, 3, f"Generating {done}/{total}"
            ),
        )
        calls["n"] = made
        return dataset, recipe["name"]

    try:
        draft = await generate_draft(
            creds,
            recipe["target_repo"],
            own_recipe_pair(recipe["id"]),
            make,
            missing_repo="The recipe names no Hugging Face repo",
            model_ref=recipe.get("model_ref"),
        )
    except JobError as exc:
        raise RecipeRunError(str(exc)) from None
    return {
        "dataset": draft.dataset.to_dict(),
        "username": draft.username,
        "repo_id": draft.repo_id,
        "full_refresh": draft.full_refresh,
        "model_ref": draft.model_ref,
        "base_commit": draft.base_commit,
        "model_calls": calls["n"],
        "estimated_tokens": estimate,
        "groups": len(sources),
    }


def _complete_repo(creds: Credentials, target: str) -> str:
    """``namespace/name``: a bare name takes the namespace saved in Settings."""
    target = target.strip()
    if "/" in target or not creds.hf_namespace:
        return target
    return f"{creds.hf_namespace}/{target}"


# --- preview -------------------------------------------------------------------


def _preview_key(source: Dict[str, Any]) -> str:
    """What the cached loaded table depends on: the data source's settings."""
    material = json.dumps(
        {"config": source["config"], "connector": source["connector"]},
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(material.encode()).hexdigest()


def _preview_in(
    run_dir: Path,
    fetched: Optional[FetchResult],
    steps: List[Dict[str, Any]],
    key: str,
    facts_options: Any = None,
    llm_options: Any = None,
    recipe_id: str = "",
) -> Dict[str, Any]:
    cache = run_dir / "source.parquet"
    stamp = run_dir / "source.key"
    with session(run_dir, timeout_s=PREVIEW_TIMEOUT_S) as s:
        if fetched is None:
            source_rows = load_cached(s, cache)
        else:
            source_rows = load(s, fetched).rows
            write_parquet(s, TABLE, cache)
            stamp.write_text(key)
        error: Optional[Dict[str, Any]] = None
        try:
            applied = apply_steps(s, steps, source=TABLE, target=RESULT)
        except StepError as exc:
            error = {"step": exc.index, "message": exc.detail}
            applied = apply_steps(s, steps[: exc.index], source=TABLE, target=RESULT)
        except EngineError as exc:
            error = {"step": None, "message": str(exc)}
            applied = apply_steps(s, [], source=TABLE, target=RESULT)
        return {
            "source_rows": source_rows,
            "rows": applied.rows,
            "schema": [{"name": n, "type": t} for n, t in applied.schema],
            "step_rows": applied.step_rows,
            "source_schema": [
                {"name": n, "type": t} for n, t in table_schema(s, TABLE)
            ],
            "step_schemas": [
                [{"name": n, "type": t} for n, t in schema]
                for schema in applied.step_schemas
            ],
            "sample": preview_rows(s, RESULT, PREVIEW_ROWS),
            "pairs": _preview_pairs(facts_options, preview_rows(s, RESULT, 20), error),
            "llm": _preview_llm(s, llm_options, recipe_id, error),
            "error": error,
        }


def _preview_pairs(facts_options: Any, rows: List[Dict[str, Any]], error: Any):
    """The pairs of the first 20 rows, for a facts recipe (None otherwise)."""
    if facts_options is None or error:
        return None
    from server.generators.facts import TemplateError, check_columns, facts

    try:
        if rows:
            check_columns(facts_options, rows[0].keys())
        return facts(facts_options, rows, source="", recipe_id="preview", created_at="")
    except TemplateError as exc:
        return [{"error": str(exc)}]


def _preview_llm(s: Any, options: Any, recipe_id: str, error: Any):
    """A model recipe: its groups and the tokens a full run would spend."""
    if options is None or error:
        return None
    from server.engine.profile import iter_rows
    from server.generators.facts import TemplateError
    from server.generators.qa_llm import check_columns, estimate_tokens, sources_of_rows
    from server.engine.steps import table_schema

    try:
        check_columns(options, [n for n, _ in table_schema(s, RESULT)])
    except TemplateError as exc:
        return {"error": str(exc)}
    sources = sources_of_rows(options, iter_rows(s, RESULT), recipe_id)
    first = next(iter(sources.values()), None)
    return {
        "groups": len(sources),
        "estimated_tokens": estimate_tokens(options, sources),
        "limit": config.quota_tokens_per_run,
        "first_source": first.text[:2000] if first else "",
    }


def _llm_options(recipe: Dict[str, Any]) -> Any:
    if recipe.get("output_kind") != OutputKind.QA:
        return None
    if (recipe.get("output_options") or {}).get("generator") != "llm":
        return None
    from pydantic import ValidationError

    from server.generators.qa_llm import LlmOptions

    try:
        return LlmOptions.model_validate(recipe.get("output_options") or {})
    except ValidationError:
        return None


def _facts_options(recipe: Dict[str, Any]) -> Any:
    if recipe.get("output_kind") != OutputKind.QA:
        return None
    from pydantic import ValidationError

    from server.generators.facts import FactsOptions

    try:
        return FactsOptions.model_validate(recipe.get("output_options") or {})
    except ValidationError:
        return None


async def preview_recipe(
    creds: Credentials,
    recipe_id: str,
    steps: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """The recipe's first rows after ``steps`` (its own when None)."""
    owner_id = creds.user_id
    loaded = await asyncio.to_thread(_load_rows, owner_id, recipe_id)
    recipe, source = loaded.recipe, loaded.source
    from server.services.draft_store import get_store

    store = get_store()
    folder = f"preview-{recipe['id']}"
    run_dir = store.run_dir(owner_id, folder)
    key = _preview_key(source)
    stamp = run_dir / "source.key"
    cached = (
        (run_dir / "source.parquet").is_file()
        and stamp.is_file()
        and stamp.read_text() == key
    )
    fetched = None
    if not cached:
        store.delete(owner_id, folder)
        try:
            fetched = await _fetch(
                owner_id, source, creds, store.raw_dir(owner_id, folder)
            )
        except ConnectorError as exc:
            raise RecipeRunError(str(exc)) from None
    missing: Optional[str] = None
    if _llm_options(recipe) is not None:
        from server.jobs.qa_build import JobError, model_for

        try:
            model_for(creds, recipe.get("model_ref"), None)
        except JobError as exc:
            missing = str(exc)
    try:
        preview = await asyncio.to_thread(
            _preview_in,
            run_dir,
            fetched,
            recipe["steps"] if steps is None else steps,
            key,
            _facts_options(recipe),
            _llm_options(recipe),
            recipe["id"],
        )
    except EngineError as exc:
        raise RecipeRunError(str(exc)) from None
    if preview.get("llm") is not None and missing:
        preview["llm"]["missing"] = missing
    return preview


# --- scheduled refreshes (#314) ---------------------------------------------------


def unchanged_reason(db, owner_id: str, recipe_id: str) -> Optional[str]:
    """Why a scheduled run of the recipe would bring nothing new: its data
    source still has the fingerprint of the last run, and the recipe was not
    edited since. None when it may have changed (or can't be told cheaply)."""
    from sqlalchemy import select

    from server.models.data_source import Recipe
    from server.models.job_run import JobRun

    recipe = db.get(Recipe, recipe_id)
    if recipe is None or recipe.owner_id != owner_id:
        return None
    source = db.get(DataSource, recipe.data_source_id)
    if source is None or not source.last_fingerprint:
        return None
    last = None
    for run in db.scalars(
        select(JobRun)
        .where(
            JobRun.owner_id == owner_id,
            JobRun.job_id == "recipe",
            JobRun.status.in_(("succeeded", "published", "rejected")),
        )
        .order_by(JobRun.started_at.desc())
    ):
        if (run.options or {}).get("recipe_id") == recipe_id:
            last = run
            break
    if last is None or last.started_at is None:
        return None
    started = (
        last.started_at
        if last.started_at.tzinfo
        else last.started_at.replace(tzinfo=timezone.utc)
    )
    edited = recipe.updated_at
    if edited is not None:
        edited = edited if edited.tzinfo else edited.replace(tzinfo=timezone.utc)
        if edited > started:
            return None  # the recipe changed since: run it
    connector = get_connector(source.connector)
    check = getattr(connector, "unchanged", None)
    if check is None:
        return None
    try:
        same = asyncio.run(
            check(
                owner_id, source.id, dict(source.config or {}), source.last_fingerprint
            )
        )
    except Exception as exc:  # noqa: BLE001 — a failed check runs the recipe
        logger.info("fingerprint check of %s failed: %s", source.id, exc)
        return None
    if not same:
        return None
    when = source.last_fetched_at or started
    return f"unchanged since {when:%Y-%m-%d}"


async def publish_scheduled(
    creds: Credentials, run_id: str, draft: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    """A scheduled run that may publish: publish when no blocking rule fails
    (and the licence allows the visibility); None when the draft must wait
    for a review."""
    from server.review.tabular_quality import blocking_rules
    from server.services.tabular_publish import (
        PublishRefused,
        publish_draft,
        public_allowed,
    )

    if blocking_rules(draft.get("quality_report")):
        return None
    if draft.get("visibility") == "public" and public_allowed(draft):
        return None
    provenance = draft.get("provenance") or {}
    message = "refresh: {} {}".format(
        provenance.get("producer") or provenance.get("connector") or "data source",
        str(provenance.get("last_modified") or provenance.get("fetched_at") or "")[:10],
    ).strip()

    def go():
        from server.models.data_source import Review
        from server.services import audit
        from server.models.user import User

        with get_scoped_db() as db:
            try:
                published = publish_draft(
                    db, creds, creds.user_id, run_id, draft, message=message
                )
            except PublishRefused:
                return None
            db.add(
                Review(
                    owner_id=creds.user_id,
                    run_id=run_id,
                    reviewer_id=None,
                    decision="approved",
                    comment="Scheduled refresh: published as every blocking rule passed",
                )
            )
            audit.record(
                db,
                "recipe.review.approved",
                actor=db.get(User, creds.user_id),
                detail={
                    "run_id": run_id,
                    "scheduled": True,
                    "commit": published["commit"],
                },
                commit=False,
            )
            db.commit()
            return published

    return await asyncio.to_thread(go)
