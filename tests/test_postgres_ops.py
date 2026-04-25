from __future__ import annotations

from app.postgres_ops import backup_filename, load_postgres_connection_info


def test_load_postgres_connection_info_uses_database_url():
    info = load_postgres_connection_info(
        {
            "DATABASE_URL": "postgresql://chatbot_user:secret_pw@192.168.10.50:5433/lavpop_chatbot_prod",
            "DB_HOST": "127.0.0.1",
            "DB_PORT": "5432",
            "DB_NAME": "lavpop_chatbot",
            "DB_USER": "postgres",
            "DB_PASSWORD": "postgres",
        }
    )

    assert info.host == "192.168.10.50"
    assert info.port == 5433
    assert info.dbname == "lavpop_chatbot_prod"
    assert info.user == "chatbot_user"
    assert info.password == "secret_pw"


def test_load_postgres_connection_info_uses_db_vars_when_url_is_absent():
    info = load_postgres_connection_info(
        {
            "DB_HOST": "db.internal",
            "DB_PORT": "6432",
            "DB_NAME": "chatbot",
            "DB_USER": "ops",
            "DB_PASSWORD": "pw",
        }
    )

    assert info.host == "db.internal"
    assert info.port == 6432
    assert info.dbname == "chatbot"
    assert info.user == "ops"
    assert info.password == "pw"


def test_backup_filename_has_dump_extension():
    filename = backup_filename("chatbot")
    assert filename.startswith("chatbot-")
    assert filename.endswith(".dump")
