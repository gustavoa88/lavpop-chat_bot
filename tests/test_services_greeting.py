from app.config import Settings
from app.services import ChatService, PROACTIVE_MENU_MESSAGE


class FakeDatabase:
    def __init__(self):
        self.logs = []
        self.contexts = []

    def fetchall(self, query, params=()):
        return []

    def fetchone(self, query, params=()):
        return None

    def execute(self, query, params=()):
        if "log_conversas" in query:
            self.logs.append(params)
        elif "contexto_cliente" in query:
            self.contexts.append(params)


class DummySettings(Settings):
    pass


def _build_service() -> ChatService:
    settings = DummySettings(
        openai_api_key="",
        openai_model="gpt-4.1-mini",
        meta_verify_token="verify-token",
        meta_whatsapp_token="",
        meta_phone_number_id="",
        meta_app_secret="",
        meta_validate_signature=True,
        meta_require_app_secret=False,
        db_host="127.0.0.1",
        db_port=5432,
        db_name="lavpop_chatbot",
        db_user="postgres",
        db_password="postgres",
        db_min_conn=1,
        db_max_conn=5,
        db_connect_timeout=3,
    )
    return ChatService(FakeDatabase(), settings)


def test_answer_message_returns_proactive_menu_for_simple_greeting():
    service = _build_service()

    response, source, rule_name, intent = service.answer_message("5511999999999", "Gustavo", "olá")

    assert response == PROACTIVE_MENU_MESSAGE
    assert source == "menu"
    assert rule_name is None
    assert intent == "menu_inicial"


def test_answer_message_keeps_regular_flow_for_non_greeting_message():
    service = _build_service()

    response, source, rule_name, intent = service.answer_message(
        "5511999999999", "Gustavo", "qual o horário de atendimento?"
    )

    assert "horário" in response
    assert source == "ia"
    assert rule_name is None
    assert intent is None
