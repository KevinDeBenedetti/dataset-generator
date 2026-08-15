"""Tests for the configuration derived from the environment (CORS, env parsing)."""

from dataclasses import replace

import pytest

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

        cfg = Config()

        assert cfg.auth_refresh_cookie_name == "refresh_token"
        assert cfg.auth_cookie_name == "access_token"

    @pytest.mark.parametrize(
        "name",
        ["CRAWL_MAX_DEPTH", "CRAWL_MAX_PAGES", "CRAWL_DELAY_SECONDS"],
    )
    def test_blank_numeric_keys_do_not_crash_at_construction(self, monkeypatch, name):
        """`int("")` / `float("")` would raise before the app could even start."""
        monkeypatch.setenv(name, "")

        cfg = Config()  # must not raise

        assert cfg.crawl_max_depth >= 0


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
