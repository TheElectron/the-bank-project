"""Falha se alguma DAG não importar. Roda dentro da imagem do Airflow (`make dag-check`)."""

from airflow.models import DagBag

bag = DagBag("/opt/airflow/dags", include_examples=False)
assert not bag.import_errors, bag.import_errors
assert {"data_pipeline", "training"} <= set(bag.dags), f"DAGs encontradas: {list(bag.dags)}"
print(f"OK: {sorted(bag.dags)}")
