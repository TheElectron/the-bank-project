# Servidor MLflow (tracking + registry). A versão acompanha a do cliente no pyproject.toml,
# senão o cliente e o servidor podem divergir no schema do banco/API.
FROM python:3.12-slim

ARG MLFLOW_VERSION=3.16.1
RUN pip install --no-cache-dir "mlflow==${MLFLOW_VERSION}"

WORKDIR /mlflow
EXPOSE 5000
# --serve-artifacts: os clientes (host e Airflow) enviam artefatos pelo servidor, sem compartilhar disco.
# --allowed-hosts: o middleware de segurança do MLflow 3 rejeita Hosts desconhecidos (ex.: o nome `mlflow`).
CMD ["mlflow", "server", "--host", "0.0.0.0", "--port", "5000", \
     "--backend-store-uri", "sqlite:////mlflow/mlflow.db", \
     "--artifacts-destination", "/mlflow/artifacts", "--serve-artifacts", \
     "--allowed-hosts", "mlflow:5000,localhost:5000,127.0.0.1:5000"]
