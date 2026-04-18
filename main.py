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

# =========================================================
# CONFIG
# =========================================================
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

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
ENABLE_CONTINUATION_HINT = os.getenv("ENABLE_CONTINUATION_HINT", "true").lower() == "true"

# =========================================================
# ESTADO GLOBAL
# =========================================================
db_pool: Optional[ThreadedConnectionPool] = None
faq_cache: List[Dict[str, Any]] = []
faq_cache_loaded_at: float = 0.0
faq_cache_lock = Lock()

# =========================================================
# APP
# =========================================================
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
    remetente = normalizar_telefone((data.get("From") or "").strip())
    nome_contato = (data.get("ProfileName") or "").strip()

    print(f"Mensagem recebida de {remetente} ({nome_contato}): {mensagem}")

    contexto = buscar_contexto_cliente(remetente)
    print(f"CONTEXTO_CLIENTE: {contexto}")

    resposta, origem, regra_nome, nome_intencao = gerar_resposta(
        mensagem=mensagem,
        contexto=contexto,
        nome_contato=nome_contato,
    )

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

    salvar_contexto_cliente(
        telefone=remetente,
        nome_contato=nome_contato,
        nome_intencao=nome_intencao,
        ultimo_assunto=regra_nome or nome_intencao,
        ultima_resposta_tipo=definir_tipo_resposta(regra_nome, nome_intencao, resposta, origem),
    )

    resposta_xml = html.escape(resposta)

    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Message>{resposta_xml}</Message>
</Response>"""

    return Response(content=twiml, media_type="text/xml")


# =========================================================
# NORMALIZAÇÃO / TEXTO
# =========================================================
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
    texto = re.sub(r"[^\w\s!?.,:+-]", " ", texto)
    texto = re.sub(r"\s+", " ", texto)
    return texto.strip()


def normalizar_telefone(telefone: str) -> str:
    if not telefone:
        return ""
    telefone = telefone.strip()
    telefone = telefone.replace("whatsapp:", "")
    return telefone


def texto_contem_termo(msg_normalizada: str, termo_normalizado: str) -> bool:
    if not termo_normalizado:
        return False

    pattern = rf"(?<!\w){re.escape(termo_normalizado)}(?!\w)"
    if re.search(pattern, msg_normalizada):
        return True

    return termo_normalizado in msg_normalizada


def eh_saudacao_pura(mensagem: str) -> bool:
    msg = normalizar_texto(mensagem)
    saudacoes = {"oi", "ola", "bom dia", "boa tarde", "boa noite", "opa", "olá"}
    return msg in saudacoes


# =========================================================
# BANCO / CONEXÃO
# =========================================================
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


# =========================================================
# CONTEXTO CLIENTE
# =========================================================
def buscar_contexto_cliente(telefone: str) -> Optional[Dict[str, Any]]:
    conn = None
    cursor = None

    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        cursor.execute("""
            SELECT
                telefone,
                nome,
                ultima_interacao,
                status,
                observacoes,
                ultima_intencao,
                ultimo_assunto,
                ultima_resposta_tipo,
                total_interacoes,
                updated_at
            FROM chatbot.contexto_cliente
            WHERE telefone = %s
            LIMIT 1
        """, (telefone,))

        return cursor.fetchone()

    except Exception as e:
        print(f"Erro ao buscar contexto do cliente: {e}")
        return None

    finally:
        if cursor:
            try:
                cursor.close()
            except Exception:
                pass
        if conn:
            put_db_connection(conn)


def salvar_contexto_cliente(
    telefone: str,
    nome_contato: str,
    nome_intencao: Optional[str],
    ultimo_assunto: Optional[str],
    ultima_resposta_tipo: Optional[str],
) -> None:
    conn = None
    cursor = None

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO chatbot.contexto_cliente (
                telefone,
                nome,
                ultima_interacao,
                status,
                observacoes,
                ultima_intencao,
                ultimo_assunto,
                ultima_resposta_tipo,
                total_interacoes,
                updated_at
            )
            VALUES (
                %s,
                %s,
                NOW(),
                %s,
                %s,
                %s,
                %s,
                %s,
                1,
                NOW()
            )
            ON CONFLICT (telefone)
            DO UPDATE SET
                nome = EXCLUDED.nome,
                ultima_interacao = NOW(),
                status = EXCLUDED.status,
                ultima_intencao = EXCLUDED.ultima_intencao,
                ultimo_assunto = EXCLUDED.ultimo_assunto,
                ultima_resposta_tipo = EXCLUDED.ultima_resposta_tipo,
                total_interacoes = COALESCE(chatbot.contexto_cliente.total_interacoes, 0) + 1,
                updated_at = NOW()
        """, (
            telefone,
            nome_contato or None,
            "ativo",
            None,
            nome_intencao,
            ultimo_assunto,
            ultima_resposta_tipo,
        ))

        conn.commit()
        print(
            "CONTEXTO_SALVO:",
            telefone,
            nome_intencao,
            ultimo_assunto,
            ultima_resposta_tipo,
        )

    except Exception as e:
        print(f"Erro ao salvar contexto do cliente: {e}")
        try:
            if conn:
                conn.rollback()
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


def definir_tipo_resposta(
    regra_nome: Optional[str],
    nome_intencao: Optional[str],
    resposta: str,
    origem: str,
) -> str:
    resposta_norm = normalizar_texto(resposta)
    regra = normalizar_texto(regra_nome or "")
    intencao = normalizar_texto(nome_intencao or "")

    if origem == "ia":
        return "ia"

    if any(t in resposta_norm for t in ["nao", "não", "nao rola", "nao conseguimos", "não conseguimos"]):
        if regra in {"edredom"} or intencao in {"capacidade_peca"}:
            return "negativa_capacidade"
        return "negativa"

    return "informativa"


def saudacao_contextual(contexto: Optional[Dict[str, Any]]) -> str:
    if not contexto:
        return "Opa! 😊 Aqui é o atendimento da LavPop Jardim São Bernardo. Como posso te ajudar?"

    total = contexto.get("total_interacoes") or 0
    if total >= 3:
        return "Opa! 😊 Que bom te ver por aqui de novo. Como posso te ajudar?"

    return "Opa! 😊 Aqui é o atendimento da LavPop Jardim São Bernardo. Como posso te ajudar?"


# =========================================================
# REGRAS / CACHE
# =========================================================
def carregar_regras_db() -> List[Dict[str, Any]]:
    conn = None
    cursor = None

    consultas = [
        """
        SELECT
            id,
            nome_regra,
            COALESCE(nome_intencao, nome_regra) AS nome_intencao,
            palavras_chave,
            resposta,
            prioridade,
            COALESCE(humanizar, true) AS humanizar
        FROM chatbot.faq_regras
        WHERE ativo = true
        ORDER BY prioridade ASC, id ASC
        """,
        """
        SELECT
            id,
            nome_regra,
            nome_regra AS nome_intencao,
            palavras_chave,
            resposta,
            prioridade,
            COALESCE(humanizar, true) AS humanizar
        FROM chatbot.faq_regras
        WHERE ativo = true
        ORDER BY prioridade ASC, id ASC
        """,
        """
        SELECT
            id,
            nome_regra,
            nome_regra AS nome_intencao,
            palavras_chave,
            resposta,
            prioridade,
            true AS humanizar
        FROM chatbot.faq_regras
        WHERE ativo = true
        ORDER BY prioridade ASC, id ASC
        """
    ]

    ultimo_erro = None

    for sql in consultas:
        conn = None
        cursor = None
        try:
            conn = get_db_connection()
            cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cursor.execute(sql)
            return cursor.fetchall() or []
        except Exception as e:
            ultimo_erro = e
            if cursor:
                try:
                    cursor.close()
                except Exception:
                    pass
            if conn:
                try:
                    put_db_connection(conn, close=True)
                except Exception:
                    pass
        finally:
            if cursor:
                try:
                    cursor.close()
                except Exception:
                    pass
            if conn:
                try:
                    put_db_connection(conn)
                except Exception:
                    pass

    print(f"Erro ao carregar regras do DB: {ultimo_erro}")
    return []


def get_faq_regras() -> List[Dict[str, Any]]:
    global faq_cache, faq_cache_loaded_at

    now = time.time()

    with faq_cache_lock:
        if faq_cache and (now - faq_cache_loaded_at) < FAQ_CACHE_TTL_SECONDS:
            return faq_cache

        faq_cache = carregar_regras_db()
        faq_cache_loaded_at = now
        print(f"FAQ_CACHE: carregado com {len(faq_cache)} regras")
        return faq_cache


# =========================================================
# MATCH / INTENÇÃO
# =========================================================
def calcular_score_regra(msg_normalizada: str, regra: Dict[str, Any]) -> int:
    palavras = regra.get("palavras_chave") or []
    score = 0

    for palavra in palavras:
        palavra_norm = normalizar_texto(str(palavra))
        if not palavra_norm:
            continue

        if texto_contem_termo(msg_normalizada, palavra_norm):
            score += 2

    return score


def buscar_regra(mensagem: str) -> Tuple[Optional[Dict[str, Any]], Optional[str], Optional[str]]:
    try:
        regras = get_faq_regras()
        msg_normalizada = normalizar_texto(mensagem)

        melhor_regra_obj = None
        melhor_score = 0
        melhor_regra = None
        melhor_intencao = None
        melhor_prioridade = None

        for regra in regras:
            prioridade = regra.get("prioridade")
            score = calcular_score_regra(msg_normalizada, regra)

            if score > 0:
                if (
                    melhor_regra_obj is None
                    or score > melhor_score
                    or (
                        score == melhor_score
                        and melhor_prioridade is not None
                        and prioridade < melhor_prioridade
                    )
                ):
                    melhor_regra_obj = regra
                    melhor_score = score
                    melhor_regra = regra.get("nome_regra")
                    melhor_intencao = regra.get("nome_intencao")
                    melhor_prioridade = prioridade

        if melhor_regra_obj:
            resposta = (melhor_regra_obj.get("resposta") or "").replace("\\n", "\n")
            melhor_regra_obj["resposta"] = resposta
            print(
                f"REGRA_ENCONTRADA: {melhor_regra} | "
                f"INTENCAO: {melhor_intencao} | "
                f"SCORE: {melhor_score}"
            )
            return melhor_regra_obj, melhor_regra, melhor_intencao

        print("REGRA_ENCONTRADA: nenhuma")
        return None, None, None

    except Exception as e:
        print(f"Erro em buscar_regra: {e}")
        return None, None, None


# =========================================================
# HUMANIZAÇÃO / PERSUASÃO LEVE
# =========================================================
def precisa_continuacao(
    nome_regra: Optional[str],
    nome_intencao: Optional[str],
    resposta_final: str
) -> bool:
    if not ENABLE_CONTINUATION_HINT:
        return False

    regra = normalizar_texto(nome_regra or "")
    intencao = normalizar_texto(nome_intencao or "")
    resposta_norm = normalizar_texto(resposta_final)

    bloqueadas = {
        "horario",
        "endereco",
        "preco",
        "pagamento",
        "saudacao",
        "identidade"
    }

    if regra in bloqueadas or intencao in bloqueadas:
        return False

    if "se quiser" in resposta_norm:
        return False

    return True


def adicionar_continuacao(
    resposta: str,
    nome_regra: Optional[str],
    nome_intencao: Optional[str]
) -> str:
    if not precisa_continuacao(nome_regra, nome_intencao, resposta):
        return resposta

    chave = normalizar_texto(nome_regra or nome_intencao or "")

    sugestoes = {
        "edredom": "Se quiser, posso te explicar o que dá para lavar tranquilamente aqui 😊",
        "secagem": "Se quiser, eu também posso te explicar rapidinho como funciona a secagem 😊",
        "lavagem": "Se quiser, eu posso te explicar rapidinho como funciona a lavagem 😊",
        "como_funciona": "Se quiser, eu posso te explicar o passo a passo rapidinho 😊",
        "capacidade_peca": "Se quiser, me fala a peça que você quer lavar que eu te ajudo a ver se vai tranquilo 👌",
    }

    complemento = sugestoes.get(
        chave,
        "Se quiser, eu posso te explicar rapidinho como funciona 😊"
    )

    return f"{resposta}\n\n{complemento}"


def adicionar_incentivo_cliente_indeciso(
    resposta_final: str,
    contexto: Optional[Dict[str, Any]],
    nome_intencao: Optional[str],
) -> str:
    if not contexto:
        return resposta_final

    total_interacoes = contexto.get("total_interacoes") or 0
    ultima_intencao = normalizar_texto(contexto.get("ultima_intencao") or "")
    intencao_atual = normalizar_texto(nome_intencao or "")
    resposta_norm = normalizar_texto(resposta_final)
    ultima_resposta_tipo = normalizar_texto(contexto.get("ultima_resposta_tipo") or "")

    if "pode vir sem medo" in resposta_norm or "rapidinho voce ja pega o jeito" in resposta_norm:
        return resposta_final

    if ultima_resposta_tipo in {"negativa", "negativa_capacidade", "ia"}:
        return resposta_final

    intencoes_permitidas = {"preco", "como_funciona", "pagamento"}
    intencoes_interesse = {"preco", "como_funciona"}

    if intencao_atual not in intencoes_permitidas:
        return resposta_final

    if total_interacoes >= 3 and ultima_intencao in intencoes_interesse:
        return (
            f"{resposta_final}\n\n"
            "Se quiser, pode vir sem medo 😊 é bem simples de usar e rapidinho você já pega o jeito."
        )

    return resposta_final


def humanizar_resposta(
    resposta_base: str,
    nome_regra: Optional[str],
    nome_intencao: Optional[str]
) -> str:
    if not client:
        return resposta_base

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": """
Você é um atendente virtual da LavPop no WhatsApp.

Sua tarefa é reescrever uma resposta já validada pela operação.

Regras obrigatórias:
- escreva de forma natural, simpática, curta e fluida
- use linguagem de WhatsApp
- pode usar emoji leve
- NÃO invente nenhuma informação nova
- NÃO mude o significado da resposta
- NÃO altere números, preços, horários, endereços, percentuais, prazos ou regras
- NÃO troque valores
- apenas melhore a forma de falar, sem mudar o conteúdo factual
- evite repetir exatamente a mesma estrutura do texto original
- retorne apenas o texto final
                    """.strip(),
                },
                {
                    "role": "user",
                    "content": (
                        f"Nome da regra: {nome_regra or 'nao_informada'}\n"
                        f"Nome da intenção: {nome_intencao or 'nao_informada'}\n\n"
                        f"Reescreva esta resposta sem alterar o conteúdo:\n{resposta_base}"
                    ),
                },
            ],
        )

        conteudo = response.choices[0].message.content
        if conteudo and conteudo.strip():
            return conteudo.strip()

    except Exception as e:
        print(f"Erro ao humanizar resposta: {e}")

    return resposta_base


def montar_resposta_banco(
    regra_obj: Dict[str, Any],
    nome_regra: Optional[str],
    nome_intencao: Optional[str],
    contexto: Optional[Dict[str, Any]]
) -> str:
    resposta_base = (regra_obj.get("resposta") or "").strip()
    humanizar = bool(regra_obj.get("humanizar", True))

    if not resposta_base:
        return "No momento, não encontrei essa informação confirmada na base da unidade."

    if humanizar:
        resposta_final = humanizar_resposta(
            resposta_base=resposta_base,
            nome_regra=nome_regra,
            nome_intencao=nome_intencao,
        )
    else:
        resposta_final = resposta_base

    resposta_final = ajustar_resposta_por_intencao(
        resposta_final=resposta_final,
        mensagem=regra_obj.get("_mensagem_original", ""),
        nome_intencao=nome_intencao,
        contexto=contexto,
    )

    resposta_final = adicionar_continuacao(
        resposta=resposta_final,
        nome_regra=nome_regra,
        nome_intencao=nome_intencao,
    )

    resposta_final = adicionar_incentivo_cliente_indeciso(
        resposta_final=resposta_final,
        contexto=contexto,
        nome_intencao=nome_intencao,
    )

    return resposta_final


# =========================================================
# AJUSTES POR INTENÇÃO / CONTEXTO
# =========================================================
def ajustar_resposta_por_intencao(
    resposta_final: str,
    mensagem: str,
    nome_intencao: Optional[str],
    contexto: Optional[Dict[str, Any]]
) -> str:
    msg = normalizar_texto(mensagem)
    intencao = normalizar_texto(nome_intencao or "")

    if intencao == "horario":
        if "hoje" in msg and "23h" in resposta_final and not resposta_final.lower().startswith("hoje"):
            return f"Hoje ficamos abertos até as 23h 😊\n\n{resposta_final}"

    if intencao == "capacidade_peca" and contexto:
        ultima_intencao = normalizar_texto(contexto.get("ultima_intencao") or "")
        ultima_resposta_tipo = normalizar_texto(contexto.get("ultima_resposta_tipo") or "")

        if ultima_intencao == "capacidade_peca" and ultima_resposta_tipo == "negativa_capacidade":
            if "o que da pra lavar" in msg or "o que posso lavar" in msg:
                return (
                    "Roupas do dia a dia, toalhas e peças menores costumam ir tranquilo 😊 "
                    "Peças muito grandes ou volumosas já podem não caber bem nas máquinas."
                )

    return resposta_final


# =========================================================
# FALLBACK IA
# =========================================================
def mensagem_tema_critico(msg_normalizada: str) -> bool:
    temas_criticos = [
        "preco", "valor", "custa", "pagamento", "pagar",
        "horario", "horas", "endereco", "localizacao", "onde fica",
        "tempo", "demora", "edredom", "capacidade", "kg", "quilo",
        "quilos", "cobertor", "coberta", "roupa de cama", "o que lavar",
        "o que pode lavar", "tipo de roupa", "pode lavar"
    ]
    return any(tema in msg_normalizada for tema in temas_criticos)


def gerar_resposta_ia(mensagem: str, contexto: Optional[Dict[str, Any]], nome_contato: str) -> str:
    msg = normalizar_texto(mensagem)

    if mensagem_tema_critico(msg):
        ultima_intencao = normalizar_texto((contexto or {}).get("ultima_intencao") or "")
        ultima_resposta_tipo = normalizar_texto((contexto or {}).get("ultima_resposta_tipo") or "")

        if ultima_intencao == "capacidade_peca" and ultima_resposta_tipo == "negativa_capacidade":
            return (
                "Depende do tamanho da peça 😊 "
                "Se quiser, me fala exatamente o que você quer lavar que eu te ajudo a ver se vai tranquilo."
            )

        return (
            "No momento, não encontrei essa informação confirmada na base da unidade. "
            "Se quiser, me fala mais detalhes que eu tento te orientar da forma mais segura 😊"
        )

    if eh_saudacao_pura(mensagem):
        return saudacao_contextual(contexto)

    if not client:
        return (
            "No momento, não tenho essa informação confirmada. "
            "Posso te ajudar com informações gerais sobre como funciona a unidade 😊"
        )

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": """
Você é um atendente virtual da LavPop.

Seu jeito de responder deve ser:
- natural
- simpático
- curto
- com linguagem de WhatsApp
- sem parecer robô

Estilo de comunicação:
- pode usar expressões como: "Opa!", "Claro 😊", "Boa!"
- respostas leves e diretas
- evite frases formais ou engessadas
- quando a pergunta for ampla ou ambígua, prefira conduzir a conversa em vez de afirmar demais

Regras IMPORTANTES:
- nunca invente informações
- nunca confirme preço, horário, endereço, capacidade ou regras da unidade sem base confirmada
- se não tiver certeza, diga que não encontrou essa informação confirmada na base
- não crie detalhes que não foram informados

Responda sempre em português do Brasil.
                    """.strip(),
                },
                {
                    "role": "user",
                    "content": (
                        f"Nome do contato: {nome_contato or 'nao_informado'}\n"
                        f"Ultima intencao do contexto: {(contexto or {}).get('ultima_intencao') or 'nao_informada'}\n"
                        f"Ultimo tipo de resposta: {(contexto or {}).get('ultima_resposta_tipo') or 'nao_informado'}\n\n"
                        f"Mensagem do cliente: {mensagem}"
                    )
                },
            ],
        )

        conteudo = response.choices[0].message.content
        if conteudo and conteudo.strip():
            return conteudo.strip()

    except Exception as e:
        print(f"Erro OpenAI em gerar_resposta_ia: {e}")

    return (
        "No momento, não tenho essa informação confirmada. "
        "Posso te ajudar com informações gerais sobre como funciona a unidade 😊"
    )


# =========================================================
# LOG
# =========================================================
def deve_salvar_log(mensagem: str) -> bool:
    if not ENABLE_DB_LOG:
        return False

    if not LOG_IGNORE_GREETINGS:
        return True

    return not eh_saudacao_pura(mensagem)


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

        cursor.execute(
            """
            INSERT INTO chatbot.log_conversas (
                telefone,
                nome_contato,
                mensagem_cliente,
                resposta_bot,
                origem_resposta,
                regra_nome
            )
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                telefone,
                nome_contato,
                mensagem_cliente,
                resposta_bot,
                origem_resposta,
                regra_nome,
            ),
        )

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


# =========================================================
# ORQUESTRAÇÃO
# =========================================================
def gerar_resposta(
    mensagem: str,
    contexto: Optional[Dict[str, Any]] = None,
    nome_contato: str = "",
) -> Tuple[str, str, Optional[str], Optional[str]]:
    regra_obj, nome_regra, nome_intencao = buscar_regra(mensagem)

    if regra_obj:
        print("RESPOSTA_ORIGEM: BANCO")
        regra_obj["_mensagem_original"] = mensagem
        resposta_final = montar_resposta_banco(
            regra_obj=regra_obj,
            nome_regra=nome_regra,
            nome_intencao=nome_intencao,
            contexto=contexto,
        )
        print(f"RESPOSTA_FINAL: {resposta_final}")
        return resposta_final, "banco", nome_regra, nome_intencao

    print("RESPOSTA_ORIGEM: IA")
    resposta_ia = gerar_resposta_ia(
        mensagem=mensagem,
        contexto=contexto,
        nome_contato=nome_contato,
    )
    print(f"RESPOSTA_FINAL: {resposta_ia}")
    return resposta_ia, "ia", None, None