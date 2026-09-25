"""Kurulum ve demo veri.
  python -m jarvis.seed              -> tablolar + ekip kullanıcıları (idempotent)
  python -m jarvis.seed --demo       -> her yönetici için 2'şer örnek REQ (yalnızca sistemi denemek için)
  python -m jarvis.seed --purge-demo -> demo kayıtlarını siler; gerçek verilere dokunmaz"""
import sys

from sqlalchemy import delete, select

from jarvis import pipeline as pl, services as sv
from jarvis.db import init_db, session_scope
from jarvis.models import Partner, Product, Req, User

BASE_USERS = [
    ("yusuf.oz", "Yusuf Öz", pl.ADMIN),
    ("eren.memisoglu", "Eren Memişoğlu", pl.TRADE_MANAGER),
    ("beyza.yazar", "Beyza Yazar", pl.TRADE_MANAGER),
    ("eren.zorman", "Eren Zorman", pl.TRADE_MANAGER),
    ("zerrin.oz", "Zerrin Öz", pl.TRADE_MANAGER),
    ("gumruk.ofis", "Gümrük Operasyon", pl.CUSTOMS_BROKER),
]

DEMO_CUSTOMERS = [("Demo Savunma A.Ş.", "DMS", "Savunma"), ("Demo Havacılık Ltd.", "DMH", "Ticari")]
DEMO_SUPPLIERS = [("Demo Tedarikçi HK", "Elektronik", "esc, motor, alıcı, vtx", "Hong Kong"), ("Demo Motor Ltd.", "İtki & Güç", "motor, pervane, batarya", "China")]
# (ad, GTİP, birim alış, adet) — TTRA_REQ_17'deki gerçek birim maliyetlerden alındı.
DEMO_PRODUCTS = [
    ("FLYCOLOR X-Cross HV3 5-12S 120A ESC", "8543.70", 132.95, 10),
    ("Hobbywing 4218 560KV Motor", "8501.31", 77.08, 6),
    ("TBS Crossfire 8Ch Diversity Rx", "8517.62", 176.72, 2),
    ("RushFPV 3.3GHz 4W VTX", "8517.62", 90.72, 7),
]
DEMO_COST = {name: cost for name, _, cost, _ in DEMO_PRODUCTS}
DEMO_STAGES = ["talep", "fiyat", "gumruk", "teklif", "karar", "siparis", "lojistik", "teslim"]


def bootstrap(s):
    """Tablolar, şirket ve ekip kullanıcıları. Var olanlara dokunmaz."""
    init_db()
    company = sv.ensure_company(s)
    for username, name, role in BASE_USERS: sv.ensure_user(s, company, username, name, role)
    return company


def _actor(s, username):
    return sv.to_actor(s.scalar(select(User).where(User.username == username)))


def _progress(s, req_id, target, owner, broker):
    """Demo REQ'yi gerçek iş akışı kapılarından geçirerek hedef aşamaya taşır."""
    for stage in DEMO_STAGES[:DEMO_STAGES.index(target)]:
        req = sv.get_req(s, owner, req_id=req_id)
        actor = broker if stage == "gumruk" else owner
        if stage == "fiyat":
            sv.save_line_values(s, actor, req, "unit_cost", [{"id": l.id, "value": DEMO_COST.get(l.name, 10.0)} for l in req.lines])
        elif stage == "gumruk":
            sv.save_line_values(s, actor, req, "unit_customs", [{"id": l.id, "value": 3.3} for l in req.lines])
            sv.save_line_values(s, actor, req, "unit_logistics", [{"id": l.id, "value": 2.0} for l in req.lines])
            sv.save_costs(s, actor, req, [{"label": "Genel nakliye", "amount": 120.0, "kind": "lojistik"}])
        elif stage == "teklif":
            # Çeşitlilik için: bazı demo tekliflerde KDV yok, bazılarında lojistik ayrı kalem.
            variant = {"karar": dict(tax_enabled=False), "siparis": dict(logistics_mode="ayri")}.get(target, {})
            sv.update_fields(s, actor, req, margin_pct=20.0, payment_terms="%50 peşin, %50 sevkiyat öncesi", **variant)
            sv.mark_quote_sent(s, actor, req)
        elif stage == "karar":
            sv.decide(s, actor, req, True)
            continue
        elif stage == "siparis":
            sv.set_po_approved(s, actor, req, True)
        sv.advance_req(s, actor, req)


def load_demo(s):
    company = bootstrap(s)
    admin = _actor(s, "yusuf.oz")
    broker = _actor(s, "gumruk.ofis")
    customers = []
    for name, code, kind in DEMO_CUSTOMERS:
        customers.append(s.scalar(select(Partner).where(Partner.name == name)) or sv.add_partner(s, admin, name=name, is_customer=True, short_code=code, kind=kind, is_demo=True))
    for name, cat, keywords, country in DEMO_SUPPLIERS:
        if not s.scalar(select(Partner).where(Partner.name == name)):
            sv.add_partner(s, admin, name=name, is_supplier=True, category=cat, keywords=keywords, country=country, is_demo=True)
    products = []
    for name, hs, cost, _ in DEMO_PRODUCTS:
        products.append(s.scalar(select(Product).where(Product.name == name)) or sv.add_product(s, admin, name=name, hs_code=hs, last_cost=cost, category="Elektronik", is_demo=True))

    managers = [u for u in sv.list_users(s) if u.role == pl.TRADE_MANAGER]
    stage_iter = iter(DEMO_STAGES)
    for user in managers:
        owner = sv.to_actor(user)
        for i in range(2):
            target = next(stage_iter, "talep")
            items = [(p.id, q) for p, (_, _, _, q) in zip(products, DEMO_PRODUCTS)][: 2 + (i * 2)]
            req = sv.create_req(s, owner, customer_id=customers[i % 2].id, items=items, currency="USD",
                                 delivery_type="Kapı Teslim" if i else "Gümrük Teslim", notes="Demo kayıt", is_demo=True)
            _progress(s, req.id, target, owner, broker)
    return company


def purge_demo(s) -> dict:
    """Yalnızca is_demo işaretli kayıtları siler (REQ satırları, masraflar ve geçmiş dahil)."""
    req_ids = list(s.scalars(select(Req.id).where(Req.is_demo.is_(True))))
    for req in s.scalars(select(Req).where(Req.id.in_(req_ids))): s.delete(req)
    s.flush()
    products = s.execute(delete(Product).where(Product.is_demo.is_(True))).rowcount
    partners = s.execute(delete(Partner).where(Partner.is_demo.is_(True))).rowcount
    s.commit()
    return {"req": len(req_ids), "urun": products, "kisi": partners}


if __name__ == "__main__":
    with session_scope() as session:
        if "--purge-demo" in sys.argv: print("Silindi:", purge_demo(session))
        elif "--demo" in sys.argv:
            load_demo(session)
            print("Demo veri yüklendi.")
        else:
            bootstrap(session)
            print("Kurulum tamam.")
