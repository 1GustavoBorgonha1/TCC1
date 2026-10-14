import numpy as np
import pandas as pd
import streamlit as st

import db
import modelo
from config import exibir

anonimo = st.session_state.get('anonimo', False)
st.title('Resultados')

# ---------------------------------------------------------------- Visão geral
geral = db.consultar("""
    select (select count(*) from sessoes)                                  as sessoes,
           (select count(distinct numero_chamado) from sessoes)            as chamados,
           (select count(*) from orcamentos where status <> 'cancelado')   as orcamentos,
           (select count(*) from orcamentos where status = 'aberto')       as abertos""").iloc[0]
treino = modelo.treino_ativo()

a, b, c, d = st.columns(4)
a.metric('Sessões importadas', int(geral['sessoes']))
b.metric('Chamados', int(geral['chamados']))
c.metric('Demandas no treino', treino['n_demandas'] + treino['n_orcamentos'] if treino else 0)
d.metric('Orçamentos', int(geral['orcamentos']), f"{geral['abertos']} em aberto",
         delta_color='off')
if treino:
    st.caption(f"Modelo ativo: versão {treino['id']}, treinado em "
               f"{treino['criado_em']:%d/%m/%Y %H:%M}.")

# ---------------------------------------------------------------- Validação
st.header('Validação: previsto × executado')
concluidos = db.consultar("""
    select concluido_em, numero_chamado, tipo_projeto, tipo_tarefa,
           limite_inf, previsao_horas, limite_sup, horas_reais, treino_id
      from orcamentos where status = 'concluido' order by concluido_em desc""")

if concluidos.empty:
    st.info('Nenhum orçamento concluído ainda.')
    st.stop()

real = concluidos['horas_reais'].to_numpy(float)
previsto = concluidos['previsao_horas'].to_numpy(float)
n = len(real)
st.caption('Cada orçamento teve a faixa registrada antes da execução, por um modelo que não '
           'conhecia a demanda; o esforço real veio do apontamento depois de concluída.')

# Acerto: proporção de demandas em que a estimativa atendeu a regra declarada
concluidos['dentro_da_faixa'] = (real >= concluidos['limite_inf']) & (real <= concluidos['limite_sup'])
erro_relativo = modelo.mre(real, previsto)
acertos = [
    ('Acerto da faixa', concluidos['dentro_da_faixa'].sum(),
     'O esforço real ficou entre o limite inferior e o superior da faixa. '
     'É o que o sistema entrega; a meta declarada é 80%.'),
    ('Acerto com tolerância de 25% — PRED(25)', (erro_relativo <= 0.25).sum(),
     'O valor central errou no máximo 25% do esforço real.'),
    ('Acerto com tolerância de 50% — PRED(50)', (erro_relativo <= 0.50).sum(),
     'O valor central errou no máximo 50% do esforço real.'),
]

st.subheader('Quanto o modelo acerta')
for coluna, (nome, k, regra) in zip(st.columns(3), acertos):
    coluna.metric(nome, f'{k} de {n}', f'{k / n:.1%}', delta_color='off')
    coluna.caption(regra)

acima, abaixo = (previsto > real).sum(), (previsto < real).sum()
st.caption(f'Quando errou, o modelo superestimou {acima} e subestimou {abaixo} demandas: '
           f'previu {previsto.sum():.1f} h no total para {real.sum():.1f} h executadas.')
if n < 30:
    st.caption(f'Com {n} demandas, os percentuais são indicativos (teste exploratório).')

st.subheader('Tamanho do erro')
st.caption('As métricas da fase de avaliação (Quadro 9), sobre as mesmas demandas.')
st.dataframe(pd.DataFrame([{
    'MAE (h)': round(float(np.abs(real - previsto).mean()), 3),
    'RMSE (h)': round(float(np.sqrt(((real - previsto) ** 2).mean())), 3),
    'MMRE': round(modelo.mmre(real, previsto), 3),
    'MdMRE': round(modelo.mdmre(real, previsto), 3),
}]), hide_index=True)

st.subheader('Orçamentos concluídos')
st.dataframe(exibir(concluidos, anonimo), hide_index=True)
