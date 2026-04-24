from dataclasses import dataclass
from typing import Optional

from app.services import PROACTIVE_MENU_OPTIONS, extract_menu_option, normalize_text


BOT_MODE = "bot"
HUMAN_MODE = "humano"
WAITING_HUMAN_MODE = "aguardando_humano"
REGISTER_ONLY_ACTION = "registrar"
BOT_ACTION = "bot"
HANDOFF_ACTION = "handoff"


HUMAN_HANDOFF_MESSAGE = PROACTIVE_MENU_OPTIONS["5"]["fallback"]


@dataclass(frozen=True)
class RouteDecision:
    action: str
    mode: str
    reason: str
    answer: Optional[str] = None


class ConversationRouter:
    def should_resume_bot(self, message: str) -> bool:
        msg_norm = normalize_text(message)
        return msg_norm in {
            "/retomar",
            "retomar",
            "retomar bot",
            "voltar bot",
            "ativar bot",
            "bot",
        }

    def should_pause_for_human(self, message: str) -> bool:
        msg_norm = normalize_text(message)
        if extract_menu_option(message) == "5":
            return True

        handoff_terms = {
            "atendente",
            "atendimento humano",
            "falar com atendente",
            "falar com atendimento",
            "falar com humano",
            "humano",
            "suporte humano",
            "/humano",
            "/pausar",
            "pausar",
            "pausar bot",
        }
        return any(term in msg_norm for term in handoff_terms)

    def decide(self, message: str, context: Optional[dict]) -> RouteDecision:
        mode = ((context or {}).get("modo_conversa") or BOT_MODE).strip().lower()
        if mode == "encerrado":
            mode = BOT_MODE

        if self.should_resume_bot(message):
            return RouteDecision(
                action=BOT_ACTION,
                mode=BOT_MODE,
                reason="comando_retomar_bot",
            )

        if self.should_pause_for_human(message):
            return RouteDecision(
                action=HANDOFF_ACTION,
                mode=WAITING_HUMAN_MODE,
                reason="pedido_atendimento_humano",
                answer=HUMAN_HANDOFF_MESSAGE,
            )

        if mode in {HUMAN_MODE, WAITING_HUMAN_MODE}:
            return RouteDecision(
                action=REGISTER_ONLY_ACTION,
                mode=mode,
                reason=f"conversa_em_modo_{mode}",
            )

        return RouteDecision(
            action=BOT_ACTION,
            mode=BOT_MODE,
            reason="bot_ativo",
        )
