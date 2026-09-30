import json
import re
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from huggingface_hub.errors import EntryNotFoundError, RepositoryNotFoundError

from server.jobs import qa_dataset
from server.jobs.qa_dataset import (
    CompletionRequest,
    JobError,
    PreviousState,
    QAPair,
    QADataset,
    build_qa_dataset,
    dataset_card,
    dedupe_key,
    generate_pairs,
    load_previous_state,
    pair_id,
    parse_pairs,
    profile_pairs,
    publish_qa_dataset,
    sanitize_pairs,
    to_jsonl,
)
from server.jobs.github_snapshot import RepoData
from server.tests.fake_embedder import FakeEmbedder
from server.tests.jobs.conftest import b64


def test_profile_pairs(snapshot):
    pairs = profile_pairs(snapshot.profile, 4)
    assert pairs[0].answer == "@kevin"
    assert pairs[1].answer == "4 (excluding forks and archived repositories)"
    assert {p.category for p in pairs} == {"profile"}
    assert pairs[-1].answer == "34 followers, 5 following"
    assert len(pairs) == 8
    assert profile_pairs(None, 1) == []


@pytest.mark.parametrize(
    "raw",
    [
        '[{"question":"What is X?","answer":"A tool."}]',
        '```json\n[{"question":"What is X?","answer":"A tool."}]\n```',
        'Sure! [{"question":"What is X?","answer":"A tool."}] Hope it helps.',
        # Cut off by max tokens: the complete first object is salvaged.
        '[{"question":"What is X?","answer":"A tool."},{"question":"Wh',
    ],
)
def test_parse_pairs_tolerates_formatting_slips(raw):
    [pair] = parse_pairs(raw, "repo", "overview", "m")
    assert (pair.question, pair.answer, pair.repo, pair.model) == (
        "What is X?",
        "A tool.",
        "repo",
        "m",
    )


def test_parse_pairs_skips_invalid_items():
    raw = '[{"question":"Q?"},{"question":" ","answer":"a"},"x",{"question":"Ok q?","answer":"yes"}]'
    assert [p.question for p in parse_pairs(raw, "r", "docs", "m")] == ["Ok q?"]
    assert parse_pairs("no json at all", "r", "docs", "m") == []


async def test_generate_pairs_retries_empty_then_unparseable():
    responses = iter(["", "garbage", "", '[{"question":"Why X?","answer":"Because."}]'])

    async def complete(_req):
        return next(responses)

    req = CompletionRequest(system="s", user="u", max_tokens=10)
    pairs = await generate_pairs(complete, req, "r", "overview", "m")
    assert [p.answer for p in pairs] == ["Because."]


async def test_generate_pairs_gives_up_after_retry():
    async def complete(_req):
        return "nope"

    with pytest.raises(JobError, match="no usable pairs"):
        await generate_pairs(
            complete, CompletionRequest("s", "u", 1), "r", "overview", "m"
        )


def test_sanitize_drops_trivial_and_duplicate_pairs():
    pairs = [
        QAPair("What is Élan?", "A framework.", "overview", "r"),
        QAPair("what is elan", "Duplicate.", "overview", "r"),
        QAPair("Short?", "x", "overview", "r"),
        QAPair("Echo question", "echo question!", "overview", "r"),
    ]
    clean, dropped = sanitize_pairs(pairs)
    assert [p.question for p in clean] == ["What is Élan?"]
    assert dropped == 3
    assert clean[0].id == pair_id(clean[0]) and len(clean[0].id) == 12


def test_dedupe_key():
    assert dedupe_key("  Où est-ce_déployé ?") == "ou est ce deploye"


def test_to_jsonl_record_shape():
    pair = QAPair("Q one?", "A", "overview", repo="r", model="m", id="b")
    profile = QAPair("Q two?", "B", "profile", id="a")
    lines = to_jsonl([pair, profile]).splitlines()
    assert (
        lines[0]
        == '{"question":"Q two?","answer":"B","source":"github","category":"profile","id":"a"}'
    )
    assert json.loads(lines[1])["repo"] == "r"


def _repo_routes(github):
    github.json("/repos/kevin/portfolio", {"default_branch": "main"})
    github.json(
        "/repos/kevin/portfolio/git/trees/main",
        {
            "tree": [
                {"path": f"docs/{i}.md", "type": "blob", "size": 10} for i in range(4)
            ]
        },
    )
    for i in range(4):
        github.json(
            f"/repos/kevin/portfolio/contents/docs/{i}.md",
            {"content": b64(f"doc {i}"), "encoding": "base64"},
        )


async def test_build_qa_dataset_runs_overview_and_doc_batches(github, snapshot):
    _repo_routes(github)
    requests = []

    async def complete(req: CompletionRequest) -> str:
        requests.append(req)
        n = len(requests)
        if n == 3:
            return "broken"
        return json.dumps(
            [{"question": f"Question number {n}?", "answer": f"Answer {n}."}]
        )

    dataset = await build_qa_dataset(github.client(), snapshot, complete, "claude-x")

    # overview + 2 docs batches (3 + 1 files); the second batch got retried once.
    assert "Generate 3 distinct" in requests[0].user
    assert "Generate 6 distinct" in requests[1].user
    assert "Generate 2 distinct" in requests[-1].user
    categories = [p.category for p in dataset.pairs]
    assert categories.count("profile") == 8
    assert categories.count("overview") == 1
    assert categories.count("docs") == 2
    assert dataset.errors == []
    assert {p.model for p in dataset.pairs if p.category != "profile"} == {"claude-x"}


async def test_build_qa_dataset_records_failed_repos(github, snapshot):
    async def complete(_req):
        return ""

    dataset = await build_qa_dataset(github.client(), snapshot, complete, "m")
    assert dataset.errors == [
        "portfolio (overview): LLM returned no usable pairs (empty or unparseable) after retry"
    ]
    assert {p.category for p in dataset.pairs} == {"profile"}


def test_dataset_card():
    pairs = [
        QAPair("Q one?", "A", "overview", repo="r", model="m"),
        QAPair("Q two?", "B", "profile"),
    ]
    card = dataset_card(
        QADataset(pairs, 2, ["r (docs 1): boom"]), "kevin", "other", "https://l"
    )
    assert card.startswith(
        "---\nlanguage:\n- en\nlicense: other\nlicense_link: https://l\n"
    )
    assert "- n<1K" in card
    assert "| [r](https://github.com/kevin/r) | 1 |" in card
    assert "(2 low-quality/duplicate pair(s) dropped before export)" in card
    assert "- r (docs 1): boom" in card
    assert "generated by `m`" in card


def test_publish_commits_both_files_to_private_repo(snapshot):
    api = MagicMock()
    api.repo_info.return_value = MagicMock(private=True)
    pairs, _ = sanitize_pairs(profile_pairs(snapshot.profile, 1))
    with patch("server.services.huggingface._api", return_value=api):
        result = publish_qa_dataset(QADataset(pairs, 0, []), "kevin", "ns/qa")

    assert result == {
        "repo": "ns/qa",
        "url": "https://huggingface.co/datasets/ns/qa",
        "records": 8,
        "dropped": 0,
    }
    ops = api.create_commit.call_args.kwargs["operations"]
    assert [op.path_in_repo for op in ops] == [
        "train.jsonl",
        "review.jsonl",
        "manifest.json",
        "README.md",
    ]


def test_publish_refuses_empty_dataset():
    with pytest.raises(JobError, match="0 pairs"):
        publish_qa_dataset(QADataset([], 0, []), "kevin", "ns/qa")


async def test_run_checks_hf_token_before_generating(monkeypatch):
    monkeypatch.setenv("GITHUB_USERNAME", "kevin")
    monkeypatch.setenv("HF_TOKEN", "hf")
    monkeypatch.setenv("HF_QA_DATASET_REPO", "ns/qa")
    api = MagicMock()
    api.whoami.side_effect = RuntimeError("401")

    async def complete(_req):  # pragma: no cover — must never be reached
        raise AssertionError("generation started with a rejected HF token")

    with patch("server.services.huggingface._api", return_value=api):
        with pytest.raises(JobError, match="HF_TOKEN rejected"):
            await qa_dataset.run(complete)


async def test_run_requires_claude_credentials(monkeypatch):
    monkeypatch.setenv("GITHUB_USERNAME", "kevin")
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(JobError, match="CLAUDE_CODE_OAUTH_TOKEN"):
        await qa_dataset.run()


async def test_run_dry_run_skips_hf_checks_and_publish(monkeypatch, github):
    monkeypatch.setenv("GITHUB_USERNAME", "kevin")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "ak")
    # No HF_TOKEN / HF_QA_DATASET_REPO at all — a dry run needs neither.
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.delenv("HF_QA_DATASET_REPO", raising=False)
    github.json("/users/kevin", {"login": "kevin", "name": "Kevin"})
    github.json("/users/kevin/repos", [])

    async def complete(_req):  # pragma: no cover — no repos to generate for
        raise AssertionError("unexpected LLM call")

    with patch(
        "server.jobs.qa_dataset.CorpusGitHubClient", return_value=github.client()
    ):
        result = await qa_dataset.run(complete, dry_run=True)

    assert result["dry_run"] is True
    assert result["url"] is None
    # Deterministic profile pairs only (username, indexed-repo count, followers).
    assert result["records"] == 3


async def test_run_passes_max_repos_to_build_qa_dataset(monkeypatch, github):
    monkeypatch.setenv("GITHUB_USERNAME", "kevin")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "ak")
    monkeypatch.setenv("HF_TOKEN", "hf")
    monkeypatch.setenv("HF_QA_DATASET_REPO", "ns/qa")
    github.json("/users/kevin", {"login": "kevin", "name": "Kevin"})
    github.json("/users/kevin/repos", [])
    api = MagicMock()
    api.whoami.return_value = {"name": "kevin"}
    # First publish: nothing on the Hub yet.
    api.hf_hub_download.side_effect = EntryNotFoundError("missing")

    async def complete(_req):  # pragma: no cover
        raise AssertionError("unexpected LLM call")

    with (
        patch(
            "server.jobs.qa_dataset.CorpusGitHubClient", return_value=github.client()
        ),
        patch("server.services.huggingface._api", return_value=api),
        patch(
            "server.jobs.qa_dataset.build_qa_dataset",
            new=AsyncMock(return_value=QADataset([], 0, [])),
        ) as build,
    ):
        with pytest.raises(JobError, match="0 pairs"):
            await qa_dataset.run(complete, max_repos=2, dry_run=False)

    assert build.call_args.args[-1] == 2


def test_parse_pairs_reads_and_clamps_confidence():
    raw = json.dumps(
        [
            {"question": "What is X?", "answer": "A tool.", "confidence": 0.87},
            {"question": "Why use X?", "answer": "It is fast.", "confidence": 3},
            {"question": "Who made X?", "answer": "Kevin.", "confidence": "n/a"},
            {"question": "When was X made?", "answer": "In 2026."},
        ]
    )
    pairs = parse_pairs(raw, "r", "overview", "m")
    assert [p.confidence for p in pairs] == [0.87, 1.0, None, None]


def test_profile_pairs_are_fully_confident(snapshot):
    assert {p.confidence for p in profile_pairs(snapshot.profile, 1)} == {1.0}


def test_to_record_includes_confidence_only_when_set():
    scored = QAPair("Q one?", "A", "overview", repo="r", confidence=0.9, id="a")
    unscored = QAPair("Q two?", "B", "overview", repo="r", id="b")
    assert list(scored.to_record()) == [
        "question",
        "answer",
        "source",
        "category",
        "repo",
        "confidence",
        "id",
    ]
    assert "confidence" not in unscored.to_record()


# --- Incremental runs ---------------------------------------------------------

DOCS = {
    "docs/setup.md": "Setup installs dependencies with uv sync and starts postgres locally.",
    "docs/deploy.md": "Deploy pushes the docker image to the registry and restarts the stack.",
    "docs/testing.md": "Testing runs pytest against a throwaway postgres container.",
    "docs/release.md": "Release uses release-please to tag versions and write the changelog.",
}


def _docs_routes(github, docs):
    github.json("/repos/kevin/portfolio", {"default_branch": "main"})
    github.json(
        "/repos/kevin/portfolio/git/trees/main",
        {"tree": [{"path": p, "type": "blob", "size": 10} for p in docs]},
    )
    for path, content in docs.items():
        github.json(
            f"/repos/kevin/portfolio/contents/{path}",
            {"content": b64(content), "encoding": "base64"},
        )


def _echo(requests, override=None):
    """Completion answering each doc with a pair drawn from that doc's text."""

    async def complete(req: CompletionRequest) -> str:
        requests.append(req)
        if override is not None:
            forced = override(req)
            if forced is not None:
                return forced
        docs = re.findall(r"### (\S+)\n([^\n]+)", req.user)
        if docs:
            return json.dumps(
                [
                    {"question": f"What does {path} cover?", "answer": content}
                    for path, content in docs
                ]
            )
        return json.dumps(
            [
                {
                    "question": "What is the portfolio repository?",
                    "answer": "Portfolio is my site, written in Go.",
                }
            ]
        )

    return complete


def _published(dataset):
    """What the next run reads back from the Hub."""
    lines = to_jsonl(dataset.pairs).splitlines()
    pairs = [QAPair.from_record(json.loads(line)) for line in lines]
    return PreviousState([p for p in pairs if p], dataset.manifest["sources"])


async def _first_version(github, snapshot, docs=DOCS):
    _docs_routes(github, docs)
    dataset = await build_qa_dataset(
        github.client(), snapshot, _echo([]), "m", embedder=FakeEmbedder()
    )
    return _published(dataset)


async def _next_version(github, snapshot, previous, docs=DOCS, override=None):
    _docs_routes(github, docs)
    requests = []
    dataset = await build_qa_dataset(
        github.client(),
        snapshot,
        _echo(requests, override),
        "m",
        previous=previous,
        embedder=FakeEmbedder(),
    )
    return dataset, requests


def _questions(dataset):
    return {p.question for p in dataset.pairs if p.category != "profile"}


async def test_first_run_records_sources_and_manifest(github, snapshot):
    previous = await _first_version(github, snapshot)
    assert set(previous.sources) == {"portfolio::overview"} | {
        f"portfolio::{p}" for p in DOCS
    }
    docs_pair = next(
        p for p in previous.pairs if p.question == "What does docs/deploy.md cover?"
    )
    # Batched with setup/testing: its sources are the whole batch.
    assert docs_pair.sources == [
        "portfolio::docs/setup.md",
        "portfolio::docs/deploy.md",
        "portfolio::docs/testing.md",
    ]
    assert docs_pair.grounding is not None


async def test_unchanged_sources_make_no_llm_call(github, snapshot):
    previous = await _first_version(github, snapshot)
    dataset, requests = await _next_version(github, snapshot, previous)
    assert requests == []
    assert _questions(dataset) == {
        p.question for p in previous.pairs if p.category != "profile"
    }
    assert (dataset.kept, dataset.new) == (5, 0)
    assert dataset.manifest["sources"] == previous.sources


async def test_changed_doc_is_regenerated_with_avoid_list(github, snapshot):
    previous = await _first_version(github, snapshot)
    docs = {
        **DOCS,
        "docs/release.md": "Release now publishes the changelog to GitHub releases with release-please.",
    }
    dataset, requests = await _next_version(github, snapshot, previous, docs)

    [req] = requests  # only the changed doc, alone in its batch
    assert "### docs/release.md" in req.user and "docs/setup.md" not in req.user
    assert "do NOT ask them again" in req.user
    assert "What does docs/release.md cover?" in req.user
    # Old pair re-checked against the new text (still grounded) and kept; the
    # regenerated one repeats its question, so it is dropped as a duplicate.
    assert "What does docs/release.md cover?" in _questions(dataset)
    assert dataset.new == 0 and dataset.dropped == 1
    assert (
        dataset.manifest["sources"]["portfolio::docs/release.md"]
        != previous.sources["portfolio::docs/release.md"]
    )


async def test_rephrasing_is_rejected_semantically(github, snapshot):
    previous = await _first_version(github, snapshot)
    docs = {**DOCS, "docs/release.md": DOCS["docs/release.md"] + " It runs on main."}

    def rephrase(req):
        return json.dumps(
            [
                {
                    "question": "What does the docs/release.md file cover",
                    "answer": docs["docs/release.md"],
                },
                {
                    "question": "Which tool tags versions and writes the changelog?",
                    "answer": "release-please tags versions and writes the changelog.",
                },
            ]
        )

    dataset, _ = await _next_version(github, snapshot, previous, docs, rephrase)
    assert dataset.semantic_duplicates == 1
    assert "What does the docs/release.md file cover" not in _questions(dataset)
    assert "Which tool tags versions and writes the changelog?" in _questions(dataset)
    assert dataset.new == 1


async def test_ungrounded_answer_goes_to_review(github, snapshot):
    previous = await _first_version(github, snapshot)
    docs = {**DOCS, "docs/release.md": DOCS["docs/release.md"] + " It runs on main."}

    def hallucinate(req):
        return json.dumps(
            [
                {
                    "question": "Who sponsors the project financially?",
                    "answer": "A Swiss bank since 1998.",
                }
            ]
        )

    dataset, _ = await _next_version(github, snapshot, previous, docs, hallucinate)
    assert [p.question for p in dataset.review] == [
        "Who sponsors the project financially?"
    ]
    assert "Who sponsors the project financially?" not in _questions(dataset)
    assert dataset.review[0].grounding < 0.35


async def test_changed_source_drops_old_pairs_no_longer_grounded(github, snapshot):
    previous = await _first_version(github, snapshot)
    docs = {
        **DOCS,
        "docs/release.md": "Versioning is manual: bump pyproject then push a git tag.",
    }
    dataset, _ = await _next_version(github, snapshot, previous, docs)
    assert [p.question for p in dataset.review] == ["What does docs/release.md cover?"]
    assert dataset.new == 1  # regenerated from the new text


async def test_removed_doc_drops_its_pairs(github, snapshot):
    previous = await _first_version(github, snapshot)
    docs = {k: v for k, v in DOCS.items() if k != "docs/release.md"}
    dataset, requests = await _next_version(github, snapshot, previous, docs)
    assert requests == []
    assert "What does docs/release.md cover?" not in _questions(dataset)
    assert "portfolio::docs/release.md" not in dataset.manifest["sources"]


async def test_failed_call_keeps_previous_hash(github, snapshot):
    previous = await _first_version(github, snapshot)
    docs = {**DOCS, "docs/release.md": DOCS["docs/release.md"] + " It runs on main."}
    dataset, _ = await _next_version(github, snapshot, previous, docs, lambda req: "")
    assert dataset.errors == [
        "portfolio (docs 1): LLM returned no usable pairs (empty or unparseable) after retry"
    ]
    key = "portfolio::docs/release.md"
    assert dataset.manifest["sources"][key] == previous.sources[key]


async def test_repos_outside_the_run_are_carried_over_and_gone_ones_dropped(
    github, snapshot
):
    snapshot.repos.append(RepoData(name="side", description="Side project", stars=1))
    previous = await _first_version(github, snapshot)
    previous.pairs += [
        QAPair(
            "What is side about?",
            "A side project.",
            "overview",
            repo="side",
            sources=["side::overview"],
        ),
        QAPair(
            "What was gone about?",
            "Deleted.",
            "overview",
            repo="gone",
            sources=["gone::overview"],
        ),
    ]
    previous.sources.update({"side::overview": "h1", "gone::overview": "h2"})

    _docs_routes(github, DOCS)
    dataset = await build_qa_dataset(
        github.client(),
        snapshot,
        _echo([]),
        "m",
        1,
        previous=previous,
        embedder=FakeEmbedder(),
    )
    assert "What is side about?" in _questions(dataset)
    assert "What was gone about?" not in _questions(dataset)
    assert dataset.manifest["sources"]["side::overview"] == "h1"
    assert "gone::overview" not in dataset.manifest["sources"]


async def test_legacy_pairs_without_sources_are_rechecked_not_dropped(github, snapshot):
    legacy = PreviousState(
        [
            QAPair(
                "What is the portfolio repository?",
                "Portfolio is my site, written in Go.",
                "overview",
                repo="portfolio",
            ),
            QAPair(
                "What does docs/setup.md cover?",
                DOCS["docs/setup.md"],
                "docs",
                repo="portfolio",
            ),
        ],
        {},
    )
    dataset, requests = await _next_version(github, snapshot, legacy)
    assert {
        "What is the portfolio repository?",
        "What does docs/setup.md cover?",
    } <= _questions(dataset)
    # No manifest: every source counts as changed and is regenerated once.
    assert len(requests) == 3
    legacy_docs_pair = next(
        p for p in dataset.pairs if p.question == "What does docs/setup.md cover?"
    )
    assert "portfolio::docs/setup.md" in legacy_docs_pair.sources


def test_load_previous_state(tmp_path):
    train = tmp_path / "train.jsonl"
    train.write_text(
        to_jsonl(
            [
                QAPair(
                    "Q one?",
                    "A",
                    "overview",
                    repo="r",
                    id="a",
                    sources=["r::overview"],
                    grounding=0.7,
                )
            ]
        )
        + "not json\n"
    )
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"sources": {"r::overview": "abc"}}))
    api = MagicMock()
    api.hf_hub_download.side_effect = lambda filename, **_: str(tmp_path / filename)

    state = load_previous_state(api, "ns/qa")
    [pair] = state.pairs
    assert (pair.sources, pair.grounding) == (["r::overview"], 0.7)
    assert state.sources == {"r::overview": "abc"}


def test_load_previous_state_first_run_and_errors():
    api = MagicMock()
    api.hf_hub_download.side_effect = RepositoryNotFoundError(
        "no repo", response=MagicMock()
    )
    assert load_previous_state(api, "ns/qa") == PreviousState()

    api.hf_hub_download.side_effect = RuntimeError("hub down")
    with pytest.raises(JobError, match="full_refresh"):
        load_previous_state(api, "ns/qa")


async def test_run_full_refresh_skips_previous_version(monkeypatch, github):
    monkeypatch.setenv("GITHUB_USERNAME", "kevin")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "ak")
    monkeypatch.setenv("HF_TOKEN", "hf")
    monkeypatch.setenv("HF_QA_DATASET_REPO", "ns/qa")
    github.json("/users/kevin", {"login": "kevin", "name": "Kevin"})
    github.json("/users/kevin/repos", [])

    def must_not_load(*_):  # pragma: no cover
        raise AssertionError("previous version read on a full refresh")

    monkeypatch.setattr(qa_dataset, "load_previous_state", must_not_load)
    with patch(
        "server.jobs.qa_dataset.CorpusGitHubClient", return_value=github.client()
    ):
        result = await qa_dataset.run(_echo([]), dry_run=True, full_refresh=True)
    assert result["full_refresh"] is True
    assert (result["kept"], result["new"], result["review"]) == (0, 0, 0)


def test_card_mentions_incremental_stats_and_review():
    pairs = [QAPair("Q one?", "A", "overview", repo="r", model="m")]
    dataset = QADataset(
        pairs,
        0,
        [],
        kept=1,
        new=0,
        semantic_duplicates=2,
        review=[QAPair("Q two?", "B", "docs", repo="r")],
        manifest={"embedding_model": "mini", "sources": {}},
    )
    card = dataset_card(dataset, "kevin")
    assert "1 pair(s) carried over from unchanged sources, 0 newly generated" in card
    assert "embedding similarity (`mini`, 2 rephrasing(s)" in card
    assert "1 pair(s) held out in `review.jsonl`" in card


async def test_every_public_repo_is_processed_by_default(github, snapshot):
    # More repos than the old 15-repo cap: none may be left out.
    snapshot.repos = [
        RepoData(name=f"repo{i}", description=f"Project number {i}", stars=i)
        for i in range(20)
    ]
    seen = []

    async def complete(req: CompletionRequest) -> str:
        match = re.search(r"Repository: (\S+)", req.user)
        assert match is not None
        repo = match.group(1)
        seen.append(repo)
        return json.dumps(
            [{"question": f"What is {repo} about?", "answer": f"{repo} is a project."}]
        )

    dataset = await build_qa_dataset(github.client(), snapshot, complete, "m")
    assert sorted(seen) == sorted(f"repo{i}" for i in range(20))
    assert dataset.new == 20

    # max_repos still trims to the most-starred, for a cheap test run.
    seen.clear()
    await build_qa_dataset(github.client(), snapshot, complete, "m", 2)
    assert sorted(seen) == ["repo18", "repo19"]


# --- Drafts ---------------------------------------------------------------------


def _draft_dataset():
    pairs = [
        QAPair(
            "Kept one?", "K.", "overview", repo="r", id="k1", sources=["r::overview"]
        ),
        QAPair("New one?", "N1.", "docs", repo="r", id="n1", grounding=0.6),
        QAPair("New two?", "N2.", "docs", repo="r", id="n2"),
    ]
    review = [QAPair("Held?", "H.", "docs", repo="r", id="h1", grounding=0.1)]
    return QADataset(
        pairs,
        1,
        ["r (docs 1): boom"],
        kept=1,
        new=2,
        semantic_duplicates=3,
        review=review,
        manifest={"sources": {"r::overview": "abc"}},
        new_ids=["n1", "n2"],
    )


def test_draft_round_trips_through_json():
    dataset = _draft_dataset()
    restored = QADataset.from_dict(json.loads(json.dumps(dataset.to_dict())))
    assert [p.to_record() for p in restored.pairs] == [
        p.to_record() for p in dataset.pairs
    ]
    assert restored.review[0].grounding == 0.1
    assert (restored.kept, restored.new, restored.semantic_duplicates) == (1, 2, 3)
    assert restored.manifest == dataset.manifest and restored.new_ids == ["n1", "n2"]


def test_with_selection_excludes_and_promotes():
    selected = _draft_dataset().with_selection(exclude=["n2", "k1"], promote=["h1"])
    # Only *new* pairs can be excluded; carried-over ones stay.
    assert [p.id for p in selected.pairs] == ["k1", "n1", "h1"]
    assert selected.review == [] and selected.new == 2
    assert selected.new_ids == ["n1", "h1"]


async def test_build_reports_progress(github, snapshot):
    _repo_routes(github)
    progress = []

    async def complete(req):
        return json.dumps([{"question": "Some question here?", "answer": "An answer."}])

    await build_qa_dataset(
        github.client(),
        snapshot,
        complete,
        "m",
        on_progress=lambda *a: progress.append(a),
    )
    assert progress == [(0, 1, ""), (1, 1, "portfolio")]


async def test_generate_without_hub_is_a_full_run(monkeypatch, github):
    monkeypatch.setenv("GITHUB_USERNAME", "kevin")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "ak")
    monkeypatch.delenv("HF_TOKEN", raising=False)
    github.json("/users/kevin", {"login": "kevin", "name": "Kevin"})
    github.json("/users/kevin/repos", [])

    async def complete(_req):  # pragma: no cover — no repos
        raise AssertionError("unexpected LLM call")

    with patch(
        "server.jobs.qa_dataset.CorpusGitHubClient", return_value=github.client()
    ):
        draft = await qa_dataset.generate(complete, require_hub=False)
    assert draft.username == "kevin" and len(draft.dataset.pairs) == 3
    assert draft.stats()["records"] == 3


async def test_generate_requires_the_hub_by_default(monkeypatch):
    monkeypatch.setenv("GITHUB_USERNAME", "kevin")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "ak")
    monkeypatch.delenv("HF_TOKEN", raising=False)
    with pytest.raises(JobError, match="HF_TOKEN"):
        await qa_dataset.generate(AsyncMock())


async def test_publish_requires_a_repo():
    draft = qa_dataset.Draft(_draft_dataset(), "kevin", "", False, "m")
    with pytest.raises(JobError, match="HF_QA_DATASET_REPO"):
        await qa_dataset.publish(draft)


def test_publish_completes_a_bare_repo_name(snapshot):
    # HF_QA_DATASET_REPO=github-personal (no namespace) 404'd on the commit.
    api = MagicMock()
    api.whoami.return_value = {"name": "kevin"}
    api.repo_info.return_value = MagicMock(private=True)
    pairs, _ = sanitize_pairs(profile_pairs(snapshot.profile, 1))
    with patch("server.services.huggingface._api", return_value=api):
        result = publish_qa_dataset(QADataset(pairs, 0, []), "kevin", "github-personal")

    assert result["repo"] == "kevin/github-personal"
    assert result["url"] == "https://huggingface.co/datasets/kevin/github-personal"
    assert api.create_repo.call_args.args[0] == "kevin/github-personal"
    assert api.create_commit.call_args.kwargs["repo_id"] == "kevin/github-personal"


async def test_generate_reads_the_previous_version_from_the_full_repo_id(
    monkeypatch, github
):
    monkeypatch.setenv("GITHUB_USERNAME", "kevin")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "ak")
    monkeypatch.setenv("HF_TOKEN", "hf")
    monkeypatch.setenv("HF_QA_DATASET_REPO", "github-personal")
    github.json("/users/kevin", {"login": "kevin", "name": "Kevin"})
    github.json("/users/kevin/repos", [])
    api = MagicMock()
    api.whoami.return_value = {"name": "kevin"}
    api.hf_hub_download.side_effect = EntryNotFoundError("missing")

    async def complete(_req):  # pragma: no cover — no repos
        raise AssertionError("unexpected LLM call")

    with (
        patch(
            "server.jobs.qa_dataset.CorpusGitHubClient", return_value=github.client()
        ),
        patch("server.services.huggingface._api", return_value=api),
    ):
        draft = await qa_dataset.generate(complete)

    # Otherwise the bare name 404s and is silently treated as a first run.
    assert draft.repo_id == "kevin/github-personal"
    assert api.hf_hub_download.call_args.kwargs["repo_id"] == "kevin/github-personal"
