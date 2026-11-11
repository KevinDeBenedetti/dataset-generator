"""Q&A pairs from one of your resumes on Reactive Resume — the ``resume-qa`` job.

The resume is read as the Resume page shows it (services/reactive_resume.py,
``resume_view``): basics, summary and the visible sections, hidden items left
out. Two kinds of pairs:

* **facts**, deterministic (category ``profile``): who the person is, where,
  the current position, their experience, education, skills, languages,
  certifications and projects as the resume lists them, and how to get in
  touch — email, website and links, never the phone number. Exact answers, no
  model, rebuilt every run, in the resume's language (or the one asked for).
* **generated** pairs: one model call per batch of a section's items, in that
  language, checked like the GitHub Q&A's (jobs/qa_dataset.py): a rephrasing
  of an existing question is dropped, an answer far from its item is held out
  for review.

Incremental: every item is a source hashed into the published manifest, so an
unchanged item keeps its pairs with no model call and an untouched resume
costs nothing. The dataset has the GitHub Q&A's columns — ``source`` is
``"resume"``, ``category`` the section's key, ``sources`` the items a pair
came from — so the two join as they are.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

from server.core.cpu import cpu_bound
from server.jobs.github_snapshot import gather_limited
from server.jobs.qa_dataset import (
    ANSWER_STYLE,
    JSON_FORMAT_INSTRUCTION,
    CompletionFn,
    CompletionRequest,
    Draft,
    JobError,
    PreviousState,
    ProgressFn,
    QADataset,
    QAPair,
    _guidance,
    _model_for,
    _size_category,
    _Source,
    _token_budget,
    content_hash,
    dedupe_key,
    grade_pairs,
    generate_pairs,
    guidance_for,
    load_previous_state,
    provider_completion,
    publish_qa_dataset,
    question_index,
    recheck_pairs,
    removed_pairs,
    sanitize_pairs,
    screen_pairs,
)
from server.services import reactive_resume as rr
from server.services.credentials import HF_TOKEN, Credentials
from server.services.semantic import Embedder, SemanticIndex, get_embedder

logger = logging.getLogger(__name__)

RESUME_JOB_ID = "resume-qa"
SOURCE = "resume"
# The deterministic pairs' category: rebuilt every run, never carried over.
FACTS_CATEGORY = "profile"
LANGUAGES = ("auto", "en", "fr")

PAIRS_PER_ITEM = 2
MAX_PAIRS_PER_CALL = 10
# A section's items go to the model a few at a time, this much text at most.
BATCH_CHAR_BUDGET = 6000
SECTION_CONCURRENCY = 2
MAX_LIST_ITEMS = 12

# A FACTS_CATEGORY pair's question is a template of its language, filled with
# the person's name; the answer with what the resume says.
_FACTS: Dict[str, Dict[str, Tuple[str, str]]] = {
    "en": {
        "who": ("Who is {who}?", "{who} is {headline}."),
        "location": ("Where is {who} based?", "{who} is based in {location}."),
        "current": (
            "What is {who}'s current position?",
            "{who} is {title} at {subtitle} ({period}).",
        ),
        "latest": (
            "What was {who}'s most recent position?",
            "{who} was {title} at {subtitle} ({period}).",
        ),
        "experience": ("Where has {who} worked?", "{who} has worked as {list}."),
        "education": ("What did {who} study?", "{who} studied {list}."),
        "skills": ("What are {who}'s main skills?", "{who}'s main skills are {list}."),
        "languages": ("Which languages does {who} speak?", "{who} speaks {list}."),
        "certifications": (
            "Which certifications does {who} hold?",
            "{who} holds {list}.",
        ),
        "projects": ("Which projects has {who} worked on?", "{who} worked on {list}."),
        "contact": ("How can I contact {who}?", "You can reach {who} {list}."),
    },
    "fr": {
        "who": ("Qui est {who} ?", "{who} est {headline}."),
        "location": ("Où se trouve {who} ?", "{who} se trouve à {location}."),
        "current": (
            "Quel est le poste actuel de {who} ?",
            "{who} est {title} chez {subtitle} ({period}).",
        ),
        "latest": (
            "Quel est le dernier poste occupé par {who} ?",
            "{who} était {title} chez {subtitle} ({period}).",
        ),
        "experience": (
            "Quelles sont les expériences professionnelles de {who} ?",
            "{who} a travaillé comme {list}.",
        ),
        "education": ("Quelle est la formation de {who} ?", "{who} a étudié {list}."),
        "skills": (
            "Quelles sont les principales compétences de {who} ?",
            "Les principales compétences de {who} sont {list}.",
        ),
        "languages": ("Quelles langues parle {who} ?", "{who} parle {list}."),
        "certifications": (
            "Quelles certifications détient {who} ?",
            "{who} détient {list}.",
        ),
        "projects": (
            "Quels sont les projets de {who} ?",
            "{who} a travaillé sur {list}.",
        ),
        "contact": ("Comment contacter {who} ?", "Vous pouvez joindre {who} {list}."),
    },
}
_AT = {"en": "at", "fr": "chez"}
_AND = {"en": "and", "fr": "et"}
_CONTACT = {
    "en": ("by email at {email}", "through {website}", "on {label} ({url})"),
    "fr": ("par e-mail à {email}", "via {website}", "sur {label} ({url})"),
}
_LANGUAGE_NAMES = {"en": "English", "fr": "French"}
# An ongoing position, as Reactive Resume writes the period.
_ONGOING = ("present", "today", "now", "aujourd'hui", "actuel", "en cours", "ongoing")
# Sections whose items are qualified by a level or keywords, not by dates.
_LEVELLED = ("skills", "languages", "interests")

# Language detection: the common words of each, counted in the resume's text.
_FR_MARKERS = (
    " le ", " la ", " les ", " des ", " et ", " une ", " pour ", " avec ",
    " dans ", " sur ", " du ", " au ", " aux ", " chez ", " est ", " d'", " l'",
)  # fmt: skip
_EN_MARKERS = (
    " the ", " and ", " with ", " for ", " of ", " to ", " in ", " on ", " at ",
    " is ", " a ", " an ", " as ",
)  # fmt: skip


def detect_language(text: str) -> str:
    """``"fr"`` or ``"en"``: the one whose common words the text uses more
    (French gets its accents counted too). English on a tie or no text."""
    sample = f" {' '.join(text.lower().split())} "
    fr = sum(sample.count(m) for m in _FR_MARKERS) + sum(
        sample.count(c) for c in "éèêàçù"
    )
    en = sum(sample.count(m) for m in _EN_MARKERS)
    return "fr" if fr > en else "en"


# --- the resume as sources ------------------------------------------------------


@dataclass(frozen=True)
class Item:
    """One visible item of a section, as ``resume_view`` gives it."""

    section_key: str
    section_title: str
    id: str
    title: str
    subtitle: str = ""
    period: str = ""
    text: str = ""
    keywords: Tuple[str, ...] = ()
    url: str = ""

    @property
    def key(self) -> str:
        """The source key: ``<section>::<item id>``."""
        return f"{self.section_key}::{self.id}"

    @property
    def category(self) -> str:
        """``experience``, ``education``…; ``custom`` for a custom section."""
        return self.section_key.split(":", 1)[0]

    def context(self) -> str:
        """What the model and the hash see: the item as text."""
        head = self.title
        if self.subtitle:
            head += f" — {self.subtitle}"
        if self.period:
            head += f" ({self.period})"
        lines = [head]
        if self.text:
            lines.append(self.text)
        if self.keywords:
            lines.append("Keywords: " + ", ".join(self.keywords))
        if self.url:
            lines.append(self.url)
        return "\n".join(lines)


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def items_of(view: Dict[str, Any]) -> List[Item]:
    """The resume's items, section by section, in the page's order."""
    items: List[Item] = []
    for section in view.get("sections") or []:
        key, title = _text(section.get("key")), _text(section.get("title"))
        for raw in section.get("items") or []:
            if not _text(raw.get("id")) or not _text(raw.get("title")):
                continue
            items.append(
                Item(
                    section_key=key,
                    section_title=title or key,
                    id=_text(raw.get("id")),
                    title=_text(raw.get("title")),
                    subtitle=_text(raw.get("subtitle")),
                    period=_text(raw.get("period")),
                    text=_text(raw.get("text")),
                    keywords=tuple(k for k in (raw.get("keywords") or []) if _text(k)),
                    url=_text(raw.get("url")),
                )
            )
    return items


def basics_text(view: Dict[str, Any]) -> str:
    """The person as the resume introduces them — the ``basics`` source."""
    basics = view.get("basics") or {}
    lines = [
        " — ".join(
            v for v in (_text(basics.get("name")), _text(basics.get("headline"))) if v
        )
    ]
    if _text(basics.get("location")):
        lines.append(_text(basics.get("location")))
    lines += [_text(f) for f in basics.get("facts") or [] if _text(f)]
    lines += [
        f"{_text(link.get('label'))}: {_text(link.get('url'))}"
        for link in basics.get("links") or []
        if _text(link.get("url"))
    ]
    return "\n".join(line for line in lines if line)


def resume_sources(view: Dict[str, Any], items: Sequence[Item]) -> Dict[str, _Source]:
    """Every hashed source: the basics, the summary and each item."""
    sources: Dict[str, _Source] = {}
    text = basics_text(view)
    if text:
        sources["basics"] = _Source("basics", text)
    summary = _text(view.get("summary"))
    if summary:
        sources["summary"] = _Source("summary", summary)
    for item in items:
        sources[item.key] = _Source(item.key, item.context())
    return sources


# --- facts ---------------------------------------------------------------------


def _join(parts: Sequence[str], language: str) -> str:
    """``a``, ``a and b``, ``a, b and c`` — in the language's words."""
    parts = [p for p in parts if p]
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    return f"{', '.join(parts[:-1])} {_AND[language]} {parts[-1]}"


def _label(item: Item, language: str) -> str:
    """An item in a list: what it is, who with or at what level, and when."""
    if item.category in _LEVELLED:
        detail = ", ".join(item.keywords) or item.subtitle
        return f"{item.title} ({detail})" if detail else item.title
    label = item.title
    if item.subtitle:
        joiner = _AT[language] if item.category == "experience" else "—"
        label += f" {joiner} {item.subtitle}"
    if item.period:
        label += f" ({item.period})"
    return label


def _ongoing(period: str) -> bool:
    lowered = period.lower()
    return any(marker in lowered for marker in _ONGOING)


def profile_facts(
    view: Dict[str, Any], items: Sequence[Item], language: str
) -> List[QAPair]:
    """Deterministic pairs about the person, from the resume's fields alone:
    exact answers, no model — what a visitor asks first."""
    basics = view.get("basics") or {}
    who = _text(basics.get("name")) or _text(view.get("name"))
    if not who:
        return []
    templates = _FACTS[language]

    def pair(key: str, **values: str) -> QAPair:
        question, answer = templates[key]
        return QAPair(
            question=question.format(who=who, **values),
            answer=answer.format(who=who, **values),
            category=FACTS_CATEGORY,
            source=SOURCE,
            confidence=1.0,
        )

    pairs: List[QAPair] = []
    if _text(basics.get("headline")):
        pairs.append(pair("who", headline=_text(basics.get("headline")).rstrip(".")))
    if _text(basics.get("location")):
        pairs.append(pair("location", location=_text(basics.get("location"))))

    by_category: Dict[str, List[Item]] = {}
    for item in items:
        by_category.setdefault(item.category, []).append(item)
    latest = next(iter(by_category.get("experience", [])), None)
    if latest is not None and latest.subtitle:
        pairs.append(
            pair(
                "current" if _ongoing(latest.period) else "latest",
                title=latest.title,
                subtitle=latest.subtitle,
                period=latest.period or "—",
            )
        )
    for key in (
        "experience",
        "education",
        "skills",
        "languages",
        "certifications",
        "projects",
    ):
        listed = by_category.get(key, [])[:MAX_LIST_ITEMS]
        if listed:
            pairs.append(
                pair(key, list=_join([_label(i, language) for i in listed], language))
            )

    ways: List[str] = []
    email, website = _text(basics.get("email")), _text(basics.get("website"))
    by_email, through, on = _CONTACT[language]
    if email:
        ways.append(by_email.format(email=email))
    if website:
        ways.append(through.format(website=website))
    for link in basics.get("links") or []:
        if _text(link.get("url")):
            ways.append(
                on.format(
                    label=_text(link.get("label")) or "the web",
                    url=_text(link.get("url")),
                )
            )
    if ways:
        pairs.append(pair("contact", list=_join(ways, language)))
    return pairs


# --- generation ------------------------------------------------------------------


@dataclass
class _Batch:
    """One model call: a few changed items of one section."""

    section_key: str
    section_title: str
    items: List[Item]
    avoid: List[str] = field(default_factory=list)
    focus: List[str] = field(default_factory=list)
    failed: bool = False

    @property
    def keys(self) -> List[str]:
        return [i.key for i in self.items]

    def context(self) -> str:
        return f"## {self.section_title}\n\n" + "\n\n".join(
            i.context() for i in self.items
        )


def _batches(items: Sequence[Item]) -> List[_Batch]:
    """Changed items of each section, a budget of text per call."""
    batches: List[_Batch] = []
    for item in items:
        current = batches[-1] if batches else None
        if (
            current is None
            or current.section_key != item.section_key
            or len(current.context()) + len(item.context()) > BATCH_CHAR_BUDGET
        ):
            current = _Batch(item.section_key, item.section_title, [])
            batches.append(current)
        current.items.append(item)
    return batches


def _name_the_person(who: str) -> str:
    return (
        f'\n\nEvery question must name "{who}" explicitly (e.g. "What did {who} '
        f'do at …?") — never "the candidate", "this person" or a pronoun alone.'
    )


async def batch_pairs(
    complete: CompletionFn, model: str, who: str, language: str, batch: _Batch
) -> List[QAPair]:
    """The pairs of one batch of items, each pair recording the batch's sources."""
    want = min(MAX_PAIRS_PER_CALL, len(batch.items) * PAIRS_PER_ITEM)
    pairs = await generate_pairs(
        complete,
        CompletionRequest(
            system=(
                f"You generate question/answer pairs in {_LANGUAGE_NAMES[language]} "
                f"for a fine-tuning dataset, from the resume of {who}. "
                f"{JSON_FORMAT_INSTRUCTION} Answers must stay factual and rely "
                f"only on the given context. {ANSWER_STYLE} Cover what a recruiter "
                f"or a visitor of {who}'s portfolio would ask: responsibilities, "
                "achievements, technologies, dates and outcomes — never invent "
                "a figure, a date or a name the context doesn't give."
            ),
            user=(
                f"Generate {want} distinct question/answer pairs from this part "
                f"of {who}'s resume:\n\n{batch.context()}"
                + _name_the_person(who)
                + _guidance(batch.avoid, batch.focus)
            ),
            max_tokens=_token_budget(want),
        ),
        batch.section_title,
        batch.items[0].category,
        model,
    )
    for pair in pairs:
        pair.source = SOURCE
        pair.repo = None
        pair.sources = batch.keys
    return pairs


# Questions the resume doesn't answer, each answered by saying so: what tests
# (and teaches) a portfolio chat to decline instead of inventing.
UNANSWERABLE_CATEGORY = "unanswerable"
UNANSWERABLE_KEY = "unanswerable"  # its source: the whole resume
UNANSWERABLE_PAIRS = 6
UNANSWERABLE_CONTEXT_CHARS = 12000
MAX_AVOID = 30  # existing questions listed as "don't ask again"

UNANSWERABLE_RUBRIC = (
    "Each question below is meant to be one the context does NOT answer, with "
    "an answer that says so, for a dataset that tests a portfolio chatbot. "
    "Grade each pair from 0 to 1: 1 when the context does not answer the "
    "question and the answer says so honestly, adds only what the context does "
    "say on the topic, and invents nothing; 0 when the context answers the "
    "question (so it isn't unanswerable) or the answer invents a fact. Respond "
    "ONLY with a JSON array covering every pair, "
    '[{"id":"...","score":0.8,"reason":"a few words"}].'
)


async def unanswerable_pairs(
    complete: CompletionFn,
    model: str,
    who: str,
    language: str,
    resume: str,
    count: int,
    *,
    contact: str = "",
    avoid: Sequence[str] = (),
) -> List[QAPair]:
    """``count`` questions about the person that the resume doesn't answer,
    each answered as the chat should: by saying so, with what the resume does
    say on the topic and how to ask the person."""
    reach = f" ({contact})" if contact else ""
    pairs = await generate_pairs(
        complete,
        CompletionRequest(
            system=(
                f"You write test questions in {_LANGUAGE_NAMES[language]} for the "
                f"portfolio chatbot of {who}: questions a recruiter or visitor "
                f"might ask that {who}'s resume does NOT answer — a degree, a "
                "skill, a job, a certification, a place, a date, an availability "
                "it doesn't mention. Never ask what the resume answers. For each, "
                "write the answer the chatbot should give: say the resume doesn't "
                "mention it, add only what the resume does say on the topic if "
                f"anything, and suggest asking {who} directly{reach}. "
                f"{JSON_FORMAT_INSTRUCTION}"
            ),
            user=(
                f"Write {count} such pairs from this resume:\n\n"
                f"{resume[:UNANSWERABLE_CONTEXT_CHARS]}"
                + _name_the_person(who)
                + _guidance(avoid, ())
            ),
            max_tokens=_token_budget(count),
        ),
        "unanswerable",
        UNANSWERABLE_CATEGORY,
        model,
    )
    for pair in pairs:
        pair.source, pair.repo, pair.sources = SOURCE, None, [UNANSWERABLE_KEY]
    return pairs


async def build_resume_dataset(
    view: Dict[str, Any],
    complete: CompletionFn,
    model: str,
    *,
    previous: Optional[PreviousState] = None,
    embedder: Optional[Embedder] = None,
    language: str = "auto",
    on_progress: Optional[ProgressFn] = None,
    grader: Optional[CompletionFn] = None,
    unanswerable: int = 0,
) -> QADataset:
    """The next version of the resume's dataset from ``previous`` (empty: a
    full run), like :func:`server.jobs.qa_dataset.build_qa_dataset`:

    1. every source (the basics, the summary, each item) is hashed; an
       unchanged item keeps its pairs with no model call, a removed item's
       pairs are dropped;
    2. a changed item's old pairs are re-checked against its new text (kept
       when still grounded, else sent to review), then its section is
       regenerated with the nearest existing questions as "don't ask again"
       and its uncovered parts as "prioritize";
    3. new pairs are deduplicated against every kept one and held out for
       review when their answer is far from the item.

    The facts are rebuilt every run. Without an ``embedder`` the embedding
    parts are skipped. ``manifest["changed"]`` says how many sources moved.
    """
    previous = previous or PreviousState()
    items = items_of(view)
    sources = resume_sources(view, items)
    if not sources:
        raise JobError("The resume has nothing visible to generate from")
    if language == "auto":
        language = detect_language("\n".join(s.text for s in sources.values()))
    basics = view.get("basics") or {}
    who = _text(basics.get("name")) or _text(view.get("name")) or "the person"
    if unanswerable:
        whole = "\n\n".join(src.text for src in sources.values())
        sources[UNANSWERABLE_KEY] = _Source(UNANSWERABLE_KEY, whole)
    for src in sources.values():
        src.changed = previous.sources.get(src.key) != content_hash(src.text)

    kept: List[QAPair] = []
    recheck: List[QAPair] = []
    previous_unanswerable: List[QAPair] = []
    for pair in previous.pairs:
        if pair.category == FACTS_CATEGORY:
            continue
        if pair.category == UNANSWERABLE_CATEGORY:
            if unanswerable:
                previous_unanswerable.append(pair)
            continue
        keys = [k for k in pair.sources if k in sources]
        if not keys:
            continue  # its item is gone from the resume
        pair.sources = keys
        (recheck if any(sources[k].changed for k in keys) else kept).append(pair)

    facts = profile_facts(view, items, language)
    review: List[QAPair] = []
    errors: List[str] = []
    batches = _batches([i for i in items if sources[i.key].changed])

    def prepare() -> SemanticIndex:
        recheck_pairs(embedder, recheck, sources, kept, review)
        if embedder is None or not batches:
            return SemanticIndex()  # nothing to generate: no embedding spent
        index = question_index(embedder, facts + kept)
        for batch in batches:
            batch.avoid, batch.focus = guidance_for(batch.context(), index, embedder)
        return index

    index = await cpu_bound(prepare)  # embedding batches: core/cpu.py
    changed = sum(s.changed for s in sources.values())
    logger.info(
        "%s: %d source(s) changed of %d; %d pair(s) carried over, %d re-checked "
        "(%d to review), %d model call(s) to make",
        who,
        changed,
        len(sources),
        len(kept),
        len(recheck),
        len(review),
        len(batches),
    )

    done = 0
    if on_progress is not None:
        on_progress(0, len(batches), "")

    async def for_batch(batch: _Batch) -> List[QAPair]:
        nonlocal done
        pairs: List[QAPair] = []
        try:
            pairs = await batch_pairs(complete, model, who, language, batch)
        except JobError as exc:
            batch.failed = True
            errors.append(f"{batch.section_title}: {exc}")
        done += 1
        if on_progress is not None:
            on_progress(done, len(batches), batch.section_title)
        return pairs

    generated: List[QAPair] = []
    for pairs in await gather_limited(
        SECTION_CONCURRENCY, [for_batch(b) for b in batches]
    ):
        generated += pairs

    # Existing pairs first, so a regenerated question never displaces one.
    clean, dropped = sanitize_pairs(facts + kept + generated)
    fresh_ids = {id(p) for p in generated}
    existing = [p for p in clean if id(p) not in fresh_ids]
    fresh = [p for p in clean if id(p) in fresh_ids]
    accepted, semantic_duplicates = await cpu_bound(  # embedding batches: core/cpu.py
        screen_pairs, embedder, fresh, sources, index, review, errors
    )
    if grader is not None:
        accepted = await grade_pairs(grader, accepted, sources, review, errors)

    # A failed call's sources keep their previous hash (or none), so the next
    # run retries them instead of believing them up to date.
    failed = {k for b in batches if b.failed for k in b.keys}

    kept_unanswerable: List[QAPair] = []
    new_unanswerable: List[QAPair] = []
    if unanswerable:
        whole = sources[UNANSWERABLE_KEY]
        kept_unanswerable = previous_unanswerable
        # The resume changed: a question it answers now is no longer one.
        if whole.changed and kept_unanswerable and grader is not None:
            kept_unanswerable = await grade_pairs(
                grader,
                kept_unanswerable,
                sources,
                [],  # answered now: dropped, not reviewed
                errors,
                rubric=UNANSWERABLE_RUBRIC,
                context_chars=UNANSWERABLE_CONTEXT_CHARS,
            )
        missing = unanswerable - len(kept_unanswerable)
        # Asked again only when the resume changed (a failed try leaves its
        # hash unrecorded): an untouched resume costs no model call.
        if missing > 0 and whole.changed:
            asked = facts + existing + accepted + kept_unanswerable
            try:
                fresh_unanswerable = await unanswerable_pairs(
                    complete,
                    model,
                    who,
                    language,
                    whole.text,
                    missing,
                    contact=_text(basics.get("email")) or _text(basics.get("website")),
                    avoid=[p.question for p in asked][:MAX_AVOID],
                )
            except JobError as exc:
                errors.append(f"Unanswerable questions: {exc}")
                failed.add(UNANSWERABLE_KEY)
                fresh_unanswerable = []
            seen = {dedupe_key(p.question) for p in asked}
            new_unanswerable = [
                p
                for p in sanitize_pairs(fresh_unanswerable)[0]
                if dedupe_key(p.question) not in seen
            ][:missing]
            if grader is not None and new_unanswerable:
                new_unanswerable = await grade_pairs(
                    grader,
                    new_unanswerable,
                    sources,
                    [],  # answered by the resume after all: dropped
                    errors,
                    rubric=UNANSWERABLE_RUBRIC,
                    context_chars=UNANSWERABLE_CONTEXT_CHARS,
                )
    manifest_sources: Dict[str, str] = {}
    for key, src in sources.items():
        if key not in failed:
            manifest_sources[key] = content_hash(src.text)
        elif key in previous.sources:
            manifest_sources[key] = previous.sources[key]

    pairs = existing + accepted + kept_unanswerable + new_unanswerable
    kept_count = sum(p.category != FACTS_CATEGORY for p in existing) + len(
        kept_unanswerable
    )
    # A fact is rebuilt every run, but it is new to the dataset when the
    # published version lacks it or says otherwise (its id is its question's):
    # the review lists it then, as it lists the generated pairs.
    published = {p.id: p.answer for p in previous.pairs}
    new_facts = [
        p
        for p in existing
        if p.category == FACTS_CATEGORY and published.get(p.id) != p.answer
    ]
    logger.info(
        "%d pair(s): %d kept, %d new fact(s), %d new; %d dropped, %d rephrasing(s), "
        "%d to review, %d error(s)",
        len(pairs),
        kept_count,
        len(new_facts),
        len(accepted),
        dropped,
        semantic_duplicates,
        len(review),
        len(errors),
    )
    return QADataset(
        pairs,
        dropped,
        errors,
        kept=kept_count,
        new=len(new_facts) + len(accepted) + len(new_unanswerable),
        semantic_duplicates=semantic_duplicates,
        review=review,
        manifest={
            "embedding_model": embedder.model_name if embedder else None,
            "sources": dict(sorted(manifest_sources.items())),
            "changed": changed,
            "resume": {
                "id": _text(view.get("id")),
                "name": _text(view.get("name")),
                "slug": _text(view.get("slug")),
                "updated_at": view.get("updated_at"),
                "language": language,
            },
        },
        new_ids=[p.id for p in new_facts + accepted + new_unanswerable if p.id],
    )


# --- generate, publish ------------------------------------------------------------


def unchanged(draft: Draft) -> bool:
    """Whether the run found nothing to do: no source moved since the
    published version, so nothing new, removed or to review."""
    dataset = draft.dataset
    return (
        not draft.full_refresh
        and dataset.manifest.get("changed") == 0
        and not dataset.new
        and not dataset.removed
        and not dataset.review
    )


async def generate(
    creds: Credentials,
    resume_id: str,
    target_repo: str,
    *,
    language: str = "auto",
    full_refresh: bool = False,
    model_ref: Optional[str] = None,
    complete: Optional[CompletionFn] = None,
    on_progress: Optional[ProgressFn] = None,
) -> Draft:
    """The next version of the resume's Q&A dataset, without publishing it.

    Like the GitHub Q&A's :func:`server.jobs.qa_dataset.generate`: the Hugging
    Face token is checked before any model usage is spent, the run is
    incremental against ``target_repo`` (``full_refresh`` ignores it), and
    ``model_ref`` picks the model (default: your LLM). The resume is read with
    the server's Reactive Resume key.
    """
    if language not in LANGUAGES:
        raise JobError(f"Unknown language '{language}': one of {', '.join(LANGUAGES)}")
    model_ref, model = _model_for(creds, model_ref, complete)
    if not creds.has(HF_TOKEN):
        raise JobError("Your Hugging Face token is required (add it in Settings)")
    if not target_repo.strip():
        raise JobError("The dataset repo is required (e.g. 'kevindb/resume-qa')")

    from server.services.huggingface import (
        HuggingFaceNotConfiguredError,
        _api,
        qualify_repo_id,
    )

    try:
        await asyncio.to_thread(_api(creds).whoami)
    except Exception as exc:
        raise JobError(f"Hugging Face rejected your token: {exc}") from exc
    try:
        repo_id = await asyncio.to_thread(qualify_repo_id, creds, target_repo)
    except HuggingFaceNotConfiguredError as exc:
        raise JobError(str(exc)) from exc

    try:
        view = await rr.get_resume(resume_id)
    except rr.ResumeNotFoundError as exc:
        raise JobError(f"Reactive Resume has no resume '{resume_id}' any more") from exc
    except (rr.ResumeNotConfiguredError, rr.ResumeUnavailableError) as exc:
        raise JobError(str(exc)) from exc

    previous = PreviousState()
    if full_refresh:
        logger.info("full refresh: ignoring the previously published version")
    else:
        previous = await asyncio.to_thread(load_previous_state, _api(creds), repo_id)
    embedder = await asyncio.to_thread(get_embedder, creds)
    complete = complete or provider_completion(model_ref, creds)

    logger.info("generating Q&A pairs for resume %s with %s…", resume_id, model)
    dataset = await build_resume_dataset(
        view,
        complete,
        model,
        previous=previous,
        embedder=embedder,
        language=language,
        on_progress=on_progress,
        grader=complete,
        unanswerable=UNANSWERABLE_PAIRS,
    )
    for err in dataset.errors:
        logger.warning("non-fatal: %s", err)
    dataset.removed = removed_pairs(previous, dataset)
    who = _text((view.get("basics") or {}).get("name")) or _text(view.get("name"))
    return Draft(dataset, who, repo_id, full_refresh, model_ref)


def dataset_card(dataset: QADataset, who: str) -> str:
    """The dataset's README: its structure, composition and how it was made."""
    meta = dataset.manifest.get("resume") or {}
    language = meta.get("language") or "en"
    by_category: Dict[str, int] = {}
    models: List[str] = []
    for p in dataset.pairs:
        by_category[p.category] = by_category.get(p.category, 0) + 1
        if p.model and p.model not in models:
            models.append(p.model)
    facts = by_category.pop(FACTS_CATEGORY, 0)
    sections = (
        "\n".join(f"| `{c}` | {n} |" for c, n in sorted(by_category.items()))
        or "| _none_ | 0 |"
    )
    model_list = ", ".join(f"`{m}`" for m in models) or "an LLM"
    embedding_model = dataset.manifest.get("embedding_model")
    semantic_note = (
        f" and by embedding similarity (`{embedding_model}`, "
        f"{dataset.semantic_duplicates} rephrasing(s) rejected this version)"
        if embedding_model
        else ""
    )
    review_note = (
        f"- {len(dataset.review)} pair(s) held out in `review.jsonl`: their answer "
        "is far from the resume's text (possible hallucination) — review before "
        "moving them into `train.jsonl`.\n"
        if dataset.review
        else ""
    )
    errors_section = ""
    if dataset.errors:
        errors_section = (
            f"\n## Known generation issues\n\n{len(dataset.errors)} non-fatal "
            "error(s) occurred while generating this dataset (the affected "
            "section was skipped, not the whole run):\n\n"
            + "\n".join(f"- {e}" for e in dataset.errors)
            + "\n"
        )
    updated = f", last changed {meta['updated_at']}" if meta.get("updated_at") else ""
    name = meta.get("name") or ""
    dropped_note = (
        f" ({dataset.dropped} low-quality/duplicate pair(s) dropped before export)"
        if dataset.dropped
        else ""
    )
    front = [
        "---",
        "language:",
        f"- {language}",
        f'pretty_name: "Resume Q&A — {who}"',
        "tags:",
        "- resume",
        "- portfolio",
        "- synthetic",
        "annotations_creators:",
        "- machine-generated",
        "task_categories:",
        "- question-answering",
        "- text-generation",
        "size_categories:",
        f"- {_size_category(len(dataset.pairs))}",
        "---",
    ]
    body = f"""# Resume Q&A dataset — {who}

Synthetic question/answer pairs in {_LANGUAGE_NAMES.get(language, language)} about
{who}, generated from their resume on Reactive Resume ("{name}"{updated})
— the facts it states and the descriptions of its sections — for fine-tuning or
evaluating a personal-assistant / portfolio chatbot.

## Dataset structure

Each line of `train.jsonl` is one record:

| Field | Type | Description |
|---|---|---|
| `id` | string | Stable id derived from the pair's content |
| `question` | string | Generated question, naming {who} |
| `answer` | string | Generated answer |
| `source` | string | Always `"resume"` |
| `category` | string | `profile` (facts from the resume's fields), `unanswerable` (a question the resume doesn't answer, answered by saying so: the chat should decline), or the section the pair comes from (`experience`, `education`, `skills`, `projects`…) |
| `model` | string | LLM that generated the pair — absent for `profile` pairs (deterministic, no LLM) |
| `confidence` | number | 0–1: how well the source supports the answer, as reported by the LLM; 1.0 for `profile` pairs — absent when the model gave none |
| `sources` | list | The items the pair was generated from (`<section>::<item id>`) — absent for `profile` pairs |
| `grounding` | number | Cosine similarity between the answer and the closest passage of its items — absent when not computed |
| `judge` | number | The LLM's grade of the pair, 0–1 (true to its source, useful, self-contained); below 0.6 the pair is held out in `review.jsonl` — absent when not graded |
| `judge_note` | string | The grade's reason, in a few words |

## Composition

- **{len(dataset.pairs)} pairs** total: {facts} facts from the resume's fields (no LLM), the rest generated per section.
- This version: {dataset.kept} pair(s) carried over from unchanged items, {dataset.new} new or changed{dropped_note}.
- Deduplicated by normalized question text{semantic_note}; trivial or self-answering pairs dropped.
{review_note}
### Pairs per section

| Section | Pairs |
|---|---|
{sections}

## Generation

- The facts are taken from the resume's fields — no LLM involved; the phone
  number is never included.
- The other pairs are generated by {model_list} from each section's items,
  hidden sections and items left out.
- **Not manually reviewed** — treat this as synthetic/weak-labeled data and spot-check before
  relying on it for evaluation.
- Generated on {datetime.now(timezone.utc).isoformat()}.
{errors_section}"""
    return "\n".join(front) + "\n" + body


async def publish(creds: Credentials, draft: Draft) -> dict:
    """Publish a draft to its Hugging Face repo, with the resume's own card."""
    if not draft.repo_id:
        raise JobError("The dataset repo is required (e.g. 'kevindb/resume-qa')")
    return await asyncio.to_thread(
        publish_qa_dataset,
        creds,
        draft.dataset,
        draft.username,
        draft.repo_id,
        card=dataset_card(draft.dataset, draft.username),
        commit_message=f"Export resume Q&A dataset ({len(draft.dataset.pairs)} pairs)",
    )
