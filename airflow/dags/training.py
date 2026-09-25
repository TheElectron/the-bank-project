"""DAG de treino: treina os candidatos e passa o challenger pelo gate de promoção.

Disparo manual; na Fase 7 o alerta de drift a dispara via API do Airflow. Pressupõe o
`data_pipeline` já executado (Gold, labels e Feast materializado).
"""

import pendulum
from airflow.sdk import dag, task

# Python do venv com as deps do projeto (ver docker/airflow/Dockerfile). O decorator precisa
# aparecer por extenso em cada task: o Airflow o remove do código-fonte que envia ao venv.
PROJECT_PYTHON = "/opt/airflow/venv/bin/python"


@dag(
    dag_id="training",
    schedule=None,
    start_date=pendulum.datetime(2026, 1, 1, tz="UTC"),
    catchup=False,
    tags=["model"],
)
def training() -> None:
    """`train` registra o challenger; `promote` só o promove se superar o campeão atual."""

    @task.external_python(python=PROJECT_PYTHON, expect_airflow=False, expect_pendulum=False)
    def train() -> None:
        from the_bank_project.config import load_config
        from the_bank_project.training.train import run_training

        run_training(load_config())

    @task.external_python(python=PROJECT_PYTHON, expect_airflow=False, expect_pendulum=False)
    def promote() -> None:
        from the_bank_project.config import load_config
        from the_bank_project.training.registry import promote as run_promote

        run_promote(load_config())

    train() >> promote()


training()
