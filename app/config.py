# Constantes do notebook, num lugar só
from pathlib import Path

# Pasta raiz do projeto (C:\TCC): .resolve() torna o caminho deste arquivo absoluto
# e .parents[1] sobe dois níveis (config.py -> app -> raiz)
RAIZ = Path(__file__).resolve().parents[1]
PASTA_MODELOS = RAIZ / 'modelos'

# 1.4 — Sessões fora de escopo e número do chamado (seis dígitos, '#' opcional)
TAGS_FORA = ['Suporte', 'Reunião']
NUM_CHAMADO = r'2[5-9]\d{4}|3[0-2]\d{4}'
PADRAO_CHAMADO = rf'#?\b({NUM_CHAMADO})\b'

# 1.9 — Chamados mesclados no Movidesk: filho -> pai
MESCLADOS = {'299033': '298991', '306683': '306115'}

# Parte 4 — Regras de inclusão
TAG_ORCAMENTO = 'Orçamento'
SISTEMAS_FORA = ['PAF WS', 'Volcan SFT']   # Sistema_001 e Sistema_004
PISO = 0.25
DIAS_CENSURA = 5
CHAMADOS_INTERNOS = ['302330']             # Chamado_142
MIN_OCORRENCIAS = 5

# Parte 5 — Codificação
TIPO_PROJETO = {'Power BI': 1, 'WBI': 2}
TIPO_TAREFA = {'Nova Funcionalidade': 1, 'Alteração': 2, 'Análise de problema': 3}
NOME_PROJETO = {1: 'BI (Power BI)', 2: 'Relatório de Sistema'}
NOME_TAREFA = {codigo: nome for nome, codigo in TIPO_TAREFA.items()}

# Partes 6 a 8 — Modelo e faixa
SEMENTE = 42
FEATURES = ['tipo_projeto', 'tipo_tarefa']
COBERTURA = (0.10, 0.90)
CORTE = 2.0          # segmento da faixa (4.1.5.3)
MIN_BASE = 10        # mínimo de demandas parecidas no histórico; abaixo disso a estimativa mostra o aviso "Poucos casos parecidos"
LIMIAR_PORTE = 8.0   # horas a partir das quais a demanda é "grande": última divisa de FAIXAS e gatilho do aviso de baixa confiança
FAIXAS = [0.25, 1, 3, LIMIAR_PORTE, float('inf')]
ROTULOS = ['0,25–1 h', '1–3 h', '3–8 h', 'acima de 8 h']


def exibir(df, anonimo):
    """Rótulos legíveis de projeto e tarefa; no modo anônimo, oculta o chamado."""
    df = df.copy()
    if anonimo and 'numero_chamado' in df:
        df['numero_chamado'] = df['numero_chamado'].map(lambda c: 'oculto' if c else '—')
    if 'tipo_projeto' in df:
        df['tipo_projeto'] = df['tipo_projeto'].map(NOME_PROJETO)
    if 'tipo_tarefa' in df:
        df['tipo_tarefa'] = df['tipo_tarefa'].map(NOME_TAREFA)
    return df
