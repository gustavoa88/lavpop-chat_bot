from app.config import Settings
from app.services import ChatService, PROACTIVE_MENU_MESSAGE, PROACTIVE_MENU_OPTIONS


class FakeDatabase:
    def __init__(self, rules=None):
        self.logs = []
        self.contexts = []
        self.rules = rules or []

    def fetchall(self, query, params=()):
        if "FROM chatbot.faq_regras" in query:
            return self.rules
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


def _build_service(rules=None) -> ChatService:
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
    return ChatService(FakeDatabase(rules=rules), settings)


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


def test_answer_message_returns_fixed_response_for_menu_option_1():
    service = _build_service()

    response, source, rule_name, intent = service.answer_message("5511941878601", "Gustavo", "1")

    assert response == PROACTIVE_MENU_OPTIONS["1"]["fallback"]
    assert source == "menu"
    assert rule_name is None
    assert intent == "menu_opcao_1"


def test_menu_option_1_prefers_database_rule_when_available():
    service = _build_service(
        rules=[
            {
                "nome_regra": "horario_oficial",
                "resposta": "Funcionamos das 05h às 23h (seg-sex), sáb das 08h às 23h e dom das 08h às 20h.",
                "palavras_chave": ["horario", "funcionamento"],
            }
        ]
    )

    response, source, rule_name, intent = service.answer_message("5511941878601", "Gustavo", "1")

    assert "05h às 23h" in response
    assert source == "banco"
    assert rule_name == "horario_oficial"
    assert intent == "menu_opcao_1"
