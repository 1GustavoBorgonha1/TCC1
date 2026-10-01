"""Registro de orçamentos a partir da estimativa do modelo."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st

import ui
from core import db, estimativa
from core.mascara import obter_mapa

ui.configurar('Orçamento')
anonimo = ui.barra_lateral()

st.title('Novo orçamento')

treino = estimativa.treino_ativo()
if treino is None:
    st.warning('Nenhum modelo treinado. Vá em **Dados e Modelo** e treine antes '
               'de orçar.')
    st.stop()

st.caption(
    f"Modelo versão {treino['id']}, treinado sobre {treino['n_demandas']} demandas "
    f"históricas e {treino['n_orcamentos']} orçamentos concluídos."
)

# =====================================================================
# Entradas
# =====================================================================
# O distinct é necessário porque nomes diferentes do Clockify podem
# apontar para o mesmo código ('Power BI' e 'PowerBI').
projetos = db.consultar(
    'select distinct codigo, rotulo from tipos_projeto order by codigo')
tarefas = db.consultar(
    'select distinct codigo, rotulo from tipos_tarefa order by codigo')

st.subheader('Parâmetros da estimativa')
st.caption('Os dois campos abaixo são os **únicos** que o modelo utiliza.')

col_a, col_b = st.columns(2)
projeto = col_a.selectbox('Tipo de projeto', projetos['codigo'],
                          format_func=lambda c: projetos.set_index('codigo')
                                                        .loc[c, 'rotulo'])
tarefa = col_b.selectbox('Tipo de tarefa', tarefas['codigo'],
                         format_func=lambda c: tarefas.set_index('codigo')
                                                      .loc[c, 'rotulo'])

st.subheader('Identificação')
st.caption(
    'Campos de registro: aparecem no histórico e permitem medir a acurácia '
    'depois, mas **não influenciam a estimativa**. O modelo final do TCC usa '
    'apenas tipo de projeto e tipo de tarefa.'
)

clientes = db.consultar(
    'select distinct cliente from demandas where cliente is not null order by cliente'
)['cliente'].tolist()
mapa_cliente = obter_mapa('cliente') if anonimo else {}

col_c, col_d = st.columns(2)
cliente = col_c.selectbox(
    'Cliente', ['—'] + clientes,
    format_func=lambda c: mapa_cliente.get(c, c) if anonimo and c != '—' else c,
)
chamado = col_d.text_input('Número do chamado', placeholder='opcional')
descricao = st.text_area('Descrição da demanda', placeholder='opcional', height=80)

# =====================================================================
# Resultado
# =====================================================================
try:
    resultado = estimativa.estimar(int(projeto), int(tarefa))
except (FileNotFoundError, RuntimeError) as erro:
    # Sem treino ativo ou .joblib ausente nesta máquina (modelos/ não vai para o git)
    st.error(f'Não foi possível carregar o modelo: {erro}')
    st.info('Treine o modelo na aba **Dados e Modelo** para gerar o arquivo nesta máquina.')
    st.page_link('pages/3_Dados_e_Modelo.py', label='Ir para Dados e Modelo', icon='➡️')
    st.stop()

st.divider()
st.subheader('Estimativa')

col_e, col_f, col_g = st.columns([2, 1, 1])
col_e.metric(
    'Faixa estimada',
    f"{resultado['limite_inf']:.1f} – {resultado['limite_sup']:.1f} h",
)
col_f.metric('Valor central', f"{resultado['previsao']:.1f} h")
col_g.metric('Base histórica', f"{resultado['base_historica']} demandas")

st.caption(
    f"Cobertura nominal de {resultado['cobertura_nominal']:.0%}: em cada dez "
    'demandas semelhantes do histórico, oito terminaram dentro desta faixa. '
    'O valor central não é uma promessa — é a tendência da distribuição.'
)

for aviso in resultado['ressalvas']:
    st.warning(aviso)

if not resultado['ressalvas']:
    st.success('Estimativa na região de melhor desempenho aferido do modelo.')

# =====================================================================
# Registro
# =====================================================================
st.divider()

if st.button('Registrar orçamento', type='primary'):
    db.executar(
        """insert into orcamentos
               (cliente, sistema, descricao, tipo_projeto, tipo_tarefa,
                previsao_horas, limite_inf, limite_sup, base_historica,
                ressalvas, treino_id, numero_chamado)
           values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        (None if cliente == '—' else cliente,
         projetos.set_index('codigo').loc[projeto, 'rotulo'],
         descricao or None, int(projeto), int(tarefa),
         resultado['previsao'], resultado['limite_inf'], resultado['limite_sup'],
         resultado['base_historica'], db.Json(resultado['ressalvas']),
         resultado['treino_id'], chamado or None),
    )
    st.success(
        'Orçamento registrado. Quando a demanda terminar, informe as horas '
        'reais em **Histórico** — elas medem a acurácia e entram no próximo treino.'
    )
