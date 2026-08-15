from dataclasses import dataclass, field
from typing import List, Optional
import os

from dotenv import load_dotenv

load_dotenv()


def _env(name: str, default: str = "") -> str:
    """Read an env var, treating an empty/whitespace value as unset.

    ``os.getenv`` only falls back to its default when the variable is *absent*:
    a key present but blank wins with "". `.env.example` ships several keys that
    way (``AUTH_REFRESH_COOKIE_NAME=``, ``CRAWL_MAX_DEPTH=``, ...) and `make env`
    copies it verbatim, so those blanks reach the app. The damage was silent and
    varied: an empty cookie name made ``set_cookie(key="")`` raise
    ``CookieError``, turning every *successful* login into a 500 (a wrong
    password still returned 401, since it never got that far), while an empty
    numeric key crashed ``int("")`` at import. Collapsing blank to absent makes a
    key with no value mean "use the default", which is what writing it that way
    plainly intends.
    """
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    return value


@dataclass
class Config:
    # API Configuration (single OpenAI-compatible provider)
    openai_api_key: str = field(default_factory=lambda: _env("OPENAI_API_KEY", ""))
    openai_base_url: str = field(default_factory=lambda: _env("OPENAI_BASE_URL", ""))

    # Reasoning models (e.g. gpt-oss) emit a chain-of-thought before the answer.
    # "low" keeps that short so the agent reliably reaches the final JSON.
    # Set OPENAI_REASONING_EFFORT="" to disable for models that reject the param.
    openai_reasoning_effort: str = field(
        default_factory=lambda: _env("OPENAI_REASONING_EFFORT", "low")
    )

    # Models (one per role, from the configured provider)
    openai_llm_model: str = field(default_factory=lambda: _env("OPENAI_LLM_MODEL", ""))
    openai_embedding_model: str = field(
        default_factory=lambda: _env("OPENAI_EMBEDDING_MODEL", "")
    )
    openai_vlm_model: str = field(default_factory=lambda: _env("OPENAI_VLM_MODEL", ""))

    # Scraping
    max_retries: int = 3
    timeout: int = 10
    scrape_delay: float = 0.2

    # Deep crawl: when enabled, the scraper follows internal links from the seed
    # URL (breadth-first) to cover the whole site and maximise the dataset.
    # Each discovered page triggers a clean + QA generation, so the limits below
    # bound the cost. Same-domain only by default.
    crawl_max_depth: int = field(
        default_factory=lambda: int(_env("CRAWL_MAX_DEPTH", "2"))
    )
    crawl_max_pages: int = field(
        default_factory=lambda: int(_env("CRAWL_MAX_PAGES", "50"))
    )
    crawl_same_domain: bool = field(
        default_factory=lambda: (
            _env("CRAWL_SAME_DOMAIN", "true").lower() not in ("0", "false", "no")
        )
    )
    # Cost controls. crawl_delay_seconds throttles the crawler by pausing between
    # page fetches (0 = no throttle). crawl_max_pages_per_domain caps pages taken
    # from any single host (0 = unlimited) — a budget that matters most when
    # crawl_same_domain is off and the crawl can span several domains.
    crawl_delay_seconds: float = field(
        default_factory=lambda: float(_env("CRAWL_DELAY_SECONDS", "0"))
    )
    crawl_max_pages_per_domain: int = field(
        default_factory=lambda: int(_env("CRAWL_MAX_PAGES_PER_DOMAIN", "0"))
    )

    # Dev log console: when true, the server exposes /debug/logs (SSE) so the
    # Next.js dev UI can stream server logs into an in-browser terminal. Toggle
    # with `DEBUG_LOGS=1 make dev`. Off by default (never enable in production).
    debug_logs: bool = field(
        default_factory=lambda: (
            _env("DEBUG_LOGS", "false").lower() not in ("0", "false", "no", "")
        )
    )

    # Authentication. The JWT is signed with HS256 using auth_secret_key and
    # delivered to the browser as an httpOnly cookie. Set AUTH_SECRET_KEY to a
    # long random value in any shared environment — the dev default is insecure
    # and only meant for local use (a warning is logged when it's in effect).
    auth_secret_key: str = field(
        default_factory=lambda: _env("AUTH_SECRET_KEY", "dev-insecure-secret-change-me")
    )
    # Access tokens are short-lived; sessions are kept alive by the refresh
    # token below (rotated on every use), so expiry here only bounds how long a
    # stolen access token stays valid — not how often users must log back in.
    auth_token_ttl_seconds: int = field(
        default_factory=lambda: int(_env("AUTH_TOKEN_TTL_SECONDS", str(60 * 15)))
    )
    # Refresh tokens are opaque, stored hashed server-side and single-use
    # (each POST /auth/refresh revokes the presented token and issues a new
    # one). This TTL is the maximum idle time before a user must log in again.
    auth_refresh_token_ttl_seconds: int = field(
        default_factory=lambda: int(
            _env("AUTH_REFRESH_TOKEN_TTL_SECONDS", str(60 * 60 * 24 * 14))
        )
    )
    auth_cookie_name: str = field(
        default_factory=lambda: _env("AUTH_COOKIE_NAME", "access_token")
    )
    auth_refresh_cookie_name: str = field(
        default_factory=lambda: _env("AUTH_REFRESH_COOKIE_NAME", "refresh_token")
    )
    # Send the cookie only over HTTPS. Default off for local http dev; set
    # AUTH_COOKIE_SECURE=true behind TLS.
    auth_cookie_secure: bool = field(
        default_factory=lambda: (
            _env("AUTH_COOKIE_SECURE", "false").lower() not in ("0", "false", "no", "")
        )
    )
    # Anti-brute-force on POST /auth/login: after auth_login_max_attempts failed
    # attempts from one client IP within auth_login_window_seconds, further
    # attempts get a 429 until the window slides. Backed by Redis when redis_url
    # is set (shared across workers/replicas), else in-process (see
    # services/rate_limit.py) — a first layer, not a distributed quota.
    auth_login_max_attempts: int = field(
        default_factory=lambda: int(_env("AUTH_LOGIN_MAX_ATTEMPTS", "10"))
    )
    auth_login_window_seconds: int = field(
        default_factory=lambda: int(_env("AUTH_LOGIN_WINDOW_SECONDS", "300"))
    )
    # Optional Redis backing store for the login rate limiter (and any future
    # shared state). When unset, the limiter falls back to in-process state.
    redis_url: str = field(default_factory=lambda: _env("REDIS_URL", ""))

    # Deployment environment. Gates fail-safe behaviours that must never be active
    # in a shared/production deployment — notably whether the dev-user seeding may
    # fall back to the weak built-in passwords (see ``seed_dev_users``). Defaults
    # to "production" so anything left unset is treated as untrusted (fail closed);
    # set ENVIRONMENT=development for local dev.
    environment: str = field(
        default_factory=lambda: _env("ENVIRONMENT", "production").strip().lower()
    )

    # When true, the two local dev accounts (see services/users.py) are seeded
    # on startup. Local-dev convenience only — keep off in shared environments.
    seed_dev_users: bool = field(
        default_factory=lambda: (
            _env("SEED_DEV_USERS", "false").lower() not in ("0", "false", "no", "")
        )
    )

    # OIDC (Infomaniak). Login via OpenID Connect is enabled only when the
    # client id/secret and the issuer are all set. The issuer must expose
    # <issuer>/.well-known/openid-configuration for discovery.
    oidc_issuer: str = field(default_factory=lambda: _env("OIDC_ISSUER", ""))
    oidc_client_id: str = field(default_factory=lambda: _env("OIDC_CLIENT_ID", ""))
    oidc_client_secret: str = field(
        default_factory=lambda: _env("OIDC_CLIENT_SECRET", "")
    )
    # Absolute URL of our callback route, registered with the provider.
    oidc_redirect_uri: str = field(
        default_factory=lambda: _env(
            "OIDC_REDIRECT_URI", "http://localhost:8000/auth/oidc/callback"
        )
    )
    oidc_scopes: str = field(
        default_factory=lambda: _env("OIDC_SCOPES", "openid email profile")
    )
    # Where to send the browser after a successful OIDC login.
    frontend_url: str = field(
        default_factory=lambda: _env("FRONTEND_URL", "http://localhost:3000")
    )

    # Browser origins allowed to make credentialed cross-origin calls. Comma-
    # separated; when unset it falls back to frontend_url alone. Never "*": the
    # session lives in cookies, and Starlette answers a credentialed request
    # with the *reflected* origin when allow_origins is "*", which would let any
    # site read authenticated responses (see cors_allow_origin_regex below for
    # how local dev keeps working without widening this).
    cors_allow_origins_raw: str = field(
        default_factory=lambda: _env("CORS_ALLOW_ORIGINS", "")
    )

    # When true (and Langfuse is configured), every generation also creates/updates
    # the dataset in Langfuse and records a versioned dataset run (DVC-like commit).
    langfuse_auto_sync: bool = field(
        default_factory=lambda: (
            _env("LANGFUSE_AUTO_SYNC", "true").lower() not in ("0", "false", "no")
        )
    )

    # Qdrant vector store. Pushing a dataset's Q/A pairs as embeddings into a
    # Qdrant collection is enabled only when qdrant_url is set; every endpoint
    # guards itself with a clear 503 otherwise (mirrors the Langfuse handling).
    # qdrant_api_key is optional (Qdrant Cloud / secured instances).
    qdrant_url: str = field(default_factory=lambda: _env("QDRANT_URL", ""))
    qdrant_api_key: str = field(default_factory=lambda: _env("QDRANT_API_KEY", ""))
    # Collection names are derived as f"{prefix}{sanitized_dataset_name}".
    qdrant_collection_prefix: str = field(
        default_factory=lambda: _env("QDRANT_COLLECTION_PREFIX", "dataset_")
    )

    # crawl4ai service (Docker). The scraper calls this REST API instead of
    # running crawl4ai in-process, keeping the browser stack out of this image.
    crawl4ai_base_url: str = field(
        default_factory=lambda: _env("CRAWL4AI_BASE_URL", "http://crawl4ai:11235")
    )
    crawl4ai_api_token: str = field(
        default_factory=lambda: _env("CRAWL4AI_API_TOKEN", "")
    )
    # Upper bound (seconds) for a single /md request: the service renders the
    # page in a browser, so this must comfortably exceed the page timeout.
    crawl4ai_timeout: int = field(
        default_factory=lambda: int(_env("CRAWL4AI_TIMEOUT", "120"))
    )

    # LLM
    max_tokens_cleaning: int = 3000
    max_tokens_qa: int = 4000
    temperature: float = 0.0

    # Defaults for runtime overrides (set via route)
    target_language: str = field(
        default_factory=lambda: _env("DEFAULT_TARGET_LANGUAGE", "en")
    )
    model_cleaning: str = field(default_factory=lambda: _env("OPENAI_LLM_MODEL", ""))
    model_qa: str = field(default_factory=lambda: _env("OPENAI_LLM_MODEL", ""))

    # Output
    output_formats: List[str] = field(default_factory=lambda: ["json", "jsonl", "csv"])
    scrapes_dir: str = "scrapes"
    datasets_dir: str = "datasets"

    # Available models, derived from the configured provider models
    available_models: List[str] = field(default_factory=list)

    @property
    def is_development(self) -> bool:
        """True only for an explicitly-declared local/dev environment."""
        return self.environment in ("development", "dev", "local")

    @property
    def cors_allow_origins(self) -> List[str]:
        """Explicit list of origins allowed to send credentialed requests."""
        explicit = [
            origin.strip()
            for origin in self.cors_allow_origins_raw.split(",")
            if origin.strip()
        ]
        if explicit:
            return explicit
        return [self.frontend_url] if self.frontend_url else []

    @property
    def cors_allow_origin_regex(self) -> Optional[str]:
        """Extra origin pattern accepted in development only.

        Local dev moves the front between ports (dev-port lanes, a second stack,
        `next dev -p …`), so pinning CORS to a single frontend_url would break as
        soon as the port changes. In development any localhost origin is allowed;
        outside it, only :attr:`cors_allow_origins` applies.
        """
        if not self.is_development:
            return None
        return r"https?://(localhost|127\.0\.0\.1)(:\d+)?$"

    # Validation
    def __post_init__(self):
        if not self.openai_api_key:
            raise EnvironmentError("OPENAI_API_KEY missing in .env")

        # Build the available-models list from every configured model,
        # de-duplicated and preserving order.
        candidates = [
            self.openai_llm_model,
            self.openai_vlm_model,
            self.model_cleaning,
            self.model_qa,
        ]
        self.available_models = list(dict.fromkeys(m for m in candidates if m))


config = Config()
