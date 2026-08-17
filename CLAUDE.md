# CLAUDE.md — Sistema de Apoio à Estimativa de Esforço em Demandas de BI

## 1. Sobre o projeto

- **Título do TCC:** Sistema de Apoio à Estimativa de Esforço em Demandas de Business Intelligence Baseado em Dados Históricos e Regressão
- **Autor:** Gustavo Borgonha
- **Orientador:** Prof. Ademar Perfoll Junior
- **Instituição:** UNIDAVI — Sistemas da Informação, Rio do Sul, 2026
- **Problema de pesquisa:** Como modelos preditivos baseados em dados históricos podem contribuir para a precisão da estimativa de esforço em demandas de business intelligence desenvolvidas por pequenas empresas e profissionais independentes?

Resumo: o sistema vai receber dados históricos de demandas de BI (dashboards, reports, análises), treinar modelos de regressão sobre esses dados e usar o modelo treinado para estimar o esforço (horas/custo) de novas demandas — como apoio à orçamentação, não substituição do julgamento humano.

## 2. Objetivos

**Objetivo geral:**
Desenvolver um sistema web preditivo baseado em algoritmos de regressão e dados históricos para auxiliar na tomada de decisão e no controle de orçamentos de demandas de business intelligence.

**Objetivos específicos:**
1. Identificar dados históricos relacionados à demanda da área de dados.
2. Estruturar os dados históricos em um formato padronizado.
3. Mapear variáveis relevantes para a estimativa de esforço.
4. Implementar modelos de regressão para estimar o esforço das demandas.
5. Comparar o desempenho dos modelos treinados utilizando métricas quantitativas de erro (MAE, RMSE, etc.).
6. Elaborar uma interface web para cadastro, consulta e apoio à estimativa de novas demandas.
7. Avaliar se o modelo pode apoiar o processo de orçamentação em relação às estimativas feitas manualmente.

Use esta lista como bússola: qualquer funcionalidade proposta deve apontar para pelo menos um destes itens.

## 3. Regras de colaboração (fixas para todas as sessões neste projeto)

- **Claude nunca cria, edita ou executa nada além de ler arquivos e os dois arquivos de documentação listados abaixo.** Nada de terminal — nem comandos read-only. Todo código, comando de terminal, arquivo de configuração (`.gitignore`, `requirements.txt`, `package.json`, migrations, etc.) é **escrito e executado pelo Gustavo**, seguindo as instruções que o Claude fornece em texto no chat.
- **Os únicos arquivos que o Claude está autorizado a editar são o `CLAUDE.md` e o `FERRAMENTAS_PENDENTES.md`.** Todo o resto — se precisar existir — vem como instrução em texto (o que criar, com qual conteúdo, com quais comandos).
- **Papel do Claude: professor.** Prioriza explicar o raciocínio ("por que essa abordagem", "que problema isso resolve", "quais as alternativas e trade-offs") antes de dar a resposta pronta. Quando fizer sentido, faz perguntas para checar entendimento, propõe pequenos exercícios/desafios, e revisa o código que o Gustavo escrever apontando erros, riscos e melhorias — sem reescrevê-lo diretamente.
- Se o Gustavo pedir para o Claude "criar" ou "editar" algo que não seja o `CLAUDE.md`, a resposta correta é: atualizar o `CLAUDE.md` (se for informação estrutural do projeto) e/ou explicar passo a passo o que ele mesmo deve fazer.

## 4. Ferramentas permitidas (travadas pelo referencial teórico do TCC, cap. 2.4 e correlatos)

Só usar o que está listado abaixo. **Nenhuma ferramenta fora desta lista deve ser proposta** sem que antes seja incluída no referencial teórico do TCC (o PDF em `Dados\TCC_GustavoBorgonha_BSN 2026.pdf`) — isso inclui trocar de framework, adicionar Docker, adicionar outro banco de dados, etc. Se surgir necessidade real de algo fora da lista, o primeiro passo é discutir e atualizar o referencial teórico, não só o código.

| Camada | Ferramenta |
|---|---|
| Linguagem/backend/dados | Python + Pandas |
| Machine Learning | scikit-learn (Regressão Linear, Árvores de Decisão, Random Forest, SVR, Gradient Boosting) |
| Banco de dados | PostgreSQL |
| API | REST sobre HTTP/JSON |
| Frontend | Angular + TypeScript |
| Métricas de avaliação | MAE, RMSE, MdMRE, MMRE, R², PRED(25) |

**Ferramentas em uso que ainda não estão no referencial:** sempre que uma ferramenta fora da tabela acima entrar em uso, ela deve ser registrada em `Dados\FERRAMENTAS_PENDENTES.md` no mesmo momento — com o uso que faz dela e a justificativa. Esse arquivo é a lista de trabalho para atualizar o cap. 2 do TCC depois, em bloco. Registrar não substitui a atualização do referencial; só evita que algo entre em uso e seja esquecido.

## 5. Roadmap / fluxo de desenvolvimento (do capítulo de metodologia)

1. **Modelagem e estruturação dos dados históricos** (Python + PostgreSQL) — *em andamento, ver seção 6.*
2. Motor de ML (Python/Pandas/scikit-learn).
3. API REST.
4. Frontend (Angular/TypeScript).
5. Aplicação empírica em demandas reais de BI.
6. Análise quantitativa (MAE/RMSE) e qualitativa (interface, navegação, UX).
7. Refinamento da ferramenta e considerações finais.

## 6. Estado atual da Fase 1 (limpeza e estruturação dos dados)

**Ambiente:** git inicializado, `.gitignore` cobrindo `.claude/`, `CLAUDE.md`, `venv/`, os CSVs brutos do Clockify e o `mapeamento_privado.csv`. Ambiente virtual em `c:\TCC\venv` (Python 3.13), com pandas e ipykernel. Notebooks rodam pela extensão Jupyter do VS Code.

**Fonte dos dados:** exports "Detailed Time Report" do Clockify (plataforma de apontamento usada pelo Gustavo no trabalho), dois arquivos cobrindo 01/10/2025 a 07/08/2026 — 1630 sessões de cronômetro. Cada linha é uma sessão, não uma demanda; uma demanda é a soma das sessões que compartilham o mesmo número de chamado.

**Notebooks em `Passo1_Limpeza`, na ordem de execução:**

| Arquivo | O que faz | Saída |
|---|---|---|
| `01_mascarando_dados.ipynb` | Une os dois exports, filtra tags fora de escopo, extrai o nº do chamado da descrição via regex, cria IDs sintéticos (`S____`) para sessões sem chamado, anonimiza clientes/sistemas/chamados e nomes soltos em texto livre | `clockify_unificado_mascarado.csv` (1319 sessões) e `mapeamento_privado.csv` |
| `02_agrupamento.ipynb` | Converte datas para `datetime`, agrupa por chamado somando o esforço | `demandas.csv` (~300 demandas) |

**Semântica dos dados que não é óbvia pelo código:**
- `Cliente_012` (IBS Sistemas) **não é trabalho interno** — é o balde onde caem as demandas de clientes curva C, que não são registrados individualmente no Clockify. São demandas reais e orçadas; equivalem a uma categoria "Outros" já pronta (99 das 383 demandas).
- `Sistema_001` (IBS BI) **é** produto interno: 100% das suas demandas são sem chamado formal, nunca passam por orçamentação. Excluído do estudo.
- A tag `Orçamento` marca o tempo gasto lendo a demanda e estimando as horas — é meta-trabalho, não execução. Excluído do treino, mas o total (12 demandas) serve de linha de base do processo manual para o objetivo específico 7.

**Decisões de modelagem já tomadas (registrar na metodologia do TCC):**
- Sessões com tags `Suporte` e `Reunião`, e sessões sem tag, foram removidas.
- Sessões sem `#número` na descrição recebem um ID sintético baseado em cliente + projeto + descrição idênticos (premissa: mesma descrição = mesma demanda).
- No agrupamento, o dataframe é ordenado por duração decrescente antes do `groupby`, de modo que cliente/sistema/tag da demanda venham da **sessão mais longa** — critério usado para resolver os 3 chamados com valores divergentes entre sessões.
- `esforco_horas` (soma das durações) é a variável-alvo. **Não confundir com tempo decorrido** (`data_fim - data_inicio`), que inclui noites, fins de semana e trabalho em outras demandas.

**Alerta permanente sobre notebooks:** o kernel guarda estado entre execuções, então uma célula pode "funcionar" na tela e estar quebrada no arquivo. Três bugs desta base já vieram daí. Sempre **Restart Kernel → Run All** antes de confiar em qualquer resultado.

**Próximas etapas planejadas:** análise exploratória (`03_`), regras de inclusão — censura temporal, outliers, demandas sintéticas (`04_`), e engenharia de variáveis com remoção de vazamento de dados (`05_`), fechando o objetivo específico 3. A carga em PostgreSQL fica para depois do dataset estar pronto.
