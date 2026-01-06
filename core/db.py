from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = PROJECT_ROOT / "dividends.sqlite3"
DB_URL = f"sqlite:///{DB_PATH.as_posix()}"

engine = create_engine(
    DB_URL,
    echo=False,
    future=True,
    connect_args={"check_same_thread": False},  # Streamlit multi-thread 대응
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    future=True,
    expire_on_commit=False,
)


@contextmanager
def db_session():
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def run_simple_migrations() -> None:
    """Perform minimal ALTER TABLE operations for backward-compatible schema updates."""

    with engine.begin() as conn:
        table_exists = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='holding_lots'")
        ).scalar_one_or_none()
        if not table_exists:
            return

        columns = {
            row["name"]
            for row in conn.execute(text("PRAGMA table_info('holding_lots')")).mappings()
        }

        def add_column(name: str, ddl: str) -> None:
            if name not in columns:
                conn.execute(text(f"ALTER TABLE holding_lots ADD COLUMN {name} {ddl}"))
                columns.add(name)

        add_column("side", "VARCHAR(8) DEFAULT 'BUY'")
        add_column("currency", "VARCHAR(8) DEFAULT 'KRW'")
        add_column("fx_rate", "FLOAT DEFAULT 1.0")
        add_column("price_krw", "FLOAT")
        add_column("amount_krw", "FLOAT")
        add_column("note", "TEXT")
        add_column("source", "VARCHAR(32) DEFAULT 'manual'")
        add_column("created_at", "DATETIME DEFAULT CURRENT_TIMESTAMP")
        add_column("updated_at", "DATETIME DEFAULT CURRENT_TIMESTAMP")
