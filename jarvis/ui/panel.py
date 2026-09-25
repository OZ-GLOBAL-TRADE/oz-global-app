from datetime import datetime, timezone

import pandas as pd
import plotly.express as px
import streamlit as st

from jarvis import analytics, fx, jarvis_chat, pipeline as pl, services as sv
from jarvis.db import session_scope
from jarvis.ui.common import STAGE_COLORS, TR_TZ, fmt_dt, kpi, money

STAGE_LABEL = {s.key: s.label for s in pl.STAGES}
DISPLAY_CURRENCIES = ["USD", "EUR", "TRY"]


def _briefing_closed():
    st.session_state.pop("briefing_open", None)


@st.dialog("📰 Günlük Brifing", width="large", on_dismiss=_briefing_closed)
def _briefing_dialog(actor, facts):
    with st.container(key="drawer_briefing"):  # common.CSS: sağdan kayan panel
        st.caption(datetime.now(TR_TZ).strftime("%d.%m.%Y %H:%M") + " itibarıyla")
    regen = st.button("🔄 Yeniden üret", key="briefing_regen")
    if regen or "briefing_text" not in st.session_state:
        with st.spinner("Jarvis brifingi hazırlıyor..."), session_scope() as s:
            st.session_state["briefing_text"] = jarvis_chat.daily_briefing(s, actor, facts)
    st.markdown(st.session_state["briefing_text"])


def _convert_column(df, amount_col, cur_col, target, rates):
    """Her satırı kendi para biriminden `target`'a çevirir; kur yoksa yalnızca zaten o para birimindekiler sayılır."""
    def one(r):
        if pd.isna(r[amount_col]): return None
        return fx.convert(r[amount_col], r[cur_col], target, rates) if rates else (r[amount_col] if r[cur_col] == target else None)
    return df.apply(one, axis=1) if not df.empty else pd.Series(dtype=float)


def _bar(frame, x, y, cur, **kw):
    fig = px.bar(frame, x=x, y=y, barmode="group", **kw)
    fig.update_layout(xaxis_title=None, yaxis_title=cur, legend_title=None, margin=dict(t=10))
    return fig


def render():
    actor = st.session_state["actor"]
    with session_scope() as s:
        reqs = sv.visible_reqs(s, actor)
        durations = analytics.stage_durations(s, reqs)
        lead = analytics.lead_time_days(s, reqs)
        df = analytics.reqs_frame(reqs)
        products = analytics.product_frame(reqs)
        facts = analytics.briefing_facts(reqs, datetime.now(timezone.utc)) if reqs else []

    head = st.columns([4, 1.4], vertical_alignment="center")
    head[0].title("Panel")
    if head[1].button("📰 Günlük brifing üret", width="stretch", type="primary", disabled=df.empty):
        st.session_state.pop("briefing_text", None)
        st.session_state["briefing_open"] = True
    if st.session_state.get("briefing_open"): _briefing_dialog(actor, facts)
    st.caption("Tüm REQ'lerin özeti" if actor.role in (pl.ADMIN, pl.TRADE_MANAGER) else "Yalnızca gümrük/lojistik aşamasındaki REQ'ler")
    if df.empty:
        st.info("Henüz REQ yok. Talepler sayfasından ilk REQ'yi açın ya da kenar çubuğundan demo veriyi yükleyin.")
        return

    active = df[df["Durum"] == pl.ACTIVE]
    count = lambda *stages: int(active["Aşama"].isin(stages).sum())
    cards = [("Aktif Talep", len(active), "devam eden REQ", "#38BDF8"),
             ("Fiyat Bekleyen", count("talep", "fiyat"), "talep + fiyat araştırması", "#0EA5E9"),
             ("Gümrükte", count("gumruk"), "tarifelendirme bekliyor", "#8B5CF6"),
             ("Teklif & Karar", count("teklif", "karar"), "müşteri kararı dahil", "#F59E0B"),
             ("Sipariş & Lojistik", count("siparis", "lojistik", "teslim"), "onaylanmış işler", "#10B981")]
    for col, card in zip(st.columns(len(cards)), cards): col.markdown(kpi(*card), unsafe_allow_html=True)
    done, shelved = int((df["Durum"] == pl.DONE).sum()), int((df["Durum"] == pl.SHELVED).sum())
    st.caption(f"Tamamlanan: {done} · Rafa kaldırılan: {shelved}"
               + (f" · Açılıştan tamamlanmaya ortalama: **{analytics.fmt_duration(lead)}**" if lead else ""))

    left, right = st.columns(2)
    with left:
        st.subheader("Aşama Bazlı Talep Sayısı")
        per_stage = pd.DataFrame({"Aşama": [STAGE_LABEL[k] for k in pl.STAGE_KEYS],
                                  "Adet": [int((active["Aşama"] == k).sum()) for k in pl.STAGE_KEYS]})
        fig = px.bar(per_stage, x="Aşama", y="Adet", text="Adet", color="Aşama",
                     color_discrete_map={STAGE_LABEL[k]: c for k, c in STAGE_COLORS.items()})
        fig.update_layout(showlegend=False, xaxis_title=None, margin=dict(t=10))
        fig.update_yaxes(rangemode="tozero")
        st.plotly_chart(fig, width="stretch")
    with right:
        st.subheader("Aşama Bazlı Ortalama Süre")
        in_hours = durations["Ortalama Gün"].max() < 1
        y = "Ortalama Saat" if in_hours else "Ortalama Gün"
        fig = px.bar(durations, x="Aşama", y=y, text="Süre", hover_data={"Adet": True, "Süre": True, y: False})
        fig.update_layout(xaxis_title=None, yaxis_title="saat" if in_hours else "gün", margin=dict(t=10))
        fig.update_yaxes(rangemode="tozero")
        st.plotly_chart(fig, width="stretch")
        slowest = durations[durations["Adet"] > 0].sort_values("Ortalama Gün", ascending=False)
        if not slowest.empty and slowest.iloc[0]["Ortalama Gün"] > 0:
            st.caption(f"En uzun bekleme: **{slowest.iloc[0]['Aşama']}** ({slowest.iloc[0]['Süre']}). Süre: aşamaya girişten "
                       "(1. aşamada REQ'in açılışından) bir sonraki aşamaya geçişe kadar; yalnızca o aşamadan çıkmış REQ'ler.")

    _financials(df, products)

    st.subheader("Son Hareketler")
    recent = df.head(12).copy()
    recent["Aşama"] = recent.apply(lambda r: STAGE_LABEL[r["Aşama"]] if r["Durum"] == pl.ACTIVE else pl.STATUS_LABELS[r["Durum"]], axis=1)
    recent["Teklif"] = recent.apply(lambda r: money(r["Teklif"], r["Para Birimi"]) if pd.notna(r["Teklif"]) else "-", axis=1)
    recent["Güncelleme"] = recent["Güncelleme"].map(fmt_dt)
    event = st.dataframe(recent[["REQ", "Müşteri", "Yönetici", "Aşama", "Teklif", "Güncelleme"]], hide_index=True, width="stretch",
                         on_select="rerun", selection_mode="single-row", key=f"panel_recent_{st.session_state.get('panel_ver', 0)}")
    if event.selection.rows:
        st.session_state["open_req"] = recent.iloc[event.selection.rows[0]]["REQ"]
        st.session_state["panel_ver"] = st.session_state.get("panel_ver", 0) + 1
        st.switch_page(st.session_state["pages"]["talepler"])


def _financials(df, products):
    head = st.columns([3, 2], vertical_alignment="bottom")
    head[0].subheader("Teklif & Kâr")
    # Seçim, verinin HANGİ PARA BİRİMİNDE gösterileceğidir; tüm REQ'ler güncel kurla bu birime çevrilir.
    cur = head[1].segmented_control("Gösterim para birimi", DISPLAY_CURRENCIES, default="USD", required=True, key="panel_display_cur")
    rates = fx.get_rates("USD")

    priced = df[df["Teklif"].notna() & (df["Durum"] != pl.SHELVED)].copy()
    if priced.empty:
        st.caption("Henüz fiyatlanmış teklif yok.")
        return
    priced["Teklif_c"] = _convert_column(priced, "Teklif", "Para Birimi", cur, rates)
    priced["Kâr_c"] = _convert_column(priced, "Kâr", "Para Birimi", cur, rates)
    missing = int(priced["Teklif_c"].isna().sum())
    priced = priced[priced["Teklif_c"].notna()]
    if rates:
        others = " · ".join(f"1 USD = {rates[c]:,.2f} {c}".replace(",", "X").replace(".", ",").replace("X", ".") for c in DISPLAY_CURRENCIES if c != "USD" and c in rates)
        st.caption(f"Tüm teklifler güncel kurla {cur}'ye çevrildi ({others}; Avrupa Merkez Bankası, saatlik güncellenir). Rafa kaldırılanlar hariç.")
    else:
        st.warning(f"Canlı döviz kuru alınamadı; yalnızca zaten {cur} olan teklifler gösteriliyor.")
    if missing: st.caption(f"⚠️ {missing} teklif çevrilemediği için toplamlara dahil edilmedi.")

    total_offer, total_profit = priced["Teklif_c"].sum(), priced["Kâr_c"].sum()
    decided = df["Karar"].isin(["onay", "ret"])
    wins = int((df["Karar"] == "onay").sum())
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Toplam teklif (KDV hariç)", money(total_offer, cur))
    m2.metric("Toplam kâr", money(total_profit, cur))
    m3.metric("Maliyet üzerinden kâr oranı", f"%{(total_profit / (total_offer - total_profit) * 100):.1f}" if total_offer > total_profit else "-")
    m4.metric("Kazanma oranı", f"%{wins / decided.sum() * 100:.0f}" if decided.sum() else "-",
              help="Müşteri kararı verilmiş teklifler içinde onaylananların oranı.")

    t_mgr, t_prod, t_cust, t_time = st.tabs(["👤 Yönetici", "📦 Ürün", "🏢 Müşteri", "📅 Zaman"])
    with t_mgr:
        by_manager = priced.groupby("Yönetici", as_index=False)[["Teklif_c", "Kâr_c"]].sum().rename(columns={"Teklif_c": "Teklif", "Kâr_c": "Kâr"})
        st.plotly_chart(_bar(by_manager, "Yönetici", ["Teklif", "Kâr"], cur), width="stretch")
    with t_prod:
        _products_tab(products, cur, rates)
    with t_cust:
        by_cust = (priced.groupby("Müşteri", as_index=False)[["Teklif_c", "Kâr_c"]].sum()
                   .rename(columns={"Teklif_c": "Teklif", "Kâr_c": "Kâr"}).sort_values("Teklif", ascending=False).head(10))
        st.plotly_chart(_bar(by_cust, "Müşteri", ["Teklif", "Kâr"], cur), width="stretch")
        st.caption("En yüksek teklif tutarına sahip 10 müşteri.")
    with t_time:
        monthly = df.assign(Ay=pd.to_datetime(df["Açılış"], utc=True).dt.strftime("%Y-%m"))
        opened = monthly.groupby("Ay", as_index=False).size().rename(columns={"size": "Açılan REQ"})
        offers = (priced.assign(Ay=pd.to_datetime(priced["Açılış"], utc=True).dt.strftime("%Y-%m"))
                  .groupby("Ay", as_index=False)["Teklif_c"].sum().rename(columns={"Teklif_c": "Teklif"}))
        c1, c2 = st.columns(2)
        fig = px.bar(opened, x="Ay", y="Açılan REQ", text="Açılan REQ")
        fig.update_layout(xaxis_title=None, margin=dict(t=10))
        c1.plotly_chart(fig, width="stretch")
        c2.plotly_chart(_bar(offers, "Ay", "Teklif", cur), width="stretch")
        st.caption("Aylar REQ'in açılış tarihine göre.")


def _products_tab(products, cur, rates):
    if products.empty:
        st.caption("Henüz fiyatlanmış ürün yok.")
        return
    p = products.copy()
    for col in ("Maliyet", "Satış", "Kâr"): p[col] = _convert_column(p, col, "Para Birimi", cur, rates)
    p = p[p["Satış"].notna()]
    by_prod = p.groupby("Ürün", as_index=False).agg(Adet=("Adet", "sum"), Satış=("Satış", "sum"), Maliyet=("Maliyet", "sum"),
                                                    Kâr=("Kâr", "sum"), REQ=("REQ", "nunique"))
    by_prod["Marj %"] = (by_prod["Kâr"] / by_prod["Maliyet"].where(by_prod["Maliyet"] > 0) * 100).round(1)
    top = by_prod.sort_values("Kâr", ascending=False).head(10)
    top = top.assign(Etiket=top["Ürün"].map(lambda n: n if len(n) <= 28 else n[:27] + "…"))
    fig = px.bar(top.sort_values("Kâr"), x="Kâr", y="Etiket", orientation="h", text_auto=".2s", hover_data={"Ürün": True, "Etiket": False})
    fig.update_layout(xaxis_title=cur, yaxis_title=None, margin=dict(t=10))
    c1, c2 = st.columns([3, 2])
    c1.markdown("**En çok kâr getiren 10 ürün**")
    c1.plotly_chart(fig, width="stretch")
    c2.markdown("**En düşük marjlı ürünler**")
    c2.dataframe(by_prod.dropna(subset=["Marj %"]).sort_values("Marj %").head(8)[["Ürün", "Marj %", "Adet"]], hide_index=True, width="stretch")
    st.dataframe(by_prod.sort_values("Satış", ascending=False), hide_index=True, width="stretch",
                 column_config={c: st.column_config.NumberColumn(f"{c} ({cur})", format="%.2f") for c in ("Satış", "Maliyet", "Kâr")}
                 | {"Adet": st.column_config.NumberColumn(format="%g"), "REQ": st.column_config.NumberColumn("REQ sayısı")})
    st.caption("Satış ve maliyet teklif hesabından gelir (ekstra masraflar ürünlere dağıtılmış olarak). Lojistik 'ayrı kalem' satırları ürüne dahil değildir.")
