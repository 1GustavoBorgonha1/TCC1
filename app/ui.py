"""Elementos de interface compartilhados pelas páginas.

Fica fora de core/ porque importa streamlit — a regra do projeto é que o
motor rode sem interface nenhuma.
"""
import streamlit as st

from core import mascara


def configurar(titulo: str) -> None:
    st.set_page_config(page_title=f'{titulo} · Estimativa de Esforço',
                       layout='wide')


def barra_lateral() -> bool:
    """Desenha a barra lateral e devolve se o modo anônimo está ligado.

    O valor mora em st.session_state para atravessar as páginas: ligar o
    modo na tela de histórico e ele continuar ligado no orçamento.
    """
    with st.sidebar:
        st.caption('TCC · Gustavo Borgonha · UNIDAVI 2026')
        anonimo = st.toggle(
            'Modo anônimo',
            key='modo_anonimo',
            help='Substitui nomes reais por códigos (Cliente_011). '
                 'Use para prints do TCC e para a apresentação.',
        )
        if anonimo:
            st.caption('Nomes reais ocultos')
    return anonimo


def talvez_mascarar(df, anonimo: bool, colunas_por_tipo: dict):
    """Aplica o mascaramento só quando o modo anônimo estiver ligado."""
    if not anonimo or df.empty:
        return df
    return mascara.aplicar(df, colunas_por_tipo)
