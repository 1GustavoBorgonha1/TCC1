"""Treino, validação e calibração do modelo (Partes 6 a 8 do notebook).

O que sai daqui: um .joblib em disco e um registro na tabela `treinos`
com métricas, multiplicadores da faixa e cobertura aferida. Os JSONs não
são relatório: a estimativa não funciona sem eles.
"""

from datetime import datetime

import joblib
import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, RegressorMixin
from sklearn.compose import ColumnTransformer
from sklearn.dummy import DummyRegressor
from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
from sklearn.linear_model import LinearRegression
from sklearn.metrics import make_scorer
from sklearn.model_selection import KFold, cross_val_predict, cross_validate
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder
from sklearn.svm import SVR
from sklearn.tree import DecisionTreeRegressor

from . import db, pipeline
from .config import (ALVO, COBERTURA, CORTE_SEGMENTO, FAIXAS_ESFORCO, FEATURES,
                     N_FOLDS, PASTA_MODELOS, SEMENTE)

VALIDACAO = KFold(n_splits=N_FOLDS, shuffle=True, random_state=SEMENTE)


# =====================================================================
# Métricas — célula 104
# Além de MAE/RMSE/R², o TCC usa as métricas relativas consagradas na
# literatura de estimativa de esforço, que medem o erro em proporção ao
# tamanho da demanda: errar 2 h num trabalho de 40 h não é o mesmo que
# errar 2 h num de 3 h.
# =====================================================================

def mre(y_real, y_previsto):
    """Magnitude of Relative Error, elemento a elemento."""
    return np.abs(np.asarray(y_real) - np.asarray(y_previsto)) / np.asarray(y_real)


def mmre(y_real, y_previsto):
    return float(mre(y_real, y_previsto).mean())


def mdmre(y_real, y_previsto):
    return float(np.median(mre(y_real, y_previsto)))


def pred_25(y_real, y_previsto):
    """Proporção de estimativas com erro relativo de até 25%."""
    return float((mre(y_real, y_previsto) <= 0.25).mean())


METRICAS = {
    'MAE':    'neg_mean_absolute_error',
    'RMSE':   'neg_root_mean_squared_error',
    'R2':     'r2',
    'MMRE':   make_scorer(mmre,    greater_is_better=False),
    'MdMRE':  make_scorer(mdmre,   greater_is_better=False),
    'PRED25': make_scorer(pred_25, greater_is_better=True),
}

# O scikit-learn devolve negado tudo que "quanto menor, melhor", para que
# maior signifique sempre melhor internamente. Desfazemos na exibição.
INVERTER_SINAL = {'MAE', 'RMSE', 'MMRE', 'MdMRE'}


# =====================================================================
# Baselines — células 108 e 112
# =====================================================================

class MedianaPorGrupo(BaseEstimator, RegressorMixin):
    """Prevê a mediana histórica do grupo; grupo novo cai na mediana global.

    É a regra de bolso que qualquer analista experiente aplicaria sem
    computador. Qualquer modelo que não a supere não se justifica.
    """

    def __init__(self, colunas=None):
        self.colunas = colunas

    def fit(self, X, y):
        dados = pd.DataFrame(X).reset_index(drop=True)
        dados['_alvo'] = np.asarray(y)
        self.medianas_ = dados.groupby(self.colunas, as_index=False)['_alvo'].median()
        self.mediana_global_ = float(np.median(y))
        return self

    def predict(self, X):
        dados = pd.DataFrame(X).reset_index(drop=True)
        previsto = dados.merge(self.medianas_, on=self.colunas, how='left')['_alvo']
        return previsto.fillna(self.mediana_global_).to_numpy()


def _montar(modelo) -> Pipeline:
    """Encadeia one-hot e estimador.

    handle_unknown='ignore' é o que impede a aplicação de quebrar quando
    aparece uma combinação que não existia no treino: em vez de erro, o
    modelo recebe um vetor de zeros e devolve a tendência central.
    """
    return Pipeline([
        ('preprocessamento', ColumnTransformer([
            ('categoricas', OneHotEncoder(handle_unknown='ignore'), FEATURES),
        ])),
        ('modelo', modelo),
    ])


def modelos_candidatos() -> dict:
    """Os cinco algoritmos do referencial, mais as baselines (célula 114)."""
    return {
        'Baseline — mediana global':    DummyRegressor(strategy='median'),
        'Baseline — mediana por tarefa': MedianaPorGrupo(colunas=['tipo_tarefa']),
        'Baseline — mediana por projeto × tarefa': MedianaPorGrupo(colunas=FEATURES),
        'Regressão Linear':  LinearRegression(),
        'Árvore de Decisão': DecisionTreeRegressor(min_samples_leaf=10,
                                                   random_state=SEMENTE),
        'Random Forest':     RandomForestRegressor(n_estimators=300,
                                                   min_samples_leaf=5,
                                                   random_state=SEMENTE, n_jobs=-1),
        'SVR':               SVR(),
        'Gradient Boosting': GradientBoostingRegressor(min_samples_leaf=5,
                                                        random_state=SEMENTE),
    }


def comparar(X: pd.DataFrame, y: pd.Series) -> pd.DataFrame:
    """Validação cruzada de todos os candidatos. Uma linha por modelo."""
    linhas = []
    for nome, estimador in modelos_candidatos().items():
        # As baselines de mediana por grupo trabalham direto nas colunas
        # originais: passar por one-hot destruiria o agrupamento.
        montado = estimador if isinstance(estimador, MedianaPorGrupo) else _montar(estimador)

        resultado = cross_validate(montado, X, y, cv=VALIDACAO, scoring=METRICAS)

        linha = {'modelo': nome}
        for metrica in METRICAS:
            valores = resultado[f'test_{metrica}']
            if metrica in INVERTER_SINAL:
                valores = -valores
            linha[metrica] = round(float(valores.mean()), 3)
            linha[f'{metrica}_desvio'] = round(float(valores.std()), 3)
        linhas.append(linha)

    return pd.DataFrame(linhas)


def modelo_final():
    """O estimador escolhido no TCC (célula 130).

    criterion='absolute_error' faz a árvore otimizar o erro absoluto em vez
    do quadrático. Com uma distribuição tão assimétrica quanto a sua —
    mediana de 1,25 h e máximo de 69 h — o erro quadrático deixaria os
    poucos casos gigantes ditarem o modelo inteiro.
    """
    return _montar(RandomForestRegressor(
        n_estimators=300, min_samples_leaf=5, criterion='absolute_error',
        random_state=SEMENTE, n_jobs=-1,
    ))


# =====================================================================
# Calibração da faixa — células 132 a 134
# =====================================================================

def calibrar(modelo, X, y) -> tuple[dict, dict]:
    """Converte a previsão pontual em faixa. Devolve (multiplicadores, cobertura).

    A razão real/previsto é medida FORA DA AMOSTRA (cross_val_predict):
    usar previsões do próprio treino daria uma faixa otimista e estreita
    que não se sustentaria no uso real.
    """
    previsto = cross_val_predict(modelo, X, y, cv=VALIDACAO)
    calib = pd.DataFrame({'real': np.asarray(y), 'previsto': previsto})
    calib['razao'] = calib['real'] / calib['previsto']

    # A segmentação usa o valor PREVISTO, não o real: na hora de orçar, o
    # real é justamente o que não se conhece.
    calib['segmento'] = np.where(calib['previsto'] <= CORTE_SEGMENTO,
                                 f'até {CORTE_SEGMENTO:.0f} h',
                                 f'acima de {CORTE_SEGMENTO:.0f} h')

    multiplicadores = {}
    for segmento, grupo in calib.groupby('segmento'):
        multiplicadores[segmento] = {
            'demandas':  int(len(grupo)),
            'fator_min': round(float(grupo['razao'].quantile(COBERTURA[0])), 3),
            'fator_max': round(float(grupo['razao'].quantile(COBERTURA[1])), 3),
            'razao_mediana': round(float(grupo['razao'].median()), 3),
        }

    # Cobertura aferida: a faixa realmente contém o valor real na
    # proporção prometida? É daqui que saem as ressalvas da tela.
    calib['limite_inf'] = calib.apply(
        lambda l: l['previsto'] * multiplicadores[l['segmento']]['fator_min'], axis=1)
    calib['limite_sup'] = calib.apply(
        lambda l: l['previsto'] * multiplicadores[l['segmento']]['fator_max'], axis=1)
    calib['dentro'] = calib['real'].between(calib['limite_inf'], calib['limite_sup'])

    cobertura = {'geral': round(float(calib['dentro'].mean()), 3)}
    for minimo, maximo, rotulo in FAIXAS_ESFORCO:
        faixa = calib[(calib['real'] >= minimo) & (calib['real'] < maximo)]
        if len(faixa):
            cobertura[rotulo] = {
                'demandas': int(len(faixa)),
                'cobertura': round(float(faixa['dentro'].mean()), 3),
            }

    return multiplicadores, cobertura


# =====================================================================
# Execução completa
# =====================================================================

def executar() -> dict:
    """Treina, calibra, salva e ativa. Devolve tudo o que a tela mostra."""
    dataset = pipeline.montar_dataset()
    if len(dataset) < 30:
        raise ValueError(
            f'Apenas {len(dataset)} demandas no dataset. Importe mais dados '
            'antes de treinar: com base pequena a validação cruzada não '
            'produz estimativa confiável.'
        )

    X = dataset[FEATURES]
    y = dataset[ALVO]

    comparacao = comparar(X, y)

    final = modelo_final()
    final.fit(X, y)

    # Com dois preditores categóricos, o modelo emite um valor por
    # combinação existente. Vale listar todas: é o repertório completo
    # do que ele consegue responder.
    combinacoes = X.drop_duplicates().sort_values(FEATURES).reset_index(drop=True)
    combinacoes['previsao'] = final.predict(combinacoes).round(2)
    combinacoes = combinacoes.merge(
        X.groupby(FEATURES).size().rename('demandas'), on=FEATURES, how='left')

    multiplicadores, cobertura = calibrar(modelo_final(), X, y)

    PASTA_MODELOS.mkdir(parents=True, exist_ok=True)

    # A transação inteira numa conexão só: o índice parcial único exige
    # que a desativação do modelo anterior e a ativação do novo aconteçam
    # juntas. Se o joblib falhar ao gravar, nada é comitado.
    with db.conexao() as conexao:
        with conexao.cursor() as cursor:
            cursor.execute('update treinos set ativo = false where ativo')
            cursor.execute(
                """insert into treinos
                       (n_demandas, n_orcamentos, metricas, multiplicadores,
                        combinacoes, cobertura_por_faixa, caminho_modelo, ativo)
                   values (%s, %s, %s, %s, %s, %s, '', true)
                   returning id""",
                (int((dataset['origem'] == 'clockify').sum()),
                 int((dataset['origem'] == 'orcamento').sum()),
                 db.Json(comparacao.to_dict('records')),
                 db.Json(multiplicadores),
                 db.Json(combinacoes.to_dict('records')),
                 db.Json(cobertura)),
            )
            treino_id = cursor.fetchone()[0]

            caminho = PASTA_MODELOS / f'modelo_v{treino_id}.joblib'
            joblib.dump(final, caminho)

            cursor.execute('update treinos set caminho_modelo = %s where id = %s',
                           (str(caminho), treino_id))

    return {
        'treino_id': treino_id,
        'n_demandas': len(dataset),
        'comparacao': comparacao,
        'combinacoes': combinacoes,
        'multiplicadores': multiplicadores,
        'cobertura': cobertura,
        'caminho': str(caminho),
        'quando': datetime.now(),
    }
