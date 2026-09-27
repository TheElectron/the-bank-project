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
| 6    | Inferência via API (FastAPI + Docker)                           | 6                   | ✅     |
| 7    | Monitoramento e re-treino por drift (7a ✅, 7b ✅, 7c ✅)         | 7                   | ✅     |
| 8    | CD e fechamento                                                 | CI/CD               | ✅     |
| 9    | Ajustes e melhorias (9a tuning ✅, 9b interface ✅)              | 5, 6                | ✅     |

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
  própria imagem (`@task.external_python`), instalado pelo `poetry.lock`: as tasks usam as mesmas versões
  do dev, do CI e da API de serving (o modelo do MLflow é um pickle), não as fixadas pelos constraints do Airflow.
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
- A tabela cadastral (antes `gold_client`) passou a ter grão de conta, com os
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
- `FeatureService` por modelo (só a regressão de gastos; a
  classificação de inadimplência saiu do escopo).
- `feast apply` e `feast materialize` como tasks da DAG.
- Único ponto de acesso às features para treino e serving (nenhum outro
  módulo lê a Gold diretamente).

Implementado em `feature_repo/` (definições e `feature_store.yaml`) e
`src/the_bank_project/features/` (`store.py`, CLI `make features`); tasks
`feast_apply` e `feast_materialize` no fim da DAG. Decisões: Feast exige
`pandas<3`, então o projeto todo foi fixado em pandas 2.3 (2026-09-24); views sem
TTL (o offline store de arquivos descarta/quebra com TTL); materialização
completa em vez de incremental (dataset histórico). Só o FeatureService da
regressão existe (a inadimplência saiu do escopo), e `card_*`/`loan_*`
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

- O modelo de classificação de inadimplência (antiga Fase 5b) foi **removido do escopo** em 2026-09-25: o projeto
  cobre só a regressão de gastos do mês seguinte.

## Fase 6 — Inferência via API

- FastAPI com `/predict`, `/health` e `/metrics` (formato Prometheus).
- Schemas de entrada/saída em Pydantic.
- Modelo carregado do registry (alias `champion`); features lidas do online store do Feast.
- Dockerfile em `docker/serving/` e serviço no compose.

Implementado em `src/the_bank_project/serving/` (`app`, `service`, `catalog`, `model_store`,
`evaluation`, `metrics`, `schemas`, `feature_catalog`), a interface web em `serving/static/`
(HTML/CSS/JS sem build, gráficos em SVG próprio, fontes embutidas), `docker/serving/` e o serviço
`serving` no compose (:8000); `make serve` roda local. Além do `/predict` do escopo original:
modo histórico (`reference_month`) com valor real, `/api/*` de apoio à interface, avaliação no teste
inteiro recalculada com o campeão e recarga automática do campeão (polling do alias a cada 60 s).
Imagens da API e do venv do Airflow passaram a instalar pelo `poetry.lock` (o modelo é um pickle).

## Fase 7 — Monitoramento e re-treino

- Prometheus (scrape do `/metrics`) e Grafana (dashboards provisionados em `monitoring/`). A API já expõe
  requisições e latência por rota, previsões geradas, contas sem features, distribuição dos valores
  previstos e a versão do campeão (`model_info`).
- **Sub-fases:** 7a Prometheus + Grafana (✅) → 7b Evidently (✅) → 7c re-treino por drift (✅).
- **7a (implementada):** `prometheus` (:9090) e `grafana` (:3000) no compose; `monitoring/` com `prometheus.yml`,
  `alerts.yml` (5 alertas de infra, sem Alertmanager) e Grafana provisionado (datasource + dashboard "API de
  inferência"); `make monitoring-check` roda o `promtool`; `tests/monitoring/` garante que as métricas citadas existem.
- **7b (implementada):** Evidently, relatórios de drift de dados, gerados por task do Airflow (DAG `monitoring`).
  Decisões de 2026-09-25: o "dado atual" é um **replay temporal** (referência = meses de treino, atual = meses
  mais recentes da Gold, via `the_bank_project.features`); o resumo de drift chega ao Prometheus por
  **Pushgateway**; o painel de drift entra no dashboard nesta sub-fase.
  - **Dependência (feito, 2026-09-25):** `evidently>=0.7.23,<0.8` no grupo `monitoring` do `pyproject.toml`. Resolve
    sem conflito com `pandas<3`/Feast (só +30 pacotes, nenhuma versão existente mudou). Dev/CI e o venv do Airflow
    instalam o grupo (`--only main,monitoring`); a imagem da API não. Evidently envia telemetria de uso a menos que
    `DO_NOT_TRACK` esteja definida: desligar no código/compose.
  - **`drift.py` (feito, 2026-09-25):** `the_bank_project.monitoring` (função pura `compute_drift` + `run_drift` + CLI `make drift`),
    saída em `data/monitoring/` (HTML + JSON). Parâmetros: janela atual de 3 meses, Wasserstein > 0,1 por feature, drift no
    dataset com >= 50% das features. Nos dados reais: 12/29 (41%), sem drift, mas perto do limiar (ver README).
  - **DAG `monitoring` + Pushgateway + painel (feito, 2026-09-25):** DAG semanal `drift_report` → `publish_metrics`;
    Pushgateway (:9091, volume persistente) no compose; painel "Drift de dados" no dashboard e 2 alertas (`drift_detected`,
    relatório com mais de 8 dias). Validado ponta a ponta: run manual `success` (~8 min), `drift_share` = 0,41 no Prometheus.
- Performance real é **defasada** (o target só chega no mês seguinte); o drift
  de dados é o gatilho imediato.
- **7c (implementada e validada, 2026-09-25):** re-treino por drift. Decisão de 2026-09-25:
  `TriggerDagRunOperator` dentro da própria DAG `monitoring` (em vez da API do Airflow, que exigiria token JWT e
  uma chamada HTTP; a decisão já acontece nessa DAG) e cooldown de 14 dias.
  - `the_bank_project.monitoring.retrain`: função pura `should_retrain` (`retrain`/`no_drift`/`cooldown`/`disabled`),
    estado em `data/monitoring/last_retrain.json` (gravado na decisão) e `make retrain-check` (dry run).
  - DAG: `drift_report → decide_retrain → (publish_metrics | retrain_needed → trigger_training)`; a `training`
    precisa estar ativa. O `promote` da `training` é o gate da Fase 5.
  - Config `monitoring`: `retrain_enabled` (true) e `retrain_cooldown_days` (14). Métrica
    `retrain_last_timestamp_seconds` e painel "Último re-treino por drift" no Grafana.
  - 12 testes novos (`tests/monitoring/test_retrain.py`); `make check` com 221 testes.
  - **Limite conhecido:** com o dataset estático, re-treinar reproduz o mesmo modelo e o gate deve mantê-lo; a fase
    valida o mecanismo, não um ganho de desempenho.
  - **Validação ponta a ponta (feita):** com `drift_share_threshold` = 0,3, o 1º run disparou a `training` (gate
    rejeitou o challenger v3, MAE igual ao do campeão v1, que foi mantido) e o 2º foi bloqueado pelo cooldown
    (`trigger_training` skipped, nenhum novo run). Config e estado restaurados; a v3 segue como `challenger` no Registry.

## Fase 8 — CD e fechamento

- **Implementada (2026-09-25) e validada no GitHub (2026-09-26):** o 1º run do `cd.yml` (commit `23b8132`, após o CI
  verde) construiu, testou e publicou as 3 imagens (`airflow` ~6 min, `serving` e `mlflow` ~2 min); as tags `latest` e
  `sha-23b8132` existem no GHCR. Sem cloud, "deploy" = publicar as imagens no GHCR e subir o compose local.
- `.github/workflows/cd.yml`: dispara por `workflow_run` do CI em `master` (só se `conclusion == 'success'`) e por
  `workflow_dispatch`. Matrix `airflow | mlflow | serving`: build (cache do GHA) → smoke test → push para
  `ghcr.io/<dono>/the-bank-project-<imagem>` com as tags `sha-<curto>` e `latest`. O push só acontece depois do smoke.
- `scripts/smoke_image.sh`: o essencial de cada imagem importa/sobe (Airflow: `the_bank_project` e `evidently` no venv;
  MLflow: `--version`; API: `import the_bank_project.serving`). Não sobe a stack: a API precisa da Gold e do Feast, que
  não existem num runner de CI (o `dag-check` do CI já cobre as DAGs).
- `docker-compose.ghcr.yml`: override que troca `build` pelas imagens do GHCR
  (`docker compose -f docker-compose.yml -f docker-compose.ghcr.yml up -d`; `GHCR_OWNER`, `IMAGE_TAG`). `make up`
  continua construindo localmente.
- `make cd-check`: valida o override (`docker compose config`) e roda o smoke nas imagens locais.
- `tests/cd/`: contrato entre a matrix, os `Dockerfile`, o compose, o override e o smoke script (12 testes).
- Decisões: `workflow_run` (não `push`, que publicaria com CI vermelho); GHCR com `GITHUB_TOKEN`, sem segredos
  novos; pacotes nascem privados (torná-los públicos é decisão do dono); sem Trivy.
- **Override validado (2026-09-26):** `docker compose -f docker-compose.yml -f docker-compose.ghcr.yml pull` + `up -d`
  com as imagens baixadas do GHCR: API saudável (campeão v1, 4.500 contas) e uma previsão real em `/predict`, MLflow
  `OK`, Airflow saudável com as 3 DAGs sem erros de import. O pull precisou de uma nova tentativa (reset de conexão).
- **Revisão final (feita, 2026-09-25):** README, `CLAUDE.md` e este roadmap refletem o estado real; a Fase 5b saiu do
  escopo. Limites conhecidos: o dataset é estático (o re-treino por drift valida o mecanismo, não um ganho de
  desempenho); sem Alertmanager; sem autenticação na API (projeto local).

## Fase 9 — Ajustes e melhorias

Fase pós-entrega: melhora o que já existe sem mudar a arquitetura. **9a** tuning de hiperparâmetros; **9b** layout e
informações da interface (a 9b não depende da 9a).

### 9a — Tuning de hiperparâmetros (✅ implementada e executada, 2026-09-26)

- **Situação anterior:** configuração padrão + 8 sorteios aleatórios por modelo, escolhidos pelo MAE de **uma única**
  janela de validação. Os 3 melhores modelos estavam a 2,5% um do outro no MAE de teste.
- **Fluxo:** `make tune` (Optuna/TPE + validação cruzada temporal) grava `configs/best_params.yaml`; o `train` usa esse
  arquivo no lugar do sorteio simples (com fallback para o sorteio se o arquivo não existir). O gate da Fase 5 não muda.
- **Decisões (2026-09-26):**
  - Optuna no grupo `tuning` do Poetry (só dev/CI). O treino em produção lê o YAML e não importa o Optuna, então as
    imagens (Airflow, API) não mudam.
  - Dobras de janela expansiva por mês (`the_bank_project.training.cv`), **só dentro dos meses de treino**, com o
    `gap_months` do split. Desvio em relação ao plano inicial (treino+validação): usar a validação no tuning
    enviesaria a escolha do campeão entre os algoritmos, que é feita justamente por ela. O teste segue intocado.
  - Cada modelo compara o melhor achado com a configuração **padrão nas mesmas dobras**; se nada a bate, fica a padrão
    (`source: default`), então o tuning nunca piora o CV.
  - Orçamento: 30 tentativas, 4 dobras e teto de 20 min por modelo (`tuning` em `global_config.yaml`). Reduzido do
    plano (40) porque cada tentativa são 4 ajustes; tentativas em sequência, sem paralelismo.
  - Regressão linear fora do tuning (sem hiperparâmetros relevantes).
  - MLflow: run `tuning_<modelo>_<data>` com as tentativas aninhadas; o `train` marca `params_source` (`tuned` ou
    `random_search`) em cada run.
- **Implementação:** `training/cv.py`, `tuned_params.py` (schema + leitura/escrita, sem Optuna), `tuning.py`, espaços
  `tune_space` em `models.py`, passo `tune` no CLI e `make tune`; testes em `tests/training/`.
- **Resultado (execução real, ~35 min):** o CV melhorou 0,6% (RF), 0,4% (Gradient Boosting) e 1,0% (XGBoost), mas no
  teste o efeito ficou entre −0,5% e +0,2%, dentro do ruído. O challenger v4 (RF ajustado, MAE de teste 6.492) **perdeu
  no gate** para o campeão v1 (6.478), que foi mantido. O RF parou em 13 tentativas pelo teto de 20 min. Conclusão: o
  erro é limitado pelas features, não pelos hiperparâmetros; melhorias maiores tendem a vir de features. Detalhes e
  tabela no README ("Tuning de hiperparâmetros").
- `configs/best_params.yaml` foi mantido (o CV, que é o critério do tuning, melhorou nos três). Apagá-lo devolve o
  `train` ao sorteio simples.

### 9b — Layout e informações da interface (✅ implementada, 2026-09-26)

- **Escolhas do usuário (2026-09-26):** informações novas = cartão do modelo, importância das features, erro por faixa
  de gasto e status de monitoramento; visual = reorganizar mantendo a identidade (livro-razão editorial, Fraunces +
  Hanken Grotesk, mesmas cores de série). Estrutura de página não respondida: adotada a recomendada (página única com
  navegação fixa).
- **Layout:** cabeçalho fixo com âncoras e destaque da seção visível (`IntersectionObserver`); seções numeradas
  (01 Visão geral, 02 Modelo, 03 Laboratório, 04 Desempenho); seções que dependem de dados ficam ocultas até eles chegarem;
  responsivo (nav rolável no celular). Continua JS puro, sem build, textos via `textContent`.
- **Seção Modelo (nova, `static/js/model_panel.js`):** cartão do modelo, importância das features (top 10 + por grupo, com
  tabela equivalente em `<details>`) e saúde dos dados (drift: 12 de 29 = 41% contra o limite de 50%, features que mais
  mudaram, janelas, último re-treino). O `renderModelSection` recebe `null` no monitoramento sem quebrar.
- **Desempenho:** novo cartão "Erro por faixa de gasto"; os gráficos de barras passaram a usar `pairedBars` (mesmo
  código para mês e faixa). Na base real o modelo bate a média de 3 meses nas 5 faixas, e o maior erro absoluto está
  acima de 50 mil (34.350 Kč, 1.035 contas-mês).
- **Backend (aditivo, `POST /predict` intacto):** `ModelInfo` ganhou `params`, `params_source` e `trained_at`;
  `EvaluationReport.by_band` (`error_by_band`, faixas fixas em `evaluation.py`); `GET /api/monitoring`
  (`serving/monitoring_status.py`, lê `drift_summary.json` e `last_retrain.json`); o compose monta `data/monitoring`
  somente leitura na API.
- **Bug encontrado e corrigido no caminho:** o comparativo de modelos usava "o run mais recente de cada um" na mesma
  janela de teste, então o challenger v4 (rejeitado pelo gate) apareceu com os números do campeão v1 (6.492 no gráfico
  contra 6.478 no cartão). Agora só entram runs a até 3 h do run do campeão (`SAME_TRAINING_HOURS`), com teste de regressão.
- **Verificação:** capturas com Chromium headless em desktop e celular (tema claro). **O tema escuro não foi
  confirmado visualmente**; o CSS novo só usa variáveis que já têm valor no escuro.
- **Testes:** `tests/serving/` (endpoint de monitoramento com arquivo ausente, presente e corrompido, faixas de erro,
  parâmetros do modelo, comparativo). A interface em si (JS) não tem teste automatizado além do carregamento dos assets.
- **Para ver a interface nova no Docker:** reconstruir a imagem da API e recriar o serviço (o compose ganhou o volume
  `data/monitoring`); o CD do GHCR também as publica no próximo push.
