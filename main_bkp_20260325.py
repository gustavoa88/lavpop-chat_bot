from fastapi import FastAPI, Request
from fastapi.responses import Response
from dotenv import load_dotenv
from openai import OpenAI
import psycopg2
import psycopg2.extras
import html
import os
import re
from typing import Optional

load_dotenv()

app = FastAPI()

# =========================
# CONFIG OPENAI
# =========================
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

# =========================
# CONFIG DB
# =========================
DB_CONFIG = {
    "host": os.getenv("DB_HOST"),
    "dbname": os.getenv("DB_NAME"),
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"),
    "port": os.getenv("DB_PORT", "5432"),
}

# =========================
# APP
# =========================
@app.get("/")
async def home():
    return {"status": "ok", "service": "lavpop-bot"}


@app.post("/webhook")
async def webhook(request: Request):
    data = await request.form()

    mensagem = (data.get("Body") or "").strip()
    remetente = data.get("From", "")
    nome_contato = data.get("ProfileName", "")

    print(f"Mensagem recebida de {remetente} ({nome_contato}): {mensagem}")

    resposta = gerar_resposta(mensagem)

    resposta_xml = html.escape(resposta)

    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Message>{resposta_xml}</Message>
</Response>"""

    return Response(content=twiml, media_type="text/xml")


# =========================
# FUNÇÕES AUXILIARES
# =========================
def normalizar_texto(texto: str) -> str:
    if not texto:
        return ""

    texto = texto.lower().strip()
    texto = texto.replace("á", "a").replace("à", "a").replace("ã", "a").replace("â", "a")
    texto = texto.replace("é", "e").replace("ê", "e")
    texto = texto.replace("í", "i")
    texto = texto.replace("ó", "o").replace("ô", "o").replace("õ", "o")
    texto = texto.replace("ú", "u")
    texto = texto.replace("ç", "c")
    texto = re.sub(r"\s+", " ", texto)
    return texto


def conectar_db():
    return psycopg2.connect(**DB_CONFIG)


def buscar_resposta_db(mensagem: str):
    conn = None
    cursor = None

    try:
        conn = conectar_db()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        cursor.execute("""
            SELECT id, nome_regra, palavras_chave, resposta, prioridade
            FROM chatbot.faq_regras
            WHERE ativo = true
            ORDER BY prioridade ASC, id ASC
        """)

        regras = cursor.fetchall()
        msg_normalizada = normalizar_texto(mensagem)

        melhor_resposta = None
        melhor_score = 0
        melhor_regra = None

        for regra in regras:
            palavras = regra["palavras_chave"] or []
            resposta = regra["resposta"]
            nome_regra = regra["nome_regra"]

            score = 0

            for palavra in palavras:
                palavra_norm = normalizar_texto(str(palavra))
                if palavra_norm and palavra_norm in msg_normalizada:
                    score += 1

            if score > melhor_score:
                melhor_score = score
                melhor_resposta = resposta
                melhor_regra = nome_regra

        if melhor_resposta:
            print(f"REGRA_ENCONTRADA: {melhor_regra} | SCORE: {melhor_score}")
            return melhor_resposta

        print("REGRA_ENCONTRADA: nenhuma")
        return None

    except Exception as e:
        print(f"Erro DB: {e}")
        return None

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


def gerar_resposta_ia(mensagem: str) -> str:
    msg = normalizar_texto(mensagem)

    temas_criticos = [
        "preco", "valor", "custa", "pagamento", "pagar", "horario", "horas",
        "endereco", "localizacao", "onde fica", "tempo", "demora",
        "edredom", "capacidade", "kg", "quilo", "quilos"
    ]

    if any(tema in msg for tema in temas_criticos):
        return (
            "No momento, não encontrei essa informação confirmada na base da unidade. "
            "Posso te ajudar com valores, horário, endereço e como funciona a lavanderia 😊"
        )

    if not client:
        return (
            "No momento, não tenho essa informação confirmada. "
            "Posso te ajudar com valores, horário, endereço e como funciona a unidade 😊"
        )

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": """
Você é um atendente da LavPop.

IMPORTANTE:
- Nunca invente informações
- Nunca responda sobre preço, pagamento, horário, endereço, capacidade, tempo ou regras da unidade sem confirmação
- Se a pergunta for operacional e não estiver confirmada, diga que não encontrou a informação na base
- Seja educado, direto e curto
                    """.strip(),
                },
                {"role": "user", "content": mensagem},
            ],
        )

        conteudo = response.choices[0].message.content
        if conteudo and conteudo.strip():
            return conteudo.strip()

    except Exception as e:
        print(f"Erro OpenAI: {e}")

    return (
        "No momento, não tenho essa informação confirmada. "
        "Posso te ajudar com valores, horário, endereço e como funciona a unidade 😊"
    )


# =========================
# RESPOSTA PRINCIPAL
# =========================
def gerar_resposta(mensagem: str) -> str:
    resposta_db = buscar_resposta_db(mensagem)

    if resposta_db:
        print("RESPOSTA_ORIGEM: BANCO")
        print(f"RESPOSTA_FINAL: {resposta_db}")
        return resposta_db

    print("RESPOSTA_ORIGEM: IA")
    resposta_ia = gerar_resposta_ia(mensagem)
    print(f"RESPOSTA_FINAL: {resposta_ia}")
    return resposta_ia