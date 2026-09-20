"""Aplica o schema no banco. Idempotente: pode rodar quantas vezes precisar."""
import os
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

load_dotenv()

sql = (Path(__file__).parent / 'schema.sql').read_text(encoding='utf-8')

with psycopg2.connect(os.environ['DATABASE_URL']) as conexao:
    with conexao.cursor() as cursor:
        cursor.execute(sql)
        cursor.execute("""
            select table_name
              from information_schema.tables
             where table_schema = 'public'
             order by table_name
        """)
        tabelas = [linha[0] for linha in cursor.fetchall()]

print(f'{len(tabelas)} tabelas: {", ".join(tabelas)}')
