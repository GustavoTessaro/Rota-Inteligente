from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import settings


class Base(DeclarativeBase):
    pass


if settings.database_url.startswith("sqlite"):
    sqlite_path = settings.database_url.replace("sqlite:///", "", 1).replace("sqlite://", "", 1)
    database_file = Path(sqlite_path).expanduser().resolve()
    database_file.parent.mkdir(parents=True, exist_ok=True)
    connect_args = {"check_same_thread": False}
else:
    database_file = None
    connect_args = {}

engine = create_engine(settings.database_url, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
