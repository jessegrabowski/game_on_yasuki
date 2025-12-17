from pathlib import Path

import psycopg2
import pytest

from app.install import install_db


class DummyCursor:
    def __init__(self, tables_exist: bool = False):
        self.tables_exist = tables_exist
        self.executed: list[str] = []
        self.result = [(False,)]

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, *args, **kwargs):
        self.executed.append(sql)
        if "SELECT EXISTS" in sql:
            self.result = [(self.tables_exist,)]

    def fetchone(self):
        return self.result[0]


class DummyConnection:
    def __init__(self, cursor: DummyCursor):
        self.cursor_instance = cursor
        self.closed = False
        self.autocommit = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.closed = True
        return False

    def cursor(self):
        return self.cursor_instance

    def commit(self):
        pass


class DummyImporter:
    def __init__(self):
        self.called = False

    def __call__(self, *args, **kwargs):
        self.called = True


def test_schema_exists_without_force_raises(monkeypatch):
    cur = DummyCursor(tables_exist=True)
    conn = DummyConnection(cur)
    monkeypatch.setattr(psycopg2, "connect", lambda dsn: conn)

    cfg = install_db.InstallerConfig(
        dsn="fake",
        cards_path=Path("cards.json"),
        sets_path=Path("sets.json"),
        schema_path=Path("schema.sql"),
        force=False,
        skip_sets=True,
        skip_cards=True,
    )

    installer = install_db.Installer(cfg)
    with monkeypatch.context() as m:
        m.setattr(installer, "_validate_prerequisites", lambda: None)
        m.setattr(installer, "_validate_files", lambda: None)
        m.setattr(installer, "_ensure_database_exists", lambda: None)

        with pytest.raises(install_db.InstallerError):
            installer.run()


def test_force_drop_calls_reset(monkeypatch):
    cur = DummyCursor(tables_exist=True)
    conn = DummyConnection(cur)
    monkeypatch.setattr(psycopg2, "connect", lambda dsn: conn)

    called_reset = False

    class TestInstaller(install_db.Installer):
        def _reset_schema(self, cursor):
            nonlocal called_reset
            called_reset = True
            super()._reset_schema(cursor)

        def _apply_schema(self, cursor):
            pass

    cfg = install_db.InstallerConfig(
        dsn="fake",
        cards_path=Path("cards.json"),
        sets_path=Path("sets.json"),
        schema_path=Path("schema.sql"),
        force=True,
        skip_sets=True,
        skip_cards=True,
    )

    installer = TestInstaller(cfg)
    monkeypatch.setattr(installer, "_validate_prerequisites", lambda: None)
    monkeypatch.setattr(installer, "_validate_files", lambda: None)
    monkeypatch.setattr(installer, "_ensure_database_exists", lambda: None)

    installer.run()

    assert called_reset
