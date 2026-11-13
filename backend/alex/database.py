"""SQLite via SQLAlchemy. One file under the data directory."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from alex.config import get_settings
from alex.models import Base

engine = None
SessionLocal: sessionmaker[Session] | None = None


def reset_engine() -> None:
    global engine, SessionLocal
    if engine is not None:
        engine.dispose()
    settings = get_settings()
    settings.data_path.mkdir(parents=True, exist_ok=True)
    db_path = settings.database_path
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )

    @event.listens_for(engine, "connect")
    def _pragma(dbapi_conn, _connection_record) -> None:  # noqa: ANN001
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def init_db() -> None:
    from alex.config import migrate_legacy_install

    migrate_legacy_install()
    if engine is None or SessionLocal is None:
        reset_engine()
    assert engine is not None
    Base.metadata.create_all(engine)
    _ensure_setting_columns()
    from alex.projects.service import seed_defaults

    with session_scope() as db:
        seed_defaults(db)


def _ensure_setting_columns() -> None:
    """Old databases predate columns added after the first install."""
    from sqlalchemy import inspect, text

    assert engine is not None
    tables = inspect(engine).get_table_names()
    if "app_settings" not in tables:
        return
    present = {column["name"] for column in inspect(engine).get_columns("app_settings")}
    additions = {
        "computer_use_enabled": "BOOLEAN DEFAULT 0",
        "computer_use_max_steps": "INTEGER DEFAULT 12",
        "voice_wake": "BOOLEAN DEFAULT 0",
        "wake_phrase": "VARCHAR(80) DEFAULT 'alex'",
    }
    with engine.begin() as connection:
        for name, ddl in additions.items():
            if name not in present:
                connection.execute(text(f"ALTER TABLE app_settings ADD COLUMN {name} {ddl}"))


@contextmanager
def session_scope() -> Iterator[Session]:
    if SessionLocal is None:
        reset_engine()
    assert SessionLocal is not None
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def get_db() -> Iterator[Session]:
    with session_scope() as db:
        yield db
