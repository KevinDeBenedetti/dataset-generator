from dataclasses import dataclass, field
from typing import List, Optional
import hashlib
import hmac
import logging
import os

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# Public (it is in this file), so it may only ever sign tokens in development.
DEV_AUTH_SECRET = "dev-insecure-secret-change-me"


def _env(name: str, default: str = "") -> str:
    """Read an env var, treating an empty/whitespace value as unset.

    ``os.getenv`` only falls back to its default when the variable is *absent*;
    `.env.example` ships optional keys blank and `make env` copies it verbatim,
    so a blank must mean "use the default" (an empty numeric key would otherwise
    crash ``int("")`` at import).
    """
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    return value


def _is_dev_env() -> bool:
    """True only for an explicitly-declared local/dev environment (read from the
    env at call time — defaults below depend on it, before ``Config`` exists)."""
    return _env("ENVIRONMENT", "production").strip().lower() in (
        "development",
        "dev",
        "local",
    )


def _is_ci() -> bool:
    """Running in a CI job (GitHub Actions sets both variables)."""
    return any(
        _env(name, "").strip().lower() in ("1", "true", "yes")
        for name in ("GITHUB_ACTIONS", "CI")
    )


def _flag(name: str, default: bool) -> bool:
    raw = _env(name, "")
    if not raw:
        return default
    return raw.strip().lower() not in ("0", "false", "no")


def _reasoning_effort() -> str:
    value = _env("OPENAI_REASONING_EFFORT", "low").strip().lower()
    return "" if value in ("off", "false", "0", "no", "disabled") else value


@dataclass
class Config:
    """Every setting the server reads, in one place.

    Only what differs between deployments comes from the environment; tuning
    values live here as constants, and everything a deployment can't get wrong
    is derived from ``ENVIRONMENT`` (development vs production).
    """

    # --- Deployment ---------------------------------------------------------
    # "development" for local runs; anything else (or unset) is production and
    # fails closed: secure cookies, SSO only, no server keys, no Claude, strict
    # startup checks (see production_problems).
    environment: str = field(
        default_factory=lambda: _env("ENVIRONMENT", "production").strip().lower()
    )
    # The browser-facing URL of the app, and of its API. In production the API is
    # served under the same host (``<FRONTEND_URL>/api``); development reaches
    # it directly (docker-compose sets API_PUBLIC_URL from SERVER_PORT).
    frontend_url: str = field(
        default_factory=lambda: _env("FRONTEND_URL", "http://localhost:3000")
    )
    api_public_url: str = field(default_factory=lambda: _env("API_PUBLIC_URL", ""))
    # Run Alembic in every process at startup. Off in Kubernetes, where a
    # pre-upgrade Job migrates once before the pods roll.
    run_migrations_on_startup: bool = field(
        default_factory=lambda: _flag("RUN_MIGRATIONS_ON_STARTUP", True)
    )
    redis_url: str = field(default_factory=lambda: _env("REDIS_URL", ""))

    # --- Secrets ------------------------------------------------------------
    # Signs the session JWTs (and, derived, the SSO state cookie). Production
    # refuses the public dev default.
    auth_secret_key: str = field(
        default_factory=lambda: _env("AUTH_SECRET_KEY", DEV_AUTH_SECRET)
    )
    # AES-GCM key ring for the keys users store ("id:key,id:key", first
    # encrypts — core/crypto.py). Kept apart from AUTH_SECRET_KEY so rotating one
    # never loses the other. Production requires it; development derives one.
    secrets_encryption_keys_raw: str = field(
        default_factory=lambda: _env("SECRETS_ENCRYPTION_KEYS", "")
    )

    # --- Sign-in ------------------------------------------------------------
    infomaniak_client_id: str = field(
        default_factory=lambda: _env("INFOMANIAK_CLIENT_ID", "")
    )
    infomaniak_client_secret: str = field(
        default_factory=lambda: _env("INFOMANIAK_CLIENT_SECRET", "")
    )
    github_client_id: str = field(default_factory=lambda: _env("GITHUB_CLIENT_ID", ""))
    github_client_secret: str = field(
        default_factory=lambda: _env("GITHUB_CLIENT_SECRET", "")
    )
    # Callbacks registered with each provider: <API_PUBLIC_URL>/auth/<provider>/callback
    # (filled in __post_init__).
    infomaniak_redirect_uri: str = ""
    github_redirect_uri: str = ""
    infomaniak_issuer: str = "https://login.infomaniak.com"
    infomaniak_scopes: str = "openid email profile"
    # Email + password sign-in: on in development, off in production unless
    # asked for (a deployment without SSO).
    enable_local_login: bool = field(
        default_factory=lambda: _flag("ENABLE_LOCAL_LOGIN", _is_dev_env())
    )
    # Accounts whose verified email is listed are always admins (promoted at
    # sign-in, locked in the backoffice) and receive the pre-multi-user data.
    admin_emails_raw: str = field(default_factory=lambda: _env("ADMIN_EMAILS", ""))
    # Providers whose *verified* email may attach a sign-in to an existing account.
    sso_trusted_email_providers_raw: str = "infomaniak,github"
    # Defaults of the backoffice platform switches (services/platform.py).
    allow_signup: bool = True
    allowed_email_domains_raw: str = ""
    allowed_llm_hosts_raw: str = ""
    allow_custom_base_url: bool = False

    # --- Sessions (derived from ENVIRONMENT, constants otherwise) -----------
    # Outside development the cookies are Secure and ``__Host-`` prefixed (a
    # sibling subdomain can neither set nor shadow them); the Next proxy uses
    # the same names, chosen by NODE_ENV.
    auth_cookie_secure: bool = field(default_factory=lambda: not _is_dev_env())
    auth_cookie_name: str = field(
        default_factory=lambda: (
            "access_token" if _is_dev_env() else "__Host-access_token"
        )
    )
    auth_refresh_cookie_name: str = field(
        default_factory=lambda: (
            "refresh_token" if _is_dev_env() else "__Host-refresh_token"
        )
    )
    # Short-lived access token; the session lives on in the rotated refresh token.
    auth_token_ttl_seconds: int = 15 * 60
    auth_refresh_token_ttl_seconds: int = 14 * 24 * 3600
    auth_issuer: str = "datasetgen"
    auth_audience: str = "datasetgen-api"
    # Two tabs refreshing at once present the same single-use token: within this
    # window the just-rotated token gets another successor instead of being
    # treated as theft.
    auth_refresh_reuse_grace_seconds: int = 10
    # Per-client-IP throttles. Login counts failures only (10 per 5 minutes).
    auth_login_max_attempts: int = 10
    auth_login_window_seconds: int = 300
    auth_refresh_max_per_minute: int = 60
    auth_sso_max_per_minute: int = 30
    # Swagger UI + /openapi.json: development only.
    docs_enabled: bool = field(default_factory=_is_dev_env)

    # --- Model providers ----------------------------------------------------
    # Models the OpenAI provider offers (per role), on each user's own key.
    openai_llm_model: str = field(default_factory=lambda: _env("OPENAI_LLM_MODEL", ""))
    openai_vlm_model: str = field(default_factory=lambda: _env("OPENAI_VLM_MODEL", ""))
    openai_embedding_model: str = field(
        default_factory=lambda: _env("OPENAI_EMBEDDING_MODEL", "")
    )
    # "low" keeps reasoning models from spending their budget thinking;
    # OPENAI_REASONING_EFFORT=off for models that reject the parameter (gpt-4o*).
    openai_reasoning_effort: str = field(default_factory=lambda: _reasoning_effort())
    # Fill what a user hasn't entered from the server's own keys (OPENAI_API_KEY,
    # HF_TOKEN…): development only — production never lends its keys.
    allow_env_credentials: bool = field(default_factory=_is_dev_env)
    # The Claude subscription provider runs in local development and CI only.
    enable_claude_provider: bool = field(
        default_factory=lambda: _is_dev_env() or _is_ci()
    )
    # Model ids the Claude provider offers (comma-separated; default: built-in list).
    claude_models_raw: str = field(default_factory=lambda: _env("CLAUDE_MODELS", ""))
    # Model of the scheduled jobs when no default is saved (the CI runs DB-free).
    qa_job_model: str = field(
        default_factory=lambda: _env("QA_JOB_MODEL", "claude:claude-sonnet-5")
    )

    # --- Jobs ---------------------------------------------------------------
    # Workers (python -m server.worker, services/queue.py). EMBEDDED_WORKER runs
    # one inside the API process (`make dev-local`).
    embedded_worker: bool = field(
        default_factory=lambda: _flag("EMBEDDED_WORKER", False)
    )
    worker_concurrency: int = field(
        default_factory=lambda: max(1, int(_env("WORKER_CONCURRENCY", "1")))
    )
    # On SIGTERM, how long a worker lets its current runs finish (keep below the
    # pod's terminationGracePeriodSeconds).
    worker_drain_seconds: float = field(
        default_factory=lambda: float(_env("WORKER_DRAIN_SECONDS", "25"))
    )
    worker_poll_seconds: float = 2.0
    worker_heartbeat_seconds: float = 10.0
    # A running job whose heartbeat is older than this is marked interrupted.
    worker_stale_seconds: float = 120.0
    # Per-user quotas (0 = unlimited).
    quota_active_runs: int = field(
        default_factory=lambda: int(_env("QUOTA_ACTIVE_RUNS", "2"))
    )
    quota_runs_per_day: int = field(
        default_factory=lambda: int(_env("QUOTA_RUNS_PER_DAY", "20"))
    )
    quota_datasets: int = field(
        default_factory=lambda: int(_env("QUOTA_DATASETS", "50"))
    )

    # --- Storage ------------------------------------------------------------
    # Store generated pairs and version each generation; off = pass-through.
    persist_datasets: bool = field(
        default_factory=lambda: _flag("PERSIST_DATASETS", True)
    )
    # Qdrant (vector search): enabled when QDRANT_URL is set.
    qdrant_url: str = field(default_factory=lambda: _env("QDRANT_URL", ""))
    qdrant_api_key: str = field(default_factory=lambda: _env("QDRANT_API_KEY", ""))
    # Lets several environments share one Qdrant.
    qdrant_collection_prefix: str = field(
        default_factory=lambda: _env("QDRANT_COLLECTION_PREFIX", "dataset_")
    )

    # --- Local embeddings (services/semantic.py) ----------------------------
    # FastEmbed/ONNX, no API call: semantic dedup, the "don't ask these again"
    # list, uncovered sections and the answer grounding check. Disabled (or
    # when the model can't load), callers fall back to the lexical path.
    semantic_enabled: bool = field(
        default_factory=lambda: _flag("SEMANTIC_ENABLED", True)
    )
    semantic_model: str = field(
        default_factory=lambda: _env(
            "SEMANTIC_MODEL",
            "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        )
    )
    # Question ↔ question cosine at or above which a new pair is a duplicate.
    semantic_dedup_threshold: float = field(
        default_factory=lambda: float(_env("SEMANTIC_DEDUP_THRESHOLD", "0.85"))
    )
    # Answer ↔ best source chunk cosine below which the answer is flagged for
    # review (faithful paraphrases score ~0.45–0.65, off-topic ~0.3–0.4).
    answer_grounding_threshold: float = field(
        default_factory=lambda: float(_env("ANSWER_GROUNDING_THRESHOLD", "0.35"))
    )
    # Source section ↔ best question cosine below which a section is uncovered.
    uncovered_section_threshold: float = field(
        default_factory=lambda: float(_env("UNCOVERED_SECTION_THRESHOLD", "0.4"))
    )
    # Where the ~220 MB model is cached (FastEmbed's default is a temp dir).
    fastembed_cache_path: str = field(
        default_factory=lambda: _env("FASTEMBED_CACHE_PATH", "")
    )

    # --- Development --------------------------------------------------------
    # Seed the two local accounts (services/users.py).
    seed_dev_users: bool = field(default_factory=lambda: _flag("SEED_DEV_USERS", False))
    # Stream server logs into an in-browser console (/debug/logs). Never in
    # shared environments.
    debug_logs: bool = field(default_factory=lambda: _flag("DEBUG_LOGS", False))

    # --- Generation constants -----------------------------------------------
    max_tokens_cleaning: int = 3000
    max_tokens_qa: int = 4000
    temperature: float = 0.0
    # Default language when a request names none.
    target_language: str = "en"
    model_cleaning: str = field(default_factory=lambda: _env("OPENAI_LLM_MODEL", ""))
    model_qa: str = field(default_factory=lambda: _env("OPENAI_LLM_MODEL", ""))
    # Every configured OpenAI model id, de-duplicated (filled in __post_init__).
    available_models: List[str] = field(default_factory=list)

    @property
    def session_cookie_name(self) -> str:
        return "session" if self.is_development else "__Host-session"

    @property
    def effective_session_secret(self) -> str:
        """The key signing the short-lived SSO state cookie: derived from
        AUTH_SECRET_KEY (domain-separated), so it is never the JWT key itself."""
        return hmac.new(
            self.auth_secret_key.encode(), b"datasetgen/sso-state", hashlib.sha256
        ).hexdigest()

    @property
    def public_api_url(self) -> str:
        """The API as the browser and the SSO providers reach it."""
        if self.api_public_url:
            return self.api_public_url.rstrip("/")
        if self.is_development:
            return "http://localhost:8000"
        return f"{self.frontend_url.rstrip('/')}/api"

    def production_problems(self) -> List[str]:
        """What makes this configuration unsafe to serve real users with.

        Empty in development. Checked at startup (see ``ensure_production_config``)
        so a deployment that forgot a setting refuses to boot. (The JWT secret is
        checked separately: services/auth.ensure_secret_is_safe.)
        """
        if self.is_development:
            return []
        problems: List[str] = []
        if not _env("DATABASE_URL"):
            problems.append(
                "DATABASE_URL is required (the fallback is the local dev database "
                "with default credentials)"
            )
        if not self.secrets_encryption_keys_raw:
            problems.append(
                "SECRETS_ENCRYPTION_KEYS is required (generate a key with "
                "`python -m server.cli gen-key`)"
            )
        else:
            from server.core.crypto import CryptoError, parse_ring

            try:
                parse_ring(self.secrets_encryption_keys_raw)
            except CryptoError as exc:
                problems.append(f"SECRETS_ENCRYPTION_KEYS is invalid: {exc}")
        sso = (self.infomaniak_client_id and self.infomaniak_client_secret) or (
            self.github_client_id and self.github_client_secret
        )
        if not sso and not self.enable_local_login:
            problems.append(
                "No sign-in method: set INFOMANIAK_CLIENT_ID/SECRET or "
                "GITHUB_CLIENT_ID/SECRET (or ENABLE_LOCAL_LOGIN=true)"
            )
        if not self.frontend_url.lower().startswith("https://"):
            problems.append(
                f"FRONTEND_URL must be the public https URL (got '{self.frontend_url}')"
            )
        return problems

    def ensure_production_config(self) -> None:
        """Raise RuntimeError listing every :meth:`production_problems` entry."""
        problems = self.production_problems()
        if problems:
            raise RuntimeError(
                "Unsafe production configuration:\n  - " + "\n  - ".join(problems)
            )

    @property
    def claude_provider_available(self) -> bool:
        """The Claude provider may run here: development or CI, and not switched off."""
        return self.enable_claude_provider and (self.is_development or _is_ci())

    @staticmethod
    def _csv(raw: str) -> List[str]:
        return [part.strip().lower() for part in raw.split(",") if part.strip()]

    @property
    def admin_emails(self) -> List[str]:
        return self._csv(self.admin_emails_raw)

    @property
    def allowed_email_domains(self) -> List[str]:
        return [d.lstrip("@") for d in self._csv(self.allowed_email_domains_raw)]

    @property
    def sso_trusted_email_providers(self) -> List[str]:
        return self._csv(self.sso_trusted_email_providers_raw)

    @property
    def allowed_llm_hosts(self) -> List[str]:
        extra = [h.strip().lower() for h in self.allowed_llm_hosts_raw.split(",")]
        return ["api.openai.com", *[h for h in extra if h]]

    @property
    def is_development(self) -> bool:
        """True only for an explicitly-declared local/dev environment."""
        return self.environment in ("development", "dev", "local")

    @property
    def cors_allow_origins(self) -> List[str]:
        """Origins allowed to send credentialed requests: the app itself.

        Never "*": the session lives in cookies, and Starlette answers a
        credentialed request with the *reflected* origin when allow_origins is
        "*", which would let any site read authenticated responses.
        """
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

    def __post_init__(self):
        api = self.public_api_url
        self.infomaniak_redirect_uri = (
            self.infomaniak_redirect_uri or f"{api}/auth/infomaniak/callback"
        )
        self.github_redirect_uri = (
            self.github_redirect_uri or f"{api}/auth/github/callback"
        )
        candidates = [
            self.openai_llm_model,
            self.openai_vlm_model,
            self.model_cleaning,
            self.model_qa,
        ]
        self.available_models = list(dict.fromkeys(m for m in candidates if m))


config = Config()
