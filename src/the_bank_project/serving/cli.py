"""CLI do serving: `python -m the_bank_project.serving` sobe a API com uvicorn."""

import argparse
import sys
from collections.abc import Sequence

import uvicorn

from the_bank_project.config import load_config
from the_bank_project.logging_config import configure_logging


def main(argv: Sequence[str] | None = None) -> int:
    """Sobe o servidor (host e porta da config, sobrescritos por --host/--port)."""
    cfg = load_config()
    parser = argparse.ArgumentParser(prog="the_bank_project.serving", description="API de inferência.")
    parser.add_argument("--host", default=cfg.serving.host)
    parser.add_argument("--port", type=int, default=cfg.serving.port)
    args = parser.parse_args(argv)
    configure_logging()
    uvicorn.run("the_bank_project.serving.app:create_app", factory=True, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
