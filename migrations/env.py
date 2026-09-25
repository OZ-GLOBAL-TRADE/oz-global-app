import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from jarvis.db import get_engine  # noqa: E402 — proje kökü path'e eklendikten sonra
from jarvis.models import Base  # noqa: E402

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# jarvis.db.get_engine() zaten DATABASE_URL'i (env/secrets, yerelde spark_dev.db/jarvis_dev.db) ve
# postgres:// -> postgresql+psycopg:// normalizasyonunu uyguluyor — burada tekrar yazmıyoruz, uygulamanın
# bağlandığı VERİTABANININ AYNISINA bağlanmak için tek gerçek kaynağı (jarvis.db) kullanıyoruz.
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """'--sql' ile üretim modu: bağlanmadan yalnızca SQL üretir."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def _refuse_implicit_local_db() -> None:
    """DATABASE_URL o terminalde tanımlı değilse config.py sessizce yerel spark_dev.db'ye düşer; Supabase'e
    uygulandığı sanılan bir migration aslında yerel dosyaya gider (2026-09-24'te tam olarak bu oldu)."""
    from jarvis import config
    if config.DATABASE_URL == f"sqlite:///{config._LOCAL_DB}":
        sys.exit("DURDURULDU: DATABASE_URL tanımlı değil, Alembic yerel veritabanına ({}) bağlanacaktı.\n"
                 "Supabase için aynı terminalde önce şunu çalıştırın:  $env:DATABASE_URL = \"postgresql://...\"\n"
                 "Bilerek yerel dosyada çalıştırmak için: $env:DATABASE_URL = \"sqlite:///{}\"".format(config._LOCAL_DB, config._LOCAL_DB))


def run_migrations_online() -> None:
    _refuse_implicit_local_db()
    connectable = get_engine()
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
