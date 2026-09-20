#Guarda as constantes de configuração da aplicação.
from pathlib import Path

# Busca a pasta raiz da aplicação
# config.py -> core -> app -> C:\TCC
RAIZ = Path(__file__).resolve().parents[2]
PASTA_MODELOS = RAIZ / 'modelos'

# Lista das colunas que vem no csv do clockfy
COLUNAS_CLOCKIFY = [
    'Project', 'Client', 'Description', 'Task', 'User', 'Group', 'Email',
    'Tags', 'Billable', 'Start Date', 'Start Time', 'End Date', 'End Time',
    'Duration (h)', 'Duration (decimal)', 'Date of creation',
]

#Formato da data/hora que vem do clockfy
FORMATO_DATA_CLOCKIFY = '%d/%m/%Y %H:%M:%S'   # célula 35

# Número do chamado: seis dígitos na faixa existente, '#' opcional (célula 7).
# Com grupo de captura para extrair; sem grupo para apenas testar.
PADRAO_CHAMADO = r'#?\b(2[5-9]\d{4}|3[0-2]\d{4})\b'
TEM_CHAMADO    = r'#?\b(?:2[5-9]\d{4}|3[0-2]\d{4})\b'

TAGS_FORA_ESCOPO = ('Suporte', 'Reunião') # Tags removidas do treinamento
TAG_META_TRABALHO = 'Orçamento'      # Tag removida do treinamento, mas usada para meta de trabalho
SISTEMAS_INTERNOS = frozenset({'IBS BI'})  # Remoção de tipo de sistema (uso interno da empresa)
PISO_HORAS        = 0.25             # Piso minimo de horas para uma demanda
DIAS_CENSURA      = 5                # Dias de censura para demandas recentes
MIN_OCORRENCIAS   = 5                # Minimo de ocorrência em que alguma característica tem que ter

# Configuração do modelo de regressão
SEMENTE   = 42
N_FOLDS   = 5
FEATURES  = ['tipo_projeto', 'tipo_tarefa']
ALVO      = 'horas_executadas'

COBERTURA       = (0.10, 0.90)   #  Faixa de cobertura do modelo
CORTE_SEGMENTO  = 3.0            # Separa os dois segmentos de previsão
MIN_BASE_CONFIAVEL = 10          # Abaixo disso não se considera a base confiável para aferição de cobertura

# Faixas de esforço real usadas na aferição de cobertura
FAIXAS_ESFORCO = [
    (0.25, 1.0,   '0,25–1 h'),
    (1.0,  3.0,   '1–3 h'),
    (3.0,  8.0,   '3–8 h'),
    (8.0,  float('inf'), 'acima de 8 h'),
]
