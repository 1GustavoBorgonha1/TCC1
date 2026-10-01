from functools import lru_cache # Guarda o resultado da função em memória;
from pathlib import PureWindowsPath

import joblib #usado para salvar e carregar modelos de ML em json
import pandas as pd

from . import treino

from . import db
from .config import (COBERTURA, CORTE_SEGMENTO, FAIXAS_ESFORCO, FEATURES,
                     MIN_BASE_CONFIAVEL, PASTA_MODELOS)

NOMINAL = COBERTURA[1] - COBERTURA[0]
TOLERANCIA = 0.05  


def treino_ativo() -> dict | None:
    tabela = db.consultar("""
        select id, criado_em, n_demandas, n_orcamentos, caminho_modelo,
               multiplicadores, combinacoes, cobertura_por_faixa
          from treinos where ativo
    """)
    return None if tabela.empty else tabela.iloc[0].to_dict()

# Guarda até 4 modelos em memória; o caminho tem o id do treino, então treinar invalida sozinho
@lru_cache(maxsize=4)
def _carregar(caminho: str):
    # O banco guarda o caminho absoluto da máquina que treinou; usa só o nome do arquivo
    return joblib.load(PASTA_MODELOS / PureWindowsPath(caminho).name)


def estimar(tipo_projeto: int, tipo_tarefa: int) -> dict:
    #Define a faixa de horas para uma combinação, com as ressalvas cabíveis.
    treino = treino_ativo()
    if treino is None:
        raise RuntimeError('Nenhum modelo treinado. Treine em Dados e Modelo.')

    modelo = _carregar(treino['caminho_modelo'])
    entrada = pd.DataFrame([{FEATURES[0]: tipo_projeto, FEATURES[1]: tipo_tarefa}])
    previsao = float(modelo.predict(entrada)[0])  # predict é do scikit-learn; devolve lista de 1 item

    # O segmento sai da própria previsão: na hora de orçar, é o único
    # valor disponível — o real é justamente o que se quer descobrir.
    chave = (f'até {CORTE_SEGMENTO:.0f} h' if previsao <= CORTE_SEGMENTO
             else f'acima de {CORTE_SEGMENTO:.0f} h')
    fatores = treino['multiplicadores'][chave]

    limite_inf = previsao * fatores['fator_min']
    limite_sup = previsao * fatores['fator_max']

    # Quantas demandas históricas sustentam esta combinação
    base = 0
    for c in treino['combinacoes']:
        if c[FEATURES[0]] == tipo_projeto and c[FEATURES[1]] == tipo_tarefa:
            base = int(c['demandas'])
            break

    return {
        'previsao': previsao,
        'limite_inf': limite_inf,
        'limite_sup': limite_sup,
        'segmento': chave,
        'base_historica': base,
        'treino_id': int(treino['id']),
        'cobertura_nominal': NOMINAL,
        'ressalvas': _ressalvas(previsao, limite_inf, limite_sup, base,
                                treino['cobertura_por_faixa']),
    }


def _ressalvas(previsao, limite_inf, limite_sup, base, cobertura) -> list[str]:
#Condições aferidas no treino que restringem o uso desta estimativa
    avisos = []

    if base == 0:
        avisos.append(
            'Combinação inédita: nenhuma demanda histórica com este par de '
            'projeto e tarefa. A previsão recai na tendência geral da base.'
        )
    elif base < MIN_BASE_CONFIAVEL:
        avisos.append(
            f'Base histórica reduzida: apenas {base} demandas semelhantes, '
            f'abaixo das {MIN_BASE_CONFIAVEL} consideradas mínimas. A previsão '
            'apoia-se em poucos casos.'
        )

    # Faixas de esforço que a estimativa alcança e onde a cobertura medida
    # ficou abaixo do prometido. É a ressalva mais importante: avisa que a
    # faixa não cumpre o que promete justamente nesta região.
    for minimo, maximo, rotulo in FAIXAS_ESFORCO:
        if limite_sup < minimo or limite_inf > maximo:
            continue                       # a estimativa não alcança esta faixa
        medida = cobertura.get(rotulo)
        if isinstance(medida, dict) and medida['cobertura'] < NOMINAL - TOLERANCIA:
            avisos.append(
                f'A faixa alcança o intervalo de {rotulo}, onde a cobertura '
                f'aferida foi de {medida["cobertura"]:.0%} contra os '
                f'{NOMINAL:.0%} nominais ({medida["demandas"]} demandas).'
            )

    if previsao > CORTE_SEGMENTO:
        avisos.append(
            f'Previsão acima de {CORTE_SEGMENTO:.0f} h: o segmento com maior '
            'dispersão histórica entre o estimado e o realizado.'
        )

    return avisos
