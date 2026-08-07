"""Tests for the CORS-related configuration derived from the environment."""

from dataclasses import replace

from server.core.config import config


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
