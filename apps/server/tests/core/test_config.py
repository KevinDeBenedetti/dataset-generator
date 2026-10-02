"""The configuration: what comes from the environment, what is derived from
ENVIRONMENT, and the startup checks a production deployment must pass."""

import re
from dataclasses import replace

import pytest

from server.core.config import Config, _env, config
from server.core.crypto import generate_key


class TestEnvBlankHandling:
    """A key present but blank must mean "use the default", not "".

    `.env.example` ships optional keys with no value and `make env` copies it
    verbatim; `os.getenv` only defaults when a key is *absent*.
    """

    def test_blank_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("SOME_KEY", "")
        assert _env("SOME_KEY", "fallback") == "fallback"

    def test_whitespace_only_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("SOME_KEY", "   ")
        assert _env("SOME_KEY", "fallback") == "fallback"

    def test_absent_falls_back_to_default(self, monkeypatch):
        monkeypatch.delenv("SOME_KEY", raising=False)
        assert _env("SOME_KEY", "fallback") == "fallback"

    def test_real_value_wins(self, monkeypatch):
        monkeypatch.setenv("SOME_KEY", "actual")
        assert _env("SOME_KEY", "fallback") == "actual"

    @pytest.mark.parametrize(
        "name", ["QUOTA_ACTIVE_RUNS", "WORKER_CONCURRENCY", "WORKER_DRAIN_SECONDS"]
    )
    def test_blank_numeric_keys_do_not_crash_at_construction(self, monkeypatch, name):
        """`int("")` / `float("")` would raise before the app could even start."""
        monkeypatch.setenv(name, "")
        Config()  # must not raise


def test_cors_allows_the_app_itself_only():
    cfg = replace(config, frontend_url="https://app.example.com")
    assert cfg.cors_allow_origins == ["https://app.example.com"]
    # A credentialed API must never end up allowing every origin.
    empty = replace(config, frontend_url="")
    assert empty.cors_allow_origins == [] and "*" not in empty.cors_allow_origins


def test_cors_allow_origin_regex_is_none_outside_development():
    assert replace(config, environment="production").cors_allow_origin_regex is None


def test_cors_allow_origin_regex_matches_any_localhost_port_in_development():
    pattern = replace(config, environment="development").cors_allow_origin_regex
    assert pattern is not None
    assert re.match(pattern, "http://localhost:3020")
    assert re.match(pattern, "http://127.0.0.1:8020")
    assert re.match(pattern, "https://localhost")
    # Anchored: a host that merely starts with "localhost" must not slip through.
    assert not re.match(pattern, "http://localhost.evil.com")
    assert not re.match(pattern, "https://evil.com")


class TestReasoningEffort:
    """`off` is the switch for models that reject the param; blank is the default."""

    @pytest.mark.parametrize("value", ["off", "OFF", "false", "0", "no", "disabled"])
    def test_off_values_disable_the_param(self, monkeypatch, value):
        monkeypatch.setenv("OPENAI_REASONING_EFFORT", value)
        assert Config().openai_reasoning_effort == ""

    def test_blank_means_the_default(self, monkeypatch):
        monkeypatch.setenv("OPENAI_REASONING_EFFORT", "")
        assert Config().openai_reasoning_effort == "low"

    def test_explicit_level_is_kept(self, monkeypatch):
        monkeypatch.setenv("OPENAI_REASONING_EFFORT", "High")
        assert Config().openai_reasoning_effort == "high"


def _config(monkeypatch, **env) -> Config:
    """A Config built from a production environment, with overrides."""
    base = {
        "ENVIRONMENT": "production",
        "AUTH_SECRET_KEY": "a" * 48,
        "DATABASE_URL": "postgresql://u:p@db/app",
        "FRONTEND_URL": "https://app.example.com",
        "SECRETS_ENCRYPTION_KEYS": f"k1:{generate_key()}",
        "GITHUB_CLIENT_ID": "gh",
        "GITHUB_CLIENT_SECRET": "gh-secret",
    }
    for key in (
        "CI",
        "GITHUB_ACTIONS",
        "INFOMANIAK_CLIENT_ID",
        "INFOMANIAK_CLIENT_SECRET",
        "API_PUBLIC_URL",
        "ENABLE_LOCAL_LOGIN",
    ):
        monkeypatch.delenv(key, raising=False)
    for key, value in {**base, **env}.items():
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, value)
    return Config()


class TestProductionHardening:
    """Startup refuses a configuration unsafe for real users."""

    def test_a_complete_production_config_is_accepted(self, monkeypatch):
        cfg = _config(monkeypatch)
        assert cfg.production_problems() == []
        cfg.ensure_production_config()  # does not raise

    def test_development_is_never_flagged(self, monkeypatch):
        cfg = _config(
            monkeypatch,
            ENVIRONMENT="development",
            DATABASE_URL=None,
            SECRETS_ENCRYPTION_KEYS=None,
            GITHUB_CLIENT_SECRET=None,
        )
        assert cfg.production_problems() == []

    @pytest.mark.parametrize(
        "override, needle",
        [
            ({"DATABASE_URL": None}, "DATABASE_URL"),
            ({"FRONTEND_URL": "http://app.example.com"}, "FRONTEND_URL"),
            ({"SECRETS_ENCRYPTION_KEYS": None}, "SECRETS_ENCRYPTION_KEYS is required"),
            (
                {"SECRETS_ENCRYPTION_KEYS": "k1:short"},
                "SECRETS_ENCRYPTION_KEYS is invalid",
            ),
            ({"GITHUB_CLIENT_SECRET": None}, "No sign-in method"),
        ],
    )
    def test_each_unsafe_setting_is_reported(self, monkeypatch, override, needle):
        cfg = _config(monkeypatch, **override)
        problems = cfg.production_problems()
        assert any(needle in p for p in problems), problems
        with pytest.raises(RuntimeError, match=needle):
            cfg.ensure_production_config()

    def test_every_problem_is_listed_at_once(self, monkeypatch):
        cfg = _config(monkeypatch, DATABASE_URL=None, SECRETS_ENCRYPTION_KEYS=None)
        assert len(cfg.production_problems()) == 2

    def test_infomaniak_alone_is_a_sign_in_method(self, monkeypatch):
        cfg = _config(
            monkeypatch,
            GITHUB_CLIENT_SECRET=None,
            INFOMANIAK_CLIENT_ID="ik",
            INFOMANIAK_CLIENT_SECRET="ik-secret",
        )
        assert cfg.production_problems() == []

    def test_local_login_alone_is_a_sign_in_method(self, monkeypatch):
        cfg = _config(monkeypatch, GITHUB_CLIENT_SECRET=None, ENABLE_LOCAL_LOGIN="true")
        assert cfg.production_problems() == []


class TestDerivedFromEnvironment:
    """What a deployment can't get wrong is not configurable: ENVIRONMENT decides."""

    def test_production(self, monkeypatch):
        cfg = _config(monkeypatch)
        assert cfg.auth_cookie_secure is True
        assert cfg.auth_cookie_name == "__Host-access_token"
        assert cfg.auth_refresh_cookie_name == "__Host-refresh_token"
        assert cfg.session_cookie_name == "__Host-session"
        assert cfg.enable_local_login is False
        assert cfg.docs_enabled is False
        # Users bring their own keys; the Claude subscription never runs.
        assert cfg.allow_env_credentials is False
        assert cfg.claude_provider_available is False
        assert cfg.allowed_llm_hosts == ["api.openai.com"]
        assert cfg.allow_custom_base_url is False

    def test_development(self, monkeypatch):
        cfg = _config(monkeypatch, ENVIRONMENT="development")
        assert cfg.auth_cookie_secure is False
        assert cfg.auth_cookie_name == "access_token"
        assert cfg.session_cookie_name == "session"
        assert cfg.enable_local_login is True
        assert cfg.docs_enabled is True
        assert cfg.allow_env_credentials is True
        assert cfg.claude_provider_available is True

    def test_claude_runs_in_ci_but_never_on_a_deployed_server(self, monkeypatch):
        ci = _config(monkeypatch, GITHUB_ACTIONS="true")
        assert ci.claude_provider_available
        assert ci.production_problems() == []  # the CI job is not a deployment
        deployed = _config(monkeypatch)
        deployed.enable_claude_provider = True  # forced on: still unavailable
        assert deployed.claude_provider_available is False

    def test_local_login_can_be_switched(self, monkeypatch):
        assert _config(monkeypatch, ENABLE_LOCAL_LOGIN="true").enable_local_login
        dev = _config(
            monkeypatch, ENVIRONMENT="development", ENABLE_LOCAL_LOGIN="false"
        )
        assert dev.enable_local_login is False


class TestPublicUrls:
    """One API URL drives both SSO callbacks."""

    def test_production_serves_the_api_under_the_app_host(self, monkeypatch):
        cfg = _config(monkeypatch)
        assert cfg.public_api_url == "https://app.example.com/api"
        assert (
            cfg.github_redirect_uri
            == "https://app.example.com/api/auth/github/callback"
        )
        assert (
            cfg.infomaniak_redirect_uri
            == "https://app.example.com/api/auth/infomaniak/callback"
        )

    def test_an_explicit_api_url_wins(self, monkeypatch):
        cfg = _config(monkeypatch, API_PUBLIC_URL="http://localhost:8020/")
        assert cfg.public_api_url == "http://localhost:8020"
        assert cfg.github_redirect_uri == "http://localhost:8020/auth/github/callback"

    def test_development_defaults_to_the_local_api(self, monkeypatch):
        cfg = _config(monkeypatch, ENVIRONMENT="development")
        assert cfg.public_api_url == "http://localhost:8000"


def test_the_sso_state_cookie_key_is_derived_never_the_jwt_key(monkeypatch):
    cfg = _config(monkeypatch)
    assert cfg.effective_session_secret != cfg.auth_secret_key
    assert len(cfg.effective_session_secret) == 64
    # Rotating AUTH_SECRET_KEY rotates it too.
    other = _config(monkeypatch, AUTH_SECRET_KEY="z" * 48)
    assert other.effective_session_secret != cfg.effective_session_secret
