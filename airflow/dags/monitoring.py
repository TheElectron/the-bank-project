"""DAG de monitoramento: relatório de drift (Evidently) e publicação do resumo no Prometheus.

Semanal, além do disparo manual. Pressupõe o `data_pipeline` já executado (labels e Feast). O re-treino
por drift (Fase 7c) entra depois destas duas tasks.
"""

import pendulum
from airflow.sdk import dag, task

# Python do venv com as deps do projeto (ver docker/airflow/Dockerfile). O decorator precisa
# aparecer por extenso em cada task: o Airflow o remove do código-fonte que envia ao venv.
PROJECT_PYTHON = "/opt/airflow/venv/bin/python"


@dag(
    dag_id="monitoring",
    schedule="@weekly",
    start_date=pendulum.datetime(2026, 1, 1, tz="UTC"),
    catchup=False,
    tags=["monitoring"],
)
def monitoring() -> None:
    """`drift_report` grava o relatório e o resumo em disco; `publish_metrics` envia o resumo ao Pushgateway."""

    @task.external_python(python=PROJECT_PYTHON, expect_airflow=False, expect_pendulum=False)
    def drift_report() -> None:
        from the_bank_project.config import load_config
        from the_bank_project.monitoring import run_drift

        run_drift(load_config())

    @task.external_python(python=PROJECT_PYTHON, expect_airflow=False, expect_pendulum=False)
    def publish_metrics() -> None:
        from the_bank_project.config import Settings, load_config
        from the_bank_project.monitoring import load_summary, push_drift

        url = Settings().pushgateway_url
        if not url:
            raise ValueError("PUSHGATEWAY_URL não está definida no ambiente do Airflow.")
        push_drift(load_summary(load_config().paths.monitoring), url)

    drift_report() >> publish_metrics()


monitoring()
