import pytest

from jarvis import db, seed, services as sv


@pytest.fixture
def s(tmp_path):
    db.configure(f"sqlite:///{tmp_path / 'test.db'}")
    with db.session_scope() as session:
        seed.bootstrap(session)
        yield session


def actor(s, username):
    return sv.to_actor(next(u for u in sv.list_users(s) if u.username == username))


@pytest.fixture
def world(s):
    admin, eren, beyza, broker = (actor(s, n) for n in ("yusuf.oz", "eren.memisoglu", "beyza.yazar", "gumruk.ofis"))
    cust = sv.add_partner(s, admin, name="TİTRA TEKNOLOJİ", is_customer=True, short_code="TTRA", req_seq=16)
    prods = [sv.add_product(s, admin, name=n) for n in ("ESC", "Motor")]
    return dict(admin=admin, eren=eren, beyza=beyza, broker=broker, cust=cust, prods=prods)


def new_req(s, w, who="eren", **kw):
    return sv.create_req(s, w[who], customer_id=w["cust"].id, items=[(w["prods"][0].id, 10), (w["prods"][1].id, 6)], **kw)
