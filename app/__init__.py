import logging
import os
import sys
from pathlib import Path

DATABASE_DIR = Path(__file__).resolve().parent / "assets" / "database"
DEFAULT_DSN = os.environ.get("L5R_DATABASE_URL", "postgresql://localhost/l5r")

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
