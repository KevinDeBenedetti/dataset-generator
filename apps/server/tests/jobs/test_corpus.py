import json
from dataclasses import replace
from unittest.mock import MagicMock, patch

import pytest

from server.jobs import corpus
from server.jobs.corpus import (
    Chunk,
    JobError,
    RawFile,
    build_github_snapshot_chunks,
    build_knowledge_profile_chunks,
    chunk_file,
    doc_sections,
    export_corpus,
    is_code_indexable,
    language_for_path,
    parse_sources,
    push_corpus,
    split_markdown_sections,
    write_jsonl,
)
from server.jobs.github_snapshot import RepoDoc, deterministic_id
from server.tests.jobs.conftest import b64

# Golden output of the Go/TS builders: ids and text are both contractual.
GO_OUTPUT = [
    {
        "id": "2f2eed0b-e0f4-5a0b-a846-ae7df0d9a5d2",
        "content": "GitHub Profile: kevin\nName: Kevin De Benedetti\nBio: Dev\n"
        "Company: Acme\nLocation: Lyon\nGitHub URL: https://github.com/kevin\n"
        "Public repositories: 12\nFollowers: 34 | Following: 5",
        "source": "github",
        "type": "bio",
        "url": "https://github.com/kevin",
    },
    {
        "id": "874fd59d-032a-5082-ae0c-d7606f4f6ffa",
        "content": "Contact information for kevin:\nEmail: k@example.com\n"
        "Website/Blog: https://kevindb.dev\nTwitter: @kdb\nGitHub: https://github.com/kevin",
        "source": "github",
        "type": "contact",
        "url": "https://github.com/kevin",
    },
    {
        "id": "ae0fb955-0a8e-5f11-b3a9-6fa22e1dc8c8",
        "content": "GitHub Repository: portfolio\nDescription: My site\n"
        "Primary Language: Go\nTopics: go, next\nStars: 7\n"
        "Homepage: https://kevindb.dev\nURL: https://github.com/kevin/portfolio"
        "\n\nREADME:\n# Portfolio\nHello",
        "source": "github",
        "type": "readme",
        "repo": "https://github.com/kevin/portfolio",
        "url": "https://github.com/kevin/portfolio",
    },
]


def test_snapshot_chunks_match_go_output(snapshot):
    records = [c.to_record() for c in build_github_snapshot_chunks(snapshot)]
    assert records == GO_OUTPUT


def test_snapshot_chunks_omit_empty_fields(snapshot):
    profile = replace(
        snapshot.profile,
        name="",
        bio="",
        company="",
        location="",
        email="",
        blog="",
        twitter="",
    )
    overview, contact = build_github_snapshot_chunks(
        replace(snapshot, profile=profile, repos=[])
    )
    assert overview.content == (
        "GitHub Profile: kevin\nGitHub URL: https://github.com/kevin\n"
        "Public repositories: 12\nFollowers: 34 | Following: 5"
    )
    assert (
        contact.content
        == "Contact information for kevin:\nGitHub: https://github.com/kevin"
    )


def test_knowledge_profile_chunks(snapshot):
    overview, skills, project = build_knowledge_profile_chunks(snapshot)
    assert overview.to_record() == {
        "id": deterministic_id("profile:overview"),
        "content": "Portfolio owner: Kevin De Benedetti\nLocation: Lyon\n"
        "Website: https://kevindb.dev\nGitHub: https://github.com/kevin\nBio: Dev",
        "source": "profile",
        "type": "bio",
    }
    assert skills.content == (
        "Technologies and programming languages used by Kevin De Benedetti "
        "across their projects: Go, go, next"
    )
    assert project.content == (
        "Project: portfolio\nDescription: My site\nTechnologies: Go, go, next\n"
        "GitHub: https://github.com/kevin/portfolio\nURL: https://kevindb.dev\n"
        "Status: active"
    )
    assert project.id == deterministic_id("profile:project:portfolio")


def test_knowledge_profile_without_profile_or_skills(snapshot):
    repo = replace(snapshot.repos[0], language="", topics=[])
    chunks = build_knowledge_profile_chunks(
        replace(snapshot, profile=None, repos=[repo])
    )
    assert [c.type for c in chunks] == ["project"]


def test_write_jsonl_is_sorted_compact_and_utf8():
    chunks = [
        Chunk(id="b", content="é", source="s", type="t"),
        Chunk(id="a", content="x", source="s", type="t", path="p"),
    ]
    assert write_jsonl(chunks) == (
        '{"id":"a","content":"x","source":"s","type":"t","path":"p"}\n'
        '{"id":"b","content":"é","source":"s","type":"t"}\n'
    )
    assert write_jsonl([]) == ""


@pytest.mark.parametrize(
    "path,size,expected",
    [
        ("src/main.go", 10, True),
        ("docs/guide.md", 10, False),
        ("a/node_modules/x.js", 10, False),
        (".eslintrc.js", 10, False),
        ("bun.lock", 10, False),
        ("src/big.py", 200_000, False),
    ],
)
def test_is_code_indexable(path, size, expected):
    assert is_code_indexable(path, size) is expected


def test_language_for_path():
    assert language_for_path("Dockerfile.dev") == "Dockerfile"
    assert language_for_path("x/y.TSX") == "TypeScript"
    assert language_for_path("Makefile") == ""


def _raw(content: str, language: str = "Python") -> RawFile:
    return RawFile(
        repo="r", path="a.py", language=language, content=content, url="https://gh/a.py"
    )


def test_chunk_file_small_file_is_one_chunk():
    [chunk] = chunk_file(_raw("print(1)\n"), "kevin")
    assert chunk.content.startswith("// File: a.py (Python) lines 1-2\n")
    assert chunk.url == "https://gh/a.py#L1-L2"
    assert chunk.id == deterministic_id("github_code:kevin/r:a.py:1")


def test_chunk_file_splits_large_file_on_function_boundaries():
    lines = ["x = 1"] * 100 + ["", "def f():"] + ["    pass"] * 100
    chunks = chunk_file(_raw("\n".join(lines)), "kevin")
    assert [str(c.url).split("#")[1] for c in chunks] == [
        "L1-L101",
        "L102-L120",
        "L121-L202",
    ]


def test_chunk_file_truncates_long_chunks():
    [chunk] = chunk_file(_raw("y" * 5000), "kevin")
    assert chunk.content.endswith("\n// [truncated]")


def test_split_markdown_sections():
    sections = split_markdown_sections(
        "# Ops\n## Deploy\n### K8s\na\n## Monitoring\nb\n```bash\n# not a heading\n```"
    )
    assert [s.heading for s in sections] == ["Ops > Deploy > K8s", "Ops > Monitoring"]
    assert "# not a heading" in sections[1].body
    assert split_markdown_sections("intro\n\n## First")[0].heading == ""
    assert split_markdown_sections("") == []


def test_doc_sections_merge_short_and_cap_long():
    long_body = "\n\n".join(["p" * 900] * 3)
    doc = RepoDoc(path="docs/a.md", content=f"# A\nshort\n# B\nmore\n# C\n{long_body}")
    sections = doc_sections(doc)
    assert sections[0].body == "short\n\nB\nmore"
    assert [len(s.body) for s in sections[1:]] == [1802, 900]


def test_parse_sources():
    assert parse_sources("profile, github") == ["profile", "github"]
    with pytest.raises(JobError, match="unknown source"):
        parse_sources("profile,nope")
    with pytest.raises(JobError, match="at least one"):
        parse_sources(" , ")


def _fake_account(github):
    github.json("/users/kevin", {"login": "kevin", "name": "Kevin"})
    github.json(
        "/users/kevin/repos", [{"full_name": "kevin/a"}, {"full_name": "kevin/b"}]
    )
    for name in ("a", "b"):
        github.json(
            f"/repos/kevin/{name}",
            {
                "name": name,
                "html_url": f"https://github.com/kevin/{name}",
                "language": "Go",
            },
        )
        github.json(
            f"/repos/kevin/{name}/git/trees/main",
            {
                "tree": [
                    {"path": "docs/guide.md", "type": "blob", "size": 10},
                    {"path": "main.go", "type": "blob", "size": 10},
                ]
            },
        )
        github.json(
            f"/repos/kevin/{name}/contents/docs/guide.md",
            {"content": b64("# Guide\n" + "text " * 30), "encoding": "base64"},
        )
        github.json(
            f"/repos/kevin/{name}/contents/main.go",
            {"content": b64("package main"), "encoding": "base64"},
        )


async def test_export_corpus_writes_splits_manifest_and_card(github, tmp_path):
    _fake_account(github)
    with (
        patch.object(corpus, "CorpusGitHubClient", return_value=github.client()),
        patch.dict(corpus.MIN_RECORDS, {"github_code": 1, "github_docs": 1}),
    ):
        manifest = await export_corpus(
            tmp_path,
            ["profile", "github", "github_code", "github_docs"],
            "kevin",
            "t",
            "ns/kb",
        )

    assert [(f["source"], f["records"]) for f in manifest["files"]] == [
        ("github", 4),
        ("github_code", 2),
        ("github_docs", 2),
        ("profile", 4),
    ]
    assert manifest["generated_at"].endswith("Z")
    on_disk = json.loads((tmp_path / "manifest.json").read_text())
    assert on_disk["files"] == manifest["files"]
    code = (tmp_path / "data/github_code.jsonl").read_text().splitlines()
    assert json.loads(code[0])["language"] == "Go"
    card = (tmp_path / "README.md").read_text()
    assert "config_name: github_docs" in card and "- Repository: `ns/kb`" in card


async def test_export_refuses_truncated_split(github, tmp_path):
    _fake_account(github)
    with patch.object(corpus, "CorpusGitHubClient", return_value=github.client()):
        with pytest.raises(JobError, match='"github_code" produced only 2 chunks'):
            await export_corpus(tmp_path, ["github_code"], "kevin", "t")
    assert not (tmp_path / "manifest.json").exists()


def test_push_requires_a_complete_export(tmp_path):
    with pytest.raises(JobError, match="does not exist"):
        push_corpus(tmp_path / "missing", "ns/kb")
    with pytest.raises(JobError, match="no manifest.json"):
        push_corpus(tmp_path, "ns/kb")


def test_push_uploads_one_commit_to_a_private_repo(tmp_path):
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {"files": [{"source": "profile", "records": 3, "path": "data/p.jsonl"}]}
        )
    )
    api = MagicMock()
    api.whoami.return_value = {"name": "kevin"}
    api.repo_info.return_value = MagicMock(private=True)
    with patch("server.services.huggingface._api", return_value=api):
        url = push_corpus(tmp_path, "ns/kb", "abcdef1234")

    assert url == "https://huggingface.co/datasets/ns/kb"
    api.create_repo.assert_called_once_with(
        "ns/kb", repo_type="dataset", private=True, exist_ok=True
    )
    kwargs = api.upload_folder.call_args.kwargs
    assert kwargs["commit_message"] == "Weekly corpus refresh (abcdef1)"
    assert "- profile: 3 records (data/p.jsonl)" in kwargs["commit_description"]


def test_push_rejects_bad_token(tmp_path):
    (tmp_path / "manifest.json").write_text("{}")
    api = MagicMock()
    api.whoami.side_effect = RuntimeError("401")
    with patch("server.services.huggingface._api", return_value=api):
        with pytest.raises(JobError, match="HF_TOKEN rejected"):
            push_corpus(tmp_path, "ns/kb")
    api.upload_folder.assert_not_called()


def test_main_reports_missing_env(monkeypatch, capsys):
    monkeypatch.delenv("GITHUB_USERNAME", raising=False)
    assert corpus.main(["export"]) == 1
    assert "GITHUB_USERNAME is required" in capsys.readouterr().err


def test_push_completes_a_bare_repo_name(tmp_path):
    (tmp_path / "manifest.json").write_text(json.dumps({"files": []}))
    api = MagicMock()
    api.whoami.return_value = {"name": "kevin"}
    api.repo_info.return_value = MagicMock(private=True)
    with patch("server.services.huggingface._api", return_value=api):
        url = push_corpus(tmp_path, "kb")

    # The bare name would 404 on commit: it is pushed to <account>/kb.
    assert url == "https://huggingface.co/datasets/kevin/kb"
    assert api.create_repo.call_args.args[0] == "kevin/kb"
    assert api.upload_folder.call_args.kwargs["repo_id"] == "kevin/kb"
