from dataclasses import dataclass, field
from typing import List, Optional
import logging
import os

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# Public (it is in this file), so it may only ever sign tokens in development.
DEV_AUTH_SECRET = "dev-insecure-secret-change-me"


def _env(name: str, default: str = "") -> str:
    """Read an env var, treating an empty/whitespace value as unset.

    ``os.getenv`` only falls back to its default when the variable is *absent*:
    a key present but blank wins with "". `.env.example` ships several keys that
    way (``AUTH_REFRESH_COOKIE_NAME=``, ``AUTH_TOKEN_TTL_SECONDS=``, ...) and `make env`
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
    # API Configuration (single OpenAI-compatible provider)
    openai_api_key: str = field(default_factory=lambda: _env("OPENAI_API_KEY", ""))
    openai_base_url: str = field(default_factory=lambda: _env("OPENAI_BASE_URL", ""))

    # Reasoning models (e.g. gpt-oss) emit a chain-of-thought before the answer.
    # "low" keeps that short so the agent reliably reaches the final JSON.
    # Set OPENAI_REASONING_EFFORT=off to not send the param at all, for models
    # that reject it (gpt-4o, gpt-4o-mini…). A blank value means the default,
    # like every other key, so it cannot be the off switch.
    openai_reasoning_effort: str = field(default_factory=lambda: _reasoning_effort())

    # Models (one per role, from the configured provider)
    openai_llm_model: str = field(default_factory=lambda: _env("OPENAI_LLM_MODEL", ""))
    openai_embedding_model: str = field(
        default_factory=lambda: _env("OPENAI_EMBEDDING_MODEL", "")
    )
    openai_vlm_model: str = field(default_factory=lambda: _env("OPENAI_VLM_MODEL", ""))

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
    # and the server refuses to start with it outside development.
    auth_secret_key: str = field(
        default_factory=lambda: _env("AUTH_SECRET_KEY", DEV_AUTH_SECRET)
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
    # Outside development the cookies carry the ``__Host-`` prefix: browsers then
    # only accept them Secure, host-only (no Domain) and on Path=/, so a
    # sibling subdomain can neither set nor shadow them. The front-end proxy
    # reads the same names (AUTH_COOKIE_NAME / AUTH_REFRESH_COOKIE_NAME at
    # runtime, with the same defaults).
    auth_cookie_name: str = field(
        default_factory=lambda: _env(
            "AUTH_COOKIE_NAME",
            "access_token" if _is_dev_env() else "__Host-access_token",
        )
    )
    auth_refresh_cookie_name: str = field(
        default_factory=lambda: _env(
            "AUTH_REFRESH_COOKIE_NAME",
            "refresh_token" if _is_dev_env() else "__Host-refresh_token",
        )
    )
    # Claims every access token must carry and every check must find.
    auth_issuer: str = field(default_factory=lambda: _env("AUTH_ISSUER", "datasetgen"))
    auth_audience: str = field(
        default_factory=lambda: _env("AUTH_AUDIENCE", "datasetgen-api")
    )
    # Two tabs (or the Next server and a tab) refreshing at once present the same
    # single-use refresh token. Within this window a token that was *just*
    # rotated is answered with another successor of the same family instead of
    # being treated as theft; beyond it, reuse revokes the family. 0 disables.
    auth_refresh_reuse_grace_seconds: int = field(
        default_factory=lambda: int(_env("AUTH_REFRESH_REUSE_GRACE_SECONDS", "10"))
    )
    # Per-client-IP throttles (requests per minute) on the endpoints that mint
    # sessions or start an SSO flow — the login limiter only counts failures.
    auth_refresh_max_per_minute: int = field(
        default_factory=lambda: int(_env("AUTH_REFRESH_MAX_PER_MINUTE", "60"))
    )
    auth_sso_max_per_minute: int = field(
        default_factory=lambda: int(_env("AUTH_SSO_MAX_PER_MINUTE", "30"))
    )
    # Separate secret for the short-lived cookie holding the OAuth state/nonce,
    # so one leaked secret doesn't forge both sessions and SSO callbacks.
    # Falls back to auth_secret_key in development only.
    session_secret_key: str = field(
        default_factory=lambda: _env("SESSION_SECRET_KEY", "")
    )
    # AES-GCM key ring for the secrets users store ("id:key,id:key", first
    # encrypts — see core/crypto.py). Required in production; development derives
    # a key from AUTH_SECRET_KEY.
    secrets_encryption_keys_raw: str = field(
        default_factory=lambda: _env("SECRETS_ENCRYPTION_KEYS", "")
    )
    # Fill credentials a user hasn't entered from the server's own env vars
    # (OPENAI_API_KEY, HF_TOKEN…). A development convenience and what the
    # scheduled CI jobs use; off in production so one account's key can never
    # end up paying for another's requests.
    allow_env_credentials: bool = field(
        default_factory=lambda: _flag("ALLOW_ENV_CREDENTIALS", _is_dev_env())
    )
    # The Claude-subscription provider (Claude Agent SDK). Local development and
    # the CI jobs only: a deployed server never offers it, whatever this says
    # (see ``claude_provider_available``).
    enable_claude_provider: bool = field(
        default_factory=lambda: _flag(
            "ENABLE_CLAUDE_PROVIDER", _is_dev_env() or _is_ci()
        )
    )
    # Hosts a user's OpenAI-compatible base URL may point to, besides
    # api.openai.com; ALLOW_CUSTOM_BASE_URL lifts the restriction (still
    # https-only and never a private address).
    allowed_llm_hosts_raw: str = field(
        default_factory=lambda: _env("ALLOWED_LLM_HOSTS", "")
    )
    allow_custom_base_url: bool = field(
        default_factory=lambda: _flag("ALLOW_CUSTOM_BASE_URL", False)
    )
    # Email + password login. On in development; off elsewhere unless enabled
    # (production accounts sign in through SSO).
    enable_local_login: bool = field(
        default_factory=lambda: _flag("ENABLE_LOCAL_LOGIN", _is_dev_env())
    )
    # Run Alembic in every process at startup. Turn off in Kubernetes, where a
    # pre-upgrade Job migrates once before the pods roll.
    run_migrations_on_startup: bool = field(
        default_factory=lambda: _flag("RUN_MIGRATIONS_ON_STARTUP", True)
    )
    # Swagger UI + /openapi.json. Development only unless asked for.
    docs_enabled: bool = field(
        default_factory=lambda: _flag("DOCS_ENABLED", _is_dev_env())
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
    # attempts get a 429 until the window expires. Backed by Redis when redis_url
    # is set — via redis-fastapi's atomic window counter, shared across
    # workers/replicas — else by an in-process sliding window (see
    # services/rate_limit.py), a first layer rather than a distributed quota.
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
    # GitHub sign-in (an OAuth App: github.com/settings/developers). Enabled
    # when both are set. The callback is <api>/auth/github/callback.
    github_client_id: str = field(default_factory=lambda: _env("GITHUB_CLIENT_ID", ""))
    github_client_secret: str = field(
        default_factory=lambda: _env("GITHUB_CLIENT_SECRET", "")
    )
    github_redirect_uri: str = field(
        default_factory=lambda: _env(
            "GITHUB_REDIRECT_URI", "http://localhost:8000/auth/github/callback"
        )
    )
    # Accounts whose (verified) email is listed here are always admins: promoted
    # at sign-in, and shown locked in the backoffice (no demotion/deactivation).
    admin_emails_raw: str = field(default_factory=lambda: _env("ADMIN_EMAILS", ""))
    # Whether an SSO sign-in with no matching account creates one. ADMIN_EMAILS
    # can always sign up.
    allow_signup: bool = field(default_factory=lambda: _flag("ALLOW_SIGNUP", True))
    # When set, only verified emails in these domains may sign up.
    allowed_email_domains_raw: str = field(
        default_factory=lambda: _env("ALLOWED_EMAIL_DOMAINS", "")
    )
    # Providers whose *verified* email may link a sign-in to an existing account
    # with that email (otherwise linking needs an active session).
    sso_trusted_email_providers_raw: str = field(
        default_factory=lambda: _env("SSO_TRUSTED_EMAIL_PROVIDERS", "infomaniak,github")
    )
    # Job workers (python -m server.worker, services/queue.py).
    worker_poll_seconds: float = field(
        default_factory=lambda: float(_env("WORKER_POLL_SECONDS", "2"))
    )
    worker_heartbeat_seconds: float = field(
        default_factory=lambda: float(_env("WORKER_HEARTBEAT_SECONDS", "10"))
    )
    # A running job whose heartbeat is older than this is marked interrupted.
    worker_stale_seconds: float = field(
        default_factory=lambda: float(_env("WORKER_STALE_SECONDS", "120"))
    )
    worker_concurrency: int = field(
        default_factory=lambda: max(1, int(_env("WORKER_CONCURRENCY", "1")))
    )
    # On SIGTERM, how long a worker lets its current runs finish before leaving.
    worker_drain_seconds: float = field(
        default_factory=lambda: float(_env("WORKER_DRAIN_SECONDS", "25"))
    )
    # Also run a worker inside the API process (single-process local runs, e.g.
    # `make dev-local`). Deployments run dedicated workers instead.
    embedded_worker: bool = field(
        default_factory=lambda: _flag("EMBEDDED_WORKER", False)
    )
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

    # When true, every generation writes its pairs to Postgres and records a
    # versioned run (DVC-like commit). Turning it off makes generation a
    # pass-through: the pairs come back in the response and nothing is stored.
    persist_datasets: bool = field(
        default_factory=lambda: (
            _env("PERSIST_DATASETS", "true").lower() not in ("0", "false", "no")
        )
    )

    # Hugging Face Hub export. Only enabled when a write token is set; the
    # endpoint answers 503 otherwise. Exported repos are always private (see
    # services/huggingface.py). hf_namespace (user or organization) is optional
    # — the token's own account is used when it's blank.
    hf_token: str = field(default_factory=lambda: _env("HF_TOKEN", ""))
    hf_namespace: str = field(default_factory=lambda: _env("HF_NAMESPACE", ""))

    # Qdrant vector store. Pushing a dataset's Q/A pairs as embeddings into a
    # Qdrant collection is enabled only when qdrant_url is set; every endpoint
    # guards itself with a clear 503 otherwise.
    # qdrant_api_key is optional (Qdrant Cloud / secured instances).
    qdrant_url: str = field(default_factory=lambda: _env("QDRANT_URL", ""))
    qdrant_api_key: str = field(default_factory=lambda: _env("QDRANT_API_KEY", ""))
    # Collection names are derived as f"{prefix}{sanitized_dataset_name}".
    qdrant_collection_prefix: str = field(
        default_factory=lambda: _env("QDRANT_COLLECTION_PREFIX", "dataset_")
    )

    # Claude subscription provider (services/providers/claude.py): calls go
    # through the Claude Agent SDK, authenticated with CLAUDE_CODE_OAUTH_TOKEN
    # (`claude setup-token`) or ANTHROPIC_API_KEY. CLAUDE_MODELS overrides the
    # model list offered in the UI (comma-separated ids).
    claude_models_raw: str = field(default_factory=lambda: _env("CLAUDE_MODELS", ""))
    # Model used by the scheduled jobs when no default is set in the DB (the CI
    # runs DB-free): a "<provider>:<model>" reference.
    qa_job_model: str = field(
        default_factory=lambda: _env(
            "QA_JOB_MODEL", f"claude:{_env('CLAUDE_MODEL', 'claude-sonnet-5')}"
        )
    )

    # Local sentence embeddings (services/semantic.py) — FastEmbed/ONNX, no API
    # call. Back semantic dedup, the "don't ask these again" prompt list,
    # uncovered-section detection and the answer grounding check. Disabled, or
    # when the model can't load, every caller falls back to the lexical path.
    # The multilingual model scores a question and its translation ~0.97, so
    # dedup works across the fr/en/es/de target languages.
    semantic_enabled: bool = field(
        default_factory=lambda: (
            _env("SEMANTIC_ENABLED", "true").lower() not in ("0", "false", "no")
        )
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
    # review. Measured on the default model: faithful paraphrases score
    # ~0.45–0.65, off-topic answers ~0.3–0.4 — it catches drift away from the
    # source, not a factual error stated on the right topic.
    answer_grounding_threshold: float = field(
        default_factory=lambda: float(_env("ANSWER_GROUNDING_THRESHOLD", "0.35"))
    )
    # Source section ↔ best question cosine below which the section counts as
    # a topic no question covers yet.
    uncovered_section_threshold: float = field(
        default_factory=lambda: float(_env("UNCOVERED_SECTION_THRESHOLD", "0.4"))
    )
    # Where the ONNX model is cached (FastEmbed's own default is a temp dir,
    # which re-downloads ~220 MB after every reboot/container recreate).
    fastembed_cache_path: str = field(
        default_factory=lambda: _env("FASTEMBED_CACHE_PATH", "")
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

    # Available models, derived from the configured provider models
    available_models: List[str] = field(default_factory=list)

    @property
    def session_cookie_name(self) -> str:
        return "session" if self.is_development else "__Host-session"

    @property
    def effective_session_secret(self) -> str:
        """The secret signing the OAuth-state cookie (dev falls back to the JWT one)."""
        return self.session_secret_key or self.auth_secret_key

    def production_problems(self) -> List[str]:
        """What makes this configuration unsafe to serve real users with.

        Empty in development. Checked at startup (see ``ensure_production_config``)
        so a deployment that forgot a setting refuses to boot instead of running
        with cookies over plain http, the dev database or one shared secret.
        """
        if self.is_development:
            return []
        problems: List[str] = []
        if not self.auth_cookie_secure:
            problems.append(
                "AUTH_COOKIE_SECURE must be true (the session cookies are __Host- "
                "prefixed and browsers only accept those over https)"
            )
        for label, name in (
            ("AUTH_COOKIE_NAME", self.auth_cookie_name),
            ("AUTH_REFRESH_COOKIE_NAME", self.auth_refresh_cookie_name),
        ):
            if not name.startswith("__Host-"):
                problems.append(f"{label} must start with '__Host-' (got '{name}')")
        if not _env("DATABASE_URL"):
            problems.append(
                "DATABASE_URL is required (the fallback is the local dev database "
                "with default credentials)"
            )
        if not self.session_secret_key:
            problems.append("SESSION_SECRET_KEY is required")
        elif self.session_secret_key == self.auth_secret_key:
            problems.append("SESSION_SECRET_KEY must differ from AUTH_SECRET_KEY")
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
        if _flag("ENABLE_CLAUDE_PROVIDER", False) and not _is_ci():
            problems.append(
                "ENABLE_CLAUDE_PROVIDER must not be set: the Claude subscription "
                "provider is for local development and CI only"
            )
        if self.allow_env_credentials:
            problems.append(
                "ALLOW_ENV_CREDENTIALS must be false (users bring their own keys)"
            )
        sso = (
            self.oidc_issuer and self.oidc_client_id and self.oidc_client_secret
        ) or (self.github_client_id and self.github_client_secret)
        if not sso and not self.enable_local_login:
            problems.append(
                "No sign-in method: configure Infomaniak (OIDC_*) or GitHub "
                "(GITHUB_CLIENT_ID/SECRET), or enable ENABLE_LOCAL_LOGIN"
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
        if self.allow_env_credentials and not self.openai_api_key:
            # Logged rather than raised: the API-dependent routes fail on their
            # own 503/401 when this is missing, and letting the process crash
            # at import time takes down every other route (health checks,
            # auth, etc.) along with it.
            logger.error(
                "OPENAI_API_KEY missing in .env — OpenAI-backed features are disabled"
            )

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
