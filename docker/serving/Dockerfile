# API de inferência (FastAPI). As dependências saem do poetry.lock, as MESMAS versões do treino: o modelo
# do MLflow é um pickle e só carrega com o scikit-learn/XGBoost com que foi treinado.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 POETRY_VIRTUALENVS_CREATE=false POETRY_NO_INTERACTION=1
RUN pip install "poetry>=2,<3"

# /app é a raiz do projeto: `config.py` resolve configs/, data/ e feature_repo/ a partir dele.
WORKDIR /app
COPY pyproject.toml poetry.lock README.md ./
RUN poetry install --only main --no-root && rm -rf /root/.cache
# o código vem depois das dependências: mudar a interface ou a API não reinstala as bibliotecas
COPY src ./src
COPY configs ./configs
RUN poetry install --only main && rm -rf /root/.cache

EXPOSE 8000
# Um processo só: as métricas do Prometheus ficam em memória (ver serving/metrics.py).
CMD ["python", "-m", "the_bank_project.serving"]
