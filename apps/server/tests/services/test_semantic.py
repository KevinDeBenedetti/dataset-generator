"""Unit tests for the embedding helpers (fake embedders: no endpoint call)."""

from types import SimpleNamespace

import numpy as np
import pytest

from server.services import semantic
from server.services.providers import ProviderError, get_provider
from server.services.semantic import (
    SemanticIndex,
    find_semantic_duplicate,
    grounding_scores,
    nearest_texts,
    normalize,
    split_sections,
    uncovered_sections,
)
from server.tests.creds import FULL, NONE
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


# --- endpoint embeddings (OPENAI_EMBEDDING_MODEL) ------------------------------


@pytest.fixture
def endpoint(monkeypatch):
    """OPENAI_EMBEDDING_MODEL set, the endpoint's embeddings faked (fake
    vectors, or ``state.error``), the probe memory fresh."""
    state = SimpleNamespace(calls=[], error=None)
    fake = FakeEmbedder()

    def embed(model, texts, creds):
        state.calls.append((model, list(texts), creds))
        if state.error is not None:
            raise state.error
        return fake.embed(texts).tolist()

    provider = get_provider("openai")
    monkeypatch.setattr(provider, "embed", embed)
    monkeypatch.setattr(provider, "_discovered", {})  # nothing discovered yet
    monkeypatch.setattr(semantic.config, "openai_embedding_model", "embed-default")
    monkeypatch.setattr(semantic, "_probed", {})
    return state


def test_the_checks_embed_on_the_callers_endpoint(endpoint):
    chosen = semantic.get_embedder(FULL)

    assert isinstance(chosen, semantic.EndpointEmbedder)
    assert chosen.model_name == "openai:embed-default"
    vectors = chosen.embed(["port 8000", "port 8000"])
    assert np.allclose(np.linalg.norm(vectors, axis=1), 1.0)
    # Probed once, then the call itself — on the caller's own credentials.
    assert [(m, t) for m, t, _ in endpoint.calls] == [
        ("embed-default", ["ping"]),
        ("embed-default", ["port 8000", "port 8000"]),
    ]
    assert all(creds is FULL for *_, creds in endpoint.calls)
    semantic.get_embedder(FULL)
    assert len(endpoint.calls) == 2  # the probe is remembered


def test_without_an_endpoint_the_checks_compare_the_text(endpoint):
    assert semantic.get_embedder(NONE) is None
    assert semantic.get_embedder(None) is None
    assert endpoint.calls == []


def test_without_an_embedding_model_the_checks_compare_the_text(endpoint, monkeypatch):
    monkeypatch.setattr(semantic.config, "openai_embedding_model", "")
    assert semantic.get_embedder(FULL) is None
    assert endpoint.calls == []


def test_an_endpoint_that_can_not_embed_leaves_the_checks_on_the_text(endpoint):
    endpoint.error = ProviderError("Error code: 404 - model not found")
    assert semantic.get_embedder(FULL) is None
    assert semantic.get_embedder(FULL) is None
    assert len(endpoint.calls) == 1  # the failure is remembered too


def test_an_endpoint_failure_reads_as_a_model_error(endpoint):
    endpoint.error = ProviderError("openai:embed-default embedding failed: 429")
    with pytest.raises(semantic.EmbeddingModelError, match="429"):
        semantic.EndpointEmbedder("embed-default", FULL).embed(["a"])


def test_the_default_embedding_names_the_endpoints_model(endpoint, monkeypatch):
    assert semantic.default_embedding_model(FULL) == "openai:embed-default"
    assert semantic.default_embedding_model(NONE) == ""
    monkeypatch.setattr(semantic.config, "openai_embedding_model", "")
    assert semantic.default_embedding_model(FULL) == ""


def test_the_collection_models_are_the_endpoints(endpoint):
    models = semantic.collection_models(FULL)
    assert [(m.name, m.provider) for m in models] == [
        ("openai:embed-default", "openai")
    ]
    assert "api.openai.com" in models[0].description
    # No endpoint, no model: no collection can be built.
    assert semantic.collection_models(NONE) == []
    assert semantic.collection_models(None) == []


def test_an_endpoint_collection_runs_on_the_callers_credentials(endpoint):
    model = semantic.get_collection_embedder("openai:embed-large", FULL)
    assert isinstance(model, semantic.EndpointEmbedder)
    model.embed_queries(["capital of France"])
    assert endpoint.calls[-1][:2] == ("embed-large", ["capital of France"])
    with pytest.raises(semantic.EmbeddingModelError, match="Settings"):
        semantic.get_collection_embedder("openai:embed-large", NONE)


def test_a_collection_of_a_local_model_must_be_built_again(endpoint):
    # FastEmbed is gone: a collection built with one can't be searched.
    with pytest.raises(semantic.EmbeddingModelError, match="build it again"):
        semantic.get_collection_embedder("BAAI/bge-small-en-v1.5", FULL)
    assert endpoint.calls == []
