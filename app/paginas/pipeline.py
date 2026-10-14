import streamlit as st

import db
import etl
import modelo
from config import NOME_PROJETO, NOME_TAREFA

st.title('Pipeline')
st.caption('Os passos do notebook, da exportação do Clockify ao modelo treinado.')

# ---------------------------------------------------------------- 1
st.header('1. Importar CSV do Clockify')
arquivos = st.file_uploader('Relatório detalhado (CSV)', type='csv', accept_multiple_files=True)
if arquivos and st.button('Importar', type='primary'):
    for arquivo in arquivos:
        r = etl.importar(arquivo, arquivo.name)
        st.success(f"{arquivo.name}: {r['lidas']} lidas, {r['fora_escopo']} fora de escopo, "
                   f"{r['sem_chamado']} sem chamado, {r['novas']} novas, "
                   f"{r['duplicadas']} já existiam")

# ---------------------------------------------------------------- 2
st.header('2. Seleção das sessões')
st.caption('Remove suporte, reunião e sessões sem etiqueta; depois, as sem número de chamado. '
           'Sessões já importadas são ignoradas pelo conteúdo.')
st.dataframe(db.consultar("""
    select sum(linhas_lidas) as lidas, sum(linhas_fora_escopo) as fora_de_escopo,
           sum(linhas_sem_chamado) as sem_chamado, sum(linhas_novas) as gravadas,
           sum(linhas_duplicadas) as repetidas
      from importacoes"""), hide_index=True)

# ---------------------------------------------------------------- 3
st.header('3. Agrupamento em demandas')
demandas, incluidas, funil = etl.base()
a, b, c = st.columns(3)
a.metric('Sessões', int(demandas['sessoes'].sum()))
b.metric('Demandas', len(demandas))
c.metric('Esforço total', f"{demandas['esforco'].sum():.2f} h")
st.caption('Uma linha por chamado (mesclados consolidados no chamado de destino). '
           'Esforço é a soma das sessões; sistema e tag vêm da sessão mais longa.')

# ---------------------------------------------------------------- 4
st.header('4. Regras de inclusão')
st.dataframe(funil, hide_index=True)

# ---------------------------------------------------------------- 5
st.header('5. Dataset codificado')
dados = etl.dataset(incluidas)
st.caption(f"{(dados['origem'] == 'clockify').sum()} demandas do Clockify e "
           f"{(dados['origem'] == 'orcamento').sum()} orçamentos concluídos.")
st.caption('Códigos — tipo_projeto: ' + ', '.join(f'{k} = {v}' for k, v in NOME_PROJETO.items())
           + ' · tipo_tarefa: ' + ', '.join(f'{k} = {v}' for k, v in NOME_TAREFA.items()))
st.dataframe(dados.rename(columns={'horas': 'horas_executadas'}), hide_index=True)

# ---------------------------------------------------------------- 6
st.header('6. Treino')
if st.button('Treinar modelo', type='primary'):
    with st.spinner('Validação cruzada, calibração e treino final…'):
        modelo.treinar(dados)

treino = modelo.treino_ativo()
if treino is None:
    st.info('Nenhum modelo treinado.')
    st.stop()

erro = treino['metricas']['modelo']
st.subheader('Erro do modelo na validação cruzada (5 partições)')
a, b, c, d, e, f = st.columns(6)
a.metric('MAE', f"{erro['MAE']:.2f} h", help='Erro médio, em horas')
b.metric('RMSE', f"{erro['RMSE']:.2f} h", help='Erro médio com peso maior para erros grandes')
c.metric('R²', f"{erro['R2']:.3f}", help='Proporção da variação do esforço explicada')
d.metric('MMRE', f"{erro['MMRE']:.0%}", help='Erro relativo médio')
e.metric('MdMRE', f"{erro['MdMRE']:.0%}", help='Erro relativo da demanda típica')
f.metric('PRED(25)', f"{erro['PRED25']:.0%}", help='Estimativas com erro de até 25%')

st.success(f"Modelo versão {treino['id']} (Random Forest com perda absoluta), treinado em "
           f"{treino['criado_em']:%d/%m/%Y %H:%M} com "
           f"{treino['n_demandas'] + treino['n_orcamentos']} demandas "
           f"({treino['n_demandas']} do Clockify e {treino['n_orcamentos']} de orçamentos "
           f"concluídos na aplicação), finalizado e pronto para estimar em Orçamentos.")
