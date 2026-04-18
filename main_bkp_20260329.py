from fastapi import FastAPI, Request
from fastapi.responses import Response
from dotenv import load_dotenv
from openai import OpenAI
from psycopg2.pool import ThreadedConnectionPool
import psycopg2
import psycopg2.extras
import html
import os
import re
import time
from threading import Lock
from typing import Optional, Tuple, List, Dict, Any

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
    "connect_timeout": int(os.getenv("DB_CONNECT_TIMEOUT", "2")),
    "application_name": "lavpop_bot",
}

DB_POOL_MIN = int(os.getenv("DB_POOL_MIN", "1"))
DB_POOL_MAX = int(os.getenv("DB_POOL_MAX", "2"))
DB_STATEMENT_TIMEOUT_MS = int(os.getenv("DB_STATEMENT_TIMEOUT_MS", "3000"))
FAQ_CACHE_TTL_SECONDS = int(os.getenv("FAQ_CACHE_TTL_SECONDS", "60"))

ENABLE_DB_LOG = os.getenv("ENABLE_DB_LOG", "false").lower() == "true"
LOG_IGNORE_GREETINGS = os.getenv("LOG_IGNORE_GREETINGS", "true").lower() == "true"

db_pool: Optional[ThreadedConnectionPool] = None
faq_cache: List[Dict[str, Any]] = []
faq_cache_loaded_at: float = 0.0
faq_cache_lock = Lock()

# =========================
# APP
# =========================
@app.on_event("startup")
async def startup_event():
    init_db_pool()


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

    resposta, origem, regra_nome = gerar_resposta(mensagem)

    if deve_salvar_log(mensagem):
        print("LOG: Vai salvar")
        salvar_log_conversa(
            telefone=remetente,
            nome_contato=nome_contato,
            mensagem_cliente=mensagem,
            resposta_bot=resposta,
            origem_resposta=origem,
            regra_nome=regra_nome,
        )
    else:
        print("LOG: ignorado") 

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


def deve_salvar_log(mensagem: str) -> bool:
    if not ENABLE_DB_LOG:
        return False

    if not LOG_IGNORE_GREETINGS:
        return True

    msg = normalizar_texto(mensagem)
    saudacoes = {"oi", "ola", "bom dia", "boa tarde", "boa noite"}
    return msg not in saudacoes


def init_db_pool() -> None:
    global db_pool

    if db_pool is not None:
        return

    try:
        db_pool = ThreadedConnectionPool(
            minconn=DB_POOL_MIN,
            maxconn=DB_POOL_MAX,
            **DB_CONFIG,
        )
        print(f"DB_POOL: inicializado com min={DB_POOL_MIN} max={DB_POOL_MAX}")
    except Exception as e:
        db_pool = None
        print(f"Erro ao inicializar pool do DB: {e}")


def get_db_connection():
    global db_pool

    if db_pool is None:
        init_db_pool()

    if db_pool is None:
        raise RuntimeError("Pool de conexão com banco não está disponível")

    conn = db_pool.getconn()

    try:
        conn.autocommit = False
        with conn.cursor() as cursor:
            cursor.execute("SET SESSION statement_timeout = %s", (DB_STATEMENT_TIMEOUT_MS,))
        return conn
    except Exception:
        try:
            db_pool.putconn(conn, close=True)
        except Exception:
            pass
        raise


def put_db_connection(conn, close: bool = False) -> None:
    global db_pool
    if conn is not None and db_pool is not None:
        db_pool.putconn(conn, close=close)


def carregar_regras_db() -> List[Dict[str, Any]]:
    conn = None
    cursor = None

    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        cursor.execute("""
            SELECT id, nome_regra, palavras_chave, resposta, prioridade
            FROM chatbot.faq_regras
            WHERE ativo = true
            ORDER BY prioridade ASC, id ASC
        """)

        return cursor.fetchall() or []

    finally:
        if cursor:
            try:
                cursor.close()
            except Exception:
                pass
        if conn:
            put_db_connection(conn)


def get_faq_regras() -> List[Dict[str, Any]]:
    global faq_cache, faq_cache_loaded_at

    now = time.time()

    with faq_cache_lock:
        if faq_cache and (now - faq_cache_loaded_at) < FAQ_CACHE_TTL_SECONDS:
            return faq_cache

        try:
            faq_cache = carregar_regras_db()
            faq_cache_loaded_at = now
            print(f"FAQ_CACHE: carregado com {len(faq_cache)} regras")
        except Exception as e:
            print(f"Erro ao carregar FAQ do DB: {e}")
            if not faq_cache:
                faq_cache = []

        return faq_cache


def buscar_resposta_db(mensagem: str) -> Tuple[Optional[str], Optional[str]]:
    try:
        regras = get_faq_regras()
        msg_normalizada = normalizar_texto(mensagem)

        melhor_resposta = None
        melhor_score = 0
        melhor_regra = None
        melhor_prioridade = None

        for regra in regras:
            palavras = regra.get("palavras_chave") or []
            resposta = regra.get("resposta")
            nome_regra = regra.get("nome_regra")
            prioridade = regra.get("prioridade")

            score = 0
            for palavra in palavras:
                palavra_norm = normalizar_texto(str(palavra))
                if palavra_norm and palavra_norm in msg_normalizada:
                    score += 1

            if score > 0:
                if (
                    melhor_resposta is None
                    or score > melhor_score
                    or (
                        score == melhor_score
                        and melhor_prioridade is not None
                        and prioridade < melhor_prioridade
                    )
                ):
                    melhor_resposta = resposta
                    melhor_score = score
                    melhor_regra = nome_regra
                    melhor_prioridade = prioridade

        if melhor_resposta:
            melhor_resposta = melhor_resposta.replace("\\n", "\n")
            print(f"REGRA_ENCONTRADA: {melhor_regra} | SCORE: {melhor_score}")
            return melhor_resposta, melhor_regra

        print("REGRA_ENCONTRADA: nenhuma")
        return None, None

    except Exception as e:
        print(f"Erro DB em buscar_resposta_db: {e}")
        return None, None


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


def salvar_log_conversa(
    telefone: str,
    nome_contato: str,
    mensagem_cliente: str,
    resposta_bot: str,
    origem_resposta: str,
    regra_nome: Optional[str],
) -> None:
    conn = None
    cursor = None

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO chatbot.log_conversas (
                telefone,
                nome_contato,
                mensagem_cliente,
                resposta_bot,
                origem_resposta,
                regra_nome
            )
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (
            telefone,
            nome_contato,
            mensagem_cliente,
            resposta_bot,
            origem_resposta,
            regra_nome,
        ))

        conn.commit()

    except Exception as e:
        print(f"Erro ao salvar log: {e}")
        try:
            if conn:
                conn.rollback()
        except Exception:
            pass
        try:
            if conn:
                put_db_connection(conn, close=True)
                conn = None
        except Exception:
            pass

    finally:
        if cursor:
            try:
                cursor.close()
            except Exception:
                pass
        if conn:
            put_db_connection(conn)


def gerar_resposta(mensagem: str) -> Tuple[str, str, Optional[str]]:
    resposta_db, regra_nome = buscar_resposta_db(mensagem)

    if resposta_db:
        print("RESPOSTA_ORIGEM: BANCO")
        print(f"RESPOSTA_FINAL: {resposta_db}")
        return resposta_db, "banco", regra_nome

    print("RESPOSTA_ORIGEM: IA")
    resposta_ia = gerar_resposta_ia(mensagem)
    print(f"RESPOSTA_FINAL: {resposta_ia}")
    return resposta_ia, "ia", None