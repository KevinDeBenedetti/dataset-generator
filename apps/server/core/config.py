from dataclasses import dataclass, field
from typing import List
import os

from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    # API Configuration (single OpenAI-compatible provider)
    openai_api_key: str = field(default_factory=lambda: os.getenv("OPENAI_API_KEY", ""))
    openai_base_url: str = field(
        default_factory=lambda: os.getenv("OPENAI_BASE_URL", "")
    )

    # Reasoning models (e.g. gpt-oss) emit a chain-of-thought before the answer.
    # "low" keeps that short so the agent reliably reaches the final JSON.
    # Set OPENAI_REASONING_EFFORT="" to disable for models that reject the param.
    openai_reasoning_effort: str = field(
        default_factory=lambda: os.getenv("OPENAI_REASONING_EFFORT", "low")
    )

    # Models (one per role, from the configured provider)
    openai_llm_model: str = field(
        default_factory=lambda: os.getenv("OPENAI_LLM_MODEL", "")
    )
    openai_embedding_model: str = field(
        default_factory=lambda: os.getenv("OPENAI_EMBEDDING_MODEL", "")
    )
    openai_vlm_model: str = field(
        default_factory=lambda: os.getenv("OPENAI_VLM_MODEL", "")
    )

    # Scraping
    max_retries: int = 3
    timeout: int = 10
    scrape_delay: float = 0.2

    # Deep crawl: when enabled, the scraper follows internal links from the seed
    # URL (breadth-first) to cover the whole site and maximise the dataset.
    # Each discovered page triggers a clean + QA generation, so the limits below
    # bound the cost. Same-domain only by default.
    crawl_max_depth: int = field(
        default_factory=lambda: int(os.getenv("CRAWL_MAX_DEPTH", "2"))
    )
    crawl_max_pages: int = field(
        default_factory=lambda: int(os.getenv("CRAWL_MAX_PAGES", "50"))
    )
    crawl_same_domain: bool = field(
        default_factory=lambda: (
            os.getenv("CRAWL_SAME_DOMAIN", "true").lower() not in ("0", "false", "no")
        )
    )
    # Cost controls. crawl_delay_seconds throttles the crawler by pausing between
    # page fetches (0 = no throttle). crawl_max_pages_per_domain caps pages taken
    # from any single host (0 = unlimited) — a budget that matters most when
    # crawl_same_domain is off and the crawl can span several domains.
    crawl_delay_seconds: float = field(
        default_factory=lambda: float(os.getenv("CRAWL_DELAY_SECONDS", "0"))
    )
    crawl_max_pages_per_domain: int = field(
        default_factory=lambda: int(os.getenv("CRAWL_MAX_PAGES_PER_DOMAIN", "0"))
    )

    # Dev log console: when true, the server exposes /debug/logs (SSE) so the
    # Next.js dev UI can stream server logs into an in-browser terminal. Toggle
    # with `DEBUG_LOGS=1 make dev`. Off by default (never enable in production).
    debug_logs: bool = field(
        default_factory=lambda: (
            os.getenv("DEBUG_LOGS", "false").lower() not in ("0", "false", "no", "")
        )
    )

    # Authentication. The JWT is signed with HS256 using auth_secret_key and
    # delivered to the browser as an httpOnly cookie. Set AUTH_SECRET_KEY to a
    # long random value in any shared environment — the dev default is insecure
    # and only meant for local use (a warning is logged when it's in effect).
    auth_secret_key: str = field(
        default_factory=lambda: os.getenv(
            "AUTH_SECRET_KEY", "dev-insecure-secret-change-me"
        )
    )
    auth_token_ttl_seconds: int = field(
        default_factory=lambda: int(
            os.getenv("AUTH_TOKEN_TTL_SECONDS", str(60 * 60 * 24))
        )
    )
    auth_cookie_name: str = field(
        default_factory=lambda: os.getenv("AUTH_COOKIE_NAME", "access_token")
    )
    # Send the cookie only over HTTPS. Default off for local http dev; set
    # AUTH_COOKIE_SECURE=true behind TLS.
    auth_cookie_secure: bool = field(
        default_factory=lambda: (
            os.getenv("AUTH_COOKIE_SECURE", "false").lower()
            not in ("0", "false", "no", "")
        )
    )
    # Anti-brute-force on POST /auth/login: after auth_login_max_attempts failed
    # attempts from one client IP within auth_login_window_seconds, further
    # attempts get a 429 until the window slides. Backed by Redis when redis_url
    # is set (shared across workers/replicas), else in-process (see
    # services/rate_limit.py) — a first layer, not a distributed quota.
    auth_login_max_attempts: int = field(
        default_factory=lambda: int(os.getenv("AUTH_LOGIN_MAX_ATTEMPTS", "10"))
    )
    auth_login_window_seconds: int = field(
        default_factory=lambda: int(os.getenv("AUTH_LOGIN_WINDOW_SECONDS", "300"))
    )
    # Optional Redis backing store for the login rate limiter (and any future
    # shared state). When unset, the limiter falls back to in-process state.
    redis_url: str = field(default_factory=lambda: os.getenv("REDIS_URL", ""))

    # When true, the two local dev accounts (see services/users.py) are seeded
    # on startup. Local-dev convenience only — keep off in shared environments.
    seed_dev_users: bool = field(
        default_factory=lambda: (
            os.getenv("SEED_DEV_USERS", "false").lower() not in ("0", "false", "no", "")
        )
    )

    # OIDC (Infomaniak). Login via OpenID Connect is enabled only when the
    # client id/secret and the issuer are all set. The issuer must expose
    # <issuer>/.well-known/openid-configuration for discovery.
    oidc_issuer: str = field(default_factory=lambda: os.getenv("OIDC_ISSUER", ""))
    oidc_client_id: str = field(default_factory=lambda: os.getenv("OIDC_CLIENT_ID", ""))
    oidc_client_secret: str = field(
        default_factory=lambda: os.getenv("OIDC_CLIENT_SECRET", "")
    )
    # Absolute URL of our callback route, registered with the provider.
    oidc_redirect_uri: str = field(
        default_factory=lambda: os.getenv(
            "OIDC_REDIRECT_URI", "http://localhost:8000/auth/oidc/callback"
        )
    )
    oidc_scopes: str = field(
        default_factory=lambda: os.getenv("OIDC_SCOPES", "openid email profile")
    )
    # Where to send the browser after a successful OIDC login.
    frontend_url: str = field(
        default_factory=lambda: os.getenv("FRONTEND_URL", "http://localhost:3000")
    )

    # When true (and Langfuse is configured), every generation also creates/updates
    # the dataset in Langfuse and records a versioned dataset run (DVC-like commit).
    langfuse_auto_sync: bool = field(
        default_factory=lambda: (
            os.getenv("LANGFUSE_AUTO_SYNC", "true").lower() not in ("0", "false", "no")
        )
    )

    # Qdrant vector store. Pushing a dataset's Q/A pairs as embeddings into a
    # Qdrant collection is enabled only when qdrant_url is set; every endpoint
    # guards itself with a clear 503 otherwise (mirrors the Langfuse handling).
    # qdrant_api_key is optional (Qdrant Cloud / secured instances).
    qdrant_url: str = field(default_factory=lambda: os.getenv("QDRANT_URL", ""))
    qdrant_api_key: str = field(default_factory=lambda: os.getenv("QDRANT_API_KEY", ""))
    # Collection names are derived as f"{prefix}{sanitized_dataset_name}".
    qdrant_collection_prefix: str = field(
        default_factory=lambda: os.getenv("QDRANT_COLLECTION_PREFIX", "dataset_")
    )

    # crawl4ai service (Docker). The scraper calls this REST API instead of
    # running crawl4ai in-process, keeping the browser stack out of this image.
    crawl4ai_base_url: str = field(
        default_factory=lambda: os.getenv("CRAWL4AI_BASE_URL", "http://crawl4ai:11235")
    )
    crawl4ai_api_token: str = field(
        default_factory=lambda: os.getenv("CRAWL4AI_API_TOKEN", "")
    )
    # Upper bound (seconds) for a single /md request: the service renders the
    # page in a browser, so this must comfortably exceed the page timeout.
    crawl4ai_timeout: int = field(
        default_factory=lambda: int(os.getenv("CRAWL4AI_TIMEOUT", "120"))
    )

    # LLM
    max_tokens_cleaning: int = 3000
    max_tokens_qa: int = 4000
    temperature: float = 0.0

    # Defaults for runtime overrides (set via route)
    target_language: str = field(
        default_factory=lambda: os.getenv("DEFAULT_TARGET_LANGUAGE", "en")
    )
    model_cleaning: str = field(
        default_factory=lambda: os.getenv("OPENAI_LLM_MODEL", "")
    )
    model_qa: str = field(default_factory=lambda: os.getenv("OPENAI_LLM_MODEL", ""))

    # Output
    output_formats: List[str] = field(default_factory=lambda: ["json", "jsonl", "csv"])
    scrapes_dir: str = "scrapes"
    datasets_dir: str = "datasets"

    # Available models, derived from the configured provider models
    available_models: List[str] = field(default_factory=list)

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
