# Imagem própria do Airflow, fora do pyproject.toml. O Airflow (com os constraints
# oficiais, que fixam pandas 2.1 / numpy 1.26 / pyarrow 18) só orquestra; o código
# do projeto roda num venv separado (/opt/airflow/venv), instalado pelo poetry.lock:
# exatamente as versões do dev, do CI e da API de serving (o modelo treinado aqui é um
# pickle que a API precisa carregar), sem lista duplicada e sem brigar com os constraints.
ARG AIRFLOW_VERSION=3.1.0
FROM apache/airflow:${AIRFLOW_VERSION}-python3.12

WORKDIR /tmp/pkg
COPY pyproject.toml poetry.lock README.md ./
COPY src ./src
RUN python -m venv /opt/airflow/venv \
    && /opt/airflow/venv/bin/pip install --no-cache-dir "poetry>=2,<3" \
    && VIRTUAL_ENV=/opt/airflow/venv /opt/airflow/venv/bin/poetry install --only main,monitoring --no-interaction
WORKDIR /opt/airflow

# O docker-compose monta ./src em /opt/airflow/src. PYTHONPATH vem antes do
# site-packages do venv, então o código montado vale sobre a cópia instalada (sem
# rebuild) — e `PROJECT_ROOT` (config.py) só resolve certo a partir dele.
ENV PYTHONPATH=/opt/airflow/src
