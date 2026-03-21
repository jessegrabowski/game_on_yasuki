import logging
import os
import sys

from yasuki_core.paths import DATABASE_DIR

DEFAULT_DSN = os.environ.get(
    "YASUKI_DATABASE_URL", os.environ.get("DATABASE_URL", "postgresql://localhost/yasuki")
)

__all__ = ["DEFAULT_DSN", "DATABASE_DIR", "setup_logging"]


def setup_logging(debug: bool = False) -> None:
    """
    Configure root logger for the application.

    Parameters
    ----------
    debug : bool
        If True, set logging level to DEBUG, otherwise INFO
    """
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)],
    )
