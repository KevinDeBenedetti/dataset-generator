"""Two users, one database: nobody reaches another user's data.

The route walk enumerates every route of the app. Each one that takes a
dataset name or a run id must answer **404** (never 200/403 — a 403 would
confirm the resource exists) to a user who doesn't own it. A route that has
neither must be listed in ``_NOT_RESOURCE_ROUTES``, so adding an endpoint
forces its author to decide which of the two it is.
"""

import re
import pytest
from sqlalchemy.orm import Session

from server.main import create_app
from server.models.dataset_recipe import DatasetRecipe
from server.models.job_run import JobRun
from server.models.user import User, UserRole
from server.models.vector_collection import VectorCollection
from server.services.datasets import (
    get_dataset_view,
    list_datasets_view,
    save_generation,
)
from server.services.users import create_user

SECRET = "bobs-secret"
RUN_ID = "run-of-bob"
RECIPE_ID = "recipe-of-bob"
COLLECTION_ID = "collection-of-bob"


def _item(id_, question):
    return {
        "id": id_,
        "question": question,
        "answer": "An answer.",
        "context": "ctx",
        "source_url": "https://example.com",
        "confidence": 0.9,
        "metadata": {},
    }


@pytest.fixture
def alice(test_db: Session) -> User:
    return create_user(test_db, email="alice@test.local", password="pw12345")


@pytest.fixture
def bob(test_db: Session) -> User:
    return create_user(test_db, email="bob@test.local", password="pw12345")


@pytest.fixture(autouse=True)
def _one_database(monkeypatch, datasets_db):
    """Job runs and collections open their own sessions: same test database."""
    monkeypatch.setattr("server.services.jobs.get_scoped_db", datasets_db)
    monkeypatch.setattr("server.services.collections.get_scoped_db", datasets_db)


@pytest.fixture
def bobs_data(bob, test_db, datasets_db):
    save_generation(
        bob.id,
        SECRET,
        [_item("b1", "Bob's question?")],
        source_url="https://example.com",
    )
    test_db.add(
        JobRun(
            id=RUN_ID,
            job_id="github-personal",
            owner_id=bob.id,
            status="succeeded",
            options={},
        )
    )
    test_db.add(
        DatasetRecipe(
            id=RECIPE_ID,
            owner_id=bob.id,
            name=SECRET,
            target_repo="bob/qa",
            sources=[{"repo": "bobs-repo", "readme": True, "docs": None}],
        )
    )
    test_db.add(
        VectorCollection(
            id=COLLECTION_ID,
            owner_id=bob.id,
            name=SECRET,
            repo_id="bob/qa",
            revision="a" * 40,
            config_name="default",
            split="train",
            text_columns=["answer"],
            query_column="question",
            model="sentence-transformers/all-MiniLM-L6-v2",
            status="ready",
            rows_total=1,
            points_count=1,
            fields=["answer", "question"],
        )
    )
    test_db.commit()


# (method, path template) -> request kwargs that make the call valid, so a 404
# can only come from ownership and never from body/query validation.
_RESOURCE_ROUTES = {
    ("GET", "/dataset/{dataset_name}/sources"): {},
    ("GET", "/dataset/{dataset_name}/versions"): {},
    ("GET", "/dataset/{dataset_name}/analyze-similarities"): {},
    ("POST", "/dataset/{dataset_name}/clean-similarities"): {},
    ("POST", "/dataset/{dataset_name}/resolve-pair"): {"json": {"remove_id": "b1"}},
    ("POST", "/dataset/{dataset_name}/duplicate"): {"params": {"target_name": "copy"}},
    ("POST", "/dataset/{dataset_name}/export/huggingface"): {
        "params": {"repo_id": "someone/repo"}
    },
    ("DELETE", "/dataset/{dataset_name}"): {},
    ("GET", "/q_a/{dataset_name}"): {},
    ("GET", "/q_a/{dataset_name}/stats"): {},
    ("POST", "/q_a/{dataset_name}/score"): {},
    ("GET", "/jobs/runs/{run_id}"): {},
    ("GET", "/jobs/runs/{run_id}/checks"): {},
    ("POST", "/jobs/runs/{run_id}/publish"): {"json": {}},
    ("POST", "/jobs/runs/{run_id}/cancel"): {},
    ("GET", "/recipes/{recipe_id}"): {},
    ("PUT", "/recipes/{recipe_id}"): {
        "json": {"name": "mine", "target_repo": "alice/qa"}
    },
    ("DELETE", "/recipes/{recipe_id}"): {},
    ("POST", "/recipes/{recipe_id}/run"): {"json": {}},
    ("GET", "/collections/{collection_id}"): {},
    ("POST", "/collections/{collection_id}/build"): {"json": {}},
    ("DELETE", "/collections/{collection_id}"): {},
    ("POST", "/collections/{collection_id}/search"): {"json": {"query": "anything"}},
    ("POST", "/collections/{collection_id}/evaluate"): {"json": {}},
}

# Routes without a per-user resource in the path: they are either public,
# scoped to the caller by construction (a list, "me", own defaults) or act on
# no stored data. Adding a route means adding it here or above, on purpose.
_NOT_RESOURCE_ROUTES = {
    ("GET", "/"),
    ("GET", "/health"),
    ("GET", "/ready"),
    ("POST", "/auth/login"),
    ("POST", "/auth/refresh"),
    ("POST", "/auth/logout"),
    ("GET", "/auth/me"),
    ("POST", "/dataset"),
    ("GET", "/dataset"),
    ("POST", "/dataset/huggingface/import"),
    # The Hub viewer: the repo lives on Hugging Face and is read with the
    # caller's own token, so the Hub decides who sees what (a repo the token
    # can't read is a 404). tests/services/test_hub.py checks that a split
    # cached for one user is never served to a token the Hub refuses.
    ("GET", "/hub/datasets"),
    ("GET", "/hub/datasets/{owner}/{name}"),
    ("GET", "/hub/datasets/{owner}/{name}/rows"),
    ("GET", "/hub/datasets/{owner}/{name}/row"),
    ("GET", "/hub/datasets/{owner}/{name}/statistics"),
    ("GET", "/hub/datasets/{owner}/{name}/commits"),
    ("GET", "/hub/datasets/{owner}/{name}/compare"),
    # GitHub browse: public data of the GitHub account saved in the caller's own
    # Settings, read from GitHub on every call — nothing stored per user.
    ("GET", "/github/profile"),
    ("GET", "/github/repos"),
    ("GET", "/github/repos/{owner}/{repo}"),
    ("GET", "/github/repos/{owner}/{repo}/doc"),
    # Your own recipes: the list and a new one are the caller's by construction.
    ("GET", "/recipes"),
    ("POST", "/recipes"),
    # Your own collections: the list and a new one (built from a Hub dataset
    # read with your own token) are the caller's by construction.
    ("GET", "/collections"),
    ("POST", "/collections"),
    ("POST", "/dataset/generate/file"),
    ("POST", "/dataset/generate/url"),
    ("GET", "/quality-rules"),
    ("PUT", "/quality-rules"),
    ("GET", "/prompts"),
    ("GET", "/models"),
    ("PUT", "/models/default"),
    ("PUT", "/models/embedding"),
    ("DELETE", "/models/embedding"),
    ("POST", "/models/test"),
    ("POST", "/agent/qa-test"),
    ("GET", "/jobs"),
    ("GET", "/jobs/drafts"),
    # Your own keys and settings: always the caller's, addressed by kind not id.
    ("GET", "/me/secrets"),
    ("PUT", "/me/secrets/{kind}"),
    ("POST", "/me/secrets/{kind}/test"),
    ("DELETE", "/me/secrets/{kind}"),
    ("GET", "/me/settings"),
    ("PUT", "/me/settings"),
    ("GET", "/me/identities"),
    ("GET", "/me/export"),
    ("DELETE", "/me"),
    # Reactive Resume: admins only, read with the server's own key — nothing
    # stored per user (tests/api/test_resumes.py checks the gate).
    ("GET", "/resumes"),
    ("GET", "/resumes/{resume_id}"),
    # A resume's dataset settings: keyed by the caller's own id and the
    # resume's (a Reactive Resume id, not a row of ours), so another user's
    # answer 404 by construction; admins only (tests/api/test_resumes.py).
    ("GET", "/resumes/{resume_id}/dataset"),
    ("PUT", "/resumes/{resume_id}/dataset"),
    ("DELETE", "/resumes/{resume_id}/dataset"),
    ("POST", "/resumes/{resume_id}/dataset/run"),
    # The backoffice: admins only (tests/api/test_admin.py walks every route).
    ("GET", "/admin/users"),
    ("GET", "/admin/users/{user_id}"),
    ("PATCH", "/admin/users/{user_id}"),
    ("DELETE", "/admin/users/{user_id}"),
    ("GET", "/admin/audit"),
    ("GET", "/admin/usage"),
    ("GET", "/admin/platform"),
    ("PUT", "/admin/platform"),
    # Owner-checked in the service (404 for another user's), see test_me.py.
    ("DELETE", "/me/identities/{identity_id}"),
    # Sign-in: public, or acting on the caller's own session.
    ("GET", "/auth/providers"),
    ("POST", "/auth/logout-all"),
    ("GET", "/auth/{provider_name}/login"),
    ("GET", "/auth/{provider_name}/link"),
    ("GET", "/auth/{provider_name}/callback"),
    ("POST", "/jobs/{job_id}/run"),
}

_SKIPPED_METHODS = {"HEAD", "OPTIONS"}


def _path(template):
    return template.format(
        dataset_name=SECRET,
        run_id=RUN_ID,
        recipe_id=RECIPE_ID,
        collection_id=COLLECTION_ID,
    )


def _routes(app):
    """Every (METHOD, path) the app serves, read from its OpenAPI schema.

    The schema is the one stable view of the routing table: FastAPI nests
    included routers, so ``app.routes`` no longer lists the endpoints.
    """
    return {
        (method.upper(), path)
        for path, operations in app.openapi()["paths"].items()
        for method in operations
        if method.upper() not in _SKIPPED_METHODS
    }


def test_every_route_is_classified():
    """A new endpoint fails here until it is walked (or explicitly exempted)."""
    unclassified = {
        route
        for route in _routes(create_app())
        if route not in _RESOURCE_ROUTES and route not in _NOT_RESOURCE_ROUTES
    }
    assert not unclassified, (
        f"Classify these routes in tests/api/test_tenant_isolation.py: {sorted(unclassified)}"
    )
    # A route that takes a resource id must be walked, not exempted.
    for method, path in _NOT_RESOURCE_ROUTES:
        assert not re.search(
            r"\{(dataset_name|run_id|recipe_id|collection_id)\}", path
        ), (
            method,
            path,
        )
    # ...and the tables must not name routes that no longer exist.
    stale = (set(_RESOURCE_ROUTES) | _NOT_RESOURCE_ROUTES) - _routes(create_app())
    assert not stale, f"Stale entries: {sorted(stale)}"


@pytest.mark.parametrize(
    "route", sorted(_RESOURCE_ROUTES), ids=lambda r: f"{r[0]} {r[1]}"
)
def test_another_users_resource_looks_like_it_does_not_exist(
    route, alice, bobs_data, client_for
):
    method, template = route
    path = _path(template)

    response = client_for(alice).request(method, path, **_RESOURCE_ROUTES[route])

    assert response.status_code == 404, response.text
    # The response must not leak what the resource holds.
    assert "Bob" not in response.text


def test_nothing_of_bob_changed_after_alice_tried_everything(
    alice, bob, bobs_data, client_for, test_db
):
    alice_client = client_for(alice)
    for (method, template), kwargs in _RESOURCE_ROUTES.items():
        path = _path(template)
        alice_client.request(method, path, **kwargs)

    detail = get_dataset_view(bob.id, SECRET)
    assert detail is not None
    assert [d["name"] for d in list_datasets_view(bob.id)] == [SECRET]
    assert list_datasets_view(alice.id) == []
    recipe = test_db.get(DatasetRecipe, RECIPE_ID)
    assert recipe is not None and recipe.name == SECRET
    assert recipe.target_repo == "bob/qa"
    collection = test_db.get(VectorCollection, COLLECTION_ID)
    assert collection is not None and collection.name == SECRET
    assert collection.status == "ready" and collection.revision == "a" * 40


def test_listings_only_show_your_own_data(alice, bob, bobs_data, client_for):
    assert client_for(alice).get("/dataset").json() == []
    names = [d["name"] for d in client_for(bob).get("/dataset").json()]
    assert names == [SECRET]


def test_two_users_can_use_the_same_dataset_name_through_the_api(
    alice, bob, client_for
):
    for user in (alice, bob):
        response = client_for(user).post(
            "/dataset", params={"name": "shared-name", "description": user.email}
        )
        assert response.status_code == 200, response.text

    for user in (alice, bob):
        listed = client_for(user).get("/dataset").json()
        assert [d["description"] for d in listed] == [user.email]


def test_a_stranger_cannot_start_reading_your_run_via_the_catalogue(
    alice, bob, bobs_data, client_for
):
    jobs = client_for(alice).get("/jobs").json()["jobs"]
    assert all(job["latest_run"] is None for job in jobs)


def test_role_does_not_grant_access_to_other_users_data(test_db, bobs_data, client_for):
    admin = create_user(
        test_db, email="root@test.local", password="pw12345", role=UserRole.ADMIN
    )
    response = client_for(admin).get(f"/q_a/{SECRET}")
    assert response.status_code == 404  # admins see accounts, not content


def test_own_data_is_reachable(bob, bobs_data, client_for):
    response = client_for(bob).get(f"/q_a/{SECRET}")
    assert response.status_code == 200
    assert response.json()["total_count"] == 1
