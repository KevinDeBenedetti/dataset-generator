from server.jobs.github_snapshot import RepoData
from server.jobs.tech_stack import (
    StackEntry,
    cargo_deps,
    detect_technologies,
    file_signals,
    go_mod_deps,
    main_entries,
    manifest_paths,
    package_json_deps,
    pyproject_deps,
    rank_stack,
    repo_technologies,
    requirements_deps,
    tech_for_dependency,
)


def test_package_json_reads_every_dependency_section():
    text = (
        '{"dependencies":{"next":"16"},"devDependencies":{"vitest":"4"},'
        '"peerDependencies":{"react":"19"}}'
    )
    assert package_json_deps(text) == ["next", "vitest", "react"]


def test_pyproject_reads_pep621_groups_and_poetry():
    text = """
[project]
dependencies = ["fastapi>=0.110", "SQLAlchemy[asyncio]~=2.0"]
[project.optional-dependencies]
ml = ["torch; python_version>'3.10'"]
[dependency-groups]
dev = ["pytest"]
[tool.poetry.dependencies]
python = "^3.12"
celery = "*"
[tool.poetry.group.lint.dependencies]
ruff = "*"
"""
    assert pyproject_deps(text) == [
        "fastapi",
        "SQLAlchemy",
        "torch",
        "pytest",
        "celery",
        "ruff",
    ]


def test_requirements_skip_comments_and_options():
    text = "-r base.txt\nflask==3.0  # web\n\n# comment\nlangchain_openai>=0.1\n"
    assert requirements_deps(text) == ["flask", "langchain_openai"]


def test_go_mod_reads_block_and_single_requires():
    text = (
        "module x\n\nrequire github.com/spf13/cobra v1.8.0\n"
        "require (\n\tgithub.com/gin-gonic/gin v1.10.0 // indirect\n)\n"
    )
    assert go_mod_deps(text) == ["github.com/spf13/cobra", "github.com/gin-gonic/gin"]


def test_cargo_reads_dependency_tables():
    text = '[dependencies]\ntokio = "1"\n[dev-dependencies]\nclap = "4"\n'
    assert cargo_deps(text) == ["tokio", "clap"]


def test_only_catalogued_dependencies_count():
    assert tech_for_dependency("next") == "Next.js"
    assert tech_for_dependency("SQLAlchemy") == "SQLAlchemy"
    # PyPI's _/- equivalence, and package families by prefix.
    assert tech_for_dependency("qdrant_client") == "Qdrant"
    assert tech_for_dependency("langchain_openai") == "LangChain"
    assert tech_for_dependency("@langchain/openai") == "LangChain"
    # Plumbing says nothing about a stack.
    assert tech_for_dependency("@types/node") == ""
    assert tech_for_dependency("httpx") == ""


def test_file_signals_ignore_vendored_and_example_code():
    paths = [
        "Dockerfile",
        "compose.yaml",
        "charts/app/Chart.yaml",
        "infra/main.tf",
        "ansible/roles/k3s/tasks/main.yml",
        ".github/workflows/ci.yml",
        "examples/demo/kustomization.yaml",
        "node_modules/x/Dockerfile.dev",
    ]
    assert file_signals(paths) == {
        "Docker",
        "Docker Compose",
        "Helm",
        "Terraform",
        "Ansible",
        "GitHub Actions",
    }


def test_manifest_paths_shallowest_first_without_vendored():
    paths = [
        "apps/web/package.json",
        "package.json",
        "node_modules/next/package.json",
        "tests/fixtures/pyproject.toml",
        "README.md",
    ]
    assert manifest_paths(paths) == ["package.json", "apps/web/package.json"]


async def test_detect_technologies_skips_malformed_manifests():
    tree = [
        {"path": "package.json", "type": "blob", "size": 40},
        {"path": "api/pyproject.toml", "type": "blob", "size": 40},
        {"path": "Dockerfile", "type": "blob", "size": 10},
        {"path": "src", "type": "tree"},
    ]
    files = {
        "package.json": "{not json",
        "api/pyproject.toml": '[project]\ndependencies = ["fastapi"]\n',
    }

    async def read(path):
        return files[path]

    assert await detect_technologies(tree, read) == ["Docker", "FastAPI"]


def test_repo_technologies_merge_topics_and_detected_on_one_label():
    repo = RepoData(
        "api",
        language="Python",
        topics=["python", "fastapi", "dotfiles"],
        technologies=["FastAPI", "Docker"],
    )
    # ``fastapi`` (topic) and ``FastAPI`` (detected) are one technology;
    # ``dotfiles`` is not a technology at all.
    assert repo_technologies(repo) == ["Python", "FastAPI", "Docker"]


def test_rank_stack_counts_each_technology_once_per_repo():
    repos = [
        RepoData("a", language="Python", topics=["docker"], technologies=["FastAPI"]),
        RepoData("b", language="Vue", technologies=["TypeScript", "Docker", "Vitest"]),
        RepoData("c", language="Python", topics=["Docker", "fastapi"]),
    ]
    stack = rank_stack(repos)
    # TypeScript is a language even though no repo has it as primary language.
    assert [(e.name, e.projects) for e in stack.languages] == [
        ("Python", 2),
        ("TypeScript", 1),
        ("Vue", 1),
    ]
    assert [(e.name, e.projects) for e in stack.tools] == [
        ("Docker", 3),
        ("FastAPI", 2),
    ]
    # A test runner is tooling, not part of the stack proper.
    assert [(e.name, e.projects) for e in stack.tooling] == [("Vitest", 1)]
    assert stack.total_projects == 3


def test_main_entries_prefer_shared_technologies():
    entries = [StackEntry(n, c) for n, c in [("A", 3), ("B", 2), ("C", 2), ("D", 1)]]
    assert [e.name for e in main_entries(entries, 8)] == ["A", "B", "C"]
    # Too few shared ones: fall back to the top of the ranking.
    assert [e.name for e in main_entries(entries[:1] + entries[3:], 8)] == ["A", "D"]
