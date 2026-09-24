# Imagem própria do Airflow: fica fora do pyproject.toml para não conflitar com
# Feast/MLflow/Evidently. Deps do pacote instaladas com os constraints oficiais;
# o código (src/, configs/, data/) entra por volume no docker-compose.yml.
ARG AIRFLOW_VERSION=3.1.0
FROM apache/airflow:${AIRFLOW_VERSION}-python3.12

ARG AIRFLOW_VERSION
COPY docker/airflow/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt \
    -c "https://raw.githubusercontent.com/apache/airflow/constraints-${AIRFLOW_VERSION}/constraints-3.12.txt"

ENV PYTHONPATH=/opt/airflow/src
