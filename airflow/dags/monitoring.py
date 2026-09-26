"""DAG de monitoramento: relatório de drift (Evidently) e publicação do resumo no Prometheus.

Semanal, além do disparo manual. Pressupõe o `data_pipeline` já executado (labels e Feast). Com drift e o
cooldown vencido, dispara a DAG `training`, cujo `promote` é o gate da Fase 5 (o campeão só muda se o
challenger o superar). A DAG `training` precisa estar ativa (unpaused), senão o run disparado fica na fila.
"""

import pendulum
from airflow.providers.standard.operators.trigger_dagrun import TriggerDagRunOperator
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
    """`drift_report` grava o relatório; `decide_retrain` aplica drift + cooldown; `publish_metrics` publica."""

    @task.external_python(python=PROJECT_PYTHON, expect_airflow=False, expect_pendulum=False)
    def drift_report() -> None:
        from the_bank_project.config import load_config
        from the_bank_project.monitoring import run_drift

        run_drift(load_config())

    @task.external_python(python=PROJECT_PYTHON, expect_airflow=False, expect_pendulum=False)
    def decide_retrain() -> bool:
        from the_bank_project.config import load_config
        from the_bank_project.monitoring import decide_retrain as decide

        return decide(load_config()).retrain

    @task.short_circuit
    def retrain_needed(retrain: bool) -> bool:
        return retrain

    @task.external_python(python=PROJECT_PYTHON, expect_airflow=False, expect_pendulum=False)
    def publish_metrics() -> None:
        from the_bank_project.config import Settings, load_config
        from the_bank_project.monitoring import load_last_retrain, load_summary, push_drift

        url = Settings().pushgateway_url
        if not url:
            raise ValueError("PUSHGATEWAY_URL não está definida no ambiente do Airflow.")
        out_dir = load_config().paths.monitoring
        push_drift(load_summary(out_dir), url, last_retrain_at=load_last_retrain(out_dir))

    decision = decide_retrain()
    trigger_training = TriggerDagRunOperator(task_id="trigger_training", trigger_dag_id="training")
    drift_report() >> decision
    decision >> publish_metrics()
    retrain_needed(decision) >> trigger_training


monitoring()
