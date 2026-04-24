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
    return title_to_option.get(compact_no_punct, "")


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
    return (phone or "").replace("whatsapp:", "").strip()


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
        return msg_norm in simple_greetings

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

        system_prompt = (
            "Você é atendente virtual da lavanderia LavPop Jardim São Bernardo. "
            "Responda em português brasileiro, em tom amigável e objetivo. "
            "Nunca invente dados. "
            "Se não houver confirmação explícita no contexto, diga que não tem essa informação e encaminhe para atendimento humano. "
            "Para pedidos sensíveis (senha, código de acesso, credenciais, dados pessoais, dados bancários), "
            "nunca forneça valores: apenas informe que um atendente humano vai orientar com segurança."
        )

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

    def save_context(
        self,
        phone: str,
        name: str,
        intent: Optional[str],
        subject: Optional[str],
        response_type: str,
    ) -> None:
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
            (phone, name, intent, subject, response_type),
        )

    def touch_inbound_context(self, phone: str, name: str, source: str = "cliente") -> None:
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
            (phone, name, source),
        )

    def set_conversation_mode(
        self,
        phone: str,
        name: str,
        mode: str,
        reason: Optional[str] = None,
    ) -> None:
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
            (phone, name, mode, reason),
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
                phone,
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
               AND ultima_interacao <= NOW() - make_interval(mins => %s)
             ORDER BY ultima_interacao ASC
             LIMIT %s
            """,
            (timeout_minutes, limit),
        )

    def mark_context_closed_for_inactivity(self, phone: str) -> None:
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
            (phone,),
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
            (phone,),
        )

    def save_log(
        self,
        phone: str,
        name: str,
        client_msg: str,
        bot_msg: str,
        source: str,
        rule_name: Optional[str],
    ) -> None:
        self.db.execute(
            """
            INSERT INTO chatbot.log_conversas (
                telefone, nome_contato, mensagem_cliente,
                resposta_bot, origem_resposta, regra_nome
            ) VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (phone, name, client_msg, bot_msg, source, rule_name),
        )

    def send_meta_message(self, destination: str, text: str) -> bool:
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
                _phone_log_id(destination),
            )
            return False

        url = f"https://graph.facebook.com/v23.0/{self.settings.meta_phone_number_id}/messages"
        payload = {
            "messaging_product": "whatsapp",
            "to": destination,
            "type": "text",
            "text": {"body": text},
        }

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
                with urllib.request.urlopen(req, timeout=10):
                    logger.info("Mensagem enviada com sucesso para %s", _phone_log_id(destination))
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
                        _phone_log_id(destination),
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
                    _phone_log_id(destination),
                    details or "-",
                )
                return False

            except (URLError, TimeoutError) as exc:
                if attempt < max_attempts:
                    wait_seconds = 0.5 * (2 ** (attempt - 1))
                    logger.warning(
                        "Falha de rede ao enviar mensagem Meta. tentativa=%s/%s destino=%s erro=%s",
                        attempt,
                        max_attempts,
                        _phone_log_id(destination),
                        exc,
                    )
                    time.sleep(wait_seconds)
                    continue

                logger.error(
                    "Falha de rede final ao enviar mensagem Meta. tentativa=%s/%s destino=%s erro=%s",
                    attempt,
                    max_attempts,
                    _phone_log_id(destination),
                    exc,
                )
                return False

    def send_meta_menu_message(self, destination: str) -> bool:
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
                _phone_log_id(destination),
            )
            return False

        url = f"https://graph.facebook.com/v23.0/{self.settings.meta_phone_number_id}/messages"
        payload = {
            "messaging_product": "whatsapp",
            "to": destination,
            "type": "interactive",
            "interactive": {
                "type": "list",
                "header": {"type": "text", "text": "Oi! Que bom falar com você. 💙"},
                "body": {"text": "Sobre o que você precisa de ajuda?"},
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
            with urllib.request.urlopen(req, timeout=10):
                logger.info("Menu interativo enviado com sucesso para %s", _phone_log_id(destination))
                return True
        except HTTPError as exc:
            details = _http_error_body(exc)
            if exc.code in {401, 403}:
                self._meta_send_blocked_until = time.time() + 300
            logger.error(
                "Falha HTTP ao enviar menu interativo Meta. code=%s destino=%s detalhe=%s",
                exc.code,
                _phone_log_id(destination),
                details or "-",
            )
            return False
        except (URLError, TimeoutError) as exc:
            logger.error(
                "Falha de rede ao enviar menu interativo Meta. destino=%s erro=%s",
                _phone_log_id(destination),
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
                response = option_response
                source = option_source or "menu"
                response_type = f"menu_opcao_{source}"
                intent = option_intent
                rule_name = option_rule_name
            else:
                rule_answer, rule_name = self._match_rule_response(message, rules=active_rules)
                intent = self.classify_intent(message)

                if rule_answer:
                    response = rule_answer
                    source = "banco"
                    response_type = f"regra_{rule_name}"
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
