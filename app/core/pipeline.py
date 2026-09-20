import pandas as pd

from . import db
from .config import (DIAS_CENSURA, MIN_OCORRENCIAS, PISO_HORAS,
                     SISTEMAS_INTERNOS, TAG_META_TRABALHO)

#Agrupa uma linha por chamado
def agrupar() -> pd.DataFrame:
    return db.consultar("""
        with atributos as (
            select distinct on (numero_chamado)
                   numero_chamado, cliente, sistema, tag, billable
              from sessoes
             order by numero_chamado, duracao_horas desc
        ),
        totais as (
            select numero_chamado,
                   min(inicio)        as data_inicio,
                   max(fim)           as data_fim,
                   sum(duracao_horas) as esforco_horas,
                   count(*)           as qtd_sessoes
              from sessoes
             group by numero_chamado
        )
        select a.numero_chamado, a.cliente, a.sistema, a.tag, a.billable,
               t.data_inicio, t.data_fim,
               round(t.esforco_horas::numeric, 2)::float8 as esforco_horas,
               t.qtd_sessoes
          from atributos a
          join totais t using (numero_chamado)
         order by a.numero_chamado
    """)

def aplicar_regras(demandas: pd.DataFrame,
                   excluidas_manuais: set[str] | None = None
                   ) -> tuple[pd.DataFrame, pd.DataFrame]:
    d = demandas.copy()
    d['incluida'] = True
    d['motivo_exclusao'] = None
    funil = []

    def excluir(condicao: pd.Series, motivo: str) -> None:
        antes = int(d['incluida'].sum())
        alvo = d['incluida'] & condicao.fillna(False)
        d.loc[alvo, ['incluida', 'motivo_exclusao']] = [False, motivo]
        funil.append({
            'regra': motivo,
            'antes': antes,
            'removidas': int(alvo.sum()),
            'depois': int(d['incluida'].sum()),
        })

    # 1 — Meta-trabalho (célula 75). Orçar não é executar; incluir isso
    # ensinaria o modelo a prever o custo de estimar, não o de fazer.
    excluir(d['tag'].eq(TAG_META_TRABALHO),
            'Meta-trabalho: tag Orçamento')

    # 2 — Produto interno (célula 77). Não passa por chamado formal nem
    # é orçado a cliente.
    excluir(d['sistema'].isin(SISTEMAS_INTERNOS),
            'Produto interno da empresa')

    # 3 — Piso mínimo (célula 79). Demanda de 5 minutos não chega a ser
    # orçada, então não é exemplo do problema que o sistema resolve.
    excluir(d['esforco_horas'] < PISO_HORAS,
            f'Esforço abaixo de {PISO_HORAS} h')

    # 4 — Censura temporal (célula 81). As últimas demandas podem estar
    # inacabadas: o esforço registrado seria um piso, não o total.
    if not d.empty:
        corte = d['data_fim'].max() - pd.Timedelta(days=DIAS_CENSURA)
        excluir(d['data_fim'] > corte,
                f'Possivelmente em andamento (últimos {DIAS_CENSURA} dias)')

    # 5 — Decisão humana (substitui o 'Chamado_142' fixo da célula 83)
    if excluidas_manuais:
        excluir(d['numero_chamado'].isin(excluidas_manuais),
                'Excluída manualmente')

    # 6 — Categorias raras (célula 85). Com menos de 5 casos o modelo
    # decora em vez de generalizar. Conta só entre as sobreviventes.
    for coluna in ['tag', 'sistema']:
        contagem = d.loc[d['incluida'], coluna].value_counts()
        raras = contagem[contagem < MIN_OCORRENCIAS].index
        excluir(d[coluna].isin(raras),
                f'Categoria rara em {coluna} (menos de {MIN_OCORRENCIAS} casos)')

    # 7 — Sem código de mapeamento. No notebook isto é um assert que
    # derruba a execução (célula 98); numa aplicação que roda toda semana,
    # derrubar não é opção: a demanda fica de fora e aparece na tela.
    mapeados_projeto = set(db.consultar('select nome_clockify from tipos_projeto')
                           ['nome_clockify'])
    mapeados_tarefa = set(db.consultar('select nome_clockify from tipos_tarefa')
                          ['nome_clockify'])
    excluir(~d['sistema'].isin(mapeados_projeto) | ~d['tag'].isin(mapeados_tarefa),
            'Projeto ou tarefa sem código de mapeamento')

    return d, pd.DataFrame(funil)


# =====================================================================
# Gravação
# =====================================================================

COLUNAS_DEMANDA = ['numero_chamado', 'cliente', 'sistema', 'tag', 'billable',
                   'data_inicio', 'data_fim', 'esforco_horas', 'qtd_sessoes',
                   'incluida', 'motivo_exclusao']


def recalcular() -> pd.DataFrame:
    """Reconstrói a tabela `demandas` a partir das sessões. Devolve o funil.

    Chamado depois de cada importação e pelo botão da tela.
    """
    manuais = set(
        db.consultar('select numero_chamado from demandas where excluida_manual')
        ['numero_chamado']
    )

    demandas, funil = aplicar_regras(agrupar(), manuais)
    if demandas.empty:
        return funil

    linhas = list(
        demandas[COLUNAS_DEMANDA]
        .astype(object)
        .where(pd.notna(demandas[COLUNAS_DEMANDA]), None)
        .itertuples(index=False, name=None)
    )

    # O update lista as colunas uma a uma DE PROPÓSITO: 'excluida_manual'
    # fica de fora e sobrevive ao recálculo. Um 'do update set' genérico
    # apagaria a decisão que você tomou na tela de histórico.
    db.executar_lote(
        f"""insert into demandas ({', '.join(COLUNAS_DEMANDA)})
            values %s
            on conflict (numero_chamado) do update set
                cliente         = excluded.cliente,
                sistema         = excluded.sistema,
                tag             = excluded.tag,
                billable        = excluded.billable,
                data_inicio     = excluded.data_inicio,
                data_fim        = excluded.data_fim,
                esforco_horas   = excluded.esforco_horas,
                qtd_sessoes     = excluded.qtd_sessoes,
                incluida        = excluded.incluida,
                motivo_exclusao = excluded.motivo_exclusao,
                recalculado_em  = now()""",
        linhas,
    )

    # Demanda cujas sessões sumiram da base não deve sobreviver ao recálculo.
    db.executar("""
        delete from demandas
         where numero_chamado not in (select distinct numero_chamado from sessoes)
    """)

    return funil


# =====================================================================
# Dataset de treino — Parte 5 do notebook
# =====================================================================

def montar_dataset() -> pd.DataFrame:
    """Demandas prontas para o modelo: tipo_projeto, tipo_tarefa, horas.

    A codificação das células 96 a 100 vira um JOIN com as tabelas de
    domínio — mesma lógica, mas editável sem mexer em código.

    Aos históricos do Clockify somam-se os orçamentos já concluídos: é o
    ciclo de realimentação, o sistema aprendendo com o próprio uso.
    """
    return db.consultar("""
        select d.numero_chamado         as referencia,
               tp.codigo                as tipo_projeto,
               tt.codigo                as tipo_tarefa,
               d.esforco_horas          as horas_executadas,
               'clockify'               as origem
          from demandas d
          join tipos_projeto tp on tp.nome_clockify = d.sistema
          join tipos_tarefa  tt on tt.nome_clockify = d.tag
         where d.incluida and not d.excluida_manual

        union all

        select o.id::text, o.tipo_projeto, o.tipo_tarefa, o.horas_reais, 'orcamento'
          from orcamentos o
         where o.status = 'concluido'
           and o.horas_reais >= %s
           -- Se o chamado do orçamento já entrou pelo Clockify, ele já está
           -- contado acima. Sem esta guarda, a demanda pesaria em dobro.
           and (o.numero_chamado is null
                or o.numero_chamado not in (
                    select numero_chamado from demandas
                     where incluida and not excluida_manual))
    """, (PISO_HORAS,))
