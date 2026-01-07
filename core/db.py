from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import shutil

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from core.secrets import get_secret

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SEED_DB_PATH = PROJECT_ROOT / "dividends-seed.sqlite3"
LEGACY_DB_PATH = PROJECT_ROOT / "dividends.sqlite3"
DEFAULT_DB_PATH = PROJECT_ROOT / "var" / "dividends.sqlite3"
HOME_DB_PATH = Path.home() / ".dividend-dashboard" / "dividends.sqlite3"


def _resolve_db_path() -> Path:
    override = get_secret("DIVIDENDS_DB_PATH")
    if override:
        candidate = Path(override).expanduser()
        if not candidate.is_absolute():
            candidate = (PROJECT_ROOT / candidate).resolve()
        if not _ensure_sqlite_db(candidate):
            raise RuntimeError(f"지정한 DIVIDENDS_DB_PATH({candidate})를 준비할 수 없습니다.")
        return candidate

    for idx, candidate in enumerate([DEFAULT_DB_PATH, HOME_DB_PATH]):
        if _ensure_sqlite_db(candidate):
            if idx > 0:
                print(f"[core.db] Using fallback DB path: {candidate}", flush=True)
            return candidate

    raise RuntimeError("Writable SQLite path를 찾을 수 없습니다. DIVIDENDS_DB_PATH 또는 DIVIDENDS_DB_URL을 설정해 주세요.")


def _ensure_sqlite_db(path: Path) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            if LEGACY_DB_PATH.exists():
                shutil.copy2(LEGACY_DB_PATH, path)
            elif SEED_DB_PATH.exists():
                shutil.copy2(SEED_DB_PATH, path)
            else:
                path.touch()
        # check writability
        with path.open("ab"):
            pass
        return True
    except OSError:
        return False


DB_URL_OVERRIDE = get_secret("DIVIDENDS_DB_URL")
if DB_URL_OVERRIDE:
    DB_PATH: Path | None = None
    DB_URL = DB_URL_OVERRIDE
else:
    DB_PATH = _resolve_db_path()
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
