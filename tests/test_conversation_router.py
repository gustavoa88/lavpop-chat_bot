from app.conversation_router import (
    BOT_ACTION,
    HANDOFF_ACTION,
    REGISTER_ONLY_ACTION,
    WAITING_HUMAN_MODE,
    ConversationRouter,
)


def test_router_sends_menu_option_5_to_human_handoff():
    decision = ConversationRouter().decide("5", {"modo_conversa": "bot"})

    assert decision.action == HANDOFF_ACTION
    assert decision.mode == WAITING_HUMAN_MODE
    assert decision.answer


def test_router_registers_only_when_conversation_is_waiting_human():
    decision = ConversationRouter().decide(
        "mais uma dúvida",
        {"modo_conversa": "aguardando_humano"},
    )

    assert decision.action == REGISTER_ONLY_ACTION
    assert decision.mode == "aguardando_humano"


def test_router_resume_command_returns_to_bot():
    decision = ConversationRouter().decide(
        "/retomar",
        {"modo_conversa": "humano"},
    )

    assert decision.action == BOT_ACTION
    assert decision.mode == "bot"
