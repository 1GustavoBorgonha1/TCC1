# Partes 6 a 8 do notebook: modelo final, métricas, faixa e estimativa
from functools import lru_cache  # guarda resultados de funções na memória

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import make_scorer
from sklearn.model_selection import KFold, cross_val_predict, cross_validate
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

import db
from config import (COBERTURA, CORTE, FAIXAS, FEATURES, LIMIAR_PORTE, MIN_BASE,
                    PASTA_MODELOS, ROTULOS, SEMENTE)

VALIDACAO = KFold(n_splits=5, shuffle=True, random_state=SEMENTE)
NOMINAL = COBERTURA[1] - COBERTURA[0]


# 6.2 — Métricas
def mre(real, previsto):
    return np.abs(np.asarray(real) - np.asarray(previsto)) / np.asarray(real)


def mmre(real, previsto):
    return float(mre(real, previsto).mean())


def mdmre(real, previsto):
    return float(np.median(mre(real, previsto)))


def pred_25(real, previsto):
    return float((mre(real, previsto) <= 0.25).mean())


METRICAS = {
    'MAE': 'neg_mean_absolute_error',
    'RMSE': 'neg_root_mean_squared_error',
    'R2': 'r2',
    'MMRE': make_scorer(mmre, greater_is_better=False),
    'MdMRE': make_scorer(mdmre, greater_is_better=False),
    'PRED25': make_scorer(pred_25),
}


def pipeline(estimador):
    """One-hot + estimador; categoria nova vira vetor de zeros em vez de erro."""
    return Pipeline([
        ('preprocessamento', ColumnTransformer(
            [('categoricas', OneHotEncoder(handle_unknown='ignore'), FEATURES)])),
        ('modelo', estimador),
    ])


def rf_final():
    return pipeline(RandomForestRegressor(n_estimators=300, min_samples_leaf=5,
                                          criterion='absolute_error',
                                          random_state=SEMENTE, n_jobs=-1))


# 6.4 — Erro do modelo final na validação cruzada
def avaliar(X, y):
    r = cross_validate(rf_final(), X, y, cv=VALIDACAO, scoring=METRICAS)
    return {'modelo': {m: round(float(r[f'test_{m}'].mean() * (1 if m in ('R2', 'PRED25') else -1)), 3)
                       for m in METRICAS}}


def segmento(previsao):
    return f'até {CORTE:.0f} h' if previsao <= CORTE else f'acima de {CORTE:.0f} h'


# 8.2 e 8.3 — Faixa pelos percentis da razão real/previsto, fora da amostra
def calibrar(X, y):
    c = pd.DataFrame({'real': np.asarray(y),
                      'previsto': cross_val_predict(rf_final(), X, y, cv=VALIDACAO)})
    c['razao'] = c['real'] / c['previsto']
    c['segmento'] = c['previsto'].map(segmento)

    multiplicadores = {
        nome: {'fator_min': round(float(g['razao'].quantile(COBERTURA[0])), 3),
               'fator_max': round(float(g['razao'].quantile(COBERTURA[1])), 3)}
        for nome, g in c.groupby('segmento')
    }

    c['inf'] = c['previsto'] * c['segmento'].map(lambda s: multiplicadores[s]['fator_min'])
    c['sup'] = c['previsto'] * c['segmento'].map(lambda s: multiplicadores[s]['fator_max'])
    c['dentro'] = c['real'].between(c['inf'], c['sup'])
    c['faixa'] = pd.cut(c['real'], bins=FAIXAS, labels=ROTULOS, include_lowest=True)

    # Cobertura por faixa de esforço real: alimenta as ressalvas da estimativa
    cobertura = {faixa: {'cobertura': round(float(g['dentro'].mean()), 3)}
                 for faixa, g in c.groupby('faixa', observed=True)}
    return multiplicadores, cobertura


# 8.1 — Treino completo: compara, calibra, salva e ativa
def treinar(dados):
    if len(dados) < 30:
        raise ValueError(f'Apenas {len(dados)} demandas: importe mais dados antes de treinar.')
    X, y = dados[FEATURES], dados['horas']

    avaliacao = avaliar(X, y)
    multiplicadores, cobertura = calibrar(X, y)
    final = rf_final().fit(X, y)
    # Quantas demandas sustentam cada combinação: base da ressalva de poucos casos
    combinacoes = X.value_counts().rename('demandas').reset_index()

    PASTA_MODELOS.mkdir(exist_ok=True)
    conexao = db.conectar()
    try:
        with conexao, conexao.cursor() as cursor:   # tudo ou nada
            cursor.execute('update treinos set ativo = false where ativo')
            cursor.execute(
                """insert into treinos (n_demandas, n_orcamentos, metricas, multiplicadores,
                                        combinacoes, cobertura_por_faixa, caminho_modelo, ativo)
                   values (%s, %s, %s, %s, %s, %s, '', true) returning id""",
                (int((dados['origem'] == 'clockify').sum()),
                 int((dados['origem'] == 'orcamento').sum()),
                 db.Json(avaliacao), db.Json(multiplicadores),
                 db.Json(combinacoes.to_dict('records')), db.Json(cobertura)))
            treino_id = cursor.fetchone()[0]
            arquivo = f'modelo_v{treino_id}.joblib'
            joblib.dump(final, PASTA_MODELOS / arquivo)
            cursor.execute('update treinos set caminho_modelo = %s where id = %s',
                           (arquivo, treino_id))
    finally:
        conexao.close()
    return treino_id


def treino_ativo():
    t = db.consultar('select * from treinos where ativo')
    return None if t.empty else t.iloc[0].to_dict()


@lru_cache(maxsize=4)
def _carregar(arquivo):
    return joblib.load(PASTA_MODELOS / arquivo)


# 8.4 — Estimativa operacional
def estimar(tipo_projeto, tipo_tarefa):
    treino = treino_ativo()
    if treino is None:
        raise RuntimeError('Nenhum modelo treinado.')
    arquivo = treino['caminho_modelo']
    if not (PASTA_MODELOS / arquivo).exists():
        raise RuntimeError(f'O arquivo do modelo ativo ({arquivo}) não está nesta máquina.')
    modelo = _carregar(arquivo)
    entrada = pd.DataFrame([{'tipo_projeto': tipo_projeto, 'tipo_tarefa': tipo_tarefa}])
    previsao = float(modelo.predict(entrada)[0])
    fatores = treino['multiplicadores'][segmento(previsao)]
    inf, sup = previsao * fatores['fator_min'], previsao * fatores['fator_max']
    base = next((c['demandas'] for c in treino['combinacoes']
                 if c['tipo_projeto'] == tipo_projeto and c['tipo_tarefa'] == tipo_tarefa), 0)
    cobertura = treino['cobertura_por_faixa']

    # Ressalvas da seção 8.4 do notebook, em linguagem de quem orça
    ressalvas = []
    if base < MIN_BASE:
        ressalvas.append(f'**Poucos casos parecidos.** Só {base} demandas do histórico têm este '
                         f'tipo de projeto e de tarefa (o mínimo recomendado é {MIN_BASE}). '
                         'A estimativa se apoia em pouca experiência.')
    if previsao > CORTE:
        ressalvas.append('**Tipo de demanda que varia muito.** Novas funcionalidades e Power BI '
                         'costumam fugir mais da previsão, para cima ou para baixo. Por isso a '
                         'faixa é mais larga.')
        if ROTULOS[2] in cobertura:
            ressalvas.append(f'**Faixa um pouco menos confiável.** Em demandas reais de '
                             f'{ROTULOS[2]}, o esforço ficou dentro da faixa em '
                             f'{cobertura[ROTULOS[2]]["cobertura"]:.0%} dos casos, abaixo dos '
                             f'{NOMINAL:.0%} prometidos. Considere folga no limite superior.')
    if sup >= LIMIAR_PORTE and ROTULOS[-1] in cobertura:
        ressalvas.append(f'**Demanda grande fica fora do alcance.** Acima de '
                         f'{LIMIAR_PORTE:.0f} h, o esforço real ficou dentro da faixa em só '
                         f'{cobertura[ROTULOS[-1]]["cobertura"]:.0%} dos casos. Se o escopo é '
                         'claramente amplo, estime pelo seu julgamento, sem apoio do modelo.')

    return {'previsao': previsao, 'inf': inf, 'sup': sup, 'base': base,
            'treino_id': int(treino['id']), 'ressalvas': ressalvas}
