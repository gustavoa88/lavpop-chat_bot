from app.conversation_router import (
    BOT_ACTION,
    HANDOFF_ACTION,
    WAITING_HUMAN_MODE,
    ConversationRouter,
)


def test_router_sends_menu_option_5_to_human_handoff():
    decision = ConversationRouter().decide("5", {"modo_conversa": "bot"})

    assert decision.action == HANDOFF_ACTION
    assert decision.mode == WAITING_HUMAN_MODE
    assert decision.answer


def test_router_informs_waiting_human_mode_instead_of_silence():
    decision = ConversationRouter().decide(
        "mais uma dúvida",
        {"modo_conversa": "aguardando_humano"},
    )

    assert decision.action == HANDOFF_ACTION
    assert decision.mode == "aguardando_humano"
    assert decision.answer


def test_router_resume_command_returns_to_bot():
    decision = ConversationRouter().decide(
        "/retomar",
        {"modo_conversa": "humano"},
    )

    assert decision.action == BOT_ACTION
    assert decision.mode == "bot"
