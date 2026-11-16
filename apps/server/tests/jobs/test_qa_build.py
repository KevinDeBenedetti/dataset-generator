"""The incremental Q&A build (jobs/qa_build.py), through its interface.

A hand-written source stands in for the GitHub and resume ones: a few named
texts, one model call per changed text. What is checked here is what every
Q&A job relies on, whatever its pairs are about — what is kept, regenerated,
dropped and recorded.
"""

from typing import Dict, Iterable, List, Optional, Sequence

from server.jobs.qa_build import (
    JobError,
    PreviousState,
    QADataset,
    QAPair,
    Run,
    generate_draft,
    to_records,
    Source,
    SourcePlan,
    Task,
    TaskGroup,
    build,
    content_hash,
    pair_id,
)
import pytest

from server.services.hub_repo import to_jsonl
from server.tests.creds import make_creds
from server.tests.fake_embedder import FakeEmbedder


def pair(question: str, source: Optional[str], category: str = "topic") -> QAPair:
    """A published pair generated from ``source`` (None: a fact)."""
    made = QAPair(
        question,
        f"An answer to: {question}",
        category,
        sources=[source] if source else [],
    )
    made.id = pair_id(made)
    return made


class FakeSource:
    """Texts by key, one model call per changed text. ``calls`` records the
    calls made, in order, with the guidance each was given."""

    def __init__(
        self,
        texts: Dict[str, str],
        *,
        facts: Sequence[QAPair] = (),
        failing: Iterable[str] = (),
        outside: Iterable[str] = (),
        groups: Optional[List[List[str]]] = None,
        answers: Optional[Dict[str, List[str]]] = None,
    ) -> None:
        self.texts = texts
        self.facts = list(facts)
        self.failing = set(failing)
        self.outside = set(outside)
        self.grouping = groups
        self.answers = answers or {}
        self.calls: List[tuple] = []

    def plan(self, concurrency: int = 1) -> SourcePlan:
        sources = {key: Source(key, text) for key, text in self.texts.items()}

        def task(key: str) -> Task:
            async def run(avoid: List[str], focus: List[str]) -> List[QAPair]:
                self.calls.append((key, list(avoid), list(focus)))
                if key in self.failing:
                    raise JobError("the model gave nothing usable")
                questions = self.answers.get(key, [f"What does {key} say now?"])
                return [pair(q, key) for q in questions]

            return Task([key], f"source {key}", sources[key].text, run)

        def groups() -> List[TaskGroup]:
            grouping = self.grouping or [[key] for key in sources]
            out = []
            for keys in grouping:
                tasks = [task(k) for k in keys if sources[k].changed]
                if tasks:
                    out.append(TaskGroup("+".join(keys), tasks))
            return out

        return SourcePlan(
            sources=sources,
            facts=self.facts,
            groups=groups,
            sources_of=lambda p: None if p.category == "fact" else p.sources,
            concurrency=concurrency,
            outside_pair=lambda p: bool(set(p.sources) & self.outside),
            outside_source=lambda key: key in self.outside,
        )


def published(texts: Dict[str, str], pairs: Sequence[QAPair]) -> PreviousState:
    """A published version built from ``texts``."""
    return PreviousState(
        list(pairs), {key: content_hash(text) for key, text in texts.items()}, "c1"
    )


def questions(pairs: Sequence[QAPair]) -> List[str]:
    return [p.question for p in pairs]


# --- what is kept, regenerated and dropped -------------------------------------


async def test_a_first_run_generates_every_source():
    source = FakeSource({"a": "Alpha text.", "b": "Beta text."})
    result = await build(source.plan(), PreviousState())

    assert [key for key, *_ in source.calls] == ["a", "b"]
    assert questions(result.accepted) == [
        "What does a say now?",
        "What does b say now?",
    ]
    assert (result.existing, result.kept, result.changed) == ([], 0, 2)
    assert result.source_hashes() == {
        "a": content_hash("Alpha text."),
        "b": content_hash("Beta text."),
    }


async def test_an_unchanged_source_keeps_its_pairs_without_a_model_call():
    texts = {"a": "Alpha text.", "b": "Beta text."}
    old = published(texts, [pair("What was a?", "a"), pair("What was b?", "b")])
    source = FakeSource({**texts, "b": "Beta text, edited."})

    result = await build(source.plan(), old)

    assert [key for key, *_ in source.calls] == ["b"]
    # a's pair is carried; b's is re-checked (kept: no embedder) and b regenerated.
    assert questions(result.existing) == ["What was a?", "What was b?"]
    assert questions(result.accepted) == ["What does b say now?"]
    assert (result.kept, result.changed) == (2, 1)
    assert questions(result.recheck) == ["What was b?"]


async def test_nothing_changed_means_no_call_and_no_embedding():
    texts = {"a": "Alpha text."}
    source = FakeSource(texts, facts=[pair("Who is it about?", None, "fact")])
    embedder = FakeEmbedder()

    result = await build(
        source.plan(), published(texts, [pair("What was a?", "a")]), embedder=embedder
    )

    assert source.calls == [] and embedder.calls == []
    assert questions(result.existing) == ["Who is it about?", "What was a?"]
    assert (result.accepted, result.changed) == ([], 0)


async def test_the_pairs_of_a_source_that_is_gone_are_dropped():
    old = published(
        {"a": "Alpha text.", "gone": "Old text."},
        [pair("What was a?", "a"), pair("What was gone?", "gone")],
    )
    source = FakeSource({"a": "Alpha text."})

    result = await build(source.plan(), old)

    assert questions(result.existing) == ["What was a?"]
    assert "gone" not in result.source_hashes()


async def test_a_pair_keeps_only_the_sources_that_still_exist():
    both = pair("What links a and gone?", "a")
    both.sources = ["a", "gone"]
    old = published({"a": "Alpha text.", "gone": "Old text."}, [both])

    result = await build(FakeSource({"a": "Alpha text."}).plan(), old)

    assert result.existing[0].sources == ["a"]


async def test_a_source_outside_the_run_keeps_its_pairs_and_its_hash():
    old = published(
        {"a": "Alpha text.", "later": "Not read this time."},
        [pair("What was a?", "a"), pair("What was later?", "later")],
    )
    source = FakeSource({"a": "Alpha text."}, outside=["later"])

    result = await build(source.plan(), old)

    assert questions(result.existing) == ["What was a?", "What was later?"]
    assert result.source_hashes()["later"] == content_hash("Not read this time.")
    assert source.calls == []


async def test_facts_are_rebuilt_never_carried():
    old = published(
        {"a": "Alpha text."},
        [pair("An old fact?", None, "fact"), pair("What was a?", "a")],
    )
    source = FakeSource(
        {"a": "Alpha text."}, facts=[pair("A fact of today?", None, "fact")]
    )

    result = await build(source.plan(), old)

    assert questions(result.existing) == ["A fact of today?", "What was a?"]
    # The facts come first, and are not counted as carried over.
    assert result.kept == 1


# --- new pairs join what is there ----------------------------------------------


async def test_an_existing_pair_is_never_displaced_by_a_regenerated_one():
    texts = {"a": "Alpha text.", "b": "Beta text."}
    kept = pair("What does b say now?", "a")  # the question b's call will ask
    old = published(texts, [kept])
    source = FakeSource({**texts, "b": "Beta text, edited."})

    result = await build(source.plan(), old)

    assert result.existing == [kept]
    assert result.accepted == [] and result.dropped == 1


async def test_a_new_pair_rephrasing_a_fact_is_dropped_as_a_duplicate():
    fact = pair("Which language is the project written in?", None, "fact")
    source = FakeSource(
        {"a": "Alpha text."},
        facts=[fact],
        answers={
            "a": [
                "which language is the project written in",
                "What does a say now?",
            ]
        },
    )

    result = await build(source.plan(), PreviousState())

    assert result.existing == [fact]
    assert questions(result.accepted) == ["What does a say now?"]


async def test_a_call_is_steered_away_from_the_questions_already_there():
    texts = {"a": "Alpha text about rockets.", "b": "Beta text about rockets."}
    old = published(texts, [pair("What does the text say about rockets?", "a")])
    source = FakeSource({**texts, "b": "Beta text about rockets, edited."})

    await build(source.plan(), old, embedder=FakeEmbedder())

    [(key, avoid, _focus)] = source.calls
    assert key == "b" and avoid == ["What does the text say about rockets?"]


async def test_a_low_grade_sends_a_new_pair_to_review():
    source = FakeSource({"a": "Alpha text."})

    async def grader(request) -> str:
        new = pair("What does a say now?", "a")  # its id is its content's
        return f'[{{"id": "{new.id}", "score": 0.2, "reason": "not in the text"}}]'

    result = await build(source.plan(), PreviousState(), grader=grader)

    assert result.accepted == []
    assert questions(result.review) == ["What does a say now?"]
    assert result.review[0].judge_note == "not in the text"


# --- failures ------------------------------------------------------------------


async def test_a_failed_call_is_reported_and_retried_next_time():
    texts = {"a": "Alpha text.", "b": "Beta text.", "new": "Never published."}
    old = published({"a": "Alpha, before.", "b": "Beta, before."}, [])
    source = FakeSource(texts, failing=["a", "new"])

    result = await build(source.plan(), old)

    assert result.errors == [
        "source a: the model gave nothing usable",
        "source new: the model gave nothing usable",
    ]
    # The rest of the run goes on.
    assert questions(result.accepted) == ["What does b say now?"]
    hashes = result.source_hashes()
    # A failed source keeps its previous hash, or none: the next run sees it
    # as changed and calls again.
    assert hashes["a"] == content_hash("Alpha, before.")
    assert "new" not in hashes
    assert hashes["b"] == content_hash("Beta text.")


async def test_a_job_can_report_a_failure_of_its_own():
    old = published({"a": "Alpha, before."}, [])
    result = await build(FakeSource({"a": "Alpha text.", "b": "Beta."}).plan(), old)

    hashes = result.source_hashes(failed=["a", "b"])
    assert hashes == {"a": content_hash("Alpha, before.")}
    assert set(result.source_hashes()) == {"a", "b"}


# --- groups and progress -------------------------------------------------------


async def test_a_groups_calls_run_in_order_and_progress_counts_groups():
    source = FakeSource(
        {"a": "Alpha.", "b": "Beta.", "c": "Gamma."}, groups=[["a", "b"], ["c"]]
    )
    seen: List[tuple] = []

    await build(
        source.plan(concurrency=2),
        PreviousState(),
        on_progress=lambda *step: seen.append(step),
    )

    order = [key for key, *_ in source.calls]
    assert order.index("a") < order.index("b")
    assert seen[0] == (0, 2, "")
    assert sorted(seen[1:]) == [(1, 2, "a+b"), (2, 2, "c")] or sorted(seen[1:]) == [
        (1, 2, "c"),
        (2, 2, "a+b"),
    ]


async def test_a_group_with_nothing_changed_is_not_counted():
    texts = {"a": "Alpha.", "b": "Beta."}
    source = FakeSource({**texts, "b": "Beta, edited."})
    seen: List[tuple] = []

    await build(
        source.plan(), published(texts, []), on_progress=lambda *s: seen.append(s)
    )

    assert seen == [(0, 1, ""), (1, 1, "b")]


# --- the manifest --------------------------------------------------------------


async def test_the_manifest_names_the_embedding_model_and_the_sources():
    result = await build(FakeSource({"a": "Alpha text."}).plan(), PreviousState())

    assert result.manifest(None)["embedding_model"] is None
    manifest = result.manifest(FakeEmbedder())
    assert manifest["embedding_model"] == "fake/bag-of-words"
    assert manifest["sources"] == {"a": content_hash("Alpha text.")}
    assert "embedding_checks" in manifest


# --- a run: generate_draft -----------------------------------------------------


def own_topic_pair(row: dict) -> Optional[QAPair]:
    made = QAPair.from_record(row)
    return made if made is not None and made.category == "topic" else None


async def _echo(_request) -> str:  # pragma: no cover — no test here calls the model
    return "[]"


async def test_a_run_checks_everything_before_the_job_builds(memory_hub):
    creds = make_creds(openai_api_key="sk-000000000000", hf_token="hf_000000000000")
    built: List[str] = []

    async def make(run: Run):  # pragma: no cover — must never be reached
        built.append("built")
        return QADataset([], 0, []), "nobody"

    async def attempt(creds=creds, repo="kevin/qa"):
        return await generate_draft(
            creds, repo, own_topic_pair, make, missing_repo="Name a dataset repo"
        )

    with pytest.raises(JobError, match="API key"):
        await attempt(make_creds(hf_token="hf_000000000000"))
    with pytest.raises(JobError, match="Hugging Face token"):
        await attempt(make_creds(openai_api_key="sk-000000000000"))
    with pytest.raises(JobError, match="Name a dataset repo"):
        await attempt(repo="  ")
    memory_hub.rejects_token = True
    with pytest.raises(JobError, match="rejected your token"):
        await attempt()
    assert built == []


async def test_a_draft_knows_what_it_was_built_on_and_what_it_removes(memory_hub):
    creds = make_creds(openai_api_key="sk-000000000000", hf_token="hf_000000000000")
    stays, goes = pair("What stays?", "a"), pair("What goes?", "b")
    foreign = {"id": "f1", "question": "From a file?", "answer": "Yes."}
    commit = memory_hub.push(
        "kevin/qa",
        {"train.jsonl": to_jsonl([*to_records([stays, goes]), foreign])},
    )
    seen: List[Run] = []

    async def make(run: Run):
        seen.append(run)
        return QADataset([stays], 0, ["a (docs 1): boom"]), "Kevin"

    draft = await generate_draft(
        creds,
        "qa",  # a bare name: completed with the token's account
        own_topic_pair,
        make,
        missing_repo="-",
        model_ref="openai:m",
        complete=_echo,
    )

    [run] = seen
    assert (run.model, run.complete) == ("m", _echo)
    # The job's own published pairs only: the foreign row is not its to build on.
    assert questions(run.previous.pairs) == ["What stays?", "What goes?"]
    assert (draft.username, draft.repo_id, draft.model_ref) == (
        "Kevin",
        "kevin/qa",
        "openai:m",
    )
    assert draft.base_commit == commit
    assert questions(draft.dataset.removed) == ["What goes?"]
    assert draft.full_refresh is False


async def test_a_full_refresh_reads_nothing_and_records_no_commit(memory_hub):
    creds = make_creds(openai_api_key="sk-000000000000", hf_token="hf_000000000000")
    memory_hub.push("kevin/qa", {"train.jsonl": b"not json\n"})

    async def make(run: Run):
        assert run.previous == PreviousState()
        return QADataset([], 0, []), "Kevin"

    draft = await generate_draft(
        creds,
        "kevin/qa",
        own_topic_pair,
        make,
        missing_repo="-",
        full_refresh=True,
        complete=_echo,
    )

    assert memory_hub.downloads == []
    assert (draft.base_commit, draft.full_refresh) == (None, True)
