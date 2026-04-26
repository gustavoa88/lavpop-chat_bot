from app.config import Settings
from app.services import (
    ChatService,
    extract_menu_option,
    normalize_phone,
    normalize_text,
    resolve_interactive_menu_selection,
)


class FakeDatabase:
    def __init__(self, rules=None, intents=None):
        self.rules = rules or []
        self.intents = intents or []

    def fetchall(self, query, params=()):
        if "FROM chatbot.faq_regras" in query:
            return self.rules
        if "FROM chatbot.intencoes" in query:
            return self.intents
        return []

    def fetchone(self, query, params=()):
        return None

    def execute(self, query, params=()):
        return None


class DummySettings(Settings):
    pass


def _build_service(rules=None, intents=None) -> ChatService:
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
        inactivity_timeout_minutes=15,
        inactivity_check_interval_seconds=60,
        app_env="test",
    )
    return ChatService(FakeDatabase(rules=rules, intents=intents), settings)


def test_normalize_text_removes_accents_and_extra_spaces():
    assert normalize_text("  OlÁ,    CÓMO   VAI?  ") == "ola, como vai?"


def test_normalize_phone_keeps_only_digits():
    assert normalize_phone("5511915277958") == "5511915277958"
    assert normalize_phone("+5511915277958") == "5511915277958"
    assert normalize_phone("whatsapp:+5511915277958") == "5511915277958"
    assert normalize_phone(" +55 (11) 91527-7958 ") == "5511915277958"


def test_find_rule_response_handles_invalid_keywords_json():
    service = _build_service(
        rules=[
            {
                "nome_regra": "regra_invalida",
                "resposta": "Resposta da regra",
                "palavras_chave": "{invalido",
            }
        ]
    )

    response, rule_name = service.find_rule_response("qualquer mensagem")

    assert response is None
    assert rule_name is None


def test_classify_intent_matches_intent_name_with_underscore():
    service = _build_service(
        intents=[
            {"nome_intencao": "falar_humano"},
        ]
    )

    intent = service.classify_intent("quero falar humano agora")

    assert intent == "falar_humano"


def test_extract_menu_option_supports_number_inside_text():
    assert extract_menu_option("Quero a opção 4, por favor.") == "4"


def test_resolve_interactive_menu_selection_accepts_known_title():
    selection = resolve_interactive_menu_selection(
        interactive_id="",
        interactive_title="2) Preços",
    )
    assert selection == "2"


def test_close_inactive_conversations_sends_message_and_updates_status(monkeypatch):
    class FakeDbInactivity:
        def __init__(self):
            self.executed = []
            self.logged = []

        def fetchall(self, query, params=()):
            if "FROM chatbot.contexto_cliente" in query:
                return [{"telefone": "5511999999999", "nome": "Cliente Teste"}]
            return []

        def fetchone(self, query, params=()):
            return None

        def execute(self, query, params=()):
            if "INSERT INTO chatbot.log_conversas" in query:
                self.logged.append(params)
            else:
                self.executed.append((query, params))

    settings = DummySettings(
        openai_api_key="",
        openai_model="gpt-4.1-mini",
        meta_verify_token="verify-token",
        meta_whatsapp_token="token",
        meta_phone_number_id="phone-id",
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
        inactivity_timeout_minutes=15,
        inactivity_check_interval_seconds=60,
        app_env="test",
    )
    service = ChatService(FakeDbInactivity(), settings)
    monkeypatch.setattr(service, "send_meta_message", lambda destination, text: True)

    closed = service.close_inactive_conversations()

    assert closed == 1
    assert len(service.db.logged) == 1
    assert any("encerrado_inatividade" in call[0] for call in service.db.executed)


def test_save_context_reactivates_closed_context():
    class FakeDbSaveContext:
        def __init__(self):
            self.last_query = ""
            self.last_params = ()

        def fetchall(self, query, params=()):
            return []

        def fetchone(self, query, params=()):
            return None

        def execute(self, query, params=()):
            self.last_query = query
            self.last_params = params

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
        inactivity_timeout_minutes=15,
        inactivity_check_interval_seconds=60,
        app_env="test",
    )
    fake_db = FakeDbSaveContext()
    service = ChatService(fake_db, settings)

    service.save_context(
        phone="5511999999999",
        name="Cliente Teste",
        intent="menu_inicial",
        subject="menu_inicial",
        response_type="menu_boas_vindas",
    )

    assert "status = 'ativo'" in fake_db.last_query


def test_send_human_message_sends_and_records_outbound(monkeypatch):
    class FakeDbHumanMessage:
        def __init__(self):
            self.executed = []

        def fetchall(self, query, params=()):
            return []

        def fetchone(self, query, params=()):
            return None

        def execute(self, query, params=()):
            self.executed.append((query, params))

    settings = DummySettings(
        openai_api_key="",
        openai_model="gpt-4.1-mini",
        meta_verify_token="verify-token",
        meta_whatsapp_token="token",
        meta_phone_number_id="phone-id",
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
        inactivity_timeout_minutes=15,
        inactivity_check_interval_seconds=60,
        app_env="test",
    )
    fake_db = FakeDbHumanMessage()
    service = ChatService(fake_db, settings)
    monkeypatch.setattr(service, "send_meta_message", lambda destination, text: True)

    sent = service.send_human_message("whatsapp:+5511999999999", "Olá, vou te ajudar.")

    assert sent is True
    assert any("INSERT INTO chatbot.mensagens" in query for query, _ in fake_db.executed)
    assert any("resposta_humana" in params for _, params in fake_db.executed)
    assert all(
        "whatsapp:" not in str(params) and "+5511999999999" not in str(params)
        for _, params in fake_db.executed
    )
