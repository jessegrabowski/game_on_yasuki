import argparse
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from collections.abc import Iterable
import shutil

import psycopg
from psycopg import sql as pgsql

from yasuki_core import DATABASE_DIR
from yasuki_core.database import get_connection_string, mask_dsn
from yasuki_core.install import images_to_sql, sets_to_sql, yaml_to_sql
from yasuki_core.install.format_metadata import populate_format_metadata
import logging


logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


DEFAULT_CARDS_PATH = DATABASE_DIR / "sets"
DEFAULT_SETS_PATH = DATABASE_DIR / "set_info.yaml"
DEFAULT_IMAGES_PATH = DATABASE_DIR / "images"
DEFAULT_SCHEMA_PATH = DATABASE_DIR / "schema.sql"
DEFAULT_DSN = get_connection_string()


@dataclass
class InstallerConfig:
    dsn: str
    cards_path: Path
    sets_path: Path
    images_path: Path
    schema_path: Path
    force: bool
    skip_sets: bool
    skip_cards: bool
    ensure_readonly_role: bool = False
    format_metadata_only: bool = False


class InstallerError(RuntimeError):
    pass


class Installer:
    def __init__(self, cfg: InstallerConfig):
        self.cfg = cfg

    def run(self) -> None:
        # A standalone, schema-free path so the role can be (re)provisioned on an already-seeded
        # database without re-running the installer.
        if self.cfg.ensure_readonly_role:
            self._provision_readonly_role()
            return

        if self.cfg.format_metadata_only:
            with psycopg.connect(self.cfg.dsn, autocommit=True) as conn, conn.cursor() as cur:
                populate_format_metadata(cur)
            logger.info("Populated format metadata (arc, block, legal_from)")
            return

        self._validate_prerequisites()
        self._validate_files()
        self._ensure_database_exists()

        logger.info("Connecting to database")
        with psycopg.connect(self.cfg.dsn, autocommit=False) as conn:
            with conn.cursor() as cur:
                if self._schema_exists(cur):
                    if self.cfg.force:
                        self._reset_schema(cur)
                        self._apply_schema(cur)
                    else:
                        logger.info("Schema already exists, will upsert data")
                else:
                    self._apply_schema(cur)
                conn.commit()

        if not self.cfg.skip_sets:
            logger.info("Loading set metadata")
            sets_to_sql.load_l5r_sets(self.cfg.sets_path, self.cfg.dsn)
        else:
            logger.info("Skipping set metadata import")

        if not self.cfg.skip_cards:
            logger.info("Loading cards")
            yaml_to_sql.load_cards(self.cfg.cards_path, self.cfg.dsn)
            logger.info("Loading print images")
            images_to_sql.load_print_images(self.cfg.images_path, self.cfg.dsn)
            images_to_sql.apply_errata_art(self.cfg.dsn)
            images_to_sql.seed_card_backs(self.cfg.dsn)
        else:
            logger.info("Skipping card import")

        self._provision_readonly_role()

        logger.info("Database installation complete")

    def _validate_prerequisites(self) -> None:
        """Check if PostgreSQL tools are available on the system."""
        if not shutil.which("psql"):
            logger.warning(
                "PostgreSQL client tools (psql) not found on PATH. "
                "This is fine for Docker/cloud deployments, but local users may need to install PostgreSQL."
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
            missing.append(f"Cards directory: {self.cfg.cards_path}")

        if missing:
            raise InstallerError("Missing required files:\n  " + "\n  ".join(missing))

    def _ensure_database_exists(self) -> None:
        """Check if the database exists and offer to create it if it doesn't."""
        try:
            with psycopg.connect(self.cfg.dsn, connect_timeout=10) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT version();")
                    logger.info("Connected to database successfully")
        except psycopg.OperationalError as e:
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
                    "  - Check connection string: " + mask_dsn(self.cfg.dsn)
                )
            elif "authentication failed" in error_msg or "password" in error_msg:
                raise InstallerError(
                    f"Authentication failed. Check your credentials in the DSN:\n"
                    f"  Current DSN: {mask_dsn(self.cfg.dsn)}\n"
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

    def _provision_readonly_role(self) -> None:
        """Create or update a least-privilege read-only login role, if configured.

        Driven by ``POSTGRES_RO_USER`` / ``POSTGRES_RO_PASSWORD``; a no-op when either is unset, so
        existing single-role setups are unaffected. The role gets only CONNECT + schema USAGE +
        SELECT (current and future tables). Idempotent: re-running refreshes the password and
        re-applies the grants.
        """
        ro_user = os.environ.get("POSTGRES_RO_USER")
        ro_password = os.environ.get("POSTGRES_RO_PASSWORD")
        if not (ro_user and ro_password):
            return

        db_name = self._extract_db_name_from_dsn(self.cfg.dsn)
        role = pgsql.Identifier(ro_user)
        with psycopg.connect(self.cfg.dsn, autocommit=True) as conn, conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (ro_user,))
            action = "ALTER" if cur.fetchone() else "CREATE"
            cur.execute(
                pgsql.SQL("{} ROLE {} WITH LOGIN PASSWORD {}").format(
                    pgsql.SQL(action), role, pgsql.Literal(ro_password)
                )
            )
            cur.execute(
                pgsql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                    pgsql.Identifier(db_name), role
                )
            )
            cur.execute(pgsql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(role))
            cur.execute(pgsql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA public TO {}").format(role))
            cur.execute(
                pgsql.SQL(
                    "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO {}"
                ).format(role)
            )
        logger.info("Provisioned read-only role '%s'", ro_user)

    def _reset_schema(self, cur) -> None:
        # The role that recreates the schema owns it, so no grant is needed. PUBLIC is intentionally
        # left without privileges; a read-only role gets scoped USAGE + SELECT separately.
        print("Existing schema detected. Dropping public schema …")
        cur.execute("DROP SCHEMA IF EXISTS public CASCADE;")
        cur.execute("CREATE SCHEMA public;")


def parse_args(argv: list[str]) -> InstallerConfig:
    parser = argparse.ArgumentParser(description="Initialize the L5R database")
    parser.add_argument(
        "--dsn",
        default=DEFAULT_DSN,
        help="PostgreSQL DSN, defaults to %(default)s or $YASUKI_DATABASE_URL",
    )
    parser.add_argument(
        "--cards",
        type=Path,
        default=DEFAULT_CARDS_PATH,
        help="Path to per-set YAML directory (default: %(default)s)",
    )
    parser.add_argument(
        "--sets",
        type=Path,
        default=DEFAULT_SETS_PATH,
        help="Path to set info YAML (default: %(default)s)",
    )
    parser.add_argument(
        "--images",
        type=Path,
        default=DEFAULT_IMAGES_PATH,
        help="Path to per-set image manifest directory (default: %(default)s)",
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
    parser.add_argument(
        "--ensure-readonly-role",
        action="store_true",
        help="Only provision the read-only role from POSTGRES_RO_USER/PASSWORD, then exit",
    )
    parser.add_argument(
        "--format-metadata",
        action="store_true",
        help="Only (re)populate formats.arc/block/legal_from on an existing database, then exit",
    )
    args = parser.parse_args(argv)

    return InstallerConfig(
        dsn=args.dsn,
        cards_path=args.cards,
        sets_path=args.sets,
        images_path=args.images,
        schema_path=args.schema,
        force=args.force,
        skip_sets=args.skip_sets,
        skip_cards=args.skip_cards,
        ensure_readonly_role=args.ensure_readonly_role,
        format_metadata_only=args.format_metadata,
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
    except psycopg.OperationalError as exc:
        logger.error(f"Database connection failed: {exc}")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
