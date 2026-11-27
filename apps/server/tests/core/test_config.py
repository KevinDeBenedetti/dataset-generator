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


class TestDefaultModels:
    """OPENAI_LLM_MODEL is the one LLM: every step, the jobs too."""

    def test_the_llm_is_the_one_configured_model(self, monkeypatch):
        monkeypatch.setenv("OPENAI_LLM_MODEL", "chat-default")
        assert Config().available_models == ["chat-default"]
        monkeypatch.setenv("OPENAI_LLM_MODEL", "")
        assert Config().available_models == []

    def test_the_default_embedding_and_the_admins_server_llm(self, monkeypatch):
        monkeypatch.setenv("OPENAI_EMBEDDING_MODEL", "embed-default")
        monkeypatch.delenv("SERVER_LLM_FOR_ADMINS", raising=False)
        cfg = Config()
        assert cfg.openai_embedding_model == "embed-default"
        assert cfg.server_llm_for_admins is False  # opt-in
        monkeypatch.setenv("SERVER_LLM_FOR_ADMINS", "true")
        assert Config().server_llm_for_admins is True


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
        "ADMIN_USERNAME": "operator",
        "ADMIN_PASSWORD_HASH": _ARGON2_HASH,
    }
    for key in (
        "ADMIN_PASSWORD",
        "ADMIN_TOTP_SECRET",
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


_ARGON2_HASH = "$argon2id$v=19$m=65536,t=3,p=4$c2FsdHNhbHQ$aGFzaGhhc2hoYXNo"


class TestAdminSecrets:
    """The admin's deployment secrets (auth/admin_secrets.py) are checked at start."""

    def test_admin_username_is_required(self, monkeypatch):
        problems = _config(monkeypatch, ADMIN_USERNAME=None).production_problems()
        assert any("ADMIN_USERNAME is required" in p for p in problems)

    def test_a_username_without_a_hash_is_refused(self, monkeypatch):
        problems = _config(monkeypatch, ADMIN_PASSWORD_HASH=None).production_problems()
        assert any("ADMIN_PASSWORD_HASH is required" in p for p in problems)

    def test_a_hash_that_is_not_argon2id_is_refused(self, monkeypatch):
        bcrypt_hash = "$2b$12$" + "a" * 53
        cfg = _config(monkeypatch, ADMIN_PASSWORD_HASH=bcrypt_hash)
        assert any("argon2id" in p for p in cfg.production_problems())

    def test_a_password_in_clear_is_refused(self, monkeypatch):
        cfg = _config(monkeypatch, ADMIN_PASSWORD="hunter2hunter2")
        assert any("development only" in p for p in cfg.production_problems())

    def test_a_username_with_odd_characters_is_refused(self, monkeypatch):
        cfg = _config(monkeypatch, ADMIN_USERNAME="admin@example.com")
        assert any("letters, digits" in p for p in cfg.production_problems())

    def test_a_totp_secret_must_be_base32(self, monkeypatch):
        bad = _config(monkeypatch, ADMIN_TOTP_SECRET="not base32 !!")
        assert any("base32" in p for p in bad.production_problems())
        good = _config(monkeypatch, ADMIN_TOTP_SECRET="JBSWY3DPEHPK3PXPJBSWY3DP")
        assert good.production_problems() == []

    def test_development_needs_none_of_it(self, monkeypatch):
        cfg = _config(
            monkeypatch,
            ENVIRONMENT="development",
            ADMIN_USERNAME=None,
            ADMIN_PASSWORD="x",
        )
        assert cfg.production_problems() == []


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

    @pytest.mark.parametrize(
        "url",
        [
            "https://portfolio.example.com/api/collections/hf/sync",
            "http://portfolio.portfolio.svc.cluster.local:3000/api/collections/hf/sync",
            "http://portfolio.portfolio.svc/sync",
            "http://portfolio:3000/sync",
            "http://10.43.0.12/sync",
            "http://127.0.0.1:8080/sync",
        ],
    )
    def test_a_reindex_url_that_keeps_its_secret_safe_is_accepted(
        self, monkeypatch, url
    ):
        cfg = _config(
            monkeypatch, CORPUS_REINDEX_URL=url, CORPUS_REINDEX_SECRET="s3cret"
        )
        assert cfg.production_problems() == []

    @pytest.mark.parametrize(
        "url",
        [
            "http://portfolio.example.com/api/collections/hf/sync",
            "http://203.0.113.7/sync",
            "http://8.8.8.8/sync",
            "ftp://portfolio.example.com/sync",
            "portfolio.example.com/sync",
        ],
    )
    def test_a_reindex_url_that_would_leak_its_secret_is_refused(
        self, monkeypatch, url
    ):
        cfg = _config(
            monkeypatch, CORPUS_REINDEX_URL=url, CORPUS_REINDEX_SECRET="s3cret"
        )
        problems = cfg.production_problems()
        assert any("CORPUS_REINDEX_URL must be https" in p for p in problems), problems
        assert not any("s3cret" in p for p in problems)

    @pytest.mark.parametrize(
        "url, secret",
        [("https://portfolio.example.com/sync", None), (None, "s3cret")],
    )
    def test_the_reindex_settings_go_together(self, monkeypatch, url, secret):
        cfg = _config(monkeypatch, CORPUS_REINDEX_URL=url, CORPUS_REINDEX_SECRET=secret)
        assert any("go together" in p for p in cfg.production_problems())

    def test_an_http_reindex_url_is_fine_in_development(self, monkeypatch):
        cfg = _config(
            monkeypatch,
            ENVIRONMENT="development",
            CORPUS_REINDEX_URL="http://portfolio.example.com/sync",
            CORPUS_REINDEX_SECRET="s3cret",
        )
        assert cfg.production_problems() == []

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
        # Users bring their own keys.
        assert cfg.allow_env_credentials is False
        assert cfg.allowed_llm_hosts == ["api.openai.com"]
        assert cfg.allow_custom_base_url is False
        # A public deployment creates no account until an admin opens sign-up.
        assert cfg.allow_signup is False

    def test_development(self, monkeypatch):
        cfg = _config(monkeypatch, ENVIRONMENT="development")
        assert cfg.auth_cookie_secure is False
        assert cfg.auth_cookie_name == "access_token"
        assert cfg.session_cookie_name == "session"
        assert cfg.enable_local_login is True
        assert cfg.docs_enabled is True
        assert cfg.allow_env_credentials is True
        assert cfg.allow_signup is True

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


def test_the_q_and_a_dataset_license_is_a_setting_of_the_config(monkeypatch):
    """Read in one place with every other setting (core/config.py), not by the
    job that writes the dataset card."""
    from server.core.config import Config

    monkeypatch.setenv("HF_QA_DATASET_LICENSE", "other")
    monkeypatch.setenv("HF_QA_DATASET_LICENSE_LINK", "https://example.com/license")
    settings = Config()
    assert settings.hf_qa_dataset_license == "other"
    assert settings.hf_qa_dataset_license_link == "https://example.com/license"

    monkeypatch.delenv("HF_QA_DATASET_LICENSE")
    monkeypatch.delenv("HF_QA_DATASET_LICENSE_LINK")
    assert Config().hf_qa_dataset_license == ""
