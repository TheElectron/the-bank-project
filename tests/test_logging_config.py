import logging

from the_bank_project.logging_config import configure_logging


def test_configure_logging_sets_root_handler():
    configure_logging()
    root = logging.getLogger()
    assert root.level == logging.INFO
    assert root.handlers
