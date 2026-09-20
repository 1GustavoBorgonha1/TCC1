import hashlib #transforma uma string em hash SHA-256

import pandas as pd

from . import db, mascara
from .config import (COLUNAS_CLOCKIFY, FORMATO_DATA_CLOCKIFY, PADRAO_CHAMADO,
                     TAGS_FORA_ESCOPO, TEM_CHAMADO)


def _hash_sessao(linha: pd.Series) -> str:
    bruto = '|'.join([
        str(linha['usuario']),
        str(linha['descricao']),
        linha['inicio'].isoformat(),
        linha['fim'].isoformat(),
        f"{linha['duracao_horas']:.4f}",
    ])
    # utf-8 fixa os bytes dos acentos; hexdigest devolve os 64 caracteres da coluna
    return hashlib.sha256(bruto.encode('utf-8')).hexdigest()

#Lê o CSV e aplica os filtros de escopo.
def preparar(origem, nome_arquivo: str) -> tuple[pd.DataFrame, dict]:
    df = pd.read_csv(origem)

    faltando = set(COLUNAS_CLOCKIFY) - set(df.columns)
    if faltando:
        raise ValueError(
            f'O arquivo não parece um export do Clockify. '
            f'Colunas ausentes: {sorted(faltando)}'
        )

    resumo = {'arquivo': nome_arquivo, 'linhas_lidas': len(df)}

    # Regra 1 : fora do escopo de desenvolvimento
    no_escopo = df['Tags'].notna() & ~df['Tags'].isin(TAGS_FORA_ESCOPO)
    resumo['linhas_fora_escopo'] = int((~no_escopo).sum())
    df = df[no_escopo]

    #Regra 2: sem chamado formal 
    tem_chamado = df['Description'].str.contains(TEM_CHAMADO, na=False, regex=True)
    resumo['linhas_sem_chamado'] = int((~tem_chamado).sum())
    resumo['horas_sem_chamado'] = float(
        df.loc[~tem_chamado, 'Duration (decimal)'].sum()
    )
    df = df[tem_chamado].copy()

    if df.empty:
        return df, resumo

    #Normalização
    sessoes = pd.DataFrame({
        'numero_chamado': df['Description'].str.extract(PADRAO_CHAMADO, expand=False),
        'cliente':  df['Client'].astype('string').str.strip(),
        'sistema':  df['Project'].astype('string').str.strip(),
        'tag':      df['Tags'].astype('string').str.strip(),
        'billable': df['Billable'].astype('string').str.strip().str.lower().eq('yes'),
        'usuario':  df['User'].astype('string').str.strip(),
        'descricao': df['Description'].astype('string'),
        'inicio': pd.to_datetime(df['Start Date'] + ' ' + df['Start Time'],
                                 format=FORMATO_DATA_CLOCKIFY),
        'fim':    pd.to_datetime(df['End Date'] + ' ' + df['End Time'],
                                 format=FORMATO_DATA_CLOCKIFY),
        'duracao_horas': pd.to_numeric(df['Duration (decimal)'], errors='coerce'),
    })

    # Sessão com duração ilegível ou zerada não é dado, é ruído.
    sessoes = sessoes[sessoes['duracao_horas'] > 0].reset_index(drop=True)

    sessoes['hash_linha'] = sessoes.apply(_hash_sessao, axis=1)
    sessoes['arquivo_origem'] = nome_arquivo

    # Duplicata dentro do próprio arquivo: o ON CONFLICT não protege
    # contra colisão no mesmo INSERT, então resolvemos antes.
    antes = len(sessoes)
    sessoes = sessoes.drop_duplicates(subset='hash_linha').reset_index(drop=True)
    resumo['linhas_repetidas_no_arquivo'] = antes - len(sessoes)
    resumo['linhas_validas'] = len(sessoes)

    return sessoes, resumo


COLUNAS_INSERCAO = [
    'hash_linha', 'numero_chamado', 'cliente', 'sistema', 'tag', 'billable',
    'usuario', 'descricao', 'inicio', 'fim', 'duracao_horas', 'arquivo_origem',
]

#Grava as sessões e devolve quantas eram inéditas.
def gravar(sessoes: pd.DataFrame) -> int:
    if sessoes.empty:
        return 0

    linhas = list(
        sessoes[COLUNAS_INSERCAO] # fixa as colunas e a ordem do INSERT
        .astype(object) # tipo genérico: só ele aceita None
        .where(pd.notna(sessoes[COLUNAS_INSERCAO]), None) # NaN do pandas -> NULL do Postgres
        .itertuples(index=False, name=None) # cada linha vira uma tupla simples
    )


    inseridas = db.executar_lote(
        f"""insert into sessoes ({', '.join(COLUNAS_INSERCAO)})
            values %s
            on conflict (hash_linha) do nothing
            returning id""",
        linhas,
        retornar=True,
    )
    return len(inseridas)

#Fluxo completo de uma importação: ler, filtrar, gravar, registrar
def importar(origem, nome_arquivo: str) -> dict:
    sessoes, resumo = preparar(origem, nome_arquivo)

    resumo['linhas_novas'] = gravar(sessoes)
    resumo['linhas_duplicadas'] = len(sessoes) - resumo['linhas_novas']

    # Códigos de mascaramento para os valores inéditos deste lote
    if not sessoes.empty:
        resumo['mascaras_novas'] = (
            mascara.registrar_novos('cliente', sessoes['cliente'])
            + mascara.registrar_novos('sistema', sessoes['sistema'])
            + mascara.registrar_novos('chamado', sessoes['numero_chamado'])
        )

    db.executar(
        """insert into importacoes
               (arquivo, linhas_lidas, linhas_fora_escopo,
                linhas_sem_chamado, linhas_novas, linhas_duplicadas)
           values (%s, %s, %s, %s, %s, %s)""",
        (resumo['arquivo'], resumo['linhas_lidas'], resumo['linhas_fora_escopo'],
         resumo['linhas_sem_chamado'], resumo.get('linhas_novas', 0),
         resumo.get('linhas_duplicadas', 0)),
    )
    return resumo
