#Acesso ao PostgreSQL (Supabase) por conexão direta
import os
import threading  # Controla execuções simultâneas; usado no cadeado do pool
from contextlib import contextmanager # Permite usar a conexão com 'with', que garante commit/rollback automático

import pandas as pd
import psycopg2 #Driver do PostgreSQL
from dotenv import load_dotenv
from streamlit import cursor
from .config import RAIZ
from psycopg2.extras import Json, execute_values  # Json: dict -> jsonb | execute_values: INSERT em lote
from psycopg2.pool import ThreadedConnectionPool  # Pool de conexões reaproveitadas, seguro entre threads

#Carrega dados da env
load_dotenv(RAIZ / '.env')

_pool: ThreadedConnectionPool | None = None
_trava = threading.Lock() # Impede que duas threads criem dois pools ao mesmo tempo

#Cria o pool na primeira chamada e o reaproveita depois
def _obter_pool() -> ThreadedConnectionPool:
    global _pool
    if _pool is None:
        with _trava:
            if _pool is None:
                url = os.environ.get('DATABASE_URL')
                if not url:
                    raise RuntimeError(
                        'DATABASE_URL não encontrada. Confira o arquivo .env na raiz.'
                    )
                #Define minimo e maxico de conexões no pool (para o Supabase)
                _pool = ThreadedConnectionPool(minconn=1, maxconn=5, dsn=url)
    return _pool


@contextmanager #Decorator - permite usar a função com 'with', que garante commit/rollback automático
def conexao():
    pool = _obter_pool()
    conn = None

    # Até 3 tentativas: descarta conexões que morreram no lado do servidor
    for _ in range(3):
        #Tira uma conexão do pool. Se não houver, espera até que outra thread devolva.
        candidata = pool.getconn()
        try:
            with candidata.cursor() as cursor: # Cursor envia os comandos SQL e lê o resultado
                cursor.execute('select 1')
            candidata.commit()
            conn = candidata
            break
        except psycopg2.Error:
            pool.putconn(candidata, close=True)   # close=True: não devolve ao pool

    if conn is None:
        raise RuntimeError('Não foi possível obter conexão viva com o banco.')

    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)

#Excecuta consultas sql
def consultar(
    sql: str, 
    params: tuple | dict | None = None  # Valores dos %s, enviados separados do SQL — bloqueia injeção
) -> pd.DataFrame:
    with conexao() as conn:
        with conn.cursor() as cursor:
            cursor.execute(sql, params)
            if cursor.description is None: # não era SELECT por não conter colunas de resposta
                return pd.DataFrame() #retorna um dataframe vazio
            colunas = [descricao[0] for descricao in cursor.description] #retorna os nomes das colunas do resultado
            return pd.DataFrame(cursor.fetchall(), columns=colunas) #Monta o DataFrame com os dados e os nomes das colunas

#Primeira coluna da primeira linha. Para contagens de um número só.
def escalar(sql: str, params: tuple | dict | None = None):
    with conexao() as conn:
        with conn.cursor() as cursor:
            cursor.execute(sql, params)
            # Traz só a primeira linha; None se a consulta não devolveu nada
            resultado = cursor.fetchone()
            if resultado is None:
                return None
            return resultado[0]

#INSERT/UPDATE/DELETE de uma linha só. Devolve quantas linhas mudaram
def executar(sql: str, params: tuple | dict | None = None) -> int:
    with conexao() as conn:
        with conn.cursor() as cursor:
            cursor.execute(sql, params)
            return cursor.rowcount

#Insert em massa numa única ida ao banco; com retornar=True devolve o Returning
def executar_lote(sql: str, linhas: list[tuple], retornar: bool = False):
    if not linhas:
        return [] if retornar else 0
    with conexao() as conn:
        with conn.cursor() as cursor:
            resultado = execute_values(cursor, sql, linhas, page_size=500,
                                       fetch=retornar)
            # rowcount reflete só a última página; use retornar=True quando a contagem importa
            return resultado if retornar else cursor.rowcount
