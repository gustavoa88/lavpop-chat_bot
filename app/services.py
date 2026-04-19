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
        "lookup_terms": ["servicos", "tipos de servico", "o que voces fazem"],
        "fallback": (
            "✅ *Serviços disponíveis*\n"
            "- Lavagem de roupas do dia a dia\n"
            "- Peças delicadas\n"
            "- Edredons e cobertores\n"
            "- Passadoria\n"
            "- Coleta e entrega (sob consulta de região)"
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


class ChatService:
    def __init__(self, db: Database, settings: Settings):
        self.db = db
        self.settings = settings
        self.client = OpenAI(api_key=settings.openai_api_key) if settings.openai_api_key else None
        self._meta_send_blocked_until = 0.0

    def find_rule_response(self, message: str) -> tuple[Optional[str], Optional[str]]:
        msg_norm = normalize_text(message)
        rules = self.db.fetchall(
            """
            SELECT nome_regra, resposta, palavras_chave
              FROM chatbot.faq_regras
             WHERE ativo = TRUE
             ORDER BY prioridade ASC, id ASC
            """
        )
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
        self, message: str
    ) -> tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
        option_key = _extract_menu_option_token(message)
        option = PROACTIVE_MENU_OPTIONS.get(option_key)
        if not option:
            return None, None, None, None

        for term in option["lookup_terms"]:
            db_answer, rule_name = self.find_rule_response(term)
            if db_answer:
                return db_answer, option["intent"], rule_name, "banco"

        return option["fallback"], option["intent"], None, "menu"

    def ai_response(self, message: str, customer_name: str, context: Optional[dict]) -> str:
        if not self.client:
            return "No momento estou sem IA ativa. Posso te ajudar com horário, preço e serviços 🙂"

        system_prompt = (
            "Você é atendente virtual da lavanderia LavPop Jardim São Bernardo. "
            "Responda em português brasileiro, em tom amigável e objetivo. "
            "Se não souber algo, diga que vai encaminhar para atendimento humano."
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
                ultima_intencao = EXCLUDED.ultima_intencao,
                ultimo_assunto = EXCLUDED.ultimo_assunto,
                ultima_resposta_tipo = EXCLUDED.ultima_resposta_tipo,
                total_interacoes = chatbot.contexto_cliente.total_interacoes + 1,
                updated_at = NOW()
            """,
            (phone, name, intent, subject, response_type),
        )

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

    def send_meta_message(self, destination: str, text: str) -> None:
        if not self.settings.meta_whatsapp_token or not self.settings.meta_phone_number_id:
            logger.error(
                "Envio para Meta ignorado por configuração ausente. token=%s phone_number_id=%s",
                _token_hint(self.settings.meta_whatsapp_token),
                "ok" if self.settings.meta_phone_number_id else "ausente",
            )
            return

        now = time.time()
        if now < self._meta_send_blocked_until:
            logger.warning(
                "Envio para Meta temporariamente desabilitado por erro de autenticação anterior. destino=%s",
                destination,
            )
            return

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
                    logger.info("Mensagem enviada com sucesso para %s", destination)
                    return

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
                        destination,
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
                    destination,
                    details or "-",
                )
                return

            except (URLError, TimeoutError) as exc:
                if attempt < max_attempts:
                    wait_seconds = 0.5 * (2 ** (attempt - 1))
                    logger.warning(
                        "Falha de rede ao enviar mensagem Meta. tentativa=%s/%s destino=%s erro=%s",
                        attempt,
                        max_attempts,
                        destination,
                        exc,
                    )
                    time.sleep(wait_seconds)
                    continue

                logger.error(
                    "Falha de rede final ao enviar mensagem Meta. tentativa=%s/%s destino=%s erro=%s",
                    attempt,
                    max_attempts,
                    destination,
                    exc,
                )
                return

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
                destination,
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
                logger.info("Menu interativo enviado com sucesso para %s", destination)
                return True
        except HTTPError as exc:
            details = _http_error_body(exc)
            if exc.code in {401, 403}:
                self._meta_send_blocked_until = time.time() + 300
            logger.error(
                "Falha HTTP ao enviar menu interativo Meta. code=%s destino=%s detalhe=%s",
                exc.code,
                destination,
                details or "-",
            )
            return False
        except (URLError, TimeoutError) as exc:
            logger.error(
                "Falha de rede ao enviar menu interativo Meta. destino=%s erro=%s",
                destination,
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
            option_response, option_intent, option_rule_name, option_source = self.proactive_menu_option_response(
                message
            )
            if option_response:
                response = option_response
                source = option_source or "menu"
                response_type = f"menu_opcao_{source}"
                intent = option_intent
                rule_name = option_rule_name
            else:
                rule_answer, rule_name = self.find_rule_response(message)
                intent = self.classify_intent(message)

                if rule_answer:
                    response = rule_answer
                    source = "banco"
                    response_type = f"regra_{rule_name}"
                else:
                    response = self.ai_response(message, name, context)
                    source = "ia"
                    response_type = "ia"

        self.save_log(phone, name, message, response, source, rule_name)
        self.save_context(phone, name, intent, rule_name or intent, response_type)

        return response, source, rule_name, intent
