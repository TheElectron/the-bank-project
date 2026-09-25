# Roadmap

Plano de implementação do `the-bank-project`, alinhado ao
`architecture_diagram.png` (7 estágios + CI/CD). O racional dos dados e dos
modelos está no [README](README.md); aqui ficam o **escopo e a ordem** de cada fase.

Legenda: ⬜ não iniciada · 🚧 em andamento · ✅ concluída

| Fase | Conteúdo                                                        | Estágio do diagrama | Status |
| ---- | --------------------------------------------------------------- | ------------------- | ------ |
| 0    | Esqueleto do projeto, ambiente e CI mínimo                      | CI/CD               | ✅     |
| 1a   | Ingestão Kaggle → Raw → Bronze                                  | 1, 3                | ✅     |
| 1b   | Airflow (imagem própria + compose) e DAG de ingestão            | 2                   | ✅     |
| 2    | Bronze → Silver                                                 | 3                   | ✅     |
| 3    | Silver → Gold                                                   | 3                   | ✅     |
| 4    | Feature Store (Feast)                                           | 4                   | ✅     |
| 5    | Treino, validação e ciclo de vida dos modelos (MLflow)          | 5                   | ✅     |
| 6    | Inferência via API (FastAPI + Docker)                           | 6                   | ⬜     |
| 7    | Monitoramento e re-treino por drift                             | 7                   | ⬜     |
| 8    | CD e fechamento                                                 | CI/CD               | ⬜     |

## Princípios

- **Definição de pronto (toda fase):** testes, `ruff` e `mypy` verdes; DAG do
  Airflow estendida quando a fase produz um novo passo do pipeline; README e
  `CLAUDE.md` atualizados.
- **Airflow cresce junto com o pipeline:** o código de cada fase nasce como
  função pura + CLI, testável sem Airflow; a DAG só o envolve. Cada task é
  idempotente e não trafega dados pelo XCom (só paths).
- **Infra 100% local via Docker:** nenhum recurso de cloud é assumido. O
  `docker-compose.yml` da raiz cresce por fase.
- **Dependências isoladas:** o Airflow roda só em imagem Docker própria
  (`docker/airflow/`), instalado com os *constraints* oficiais, fora do
  `pyproject.toml`, para evitar conflito com Feast/MLflow/Evidently. O código do projeto roda num venv da
  própria imagem (`@task.external_python`), com as dependências do `pyproject.toml`: assim
  as tasks usam as mesmas versões do dev/CI, não as fixadas pelos constraints do Airflow.
- **Config tipada:** `configs/*.yaml` carregados via Pydantic; nada de paths ou
  credenciais hardcoded (`.env` para segredos, com `.env.example` versionado).
- **Entidade do projeto é `account_id`** (decisão de 2026-09-23): ver Fase 3.

---

## Fase 0 — Esqueleto do projeto

Estrutura de pastas, ambiente e CI mínimo.

```
the-bank-project/
├── .claude/                  # Configuração do Claude Code
├── .github/workflows/
│   ├── ci.yml                # Lint, type check e testes (criado já na Fase 0)
│   └── cd.yml                # Build/deploy (Fase 8)
├── airflow/dags/             # DAGs (Fase 1b em diante)
├── configs/
│   ├── global_config.yaml    # Parâmetros gerais (carregados via Pydantic)
│   └── logger.yaml           # Configuração de logs
├── data/                     # Ignorado pelo git (mantém só .gitkeep)
│   ├── raw/                  # Dados originais, imutáveis
│   ├── bronze/               # .parquet, cópia 1:1 do raw
│   ├── silver/               # Limpos, tratados e reestruturados
│   └── gold/                 # Prontos para consumo
├── docker/                   # Dockerfiles (airflow/, serving/ ...)
├── feature_repo/             # Repositório Feast (Fase 4)
├── monitoring/               # Configs Prometheus e Grafana (Fase 7)
├── notebooks/                # Exploração; nada aqui é dependência de produção
├── scripts/                  # Utilitários que não cabem como CLI do pacote
├── src/the_bank_project/     # Pacote Python principal (layout src)
├── tests/                    # pytest, espelhando o pacote
├── .env.example              # Modelo de variáveis (credenciais do Kaggle etc.)
├── .gitignore
├── .pre-commit-config.yaml
├── CLAUDE.md                 # Reescrito para a nova estrutura
├── docker-compose.yml        # Cresce a cada fase
├── Makefile                  # Interface: make install / test / lint / ingest ...
├── pyproject.toml            # Poetry: grupos dev, ml, serving (sem Airflow)
├── README.md
└── ROADMAP.md
```

Entregas:
- `pyproject.toml` (Poetry, Python fixado, grupos de dependência), `ruff`, `mypy`, `pytest`.
- `.gitignore`: `data/*` (exceto `.gitkeep`), `.env`, `mlruns/`, `*.db`,
  registry/online store do Feast, caches, `.venv`.
- `global_config.yaml` + `BaseSettings` (Pydantic) e `logger.yaml`.
- `ci.yml` mínimo (ruff + mypy + pytest) e `pre-commit`.
- Makefile como interface dos comandos recorrentes.

Fechamento: o nome do pacote (`the_bank_project`) e o Makefile estão no
lugar; o `CLAUDE.md` novo substitui o antigo.

## Fase 1a — Ingestão Kaggle → Raw → Bronze

- Download do dataset via API do Kaggle para `data/raw/` (credenciais via `.env`).
- Conversão dos `.csv` para `.parquet` em `data/bronze/`, **cópia 1:1 sem inferência de tipo**.
- Funções por camada (`download`, `to_bronze`); no máximo uma classe pequena de
  acesso a paths/storage, vinda da config. **Sem `DataManager` centralizador**
  (evita God class e dificulta o mapeamento em tasks).
- Idempotente: reexecutar não corrompe nem duplica.
- Testes com dados sintéticos pequenos (sem depender do Kaggle).

## Fase 1b — Airflow

- `docker/airflow/` (imagem própria, *constraints* oficiais) e serviços no `docker-compose.yml`.
- DAG `data_pipeline` (`download` → `to_bronze`, depois `to_silver`) chamando o código do pacote.
- Convenção: uma task por passo, idempotente, sem dados no XCom.

## Fase 2 — Bronze → Silver

Descrito em detalhes no README ("Camada Silver"): tipagem, nulos, tradução de
categóricas e reorganização 8 → 5 tabelas (`district`, `client`, `account`,
`order`, `trans`).

- As validações 1:1 dos merges (hoje manuais no README) viram **testes/checks
  automatizados** (chaves únicas, integridade referencial).
- Task adicionada à DAG.

Implementado em `src/the_bank_project/silver/` (`transform.py` puro, `checks.py`,
CLI `make silver`). Os merges usam `validate="1:1"` do pandas e `check_silver`
cobre PKs, FKs, 1 titular por conta e cartão só em titular; nada é gravado se
uma regra falhar. Categóricas traduzidas para rótulos em português; `""`, `" "`
e `"?"` viram nulo; código fora do mapa de tradução é erro.

## Fase 3 — Silver → Gold

Descrito em detalhes no README ("Camada Gold"), **com a mudança de entidade**:

- **`account_id` como entidade** da tabela mensal (e do Feast). Motivo: 5.369
  clientes para 4.500 contas — ~869 dependentes teriam a mesma série temporal
  e o mesmo target do titular, duplicando observações e enviesando as métricas.
- A tabela cadastral (hoje `gold_client`) passa a ter grão de conta, com os
  atributos do titular. Renomear as tabelas (`gold_client` →
  `gold_account`, `gold_client_monthly_movements` →
  `gold_account_monthly_movements`) e **atualizar o README** junto com a fase.
- **Timestamps para o Feast:** `reference_month` é o `event_timestamp` da
  tabela mensal; a cadastral recebe um timestamp explícito (ex.: data de
  criação da conta).
- Features com janela usam só informação até o mês de referência
  (anti-vazamento). O target **não** entra na Gold.
- Validações: PK única, sem `NaN` onde não deve haver, consistência das
  janelas. Task adicionada à DAG.

Implementado em `src/the_bank_project/gold/` (`account.py`, `monthly.py`,
`checks.py`, CLI `make gold`); tabelas em `data/gold/gold_account.parquet` e
`gold_account_monthly_movements.parquet`. Decisões: `reference_month` é o último
dia do mês; meses sem movimento entram com fluxo 0; saldo de abertura/fechamento
resolvido pela cadeia de `balance` (o `trans_id` não ordena dentro do dia).
O README foi atualizado junto (seção "Camada Gold").

## Fase 4 — Feature Store (Feast)

- `feature_repo/` com `feature_store.yaml`, entidade `account_id` e 2
  `FeatureView`s (cadastral e mensal).
- Offline store em parquet (`data/gold/`); online store SQLite local.
- `FeatureService` por modelo (regressão de gastos; classificação de
  inadimplência terá views/labels próprios).
- `feast apply` e `feast materialize` como tasks da DAG.
- Único ponto de acesso às features para treino e serving (nenhum outro
  módulo lê a Gold diretamente).

Implementado em `feature_repo/` (definições e `feature_store.yaml`) e
`src/the_bank_project/features/` (`store.py`, CLI `make features`); tasks
`feast_apply` e `feast_materialize` no fim da DAG. Decisões: Feast exige
`pandas<3`, então o projeto todo foi fixado em pandas 2.3 (2026-09-24); views sem
TTL (o offline store de arquivos descarta/quebra com TTL); materialização
completa em vez de incremental (dataset histórico). Só o FeatureService da
regressão existe; o da inadimplência vem com o modelo (Fase 5), e `card_*`/`loan_*`
precisam ser mascarados pela própria data antes de virar feature.

## Fase 5 — Treino, validação e ciclo de vida (MLflow)

- MLflow no compose (backend SQLite ou Postgres, artefatos em volume).
- **Montagem dos labels:** tabela de labels (entidade + timestamp + target)
  e `get_historical_features` com *point-in-time join*. `next_month_outflow`
  = `outflow_amount(T+1)`; o último mês de cada conta não tem target e é descartado.
- Divisão cronológica 70/20/10; validação temporal.
- Modelos: Regressão Linear (baseline) → Random Forest → Gradient Boosting →
  XGBoost; métricas MAE, RMSE e R², **as mesmas em todos os runs**.
- Nome de experimentos/runs: `<etapa>_<modelo>_<data>`.
- Registry com **aliases** (`champion`/`challenger`) — a decisão anterior
  de usar `stage` será revisitada por a API de stages estar depreciada.
- **Gate de promoção:** o challenger só vira campeão se superar o atual.

Implementado em `src/the_bank_project/training/` (`labels`, `dataset`, `split`,
`models`, `evaluate`, `train`, `registry`, `tracking`; CLI `make labels|train|promote`),
`docker/mlflow/` (servidor no compose) e a DAG `training` (`train` → `promote`); a
task `to_labels` entrou na `data_pipeline`. Decisões: aliases (não stages); corte por
mês com 1 mês de folga; 2 baselines ingênuos; log1p no alvo exceto na regressão
linear; gate estrito reavaliando os dois modelos no mesmo teste. Resultado e
ressalvas no README ("Modelo de regressão").

- **Fase 5b (fora do caminho crítico):** modelo de classificação de
  inadimplência (TBD no README): definir label, features e métricas antes de implementar.

## Fase 6 — Inferência via API

- FastAPI com `/predict`, `/health` e `/metrics` (formato Prometheus).
- Schemas de entrada/saída em Pydantic.
- Modelo carregado do registry (alias `champion`); features lidas do online store do Feast.
- Dockerfile em `docker/serving/` e serviço no compose.

## Fase 7 — Monitoramento e re-treino

- Prometheus (scrape do `/metrics`) e Grafana (dashboards provisionados em `monitoring/`).
- Evidently: relatórios de drift de dados, gerados por task do Airflow.
- Performance real é **defasada** (o target só chega no mês seguinte); o drift
  de dados é o gatilho imediato.
- Re-treino: o alerta de drift dispara a DAG de treino via API do Airflow,
  com *cooldown* para evitar loops, e passa pelo mesmo gate de promoção da Fase 5.

## Fase 8 — CD e fechamento

- `cd.yml`: build e push das imagens (ex.: GHCR) e `docker compose up` local.
  Sem cloud, "deploy" significa isso; redefinir aqui se isso mudar.
- Revisão final: README, `CLAUDE.md` e este roadmap refletindo o estado real.
