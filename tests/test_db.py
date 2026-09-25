import sqlalchemy as sa

from jarvis import db


def test_additive_migration_upgrades_old_tables(tmp_path):
    url = f"sqlite:///{tmp_path / 'old.db'}"
    old = sa.create_engine(url)
    with old.begin() as c:  # önceki sürümün şemasını taklit eder: yeni sütunlar yok
        c.execute(sa.text("CREATE TABLE req_costs (id INTEGER PRIMARY KEY, req_id INTEGER, label VARCHAR(200), amount FLOAT)"))
        c.execute(sa.text("INSERT INTO req_costs (id, req_id, label, amount) VALUES (1, 1, 'Nakliye', 50)"))
        c.execute(sa.text("CREATE TABLE reqs (id INTEGER PRIMARY KEY, company_id INTEGER, code VARCHAR(50), stage VARCHAR(20), tax_pct FLOAT)"))
        c.execute(sa.text("INSERT INTO reqs (id, company_id, code, stage, tax_pct) VALUES (1, 1, 'X_REQ_01', 'talep', 20)"))
    old.dispose()

    db.configure(url)
    db.init_db()
    with db.get_engine().connect() as c:
        req = c.execute(sa.text("SELECT tax_enabled, delivery_type, logistics_mode FROM reqs")).one()
        kind = c.execute(sa.text("SELECT kind FROM req_costs")).scalar_one()
        lines = [col["name"] for col in sa.inspect(c).get_columns("req_lines")]
    assert tuple(req) == (1, "Gümrük Teslim", "dahil")   # mevcut kayıtlar makul varsayılanlarla dolar
    assert kind == "diger" and "unit_logistics" in lines
    db.init_db()  # ikinci çalıştırma zararsız