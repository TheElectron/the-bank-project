"""DAG do pipeline de dados: Kaggle → Raw → Bronze → Silver. Só orquestra o código do pacote."""

import pendulum
from airflow.sdk import dag, task


@dag(
    dag_id="data_pipeline",
    schedule=None,  # dataset estático (Berka, 1999): disparo manual
    start_date=pendulum.datetime(2026, 1, 1, tz="UTC"),
    catchup=False,
    tags=["data"],
)
def ingestion() -> None:
    """Uma task por passo; idempotentes e sem dados no XCom (os passos trocam só paths no disco)."""

    @task
    def download() -> None:
        from the_bank_project.config import load_config
        from the_bank_project.ingestion.raw import download_to_raw

        cfg = load_config()
        download_to_raw(cfg.kaggle.dataset, cfg.paths.raw)

    @task
    def to_bronze() -> None:
        from the_bank_project.config import load_config
        from the_bank_project.ingestion.bronze import to_bronze as convert

        cfg = load_config()
        convert(cfg.paths.raw, cfg.paths.bronze)

    @task
    def to_silver() -> None:
        from the_bank_project.config import load_config
        from the_bank_project.silver import bronze_to_silver

        cfg = load_config()
        bronze_to_silver(cfg.paths.bronze, cfg.paths.silver)

    download() >> to_bronze() >> to_silver()


ingestion()
