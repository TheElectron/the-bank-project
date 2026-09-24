# Sobre o projeto

`the-bank-project`: pipeline de ML sobre o [Berka Dataset](https://www.kaggle.com/datasets/marceloventura/the-berka-dataset)
(dados financeiros de um banco tcheco), seguindo `architecture_diagram.png`:
Kaggle → Airflow → Data Lake Medallion → Feast → MLflow → FastAPI/Docker →
Prometheus/Grafana/Evidently, com re-treino por drift e CI/CD (GitHub Actions).

Fonte da verdade — não duplicar aqui:
- `README.md`: schema dos dados, Silver, Gold, modelos.
- `ROADMAP.md`: fases e status. **Checar antes de assumir que algo existe.**

Entidade do projeto: `account_id` (decisão de 2026-09-23, ver Fase 3 do ROADMAP).
O README ainda descreve a Gold por `client_id` até a Fase 3 atualizá-lo.

# Comandos

Interface via Makefile (`make help`): `install`, `lint`, `format`, `typecheck`,
`test`, `check` (= o que o CI roda), `hooks`, `ingest` (Kaggle → Raw → Bronze),
`up`/`down` (Airflow em Docker, UI em localhost:8080), `dag-check` (valida as DAGs
na imagem do Airflow), `clean`.

# Estilo de código

- Pacote em `src/the_bank_project/` (layout src); testes espelham o pacote em `tests/`.
- Type hints obrigatórios (mypy com `disallow_untyped_defs`); docstrings no formato Google.
- Config em `configs/*.yaml` validada via Pydantic (`the_bank_project.config`); segredos em `.env` (modelo em `.env.example`). Nada de paths hardcoded.
- Um step de pipeline = função pura + CLI, testável sem Airflow; DAGs só envolvem o código do pacote.
- Airflow roda só em imagem Docker própria (`docker/airflow/`), fora do `pyproject.toml`.
- Nome de experimento/run no MLflow: `<etapa>_<modelo>_<data>`.
- Reutilizar bibliotecas reconhecidas em vez de reimplementar.

# Workflow

- Rodar `make check` após mudanças relevantes.
- Apenas o usuário faz commits; ao final de cada mudança, sugerir a mensagem em Conventional Commits (`feat:`, `fix:`, `chore:`, `docs:`, `experiment:`).
- Infra 100% local via Docker; não assumir cloud.
- Fim de fase: atualizar README, este arquivo e o status no ROADMAP.
