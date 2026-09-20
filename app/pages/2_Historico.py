"""Histórico de orçamentos, realimentação com horas reais e acurácia medida.

Fecha o ciclo do sistema: a estimativa registrada na página de orçamento
volta com o valor realizado, vira medida de acurácia e entra no próximo
treino. As métricas daqui são fora de amostra de verdade — o modelo não
conhecia estas demandas quando foi treinado.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd
import streamlit as st

import ui
from core import db, pipeline
from core.config import COBERTURA
from core.mascara import obter_mapa
from core.treino import mdmre, mmre, pred_25

ui.configurar('Histórico')
anonimo = ui.barra_lateral()

st.title('Histórico de orçamentos')

mapa_cliente = obter_mapa('cliente') if anonimo else {}


def exibir_cliente(valor):
    if valor is None:
        return '—'
    return mapa_cliente.get(valor, valor) if anonimo else valor


# =====================================================================
# Orçamentos em aberto — informar as horas reais
# =====================================================================
st.header('Em aberto')

abertos = db.consultar("""
    select id, criado_em, cliente, sistema, descricao, numero_chamado,
           previsao_horas, limite_inf, limite_sup, treino_id
      from orcamentos
     where status = 'aberto'
     order by criado_em
""")

if abertos.empty:
    st.info('Nenhum orçamento em aberto. Registre um em **Orçamento**.')
else:
    st.caption(
        f'{len(abertos)} aguardando conclusão. Ao informar as horas reais, o '
        'orçamento passa a contar na acurácia medida e entra no próximo treino.'
    )

    def rotular(identificador):
        linha = abertos.set_index('id').loc[identificador]
        cliente = exibir_cliente(linha['cliente'])
        chamado = f" · #{linha['numero_chamado']}" if linha['numero_chamado'] else ''
        return (f"{linha['criado_em']:%d/%m} · {cliente}{chamado} · "
                f"{linha['sistema']} · estimado {linha['previsao_horas']:.1f} h")

    escolhido = st.selectbox('Orçamento', abertos['id'], format_func=rotular)
    atual = abertos.set_index('id').loc[escolhido]

    col_a, col_b, col_c = st.columns(3)
    col_a.metric('Faixa estimada',
                 f"{atual['limite_inf']:.1f} – {atual['limite_sup']:.1f} h")
    col_b.metric('Valor central', f"{atual['previsao_horas']:.1f} h")
    col_c.metric('Modelo', f"versão {atual['treino_id']}")

    if atual['descricao']:
        st.caption(atual['descricao'])

    with st.form('concluir'):
        col_d, col_e = st.columns(2)
        horas = col_d.number_input('Horas reais gastas', min_value=0.01,
                                   step=0.25, value=float(atual['previsao_horas']))
        chamado = col_e.text_input('Número do chamado',
                                   value=atual['numero_chamado'] or '')

        col_f, col_g = st.columns(2)
        concluir = col_f.form_submit_button('Concluir', type='primary',
                                            width='stretch')
        cancelar = col_g.form_submit_button('Cancelar orçamento',
                                            width='stretch')

    if concluir:
        db.executar(
            """update orcamentos
                  set status = 'concluido', horas_reais = %s,
                      numero_chamado = %s, concluido_em = now()
                where id = %s""",
            (float(horas), chamado or None, escolhido),
        )
        st.success(f'Concluído com {horas:.2f} h. '
                   'Treine novamente para que entre no modelo.')
        st.rerun()

    if cancelar:
        db.executar("update orcamentos set status = 'cancelado' where id = %s",
                    (escolhido,))
        st.rerun()

st.divider()

# =====================================================================
# Acurácia em produção
# =====================================================================
st.header('Acurácia medida')

concluidos = db.consultar("""
    select criado_em, concluido_em, cliente, sistema, numero_chamado,
           tipo_projeto, tipo_tarefa, previsao_horas, limite_inf, limite_sup,
           horas_reais, treino_id
      from orcamentos
     where status = 'concluido' and horas_reais is not null
     order by concluido_em desc
""")

if concluidos.empty:
    st.info(
        'Nenhum orçamento concluído ainda. As métricas aqui são **fora de '
        'amostra de verdade**: medem o modelo prevendo demandas que não '
        'existiam quando ele foi treinado — diferente da validação cruzada '
        'da página de modelo, que reparte dados que o modelo já viu.'
    )
else:
    real = concluidos['horas_reais'].to_numpy(dtype=float)
    previsto = concluidos['previsao_horas'].to_numpy(dtype=float)
    dentro = ((real >= concluidos['limite_inf'].to_numpy(dtype=float))
              & (real <= concluidos['limite_sup'].to_numpy(dtype=float)))

    col_a, col_b, col_c, col_d = st.columns(4)
    col_a.metric('Orçamentos medidos', len(concluidos))
    col_b.metric('MAE', f'{np.abs(real - previsto).mean():.2f} h')
    col_c.metric('MdMRE', f'{mdmre(real, previsto):.1%}')
    col_d.metric('PRED(25)', f'{pred_25(real, previsto):.1%}',
                 help='Estimativas com erro relativo de até 25%')

    nominal = COBERTURA[1] - COBERTURA[0]
    aferida = float(dentro.mean())
    st.metric('Dentro da faixa prevista', f'{aferida:.1%}',
              f'{aferida - nominal:+.1%} vs. os {nominal:.0%} nominais')

    if len(concluidos) < 20:
        st.caption(
            f'Atenção: com {len(concluidos)} observações, estes números são '
            'indicativos. A cobertura só é comparável ao valor nominal a '
            'partir de algumas dezenas de casos.'
        )

    detalhe = concluidos.copy()
    detalhe['erro'] = (detalhe['horas_reais'] - detalhe['previsao_horas']).round(2)
    detalhe['erro_relativo'] = (
        (detalhe['erro'].abs() / detalhe['horas_reais']).round(3)
    )
    detalhe['dentro_da_faixa'] = dentro
    detalhe['cliente'] = detalhe['cliente'].map(exibir_cliente)

    st.dataframe(
        detalhe[['concluido_em', 'cliente', 'sistema', 'numero_chamado',
                 'previsao_horas', 'horas_reais', 'erro', 'erro_relativo',
                 'dentro_da_faixa', 'treino_id']],
        hide_index=True, width='stretch',
    )

st.divider()

# =====================================================================
# Exclusão manual de demandas
# =====================================================================
st.header('Demandas do histórico')
st.caption(
    'Demanda que não representa trabalho orçável pode ser excluída do treino. '
    'A marcação sobrevive ao recálculo e às importações futuras — é decisão '
    'sua, não resultado de regra. Substitui o `Chamado_142` que estava fixo '
    'no código do notebook.'
)

demandas = db.consultar("""
    select numero_chamado, cliente, sistema, tag, esforco_horas, qtd_sessoes,
           data_fim, incluida, motivo_exclusao, excluida_manual
      from demandas
     order by data_fim desc
""")

if demandas.empty:
    st.info('Nenhuma demanda calculada.')
    st.stop()

busca = st.text_input('Filtrar', placeholder='chamado, cliente ou sistema')
visao = demandas.copy()
visao['cliente'] = visao['cliente'].map(exibir_cliente)

if busca:
    alvo = busca.strip().lower()
    visao = visao[
        visao[['numero_chamado', 'cliente', 'sistema', 'tag']]
        .apply(lambda coluna: coluna.astype(str).str.lower().str.contains(alvo))
        .any(axis=1)
    ]

editado = st.data_editor(
    visao,
    hide_index=True, width='stretch', key='editor_demandas',
    disabled=[c for c in visao.columns if c != 'excluida_manual'],
    column_config={
        'excluida_manual': st.column_config.CheckboxColumn(
            'Excluir do treino', help='Marcação manual, preservada no recálculo'),
        'esforco_horas': st.column_config.NumberColumn('horas', format='%.2f'),
        'incluida': st.column_config.CheckboxColumn('no treino'),
    },
)

# Só grava o que mudou de fato: um UPDATE por linha editada, não por linha exibida.
mudancas = editado[editado['excluida_manual'] != visao['excluida_manual']]

if not mudancas.empty:
    st.warning(f'{len(mudancas)} marcações alteradas e ainda não salvas.')
    if st.button('Salvar e recalcular', type='primary'):
        for _, linha in mudancas.iterrows():
            db.executar(
                'update demandas set excluida_manual = %s where numero_chamado = %s',
                (bool(linha['excluida_manual']), linha['numero_chamado']),
            )
        # O recálculo precisa rodar: a exclusão manual é uma das regras, e
        # ela muda quem entra no dataset de treino.
        with st.spinner('Recalculando…'):
            pipeline.recalcular()
        st.success('Salvo. Treine novamente para aplicar ao modelo.')
        st.rerun()
