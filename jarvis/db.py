from contextlib import contextmanager

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import sessionmaker

from jarvis import config
from jarvis.models import Base

_engine = None
_Session = None


def _normalize(url: str) -> str:
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix): return "postgresql+psycopg://" + url[len(prefix):]
    return url


def get_engine():
    global _engine, _Session
    if _engine is None:
        url = _normalize(config.DATABASE_URL)
        if url.startswith("sqlite"):
            _engine = create_engine(url, connect_args={"check_same_thread": False})
            event.listen(_engine, "connect", lambda conn, _: conn.execute("PRAGMA foreign_keys=ON"))
        else:
            # prepare_threshold=None: Supabase havuzlayıcısı (pgbouncer) ile uyumlu olması için.
            _engine = create_engine(url, pool_pre_ping=True, pool_recycle=300, connect_args={"prepare_threshold": None})
        _Session = sessionmaker(_engine, expire_on_commit=False)
    return _engine


def configure(url: str):
    """Testler ve betikler için: farklı bir veritabanına geç."""
    global _engine
    if _engine is not None: _engine.dispose()
    _engine = None
    config.DATABASE_URL = url


def backend_name() -> str:
    """Bağlı veritabanı türü (sqlite: yerel/geçici, postgresql: kalıcı); arayüzde göstermek için."""
    return get_engine().dialect.name


def _migrate_additive(engine):
    """Sonradan modele eklenen sütunları mevcut tablolara ekler. Yalnızca ekleme yapar (silme/yeniden adlandırma yok).
    Alembic eklendikten sonra (bkz. migrations/) YENİ şema değişiklikleri artık `alembic revision --autogenerate`
    ile yapılır; bu fonksiyon yalnızca eski (Alembic öncesi) deploy'lar için geriye dönük bir güvenlik ağı olarak
    kalıyor — zararsız (idempotent, yalnızca eksik sütunu ekler), silinmesine gerek yok."""
    inspector = inspect(engine)
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if not inspector.has_table(table.name): continue
            existing = {c["name"] for c in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in existing: continue
                ddl = f"ALTER TABLE {table.name} ADD COLUMN {column.name} {column.type.compile(dialect=engine.dialect)}"
                if column.server_default is not None:
                    arg = column.server_default.arg
                    ddl += " DEFAULT " + (f"'{arg}'" if isinstance(arg, str) else str(arg.compile(dialect=engine.dialect)))
                conn.execute(text(ddl))


def init_db():
    engine = get_engine()
    Base.metadata.create_all(engine)
    _migrate_additive(engine)


@contextmanager
def session_scope():
    """Servis fonksiyonları yazma sonrası kendi commit'ini yapar; burada yalnızca kapatılır."""
    get_engine()
    session = _Session()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
