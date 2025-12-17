import argparse
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from collections.abc import Iterable
import shutil

import psycopg2

from app import DATABASE_DIR
from app.install import sets_to_sql, json_to_sql
import logging


logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


DEFAULT_CARDS_PATH = DATABASE_DIR / "cards.json"
DEFAULT_SETS_PATH = DATABASE_DIR / "set_info.json"
DEFAULT_SCHEMA_PATH = DATABASE_DIR / "schema.sql"
DEFAULT_DSN = os.environ.get("L5R_DATABASE_URL", "postgresql://localhost/l5r")


@dataclass
class InstallerConfig:
    dsn: str
    cards_path: Path
    sets_path: Path
    schema_path: Path
    force: bool
    skip_sets: bool
    skip_cards: bool


class InstallerError(RuntimeError):
    pass


class Installer:
    def __init__(self, cfg: InstallerConfig):
        self.cfg = cfg

    def run(self) -> None:
        self._validate_prerequisites()
        self._validate_files()
        self._ensure_database_exists()

        logger.info("Connecting to database")
        with psycopg2.connect(self.cfg.dsn) as conn:
            conn.autocommit = False
            with conn.cursor() as cur:
                if self._schema_exists(cur):
                    if not self.cfg.force:
                        raise InstallerError(
                            "Database already initialized. Use --force to recreate it."
                        )
                    self._reset_schema(cur)
                self._apply_schema(cur)
                conn.commit()

        if not self.cfg.skip_sets:
            logger.info("Loading set metadata")
            sets_to_sql.load_l5r_sets(self.cfg.sets_path, self.cfg.dsn)
        else:
            logger.info("Skipping set metadata import")

        if not self.cfg.skip_cards:
            logger.info("Loading cards (this will take a while)")
            logger.info("Image paths are automatically populated during card import")
            json_to_sql.load_cards(self.cfg.cards_path, self.cfg.dsn)
        else:
            logger.info("Skipping card import")

        logger.info("Database installation complete")

    def _validate_prerequisites(self) -> None:
        """Check if PostgreSQL tools are available on the system."""
        if not shutil.which("psql"):
            raise InstallerError(
                "PostgreSQL client tools not found. Please install PostgreSQL:\n"
                "  - macOS: brew install postgresql\n"
                "  - Ubuntu/Debian: sudo apt-get install postgresql-client\n"
                "  - Windows: Download from https://www.postgresql.org/download/"
            )

        if not shutil.which("createdb"):
            logger.warning(
                "createdb command not found in PATH. You may need to create the database manually."
            )

    def _validate_files(self) -> None:
        """Validate that all required asset files exist before attempting database operations."""
        missing = []

        if not self.cfg.schema_path.exists():
            missing.append(f"Schema file: {self.cfg.schema_path}")

        if not self.cfg.skip_sets and not self.cfg.sets_path.exists():
            missing.append(f"Sets file: {self.cfg.sets_path}")

        if not self.cfg.skip_cards and not self.cfg.cards_path.exists():
            missing.append(f"Cards file: {self.cfg.cards_path}")

        if missing:
            raise InstallerError("Missing required files:\n  " + "\n  ".join(missing))

    def _ensure_database_exists(self) -> None:
        """Check if the database exists and offer to create it if it doesn't."""
        try:
            with psycopg2.connect(self.cfg.dsn) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT version();")
                    logger.info("Connected to database successfully")
        except psycopg2.OperationalError as e:
            error_msg = str(e).lower()

            if "database" in error_msg and "does not exist" in error_msg:
                db_name = self._extract_db_name_from_dsn(self.cfg.dsn)
                raise InstallerError(
                    f"Database '{db_name}' does not exist. Create it first with:\n"
                    f"  createdb {db_name}\n"
                    f"Or create it via SQL: CREATE DATABASE {db_name};"
                )
            elif "could not connect" in error_msg or "connection refused" in error_msg:
                raise InstallerError(
                    "Could not connect to PostgreSQL server. Is it running?\n"
                    "  - macOS: brew services start postgresql\n"
                    "  - Linux: sudo systemctl start postgresql\n"
                    "  - Check connection string: " + self.cfg.dsn
                )
            elif "authentication failed" in error_msg or "password" in error_msg:
                raise InstallerError(
                    f"Authentication failed. Check your credentials in the DSN:\n"
                    f"  Current DSN: {self.cfg.dsn}\n"
                    f"  Format: postgresql://[user[:password]@][host][:port]/database"
                )
            else:
                raise InstallerError(f"Database connection failed: {e}")

    def _extract_db_name_from_dsn(self, dsn: str) -> str:
        """Extract database name from DSN string."""
        if dsn.startswith("postgresql://"):
            return dsn.split("/")[-1].split("?")[0]
        elif "dbname=" in dsn:
            for part in dsn.split():
                if part.startswith("dbname="):
                    return part.split("=")[1]
        return "l5r"

    def _schema_exists(self, cur) -> bool:
        cur.execute(
            """SELECT EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_name = 'cards'
            )"""
        )
        return bool(cur.fetchone()[0])

    def _apply_schema(self, cur) -> None:
        sql = self.cfg.schema_path.read_text(encoding="utf-8")
        cur.execute(sql)

    def _reset_schema(self, cur) -> None:
        print("Existing schema detected. Dropping public schema …")
        cur.execute("DROP SCHEMA IF EXISTS public CASCADE;")
        cur.execute("CREATE SCHEMA public;")
        cur.execute("GRANT ALL ON SCHEMA public TO public;")


def parse_args(argv: list[str]) -> InstallerConfig:
    parser = argparse.ArgumentParser(description="Initialize the L5R database")
    parser.add_argument(
        "--dsn",
        default=DEFAULT_DSN,
        help="PostgreSQL DSN, defaults to %(default)s or $L5R_DATABASE_URL",
    )
    parser.add_argument(
        "--cards",
        type=Path,
        default=DEFAULT_CARDS_PATH,
        help="Path to cards JSON (default: %(default)s)",
    )
    parser.add_argument(
        "--sets",
        type=Path,
        default=DEFAULT_SETS_PATH,
        help="Path to set info JSON (default: %(default)s)",
    )
    parser.add_argument(
        "--schema",
        type=Path,
        default=DEFAULT_SCHEMA_PATH,
        help="Path to schema SQL (default: %(default)s)",
    )
    parser.add_argument(
        "--force", action="store_true", help="Reapply schema even if tables already exist"
    )
    parser.add_argument("--skip-sets", action="store_true", help="Skip loading set metadata")
    parser.add_argument("--skip-cards", action="store_true", help="Skip loading card data")
    args = parser.parse_args(argv)

    return InstallerConfig(
        dsn=args.dsn,
        cards_path=args.cards,
        sets_path=args.sets,
        schema_path=args.schema,
        force=args.force,
        skip_sets=args.skip_sets,
        skip_cards=args.skip_cards,
    )


def main(argv: Iterable[str] | None = None) -> int:
    cfg = parse_args(list(argv or sys.argv[1:]))
    try:
        Installer(cfg).run()
    except InstallerError as exc:
        logger.error(f"Error: {exc}")
        return 1
    except FileNotFoundError as exc:
        logger.error(f"Missing file: {exc}")
        return 1
    except psycopg2.OperationalError as exc:
        logger.error(f"Database connection failed: {exc}")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
