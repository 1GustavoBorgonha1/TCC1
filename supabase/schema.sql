-- =====================================================================
-- Sistema de Apoio à Estimativa de Esforço em Demandas de BI
-- Gustavo Borgonha — UNIDAVI 2026
--
-- Schema idempotente: pode rodar quantas vezes quiser sem estragar dados.
-- A ordem das tabelas respeita as chaves estrangeiras.
-- =====================================================================


-- ---------------------------------------------------------------------
-- 1. TABELAS DE DOMÍNIO
-- Traduzem o texto livre do Clockify nos códigos que o modelo consome.
-- São editáveis pela aplicação: nome novo no Clockify não quebra nada,
-- só fica pendente de mapeamento até alguém decidir o código.
-- ---------------------------------------------------------------------

create table if not exists tipos_projeto (
    nome_clockify text    primary key,          -- valor exato da coluna "Project"
    codigo        integer not null,      -- o que entra no modelo
    rotulo        text    not null              -- o que o usuário lê na tela
);

create table if not exists tipos_tarefa (
    nome_clockify text    primary key,          -- valor exato da coluna "Tags"
    codigo        integer not null,
    rotulo        text    not null
);


-- ---------------------------------------------------------------------
-- 2. SESSOES — grão bruto do Clockify, uma linha por apontamento
-- Reproduz as células 3 a 9 do notebook, já com os filtros de escopo
-- aplicados (sem Suporte/Reunião, sem sessão sem chamado formal).
-- ---------------------------------------------------------------------

create table if not exists sessoes (
    id             bigserial primary key,
    hash_linha     char(64)  not null unique,   -- SHA-256: impede reimportação duplicada
    numero_chamado text      not null,
    cliente        text,                        -- coluna "Client"
    sistema        text,                        -- coluna "Project"
    tag            text,                        -- coluna "Tags"
    billable       boolean,
    usuario        text,
    descricao      text,
    inicio         timestamp        not null,
    fim            timestamp        not null,
    duracao_horas  double precision not null check (duracao_horas > 0),
    arquivo_origem text,
    importado_em   timestamptz      not null default now()
);

-- O agrupamento da Parte 2 do notebook faz groupby por chamado; este índice
-- é o que sustenta essa consulta.
create index if not exists idx_sessoes_chamado on sessoes (numero_chamado);


-- ---------------------------------------------------------------------
-- 3. DEMANDAS — sessões agrupadas por chamado (Parte 2) com o resultado
-- das regras de inclusão (Parte 4) gravado em vez de aplicado por
-- exclusão de linha. Assim a aplicação consegue exibir o funil inteiro.
-- ---------------------------------------------------------------------

create table if not exists demandas (
    numero_chamado  text primary key,
    cliente         text,
    sistema         text,
    tag             text,
    billable        boolean,
    data_inicio     timestamp,
    data_fim        timestamp,
    esforco_horas   double precision not null check (esforco_horas > 0),
    qtd_sessoes     integer          not null,

    -- Resultado automático das regras: recalculado a cada importação
    incluida        boolean not null default true,
    motivo_exclusao text,

    -- Decisão humana: sobrevive ao recálculo. Substitui o 'Chamado_142'
    -- que estava fixo no código da célula 83.
    excluida_manual boolean not null default false,

    recalculado_em  timestamptz not null default now()
);

create index if not exists idx_demandas_incluida on demandas (incluida);


-- ---------------------------------------------------------------------
-- 4. TREINOS — um registro por clique no botão de treinar
-- Os JSONs aqui não são luxo: 'multiplicadores' e 'combinacoes' são
-- indispensáveis para estimar e NÃO estão dentro do .joblib. Hoje eles
-- só existem como variáveis vivas do kernel do Jupyter.
-- ---------------------------------------------------------------------

create table if not exists treinos (
    id                  serial primary key,
    criado_em           timestamptz not null default now(),
    n_demandas          integer     not null,   -- vindas do Clockify
    n_orcamentos        integer     not null default 0,  -- realimentados pela página 2
    metricas            jsonb       not null,   -- MAE/RMSE/R2/MMRE/MdMRE/PRED25 por modelo
    multiplicadores     jsonb       not null,   -- fator_min/fator_max por segmento (célula 132)
    combinacoes         jsonb       not null,   -- previsão + base histórica por combinação
    cobertura_por_faixa jsonb       not null,   -- cobertura efetiva (célula 134)
    caminho_modelo      text        not null,
    ativo               boolean     not null default false
);

-- Índice parcial único: o banco garante que existe no máximo UM treino ativo.
-- Não dá para ter dois modelos em produção por descuido.
create unique index if not exists idx_treino_unico_ativo
    on treinos (ativo) where ativo;


-- ---------------------------------------------------------------------
-- 5. ORCAMENTOS — páginas 1 e 2
-- O treino_id registra com QUAL modelo cada estimativa foi feita. Sem
-- isso, você não consegue defender a acurácia medida depois.
-- ---------------------------------------------------------------------

create table if not exists orcamentos (
    id             uuid primary key default gen_random_uuid(),
    criado_em      timestamptz not null default now(),

    -- Registro: aparecem na tela, NÃO entram no modelo
    cliente        text,
    sistema        text,
    descricao      text,

    -- Os dois únicos preditores do modelo final (célula 130)
    tipo_projeto   integer not null,
    tipo_tarefa    integer not null,

    -- Saída da estimativa, congelada no momento do registro
    previsao_horas double precision not null,
    limite_inf     double precision not null,
    limite_sup     double precision not null,
    base_historica integer not null default 0,
    ressalvas      jsonb   not null default '[]'::jsonb,
    treino_id      integer references treinos (id),

    -- Preenchido na página 2, quando a demanda termina
    status         text not null default 'aberto'
                   check (status in ('aberto', 'concluido', 'cancelado')),
    horas_reais    double precision check (horas_reais > 0),
    numero_chamado text,
    concluido_em   timestamptz,

    -- Concluído sem horas reais é dado inútil: o banco recusa.
    constraint orcamento_concluido_tem_horas check (
        status <> 'concluido' or horas_reais is not null
    )
);

create index if not exists idx_orcamentos_status on orcamentos (status);


-- ---------------------------------------------------------------------
-- 6. MASCARAMENTO — sustenta o botão de anonimizar da interface
-- Append-only e estável: uma vez que 'Adesul' virou 'Cliente_011', ele
-- continua Cliente_011 em toda importação futura. Sem isso, a mesma
-- empresa trocaria de código a cada import e o TCC perderia rastreio.
-- ---------------------------------------------------------------------

create table if not exists mascaramento (
    id              bigserial primary key,
    tipo            text not null check (tipo in ('cliente', 'sistema', 'chamado')),
    valor_real      text not null,
    valor_mascarado text not null,
    criado_em       timestamptz not null default now(),
    unique (tipo, valor_real),
    unique (tipo, valor_mascarado)
);


-- ---------------------------------------------------------------------
-- 7. IMPORTACOES — log de cada upload
-- As três contagens de descarte reproduzem o funil da célula 7, que é
-- resultado citado no texto do TCC.
-- ---------------------------------------------------------------------

create table if not exists importacoes (
    id                 bigserial primary key,
    criado_em          timestamptz not null default now(),
    arquivo            text    not null,
    linhas_lidas       integer not null,
    linhas_fora_escopo integer not null default 0,  -- tag Suporte/Reunião ou nula
    linhas_sem_chamado integer not null default 0,  -- sem número formal na descrição
    linhas_novas       integer not null default 0,
    linhas_duplicadas  integer not null default 0
);


-- ---------------------------------------------------------------------
-- 8. CARGA INICIAL DOS DOMÍNIOS
-- Os códigos vêm das células 96 e 136. Repare que 'WBI' é o nome no
-- Clockify e 'Relatório de Sistema' é o rótulo: no notebook essas duas
-- coisas divergiam entre as células e ninguém percebia.
-- ---------------------------------------------------------------------

insert into tipos_projeto (nome_clockify, codigo, rotulo) values
    ('Power BI', 1, 'BI (Power BI)'),
    ('PowerBI',  1, 'BI (Power BI)'),  
    ('WBI',      2, 'Relatório de Sistema')
on conflict (nome_clockify) do nothing;

insert into tipos_tarefa (nome_clockify, codigo, rotulo) values
    ('Nova Funcionalidade', 1, 'Nova Funcionalidade'),
    ('Alteração',           2, 'Alteração'),
    ('Análise de problema', 3, 'Análise de problema')
on conflict (nome_clockify) do nothing;
