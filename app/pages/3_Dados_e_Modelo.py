"""Importação dos exports do Clockify, funil de demandas e treino do modelo."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
import streamlit as st


import ui
from core import db, ingestao, pipeline, treino
from core.config import COBERTURA

ui.configurar('Dados e Modelo')
anonimo = ui.barra_lateral()

st.title('Dados e Modelo')

# =====================================================================
# Importação
# =====================================================================
st.header('Importar sessões do Clockify')
st.caption(
    'Relatório detalhado exportado em CSV. Pode subir o mesmo arquivo mais de '
    'uma vez ou arquivos com períodos sobrepostos: cada sessão é identificada '
    'pelo conteúdo, então só o que é inédito entra.'
)

arquivos = st.file_uploader(
    'Exports do Clockify (CSV)', type='csv', accept_multiple_files=True,
)

if arquivos and st.button('Importar', type='primary'):
    for arquivo in arquivos:
        with st.spinner(f'Importando {arquivo.name}…'):
            try:
                resumo = ingestao.importar(arquivo, arquivo.name)
            except ValueError as erro:
                st.error(f'**{arquivo.name}** — {erro}')
                continue

        st.success(f"**{arquivo.name}** — {resumo['linhas_novas']} sessões novas")

        a, b, c, d = st.columns(4)
        a.metric('Lidas', resumo['linhas_lidas'])
        b.metric('Fora de escopo', resumo['linhas_fora_escopo'],
                 help='Tag Suporte, Reunião ou vazia')
        c.metric('Sem chamado', resumo['linhas_sem_chamado'],
                 help=f"{resumo.get('horas_sem_chamado', 0):.1f} h que não passam "
                      'pelo fluxo de orçamentação')
        d.metric('Já existiam', resumo['linhas_duplicadas'])

        with st.spinner('Recalculando demandas…'):
            pipeline.recalcular()
    st.rerun()

st.divider()

# =====================================================================
# Treino
# =====================================================================
st.header('Modelo')

ativo = db.consultar("""
    select id, criado_em, n_demandas, n_orcamentos, metricas,
           multiplicadores, combinacoes, cobertura_por_faixa
      from treinos where ativo
""")

col_esq, col_dir = st.columns([3, 1])
if ativo.empty:
    col_esq.info('Nenhum modelo treinado.')
else:
    linha = ativo.iloc[0]
    col_esq.success(
        f"Versão {linha['id']} · {linha['criado_em']:%d/%m/%Y %H:%M} · "
        f"{linha['n_demandas']} demandas + {linha['n_orcamentos']} orçamentos"
    )

if col_dir.button('Treinar modelo', type='primary', width='stretch'):
    try:
        with st.spinner('Validação cruzada e calibração… leva alguns segundos.'):
            st.session_state['resultado_treino'] = treino.executar()
    except ValueError as erro:
        st.error(str(erro))
    else:
        st.rerun()

if ativo.empty:
    st.stop()

linha = ativo.iloc[0]

# --- Comparação dos modelos ------------------------------------------
st.subheader('Desempenho na validação cruzada')
st.caption('Validação cruzada 5-fold sobre as mesmas demandas. '
           'MAE e MdMRE: menor é melhor. PRED25 e R²: maior é melhor.')


comparacao = pd.DataFrame(linha['metricas'])
st.dataframe(
    comparacao[['modelo', 'MAE', 'RMSE', 'R2', 'MMRE', 'MdMRE', 'PRED25']],
    hide_index=True, width='stretch',
)

# O achado central do TCC, verificado a cada treino em vez de assumido.
baselines = comparacao[comparacao['modelo'].str.startswith('Baseline')]
algoritmos = comparacao[~comparacao['modelo'].str.startswith('Baseline')]
melhor_base = baselines.loc[baselines['MAE'].idxmin()]
melhor_algo = algoritmos.loc[algoritmos['MAE'].idxmin()]

# Comparar duas médias e declarar vencedor ignora a dispersão. O desvio
# entre folds aqui é da ordem de 0,6 h; uma diferença de 0,02 h entre
# médias é ruído amostral, não superioridade. A margem de decisão é o
# próprio desvio observado.
margem = max(float(melhor_base['MAE_desvio']), float(melhor_algo['MAE_desvio']))
diferenca = float(melhor_base['MAE']) - float(melhor_algo['MAE'])

if diferenca > margem:
    st.success(
        f"«{melhor_algo['modelo']}» supera a melhor baseline com folga: "
        f"MAE {melhor_algo['MAE']:.3f} contra {melhor_base['MAE']:.3f}, "
        f'diferença maior que o desvio entre folds ({margem:.3f}).'
    )
elif diferenca < -margem:
    st.warning(
        f"**A baseline vence.** «{melhor_base['modelo']}» tem MAE "
        f"{melhor_base['MAE']:.3f} contra {melhor_algo['MAE']:.3f} do melhor "
        f"algoritmo. É o resultado registrado no TCC: com os preditores "
        'disponíveis, o aprendizado de máquina não supera a regra de bolso.'
    )
else:
    st.warning(
        f"**Empate técnico.** «{melhor_algo['modelo']}» (MAE {melhor_algo['MAE']:.3f}) "
        f"e «{melhor_base['modelo']}» (MAE {melhor_base['MAE']:.3f}) diferem em "
        f'{abs(diferenca):.3f} h, menos que o desvio entre folds ({margem:.3f} h). '
        'Não há evidência de que um seja melhor que o outro. É o achado central '
        'do TCC: o que o sistema entrega não é uma previsão mais exata que a '
        'intuição, é a **calibração da incerteza** — uma faixa com cobertura aferida.'
    )


# --- O que o modelo consegue responder -------------------------------
col_a, col_b = st.columns(2)

with col_a:
    st.subheader('Previsões possíveis')
    st.caption('Com dois preditores categóricos, uma previsão por combinação.')
    st.dataframe(pd.DataFrame(linha['combinacoes']), hide_index=True,
                 width='stretch')

with col_b:
    st.subheader('Multiplicadores da faixa')
    st.caption(
        f'Percentis {COBERTURA[0]:.0%}–{COBERTURA[1]:.0%} da razão real/previsto, '
        'medidos fora da amostra.'
    )
    st.dataframe(
        pd.DataFrame(linha['multiplicadores']).T.reset_index(names='segmento'),
        hide_index=True, width='stretch',
    )

# --- Cobertura aferida -----------------------------------------------
st.subheader('Cobertura da faixa')
cobertura = dict(linha['cobertura_por_faixa'])
geral = cobertura.pop('geral', None)

st.caption(
    f'Nominal {COBERTURA[1] - COBERTURA[0]:.0%} · '
    f'**aferida {geral:.1%}**' if geral is not None else ''
)
st.dataframe(
    pd.DataFrame(cobertura).T.reset_index(names='faixa de esforço real'),
    hide_index=True, width='stretch',
)
st.caption(
    'Faixa com cobertura muito abaixo da nominal vira ressalva automática '
    'na tela de orçamento.'
)

with st.expander('Histórico de treinos'):
    st.dataframe(
        db.consultar("""
            select id, criado_em, n_demandas, n_orcamentos, ativo
              from treinos order by id desc limit 20
        """),
        hide_index=True, width='stretch',
    )


# =====================================================================
# Demandas e funil de exclusões
# =====================================================================
st.header('Demandas')

col_esq, col_dir = st.columns([3, 1])
col_esq.caption(
    'Sessões agrupadas por chamado e submetidas às regras de inclusão do TCC. '
    'A demanda excluída continua na base com o motivo registrado.'
)
if col_dir.button('Recalcular', use_container_width=True):
    with st.spinner('Recalculando…'):
        funil = pipeline.recalcular()
    st.session_state['funil'] = funil
    st.rerun()

situacao = db.consultar("""
    select count(*)                                          as total,
           count(*) filter (where incluida
                              and not excluida_manual)        as no_treino,
           count(*) filter (where excluida_manual)            as manuais
      from demandas
""").iloc[0]

if situacao['total'] == 0:
    st.info('Nenhuma demanda calculada. Clique em Recalcular.')
    st.stop()

a, b, c = st.columns(3)
a.metric('Demandas agrupadas', situacao['total'])
b.metric('No treino', situacao['no_treino'])
c.metric('Excluídas à mão', situacao['manuais'])

if 'funil' in st.session_state and not st.session_state['funil'].empty:
    st.subheader('Funil de exclusões')
    st.caption('Cada regra opera sobre o que sobreviveu à anterior.')
    st.dataframe(st.session_state['funil'], hide_index=True,
                 use_container_width=True)

with st.expander('Demandas excluídas, por motivo'):
    st.dataframe(
        db.consultar("""
            select coalesce(motivo_exclusao, 'Excluída manualmente') as motivo,
                   count(*) as demandas,
                   round(sum(esforco_horas)::numeric, 1)::float8 as horas
              from demandas
             where not incluida or excluida_manual
             group by 1 order by demandas desc
        """),
        hide_index=True, use_container_width=True,
    )

# O dataset é o que o modelo vai ver de fato — inclusive os orçamentos
# já concluídos, realimentados pela página de histórico.
dataset = pipeline.montar_dataset()
st.caption(
    f'Dataset de treino: **{len(dataset)} demandas** '
    f"({(dataset['origem'] == 'clockify').sum()} do Clockify, "
    f"{(dataset['origem'] == 'orcamento').sum()} de orçamentos concluídos)."
)


# =====================================================================
# Estado da base
# =====================================================================
st.header('Base atual')

total = db.escalar('select count(*) from sessoes')

if not total:
    st.info('Nenhuma sessão importada ainda.')
    st.stop()

resumo_base = db.consultar("""
    select count(*)                        as sessoes,
           count(distinct numero_chamado)  as chamados,
           count(distinct cliente)         as clientes,
           sum(duracao_horas)              as horas,
           min(inicio)::date               as inicio,
           max(fim)::date                  as fim
      from sessoes
""").iloc[0]

a, b, c, d = st.columns(4)
a.metric('Sessões', f"{resumo_base['sessoes']:,}".replace(',', '.'))
b.metric('Chamados', resumo_base['chamados'])
c.metric('Clientes', resumo_base['clientes'])
d.metric('Horas apontadas', f"{resumo_base['horas']:.1f} h")
st.caption(f"Período coberto: {resumo_base['inicio']:%d/%m/%Y} a "
           f"{resumo_base['fim']:%d/%m/%Y}")

# --- Pendências de mapeamento ----------------------------------------
# Valores do Clockify sem código definido não entram no modelo. Mostrar
# isso é o que evita a demanda sumir sem ninguém entender por quê.
pendentes = db.consultar("""
    select 'Projeto' as campo, s.sistema as valor, count(*) as sessoes
      from sessoes s
      left join tipos_projeto t on t.nome_clockify = s.sistema
     where t.nome_clockify is null and s.sistema is not null
     group by s.sistema
    union all
    select 'Tarefa', s.tag, count(*)
      from sessoes s
      left join tipos_tarefa t on t.nome_clockify = s.tag
     where t.nome_clockify is null and s.tag is not null
     group by s.tag
     order by sessoes desc
""")

if not pendentes.empty:
    st.subheader('Pendentes de mapeamento')
    st.caption(
        'Valores do Clockify sem código definido. As demandas afetadas ficam '
        'fora do treino até receberem um código — ou continuam fora de '
        'propósito, se forem mesmo irrelevantes.'
    )
    st.dataframe(pendentes, hide_index=True, use_container_width=True)

# --- Últimas importações ---------------------------------------------
with st.expander('Histórico de importações'):
    st.dataframe(
        db.consultar("""
            select criado_em, arquivo, linhas_lidas, linhas_fora_escopo,
                   linhas_sem_chamado, linhas_novas, linhas_duplicadas
              from importacoes order by criado_em desc limit 20
        """),
        hide_index=True, use_container_width=True,
    )
