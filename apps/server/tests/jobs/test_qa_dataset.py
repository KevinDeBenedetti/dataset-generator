import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from server.jobs import qa_dataset
from server.jobs.qa_dataset import (
    CompletionRequest,
    JobError,
    QAPair,
    QADataset,
    build_qa_dataset,
    dataset_card,
    dedupe_key,
    generate_pairs,
    pair_id,
    parse_pairs,
    profile_pairs,
    publish_qa_dataset,
    sanitize_pairs,
    to_jsonl,
)
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
    assert [op.path_in_repo for op in ops] == ["train.jsonl", "README.md"]


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
