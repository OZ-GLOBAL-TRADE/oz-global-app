"""Panel için hesaplamalar: REQ tablosu ve aşama bazlı ortalama süreler (eski dashboard + analitik sekmelerinin karşılığı)."""
from collections import defaultdict
from datetime import timezone

import pandas as pd
from sqlalchemy import select

from jarvis import fx, pipeline as pl
from jarvis.models import Event

REQ_COLUMNS = ["id", "REQ", "Müşteri", "Yönetici", "Aşama", "Durum", "Para Birimi", "Maliyet", "Teklif", "Kâr", "Güncelleme",
               "Açılış", "Karar"]
PRODUCT_COLUMNS = ["REQ", "Ürün", "Müşteri", "Yönetici", "Durum", "Para Birimi", "Adet", "Maliyet", "Satış", "Kâr"]


def _aware(dt):
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def fmt_duration(days: float | None) -> str:
    """0.1 gün gibi anlamsız ondalıklar yerine okunur süre: '2 gün 5 saat', '3 saat 20 dk', '15 dk'."""
    if days is None or days <= 0: return "-"
    minutes = round(days * 24 * 60)
    d, rem = divmod(minutes, 24 * 60)
    h, m = divmod(rem, 60)
    if d: return f"{d} gün {h} saat" if h else f"{d} gün"
    if h: return f"{h} saat {m} dk" if m else f"{h} saat"
    return f"{max(m, 1)} dk"


def reqs_frame(reqs) -> pd.DataFrame:
    rows = []
    for r in reqs:
        q = pl.quote_for_req(r)
        priced = r.margin_pct is not None
        rows.append({"id": r.id, "REQ": r.code, "Müşteri": r.customer.name, "Yönetici": r.owner.name, "Aşama": r.stage,
                     "Durum": r.status, "Para Birimi": r.currency, "Maliyet": q.cost_total,
                     "Teklif": q.total if priced else None, "Kâr": q.profit if priced else None, "Güncelleme": r.updated_at,
                     "Açılış": r.created_at, "Karar": r.decision})
    return pd.DataFrame(rows, columns=REQ_COLUMNS)


def product_frame(reqs) -> pd.DataFrame:
    """Fiyatlanmış (marjı girilmiş), rafa kaldırılmamış REQ'lerin ürün satırları: ürün bazlı satış/maliyet/kâr analizi için.
    Satış ve maliyet, teklif hesabının kendisinden (pipeline.calculate_quote) gelir; ekstra masraflar satırlara dağıtılmış haldedir."""
    rows = []
    for r in reqs:
        if r.margin_pct is None or r.status == pl.SHELVED: continue
        for row in pl.quote_for_req(r).rows:
            if row["kind"] != "urun": continue
            rows.append({"REQ": r.code, "Ürün": row["name"], "Müşteri": r.customer.name, "Yönetici": r.owner.name,
                         "Durum": r.status, "Para Birimi": r.currency, "Adet": row["qty"], "Maliyet": row["cost"],
                         "Satış": row["line_total"], "Kâr": round(row["line_total"] - row["cost"], 2)})
    return pd.DataFrame(rows, columns=PRODUCT_COLUMNS)


def _convert_column(df, amount_col, cur_col, target, rates):
    """Her satırı kendi para biriminden `target`'a çevirir; kur yoksa yalnızca zaten o para birimindekiler sayılır
    (diğerleri NaN kalır). panel.py::_convert_column ile aynı kural."""
    def one(r):
        if pd.isna(r[amount_col]): return None
        return fx.convert(r[amount_col], r[cur_col], target, rates) if rates else (r[amount_col] if r[cur_col] == target else None)
    return df.apply(one, axis=1) if not df.empty else pd.Series(dtype=float)


def _num(v, digits: int = 2):
    """JSON'a güvenle yazılabilir sayı: NaN/None → None."""
    return None if v is None or pd.isna(v) else round(float(v), digits)


def _by(frame, key, top: int | None = None):
    grouped = frame.groupby(key, as_index=False)[["Teklif_c", "Kâr_c"]].sum().sort_values("Teklif_c", ascending=False)
    if top: grouped = grouped.head(top)
    return [{"name": r[key], "offer": _num(r["Teklif_c"]), "profit": _num(r["Kâr_c"])} for _, r in grouped.iterrows()]


def product_summary(products: pd.DataFrame, cur: str, rates) -> dict:
    """Ürün bazlı analiz (panel.py::_products_tab'ın veri kısmı): en kârlı 10, en düşük marjlı 8 ve tam tablo — `cur` biriminde."""
    empty = {"top_profit": [], "lowest_margin": [], "table": []}
    if products.empty: return empty
    p = products.copy()
    for col in ("Maliyet", "Satış", "Kâr"): p[col] = _convert_column(p, col, "Para Birimi", cur, rates)
    p = p[p["Satış"].notna()]
    if p.empty: return empty
    by_prod = p.groupby("Ürün", as_index=False).agg(Adet=("Adet", "sum"), Satış=("Satış", "sum"), Maliyet=("Maliyet", "sum"),
                                                    Kâr=("Kâr", "sum"), REQ=("REQ", "nunique"))
    by_prod["Marj"] = by_prod["Kâr"] / by_prod["Maliyet"].where(by_prod["Maliyet"] > 0) * 100
    row = lambda r: {"name": r["Ürün"], "qty": _num(r["Adet"], 3), "sale": _num(r["Satış"]), "cost": _num(r["Maliyet"]),
                     "profit": _num(r["Kâr"]), "req_count": int(r["REQ"]), "margin_pct": _num(r["Marj"], 1)}
    return {"top_profit": [row(r) for _, r in by_prod.sort_values("Kâr", ascending=False).head(10).iterrows()],
            "lowest_margin": [row(r) for _, r in by_prod.dropna(subset=["Marj"]).sort_values("Marj").head(8).iterrows()],
            "table": [row(r) for _, r in by_prod.sort_values("Satış", ascending=False).iterrows()]}


def financial_summary(df: pd.DataFrame, products: pd.DataFrame, cur: str, rates) -> dict:
    """Panel 'Teklif & Kâr' bölümünün verisi (panel.py::_financials'ın hesap kısmı). Tüm fiyatlanmış, rafa kaldırılmamış
    teklifler güncel kurla `cur`'a çevrilir (`rates` = fx.get_rates("USD") ya da None); çevrilemeyenler toplamlara girmez
    ve `missing` ile bildirilir. Hiç fiyatlanmış teklif yoksa {"priced": False}."""
    priced = df[df["Teklif"].notna() & (df["Durum"] != pl.SHELVED)].copy()
    if priced.empty: return {"priced": False}
    priced["Teklif_c"] = _convert_column(priced, "Teklif", "Para Birimi", cur, rates)
    priced["Kâr_c"] = _convert_column(priced, "Kâr", "Para Birimi", cur, rates)
    missing = int(priced["Teklif_c"].isna().sum())
    priced = priced[priced["Teklif_c"].notna()]
    offer, profit = float(priced["Teklif_c"].sum()), float(priced["Kâr_c"].sum())
    decided = int(df["Karar"].isin(["onay", "ret"]).sum())
    wins = int((df["Karar"] == "onay").sum())

    month = lambda col: pd.to_datetime(col, utc=True).dt.strftime("%Y-%m")
    opened = df.assign(Ay=month(df["Açılış"])).groupby("Ay").size()
    offers = priced.assign(Ay=month(priced["Açılış"])).groupby("Ay")["Teklif_c"].sum() if not priced.empty else pd.Series(dtype=float)
    months = sorted(set(opened.index) | set(offers.index))
    return {
        "priced": True, "currency": cur, "missing": missing,
        "rates": {c: _num(rates[c], 4) for c in ("EUR", "TRY") if rates and c in rates} if rates else None,
        "total_offer": round(offer, 2), "total_profit": round(profit, 2),
        "margin_on_cost_pct": round(profit / (offer - profit) * 100, 1) if offer > profit else None,
        "win_rate_pct": round(wins / decided * 100) if decided else None, "decided": decided, "wins": wins,
        "by_manager": _by(priced, "Yönetici"), "by_customer": _by(priced, "Müşteri", top=10),
        "monthly": [{"month": m, "opened": int(opened.get(m, 0)), "offer": _num(offers.get(m, 0.0))} for m in months],
        "products": product_summary(products, cur, rates),
    }


def _stage_exits(s, reqs):
    """Her REQ için (aşama, o aşamada geçen gün, çıkış anı) — açılış anından ve her ileri/geri geçiş olayından hesaplanır."""
    ids = [r.id for r in reqs]
    if not ids: return []
    arrival = {r.id: _aware(r.created_at) for r in reqs}
    out = []
    events = s.scalars(select(Event).where(Event.req_id.in_(ids), Event.kind.in_(("stage", "status")),
                                           Event.from_stage.is_not(None)).order_by(Event.id))
    for e in events:
        at = _aware(e.created_at)
        out.append((e.req_id, e.from_stage, (at - arrival[e.req_id]).total_seconds() / 86400, at))
        arrival[e.req_id] = at
    return out


def stage_durations(s, reqs) -> pd.DataFrame:
    """Her aşamada geçirilen ortalama süre: aşamaya giriş (1. aşama için REQ'in açılışı) ile bir sonraki aşamaya geçiş
    (ya da geri dönüş/tamamlanma) arasındaki süre. Aynı REQ bir aşamaya iki kez girdiyse süreler toplanır.
    'Adet' = o aşamadan BUGÜNE KADAR ÇIKMIŞ REQ sayısı (şu an orada bekleyen sayı DEĞİL)."""
    spent = defaultdict(float)
    for req_id, stage, days, _ in _stage_exits(s, reqs): spent[(req_id, stage)] += days
    rows = []
    for stage in pl.STAGES:
        values = [v for (_, st), v in spent.items() if st == stage.key]
        avg = sum(values) / len(values) if values else 0.0
        rows.append({"Aşama": stage.label, "Ortalama Gün": round(avg, 3), "Ortalama Saat": round(avg * 24, 1),
                     "Süre": fmt_duration(avg), "Adet": len(values)})
    return pd.DataFrame(rows)


def lead_time_days(s, reqs) -> float | None:
    """Tamamlanan REQ'lerin açılıştan tamamlanmaya ortalama toplam süresi (gün); tamamlanan yoksa None."""
    done = {r.id: _aware(r.created_at) for r in reqs if r.status == pl.DONE}
    if not done: return None
    finished = {}
    for req_id, _, _, at in _stage_exits(s, [r for r in reqs if r.id in done]): finished[req_id] = at
    values = [(finished[i] - done[i]).total_seconds() / 86400 for i in done if i in finished]
    return sum(values) / len(values) if values else None


def briefing_facts(reqs, now, stale_days: int = 7) -> list[str]:
    """Yapay zekâ olmadan da çalışan kısa, gerçek-veri tabanlı brifing maddeleri (AI brifingine bağlam olarak da verilir)."""
    active = [r for r in reqs if r.status == pl.ACTIVE]
    facts = [f"Aktif REQ: {len(active)}. Aşamalara göre: " +
             ", ".join(f"{st.label} {n}" for st in pl.STAGES if (n := sum(1 for r in active if r.stage == st.key)))]
    waiting = [r.code for r in active if r.stage == "karar"]
    if waiting: facts.append(f"Müşteri kararı bekleyen teklifler ({len(waiting)}): {', '.join(waiting[:8])}")
    unsent = [r.code for r in active if r.stage == "teklif" and not r.quote_sent_at]
    if unsent: facts.append(f"Teklif aşamasında olup henüz müşteriye iletilmemiş ({len(unsent)}): {', '.join(unsent[:8])}")
    stale = sorted(((now - _aware(r.updated_at)).days, r.code, r.owner.name) for r in active
                   if (now - _aware(r.updated_at)).days >= stale_days)
    if stale:
        facts.append(f"{stale_days}+ gündür güncellenmeyen REQ'ler ({len(stale)}): " +
                     ", ".join(f"{code} ({days} gün, {owner})" for days, code, owner in reversed(stale[-8:])))
    decided = [r.decision for r in reqs if r.decision in ("onay", "ret")]
    if decided:
        wins = decided.count("onay")
        facts.append(f"Karar verilmiş tekliflerde kazanma oranı: %{wins / len(decided) * 100:.0f} ({wins}/{len(decided)}).")
    return facts
