#!/usr/bin/env python3
"""
datalake_setup.py
==================

Provisiona a infraestrutura local de um Datalake seguindo a arquitetura
Medallion, no escopo atual do projeto (raw -> bronze -> silver/real), e
executa a ingestão inicial do dataset público "The Berka Dataset" (Kaggle)
na camada `raw/`.

--------------------------------------------------------------------------
PRÉ-REQUISITOS (executar uma única vez, fora deste script)
--------------------------------------------------------------------------
1) Criar e ativar um ambiente virtual:

    python3 -m venv .venv
    source .venv/bin/activate          # Linux/Mac
    .venv\\Scripts\\activate            # Windows

2) Instalar as dependências:

    pip install -r requirements.txt

3) Obter as credenciais da Kaggle API:
    - Acesse https://www.kaggle.com/settings -> "Create New Token".
    - Isso baixa um arquivo `kaggle.json` com `username` e `key`.
    - Coloque o arquivo em `~/.kaggle/kaggle.json` (Linux/Mac) e ajuste
    a permissão para leitura/escrita apenas do dono:

        mkdir -p ~/.kaggle
        mv ~/Downloads/kaggle.json ~/.kaggle/kaggle.json
        chmod 600 ~/.kaggle/kaggle.json

    Alternativamente, é possível definir as variáveis de ambiente
    KAGGLE_USERNAME e KAGGLE_KEY, ou apontar KAGGLE_CONFIG_DIR para o
    diretório que contém o `kaggle.json`.

4) Executar o script:

    python datalake_setup.py

--------------------------------------------------------------------------
"""

from __future__ import annotations

import argparse
import logging
import os
import shutil
import sys
import zipfile
from pathlib import Path

# --------------------------------------------------------------------------
# Configuração de logging (nível INFO conforme solicitado)
# --------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("datalake_setup")

# --------------------------------------------------------------------------
# Constantes globais
# --------------------------------------------------------------------------
DATASET_SLUG = "marceloventura/the-berka-dataset"

# Diretório base do datalake, ancorado na raiz do projeto (não na pasta
# do script). O script vive em <raiz>/src/scripts/, então subimos dois
# níveis: scripts/ -> src/ -> <raiz>.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
BASE_DIR = PROJECT_ROOT / "datalake"

# Subpastas do escopo atual do datalake (raw -> bronze -> silver/real).
MEDALLION_DIRS = [
    BASE_DIR / "raw",
    BASE_DIR / "bronze",
    BASE_DIR / "silver" / "real",
]

# Pasta temporária de trabalho usada apenas durante o download/extração.
# Fica dentro de raw/ para simplificar, mas é sempre removida ao final.
TMP_DOWNLOAD_DIR = BASE_DIR / "raw" / "_tmp_kaggle_download"


# --------------------------------------------------------------------------
# 1) Criação da estrutura de diretórios (Medallion Architecture)
# --------------------------------------------------------------------------
def create_directory_structure(directories: list[Path]) -> None:
    """Cria (de forma idempotente) as pastas da arquitetura Medallion.

    Args:
        directories: lista de caminhos (Path) a serem garantidos.

    Raises:
        OSError: caso não seja possível criar algum diretório (ex.: falta
            de permissão de escrita no sistema de arquivos).
    """
    logger.info("Etapa 1/5: verificando/criando estrutura de diretórios do Datalake...")
    for directory in directories:
        try:
            already_existed = directory.exists()
            directory.mkdir(parents=True, exist_ok=True)
            if already_existed:
                logger.info("  - já existia: %s", directory)
            else:
                logger.info("  - criado:     %s", directory)
        except OSError:
            logger.exception("Falha ao criar o diretório: %s", directory)
            raise
    logger.info("Estrutura de diretórios pronta em: %s", BASE_DIR)


# --------------------------------------------------------------------------
# 2) Validação das credenciais da Kaggle API
# --------------------------------------------------------------------------
def ensure_kaggle_credentials() -> None:
    """Verifica se as credenciais da Kaggle API estão configuradas.

    O pacote `kaggle` (>=2.x) tenta autenticar, nesta ordem:
        1. Access token novo (env `KAGGLE_API_TOKEN`, ou arquivo
            `~/.kaggle/access_token` / `access_token.txt`).
        2. Legacy API key (`~/.kaggle/kaggle.json` com `username`/`key`,
            ou env `KAGGLE_USERNAME`/`KAGGLE_KEY`).
        3. OAuth interativo / anônimo.

    Como fallback adicional (não padrão da lib, mas usado por este
    projeto), também aceitamos um token salvo em `<raiz>/kaggle/settings.json`
    contendo apenas o valor do token (sem estrutura JSON) — se encontrado,
    ele é exposto via `KAGGLE_API_TOKEN` para que a lib o leia como arquivo.

    Esta função apenas confirma a *presença* de alguma credencial; a
    validade do token só é checada pela própria lib no momento do
    `authenticate()`.

    Raises:
        FileNotFoundError: quando nenhuma credencial é encontrada.
    """
    logger.info("Etapa 2/5: validando credenciais da Kaggle API...")

    config_dir = Path(os.environ.get("KAGGLE_CONFIG_DIR", Path.home() / ".kaggle"))

    # 1) Access token novo via variável de ambiente.
    if os.environ.get("KAGGLE_API_TOKEN"):
        logger.info("  - credenciais (access token) encontradas via variável de ambiente KAGGLE_API_TOKEN.")
        return

    # 2) Access token novo via arquivo padrão (~/.kaggle/access_token[.txt]).
    for filename in ("access_token", "access_token.txt"):
        token_file = config_dir / filename
        if token_file.is_file() and token_file.read_text(encoding="utf-8").strip():
            logger.info("  - credenciais (access token) encontradas em: %s", token_file)
            return

    # 3) Legacy API key via variáveis de ambiente ou kaggle.json.
    if os.environ.get("KAGGLE_USERNAME") and os.environ.get("KAGGLE_KEY"):
        logger.info("  - credenciais (legacy api key) encontradas via variáveis de ambiente.")
        return

    kaggle_json = config_dir / "kaggle.json"
    if kaggle_json.is_file():
        logger.info("  - credenciais (legacy api key) encontradas em: %s", kaggle_json)
        return

    # 4) Fallback específico deste projeto: token salvo em kaggle/settings.json
    #    na raiz do repositório (local não padrão da lib Kaggle).
    local_token_file = PROJECT_ROOT / "kaggle" / "settings.json"
    if local_token_file.is_file() and local_token_file.read_text(encoding="utf-8").strip():
        os.environ["KAGGLE_API_TOKEN"] = str(local_token_file)
        logger.info(
            "  - credenciais (access token) encontradas em local não padrão do projeto: %s "
            "(exposto via KAGGLE_API_TOKEN; recomenda-se migrar para %s futuramente).",
            local_token_file,
            config_dir / "access_token",
        )
        return

    raise FileNotFoundError(
        "Credenciais da Kaggle API não encontradas. Gere um token em "
        "https://www.kaggle.com/settings/api e salve-o em "
        f"'{config_dir / 'access_token'}' (chmod 600), defina a variável de "
        "ambiente KAGGLE_API_TOKEN, ou use o formato legacy "
        f"'{kaggle_json}' com username/key."
    )


# --------------------------------------------------------------------------
# 3) Download do dataset via Kaggle API
# --------------------------------------------------------------------------
def download_dataset(dataset_slug: str, download_dir: Path) -> Path:
    """Baixa o dataset informado da Kaggle API (arquivo .zip único).

    A importação de `kaggle` é feita dentro da função (e não no topo do
    módulo) porque a própria biblioteca tenta autenticar no momento do
    import; isso garante que `ensure_kaggle_credentials()` já tenha
    validado o ambiente e produza um erro amigável antes disso.

    Args:
        dataset_slug: identificador do dataset no formato "usuario/nome".
        download_dir: diretório onde o .zip será salvo.

    Returns:
        Path para o arquivo .zip baixado.

    Raises:
        RuntimeError: se o download falhar ou o .zip não for encontrado.
    """
    logger.info("Etapa 3/5: baixando dataset '%s' via Kaggle API...", dataset_slug)
    download_dir.mkdir(parents=True, exist_ok=True)

    try:
        from kaggle.api.kaggle_api_extended import KaggleApi
    except ImportError as exc:
        raise RuntimeError(
            "Biblioteca 'kaggle' não instalada. Ative o ambiente virtual e "
            "rode 'pip install -r requirements.txt'."
        ) from exc

    try:
        api = KaggleApi()
        api.authenticate()
        api.dataset_download_files(
            dataset_slug,
            path=str(download_dir),
            unzip=False,  # mantemos o zip intacto; extração é feita à parte
            quiet=False,
        )
    except Exception:
        logger.exception("Falha ao baixar o dataset '%s'.", dataset_slug)
        raise

    zip_candidates = list(download_dir.glob("*.zip"))
    if not zip_candidates:
        raise RuntimeError(
            f"Download concluído mas nenhum arquivo .zip foi encontrado em {download_dir}."
        )

    zip_path = zip_candidates[0]
    logger.info("  - download concluído: %s", zip_path)
    return zip_path


# --------------------------------------------------------------------------
# 4) Extração do .zip
# --------------------------------------------------------------------------
def extract_zip(zip_path: Path, extract_to: Path) -> Path:
    """Extrai o conteúdo do .zip para uma pasta temporária.

    Args:
        zip_path: caminho do arquivo .zip a ser extraído.
        extract_to: diretório de destino da extração.

    Returns:
        Path do diretório onde os arquivos foram extraídos.

    Raises:
        zipfile.BadZipFile: caso o arquivo esteja corrompido/inválido.
    """
    logger.info("Etapa 4/5: extraindo arquivo '%s'...", zip_path.name)
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(extract_to)
            extracted_names = zf.namelist()
    except zipfile.BadZipFile:
        logger.exception("Arquivo .zip inválido ou corrompido: %s", zip_path)
        raise

    logger.info("  - %d arquivo(s) extraído(s) para: %s", len(extracted_names), extract_to)
    return extract_to


# --------------------------------------------------------------------------
# 5) Movimentação dos CSVs para a camada raw (sem alterar conteúdo)
# --------------------------------------------------------------------------
def move_csv_files(source_dir: Path, raw_dir: Path) -> list[Path]:
    """Move (sem reescrever) todos os arquivos .csv encontrados recursivamente.

    Usa `shutil.move`, que renomeia/transfere os bytes originais do
    arquivo sem abri-los para leitura/escrita, garantindo que o
    conteúdo permaneça absolutamente inalterado.

    Args:
        source_dir: diretório (recursivo) onde procurar os .csv extraídos.
        raw_dir: diretório de destino final (datalake/raw/).

    Returns:
        Lista de caminhos finais dos arquivos movidos.

    Raises:
        FileNotFoundError: se nenhum .csv for encontrado no source_dir.
    """
    csv_files = sorted(source_dir.rglob("*.csv"))
    if not csv_files:
        raise FileNotFoundError(f"Nenhum arquivo .csv encontrado em {source_dir}.")

    moved_files: list[Path] = []
    for csv_file in csv_files:
        destination = raw_dir / csv_file.name
        if destination.exists():
            logger.warning("  - arquivo já existe em raw/, será sobrescrito: %s", destination.name)
            destination.unlink()
        shutil.move(str(csv_file), str(destination))
        logger.info("  - movido: %s -> %s", csv_file.name, destination)
        moved_files.append(destination)

    return moved_files


# --------------------------------------------------------------------------
# 6) Limpeza dos artefatos temporários
# --------------------------------------------------------------------------
def cleanup(paths_to_remove: list[Path]) -> None:
    """Remove arquivos/pastas temporários (.zip e diretório de extração).

    Cada remoção é feita de forma independente e tolerante a falhas
    (best-effort), registrando um aviso caso algum caminho já não
    exista mais ou não possa ser removido.

    Args:
        paths_to_remove: lista de arquivos e/ou diretórios a remover.
    """
    logger.info("Etapa 5/5: limpando arquivos temporários...")
    for path in paths_to_remove:
        try:
            if path.is_dir():
                shutil.rmtree(path)
                logger.info("  - diretório removido: %s", path)
            elif path.is_file():
                path.unlink()
                logger.info("  - arquivo removido: %s", path)
            else:
                logger.info("  - nada a remover (já inexistente): %s", path)
        except OSError:
            logger.warning("  - não foi possível remover: %s", path, exc_info=True)


# --------------------------------------------------------------------------
# Orquestração
# --------------------------------------------------------------------------
def run(dataset_slug: str = DATASET_SLUG, base_dir: Path = BASE_DIR) -> None:
    """Executa o pipeline completo: estrutura de pastas + ingestão raw.

    Args:
        dataset_slug: dataset da Kaggle a ser baixado ("usuario/nome").
        base_dir: diretório raiz do datalake.
    """
    raw_dir = base_dir / "raw"
    tmp_dir = raw_dir / "_tmp_kaggle_download"

    directories = [
        raw_dir,
        base_dir / "bronze",
        base_dir / "silver" / "real",
    ]

    zip_path: Path | None = None
    try:
        create_directory_structure(directories)
        ensure_kaggle_credentials()

        zip_path = download_dataset(dataset_slug, tmp_dir)
        extract_zip(zip_path, tmp_dir)
        move_csv_files(tmp_dir, raw_dir)

    except Exception:
        logger.exception("Pipeline de ingestão interrompido devido a um erro.")
        raise
    finally:
        # A limpeza roda mesmo se algo falhar após o download, para não
        # deixar lixo (zip / pasta temporária) no ambiente.
        cleanup([tmp_dir])

    logger.info("Ingestão inicial concluída com sucesso. Arquivos disponíveis em: %s", raw_dir)


def parse_args() -> argparse.Namespace:
    """Define os argumentos de linha de comando (com valores padrão)."""
    parser = argparse.ArgumentParser(
        description="Provisiona o Datalake local (Medallion) e ingere o dataset Berka via Kaggle API."
    )
    parser.add_argument(
        "--dataset",
        default=DATASET_SLUG,
        help=f"Dataset da Kaggle no formato 'usuario/nome' (padrão: {DATASET_SLUG}).",
    )
    parser.add_argument(
        "--base-dir",
        default=str(BASE_DIR),
        help=f"Diretório raiz do datalake (padrão: {BASE_DIR}).",
    )
    return parser.parse_args()


def main() -> int:
    """Ponto de entrada do script. Retorna o código de saída do processo."""
    args = parse_args()
    try:
        run(dataset_slug=args.dataset, base_dir=Path(args.base_dir))
    except Exception as exc:  # noqa: BLE001 - captura ampla e intencional no nível mais alto
        logger.error("Falha na execução do script: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
