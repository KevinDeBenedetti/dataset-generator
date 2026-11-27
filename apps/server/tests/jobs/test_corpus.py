import hashlib
import json
from dataclasses import replace
from unittest.mock import MagicMock, patch

import pytest

from server.jobs import corpus
from server.jobs.corpus import (
    SCHEMA_VERSION,
    Chunk,
    CorpusMoved,
    JobError,
    RawFile,
    build_github_snapshot_chunks,
    build_knowledge_profile_chunks,
    chunk_file,
    doc_sections,
    export_corpus,
    is_code_indexable,
    language_for_path,
    push_corpus,
    split_markdown_sections,
    write_jsonl,
)
from server.jobs.github_snapshot import RepoDoc, deterministic_id
from server.tests.creds import make_creds
from server.tests.jobs.conftest import b64

CREDS = make_creds(hf_token="hf_000000000000")

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
        # The name, not the URL: the only field that departs from the Go output.
        "repo": "portfolio",
        "url": "https://github.com/kevin/portfolio",
    },
]


def test_snapshot_chunks_match_go_output(snapshot):
    records = [c.to_record() for c in build_github_snapshot_chunks(snapshot)]
    # Schema 2 adds only the content hash: ids and text are unchanged.
    assert records == [
        {**r, "content_hash": hashlib.sha256(r["content"].encode()).hexdigest()}
        for r in GO_OUTPUT
    ]


def test_readme_is_split_into_sections_after_the_card(snapshot):
    readme = (
        "# Portfolio\n"
        + "Hello, this is my site. " * 5
        + "\n\n## Install\n"
        + "Run bun install. " * 10
        + "\n\n## Deploy\n"
        + "Push to main. " * 10
    )
    repo = replace(snapshot.repos[0], readme="capped", readme_full=readme)
    card, install, deploy = build_github_snapshot_chunks(
        replace(snapshot, profile=None, repos=[repo])
    )
    assert card.content.endswith(
        "README:\n# Portfolio\n" + ("Hello, this is my site. " * 5).strip()
    )
    assert card.id == deterministic_id("github:repo:https://github.com/kevin/portfolio")
    assert install.content.startswith("# portfolio README — Portfolio > Install\n\n")
    assert install.id == deterministic_id(
        "github:readme:https://github.com/kevin/portfolio:Portfolio > Install"
    )
    assert {install.type, deploy.type, install.repo} == {"readme", "portfolio"}


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
    content = (
        "Portfolio owner: Kevin De Benedetti\nLocation: Lyon\n"
        "Website: https://kevindb.dev\nGitHub: https://github.com/kevin\nBio: Dev"
    )
    assert overview.to_record() == {
        "id": deterministic_id("profile:overview"),
        "content": content,
        "source": "profile",
        "type": "bio",
        "content_hash": hashlib.sha256(content.encode()).hexdigest(),
    }
    # The language and its same-name topic count once; ranked, not a tag dump.
    assert skills.content == (
        "Main technology stack of Kevin De Benedetti, ranked by how many of their "
        "1 public project use each technology.\n"
        "Programming languages: Go (1 project)\n"
        "Frameworks, tools and platforms: Next.js (1 project)"
    )
    assert skills.id == deterministic_id("profile:derived_skills")
    assert project.content == (
        "Project: portfolio\nDescription: My site\nTechnologies: Go, Next.js\n"
        "GitHub: https://github.com/kevin/portfolio\nURL: https://kevindb.dev\n"
        "Status: active"
    )
    assert project.id == deterministic_id("profile:project:portfolio")
    assert project.repo == "portfolio"


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
    hx = hashlib.sha256(b"x").hexdigest()
    he = hashlib.sha256("é".encode()).hexdigest()
    assert write_jsonl(chunks) == (
        f'{{"id":"a","content":"x","source":"s","type":"t","path":"p","content_hash":"{hx}"}}\n'
        f'{{"id":"b","content":"é","source":"s","type":"t","content_hash":"{he}"}}\n'
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
        ("README.md", 10, False),
        ("pkg/CHANGELOG.md", 10, False),
        ("LICENSE", 10, False),
        ("package-lock.json", 10, False),
        ("web/app.min.js", 10, False),
        ("api/v1/user.pb.go", 10, False),
        ("src/readme_parser.py", 10, True),
        ("app/security.py", 10, True),
        ("src/history.ts", 10, True),
        ("SECURITY.md", 10, False),
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


SMALL = "def main():\n    print('hello, world, from a small file')\n"


def test_chunk_file_small_file_is_one_chunk():
    [chunk] = chunk_file(_raw(SMALL), "kevin")
    assert chunk.content == f"// File: a.py (Python)\n{SMALL}"
    assert chunk.url == "https://gh/a.py#L1-L3"
    key = hashlib.sha256(SMALL.encode()).hexdigest()[:16]
    assert chunk.id == deterministic_id(f"github_code:kevin/r:a.py:{key}")


def test_chunk_file_skips_a_file_with_almost_no_code():
    assert chunk_file(_raw("package main", "Go"), "kevin") == []


def test_chunk_file_splits_large_file_on_function_boundaries():
    lines = ["x = 1"] * 100 + ["", "def f():"] + ["    pass"] * 100
    chunks = chunk_file(_raw("\n".join(lines)), "kevin")
    assert [str(c.url).split("#")[1] for c in chunks] == [
        "L1-L101",
        "L102-L120",
        "L121-L202",
    ]


def _bodies(chunks):
    return [c.content.split("\n", 1)[1] for c in chunks]


def test_chunk_file_splits_a_long_chunk_without_losing_code():
    lines = [f"value_{i} = {i}  # " + "x" * 60 for i in range(100)]
    chunks = chunk_file(_raw("\n".join(lines)), "kevin")
    assert len(chunks) > 1
    assert all(len(c.content) <= corpus.MAX_CODE_CHUNK_CHARS for c in chunks)
    assert "\n".join(_bodies(chunks)) == "\n".join(lines)
    anchors = [str(c.url).split("#")[1] for c in chunks]
    assert anchors[0].startswith("L1-") and anchors[-1].endswith("-L100")


def test_chunk_file_cuts_a_minified_line_into_pieces():
    chunks = chunk_file(_raw("y" * 5000), "kevin")
    assert "".join(_bodies(chunks)) == "y" * 5000
    assert all(str(c.url).endswith("#L1-L1") for c in chunks)
    assert len({c.id for c in chunks}) == len(chunks)


def test_code_ids_survive_code_added_above():
    body = ["def f():"] + ["    return 1"] * 10
    before = ["x = 1"] * 160 + [""] + body
    after = ["y = 2"] * 5 + before
    ids_before = {c.id: c.content for c in chunk_file(_raw("\n".join(before)), "k")}
    ids_after = {c.id: c.content for c in chunk_file(_raw("\n".join(after)), "k")}
    shared = set(ids_before) & set(ids_after)
    # The function moved five lines down: same text, same id.
    assert any("def f():" in ids_before[i] for i in shared)


def test_split_markdown_sections():
    sections = split_markdown_sections(
        "# Ops\n## Deploy\n### K8s\na\n## Monitoring\nb\n```bash\n# not a heading\n```"
    )
    assert [s.heading for s in sections] == ["Ops > Deploy > K8s", "Ops > Monitoring"]
    assert "# not a heading" in sections[1].body
    assert split_markdown_sections("intro\n\n## First")[0].heading == ""
    assert split_markdown_sections("") == []


async def test_docs_ids_survive_a_section_inserted_before(github):
    def account(content):
        github.json("/repos/kevin/a", {"default_branch": "main"})
        github.json(
            "/repos/kevin/a/git/trees/main",
            {"tree": [{"path": "docs/guide.md", "type": "blob", "size": 10}]},
        )
        github.json(
            "/repos/kevin/a/contents/docs/guide.md",
            {"content": b64(content), "encoding": "base64"},
        )

    text = "text " * 30
    account(f"# Setup\n{text}\n# Usage\n{text}")
    before, _ = await corpus.build_github_docs_chunks(github.client(), "kevin", ["a"])
    account(f"# Intro\n{text}\n# Setup\n{text}\n# Usage\n{text}")
    after, _ = await corpus.build_github_docs_chunks(github.client(), "kevin", ["a"])
    assert {c.id for c in before} <= {c.id for c in after}
    assert len(after) == 3


def test_doc_sections_merge_short_and_cap_long():
    long_body = "\n\n".join(["p" * 900] * 3)
    doc = RepoDoc(path="docs/a.md", content=f"# A\nshort\n# B\nmore\n# C\n{long_body}")
    sections = doc_sections(doc)
    assert sections[0].body == "short\n\nB\nmore"
    assert [len(s.body) for s in sections[1:]] == [1802, 900]


MAIN_GO = 'package main\n\nfunc main() {\n\tprintln("hello, world")\n}\n'


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
                "sha": f"tree-{name}",
                "tree": [
                    {"path": "docs/guide.md", "type": "blob", "size": 10},
                    {"path": "main.go", "type": "blob", "size": 10},
                ],
            },
        )
        github.json(
            f"/repos/kevin/{name}/contents/docs/guide.md",
            {"content": b64("# Guide\n" + "text " * 30), "encoding": "base64"},
        )
        github.json(
            f"/repos/kevin/{name}/contents/main.go",
            {"content": b64(MAIN_GO), "encoding": "base64"},
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
    assert manifest["schema_version"] == SCHEMA_VERSION
    assert manifest["owner"] == "kevin"
    assert manifest["chunker"]["code"]["max_chunk_chars"] == 2500
    assert manifest["inputs"] == {
        "kevin/a": {"branch": "main", "tree": "tree-a"},
        "kevin/b": {"branch": "main", "tree": "tree-b"},
    }
    on_disk = json.loads((tmp_path / "manifest.json").read_text())
    assert on_disk["files"] == manifest["files"]
    code = (tmp_path / "data/github_code.jsonl").read_text().splitlines()
    assert json.loads(code[0])["language"] == "Go"
    card = (tmp_path / "README.md").read_text()
    assert "config_name: github_docs" in card and "- Repository: `ns/kb`" in card
    assert "dataset_info:" in card and "- name: content_hash" in card
    assert "num_examples: 2" in card and "experience" not in card


async def test_export_refuses_truncated_split(github, tmp_path):
    _fake_account(github)
    with patch.object(corpus, "CorpusGitHubClient", return_value=github.client()):
        with pytest.raises(JobError, match='"github_code" produced only 2 chunks'):
            await export_corpus(tmp_path, ["github_code"], "kevin", "t")
    assert not (tmp_path / "manifest.json").exists()


def test_push_requires_a_complete_export(tmp_path):
    with pytest.raises(JobError, match="does not exist"):
        push_corpus(CREDS, tmp_path / "missing", "ns/kb")
    with pytest.raises(JobError, match="no manifest.json"):
        push_corpus(CREDS, tmp_path, "ns/kb")


def test_push_uploads_one_commit_to_a_private_repo(tmp_path, memory_hub):
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {
                "source_commit": "abcdef1234",
                "files": [{"source": "profile", "records": 3, "path": "data/p.jsonl"}],
            }
        )
    )
    api = MagicMock()
    api.repo_info.return_value = MagicMock(private=True)
    with patch("server.services.huggingface._api", return_value=api):
        url = push_corpus(CREDS, tmp_path, "ns/kb")

    assert url == "https://huggingface.co/datasets/ns/kb"
    api.create_repo.assert_called_once_with(
        "ns/kb", repo_type="dataset", private=True, exist_ok=True
    )
    kwargs = api.upload_folder.call_args.kwargs
    assert kwargs["commit_message"] == "Corpus refresh (abcdef1)"
    assert "- profile: 3 records (data/p.jsonl)" in kwargs["commit_description"]


def test_push_rejects_bad_token(tmp_path, memory_hub):
    (tmp_path / "manifest.json").write_text("{}")
    api = MagicMock()
    memory_hub.rejects_token = True
    with patch("server.services.huggingface._api", return_value=api):
        with pytest.raises(JobError, match="rejected your token"):
            push_corpus(CREDS, tmp_path, "ns/kb")
    api.upload_folder.assert_not_called()


def test_push_completes_a_bare_repo_name(tmp_path, memory_hub):
    (tmp_path / "manifest.json").write_text(json.dumps({"files": []}))
    api = MagicMock()
    api.repo_info.return_value = MagicMock(private=True)
    with patch("server.services.huggingface._api", return_value=api):
        url = push_corpus(CREDS, tmp_path, "kb")

    # The bare name would 404 on commit: it is pushed to <account>/kb.
    assert url == "https://huggingface.co/datasets/kevin/kb"
    assert api.create_repo.call_args.args[0] == "kevin/kb"
    assert api.upload_folder.call_args.kwargs["repo_id"] == "kevin/kb"


# --- push: a complete snapshot, on the version that was read ----------------


def _export_dir(tmp_path, sources=("profile",), version=SCHEMA_VERSION):
    files = []
    (tmp_path / "data").mkdir(exist_ok=True)
    for source in sources:
        path = f"data/{source}.jsonl"
        body = f'{{"id":"{source}"}}\n'
        (tmp_path / path).write_text(body)
        files.append(
            {
                "path": path,
                "source": source,
                "records": 1,
                "sha256": hashlib.sha256(body.encode()).hexdigest(),
            }
        )
    manifest = {"schema_version": version, "owner": "kevin", "files": files}
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    return manifest


def _hub_api(tmp_path, remote_files=None, remote_version=SCHEMA_VERSION):
    """An HfApi whose repo is at commit `c0ffee` holding ``remote_files``."""
    from huggingface_hub.errors import EntryNotFoundError

    hub = tmp_path / "hub"
    hub.mkdir()
    blobs = {}
    if remote_files is not None:
        entries = []
        for source, body in remote_files.items():
            path = f"data/{source}.jsonl"
            blobs[path] = body
            entries.append(
                {
                    "path": path,
                    "source": source,
                    "records": 1,
                    "sha256": hashlib.sha256(body.encode()).hexdigest(),
                }
            )
        blobs["manifest.json"] = json.dumps(
            {"schema_version": remote_version, "files": entries}
        )

    def download(repo_id, filename, repo_type, revision):
        assert revision == "c0ffee"
        if filename not in blobs:
            raise EntryNotFoundError(filename)
        target = hub / filename.replace("/", "_")
        target.write_text(blobs[filename])
        return str(target)

    api = MagicMock()
    api.repo_info.return_value = MagicMock(private=True, sha="c0ffee")
    api.hf_hub_download.side_effect = download
    return api, blobs


def test_push_deletes_stale_files_and_commits_on_the_read_version(tmp_path, memory_hub):
    export = tmp_path / "out"
    export.mkdir()
    _export_dir(export, corpus.KNOWN_SOURCES)
    api, _ = _hub_api(tmp_path)
    with patch("server.services.huggingface._api", return_value=api):
        push_corpus(CREDS, export, "ns/kb")

    kwargs = api.upload_folder.call_args.kwargs
    assert kwargs["parent_commit"] == "c0ffee"
    assert kwargs["delete_patterns"] == ["data/*"]


def test_push_carries_forward_the_splits_it_did_not_build(tmp_path, memory_hub):
    export = tmp_path / "out"
    export.mkdir()
    _export_dir(export, ["profile"])
    api, blobs = _hub_api(tmp_path, {"github_code": '{"id":"old-code"}\n'})
    with patch("server.services.huggingface._api", return_value=api):
        push_corpus(CREDS, export, "ns/kb")

    assert (export / "data/github_code.jsonl").read_text() == blobs[
        "data/github_code.jsonl"
    ]
    manifest = json.loads((export / "manifest.json").read_text())
    assert [f["source"] for f in manifest["files"]] == ["github_code", "profile"]
    assert "config_name: github_code" in (export / "README.md").read_text()


def test_push_refuses_to_mix_schema_versions(tmp_path, memory_hub):
    export = tmp_path / "out"
    export.mkdir()
    _export_dir(export, ["profile"])
    api, _ = _hub_api(tmp_path, {"github_code": "{}\n"}, remote_version=1)
    with patch("server.services.huggingface._api", return_value=api):
        with pytest.raises(JobError, match="rebuild every source once"):
            push_corpus(CREDS, export, "ns/kb")
    api.upload_folder.assert_not_called()


def test_push_refuses_a_carried_file_that_does_not_match_its_hash(tmp_path, memory_hub):
    export = tmp_path / "out"
    export.mkdir()
    _export_dir(export, ["profile"])
    api, blobs = _hub_api(tmp_path, {"github_code": "{}\n"})
    blobs["data/github_code.jsonl"] = "tampered\n"
    with patch("server.services.huggingface._api", return_value=api):
        with pytest.raises(JobError, match="does not match its manifest hash"):
            push_corpus(CREDS, export, "ns/kb")


def test_push_reports_a_repo_that_moved(tmp_path, memory_hub):
    from huggingface_hub.errors import HfHubHTTPError

    export = tmp_path / "out"
    export.mkdir()
    _export_dir(export, corpus.KNOWN_SOURCES)
    api, _ = _hub_api(tmp_path)
    api.upload_folder.side_effect = HfHubHTTPError(
        "precondition failed", response=MagicMock(status_code=412)
    )
    with patch("server.services.huggingface._api", return_value=api):
        with pytest.raises(CorpusMoved, match="run it again"):
            push_corpus(CREDS, export, "ns/kb")
