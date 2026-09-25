"""Veritabanı bağlantı kontrolü. Parola hiçbir zaman yazdırılmaz.
  py -m jarvis.check_db
Hedef, DATABASE_URL (ortam değişkeni, .env veya .streamlit/secrets.toml) ile belirlenir; yoksa yerel SQLite kullanılır."""
import sys

from sqlalchemy import func, inspect, select, text
from sqlalchemy.engine import make_url

from jarvis import config
from jarvis.db import _normalize, get_engine, init_db, session_scope
from jarvis.models import Req, User

HINTS = """
Olası nedenler:
  - Parolada @ : / ? # gibi özel karakter varsa bağlantı adresinde kodlanmalı (@ -> %40, : -> %3A, / -> %2F).
  - Supabase'de 'Connect' düğmesinden "Session pooler" (veya Transaction pooler) bağlantı adresini kullanın;
    doğrudan bağlantı yalnızca IPv6 destekler ve Streamlit Cloud gibi ortamlarda çalışmayabilir.
  - Adres şu biçimde olmalı: postgresql://KULLANICI:PAROLA@SUNUCU:PORT/postgres
  - Tarayıcıdaki Streamlit Cloud için değeri Settings > Secrets bölümüne DATABASE_URL = "..." olarak yazın."""


def main() -> int:
    raw = config.DATABASE_URL
    try:
        url = make_url(_normalize(raw))
        print(f"Hedef    : {url.render_as_string(hide_password=True)}")
        engine = get_engine()
        with engine.connect() as conn:
            version = conn.execute(text("select sqlite_version()" if engine.dialect.name == "sqlite" else "select version()")).scalar()
        print(f"Bağlantı : OK ({engine.dialect.name}) {version}")
        init_db()
        print("Tablolar :", ", ".join(sorted(inspect(engine).get_table_names())))
        with session_scope() as s:
            print("Kayıtlar : kullanıcı", s.scalar(select(func.count()).select_from(User)), "| REQ", s.scalar(select(func.count()).select_from(Req)))
    except Exception as e:
        message = (str(e).splitlines() or [""])[0]
        for secret in (raw, _normalize(raw)): message = message.replace(secret, "<gizli>")
        print(f"HATA     : {type(e).__name__}: {message}")
        print(HINTS)
        return 1
    if engine.dialect.name == "sqlite": print("Not      : SQLite yerel/geçici. Kalıcı veri için DATABASE_URL (Supabase) tanımlayın.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
