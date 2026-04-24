import os
from dataclasses import dataclass
from urllib.parse import unquote, urlparse


@dataclass(frozen=True)
class Settings:
    openai_api_key: str
    openai_model: str
    meta_verify_token: str
    meta_whatsapp_token: str
    meta_phone_number_id: str
    meta_app_secret: str
    meta_validate_signature: bool
    meta_require_app_secret: bool
    db_host: str
    db_port: int
    db_name: str
    db_user: str
    db_password: str
    db_min_conn: int
    db_max_conn: int
    db_connect_timeout: int
    inactivity_timeout_minutes: int
    inactivity_check_interval_seconds: int
    app_debug_log_mode: bool = False
    observability_internal_only: bool = True
    trust_proxy_headers: bool = False
    trusted_proxy_cidrs: tuple[str, ...] = ("127.0.0.1/32", "::1/128")
    app_env: str = "dev"


def _db_settings_from_env() -> tuple[str, int, str, str, str]:
    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        return (
            os.getenv("DB_HOST", "127.0.0.1"),
            int(os.getenv("DB_PORT", "5432")),
            os.getenv("DB_NAME", "lavpop_chatbot"),
            os.getenv("DB_USER", "postgres"),
            os.getenv("DB_PASSWORD", "postgres"),
        )

    parsed = urlparse(database_url)
    if parsed.scheme not in {"postgres", "postgresql"}:
        raise ValueError(
            "DATABASE_URL inválida: use schema postgres:// ou postgresql://."
        )

    db_name = unquote(parsed.path.lstrip("/")) or os.getenv("DB_NAME", "lavpop_chatbot")
    db_host = parsed.hostname or os.getenv("DB_HOST", "127.0.0.1")
    db_port = parsed.port or int(os.getenv("DB_PORT", "5432"))
    db_user = unquote(parsed.username) if parsed.username else os.getenv("DB_USER", "postgres")
    db_password = (
        unquote(parsed.password)
        if parsed.password is not None
        else os.getenv("DB_PASSWORD", "postgres")
    )

    return db_host, db_port, db_name, db_user, db_password


def load_settings() -> Settings:
    validate_signature = os.getenv("META_VALIDATE_SIGNATURE", "true").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    require_app_secret = os.getenv("META_REQUIRE_APP_SECRET", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    observability_internal_only = os.getenv("OBSERVABILITY_INTERNAL_ONLY", "true").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    trust_proxy_headers = os.getenv("TRUST_PROXY_HEADERS", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    app_debug_log_mode = os.getenv("APP_DEBUG_LOG_MODE", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    trusted_proxy_cidrs_raw = os.getenv("TRUSTED_PROXY_CIDRS", "127.0.0.1/32,::1/128")
    trusted_proxy_cidrs = tuple(
        item.strip() for item in trusted_proxy_cidrs_raw.split(",") if item.strip()
    )
    db_host, db_port, db_name, db_user, db_password = _db_settings_from_env()

    return Settings(
        openai_api_key=os.getenv("OPENAI_API_KEY", ""),
        openai_model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
        meta_verify_token=os.getenv("META_VERIFY_TOKEN", ""),
        meta_whatsapp_token=os.getenv("META_WHATSAPP_TOKEN", ""),
        meta_phone_number_id=os.getenv("META_PHONE_NUMBER_ID", ""),
        meta_app_secret=os.getenv("META_APP_SECRET", ""),
        meta_validate_signature=validate_signature,
        meta_require_app_secret=require_app_secret,
        db_host=db_host,
        db_port=db_port,
        db_name=db_name,
        db_user=db_user,
        db_password=db_password,
        db_min_conn=int(os.getenv("DB_MIN_CONN", "1")),
        db_max_conn=int(os.getenv("DB_MAX_CONN", "5")),
        db_connect_timeout=int(os.getenv("DB_CONNECT_TIMEOUT", "3")),
        inactivity_timeout_minutes=int(os.getenv("INACTIVITY_TIMEOUT_MINUTES", "15")),
        inactivity_check_interval_seconds=int(os.getenv("INACTIVITY_CHECK_INTERVAL_SECONDS", "60")),
        app_debug_log_mode=app_debug_log_mode,
        observability_internal_only=observability_internal_only,
        trust_proxy_headers=trust_proxy_headers,
        trusted_proxy_cidrs=trusted_proxy_cidrs,
        app_env=os.getenv("APP_ENV", os.getenv("ENV", "dev")).strip().lower(),
    )
