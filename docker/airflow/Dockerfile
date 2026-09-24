# Imagem própria do Airflow, fora do pyproject.toml. O Airflow (com os constraints
# oficiais, que fixam pandas 2.1 / numpy 1.26 / pyarrow 18) só orquestra; o código
# do projeto roda num venv separado (/opt/airflow/venv) com as dependências do
# próprio pyproject.toml — as mesmas versões maiores do dev e do CI, sem lista
# duplicada e sem brigar com os constraints.
ARG AIRFLOW_VERSION=3.1.0
FROM apache/airflow:${AIRFLOW_VERSION}-python3.12

WORKDIR /tmp/pkg
COPY pyproject.toml README.md ./
COPY src ./src
RUN python -m venv /opt/airflow/venv && /opt/airflow/venv/bin/pip install --no-cache-dir .
WORKDIR /opt/airflow

# O docker-compose monta ./src em /opt/airflow/src. PYTHONPATH vem antes do
# site-packages do venv, então o código montado vale sobre a cópia instalada (sem
# rebuild) — e `PROJECT_ROOT` (config.py) só resolve certo a partir dele.
ENV PYTHONPATH=/opt/airflow/src
