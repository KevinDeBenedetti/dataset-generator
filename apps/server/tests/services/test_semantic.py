"""Unit tests for the embedding helpers (fake embedders: no model download, no
endpoint call)."""

import os
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
    monkeypatch.setattr(semantic.config, "openai_embedding_model", "")
    names = [m.name for m in semantic.collection_models()]
    assert names[0] == semantic.config.semantic_model
    assert len(names) == len(set(names)) == len(semantic.COLLECTION_MODELS)

    monkeypatch.setattr(semantic.config, "semantic_model", "intfloat/custom")
    custom = semantic.collection_models()
    assert custom[0].name == "intfloat/custom" and custom[0].dimensions is None
    assert len(custom) == len(semantic.COLLECTION_MODELS) + 1


# --- endpoint embeddings (OPENAI_EMBEDDING_MODEL) ------------------------------


@pytest.fixture
def endpoint(monkeypatch):
    """OPENAI_EMBEDDING_MODEL set, the endpoint's embeddings faked (fake
    vectors, or ``state.error``), the probe memory and the local model fresh."""
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
    monkeypatch.setattr(semantic.config, "semantic_enabled", True)
    monkeypatch.setattr(semantic, "_probed", {})
    local = FakeEmbedder()
    local.model_name = "local/model"
    monkeypatch.setattr(semantic, "get_local_embedder", lambda: local)
    state.local = local
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


def test_without_an_endpoint_the_local_model_embeds(endpoint):
    assert semantic.get_embedder(NONE) is endpoint.local
    assert semantic.get_embedder(None) is endpoint.local
    assert endpoint.calls == []


def test_an_endpoint_that_can_not_embed_falls_back_to_the_local_model(endpoint):
    endpoint.error = ProviderError("Error code: 404 - model not found")
    assert semantic.get_embedder(FULL) is endpoint.local
    assert semantic.get_embedder(FULL) is endpoint.local
    assert len(endpoint.calls) == 1  # the failure is remembered too


def test_turning_the_checks_off_turns_the_endpoint_off_too(endpoint, monkeypatch):
    monkeypatch.setattr(semantic.config, "semantic_enabled", False)
    assert semantic.get_embedder(FULL) is None
    assert endpoint.calls == []


def test_an_endpoint_failure_reads_as_a_model_error(endpoint):
    endpoint.error = ProviderError("openai:embed-default embedding failed: 429")
    with pytest.raises(semantic.EmbeddingModelError, match="429"):
        semantic.EndpointEmbedder("embed-default", FULL).embed(["a"])


def test_the_default_embedding_names_the_endpoints_model(endpoint, monkeypatch):
    assert semantic.default_embedding_model(FULL) == "openai:embed-default"
    assert semantic.default_embedding_model(NONE) == semantic.config.semantic_model
    monkeypatch.setattr(semantic.config, "openai_embedding_model", "")
    assert semantic.default_embedding_model(FULL) == semantic.config.semantic_model


def test_a_collection_defaults_to_the_endpoints_model(endpoint):
    models = semantic.collection_models(FULL)
    assert (models[0].name, models[0].provider) == ("openai:embed-default", "openai")
    assert "api.openai.com" in models[0].description
    # The local models stay selectable, the deployment's own first of them.
    assert models[1].name == semantic.config.semantic_model
    assert {m.provider for m in models[1:]} == {"local"}
    # No endpoint, no endpoint model.
    assert semantic.collection_models(NONE)[0].name == semantic.config.semantic_model


def test_an_endpoint_collection_runs_on_the_callers_credentials(endpoint):
    model = semantic.get_collection_embedder("openai:embed-large", FULL)
    assert isinstance(model, semantic.EndpointEmbedder)
    model.embed_queries(["capital of France"])
    assert endpoint.calls[-1][:2] == ("embed-large", ["capital of France"])
    with pytest.raises(semantic.EmbeddingModelError, match="Settings"):
        semantic.get_collection_embedder("openai:embed-large", NONE)


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
