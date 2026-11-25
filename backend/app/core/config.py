from functools import lru_cache
from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    APPWRITE_ENDPOINT: str = "https://cloud.appwrite.io/v1"
    APPWRITE_PROJECT_ID: str = ""
    APPWRITE_API_KEY: str = ""
    APPWRITE_DATABASE_ID: str = ""
    APPWRITE_URLS_TABLE_ID: str = "urls"

    APPWRITE_CHECKS_TABLE_ID: str = "checks"
    APPWRITE_GOOGLE_CONNECTIONS_TABLE_ID: str = "google_connections"
    APPWRITE_GSC_TARGETS_TABLE_ID: str = "gsc_targets"
    APPWRITE_GSC_HISTORY_TABLE_ID: str = "gsc_history"
    APPWRITE_GOOGLE_QUOTA_TABLE_ID: str = "google_quota"
    APPWRITE_GOOGLE_OAUTH_STATES_TABLE_ID: str = "google_oauth_states"
    APPWRITE_BATCH_SHARING_TABLE_ID: str = "batch_sharing"

    # --- Data retention (see docs/legal/privacy-policy.md; the policy text must match these numbers) ---
    RETENTION_ENABLED: bool = True
    RETENTION_CHECK_BATCH_DAYS: int = 90  # backlink-check batches and their results
    RETENTION_SUBMISSION_DAYS: int = 90  # finished indexing submissions (completed / submitted / failed)
    RETENTION_GSC_HISTORY_DAYS: int = 365  # Google inspection history
    RETENTION_OAUTH_STATE_HOURS: int = 1  # consumed OAuth state nonces
    RETENTION_QUOTA_DAYS: int = 7  # per-day Google quota counters

    # Encrypts backup files (scripts/backup_export.py). Separate from TOKEN_ENCRYPTION_KEY; losing it makes backups unreadable.
    BACKUP_ENCRYPTION_KEY: str = ""
    APPWRITE_CHECK_BATCHES_TABLE_ID: str = "check_batches"

    INDEXNOW_KEY: str = ""
    INDEXNOW_ENDPOINT: str = "https://api.indexnow.org/indexnow"

    # Optional explicit key file URL (IndexNow "keyLocation"); default is https://<host>/<key>.txt
    INDEXNOW_KEY_LOCATION: str = ""

    # Discovery channels
    WAYBACK_SAVE: bool = False  # also ask the Internet Archive to save each URL (rate limited)
    PING_ENDPOINTS: Annotated[list[str], NoDecode] = ["http://rpc.pingomatic.com/"]
    PING_INTERVAL_SECONDS: int = 900
    # WebSub hubs notified (and advertised in the feed) when new URLs are published.
    WEBSUB_HUBS: Annotated[list[str], NoDecode] = ["https://pubsubhubbub.appspot.com/"]

    WORKER_COUNT: int = 2
    WORKER_BATCH_SIZE: int = 5
    # Idle workers sleep until woken in-process. This slow poll is only the safety net (restarts, other processes, retry
    # times that arrive while idle). Lower = faster recovery, more Appwrite reads. 60 s minimum.
    WORKER_FALLBACK_POLL_SECONDS: int = 240
    # Backlink checker workers (Check My Backlinks)
    CHECK_WORKER_COUNT: int = 2
    CHECK_WORKER_BATCH_SIZE: int = 10
    CHECK_MAX_ATTEMPTS: int = 2
    CHECK_PER_HOST_CONCURRENCY: int = 2
    MAX_ATTEMPTS: int = 3

    CORS_ORIGINS: Annotated[list[str], NoDecode] = ["http://localhost:3000", "http://localhost:5173"]
    USE_PROXY: bool = False

    # Public base URL of this API; used for absolute links inside sitemaps/feeds.
    RATE_LIMIT_PER_MINUTE: int = 10  # per signed-in customer, on write endpoints
    # Most URLs/checks a customer may have waiting in the queue at once.
    MAX_QUEUED_PER_USER: int = 5000
    # Rows per Appwrite bulk request. Plan limit: Free 100, Pro 1000.
    APPWRITE_BULK_CHUNK_SIZE: int = 100
    # Rows stuck in "processing" longer than this are returned to "pending".
    STALE_LOCK_SECONDS: int = 300

    # --- Google Search Console (placeholders: the integration stays off until these are set) ---
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REDIRECT_URI: str = "http://localhost:8000/api/v1/google/callback"
    # One or more Fernet keys, comma separated. The first encrypts; all can decrypt (key rotation).
    TOKEN_ENCRYPTION_KEY: str = ""
    GSC_WORKER_COUNT: int = 1
    GSC_INSPECT_PER_MINUTE: int = 600  # Google's per-property limit
    GSC_INSPECT_PER_DAY: int = 2000  # Google's per-property limit
    GSC_MAX_TARGETS_PER_USER: int = 2000
    GSC_MANUAL_RESERVE: int = 200  # daily inspections kept free for customers pressing Recheck

    # --- Account recovery / verification abuse limits ---
    FRONTEND_URL: str = "http://localhost:3000"  # where Appwrite emails link to; never taken from a request
    RECOVERY_PER_IP: int = 5  # requests per 15 minutes
    RECOVERY_PER_EMAIL: int = 3  # requests per hour
    VERIFICATION_RESEND_COOLDOWN: int = 60  # seconds
    VERIFICATION_PER_HOUR: int = 5

    # Publish ONE sitemap/feed listing every customer's URLs (and ping it). Off by default because it makes all
    # customers' submissions publicly visible together. Per-batch feeds at /batches/<id>/ stay available.
    PUBLIC_GLOBAL_FEED: bool = False
    PUBLIC_BASE_URL: str = "http://localhost:8000"

    @field_validator("CORS_ORIGINS", "PING_ENDPOINTS", "WEBSUB_HUBS", mode="before")
    @classmethod
    def _split_origins(cls, v):
        if isinstance(v, str) and not v.strip().startswith("["):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v


    @property
    def google_configured(self) -> bool:
        return bool(self.GOOGLE_CLIENT_ID and self.GOOGLE_CLIENT_SECRET and self.TOKEN_ENCRYPTION_KEY)


@lru_cache
def get_settings() -> Settings:
    return Settings()