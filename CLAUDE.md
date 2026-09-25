# Sobre o projeto

`the-bank-project`: pipeline de ML sobre o [Berka Dataset](https://www.kaggle.com/datasets/marceloventura/the-berka-dataset)
(dados financeiros de um banco tcheco), seguindo `architecture_diagram.png`:
Kaggle → Airflow → Data Lake Medallion → Feast → MLflow → FastAPI/Docker →
Prometheus/Grafana/Evidently, com re-treino por drift e CI/CD (GitHub Actions).

Fonte da verdade — não duplicar aqui:
- `README.md`: schema dos dados, Silver, Gold, modelos.
- `ROADMAP.md`: fases e status. **Checar antes de assumir que algo existe.**

Entidade do projeto: `account_id` (decisão de 2026-09-23, ver Fase 3 do ROADMAP);
a Gold (`gold_account`, `gold_account_monthly_movements`) já segue essa entidade.

# Comandos

Interface via Makefile (`make help`):

- Qualidade: `install`, `lint`, `format`, `typecheck`, `test`, `check` (= o que o CI roda), `hooks`, `clean`.
- Dados: `ingest` (Kaggle → Raw → Bronze), `silver`, `gold`, `features` (Feast apply + materialize).
- Modelo: `labels`, `train`, `promote` (gate do MLflow).
- Serving: `serve` (API + interface em :8000, local; precisa de `MLFLOW_TRACKING_URI` no `.env`).
- Infra Docker: `up`/`down` (Airflow :8080, MLflow :5000 e API :8000), `dag-check` (valida as DAGs na imagem do Airflow).

# Estilo de código

- `pandas<3` é obrigatório (o Feast exige); não atualizar sem checar o Feast. Acesso às features só por
  `the_bank_project.features`; definições do Feast em `feature_repo/features.py` (schema explícito + teste de contrato).
- Pacote em `src/the_bank_project/` (layout src); testes espelham o pacote em `tests/`.
- Type hints obrigatórios (mypy com `disallow_untyped_defs`); docstrings no formato Google.
- Config em `configs/*.yaml` validada via Pydantic (`the_bank_project.config`); segredos em `.env` (modelo em `.env.example`). Nada de paths hardcoded.
- Um step de pipeline = função pura + CLI, testável sem Airflow; DAGs só envolvem o código do pacote.
- Airflow roda só em imagem Docker própria (`docker/airflow/`), fora do `pyproject.toml`. O código do projeto
  roda num venv da imagem (`@task.external_python`) instalado pelo `poetry.lock`, não no ambiente do
  Airflow (cujos constraints fixam pandas 2.1/numpy 1.26). O decorator deve aparecer por extenso em cada task.
- Serving em `the_bank_project.serving` (`state` → `service`/`catalog`/`model_store` → `routes` → `app`): a API
  não lê a Gold; features só via `FeatureReader`. Interface em
  `serving/static/` sem build (JS puro, textos sempre via `textContent`). Imagens da API e do venv do Airflow
  instalam pelo `poetry.lock` (o modelo do MLflow é um pickle).
- Registry do MLflow por **aliases** (`challenger`/`champion`), não stages. Promoção só pelo gate (`make promote`).
- Nome de experimento/run no MLflow: `<etapa>_<modelo>_<data>`.
- Reutilizar bibliotecas reconhecidas em vez de reimplementar.

# Workflow

- Rodar `make check` após mudanças relevantes.
- Apenas o usuário faz commits; ao final de cada mudança, sugerir a mensagem em Conventional Commits (`feat:`, `fix:`, `chore:`, `docs:`, `experiment:`).
- Infra 100% local via Docker; não assumir cloud.
- Fim de fase: atualizar README, este arquivo e o status no ROADMAP.
