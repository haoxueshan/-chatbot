from pathlib import Path
from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker
from app.config import settings

Path(settings.data_dir).mkdir(parents=True, exist_ok=True)
Base = declarative_base()
engine = create_engine(settings.database_url, pool_pre_ping=True,
                       connect_args={'check_same_thread': False} if settings.database_url.startswith('sqlite') else {})
if settings.database_url.startswith('sqlite'):
    @event.listens_for(engine, 'connect')
    def sqlite_pragmas(dbapi, _):
        dbapi.execute('PRAGMA foreign_keys=ON')
        dbapi.execute('PRAGMA journal_mode=WAL')
        dbapi.execute('PRAGMA busy_timeout=10000')
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def get_db():
    with SessionLocal() as db:
        yield db


def init_db():
    import app.models  # noqa
    from sqlalchemy import text
    if engine.dialect.name == 'postgresql':
        with engine.begin() as conn:
            conn.execute(text('CREATE EXTENSION IF NOT EXISTS vector'))
    Base.metadata.create_all(engine)
