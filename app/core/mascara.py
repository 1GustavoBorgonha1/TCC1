import pandas as pd

from . import db

PREFIXOS = {
    'cliente': 'Cliente',
    'sistema': 'Sistema',
    'chamado': 'Chamado',
}


def obter_mapa(tipo: str) -> dict[str, str]:
    tabela = db.consultar(
        'select valor_real, valor_mascarado from mascaramento where tipo = %s',
        (tipo,),
    )
    if tabela.empty:
        return {}
    return dict(zip(tabela['valor_real'], tabela['valor_mascarado']))


def registrar_novos(tipo: str, valores) -> int:
    if tipo not in PREFIXOS:
        raise ValueError(f'Tipo desconhecido: {tipo}')

    conhecidos = obter_mapa(tipo)
    limpos = {str(v).strip() for v in valores if pd.notna(v) and str(v).strip()}
    novos = sorted(limpos - conhecidos.keys())
    if not novos:
        return 0

    # Continua a numeração de onde parou, sem reaproveitar códigos.
    ultimo = db.escalar(
        'select count(*) from mascaramento where tipo = %s', (tipo,)
    ) or 0

    prefixo = PREFIXOS[tipo]
    linhas = []
    for i, valor in enumerate(novos, start=1):
        codigo = f'{prefixo}_{ultimo + i:03d}'
        linhas.append((tipo, valor, codigo))


    db.executar_lote(
        """insert into mascaramento (tipo, valor_real, valor_mascarado)
           values %s
           on conflict (tipo, valor_real) do nothing""",
        linhas,
    )
    return len(linhas)

#Troca nomes reais pelos códigos mascarados nas colunas indicadas
def aplicar(df: pd.DataFrame, colunas_por_tipo: dict[str, str]) -> pd.DataFrame:
    saida = df.copy()
    for tipo, coluna in colunas_por_tipo.items():
        if coluna not in saida.columns:
            continue
        mapa = obter_mapa(tipo)
        saida[coluna] = saida[coluna].map(lambda v: mapa.get(str(v).strip(), '—'))
    return saida
