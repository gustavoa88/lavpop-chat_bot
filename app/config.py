import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    openai_api_key: str
    openai_model: str
    meta_verify_token: str
    meta_whatsapp_token: str
    meta_phone_number_id: str
    db_host: str
    db_port: int
    db_name: str
    db_user: str
    db_password: str
    db_min_conn: int
    db_max_conn: int
    db_connect_timeout: int


def load_settings() -> Settings:
    return Settings(
        openai_api_key=os.getenv("OPENAI_API_KEY", ""),
        openai_model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
        meta_verify_token=os.getenv("META_VERIFY_TOKEN", ""),
        meta_whatsapp_token=os.getenv("META_WHATSAPP_TOKEN", ""),
        meta_phone_number_id=os.getenv("META_PHONE_NUMBER_ID", ""),
        db_host=os.getenv("DB_HOST", "127.0.0.1"),
        db_port=int(os.getenv("DB_PORT", "5432")),
        db_name=os.getenv("DB_NAME", "lavpop_chatbot"),
        db_user=os.getenv("DB_USER", "postgres"),
        db_password=os.getenv("DB_PASSWORD", "postgres"),
        db_min_conn=int(os.getenv("DB_MIN_CONN", "1")),
        db_max_conn=int(os.getenv("DB_MAX_CONN", "5")),
        db_connect_timeout=int(os.getenv("DB_CONNECT_TIMEOUT", "3")),
    )
