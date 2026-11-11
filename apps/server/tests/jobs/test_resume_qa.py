"""The resume Q&A job (jobs/resume_qa.py): the facts, the sources, the
generation and its incremental run, the card, the publication.

The resume is a canned ``resume_view``; the model a function counting its
calls; the Hub a mock (``_api``). The job's runner (jobs/registry.py) is
covered with the generation and the publication mocked.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from huggingface_hub.errors import EntryNotFoundError

from server.jobs import registry, resume_qa
from server.jobs.qa_dataset import (
    Draft,
    JobError,
    PreviousState,
    QADataset,
    QAPair,
    content_hash,
    removed_pairs,
    sanitize_pairs,
)
from server.jobs.resume_qa import (
    FACTS_CATEGORY,
    build_resume_dataset,
    dataset_card,
    detect_language,
    items_of,
    profile_facts,
    resume_sources,
)
from server.tests.creds import make_creds
from server.tests.fake_embedder import FakeEmbedder


def _item(id, title, subtitle="", period="", text="", keywords=()):
    return {
        "id": id,
        "title": title,
        "subtitle": subtitle,
        "period": period,
        "text": text,
        "keywords": list(keywords),
        "url": "",
    }


VIEW = {
    "id": "r1",
    "name": "Engineer",
    "slug": "engineer",
    "updated_at": "2026-11-01T10:00:00Z",
    "is_public": False,
    "basics": {
        "name": "Kevin",
        "headline": "Backend developer",
        "email": "kevin@example.com",
        "phone": "+33 6 00 00 00 00",
        "location": "Lyon, France",
        "website": "https://kevin.example",
        "facts": ["Open to remote work"],
        "links": [{"label": "GitHub", "url": "https://github.com/kevin"}],
    },
    "summary": "Ten years of Python and Go, mostly on data platforms.",
    "sections": [
        {
            "key": "experience",
            "title": "Experience",
            "items": [
                _item(
                    "e1",
                    "Lead developer",
                    "Acme",
                    "2023 – Present",
                    "Built the ingestion platform in Go.\n- Cut the costs by 40%",
                    ("Go", "Kafka"),
                ),
                _item(
                    "e2",
                    "Developer",
                    "Globex",
                    "2019 – 2023",
                    "Python services for billing.",
                ),
            ],
        },
        {
            "key": "education",
            "title": "Education",
            "items": [_item("d1", "MSc Computer Science", "INSA Lyon", "2014 – 2019")],
        },
        {
            "key": "skills",
            "title": "Skills",
            "items": [
                _item("s1", "Python", "Expert", keywords=("FastAPI", "SQLAlchemy")),
                _item("s2", "Go"),
            ],
        },
        {
            "key": "languages",
            "title": "Languages",
            "items": [_item("l1", "French", "Native"), _item("l2", "English", "C1")],
        },
    ],
}
ALL_SOURCES = {
    "basics",
    "summary",
    "experience::e1",
    "experience::e2",
    "education::d1",
    "skills::s1",
    "skills::s2",
    "languages::l1",
    "languages::l2",
}


def _counting_model():
    """One pair per call, its question naming the call."""
    requests = []

    async def complete(req):
        requests.append(req)
        return json.dumps(
            [
                {
                    "question": f"What did Kevin do in call {len(requests)}?",
                    "answer": f"Answer {len(requests)}.",
                    "confidence": 0.9,
                }
            ]
        )

    return complete, requests


def _facts(view=VIEW, language="en"):
    """The facts as a published version holds them, with their ids."""
    return sanitize_pairs(profile_facts(view, items_of(view), language))[0]


def _hashes(view=VIEW):
    sources = resume_sources(view, items_of(view))
    return {k: content_hash(s.text) for k, s in sources.items()}


# --- facts and sources ----------------------------------------------------------


def test_the_facts_are_exact_and_never_the_phone():
    facts = {p.question: p for p in profile_facts(VIEW, items_of(VIEW), "en")}

    assert facts["Who is Kevin?"].answer == "Kevin is Backend developer."
    assert facts["Where is Kevin based?"].answer == "Kevin is based in Lyon, France."
    assert facts["What is Kevin's current position?"].answer == (
        "Kevin is Lead developer at Acme (2023 – Present)."
    )
    assert facts["Where has Kevin worked?"].answer == (
        "Kevin has worked as Lead developer at Acme (2023 – Present) and "
        "Developer at Globex (2019 – 2023)."
    )
    assert facts["What did Kevin study?"].answer == (
        "Kevin studied MSc Computer Science — INSA Lyon (2014 – 2019)."
    )
    assert facts["What are Kevin's main skills?"].answer == (
        "Kevin's main skills are Python (FastAPI, SQLAlchemy) and Go."
    )
    assert facts["Which languages does Kevin speak?"].answer == (
        "Kevin speaks French (Native) and English (C1)."
    )
    contact = facts["How can I contact Kevin?"].answer
    assert "kevin@example.com" in contact and "https://kevin.example" in contact
    assert "GitHub (https://github.com/kevin)" in contact
    assert "+33" not in contact
    assert all(
        (p.category, p.source, p.confidence) == (FACTS_CATEGORY, "resume", 1.0)
        for p in facts.values()
    )


def test_the_facts_speak_french_too():
    facts = {p.question: p for p in profile_facts(VIEW, items_of(VIEW), "fr")}
    assert facts["Qui est Kevin ?"].answer == "Kevin est Backend developer."
    assert facts["Quel est le poste actuel de Kevin ?"].answer == (
        "Kevin est Lead developer chez Acme (2023 – Present)."
    )
    assert facts["Quelles langues parle Kevin ?"].answer == (
        "Kevin parle French (Native) et English (C1)."
    )
    assert facts["Comment contacter Kevin ?"].answer.startswith(
        "Vous pouvez joindre Kevin par e-mail à kevin@example.com"
    )


def test_a_past_position_is_the_latest_not_the_current():
    view = json.loads(json.dumps(VIEW))
    view["sections"][0]["items"][0]["period"] = "2023 – 2025"
    facts = {p.question for p in profile_facts(view, items_of(view), "en")}
    assert "What was Kevin's most recent position?" in facts
    assert "What is Kevin's current position?" not in facts


def test_the_language_is_detected_from_the_text():
    assert (
        detect_language("Développement de services pour la facturation et les données")
        == "fr"
    )
    assert (
        detect_language("Built the ingestion platform and the billing services") == "en"
    )
    assert detect_language("") == "en"


def test_each_item_is_a_hashed_source_without_the_phone():
    sources = resume_sources(VIEW, items_of(VIEW))
    assert set(sources) == ALL_SOURCES
    assert "+33" not in sources["basics"].text
    assert "GitHub: https://github.com/kevin" in sources["basics"].text
    assert sources["experience::e1"].text == (
        "Lead developer — Acme (2023 – Present)\n"
        "Built the ingestion platform in Go.\n- Cut the costs by 40%\n"
        "Keywords: Go, Kafka"
    )


# --- the build -------------------------------------------------------------------


async def test_a_first_run_generates_per_section_and_names_the_person():
    complete, requests = _counting_model()
    progress = []

    dataset = await build_resume_dataset(
        VIEW, complete, "m", on_progress=lambda *step: progress.append(step)
    )

    # One call per section, with every item of it and the person's name required.
    assert len(requests) == 4
    assert "## Experience" in requests[0].user
    assert "Developer — Globex" in requests[0].user
    assert all('"Kevin"' in r.user and "in English" in r.system for r in requests)
    generated = [p for p in dataset.pairs if p.category != FACTS_CATEGORY]
    facts = _facts()
    assert len(generated) == 4 and dataset.kept == 0
    # A first version: its facts are new too, and the review lists them.
    assert dataset.new == 4 + len(facts)
    assert set(dataset.new_ids) == {p.id for p in facts} | {p.id for p in generated}
    assert {p.category for p in generated} == {
        "experience",
        "education",
        "skills",
        "languages",
    }
    experience = next(p for p in generated if p.category == "experience")
    assert (experience.source, experience.model, experience.sources) == (
        "resume",
        "m",
        ["experience::e1", "experience::e2"],
    )
    assert set(dataset.manifest["sources"]) == ALL_SOURCES
    assert dataset.manifest["changed"] == len(ALL_SOURCES)
    assert dataset.manifest["resume"] == {
        "id": "r1",
        "name": "Engineer",
        "slug": "engineer",
        "updated_at": "2026-11-01T10:00:00Z",
        "language": "en",
    }
    assert progress[0] == (0, 4, "") and progress[-1][0] == 4


async def test_the_pairs_follow_the_resumes_language():
    complete, requests = _counting_model()
    view = json.loads(json.dumps(VIEW))
    view["summary"] = (
        "Dix ans de Python et de Go, surtout sur des plateformes de données."
    )
    view["sections"][0]["items"][0]["text"] = (
        "Conception de la plateforme d'ingestion en Go et réduction des coûts."
    )

    dataset = await build_resume_dataset(view, complete, "m")

    assert all("in French" in r.system for r in requests)
    assert dataset.manifest["resume"]["language"] == "fr"
    assert "Qui est Kevin ?" in {p.question for p in dataset.pairs}


async def test_an_unchanged_resume_costs_no_call():
    published = QAPair(
        "What did Kevin build at Acme?",
        "The ingestion platform.",
        "experience",
        source="resume",
        id="p1",
        sources=["experience::e1", "experience::e2"],
    )
    previous = PreviousState([published, *_facts()], _hashes())

    async def never(req):  # pragma: no cover
        raise AssertionError("a model call for an unchanged resume")

    dataset = await build_resume_dataset(VIEW, never, "m", previous=previous)

    assert dataset.manifest["changed"] == 0
    assert dataset.kept == 1 and dataset.new == 0
    assert published in dataset.pairs
    draft = Draft(dataset, "Kevin", "kevin/resume-qa", False, "openai:m")
    assert resume_qa.unchanged(draft)


async def test_a_changed_item_is_regenerated_and_its_old_pairs_rechecked():
    hashes = _hashes()
    hashes["experience::e1"] = "stale"
    old_pair = QAPair(
        "What is Kevin's favourite fruit?",
        "Bananas, and plenty of them.",
        "experience",
        source="resume",
        id="old",
        sources=["experience::e1"],
    )
    kept_pair = QAPair(
        "What did Kevin do at Globex?",
        "Python services for billing.",
        "experience",
        source="resume",
        id="kept",
        sources=["experience::e2"],
    )
    requests = []

    async def complete(req):
        requests.append(req)
        # An answer in the item's own words: grounded, so accepted.
        return json.dumps(
            [
                {
                    "question": "What platform did Kevin build at Acme?",
                    "answer": "Kevin built the ingestion platform in Go at Acme.",
                }
            ]
        )

    dataset = await build_resume_dataset(
        VIEW,
        complete,
        "m",
        previous=PreviousState([old_pair, kept_pair, *_facts()], hashes),
        embedder=FakeEmbedder(),
    )

    # Only the changed item is sent, alone in its section's call.
    assert len(requests) == 1
    assert "Lead developer — Acme" in requests[0].user
    assert "Developer — Globex" not in requests[0].user
    # The old pair's answer is far from the new text: held out, not dropped.
    assert [p.id for p in dataset.review] == ["old"]
    assert kept_pair in dataset.pairs and dataset.kept == 1
    assert dataset.new == 1
    assert "What platform did Kevin build at Acme?" in {
        p.question for p in dataset.pairs
    }
    assert dataset.manifest["changed"] == 1
    assert dataset.manifest["sources"]["experience::e1"] == _hashes()["experience::e1"]


async def test_a_fact_is_new_when_the_published_version_says_otherwise():
    facts = _facts()
    where = next(p for p in facts if p.question == "Where is Kevin based?")
    stale = QAPair(
        where.question,
        "Kevin is based in Paris.",
        FACTS_CATEGORY,
        source="resume",
        id=where.id,
    )
    previous = PreviousState([stale if p is where else p for p in facts], _hashes())

    async def never(req):  # pragma: no cover
        raise AssertionError("a model call for an unchanged resume")

    dataset = await build_resume_dataset(VIEW, never, "m", previous=previous)

    # Only the fact whose answer moved is new, so the review shows it.
    assert dataset.new_ids == [where.id] and dataset.new == 1
    draft = Draft(dataset, "Kevin", "kevin/resume-qa", False, "openai:m")
    assert not resume_qa.unchanged(draft)  # something to publish


async def test_a_removed_item_drops_its_pairs():
    gone = QAPair(
        "What was project X?",
        "A thing.",
        "projects",
        source="resume",
        id="gone",
        sources=["projects::p9"],
    )
    previous = PreviousState([gone], _hashes())
    complete, _ = _counting_model()

    dataset = await build_resume_dataset(VIEW, complete, "m", previous=previous)

    assert gone not in dataset.pairs and gone not in dataset.review
    assert removed_pairs(previous, dataset) == [gone]


async def test_a_failed_section_keeps_its_previous_hash():
    async def failing(req):
        if "## Skills" in req.user:
            return ""
        return json.dumps([{"question": "What did Kevin do?", "answer": "Things."}])

    dataset = await build_resume_dataset(VIEW, failing, "m")

    assert dataset.errors and "Skills" in dataset.errors[0]
    # Never hashed: the next run sends the section again.
    assert "skills::s1" not in dataset.manifest["sources"]
    assert "experience::e1" in dataset.manifest["sources"]


async def test_an_empty_resume_is_refused():
    with pytest.raises(JobError, match="nothing visible"):
        await build_resume_dataset(
            {"id": "r", "name": "", "basics": {}, "summary": "", "sections": []},
            _counting_model()[0],
            "m",
        )


def test_the_card_describes_the_dataset():
    pairs = profile_facts(VIEW, items_of(VIEW), "en") + [
        QAPair(
            "What did Kevin build?",
            "A platform.",
            "experience",
            model="m",
            source="resume",
        )
    ]
    dataset = QADataset(
        pairs,
        0,
        [],
        kept=0,
        new=1,
        manifest={
            "resume": {"name": "Engineer", "language": "en", "updated_at": "2026-11-01"}
        },
    )
    card = dataset_card(dataset, "Kevin")
    assert 'pretty_name: "Resume Q&A — Kevin"' in card
    assert "language:\n- en" in card
    assert '("Engineer", last changed 2026-11-01)' in card
    assert "| `experience` | 1 |" in card
    assert "phone\n  number is never included" in card


# --- generate and publish -------------------------------------------------------------

CREDS = make_creds(
    openai_api_key="sk-000000000000", hf_token="hf_000000000000", hf_namespace="kevin"
)


def _hub(private=True):
    api = MagicMock()
    api.whoami.return_value = {"name": "kevin"}
    api.hf_hub_download.side_effect = EntryNotFoundError("missing")
    api.repo_info.return_value = MagicMock(private=private)
    return api


async def test_generate_reads_the_resume_with_the_servers_key_then_publishes():
    complete, requests = _counting_model()
    api = _hub()
    with (
        patch.object(resume_qa.rr, "get_resume", AsyncMock(return_value=VIEW)) as read,
        patch("server.services.huggingface._api", return_value=api),
        patch.object(resume_qa, "get_embedder", lambda creds: None),
    ):
        draft = await resume_qa.generate(CREDS, "r1", "resume-qa", complete=complete)
        result = await resume_qa.publish(CREDS, draft)

    read.assert_awaited_once_with("r1")
    # No model given: OPENAI_LLM_MODEL (a run always passes a normalized one).
    assert (draft.username, draft.repo_id, draft.model_ref) == (
        "Kevin",
        "kevin/resume-qa",
        "gpt-4o-mini",
    )
    # 4 sections, each graded, then the unanswerable questions, graded too
    # (the fake's grades read as none: every pair stays).
    graded = [
        r for r in requests if r.system.startswith(("You grade", "Each question"))
    ]
    asked = [r for r in requests if r.system.startswith("You write test questions")]
    assert (len(requests), len(graded), len(asked)) == (10, 5, 1)
    unanswerable = [p for p in draft.dataset.pairs if p.category == "unanswerable"]
    assert len(unanswerable) == 1 and unanswerable[0].sources == ["unanswerable"]
    assert draft.dataset.new == 4 + len(_facts()) + 1
    assert result["url"] == "https://huggingface.co/datasets/kevin/resume-qa"
    commit = api.create_commit.call_args.kwargs
    assert commit["repo_id"] == "kevin/resume-qa"
    assert commit["commit_message"].startswith("Export resume Q&A dataset")
    files = {op.path_in_repo: op.path_or_fileobj for op in commit["operations"]}
    assert set(files) == {"train.jsonl", "review.jsonl", "manifest.json", "README.md"}
    assert b"Resume Q&A" in files["README.md"]
    manifest = json.loads(files["manifest.json"])
    assert manifest["resume"]["id"] == "r1"
    assert set(manifest["sources"]) == ALL_SOURCES | {"unanswerable"}


async def test_generate_checks_what_it_needs_before_spending_anything():
    complete, requests = _counting_model()
    with pytest.raises(JobError, match="Hugging Face token"):
        await resume_qa.generate(
            make_creds(openai_api_key="sk-000000000000"), "r1", "x", complete=complete
        )
    with pytest.raises(JobError, match="dataset repo"):
        await resume_qa.generate(CREDS, "r1", "  ", complete=complete)
    with pytest.raises(JobError, match="language"):
        await resume_qa.generate(CREDS, "r1", "x", language="de", complete=complete)
    api = _hub()
    gone = AsyncMock(side_effect=resume_qa.rr.ResumeNotFoundError("No such resume"))
    with (
        patch.object(resume_qa.rr, "get_resume", gone),
        patch("server.services.huggingface._api", return_value=api),
    ):
        with pytest.raises(JobError, match="no resume 'r1' any more"):
            await resume_qa.generate(CREDS, "r1", "resume-qa", complete=complete)
    assert requests == []


# --- the job's runner (jobs/registry.py) -------------------------------------------


def _draft(review=False, changed=1):
    pairs = [
        QAPair("What did Kevin do?", "Things.", "experience", id="n1", source="resume")
    ]
    dataset = QADataset(
        pairs,
        0,
        [],
        new=1,
        new_ids=["n1"],
        review=[QAPair("Doubtful?", "Maybe.", "experience", id="h1")] if review else [],
        manifest={"changed": changed},
    )
    return Draft(dataset, "Kevin", "kevin/resume-qa", False, "openai:m")


def _options(**values):
    return registry.ResumeQAOptions(
        resume_id="r1", target_repo="kevin/resume-qa", **values
    )


async def test_a_run_you_start_stops_at_a_draft():
    with patch.object(resume_qa, "generate", AsyncMock(return_value=_draft())) as gen:
        outcome = await registry._run_resume_qa(
            CREDS,
            _options(language="fr", full_refresh=True),
            "openai:m",
            lambda *_: None,
        )
    assert gen.call_args.args == (CREDS, "r1", "kevin/resume-qa")
    assert gen.call_args.kwargs["language"] == "fr"
    assert gen.call_args.kwargs["full_refresh"] is True
    assert outcome.result.dry_run is True and outcome.result.url is None
    assert outcome.draft is not None and outcome.draft["repo_id"] == "kevin/resume-qa"


async def test_a_scheduled_run_publishes_what_passes_and_keeps_the_rest():
    published = {"url": "https://huggingface.co/datasets/kevin/resume-qa"}
    with (
        patch.object(
            resume_qa, "generate", AsyncMock(return_value=_draft(review=True))
        ),
        patch.object(resume_qa, "publish", AsyncMock(return_value=published)) as pub,
    ):
        outcome = await registry._run_resume_qa(
            CREDS, _options(publish=True), "openai:m", lambda *_: None
        )
    pub.assert_awaited_once()
    assert outcome.result.dry_run is False and outcome.result.url == published["url"]
    # The held-out pair stays a draft, reviewed and published on top later.
    assert outcome.draft is not None
    assert [p["id"] for p in outcome.draft["dataset"]["review"]] == ["h1"]

    with (
        patch.object(resume_qa, "generate", AsyncMock(return_value=_draft())),
        patch.object(resume_qa, "publish", AsyncMock(return_value=published)),
    ):
        outcome = await registry._run_resume_qa(
            CREDS, _options(publish=True), "openai:m", lambda *_: None
        )
    assert outcome.draft is None  # nothing left to review


async def test_an_unchanged_resume_is_reported_not_published():
    unchanged = _draft(changed=0)
    unchanged.dataset.new, unchanged.dataset.new_ids = 0, []
    with (
        patch.object(resume_qa, "generate", AsyncMock(return_value=unchanged)),
        patch.object(resume_qa, "publish", AsyncMock()) as pub,
    ):
        outcome = await registry._run_resume_qa(
            CREDS, _options(publish=True), "openai:m", lambda *_: None
        )
    pub.assert_not_awaited()
    assert outcome.draft is None
    assert outcome.result.metrics[0] == ("Unchanged", "the resume hasn't changed")


async def test_the_reviewed_draft_is_published_as_reviewed():
    data = registry._draft_to_dict(_draft(review=True))
    with patch.object(
        resume_qa, "publish", AsyncMock(return_value={"url": "https://hf.co/d"})
    ) as pub:
        result = await registry._publish_resume_qa(CREDS, data, ["n1"], ["h1"], {})
    draft = pub.call_args.args[1]
    assert [p.id for p in draft.dataset.pairs] == ["h1"]
    assert result.url == "https://hf.co/d"


def test_the_job_is_in_the_catalogue_for_admins_only():
    spec = registry.JOBS[resume_qa.RESUME_JOB_ID]
    assert spec.admin_only and not spec.listed and spec.uses_model
    assert spec.publisher is registry._publish_resume_qa


# --- the grader and the unanswerable questions -----------------------------------


def _grading(scores):
    """A model that writes one pair per section and grades by question."""
    requests = []

    async def complete(req):
        requests.append(req)
        if req.system.startswith(("You grade", "Each question")):
            listed = [
                json.loads(line) for line in req.user.split("Pairs:\n")[1].splitlines()
            ]
            return json.dumps(
                [
                    {"id": p["id"], "score": scores(p["question"]), "reason": "checked"}
                    for p in listed
                ]
            )
        if req.system.startswith("You write test questions"):
            return json.dumps(
                [
                    {
                        "question": "Does Kevin have a PhD?",
                        "answer": "The resume doesn't say.",
                    },
                    {"question": "What did Kevin study?", "answer": "Not mentioned."},
                ]
            )
        section = req.user.split("## ")[1].split("\n")[0]
        return json.dumps(
            [
                {
                    "question": f"What did Kevin do in {section}?",
                    "answer": "Things he did.",
                }
            ]
        )

    return complete, requests


async def test_the_grader_holds_low_grades_for_review_with_the_reason():
    complete, _ = _grading(lambda q: 0.2 if "Skills" in q else 0.9)

    dataset = await build_resume_dataset(VIEW, complete, "m", grader=complete)

    held = {p.question: p for p in dataset.review}
    assert set(held) == {"What did Kevin do in Skills?"}
    assert (
        held["What did Kevin do in Skills?"].judge,
        held["What did Kevin do in Skills?"].judge_note,
    ) == (0.2, "checked")
    kept = [p for p in dataset.pairs if p.category == "experience"]
    assert kept and kept[0].judge == 0.9
    # The grade travels with the pair, to the Hub and back.
    back = QAPair.from_record(kept[0].to_record())
    assert back is not None and (back.judge, back.judge_note) == (0.9, "checked")


async def test_a_failed_grading_keeps_the_pairs_and_says_so():
    async def complete(req):
        if req.system.startswith("You grade"):
            from server.services.providers import ProviderError

            raise ProviderError("openai:m call failed: 429")
        return json.dumps(
            [{"question": "What did Kevin do?", "answer": "Things he did."}]
        )

    dataset = await build_resume_dataset(VIEW, complete, "m", grader=complete)

    assert not dataset.review and dataset.new > len(_facts())
    assert any(e.startswith("Grading skipped") and "429" in e for e in dataset.errors)


async def test_unanswerable_questions_are_asked_and_the_answered_ones_dropped():
    # The grader says the resume answers "What did Kevin study?": dropped.
    complete, requests = _grading(lambda q: 0.1 if "study" in q else 0.9)

    dataset = await build_resume_dataset(
        VIEW, complete, "m", grader=complete, unanswerable=6
    )

    asked = next(r for r in requests if r.system.startswith("You write test questions"))
    assert "Write 6 such pairs" in asked.user and "kevin@example.com" in asked.system
    unanswerable = [p for p in dataset.pairs if p.category == "unanswerable"]
    assert [p.question for p in unanswerable] == ["Does Kevin have a PhD?"]
    assert unanswerable[0].id in dataset.new_ids
    assert "unanswerable" in dataset.manifest["sources"]


async def test_an_unchanged_resume_keeps_its_unanswerable_questions():
    complete, requests = _grading(lambda q: 0.9)
    first = await build_resume_dataset(
        VIEW, complete, "m", grader=complete, unanswerable=2
    )
    previous = PreviousState(first.pairs, first.manifest["sources"])

    async def never(req):  # pragma: no cover
        raise AssertionError("a model call for an unchanged resume")

    again = await build_resume_dataset(
        VIEW, never, "m", previous=previous, grader=never, unanswerable=2
    )
    assert again.manifest["changed"] == 0 and not again.new
    assert {p.question for p in again.pairs if p.category == "unanswerable"} == {
        p.question for p in first.pairs if p.category == "unanswerable"
    }
