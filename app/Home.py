#Página inicial
import sys #Faz interação com o interpretador Python
from pathlib import Path

# Adiciona o diretório pai do arquivo atual ao início da lista de caminho
sys.path.insert(0, str(Path(__file__).parent))

import streamlit as st

import ui
from core import db

ui.configurar('Início')
ui.barra_lateral()

st.title('Estimativa de Esforço em Demandas de BI')
st.caption(
    'Sistema de apoio à orçamentação baseado em dados históricos e regressão. '
    'O modelo estima a partir do tipo de projeto e do tipo de tarefa, e devolve '
    'uma faixa de horas, não um número exato.'
)

# Uma consulta só para os quatro números: cada ida ao Supabase custa uns
# 100 ms, e o Streamlit re-executa este arquivo a cada clique.
painel = db.consultar("""
    select (select count(*) from sessoes)                        as sessoes,
           (select count(distinct numero_chamado) from sessoes)  as chamados,
           (select count(*) from demandas where incluida
                                            and not excluida_manual) as demandas,
           (select count(*) from orcamentos)                     as orcamentos,
           (select count(*) from orcamentos where status = 'aberto') as abertos
""").iloc[0]

a, b, c, d = st.columns(4)
a.metric('Sessões importadas', f"{painel['sessoes']:,}".replace(',', '.'))
b.metric('Chamados', painel['chamados'])
c.metric('Demandas no treino', painel['demandas'])
d.metric('Orçamentos', painel['orcamentos'],
         f"{painel['abertos']} em aberto" if painel['abertos'] else None)

st.divider()

treino = db.consultar("""
    select id, criado_em, n_demandas, n_orcamentos
      from treinos where ativo
""")

if treino.empty:
    st.warning(
        'Nenhum modelo treinado ainda. Vá em **Dados e Modelo**, importe os '
        'exports do Clockify e clique em Treinar modelo.'
    )
else:
    linha = treino.iloc[0]
    st.success(
        f"Modelo ativo: versão {linha['id']}, treinado em "
        f"{linha['criado_em']:%d/%m/%Y às %H:%M} sobre {linha['n_demandas']} "
        f"demandas históricas e {linha['n_orcamentos']} orçamentos concluídos."
    )

st.divider()
st.markdown("""
#### Como usar

1. **Dados e Modelo** — suba os exports do Clockify e treine. Subir um arquivo
   já importado é seguro: sessões repetidas são ignoradas pelo hash de conteúdo.
2. **Orçamento** — informe o tipo de projeto e o tipo de tarefa para receber a
   faixa estimada, e registre o orçamento.
3. **Histórico** — quando a demanda terminar, informe as horas reais. Elas medem
   a acurácia do modelo e entram no próximo treino.
""")
