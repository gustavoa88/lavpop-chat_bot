import hashlib
import json
import logging
import re
import time
import urllib.request
from datetime import date, datetime
from decimal import Decimal
from urllib.error import HTTPError, URLError
from typing import Any, Optional

from openai import OpenAI

from app.ai_persona import LAVPOP_PERSONA_BLUEPRINT
from app.config import Settings
from app.db import Database

logger = logging.getLogger("meta_chatbot")

PROACTIVE_MENU_MESSAGE = (
    "Olá! 👋 Que bom falar com você.\n"
    "Posso te ajudar com:\n"
    "1) Horário de atendimento\n"
    "2) Preços\n"
    "3) Como funciona\n"
    "4) Serviços disponíveis\n"
    "5) Falar com atendimento humano\n\n"
    "Me diga o número da opção ou escreva o tema 🙂"
)

INACTIVITY_CLOSING_MESSAGE = (
    "Percebi que ficamos alguns minutinhos sem interação 🙂\n"
    "Vou encerrar este atendimento por enquanto, tudo bem?\n"
    "Quando quiser, é só me chamar novamente — vai ser um prazer te receber na LavPop! 🧺💙"
)

RETURN_TO_BOT_TRANSITION_MESSAGE = (
    "✅ Atendimento humano finalizado. Voltei a te atender por aqui.\n"
    "Vou abrir o menu para você escolher a próxima opção 🙂"
)

PROACTIVE_MENU_OPTIONS = {
    "1": {
        "intent": "menu_opcao_1",
        "lookup_terms": ["horario de atendimento", "horario de funcionamento", "funcionamento"],
        "fallback": (
            "🕒 *Horário de atendimento*\n"
            "Segunda a sexta: 8h às 18h\n"
            "Sábado: 8h às 12h\n"
            "Domingo e feriados: fechado."
        ),
    },
    "2": {
        "intent": "menu_opcao_2",
        "lookup_terms": ["preco", "precos", "tabela de precos"],
        "fallback": (
            "💰 *Preços*\n"
            "Os valores variam por tipo de peça e serviço.\n"
            "Se quiser, te passo um orçamento rápido: me diga quais peças você precisa lavar."
        ),
    },
    "3": {
        "intent": "menu_opcao_3",
        "lookup_terms": ["como funciona", "funcionamento", "processo"],
        "fallback": (
            "🧺 *Como funciona*\n"
            "1) Você envia o pedido\n"
            "2) Coletamos as peças\n"
            "3) Lavamos e finalizamos\n"
            "4) Entregamos para você.\n"
            "Se quiser, já te explico como agendar."
        ),
    },
    "4": {
        "intent": "menu_opcao_4",
        "preferred_rule": "o_que_lavar",
        "lookup_terms": ["servicos", "tipos de servico", "o que voces fazem"],
        "fallback": (
            "✅ *Serviços disponíveis*\n"
            "- Lavagem de roupas do dia a dia\n"
            "- Peças delicadas\n"
            "\nPara confirmar itens específicos (ex.: edredom, tapete, tênis), "
            "me diga a peça e eu te explico o que pode ou não pode lavar por aqui."
        ),
    },
    "5": {
        "intent": "menu_opcao_5",
        "lookup_terms": ["atendimento humano", "falar com atendente", "suporte humano"],
        "fallback": (
            "🤝 *Atendimento humano*\n"
            "Perfeito! Vou encaminhar seu atendimento para nossa equipe humana."
        ),
    },
}

PROACTIVE_MENU_ROWS = [
    {
        "id": "menu_option_1",
        "title": "Horário de atendimento",
        "description": "Dias e horários de funcionamento.",
    },
    {
        "id": "menu_option_2",
        "title": "Preços e orçamento",
        "description": "Orçamento e faixa de valores.",
    },
    {
        "id": "menu_option_3",
        "title": "Como funciona",
        "description": "Entenda o passo a passo.",
    },
    {
        "id": "menu_option_4",
        "title": "Serviços disponíveis",
        "description": "Veja tudo que a LavPop faz.",
    },
    {
        "id": "menu_option_5",
        "title": "Atendimento humano",
        "description": "Falar com um atendente agora.",
    },
]

INTERACTIVE_MENU_ID_TO_OPTION = {
    "menu_option_1": "1",
    "menu_option_2": "2",
    "menu_option_3": "3",
    "menu_option_4": "4",
    "menu_option_5": "5",
}

INTERACTIVE_MENU_TITLE_TO_OPTION = {
    "1 horario de atendimento": "1",
    "2 precos": "2",
    "3 como funciona": "3",
    "4 servicos disponiveis": "4",
    "5 atendimento humano": "5",
}


def _extract_menu_option_token(message: str) -> str:
    msg_norm = normalize_text(message)
    compact = re.sub(r"\s+", " ", msg_norm).strip()
    if not compact:
        return ""

    numeric_match = re.match(r"^(\d)", compact)
    if numeric_match:
        return numeric_match.group(1)

    compact_no_punct = re.sub(r"[^\w\s]", " ", compact)
    compact_no_punct = re.sub(r"\s+", " ", compact_no_punct).strip()

    title_to_option = {
        "horario de atendimento": "1",
        "atendimento": "5",
        "precos": "2",
        "como funciona": "3",
        "servicos disponiveis": "4",
        "atendimento humano": "5",
    }
    exact_option = title_to_option.get(compact_no_punct, "")
    if exact_option:
        return exact_option

    topic_patterns = (
        ("1", ("horario", "funcionamento", "abre", "fecha")),
        ("2", ("preco", "precos", "valor", "valores", "custo", "custos", "orcamento")),
        ("3", ("como funciona", "funciona", "processo", "passo a passo")),
        ("4", ("servico", "servicos", "lavar", "lavagem", "seca", "secagem")),
    )
    for option, terms in topic_patterns:
        if any(term in compact_no_punct for term in terms):
            return option

    return ""


def normalize_text(text: str) -> str:
    text = (text or "").strip().lower()
    replacements = {
        "á": "a",
        "à": "a",
        "ã": "a",
        "â": "a",
        "é": "e",
        "ê": "e",
        "í": "i",
        "ó": "o",
        "ô": "o",
        "õ": "o",
        "ú": "u",
        "ç": "c",
    }
    for src, dst in replacements.items():
        text = text.replace(src, dst)
    text = re.sub(r"[^\w\s!?.,:+-]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def normalize_phone(phone: str) -> str:
    normalized = (phone or "").strip()
    normalized = re.sub(r"^whatsapp:", "", normalized, flags=re.IGNORECASE).strip()
    return re.sub(r"\D+", "", normalized)


def is_sensitive_request(message: str) -> bool:
    msg_norm = normalize_text(message)
    sensitive_terms = {
        "senha",
        "wi fi",
        "wifi",
        "codigo",
        "codigo de acesso",
        "token",
        "chave",
        "documento",
        "cpf",
        "cnpj",
        "cartao",
        "pix",
        "dados bancarios",
    }
    return any(term in msg_norm for term in sensitive_terms)


def extract_menu_option(message: str) -> Optional[str]:
    normalized = normalize_text(message)
    match = re.search(r"\b([1-5])\b", normalized)
    if match:
        return match.group(1)
    compact = re.sub(r"[!?.,:;\\s]+", "", normalized).strip()
    return compact if compact in PROACTIVE_MENU_OPTIONS else None


def resolve_interactive_menu_selection(
    interactive_id: str,
    interactive_title: str,
    interactive_description: str = "",
) -> str:
    normalized_title = normalize_text(interactive_title)
    if interactive_id in INTERACTIVE_MENU_ID_TO_OPTION:
        return INTERACTIVE_MENU_ID_TO_OPTION[interactive_id]
    if normalized_title in INTERACTIVE_MENU_TITLE_TO_OPTION:
        return INTERACTIVE_MENU_TITLE_TO_OPTION[normalized_title]

    extracted = extract_menu_option(interactive_title) or extract_menu_option(interactive_description)
    if extracted:
        return extracted

    return (interactive_title or "").strip()


def _http_error_body(exc: HTTPError) -> str:
    try:
        raw = exc.read()
    except Exception:
        return ""
    if not raw:
        return ""
    return raw.decode("utf-8", errors="replace").strip()


def _token_hint(token: str) -> str:
    token = (token or "").strip()
    if not token:
        return "ausente"
    if len(token) < 20:
        return "muito_curto"
    if token.startswith("EA"):
        return "formato_esperado"
    return "formato_desconhecido"


def _json_default_serializer(obj: Any) -> Any:
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return float(obj)
    return str(obj)


def _phone_log_id(phone: str) -> str:
    phone = (phone or "").strip()
    if not phone:
        return "ausente"
    return f"phone_hash:{hashlib.sha256(phone.encode('utf-8')).hexdigest()[:12]}"


class ChatService:
    def __init__(self, db: Database, settings: Settings):
        self.db = db
        self.settings = settings
        self.client = OpenAI(api_key=settings.openai_api_key) if settings.openai_api_key else None
        self._meta_send_blocked_until = 0.0

    def _debug_log(self, message: str, *args) -> None:
        if self.settings.app_debug_log_mode and self.settings.app_env not in {"prod", "production"}:
            logger.info("[debug_log_mode] " + message, *args)

    def _active_rules(self) -> list[dict]:
        return self.db.fetchall(
            """
            SELECT nome_regra, resposta, palavras_chave
              FROM chatbot.faq_regras
             WHERE ativo = TRUE
             ORDER BY prioridade ASC, id ASC
            """
        )

    def _match_rule_response(
        self,
        message: str,
        rules: Optional[list[dict]] = None,
    ) -> tuple[Optional[str], Optional[str]]:
        msg_norm = normalize_text(message)
        rules = rules if rules is not None else self._active_rules()
        for row in rules:
            keywords = row.get("palavras_chave") or []
            if isinstance(keywords, str):
                try:
                    keywords = json.loads(keywords)
                except json.JSONDecodeError:
                    logger.warning("Falha ao converter palavras_chave da regra '%s'", row.get("nome_regra"))
                    keywords = []

            if not isinstance(keywords, list):
                keywords = [keywords]

            for keyword in keywords:
                kw = normalize_text(str(keyword))
                if kw and kw in msg_norm:
                    return row["resposta"], row["nome_regra"]

        return None, None

    def find_rule_response(self, message: str) -> tuple[Optional[str], Optional[str]]:
        return self._match_rule_response(message)

    def find_rule_by_name(self, rule_name: str, rules: Optional[list[dict]] = None) -> Optional[str]:
        target_rule = normalize_text(rule_name)
        if not target_rule:
            return None

        rules = rules if rules is not None else self._active_rules()
        for row in rules:
            current_rule = normalize_text(str(row.get("nome_regra") or ""))
            if current_rule == target_rule:
                return row.get("resposta")
        return None

    def classify_intent(self, message: str) -> Optional[str]:
        message_norm = normalize_text(message)
        intents = self.db.fetchall(
            """
            SELECT nome_intencao
              FROM chatbot.intencoes
             WHERE ativa = TRUE
             ORDER BY id ASC
            """
        )
        for intent in intents:
            intent_name = (intent.get("nome_intencao") or "").strip()
            if intent_name and intent_name.replace("_", " ") in message_norm:
                return intent_name
        return None

    def is_proactive_greeting(self, message: str) -> bool:
        msg_norm = normalize_text(message)
        msg_norm = re.sub(r"[!?.,:;]+", "", msg_norm).strip()
        simple_greetings = {
            "oi",
            "ola",
            "bom dia",
            "boa tarde",
            "boa noite",
            "e ai",
            "ei",
        }
        if msg_norm in simple_greetings:
            return True

        greeting_tokens = {"oi", "ola", "bom", "boa", "dia", "tarde", "noite", "e", "ai", "ei"}
        tokens = msg_norm.split()
        return bool(tokens) and len(tokens) <= 4 and all(token in greeting_tokens for token in tokens)

    def proactive_menu_option_response(
        self, message: str, rules: Optional[list[dict]] = None
    ) -> tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
        option_key = _extract_menu_option_token(message)
        option = PROACTIVE_MENU_OPTIONS.get(option_key)
        if not option:
            return None, None, None, None

        rules = rules if rules is not None else self._active_rules()
        preferred_rule = (option.get("preferred_rule") or "").strip()
        if preferred_rule:
            preferred_answer = self.find_rule_by_name(preferred_rule, rules=rules)
            if preferred_answer:
                return preferred_answer, option["intent"], preferred_rule, "banco"

        for term in option["lookup_terms"]:
            db_answer, rule_name = self._match_rule_response(term, rules=rules)
            if db_answer:
                return db_answer, option["intent"], rule_name, "banco"

        return option["fallback"], option["intent"], None, "menu"

    def ai_response(self, message: str, customer_name: str, context: Optional[dict]) -> str:
        if not self.client:
            return "No momento estou sem IA ativa. Posso te ajudar com horário, preço e serviços 🙂"

        system_prompt = LAVPOP_PERSONA_BLUEPRINT.system_prompt()

        context_prompt = (
            f"Contexto cliente: "
            f"{json.dumps(context or {}, ensure_ascii=False, default=_json_default_serializer)}"
        )

        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            try:
                completion = self.client.responses.create(
                    model=self.settings.openai_model,
                    input=[
                        {"role": "system", "content": system_prompt},
                        {"role": "system", "content": context_prompt},
                        {
                            "role": "user",
                            "content": f"Nome do cliente: {customer_name or 'Cliente'}\nMensagem: {message}",
                        },
                    ],
                    max_output_tokens=220,
                )
                return (completion.output_text or "").strip()

            except Exception as exc:
                status_code = getattr(exc, "status_code", None)
                retryable = (
                    status_code in {408, 409, 429}
                    or (isinstance(status_code, int) and status_code >= 500)
                    or isinstance(exc, (TimeoutError, ConnectionError))
                )

                if attempt < max_attempts and retryable:
                    wait_seconds = 0.5 * (2 ** (attempt - 1))
                    logger.warning(
                        "Falha transitória ao consultar OpenAI. tentativa=%s/%s status_code=%s erro=%s",
                        attempt,
                        max_attempts,
                        status_code,
                        exc,
                    )
                    time.sleep(wait_seconds)
                    continue

                logger.exception(
                    "Falha ao gerar resposta com OpenAI. tentativa=%s/%s status_code=%s",
                    attempt,
                    max_attempts,
                    status_code,
                )
                break

        return (
            "Estou com instabilidade no atendimento automático agora. "
            "Posso te ajudar com horário, preço e serviços, ou encaminhar para atendimento humano 🙂"
        )

    def ai_router_assist_response(
        self,
        *,
        customer_name: str,
        user_message: str,
        base_response: str,
        response_origin: str,
        context: Optional[dict],
    ) -> str:
        if not self.client:
            return base_response

        assist_prompt = (
            "Use a resposta base abaixo como fonte principal.\n"
            f"Origem da resposta base: {response_origin}\n"
            f"Resposta base: {base_response}\n\n"
            "Reescreva em tom natural, claro e objetivo para WhatsApp.\n"
            "Não invente preços, horários, políticas ou serviços além do que está na resposta base.\n"
            "Se faltar informação, mantenha o conteúdo essencial sem criar novos dados."
        )
        assisted = self.ai_response(
            message=f"{assist_prompt}\n\nMensagem do cliente: {user_message}",
            customer_name=customer_name,
            context=context,
        )
        if not assisted:
            return base_response
        assisted_norm = assisted.lower()
        if "sem ia ativa" in assisted_norm or "instabilidade no atendimento automático" in assisted_norm:
            return base_response
        return assisted

    def save_context(
        self,
        phone: str,
        name: str,
        intent: Optional[str],
        subject: Optional[str],
        response_type: str,
    ) -> None:
        normalized_phone = normalize_phone(phone)
        self.db.execute(
            """
            INSERT INTO chatbot.contexto_cliente (
                telefone, nome, ultima_interacao, status,
                ultima_intencao, ultimo_assunto, ultima_resposta_tipo,
                total_interacoes, updated_at
            ) VALUES (%s, %s, NOW(), 'ativo', %s, %s, %s, 1, NOW())
            ON CONFLICT (telefone)
            DO UPDATE SET
                nome = EXCLUDED.nome,
                ultima_interacao = NOW(),
                status = 'ativo',
                ultima_intencao = EXCLUDED.ultima_intencao,
                ultimo_assunto = EXCLUDED.ultimo_assunto,
                ultima_resposta_tipo = EXCLUDED.ultima_resposta_tipo,
                total_interacoes = chatbot.contexto_cliente.total_interacoes + 1,
                updated_at = NOW()
            """,
            (normalized_phone, name, intent, subject, response_type),
        )

    def touch_inbound_context(self, phone: str, name: str, source: str = "cliente") -> None:
        normalized_phone = normalize_phone(phone)
        self.db.execute(
            """
            INSERT INTO chatbot.contexto_cliente (
                telefone, nome, ultima_interacao, status,
                modo_conversa, ultima_origem_mensagem,
                total_interacoes, updated_at
            ) VALUES (%s, %s, NOW(), 'ativo', 'bot', %s, 1, NOW())
            ON CONFLICT (telefone)
            DO UPDATE SET
                nome = EXCLUDED.nome,
                ultima_interacao = NOW(),
                status = 'ativo',
                ultima_origem_mensagem = EXCLUDED.ultima_origem_mensagem,
                total_interacoes = chatbot.contexto_cliente.total_interacoes + 1,
                updated_at = NOW()
            """,
            (normalized_phone, name, source),
        )

    def set_conversation_mode(
        self,
        phone: str,
        name: str,
        mode: str,
        reason: Optional[str] = None,
    ) -> None:
        normalized_phone = normalize_phone(phone)
        self.db.execute(
            """
            INSERT INTO chatbot.contexto_cliente (
                telefone, nome, ultima_interacao, status,
                modo_conversa, ultimo_handoff_em, ultimo_handoff_motivo,
                updated_at
            ) VALUES (%s, %s, NOW(), 'ativo', %s, NOW(), %s, NOW())
            ON CONFLICT (telefone)
            DO UPDATE SET
                nome = EXCLUDED.nome,
                ultima_interacao = NOW(),
                status = 'ativo',
                modo_conversa = EXCLUDED.modo_conversa,
                ultimo_handoff_em = NOW(),
                ultimo_handoff_motivo = EXCLUDED.ultimo_handoff_motivo,
                updated_at = NOW()
            """,
            (normalized_phone, name, mode, reason),
        )

    def save_message(
        self,
        phone: str,
        name: str,
        direction: str,
        origin: str,
        text: str,
        event_key: Optional[str] = None,
        message_type: str = "text",
        payload: Optional[dict] = None,
        status: str = "received",
        response_source: Optional[str] = None,
        rule_name: Optional[str] = None,
        intent: Optional[str] = None,
    ) -> None:
        normalized_phone = normalize_phone(phone)
        payload_json = json.dumps(payload or {}, ensure_ascii=False, default=_json_default_serializer)
        self.db.execute(
            """
            INSERT INTO chatbot.mensagens (
                event_key, telefone, nome_contato, direcao, origem,
                tipo, conteudo_texto, payload_json, status,
                resposta_origem, regra_nome, intencao
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s)
            ON CONFLICT (event_key) WHERE event_key IS NOT NULL
            DO NOTHING
            """,
            (
                event_key,
                normalized_phone,
                name,
                direction,
                origin,
                message_type,
                text,
                payload_json,
                status,
                response_source,
                rule_name,
                intent,
            ),
        )

    def list_inactive_active_customers(self, timeout_minutes: int, limit: int = 50) -> list[dict]:
        return self.db.fetchall(
            """
            SELECT telefone, COALESCE(nome, '') AS nome
              FROM chatbot.contexto_cliente
             WHERE status = 'ativo'
               AND modo_conversa = 'bot'
               AND ultima_interacao <= NOW() - make_interval(mins => %s)
             ORDER BY ultima_interacao ASC
             LIMIT %s
            """,
            (timeout_minutes, limit),
        )

    def mark_context_closed_for_inactivity(self, phone: str) -> None:
        normalized_phone = normalize_phone(phone)
        self.db.execute(
            """
            UPDATE chatbot.contexto_cliente
               SET status = 'encerrado_inatividade',
                   modo_conversa = 'encerrado',
                   updated_at = NOW()
             WHERE telefone = %s
               AND status = 'ativo'
               AND modo_conversa = 'bot'
            """,
            (normalized_phone,),
        )

    def close_inactive_conversations(self) -> int:
        closed_count = 0
        contacts = self.list_inactive_active_customers(
            timeout_minutes=self.settings.inactivity_timeout_minutes,
            limit=100,
        )
        for contact in contacts:
            phone = (contact.get("telefone") or "").strip()
            if not phone:
                continue

            sent = self.send_meta_message(phone, INACTIVITY_CLOSING_MESSAGE)
            if not sent:
                continue

            name = (contact.get("nome") or "").strip()
            self.save_log(
                phone=phone,
                name=name,
                client_msg="[sistema] encerramento por inatividade",
                bot_msg=INACTIVITY_CLOSING_MESSAGE,
                source="automacao",
                rule_name="encerramento_inatividade",
            )
            self.mark_context_closed_for_inactivity(phone)
            closed_count += 1

        return closed_count

    def get_customer_context(self, phone: str) -> Optional[dict]:
        return self.db.fetchone(
            "SELECT * FROM chatbot.contexto_cliente WHERE telefone = %s",
            (normalize_phone(phone),),
        )

    def list_operator_conversations(self, mode: str = "aguardando_humano", limit: int = 50) -> list[dict]:
        allowed_modes = {"aguardando_humano", "humano", "bot", "encerrado"}
        normalized_mode = (mode or "aguardando_humano").strip().lower()
        if normalized_mode not in allowed_modes:
            normalized_mode = "aguardando_humano"

        return self.db.fetchall(
            """
            SELECT
                c.telefone,
                COALESCE(c.nome, '') AS nome,
                c.status,
                c.modo_conversa,
                c.ultima_interacao,
                COALESCE(m.conteudo_texto, '') AS ultima_mensagem,
                COALESCE(m.direcao, '') AS ultima_direcao,
                m.created_at AS ultima_mensagem_em
              FROM chatbot.contexto_cliente c
              LEFT JOIN LATERAL (
                    SELECT conteudo_texto, direcao, created_at
                      FROM chatbot.mensagens
                     WHERE telefone = c.telefone
                     ORDER BY created_at DESC, id DESC
                     LIMIT 1
              ) m ON TRUE
             WHERE c.modo_conversa = %s
             ORDER BY c.ultima_interacao DESC
             LIMIT %s
            """,
            (normalized_mode, max(1, min(int(limit), 100))),
        )

    def list_operator_messages(self, phone: str, limit: int = 100) -> list[dict]:
        normalized_phone = normalize_phone(phone)
        return self.db.fetchall(
            """
            SELECT
                id,
                telefone,
                COALESCE(nome_contato, '') AS nome_contato,
                direcao,
                origem,
                tipo,
                COALESCE(conteudo_texto, '') AS conteudo_texto,
                status,
                COALESCE(resposta_origem, '') AS resposta_origem,
                COALESCE(regra_nome, '') AS regra_nome,
                COALESCE(intencao, '') AS intencao,
                created_at
              FROM chatbot.mensagens
             WHERE telefone = %s
             ORDER BY created_at DESC, id DESC
             LIMIT %s
            """,
            (normalized_phone, max(1, min(int(limit), 200))),
        )

    def set_operator_conversation_mode(
        self,
        phone: str,
        mode: str,
        reason: str,
        status: str = "ativo",
    ) -> None:
        normalized_phone = normalize_phone(phone)
        self.db.execute(
            """
            UPDATE chatbot.contexto_cliente
               SET modo_conversa = %s,
                   status = %s,
                   ultimo_handoff_em = NOW(),
                   ultimo_handoff_motivo = %s,
                   updated_at = NOW()
             WHERE telefone = %s
            """,
            (mode, status, reason, normalized_phone),
        )

    def send_human_message(self, phone: str, text: str) -> bool:
        normalized_phone = normalize_phone(phone)
        normalized_text = (text or "").strip()
        if not normalized_phone or not normalized_text:
            raise ValueError("Telefone e mensagem são obrigatórios.")

        sent = self.send_meta_message(normalized_phone, normalized_text)
        self.save_message(
            phone=normalized_phone,
            name="",
            direction="outbound",
            origin="atendente",
            text=normalized_text,
            status="sent" if sent else "send_failed",
            response_source="humano",
            intent="atendimento_humano",
        )
        self.save_log(
            phone=normalized_phone,
            name="",
            client_msg="[atendente]",
            bot_msg=normalized_text,
            source="humano",
            rule_name="atendimento_humano",
        )
        self.set_operator_conversation_mode(
            normalized_phone,
            "humano",
            "resposta_humana",
            status="ativo",
        )
        return sent

    def notify_operator_handoff_start(self, customer_phone: str) -> bool:
        destination = normalize_phone(self.settings.operator_alert_whatsapp_number)
        normalized_customer_phone = normalize_phone(customer_phone)
        if not destination:
            logger.warning("Alerta de operador ignorado: OPERATOR_ALERT_WHATSAPP_NUMBER nao configurado.")
            return False
        if not normalized_customer_phone:
            raise ValueError("Telefone do cliente é obrigatório.")

        template_name = (self.settings.operator_alert_template_name or "").strip()
        template_language = (self.settings.operator_alert_template_language or "pt_BR").strip()
        if template_name:
            return self.send_meta_template_message(
                destination,
                template_name,
                template_language,
                [f"+{normalized_customer_phone}"],
            )

        message = (
            "🔔 Novo atendimento humano iniciado no painel.\n"
            f"Cliente: +{normalized_customer_phone}\n"
            "Acesse o painel para assumir ou continuar o atendimento."
        )
        return self.send_meta_message(destination, message)

    def send_meta_template_message(
        self,
        destination: str,
        template_name: str,
        language_code: str,
        body_params: list[str] | tuple[str, ...] = (),
    ) -> bool:
        normalized_destination = normalize_phone(destination)
        template_name = (template_name or "").strip()
        language_code = (language_code or "pt_BR").strip()
        if not normalized_destination:
            logger.error("Envio de template Meta ignorado por destino vazio após normalização.")
            return False
        if not template_name:
            logger.error("Envio de template Meta ignorado por nome de template vazio.")
            return False
        if not self.settings.meta_whatsapp_token or not self.settings.meta_phone_number_id:
            logger.error(
                "Envio de template Meta ignorado por configuração ausente. token=%s phone_number_id=%s",
                _token_hint(self.settings.meta_whatsapp_token),
                "ok" if self.settings.meta_phone_number_id else "ausente",
            )
            return False

        now = time.time()
        if now < self._meta_send_blocked_until:
            logger.warning(
                "Envio de template Meta temporariamente desabilitado por erro de autenticação anterior. destino=%s",
                _phone_log_id(normalized_destination),
            )
            return False

        components = []
        if body_params:
            components.append(
                {
                    "type": "body",
                    "parameters": [
                        {"type": "text", "text": str(param)}
                        for param in body_params
                    ],
                }
            )

        url = f"https://graph.facebook.com/v23.0/{self.settings.meta_phone_number_id}/messages"
        payload = {
            "messaging_product": "whatsapp",
            "to": normalized_destination,
            "type": "template",
            "template": {
                "name": template_name,
                "language": {"code": language_code},
            },
        }
        if components:
            payload["template"]["components"] = components

        self._debug_log(
            "Tentativa envio Meta template. destino=%s endpoint_phone_number_id=%s template=%s language=%s",
            _phone_log_id(normalized_destination),
            self.settings.meta_phone_number_id or "ausente",
            template_name,
            language_code,
        )

        req = urllib.request.Request(
            url=url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.settings.meta_whatsapp_token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                response_body = response.read().decode("utf-8", errors="replace")
                self._debug_log(
                    "Resposta Meta template success. status=%s body=%s",
                    getattr(response, "status", "n/a"),
                    response_body[:400],
                )
                logger.info("Template Meta enviado com sucesso para %s", _phone_log_id(normalized_destination))
                return True
        except HTTPError as exc:
            details = _http_error_body(exc)
            if exc.code in {401, 403}:
                self._meta_send_blocked_until = time.time() + 300
                logger.error(
                    "Erro de autenticação Meta (code=%s). Verifique META_WHATSAPP_TOKEN "
                    "e META_PHONE_NUMBER_ID.",
                    exc.code,
                )
            logger.error(
                "Falha HTTP ao enviar template Meta. code=%s destino=%s template=%s detalhe=%s",
                exc.code,
                _phone_log_id(normalized_destination),
                template_name,
                details or "-",
            )
            self._debug_log("HTTPError Meta template payload=%s", json.dumps(payload, ensure_ascii=False)[:400])
            return False
        except (URLError, TimeoutError) as exc:
            logger.error(
                "Falha de rede ao enviar template Meta. destino=%s template=%s erro=%s",
                _phone_log_id(normalized_destination),
                template_name,
                exc,
            )
            return False

    def return_conversation_to_bot(self, phone: str) -> dict[str, bool | str]:
        normalized_phone = normalize_phone(phone)
        if not normalized_phone:
            raise ValueError("Telefone é obrigatório.")

        self.set_operator_conversation_mode(
            normalized_phone,
            "bot",
            "devolvido_ao_bot",
            status="ativo",
        )

        transition_sent = self.send_meta_message(normalized_phone, RETURN_TO_BOT_TRANSITION_MESSAGE)
        self.save_message(
            phone=normalized_phone,
            name="",
            direction="outbound",
            origin="bot",
            text=RETURN_TO_BOT_TRANSITION_MESSAGE,
            status="sent" if transition_sent else "send_failed",
            response_source="roteador",
            intent="retorno_bot",
            rule_name="devolvido_ao_bot",
        )
        self.save_log(
            phone=normalized_phone,
            name="",
            client_msg="[sistema] retorno do atendimento humano",
            bot_msg=RETURN_TO_BOT_TRANSITION_MESSAGE,
            source="roteador",
            rule_name="devolvido_ao_bot",
        )

        menu_sent = self.send_meta_menu_message(normalized_phone, include_greeting=False)
        if not menu_sent:
            menu_sent = self.send_meta_message(normalized_phone, PROACTIVE_MENU_MESSAGE)

        self.save_message(
            phone=normalized_phone,
            name="",
            direction="outbound",
            origin="bot",
            text=PROACTIVE_MENU_MESSAGE,
            status="sent" if menu_sent else "send_failed",
            response_source="menu",
            intent="menu_inicial",
            rule_name="retorno_bot_menu",
        )
        self.save_log(
            phone=normalized_phone,
            name="",
            client_msg="[sistema] devolvido para bot",
            bot_msg=PROACTIVE_MENU_MESSAGE,
            source="menu",
            rule_name="retorno_bot_menu",
        )

        return {
            "status": "ok",
            "mode": "bot",
            "transition_sent": transition_sent,
            "menu_sent": menu_sent,
        }

    def save_log(
        self,
        phone: str,
        name: str,
        client_msg: str,
        bot_msg: str,
        source: str,
        rule_name: Optional[str],
    ) -> None:
        normalized_phone = normalize_phone(phone)
        self.db.execute(
            """
            INSERT INTO chatbot.log_conversas (
                telefone, nome_contato, mensagem_cliente,
                resposta_bot, origem_resposta, regra_nome
            ) VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (normalized_phone, name, client_msg, bot_msg, source, rule_name),
        )

    def send_meta_message(self, destination: str, text: str) -> bool:
        normalized_destination = normalize_phone(destination)
        if not normalized_destination:
            logger.error("Envio para Meta ignorado por destino vazio após normalização.")
            return False
        if not self.settings.meta_whatsapp_token or not self.settings.meta_phone_number_id:
            logger.error(
                "Envio para Meta ignorado por configuração ausente. token=%s phone_number_id=%s",
                _token_hint(self.settings.meta_whatsapp_token),
                "ok" if self.settings.meta_phone_number_id else "ausente",
            )
            return False

        now = time.time()
        if now < self._meta_send_blocked_until:
            logger.warning(
                "Envio para Meta temporariamente desabilitado por erro de autenticação anterior. destino=%s",
                _phone_log_id(normalized_destination),
            )
            return False

        url = f"https://graph.facebook.com/v23.0/{self.settings.meta_phone_number_id}/messages"
        payload = {
            "messaging_product": "whatsapp",
            "to": normalized_destination,
            "type": "text",
            "text": {"body": text},
        }
        self._debug_log(
            "Tentativa envio Meta text. destino=%s endpoint_phone_number_id=%s text_preview=%s",
            _phone_log_id(normalized_destination),
            self.settings.meta_phone_number_id or "ausente",
            (text or "").strip()[:120],
        )

        req = urllib.request.Request(
            url=url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.settings.meta_whatsapp_token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            try:
                with urllib.request.urlopen(req, timeout=10) as response:
                    response_body = response.read().decode("utf-8", errors="replace")
                    self._debug_log(
                        "Resposta Meta text success. status=%s body=%s",
                        getattr(response, "status", "n/a"),
                        response_body[:400],
                    )
                    logger.info("Mensagem enviada com sucesso para %s", _phone_log_id(normalized_destination))
                    return True

            except HTTPError as exc:
                details = _http_error_body(exc)
                retryable = exc.code in {408, 409, 429} or exc.code >= 500

                if attempt < max_attempts and retryable:
                    wait_seconds = 0.5 * (2 ** (attempt - 1))
                    logger.warning(
                        "Falha transitória ao enviar mensagem Meta. tentativa=%s/%s code=%s destino=%s",
                        attempt,
                        max_attempts,
                        exc.code,
                        _phone_log_id(normalized_destination),
                    )
                    time.sleep(wait_seconds)
                    continue

                if exc.code in {401, 403}:
                    self._meta_send_blocked_until = time.time() + 300
                    logger.error(
                        "Erro de autenticação Meta (code=%s). Verifique META_WHATSAPP_TOKEN "
                        "(token expirado/inválido ou sem permissões whatsapp_business_messaging) "
                        "e META_PHONE_NUMBER_ID.",
                        exc.code,
                    )

                logger.error(
                    "Falha HTTP ao enviar mensagem Meta. tentativa=%s/%s code=%s destino=%s detalhe=%s",
                    attempt,
                    max_attempts if retryable else attempt,
                    exc.code,
                    _phone_log_id(normalized_destination),
                    details or "-",
                )
                self._debug_log("HTTPError Meta text payload=%s", json.dumps(payload, ensure_ascii=False)[:400])
                return False

            except (URLError, TimeoutError) as exc:
                if attempt < max_attempts:
                    wait_seconds = 0.5 * (2 ** (attempt - 1))
                    logger.warning(
                        "Falha de rede ao enviar mensagem Meta. tentativa=%s/%s destino=%s erro=%s",
                        attempt,
                        max_attempts,
                        _phone_log_id(normalized_destination),
                        exc,
                    )
                    time.sleep(wait_seconds)
                    continue

                logger.error(
                    "Falha de rede final ao enviar mensagem Meta. tentativa=%s/%s destino=%s erro=%s",
                    attempt,
                    max_attempts,
                    _phone_log_id(normalized_destination),
                    exc,
                )
                return False

    def send_meta_menu_message(self, destination: str, *, include_greeting: bool = True) -> bool:
        normalized_destination = normalize_phone(destination)
        if not normalized_destination:
            logger.error("Envio de menu para Meta ignorado por destino vazio após normalização.")
            return False
        if not self.settings.meta_whatsapp_token or not self.settings.meta_phone_number_id:
            logger.error(
                "Envio de menu para Meta ignorado por configuração ausente. token=%s phone_number_id=%s",
                _token_hint(self.settings.meta_whatsapp_token),
                "ok" if self.settings.meta_phone_number_id else "ausente",
            )
            return False

        now = time.time()
        if now < self._meta_send_blocked_until:
            logger.warning(
                "Envio de menu para Meta temporariamente desabilitado por erro de autenticação anterior. destino=%s",
                _phone_log_id(normalized_destination),
            )
            return False

        url = f"https://graph.facebook.com/v23.0/{self.settings.meta_phone_number_id}/messages"
        payload = {
            "messaging_product": "whatsapp",
            "to": normalized_destination,
            "type": "interactive",
            "interactive": {
                "type": "list",
                "header": {
                    "type": "text",
                    "text": "Oi! Que bom falar com você. 💙"
                    if include_greeting
                    else "Vamos continuar por aqui. 💙",
                },
                "body": {
                    "text": "Sobre o que você precisa de ajuda?"
                    if include_greeting
                    else "Escolha uma opção para seguir com o atendimento.",
                },
                "footer": {"text": "Escreva uma frase curta ou escolha uma opção na lista."},
                "action": {
                    "button": "Ver opções",
                    "sections": [
                        {
                            "title": "Atendimento LavPop",
                            "rows": PROACTIVE_MENU_ROWS,
                        }
                    ],
                },
            },
        }
        self._debug_log(
            "Tentativa envio Meta menu. destino=%s endpoint_phone_number_id=%s",
            _phone_log_id(normalized_destination),
            self.settings.meta_phone_number_id or "ausente",
        )

        req = urllib.request.Request(
            url=url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.settings.meta_whatsapp_token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                response_body = response.read().decode("utf-8", errors="replace")
                self._debug_log(
                    "Resposta Meta menu success. status=%s body=%s",
                    getattr(response, "status", "n/a"),
                    response_body[:400],
                )
                logger.info("Menu interativo enviado com sucesso para %s", _phone_log_id(normalized_destination))
                return True
        except HTTPError as exc:
            details = _http_error_body(exc)
            if exc.code in {401, 403}:
                self._meta_send_blocked_until = time.time() + 300
            logger.error(
                "Falha HTTP ao enviar menu interativo Meta. code=%s destino=%s detalhe=%s",
                exc.code,
                _phone_log_id(normalized_destination),
                details or "-",
            )
            return False
        except (URLError, TimeoutError) as exc:
            logger.error(
                "Falha de rede ao enviar menu interativo Meta. destino=%s erro=%s",
                _phone_log_id(normalized_destination),
                exc,
            )
            return False

    def answer_message(self, phone: str, name: str, message: str) -> tuple[str, str, Optional[str], Optional[str]]:
        context = self.get_customer_context(phone)
        rule_name = None
        if self.is_proactive_greeting(message):
            response = PROACTIVE_MENU_MESSAGE
            source = "menu"
            response_type = "menu_boas_vindas"
            intent = "menu_inicial"
        else:
            active_rules = self._active_rules()
            option_response, option_intent, option_rule_name, option_source = self.proactive_menu_option_response(
                message, rules=active_rules
            )
            if option_response:
                base_source = option_source or "menu"
                response = option_response
                source = base_source
                response_type = f"menu_opcao_{base_source}"
                intent = option_intent
                rule_name = option_rule_name
            else:
                rule_answer, rule_name = self._match_rule_response(message, rules=active_rules)
                intent = self.classify_intent(message)

                if rule_answer:
                    response = self.ai_router_assist_response(
                        customer_name=name,
                        user_message=message,
                        base_response=rule_answer,
                        response_origin="banco",
                        context=context,
                    )
                    source = "banco"
                    response_type = f"regra_{rule_name}_com_ia"
                elif is_sensitive_request(message):
                    response = (
                        "Por segurança, eu não posso informar esse dado por aqui sem validação. "
                        "Vou encaminhar agora para atendimento humano te orientar com segurança. 🤝"
                    )
                    source = "seguranca"
                    response_type = "seguranca_encaminhamento"
                else:
                    response = self.ai_response(message, name, context)
                    source = "ia"
                    response_type = "ia"

        self.save_log(phone, name, message, response, source, rule_name)
        self.save_context(phone, name, intent, rule_name or intent, response_type)

        return response, source, rule_name, intent
