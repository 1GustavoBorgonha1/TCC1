import streamlit as st

import db
import etl
import modelo
from config import NOME_PROJETO, NOME_TAREFA, exibir

anonimo = st.session_state.get('anonimo', False)
st.title('Orçamentos')


def horas(texto):
    """'1,30' ou '1:30' (h,mm) -> 1.5. Vazio -> None. Formato inválido -> ValueError."""
    texto = texto.strip().replace(':', ',')
    if not texto:
        return None
    h, _, m = texto.partition(',')
    if not h.isdigit() or (m and (len(m) != 2 or not m.isdigit() or int(m) >= 60)):
        raise ValueError(f'"{texto}" não está no formato h,mm (ex.: 1,30 = uma hora e meia).')
    return int(h) + int(m or 0) / 60

# ---------------------------------------------------------------- Novo orçamento
st.header('Novo orçamento')
a, b = st.columns(2)
projeto = a.selectbox('Tipo de projeto', list(NOME_PROJETO),
                      format_func=NOME_PROJETO.get)
tarefa = b.selectbox('Tipo de tarefa', list(NOME_TAREFA),
                     format_func=NOME_TAREFA.get)
chamado = st.text_input('Número do chamado', type='password' if anonimo else 'default')

try:
    estimativa = modelo.estimar(projeto, tarefa)
except RuntimeError as erro:
    st.error(f'{erro} Treine o modelo para continuar.')
    if st.button('Treinar modelo agora', type='primary'):
        with st.spinner('Treinando…'):
            modelo.treinar(etl.dataset(etl.base()[1]))
        st.rerun()
    st.stop()

e, f, g = st.columns(3)
e.metric('Faixa estimada', f"{estimativa['inf']:.1f} – {estimativa['sup']:.1f} h")
f.metric('Valor central', f"{estimativa['previsao']:.1f} h")
g.metric('Base histórica', f"{estimativa['base']} demandas")
st.caption('Cobertura nominal de 80%: oito em cada dez demandas semelhantes do '
           'histórico terminaram dentro desta faixa.')
for ressalva in estimativa['ressalvas']:
    st.warning(ressalva)

if st.button('Registrar orçamento', type='primary'):
    db.executar("""insert into orcamentos (tipo_projeto, tipo_tarefa, previsao_horas, limite_inf,
                       limite_sup, treino_id, numero_chamado)
                   values (%s, %s, %s, %s, %s, %s, %s)""",
                (projeto, tarefa, estimativa['previsao'], estimativa['inf'], estimativa['sup'],
                 estimativa['treino_id'],
                 chamado or None))
    st.success('Orçamento registrado.')

# ---------------------------------------------------------------- Em aberto
st.header('Em aberto')
abertos = db.consultar("""select id, criado_em, numero_chamado, previsao_horas
                            from orcamentos where status = 'aberto' order by criado_em""")
if abertos.empty:
    st.caption('Nenhum orçamento em aberto.')
else:
    rotulos = exibir(abertos, anonimo)
    escolhido = st.selectbox(
        'Orçamento', abertos.index,
        format_func=lambda i: f"{rotulos.at[i, 'criado_em']:%d/%m %H:%M} · chamado "
                              f"{rotulos.at[i, 'numero_chamado'] or '—'} · "
                              f"estimado {rotulos.at[i, 'previsao_horas']:.1f} h")
    with st.form('concluir'):
        reais = st.text_input('Horas reais gastas (h,mm)', placeholder='2,15')
        h, i = st.columns(2)
        if h.form_submit_button('Concluir', type='primary'):
            try:
                reais = horas(reais)
            except ValueError as erro:
                st.error(str(erro))
                st.stop()
            if not reais:
                st.error('Informe as horas reais.')
                st.stop()
            db.executar("""update orcamentos set status = 'concluido', horas_reais = %s,
                               concluido_em = now() where id = %s""",
                        (reais, abertos.at[escolhido, 'id']))
            st.rerun()
        if i.form_submit_button('Cancelar orçamento'):
            db.executar("update orcamentos set status = 'cancelado' where id = %s",
                        (abertos.at[escolhido, 'id'],))
            st.rerun()

# ---------------------------------------------------------------- Registrados
st.header('Registrados')
registrados = db.consultar("""
    select id, criado_em, numero_chamado, tipo_projeto, tipo_tarefa,
           limite_inf, previsao_horas, limite_sup, horas_reais, status, treino_id
      from orcamentos order by criado_em desc""")
tabela = st.dataframe(exibir(registrados, anonimo), hide_index=True, column_config={'id': None},
                      on_select='rerun', selection_mode='multi-row')

# Selecione linhas na tabela (caixa à esquerda) para excluir. Apagar é definitivo.
linhas = tabela.selection.rows
if linhas:
    confirmo = st.checkbox(f'Confirmo a exclusão definitiva de {len(linhas)} orçamento(s)')
    if st.button('Excluir selecionados', disabled=not confirmo):
        db.executar('delete from orcamentos where id = any(%s::uuid[])',
                    (list(registrados.loc[linhas, 'id'].astype(str)),))
        st.rerun()
