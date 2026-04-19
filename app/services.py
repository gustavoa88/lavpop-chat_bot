import json
import re
import urllib.request
from typing import Any, Optional

from openai import OpenAI

from app.config import Settings
from app.db import Database


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


class ChatService:
    def __init__(self, db: Database, settings: Settings):
        self.db = db
        self.settings = settings
        self.client = OpenAI(api_key=settings.openai_api_key) if settings.openai_api_key else None

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
                keywords = json.loads(keywords)
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
            if intent["nome_intencao"].replace("_", " ") in message_norm:
                return intent["nome_intencao"]
        return None

    def ai_response(self, message: str, customer_name: str, context: Optional[dict]) -> str:
        if not self.client:
            return "No momento estou sem IA ativa. Posso te ajudar com horário, preço e serviços 🙂"

        system_prompt = (
            "Você é atendente virtual da lavanderia LavPop Jardim São Bernardo. "
            "Responda em português brasileiro, em tom amigável e objetivo. "
            "Se não souber algo, diga que vai encaminhar para atendimento humano."
        )

        context_prompt = f"Contexto cliente: {json.dumps(context or {}, ensure_ascii=False)}"

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
        return completion.output_text.strip()

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
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.settings.meta_whatsapp_token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10):
            return

    def answer_message(self, phone: str, name: str, message: str) -> tuple[str, str, Optional[str], Optional[str]]:
        context = self.get_customer_context(phone)
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
