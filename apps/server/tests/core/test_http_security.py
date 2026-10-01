"""Security headers and the CSRF Origin check, on a minimal app."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.core.http_security import OriginCheckMiddleware, SecurityHeadersMiddleware


def _app(hsts=False, origins=("https://app.example.com",), regex=None):
    app = FastAPI()

    @app.get("/ping")
    def ping():
        return {"ok": True}

    @app.post("/change")
    def change():
        return {"changed": True}

    @app.get("/auth/me")
    def me():
        return {"me": True}

    app.add_middleware(
        OriginCheckMiddleware, allowed_origins=origins, allowed_origin_regex=regex
    )
    app.add_middleware(SecurityHeadersMiddleware, hsts=hsts)
    return TestClient(app, base_url="https://app.example.com")


class TestSecurityHeaders:
    def test_headers_on_every_response(self):
        response = _app().get("/ping")
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["x-frame-options"] == "DENY"
        assert response.headers["referrer-policy"] == "strict-origin-when-cross-origin"
        assert response.headers["content-security-policy"] == "frame-ancestors 'none'"

    def test_hsts_only_when_asked(self):
        assert "strict-transport-security" not in _app(hsts=False).get("/ping").headers
        header = _app(hsts=True).get("/ping").headers["strict-transport-security"]
        assert "max-age=63072000" in header and "includeSubDomains" in header

    def test_auth_answers_are_never_cached(self):
        assert _app().get("/auth/me").headers["cache-control"] == "no-store"
        assert "cache-control" not in _app().get("/ping").headers

    def test_headers_are_added_to_error_responses_too(self):
        response = _app().get("/nope")
        assert response.status_code == 404
        assert response.headers["x-frame-options"] == "DENY"


class TestOriginCheck:
    def test_foreign_origin_cannot_change_state(self):
        response = _app().post("/change", headers={"Origin": "https://evil.example"})
        assert response.status_code == 403
        assert response.json() == {"detail": "Origin not allowed"}

    def test_null_origin_is_refused(self):
        # Sandboxed iframes and some redirects send "Origin: null".
        assert _app().post("/change", headers={"Origin": "null"}).status_code == 403

    def test_allowed_origin_passes(self):
        response = _app().post("/change", headers={"Origin": "https://app.example.com"})
        assert response.status_code == 200

    def test_trailing_slash_and_case_are_ignored(self):
        assert (
            _app()
            .post("/change", headers={"Origin": "https://APP.example.com/"})
            .status_code
            == 200
        )

    def test_same_origin_as_the_host_is_allowed(self):
        # FRONTEND_URL misconfigured, but the page was served by this very host.
        client = _app(origins=())
        assert (
            client.post(
                "/change", headers={"Origin": "https://app.example.com"}
            ).status_code
            == 200
        )

    def test_request_without_origin_passes(self):
        # curl, the CI, Bearer-token clients: not a browser CSRF vector.
        assert _app().post("/change").status_code == 200

    def test_safe_methods_are_never_checked(self):
        response = _app().get("/ping", headers={"Origin": "https://evil.example"})
        assert response.status_code == 200

    @pytest.mark.parametrize("method", ["put", "patch", "delete"])
    def test_every_unsafe_method_is_checked(self, method):
        app = FastAPI()

        @app.api_route("/x", methods=["PUT", "PATCH", "DELETE"])
        def x():
            return {}

        app.add_middleware(OriginCheckMiddleware, allowed_origins=[])
        client = TestClient(app, base_url="https://app.example.com")
        response = getattr(client, method)(
            "/x", headers={"Origin": "https://evil.example"}
        )
        assert response.status_code == 403

    def test_dev_regex_allows_any_localhost_port(self):
        client = _app(origins=(), regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?$")
        for origin in ("http://localhost:3020", "http://127.0.0.1:5173"):
            assert client.post("/change", headers={"Origin": origin}).status_code == 200
        assert (
            client.post(
                "/change", headers={"Origin": "http://localhost.evil.example"}
            ).status_code
            == 403
        )
