# Partes 1 a 5 do notebook: importação, agrupamento, regras de inclusão e dataset
import hashlib

import pandas as pd

import db
from config import (CHAMADOS_INTERNOS, DIAS_CENSURA, MESCLADOS, MIN_OCORRENCIAS,
                    PADRAO_CHAMADO, PISO, SISTEMAS_FORA, TAG_ORCAMENTO, TAGS_FORA,
                    TIPO_PROJETO, TIPO_TAREFA)

FORMATO_DATA = '%d/%m/%Y %H:%M:%S'  # formato das datas no CSV do Clockify (dia/mês/ano, padrão BR)
COLUNAS = ['hash_linha', 'numero_chamado', 'sistema', 'tag', 'usuario', 'descricao',
           'inicio', 'fim', 'duracao_horas'] # Colunas da tabela sessoes, na ordem usada no insert


def _hash(s):
    # Mesma composição usada desde a primeira importação: reimportar não duplica
    # Junta os dados que identificam a sessão num texto só, separados por "|"
    partes = [
        str(s['usuario']),
        str(s['descricao']),
        s['inicio'].isoformat(),         # data/hora no formato 2025-04-03T14:30:00
        s['fim'].isoformat(),
        f"{s['duracao_horas']:.4f}",     # sempre 4 casas decimais (1.5 -> "1.5000")
    ]
    bruto = '|'.join(partes)
    # Transforma o texto num código único de 64 caracteres (SHA-256)
    return hashlib.sha256(bruto.encode('utf-8')).hexdigest()

def importar(arquivo, nome):
    """1.4 e 1.5: remove sessões fora de escopo e sem chamado, grava as novas."""
    # Lê o CSV do Clockify e começa o resumo da importação
    df = pd.read_csv(arquivo)
    resumo = {'lidas': len(df)}
    # Regra 1: remove sessões de suporte, reunião e sem etiqueta
    fora = df['Tags'].isna() | df['Tags'].isin(TAGS_FORA)
    resumo['fora_escopo'] = int(fora.sum())
    df = df[~fora]
    # Regra 2: remove sessões sem número de chamado na descrição
    chamado = df['Description'].str.extract(PADRAO_CHAMADO, expand=False)
    resumo['sem_chamado'] = int(chamado.isna().sum())
    tem_chamado = chamado.notna()
    df = df[tem_chamado]
    chamado = chamado[tem_chamado]
    # Monta a tabela no formato do banco (colunas em português, datas e horas convertidas)
    s = pd.DataFrame({
        'numero_chamado': chamado,
        'sistema': df['Project'].str.strip(),
        'tag': df['Tags'].str.strip(),
        'usuario': df['User'].str.strip(),
        'descricao': df['Description'],
        'inicio': pd.to_datetime(df['Start Date'] + ' ' + df['Start Time'], format=FORMATO_DATA),
        'fim': pd.to_datetime(df['End Date'] + ' ' + df['End Time'], format=FORMATO_DATA),
        'duracao_horas': pd.to_numeric(df['Duration (decimal)'], errors='coerce'),
    })
    # Descarta sessões sem duração (zero ou valor inválido)
    s = s[s['duracao_horas'] > 0]
    # Gera a "impressão digital" de cada sessão e remove repetidas dentro do próprio CSV
    hashes = []
    for _, linha in s.iterrows():
        hashes.append(_hash(linha))
    s['hash_linha'] = hashes
    s = s.drop_duplicates('hash_linha')
    # Prepara as linhas para o banco: ordem de COLUNAS e valores vazios viram None (NULL)
    s = s[COLUNAS].astype(object)  # ordem do insert + tipos Python comuns (permite None/NULL na linha seguinte)
    s = s.where(s.notna(), None) # troca NaN (vazio do pandas) por None, que vira NULL no banco
    linhas = list(s.itertuples(index=False, name=None))  # tabela -> lista de tuplas, formato do execute_values
    # Grava as sessões; as que já existem no banco são ignoradas e não voltam no RETURNING
    if linhas:
        novas = db.inserir(f"""insert into sessoes ({', '.join(COLUNAS)}) values %s
                               on conflict (hash_linha) do nothing returning id""",
                           linhas)
    else:
        novas = []
    resumo['novas'] = len(novas)
    resumo['duplicadas'] = len(s) - len(novas)
    # Registra o resumo desta importação no histórico
    db.executar("""insert into importacoes (arquivo, linhas_lidas, linhas_fora_escopo,
                       linhas_sem_chamado, linhas_novas, linhas_duplicadas)
                   values (%s, %s, %s, %s, %s, %s)""",
                (nome, resumo['lidas'], resumo['fora_escopo'], resumo['sem_chamado'],
                 resumo['novas'], resumo['duplicadas']))
    return resumo


def sessoes():
    return db.consultar("""select numero_chamado, sistema, tag, inicio, fim, duracao_horas
                             from sessoes""")


def agrupar(s):
    """1.9 e 2.4: consolida os mesclados e agrupa as sessões por chamado.
    Sistema e tag vêm da sessão mais longa."""
    # Troca o chamado "filho" pelo "pai" nos chamados mesclados no Movidesk
    s = s.copy()
    s['numero_chamado'] = s['numero_chamado'].replace(MESCLADOS)
    # Ordena da sessão mais longa para a mais curta (o 'first' abaixo pega a mais longa)
    s = s.sort_values('duracao_horas', ascending=False)
    # Junta todas as sessões de cada chamado numa linha só
    grupos = s.groupby('numero_chamado')
    d = grupos.agg(
        sistema=('sistema', 'first'),           # sistema da sessão mais longa
        tag=('tag', 'first'),                   # tag da sessão mais longa
        data_fim=('fim', 'max'),                # quando terminou a última sessão
        esforco=('duracao_horas', 'sum'),       # total de horas do chamado
        sessoes=('duracao_horas', 'size'),      # quantas sessões o chamado teve
    )
    # Volta o numero_chamado a ser uma coluna normal (o groupby o transforma em índice)
    d = d.reset_index()
    d['esforco'] = d['esforco'].round(2)
    return d

def aplicar_regras(d):
    """Parte 4: aplica as regras em sequência e devolve (demandas, funil)."""
    # Data da última sessão registrada, fixada antes das regras (usada na regra de censura)
    fim_coleta = d['data_fim'].max()
    # Lista que guarda quantas demandas cada regra removeu
    funil = []
    # Mantém só as demandas marcadas em "manter" e anota o resultado da regra no funil
    def filtrar(d, manter, regra):
        antes = len(d)
        d = d[manter]
        funil.append({'regra': regra, 'antes': antes,
                      'removidas': antes - len(d), 'depois': len(d)})
        return d
    # Regra 1: tag Orçamento é o trabalho de orçar, não a demanda em si
    d = filtrar(d, d['tag'] != TAG_ORCAMENTO, 'Tag Orçamento (meta-trabalho)')
    # Regra 2: sistemas fora do escopo (produto interno e sistema registrado errado)
    d = filtrar(d, ~d['sistema'].isin(SISTEMAS_FORA), 'Produto interno e sistema incorreto')
    # Regra 3: demandas pequenas demais
    d = filtrar(d, d['esforco'] >= PISO, f'Esforço inferior a {PISO} h')
    # Regra 4: demandas que terminaram perto do fim da coleta podem não ter acabado
    limite_censura = fim_coleta - pd.Timedelta(days=DIAS_CENSURA)
    d = filtrar(d, d['data_fim'] <= limite_censura,
                f'Possivelmente em andamento (últimos {DIAS_CENSURA} dias)')
    # Regra 5: projetos internos da empresa
    d = filtrar(d, ~d['numero_chamado'].isin(CHAMADOS_INTERNOS), 'Projeto interno da empresa')
    # Regras 6 e 7: tipos de tarefa e sistemas raros demais para o modelo aprender
    for coluna, nome in [('tag', 'Tipo de tarefa'), ('sistema', 'Sistema')]:
        contagem = d[coluna].value_counts()
        raros = contagem[contagem < MIN_OCORRENCIAS].index
        d = filtrar(d, ~d[coluna].isin(raros),
                    f'{nome} com menos de {MIN_OCORRENCIAS} ocorrências')
    # Regra 8: valor novo no Clockify sem código no mapa fica fora até entrar no config
    mapeado = d['sistema'].isin(TIPO_PROJETO) & d['tag'].isin(TIPO_TAREFA)
    if not mapeado.all():
        d = filtrar(d, mapeado, 'Sistema ou tag sem código no mapa')
    return d, pd.DataFrame(funil)



def dataset(d):
    """Parte 5: códigos numéricos + orçamentos concluídos (realimentação)."""
    historico = pd.DataFrame({
        'tipo_projeto': d['sistema'].map(TIPO_PROJETO),
        'tipo_tarefa': d['tag'].map(TIPO_TAREFA),
        'horas': d['esforco'],
        'origem': 'clockify',
    })
    # Orçamento cujo chamado já veio pelo Clockify não conta duas vezes
    orcamentos = db.consultar("""select tipo_projeto, tipo_tarefa, horas_reais as horas
                                   from orcamentos
                                  where status = 'concluido' and horas_reais >= %s
                                    and coalesce(numero_chamado, '') <> all(%s)""",
                              (PISO, list(d['numero_chamado'])))
    orcamentos['origem'] = 'orcamento'
    return pd.concat([historico, orcamentos], ignore_index=True)


def base():
    """Parte 1 a 4 de uma vez: (demandas agrupadas, demandas incluídas, funil)."""
    d = agrupar(sessoes())
    incluidas, funil = aplicar_regras(d)
    return d, incluidas, funil
