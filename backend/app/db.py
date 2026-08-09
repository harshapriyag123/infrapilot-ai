from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import get_settings

settings = get_settings()
connect_url = settings.database_url_or_default
connect_args = {"check_same_thread": False} if connect_url.startswith("sqlite") else {}
engine = create_engine(connect_url, pool_pre_ping=True, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def init_db() -> None:
    from . import models  # noqa: F401
    Base.metadata.create_all(bind=engine)
    # Ensure new columns added by code (e.g. error_hint) exist on legacy DBs.
    try:
        inspector = inspect(engine)
        if "analysis_jobs" in inspector.get_table_names():
            cols = [{"name": c["name"]} for c in inspector.get_columns("analysis_jobs")]
            col_names = [c["name"] for c in cols]
            if "error_hint" not in col_names:
                if engine.dialect.name == "sqlite":
                    with engine.connect() as conn:
                        conn.exec_driver_sql("ALTER TABLE analysis_jobs ADD COLUMN error_hint VARCHAR(200);")
                        print("Applied inline migration: added error_hint to analysis_jobs (sqlite)")
                else:
                    print("Database missing 'error_hint' column. Run migration for your DB:")
                    print("See migrations/0001_add_error_hint.sql")
    except Exception as exc:
        print("DB init migration check failed:", exc)


def test_db_connection(timeout: float = 5.0) -> tuple[bool, str]:
    """Try a simple DB connection and return (ok, message)."""
    try:
        with engine.connect() as conn:
            # lightweight check
            # Use the driver-level execution API for SQLAlchemy 2.0 compatibility
            conn.exec_driver_sql("SELECT 1")
        return True, "ok"
    except Exception as exc:
        return False, str(exc)
