from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import get_settings

settings = get_settings()

connect_url = settings.database_url_or_default

# Zerops provides a normal PostgreSQL connection URL.
# SQLAlchemy defaults postgresql:// to psycopg2.
# InfraPilot installs psycopg v3, so explicitly select that driver.
if connect_url.startswith("postgresql://"):
    connect_url = connect_url.replace(
        "postgresql://",
        "postgresql+psycopg://",
        1,
    )
elif connect_url.startswith("postgres://"):
    connect_url = connect_url.replace(
        "postgres://",
        "postgresql+psycopg://",
        1,
    )

connect_args = (
    {"check_same_thread": False}
    if connect_url.startswith("sqlite")
    else {}
)

engine = create_engine(
    connect_url,
    pool_pre_ping=True,
    connect_args=connect_args,
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


def init_db() -> None:
    from . import models  # noqa: F401

    Base.metadata.create_all(bind=engine)

    try:
        inspector = inspect(engine)

        if "analysis_jobs" in inspector.get_table_names():
            cols = inspector.get_columns("analysis_jobs")
            col_names = [c["name"] for c in cols]

            if "error_hint" not in col_names:
                if engine.dialect.name == "sqlite":
                    with engine.begin() as conn:
                        conn.exec_driver_sql(
                            "ALTER TABLE analysis_jobs "
                            "ADD COLUMN error_hint VARCHAR(200);"
                        )
                    print(
                        "Applied inline migration: "
                        "added error_hint to analysis_jobs (sqlite)"
                    )
                else:
                    print(
                        "Database missing 'error_hint' column. "
                        "Run migrations/0001_add_error_hint.sql"
                    )

    except Exception as exc:
        print("DB init migration check failed:", exc)


def test_db_connection(timeout: float = 5.0) -> tuple[bool, str]:
    try:
        with engine.connect() as conn:
            conn.exec_driver_sql("SELECT 1")
        return True, "ok"
    except Exception as exc:
        return False, str(exc)