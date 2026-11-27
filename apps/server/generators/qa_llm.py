"""Q&A pairs from rows with the user's model (#316), through the shared
incremental build of jobs/qa_build.py.

Rows become text **sources**: each row rendered by a template (the facts
syntax, generators/facts.py) or as ``column: value`` lines, grouped by a key
column or by ``group_size`` rows, bounded in characters. A source's content
hash drives the incrementality: an unchanged group keeps its pairs with no
model call, a changed one is re-checked and regenerated; the grader holds
low-graded pairs for review, the near-duplicate and embedding checks screen
new ones — all of it qa_build's, unchanged.
"""

import hashlib
from typing import Any, Dict, Iterable, List, Literal, Optional, Tuple

from pydantic import BaseModel, Field, field_validator

from server.generators.facts import TemplateError, _parse, placeholders, render
from server.jobs.qa_build import (
    ANSWER_STYLE,
    JSON_FORMAT_INSTRUCTION,
    CompletionRequest,
    JobError,
    QADataset,
    QAPair,
    Run,
    Source,
    SourcePlan,
    Task,
    TaskGroup,
    build,
    generate_pairs,
    guidance,
    token_budget,
)

SOURCE = "recipe"
CATEGORY = "rows"
MAX_GROUP_CHARS = 6000
_LANGUAGES = {"fr": "French", "en": "English"}
# A rough count for the cost guard: ~4 characters a token, prompts included.
CHARS_PER_TOKEN = 4
PROMPT_TOKENS = 400


class LlmOptions(BaseModel):
    generator: Literal["llm"] = "llm"
    # How a row reads: a template over the columns, else "column: value" lines.
    row_template: Optional[str] = Field(None, max_length=2000)
    # Rows of one value of this column form a source; else ``group_size`` rows.
    group_by: Optional[str] = Field(None, max_length=200)
    group_size: int = Field(20, ge=1, le=500)
    pairs_per_group: int = Field(5, ge=1, le=20)
    language: Literal["fr", "en"] = "fr"
    # What the data is about, for the prompt ("les communes du Finistère").
    subject: str = Field("the rows of a table", max_length=200)
    max_groups: int = Field(500, ge=1, le=5000)

    @field_validator("row_template")
    @classmethod
    def _parses(cls, text: Optional[str]) -> Optional[str]:
        if text is None:
            return None
        try:
            _parse(text)
        except TemplateError as exc:
            raise ValueError(str(exc)) from None
        return text


def row_text(options: LlmOptions, row: Dict[str, Any]) -> str:
    if options.row_template:
        return render(options.row_template, row)
    return "\n".join(f"{k}: {v}" for k, v in row.items() if v not in (None, ""))


def check_columns(options: LlmOptions, columns: Iterable[str]) -> None:
    known = set(columns)
    names = placeholders(options.row_template or "")
    if options.group_by:
        names.append(options.group_by)
    missing = [n for n in names if n not in known]
    if missing:
        raise TemplateError(f"no column '{missing[0]}'")


def sources_of_rows(
    options: LlmOptions, rows: Iterable[Dict[str, Any]], recipe_id: str
) -> Dict[str, Source]:
    """The text sources of ``rows``, by key, in order (``max_groups`` at most)."""
    groups: Dict[str, List[str]] = {}
    for n, row in enumerate(rows):
        if options.group_by:
            key = f"{recipe_id}::{options.group_by}={row.get(options.group_by)}"
        else:
            key = f"{recipe_id}::rows-{n // options.group_size}"
        if key not in groups:
            if len(groups) >= options.max_groups:
                break
            groups[key] = []
        groups[key].append(row_text(options, row))
    out: Dict[str, Source] = {}
    for key, texts in groups.items():
        text = "\n\n".join(texts)
        if len(text) > MAX_GROUP_CHARS:
            text = text[: MAX_GROUP_CHARS - 1] + "…"
        out[key] = Source(key, text)
    return out


def estimate_tokens(options: LlmOptions, sources: Dict[str, Source]) -> int:
    """The tokens a full run spends at most (every group changed)."""
    total = 0
    for source in sources.values():
        total += PROMPT_TOKENS + len(source.text) // CHARS_PER_TOKEN
        total += token_budget(options.pairs_per_group)
    return total


def own_recipe_pair(recipe_id: str):
    """The row as a pair this recipe generated (else a foreign row)."""

    def own(row: Dict[str, Any]) -> Optional[QAPair]:
        pair = QAPair.from_record(row)
        if pair is None or pair.source != SOURCE:
            return None
        if not all(k.startswith(f"{recipe_id}::") for k in pair.sources or [""]):
            return None
        return pair

    return own


async def _group_pairs(
    run: Run, options: LlmOptions, source: Source, avoid: List[str], focus: List[str]
) -> List[QAPair]:
    language = _LANGUAGES[options.language]
    pairs = await generate_pairs(
        run.complete,
        CompletionRequest(
            system=(
                f"You generate question/answer pairs in {language} for a "
                f"fine-tuning dataset, from rows of a table about {options.subject}. "
                f"{JSON_FORMAT_INSTRUCTION} Answers must stay factual and rely only "
                f"on the given rows. {ANSWER_STYLE} Ask what someone would ask "
                "about these rows: values, comparisons between rows, what they "
                "say together — never invent a figure, a date or a name the rows "
                "don't give."
            ),
            user=(
                f"Generate {options.pairs_per_group} distinct question/answer "
                f"pairs from these rows:\n\n{source.text}" + guidance(avoid, focus)
            ),
            max_tokens=token_budget(options.pairs_per_group),
        ),
        source.key,
        CATEGORY,
        run.model,
    )
    for pair in pairs:
        pair.source = SOURCE
        pair.repo = None
        pair.sources = [source.key]
        pair.id = None  # qa_build gives it its content id
    return pairs


async def build_rows_dataset(
    run: Run,
    options: LlmOptions,
    sources: Dict[str, Source],
    *,
    on_progress=None,
) -> Tuple[QADataset, int]:
    """The next version of the recipe's Q&A dataset; and the model calls made."""
    if not sources:
        raise JobError("The table has no row to generate from")
    calls = {"n": 0}

    def groups() -> List[TaskGroup]:
        out: List[TaskGroup] = []
        for source in sources.values():
            if not source.changed:
                continue

            async def go(avoid: List[str], focus: List[str], source: Source = source):
                calls["n"] += 1
                return await _group_pairs(run, options, source, avoid, focus)

            out.append(
                TaskGroup(source.key, [Task([source.key], source.key, source.text, go)])
            )
        return out

    result = await build(
        SourcePlan(
            sources=sources,
            facts=[],
            groups=groups,
            sources_of=lambda pair: pair.sources if pair.source == SOURCE else None,
        ),
        run.previous,
        embedder=run.embedder,
        grader=run.complete,
        on_progress=on_progress,
    )
    pairs = result.existing + result.accepted
    dataset = QADataset(
        pairs,
        result.dropped,
        result.errors,
        kept=result.kept,
        new=len(result.accepted),
        semantic_duplicates=result.semantic_duplicates,
        review=result.review,
        manifest={**result.manifest(run.embedder), "changed": result.changed},
        new_ids=[p.id for p in result.accepted if p.id],
    )
    return dataset, calls["n"]


def digest(sources: Dict[str, Source]) -> str:
    return hashlib.sha256(
        "".join(sorted(s.text for s in sources.values())).encode()
    ).hexdigest()


def dataset_card(
    dataset: QADataset, title: str, provenance: Dict[str, Any], foreign: int = 0
) -> str:
    """The card of a recipe's LLM Q&A dataset (an app card)."""
    from server.hub.licences import resolve
    from server.jobs.qa_build import foreign_note, size_category
    from server.services.hub_repo import APP_CARD_TAG

    licence = resolve(provenance.get("licence"))
    models = sorted({p.model for p in dataset.pairs if p.model})
    lines = [
        "---",
        f"license: {licence.hf}",
        "tags:",
        f"- {APP_CARD_TAG}",
        "- open-data",
        "- synthetic",
        "task_categories:",
        "- question-answering",
        "size_categories:",
        f"- {size_category(len(dataset.pairs) + foreign)}",
        "---",
        "",
        f"# {title}",
        "",
        f"{len(dataset.pairs)} question/answer pairs generated by "
        f"{', '.join(f'`{m}`' for m in models) or 'an LLM'} from the rows of a "
        "table, reviewed before publication.",
        "",
        "## Source",
        "",
        f"- Data: {provenance.get('url') or provenance.get('resource_id') or '—'}",
        f"- Producer: {provenance.get('producer') or '—'}",
        f"- Licence: {licence.name}",
        f"- Retrieved: {str(provenance.get('fetched_at') or '')[:19]}",
        "",
        "## Composition",
        "",
        f"This version: {dataset.kept} pair(s) carried over from unchanged rows, "
        f"{dataset.new} new; {dataset.dropped} dropped before export.",
        foreign_note(foreign).strip(),
        "",
    ]
    return "\n".join(line for line in lines if line is not None)
