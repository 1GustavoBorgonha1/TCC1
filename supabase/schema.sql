-- =====================================================================
-- Sistema de Apoio à Estimativa de Esforço em Demandas de BI
-- Gustavo Borgonha — UNIDAVI 2026
--
-- Schema idempotente: pode rodar quantas vezes quiser sem estragar dados.
-- =====================================================================


-- Sessões do Clockify já filtradas (sem suporte, reunião, sem etiqueta e sem chamado).
-- usuario e descricao entram no hash que impede importar a mesma sessão duas vezes.
create table if not exists sessoes (
    id             bigserial primary key,
    hash_linha     char(64)         not null unique,
    numero_chamado text             not null,
    sistema        text,                        -- coluna "Project"
    tag            text,                        -- coluna "Tags"
    usuario        text,
    descricao      text,
    inicio         timestamp        not null,
    fim            timestamp        not null,
    duracao_horas  double precision not null check (duracao_horas > 0),
    importado_em   timestamptz      not null default now()
);


-- Log de cada importação: alimenta a etapa 2 da Pipeline.
create table if not exists importacoes (
    id                 bigserial primary key,
    criado_em          timestamptz not null default now(),
    arquivo            text    not null,
    linhas_lidas       integer not null,
    linhas_fora_escopo integer not null default 0,
    linhas_sem_chamado integer not null default 0,
    linhas_novas       integer not null default 0,
    linhas_duplicadas  integer not null default 0
);


-- Um registro por treino. multiplicadores, combinacoes e cobertura_por_faixa
-- não estão dentro do .joblib e são indispensáveis para estimar.
create table if not exists treinos (
    id                  serial primary key,
    criado_em           timestamptz not null default now(),
    n_demandas          integer     not null,           -- vindas do Clockify
    n_orcamentos        integer     not null default 0, -- orçamentos concluídos
    metricas            jsonb       not null,           -- erro na validação cruzada
    multiplicadores     jsonb       not null,           -- fatores da faixa por segmento
    combinacoes         jsonb       not null,           -- demandas por combinação
    cobertura_por_faixa jsonb       not null,           -- cobertura por faixa de esforço
    caminho_modelo      text        not null,           -- nome do .joblib em modelos/
    ativo               boolean     not null default false
);

-- O banco garante no máximo um treino ativo.
create unique index if not exists idx_treino_unico_ativo on treinos (ativo) where ativo;


-- Orçamentos: a estimativa congelada no registro e, ao concluir, as horas reais.
-- treino_id registra com qual modelo cada estimativa foi feita.
create table if not exists orcamentos (
    id             uuid primary key default gen_random_uuid(),
    criado_em      timestamptz not null default now(),
    numero_chamado text,
    tipo_projeto   integer not null,
    tipo_tarefa    integer not null,
    previsao_horas double precision not null,
    limite_inf     double precision not null,
    limite_sup     double precision not null,
    treino_id      integer references treinos (id),
    status         text not null default 'aberto'
                   check (status in ('aberto', 'concluido', 'cancelado')),
    horas_reais    double precision check (horas_reais > 0),
    concluido_em   timestamptz,
    constraint orcamento_concluido_tem_horas check (status <> 'concluido' or horas_reais is not null)
);
