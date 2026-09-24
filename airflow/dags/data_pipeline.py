"""DAG do pipeline de dados: Kaggle → Raw → Bronze → Silver → Gold → Feast. Só orquestra o código do pacote."""

import pendulum
from airflow.sdk import dag, task

# Python do venv com as deps do projeto (ver docker/airflow/Dockerfile). O decorator precisa
# aparecer por extenso em cada task: o Airflow o remove do código-fonte que envia ao venv.
PROJECT_PYTHON = "/opt/airflow/venv/bin/python"


@dag(
    dag_id="data_pipeline",
    schedule=None,  # dataset estático (Berka, 1999): disparo manual
    start_date=pendulum.datetime(2026, 1, 1, tz="UTC"),
    catchup=False,
    tags=["data"],
)
def data_pipeline() -> None:
    """Uma task por passo; idempotentes e sem dados no XCom (os passos trocam só paths no disco)."""

    @task.external_python(python=PROJECT_PYTHON, expect_airflow=False, expect_pendulum=False)
    def download() -> None:
        from the_bank_project.config import load_config
        from the_bank_project.ingestion.raw import download_to_raw

        cfg = load_config()
        download_to_raw(cfg.kaggle.dataset, cfg.paths.raw)

    @task.external_python(python=PROJECT_PYTHON, expect_airflow=False, expect_pendulum=False)
    def to_bronze() -> None:
        from the_bank_project.config import load_config
        from the_bank_project.ingestion.bronze import to_bronze as convert

        cfg = load_config()
        convert(cfg.paths.raw, cfg.paths.bronze)

    @task.external_python(python=PROJECT_PYTHON, expect_airflow=False, expect_pendulum=False)
    def to_silver() -> None:
        from the_bank_project.config import load_config
        from the_bank_project.silver import bronze_to_silver

        cfg = load_config()
        bronze_to_silver(cfg.paths.bronze, cfg.paths.silver)

    @task.external_python(python=PROJECT_PYTHON, expect_airflow=False, expect_pendulum=False)
    def to_gold() -> None:
        from the_bank_project.config import load_config
        from the_bank_project.gold import silver_to_gold

        cfg = load_config()
        silver_to_gold(cfg.paths.silver, cfg.paths.gold)

    @task.external_python(python=PROJECT_PYTHON, expect_airflow=False, expect_pendulum=False)
    def feast_apply() -> None:
        from the_bank_project.features import apply_repo

        apply_repo()

    @task.external_python(python=PROJECT_PYTHON, expect_airflow=False, expect_pendulum=False)
    def feast_materialize() -> None:
        from the_bank_project.features import materialize_all

        materialize_all()

    download() >> to_bronze() >> to_silver() >> to_gold() >> feast_apply() >> feast_materialize()


data_pipeline()
