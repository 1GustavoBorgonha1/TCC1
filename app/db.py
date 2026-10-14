# Acesso ao PostgreSQL (Supabase)
import os
from contextlib import closing # fecha a conexão com o banco ao sair do "with", mesmo se der erro

import pandas as pd
import psycopg2 # conecta o Python ao PostgreSQL (Supabase) e executa os comandos SQL
from dotenv import load_dotenv
from psycopg2.extras import Json, execute_values  # Json: dict -> jsonb; execute_values: insert de várias linhas num só comando

from config import RAIZ

load_dotenv(RAIZ / '.env')

# Abre conexão com o Supabase usando o endereço do .env
def conectar():
    return psycopg2.connect(os.environ['DATABASE_URL'])

# Roda um SELECT e devolve o resultado como tabela pandas
def consultar(sql, params=None):
    # Abre a conexão com o banco e fecha ao sair
    with closing(conectar()) as conexao:
        # Abre um cursor, que executa os comandos SQL
        with conexao.cursor() as cursor:
            # Executa a consulta (ex.: SELECT * FROM demandas WHERE ...)
            cursor.execute(sql, params)
            # Pega o nome de cada coluna do resultado
            colunas = []
            for descricao in cursor.description:
                colunas.append(descricao[0])  # posição 0 = nome da coluna
            # Pega todas as linhas do resultado
            linhas = cursor.fetchall()
            # Monta uma tabela do pandas com as linhas e os nomes das colunas
            return pd.DataFrame(linhas, columns=colunas)

# Roda um INSERT, UPDATE ou DELETE e salva no banco
def executar(sql, params=None):
    # Abre a conexão com o banco e fecha ao sair
    with closing(conectar()) as conexao:
        # Salva as alterações (commit) se tudo der certo; desfaz (rollback) se der erro
        with conexao:
            # Abre um cursor, que executa os comandos SQL
            with conexao.cursor() as cursor:
                # Executa o comando (ex.: INSERT, UPDATE, DELETE)
                cursor.execute(sql, params)

# Insere várias linhas de uma vez e devolve o RETURNING
def inserir(sql, linhas):
    # Abre a conexão com o banco e fecha ao sair
    with closing(conectar()) as conexao:
        # Salva as alterações (commit) se tudo der certo; desfaz (rollback) se der erro
        with conexao:
            # Abre um cursor, que executa os comandos SQL
            with conexao.cursor() as cursor:
                # Insere todas as linhas num só comando e devolve o que o RETURNING trouxer
                return execute_values(cursor, sql, linhas, fetch=True)