# Entrada do app: streamlit run app/app.py
import streamlit as st

st.set_page_config(page_title='Estimativa de Esforço', layout='wide')

with st.sidebar:
    st.toggle('Modo anônimo', key='anonimo',
              help='Oculta o número do chamado.')
    st.caption('TCC · Gustavo Borgonha · UNIDAVI 2026')

st.navigation([
    st.Page('paginas/orcamentos.py', title='Orçamentos'),
    st.Page('paginas/pipeline.py', title='Pipeline'),
    st.Page('paginas/resultados.py', title='Resultados'),
]).run()
