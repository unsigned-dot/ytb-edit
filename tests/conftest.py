import logging

import pytest


@pytest.fixture(autouse=True)
def _reset_root_logger():
    """Évite qu'un test qui configure les logs n'affecte les suivants."""
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    yield
    for handler in root.handlers[:]:
        if handler not in handlers:
            root.removeHandler(handler)
            handler.close()
    root.setLevel(level)
