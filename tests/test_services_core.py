from app.config import Settings
from app.services import ChatService, normalize_phone, normalize_text


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
    )
    return ChatService(FakeDatabase(rules=rules, intents=intents), settings)


def test_normalize_text_removes_accents_and_extra_spaces():
    assert normalize_text("  OlÁ,    CÓMO   VAI?  ") == "ola, como vai?"


def test_normalize_phone_removes_whatsapp_prefix():
    assert normalize_phone("whatsapp:5511999999999") == "5511999999999"


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
