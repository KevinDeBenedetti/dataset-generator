"""Generating a dataset from a recipe (jobs/qa_dataset.py, Selection).

GitHub is the ``github`` fake of tests/jobs/conftest.py; the model is a
function counting its calls; the Hub is a mock (``_api``).
"""

import json
from dataclasses import replace
from unittest.mock import MagicMock, patch

import pytest
from huggingface_hub.errors import EntryNotFoundError

from server.jobs import qa_dataset
from server.jobs.github_snapshot import RepoDoc
from server.jobs.qa_dataset import (
    JobError,
    PreviousState,
    QAPair,
    QADataset,
    Selection,
    build_qa_dataset,
    pair_id,
    removed_pairs,
)
from server.tests.creds import make_creds
from server.tests.jobs.conftest import b64

CREDS = make_creds(
    github_username="kevin",
    openai_api_key="sk-000000000000",
    hf_token="hf_000000000000",
)


def _counting_model():
    requests = []

    async def complete(req):
        requests.append(req)
        return json.dumps(
            [
                {
                    "question": f"What does question {len(requests)} ask?",
                    "answer": f"Answer {len(requests)}.",
                }
            ]
        )

    return complete, requests


async def test_a_selection_generates_only_what_it_selects(github, snapshot):
    complete, requests = _counting_model()
    selection = Selection(
        include_profile=False,
        overview_repos=set(),
        docs_by_repo={"portfolio": [RepoDoc("docs/guide.md", "# Guide\n\nHow to.")]},
    )

    dataset = await build_qa_dataset(
        github.client(), snapshot, complete, "m", selection=selection
    )

    # One docs batch, no overview call: the README is left out.
    assert len(requests) == 1
    assert "docs/guide.md" in requests[0].user
    # No profile facts, no repo facts: only what the docs gave.
    assert {p.category for p in dataset.pairs} == {"docs"}
    assert dataset.manifest["sources"].keys() == {"portfolio::docs/guide.md"}
    # The docs were given: the repo tree was never read.
    assert not any("/git/trees/" in call for call in github.calls)


async def test_a_deselected_source_drops_its_pairs_and_a_failed_repo_keeps_them(
    github, snapshot
):
    complete, _ = _counting_model()
    old_overview = QAPair(
        "What is portfolio?",
        "A site.",
        "overview",
        repo="portfolio",
        sources=["portfolio::overview"],
    )
    unreachable = QAPair(
        "What is gone?", "A repo.", "overview", repo="gone", sources=["gone::overview"]
    )
    # Published pairs carry their content id.
    for pair in (old_overview, unreachable):
        pair.id = pair_id(pair)
    previous = PreviousState(
        [old_overview, unreachable],
        {"portfolio::overview": "x", "gone::overview": "y"},
    )
    selection = Selection(
        include_profile=False,
        overview_repos=set(),  # portfolio's README is now left out
        docs_by_repo={"portfolio": []},
        carry_over={"gone"},  # couldn't be read this time
    )

    dataset = await build_qa_dataset(
        github.client(), snapshot, complete, "m", previous=previous, selection=selection
    )

    ids = {p.id for p in dataset.pairs}
    assert old_overview.id not in ids
    assert unreachable.id in ids
    assert dataset.manifest["sources"] == {"gone::overview": "y"}
    assert removed_pairs(previous, dataset) == [old_overview]


def test_removed_pairs_skip_what_moved_to_review():
    kept = QAPair("Q1?", "A.", "docs", id="a")
    reviewed = QAPair("Q2?", "A.", "docs", id="b")
    dropped = QAPair("Q3?", "A.", "docs", id="c")
    dataset = QADataset([kept], 0, [], review=[reviewed])

    assert removed_pairs(PreviousState([kept, reviewed, dropped], {}), dataset) == [
        dropped
    ]


def test_removed_pairs_survive_the_draft_round_trip():
    dataset = QADataset([], 0, [], removed=[QAPair("Q?", "A.", "docs", id="x")])

    again = QADataset.from_dict(dataset.to_dict())

    assert [p.id for p in again.removed] == ["x"]
    assert [p.id for p in again.with_selection().removed] == ["x"]


def _hub(api_name="kevin"):
    api = MagicMock()
    api.whoami.return_value = {"name": api_name}
    # First publish: nothing on the Hub yet.
    api.hf_hub_download.side_effect = EntryNotFoundError("missing")
    return api


def _portfolio_routes(github):
    github.json(
        "/repos/kevin/portfolio",
        {
            "name": "portfolio",
            "description": "My site",
            "default_branch": "main",
            "html_url": "https://github.com/kevin/portfolio",
        },
    )
    github.text("/repos/kevin/portfolio/readme", "# Portfolio\n\nHello.")
    github.json(
        "/repos/kevin/portfolio/git/trees/main",
        {"tree": [{"path": "docs/guide.md", "type": "blob", "size": 20}]},
    )
    github.json(
        "/repos/kevin/portfolio/contents/docs/guide.md",
        {"content": b64("# Guide\n\nHow to."), "encoding": "base64"},
    )


async def test_generate_from_recipe(github):
    _portfolio_routes(github)
    complete, requests = _counting_model()
    recipe = {
        "name": "Portfolio",
        "target_repo": "github-qa",
        "include_profile": False,
        "sources": [
            {"repo": "portfolio", "readme": True, "docs": ["docs/guide.md"]},
            {"repo": "gone", "readme": True, "docs": None},
        ],
    }

    with (
        patch(
            "server.jobs.qa_dataset.CorpusGitHubClient", return_value=github.client()
        ),
        patch("server.services.huggingface._api", return_value=_hub()),
    ):
        draft = await qa_dataset.generate_from_recipe(
            CREDS, recipe, model_ref="openai:m", complete=complete
        )

    # A bare repo name is completed with the token's account.
    assert draft.repo_id == "kevin/github-qa"
    assert {p.category for p in draft.dataset.pairs} == {"repo", "overview", "docs"}
    # One overview, one docs batch; then the grader, once per group of new
    # pairs (its answers here grade nothing: the pairs stay, ungraded).
    graded = [r for r in requests if r.system.startswith("You grade")]
    assert len(requests) - len(graded) == 2 and len(graded) == 2
    assert any(e.startswith("gone: ") for e in draft.dataset.errors)
    # Profile facts off: the account was never read.
    assert "/users/kevin" not in github.calls
    assert draft.stats()["removed"] == 0


async def test_an_empty_recipe_is_refused_before_anything_is_spent():
    with pytest.raises(JobError, match="selects nothing"):
        await qa_dataset.generate_from_recipe(
            CREDS,
            {"name": "x", "target_repo": "q", "include_profile": False, "sources": []},
        )


async def test_a_rejected_hub_token_stops_the_run_first(github):
    api = _hub()
    api.whoami.side_effect = RuntimeError("401")

    async def complete(_req):  # pragma: no cover — must never be reached
        raise AssertionError("generation started with a rejected HF token")

    with patch("server.services.huggingface._api", return_value=api):
        with pytest.raises(JobError, match="rejected your token"):
            await qa_dataset.generate_from_recipe(
                CREDS,
                {"name": "x", "target_repo": "kevin/q", "sources": [{"repo": "a"}]},
                complete=complete,
            )


# --- review edits -------------------------------------------------------------------


def _draft_dataset():
    old = QAPair("What is A?", "Old.", "overview", repo="a")
    new = QAPair("What is B?", "Model answer.", "docs", repo="a", grounding=0.9)
    held = QAPair("What is C?", "Far answer.", "docs", repo="a", grounding=0.1)
    for pair in (old, new, held):
        pair.id = pair_id(pair)
    return (
        QADataset(
            [old, new], 0, [], kept=1, new=1, review=[held], new_ids=[pair_id(new)]
        ),
        old,
        new,
        held,
    )


def test_an_edit_rewrites_a_new_pair_under_its_new_id():
    dataset, old, new, _ = _draft_dataset()

    reviewed = dataset.with_selection(
        edits={
            new.id: {"question": " What is B, really? ", "answer": "A better answer."}
        }
    )

    edited = [p for p in reviewed.pairs if p.answer == "A better answer."][0]
    assert edited.question == "What is B, really?"
    assert edited.grounding is None  # scored for the model's answer, not this one
    assert edited.id == pair_id(edited) != new.id
    assert reviewed.new_ids == [edited.id]
    assert old in reviewed.pairs


def test_edits_reach_promoted_pairs_but_never_kept_or_excluded_ones():
    dataset, old, new, held = _draft_dataset()
    rewrite = {"question": "Rewritten?", "answer": "Rewritten."}

    reviewed = dataset.with_selection(
        exclude=[new.id],
        promote=[held.id],
        edits={
            old.id: rewrite,
            new.id: rewrite,
            held.id: {"question": "C?", "answer": "Fixed."},
        },
    )

    answers = {p.answer for p in reviewed.pairs}
    assert answers == {"Old.", "Fixed."}
    assert reviewed.review == []
    assert len(reviewed.new_ids) == 1


def test_an_edit_that_duplicates_another_pair_keeps_one():
    dataset, old, new, _ = _draft_dataset()

    reviewed = dataset.with_selection(
        edits={new.id: {"question": old.question, "answer": "Same question."}}
    )

    # Same category? No: overview vs docs — distinct ids, both kept.
    assert len(reviewed.pairs) == 2
    twin = QADataset(
        [old, replace(old, answer="Other.", id="x")], 0, [], new_ids=["x"]
    ).with_selection(edits={"x": {"question": old.question, "answer": "Twin."}})
    assert [p.answer for p in twin.pairs] == ["Old."]
