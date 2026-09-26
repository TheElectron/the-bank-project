#!/usr/bin/env bash
# Smoke test de uma imagem do projeto: o essencial sobe/importa? Uso: smoke_image.sh <airflow|mlflow|serving> <imagem>
# Não sobe a stack: a API precisa da Gold e do Feast, que não existem num runner de CI (o `dag-check` cobre as DAGs).
set -euo pipefail

name="${1:?uso: $0 <airflow|mlflow|serving> <imagem>}"
image="${2:?uso: $0 <airflow|mlflow|serving> <imagem>}"

case "$name" in
  airflow) docker run --rm --entrypoint /opt/airflow/venv/bin/python "$image" -c "import the_bank_project.monitoring, evidently" ;;
  mlflow)  docker run --rm --entrypoint mlflow "$image" --version ;;
  serving) docker run --rm --entrypoint python "$image" -c "import the_bank_project.serving" ;;
  *) echo "imagem desconhecida: $name" >&2; exit 2 ;;
esac
echo "OK: $name ($image)"
