"""Tests for the configuration derived from the environment (CORS, env parsing)."""

from dataclasses import replace

import pytest

from server.core.crypto import generate_key

from server.core.config import Config, _env, config


class TestEnvBlankHandling:
    """A key present but blank must mean "use the default", not "".

    `.env.example` ships keys with no value and `make env` copies it verbatim,
    so blanks reach the app. `os.getenv` only defaults when a key is *absent*,
    which let an empty AUTH_REFRESH_COOKIE_NAME reach `set_cookie(key="")` —
    a CookieError, so every *successful* login became a 500 while a wrong
    password still returned a normal 401.
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

    def test_blank_cookie_name_does_not_become_empty(self, monkeypatch):
        """The exact regression: a blank cookie name must stay usable."""
        monkeypatch.setenv("AUTH_REFRESH_COOKIE_NAME", "")
        monkeypatch.setenv("AUTH_COOKIE_NAME", "")
        monkeypatch.setenv("ENVIRONMENT", "development")

        cfg = Config()

        assert cfg.auth_refresh_cookie_name == "refresh_token"
        assert cfg.auth_cookie_name == "access_token"

    @pytest.mark.parametrize(
        "name",
        [
            "AUTH_TOKEN_TTL_SECONDS",
            "AUTH_LOGIN_MAX_ATTEMPTS",
            "AUTH_LOGIN_WINDOW_SECONDS",
        ],
    )
    def test_blank_numeric_keys_do_not_crash_at_construction(self, monkeypatch, name):
        """`int("")` / `float("")` would raise before the app could even start."""
        monkeypatch.setenv(name, "")

        cfg = Config()  # must not raise

        assert cfg.auth_token_ttl_seconds >= 0


def test_cors_allow_origins_defaults_to_frontend_url():
    """With CORS_ALLOW_ORIGINS unset, the front-end origin is the only one."""
    cfg = replace(
        config,
        cors_allow_origins_raw="",
        frontend_url="https://app.example.com",
    )

    assert cfg.cors_allow_origins == ["https://app.example.com"]


def test_cors_allow_origins_never_wildcards():
    """A credentialed API must not end up allowing every origin."""
    cfg = replace(config, cors_allow_origins_raw="", frontend_url="")

    assert cfg.cors_allow_origins == []
    assert "*" not in cfg.cors_allow_origins


def test_cors_allow_origins_parses_comma_separated_list():
    cfg = replace(
        config,
        cors_allow_origins_raw="https://a.example.com, https://b.example.com ,",
        frontend_url="https://ignored.example.com",
    )

    assert cfg.cors_allow_origins == [
        "https://a.example.com",
        "https://b.example.com",
    ]


def test_cors_allow_origin_regex_is_none_outside_development():
    cfg = replace(config, environment="production")

    assert cfg.cors_allow_origin_regex is None


def test_cors_allow_origin_regex_matches_any_localhost_port_in_development():
    import re

    cfg = replace(config, environment="development")
    pattern = cfg.cors_allow_origin_regex
    assert pattern is not None

    assert re.match(pattern, "http://localhost:3020")
    assert re.match(pattern, "http://127.0.0.1:8020")
    assert re.match(pattern, "https://localhost")
    # An attacker-controlled host that merely starts with "localhost" must not
    # slip through (the pattern is anchored at the end).
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


class TestProductionHardening:
    """Startup refuses a configuration unsafe for real users."""

    @staticmethod
    def _prod(monkeypatch, **env):
        base = {
            "ENVIRONMENT": "production",
            "AUTH_SECRET_KEY": "a" * 48,
            "SESSION_SECRET_KEY": "b" * 48,
            "AUTH_COOKIE_SECURE": "true",
            "DATABASE_URL": "postgresql://u:p@db/app",
            "FRONTEND_URL": "https://app.example.com",
            "SECRETS_ENCRYPTION_KEYS": f"k1:{generate_key()}",
            "ALLOW_ENV_CREDENTIALS": "false",
            "GITHUB_CLIENT_ID": "gh",
            "GITHUB_CLIENT_SECRET": "gh-secret",
        }
        for key in (
            "CI",
            "GITHUB_ACTIONS",
            "ENABLE_CLAUDE_PROVIDER",
            "OIDC_ISSUER",
            "OIDC_CLIENT_ID",
            "OIDC_CLIENT_SECRET",
            "ALLOWED_LLM_HOSTS",
            "AUTH_COOKIE_NAME",
            "AUTH_REFRESH_COOKIE_NAME",
            "DOCS_ENABLED",
            "ENABLE_LOCAL_LOGIN",
        ):
            monkeypatch.delenv(key, raising=False)
        for key, value in {**base, **env}.items():
            if value is None:
                monkeypatch.delenv(key, raising=False)
            else:
                monkeypatch.setenv(key, value)
        return Config()

    def test_a_complete_production_config_is_accepted(self, monkeypatch):
        cfg = self._prod(monkeypatch)
        assert cfg.production_problems() == []
        cfg.ensure_production_config()  # does not raise

    def test_development_is_never_flagged(self, monkeypatch):
        cfg = self._prod(
            monkeypatch,
            ENVIRONMENT="development",
            AUTH_COOKIE_SECURE="false",
            DATABASE_URL=None,
            SESSION_SECRET_KEY=None,
        )
        assert cfg.production_problems() == []

    @pytest.mark.parametrize(
        "override, needle",
        [
            ({"AUTH_COOKIE_SECURE": "false"}, "AUTH_COOKIE_SECURE"),
            ({"DATABASE_URL": None}, "DATABASE_URL"),
            ({"SESSION_SECRET_KEY": None}, "SESSION_SECRET_KEY is required"),
            ({"SESSION_SECRET_KEY": "a" * 48}, "must differ"),
            ({"FRONTEND_URL": "http://app.example.com"}, "FRONTEND_URL"),
            ({"AUTH_COOKIE_NAME": "access_token"}, "AUTH_COOKIE_NAME"),
            ({"AUTH_REFRESH_COOKIE_NAME": "refresh"}, "AUTH_REFRESH_COOKIE_NAME"),
            ({"SECRETS_ENCRYPTION_KEYS": None}, "SECRETS_ENCRYPTION_KEYS is required"),
            (
                {"SECRETS_ENCRYPTION_KEYS": "k1:short"},
                "SECRETS_ENCRYPTION_KEYS is invalid",
            ),
            ({"ALLOW_ENV_CREDENTIALS": "true"}, "ALLOW_ENV_CREDENTIALS must be false"),
            ({"GITHUB_CLIENT_SECRET": None}, "No sign-in method"),
            ({"ENABLE_CLAUDE_PROVIDER": "true"}, "development and CI only"),
        ],
    )
    def test_each_unsafe_setting_is_reported(self, monkeypatch, override, needle):
        cfg = self._prod(monkeypatch, **override)
        problems = cfg.production_problems()
        assert any(needle in p for p in problems), problems
        with pytest.raises(RuntimeError, match=needle):
            cfg.ensure_production_config()

    def test_every_problem_is_listed_at_once(self, monkeypatch):
        cfg = self._prod(
            monkeypatch,
            AUTH_COOKIE_SECURE="false",
            DATABASE_URL=None,
            SESSION_SECRET_KEY=None,
        )
        assert len(cfg.production_problems()) == 3

    def test_production_defaults_keep_platform_keys_out_and_claude_off(
        self, monkeypatch
    ):
        cfg = self._prod(monkeypatch, ALLOW_ENV_CREDENTIALS=None)
        assert cfg.allow_env_credentials is False
        assert cfg.enable_claude_provider is False
        assert cfg.claude_provider_available is False
        assert cfg.allow_custom_base_url is False
        assert cfg.allowed_llm_hosts == ["api.openai.com"]

    def test_claude_never_runs_on_a_deployed_server_even_when_enabled(
        self, monkeypatch
    ):
        cfg = self._prod(monkeypatch)
        cfg.enable_claude_provider = True  # e.g. a forgotten env var
        assert cfg.claude_provider_available is False

    def test_claude_runs_in_ci_and_development(self, monkeypatch):
        ci = self._prod(monkeypatch, GITHUB_ACTIONS="true")
        assert ci.enable_claude_provider and ci.claude_provider_available
        assert ci.production_problems() == []  # the CI job is not a deployment
        dev = self._prod(monkeypatch, ENVIRONMENT="development", GITHUB_ACTIONS=None)
        assert dev.claude_provider_available

    def test_allowed_llm_hosts_are_extended_from_the_env(self, monkeypatch):
        cfg = self._prod(monkeypatch, ALLOWED_LLM_HOSTS="Gateway.Example.com, ,x.io")
        assert cfg.allowed_llm_hosts == [
            "api.openai.com",
            "gateway.example.com",
            "x.io",
        ]

    def test_production_defaults(self, monkeypatch):
        cfg = self._prod(monkeypatch)
        assert cfg.auth_cookie_name == "__Host-access_token"
        assert cfg.auth_refresh_cookie_name == "__Host-refresh_token"
        assert cfg.session_cookie_name == "__Host-session"
        assert cfg.enable_local_login is False
        assert cfg.docs_enabled is False

    def test_development_defaults(self, monkeypatch):
        cfg = self._prod(monkeypatch, ENVIRONMENT="development")
        assert cfg.auth_cookie_name == "access_token"
        assert cfg.session_cookie_name == "session"
        assert cfg.enable_local_login is True
        assert cfg.docs_enabled is True

    def test_flags_can_be_overridden(self, monkeypatch):
        cfg = self._prod(monkeypatch, ENABLE_LOCAL_LOGIN="true", DOCS_ENABLED="true")
        assert cfg.enable_local_login is True and cfg.docs_enabled is True
        cfg = self._prod(
            monkeypatch, ENVIRONMENT="development", ENABLE_LOCAL_LOGIN="false"
        )
        assert cfg.enable_local_login is False

    def test_session_secret_falls_back_only_when_unset(self, monkeypatch):
        cfg = self._prod(monkeypatch, SESSION_SECRET_KEY=None)
        assert cfg.effective_session_secret == cfg.auth_secret_key
        assert self._prod(monkeypatch).effective_session_secret == "b" * 48
