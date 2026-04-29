from app.ai_persona import LAVPOP_PERSONA_BLUEPRINT
from app.config import Settings
from app.services import ChatService


class FakeDatabase:
    def fetchall(self, query, params=()):
        return []

    def fetchone(self, query, params=()):
        return None

    def execute(self, query, params=()):
        return None


class DummySettings(Settings):
    pass


class FakeClient:
    def __init__(self):
        self.calls = []
        self.responses = self

    def create(self, **kwargs):
        self.calls.append(kwargs)

        class Result:
            output_text = "Resposta teste"

        return Result()


def _build_settings() -> Settings:
    return DummySettings(
        openai_api_key="fake-key",
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


def test_blueprint_system_prompt_contains_required_sections():
    prompt = LAVPOP_PERSONA_BLUEPRINT.system_prompt()

    assert "Persona:" in prompt
    assert "Regras obrigatórias:" in prompt
    assert "Escalonamento para humano:" in prompt
    assert "Nunca inventar" in prompt


def test_chat_service_uses_blueprint_in_ai_system_prompt():
    service = ChatService(FakeDatabase(), _build_settings())
    fake_client = FakeClient()
    service.client = fake_client

    response = service.ai_response("Qual o preço?", "Cliente", context={"modo": "bot"})

    assert response == "Resposta teste"
    payload = fake_client.calls[0]
    system_prompt = payload["input"][0]["content"]
    assert "LavPop Concierge" in system_prompt
    assert "Escalonamento para humano" in system_prompt
