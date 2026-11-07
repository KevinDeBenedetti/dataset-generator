"""Unit tests for the local-embedding helpers (fake embedder, no model download)."""

import os

import numpy as np
import pytest

from server.services import semantic
from server.services.semantic import (
    SemanticIndex,
    find_semantic_duplicate,
    grounding_scores,
    nearest_texts,
    normalize,
    split_sections,
    uncovered_sections,
)
from server.tests.fake_embedder import FakeEmbedder


@pytest.fixture
def embedder() -> FakeEmbedder:
    return FakeEmbedder()


def _index(embedder, texts):
    index = SemanticIndex()
    index.add(texts, embedder.embed(texts))
    return index


def test_normalize_keeps_zero_rows_finite():
    out = normalize(np.array([[3.0, 4.0], [0.0, 0.0]]))
    assert np.allclose(out, [[0.6, 0.8], [0.0, 0.0]])


def test_empty_index_has_no_match(embedder):
    index = SemanticIndex()
    vector = embedder.embed(["anything"])
    assert index.best(vector) is None
    assert index.top_k(vector, 3) == []
    assert find_semantic_duplicate(vector, index, 0.5) is None


def test_add_rejects_mismatched_vectors(embedder):
    with pytest.raises(ValueError):
        SemanticIndex().add(["a", "b"], embedder.embed(["a"]))


def test_semantic_duplicate_respects_threshold(embedder):
    index = _index(embedder, ["how do I run the tests", "what license is used"])
    near = embedder.embed(["how do I run the unit tests"])
    match = find_semantic_duplicate(near, index, 0.8)
    assert match is not None and match[0] == 0 and match[1] >= 0.8
    assert find_semantic_duplicate(near, index, 0.99) is None


def test_scores_take_best_of_several_vectors(embedder):
    index = _index(embedder, ["docker compose ports", "release workflow"])
    vectors = embedder.embed(["docker compose ports", "release workflow"])
    assert np.allclose(index.scores(vectors), [1.0, 1.0])


def test_nearest_texts_orders_and_applies_floor(embedder):
    index = _index(embedder, ["redis cache ttl", "redis cache eviction", "logo colour"])
    vector = embedder.embed(["redis cache ttl settings"])
    assert nearest_texts(vector, index, k=2) == [
        "redis cache ttl",
        "redis cache eviction",
    ]
    assert "logo colour" not in nearest_texts(vector, index, k=3, floor=0.2)


def test_split_sections_by_heading_and_size():
    body = "word " * 150  # 750 chars: over the 500-char window
    text = f"# Title\n\nIntro paragraph long enough to be kept as its own piece.\n\n## Big\n\n{body}\n\n## Tiny\n\nok"
    sections = split_sections(text)
    assert sections[0].startswith("# Title")
    assert all(len(s) <= 500 for s in sections)
    # The long paragraph is cut, not lost.
    assert sum(s.count("word") for s in sections) == 150
    # "## Tiny\n\nok" is under the minimum and dropped.
    assert not any("Tiny" in s for s in sections)


def test_uncovered_sections(embedder):
    sections = [
        "Installation: run make install then make dev",
        "Deployment to kubernetes with helm charts",
    ]
    vectors = embedder.embed(sections)
    assert uncovered_sections(sections, vectors, SemanticIndex(), 0.4) == sections

    index = _index(embedder, ["how do I install it with make install and make dev"])
    assert uncovered_sections(sections, vectors, index, 0.4) == [sections[1]]


def test_grounding_scores(embedder):
    chunks = embedder.embed(["the api listens on port 8000", "the ui runs on 3000"])
    answers = embedder.embed(["the api listens on port 8000", "written in cobol"])
    scores = grounding_scores(answers, chunks)
    assert scores[0] == pytest.approx(1.0) and scores[1] < 0.2
    assert list(grounding_scores(answers, np.zeros((0, 0)))) == [0.0, 0.0]


@pytest.fixture
def fresh_loader(monkeypatch):
    monkeypatch.setattr(semantic, "_embedder", None)
    monkeypatch.setattr(semantic, "_failed_at", None)
    monkeypatch.setattr(semantic.config, "semantic_enabled", True)


def test_get_local_embedder_disabled(monkeypatch, fresh_loader):
    monkeypatch.setattr(semantic.config, "semantic_enabled", False)
    assert semantic.get_local_embedder() is None


def test_get_local_embedder_failure_is_not_retried_at_once(monkeypatch, fresh_loader):
    attempts = []

    def broken(*args, **kwargs):
        attempts.append(args)
        raise OSError("no network")

    monkeypatch.setattr(semantic, "LocalEmbedder", broken)
    assert semantic.get_local_embedder() is None
    assert semantic.get_local_embedder() is None
    assert len(attempts) == 1


def test_get_local_embedder_is_shared(monkeypatch, fresh_loader):
    monkeypatch.setattr(semantic, "LocalEmbedder", lambda *a: FakeEmbedder())
    assert semantic.get_local_embedder() is semantic.get_local_embedder()


# --- the models of the vector collections ------------------------------------


@pytest.fixture
def collection_loader(monkeypatch, fresh_loader):
    """Fake models, recorded by name; the loaded ones start empty."""
    loaded = []

    def load(name, cache_dir=None):
        loaded.append(name)
        model = FakeEmbedder()
        model.model_name = name
        return model

    monkeypatch.setattr(semantic, "LocalEmbedder", load)
    monkeypatch.setattr(semantic, "_loaded", semantic.OrderedDict())
    return loaded


def test_a_collection_model_loads_once_and_two_stay_loaded(collection_loader):
    first = semantic.get_collection_embedder("a/one")
    assert semantic.get_collection_embedder("a/one") is first
    semantic.get_collection_embedder("a/two")
    semantic.get_collection_embedder("a/three")  # a third: "a/one", least recent, goes

    assert semantic.get_collection_embedder("a/three").model_name == "a/three"
    semantic.get_collection_embedder("a/one")
    assert collection_loader == ["a/one", "a/two", "a/three", "a/one"]


def test_the_duplicate_checks_model_is_shared_with_the_collections(
    monkeypatch, collection_loader
):
    shared = FakeEmbedder()
    monkeypatch.setattr(semantic, "_embedder", shared)

    assert semantic.get_collection_embedder(semantic.config.semantic_model) is shared
    assert collection_loader == []


def test_a_collection_model_that_can_not_load_says_why(monkeypatch, fresh_loader):
    def broken(*args, **kwargs):
        raise OSError("no network")

    monkeypatch.setattr(semantic, "LocalEmbedder", broken)
    with pytest.raises(semantic.EmbeddingModelError, match="FASTEMBED_CACHE_PATH"):
        semantic.get_collection_embedder("BAAI/bge-small-en-v1.5")


def test_the_collection_models_put_the_deployments_own_first(monkeypatch):
    names = [m.name for m in semantic.collection_models()]
    assert names[0] == semantic.config.semantic_model
    assert len(names) == len(set(names)) == len(semantic.COLLECTION_MODELS)

    monkeypatch.setattr(semantic.config, "semantic_model", "intfloat/custom")
    custom = semantic.collection_models()
    assert custom[0].name == "intfloat/custom" and custom[0].dimensions is None
    assert len(custom) == len(semantic.COLLECTION_MODELS) + 1


@pytest.mark.slow
@pytest.mark.skipif(
    not os.environ.get("SEMANTIC_TEST_MODEL"),
    reason="set SEMANTIC_TEST_MODEL (and FASTEMBED_CACHE_PATH) to run against the real model",
)
def test_real_model_separates_rephrasing_from_new_question():
    model = semantic.LocalEmbedder(
        os.environ["SEMANTIC_TEST_MODEL"], os.environ.get("FASTEMBED_CACHE_PATH")
    )
    v = model.embed(
        [
            "What is the purpose of this project?",
            "Quel est le but de ce projet ?",
            "Which port does the database listen on?",
        ]
    )
    assert np.allclose(np.linalg.norm(v, axis=1), 1.0, atol=1e-5)
    assert v[0] @ v[1] > 0.85
    assert v[0] @ v[2] < 0.5
