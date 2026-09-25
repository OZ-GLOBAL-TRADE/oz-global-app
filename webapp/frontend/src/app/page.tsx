"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import AppShell from "@/components/AppShell";
import BriefingDrawer from "@/components/BriefingDrawer";
import { ChartCard, GroupedHBars, SERIES_COLORS, STAGE_COLORS, VBars } from "@/components/charts";
import { btnPrimary } from "@/components/req/Actions";
import { Callout, DataTable, Metric } from "@/components/req/ui";
import { api, fmtDate, money, num, PanelData, qty, reqHref } from "@/lib/api";

const CARDS = [
  { key: "aktif_talep", label: "Aktif Talep", hint: "devam eden REQ", color: "#38BDF8" },
  { key: "fiyat_bekleyen", label: "Fiyat Bekleyen", hint: "talep + fiyat araştırması", color: "#0EA5E9" },
  { key: "gumrukte", label: "Gümrükte", hint: "tarifelendirme bekliyor", color: "#8B5CF6" },
  { key: "teklif_karar", label: "Teklif & Karar", hint: "müşteri kararı dahil", color: "#F59E0B" },
  { key: "siparis_lojistik", label: "Sipariş & Lojistik", hint: "onaylanmış işler", color: "#10B981" },
] as const;

const CURRENCIES = ["USD", "EUR", "TRY"];
const TABS = [
  { key: "yonetici", label: "👤 Yönetici" },
  { key: "urun", label: "📦 Ürün" },
  { key: "musteri", label: "🏢 Müşteri" },
  { key: "zaman", label: "📅 Zaman" },
] as const;

type Loaded = Extract<PanelData, { empty: false }>;
type Fin = Extract<NonNullable<Loaded["financials"]>, { priced: true }>;

const fmtRate = (v: number) => v.toLocaleString("tr-TR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

function Segmented<T extends string>({ options, value, onChange, label }: { options: readonly { key: T; label: string }[]; value: T; onChange: (v: T) => void; label: string }) {
  return (
    <div role="tablist" aria-label={label} className="flex flex-wrap gap-1 rounded-lg border border-zinc-800 p-1">
      {options.map((o) => (
        <button
          key={o.key}
          role="tab"
          aria-selected={value === o.key}
          onClick={() => onChange(o.key)}
          className={`rounded-md px-3 py-1 text-sm transition ${value === o.key ? "bg-sky-500 text-white" : "text-zinc-400 hover:bg-zinc-900"}`}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

function Financials({ fin, cur }: { fin: Fin; cur: string }) {
  const [tab, setTab] = useState<(typeof TABS)[number]["key"]>("yonetici");
  const pair = (rows: { name: string; offer: number; profit: number }[]) =>
    rows.map((r) => ({
      label: r.name,
      values: { offer: { value: r.offer, text: money(r.offer, cur) }, profit: { value: r.profit, text: money(r.profit, cur) } },
    }));
  const series = [
    { key: "offer", name: "Teklif", color: SERIES_COLORS.offer },
    { key: "profit", name: "Kâr", color: SERIES_COLORS.profit },
  ];
  const p = fin.products;

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Metric label="Toplam teklif (KDV hariç)" value={money(fin.total_offer, cur)} />
        <Metric label="Toplam kâr" value={money(fin.total_profit, cur)} />
        <Metric label="Maliyet üzerinden kâr oranı" value={fin.margin_on_cost_pct !== null ? `%${fin.margin_on_cost_pct.toLocaleString("tr-TR")}` : "-"} />
        <Metric label="Kazanma oranı" value={fin.win_rate_pct !== null ? `%${fin.win_rate_pct}` : "-"} />
      </div>
      {fin.win_rate_pct !== null && (
        <p className="-mt-2 text-xs text-zinc-500">Kazanma oranı: müşteri kararı verilmiş {fin.decided} teklifin {fin.wins} tanesi onaylandı.</p>
      )}

      <Segmented options={TABS} value={tab} onChange={setTab} label="Analiz sekmeleri" />

      {tab === "yonetici" && (
        <ChartCard title="Yöneticiye göre teklif ve kâr">
          <GroupedHBars rows={pair(fin.by_manager)} series={series} />
        </ChartCard>
      )}

      {tab === "musteri" && (
        <ChartCard title="Müşteriye göre teklif ve kâr" note="En yüksek teklif tutarına sahip 10 müşteri.">
          <GroupedHBars rows={pair(fin.by_customer)} series={series} />
        </ChartCard>
      )}

      {tab === "zaman" && (
        <div className="grid gap-4 lg:grid-cols-2">
          <ChartCard title="Aylık açılan REQ" note="Aylar REQ'in açılış tarihine göre.">
            <VBars items={fin.monthly.map((m) => ({ label: m.month, value: m.opened, text: String(m.opened) }))} />
          </ChartCard>
          <ChartCard title={`Aylık teklif (${cur})`}>
            <VBars items={fin.monthly.map((m) => ({ label: m.month, value: m.offer ?? 0, text: money(m.offer ?? 0, cur), color: SERIES_COLORS.offer }))} />
          </ChartCard>
        </div>
      )}

      {tab === "urun" &&
        (p.table.length === 0 ? (
          <p className="text-sm text-zinc-500">Henüz fiyatlanmış ürün yok.</p>
        ) : (
          <div className="space-y-4">
            <div className="grid gap-4 lg:grid-cols-[3fr_2fr]">
              <ChartCard title="En çok kâr getiren 10 ürün">
                <GroupedHBars
                  rows={p.top_profit.map((r) => ({ label: r.name, values: { profit: { value: r.profit, text: money(r.profit, cur) } } }))}
                  series={[series[1]]}
                />
              </ChartCard>
              <ChartCard title="En düşük marjlı ürünler">
                <DataTable
                  rows={p.lowest_margin}
                  columns={[
                    { header: "Ürün", render: (r) => r.name },
                    { header: "Marj %", align: "right", render: (r) => num(r.margin_pct, 1) },
                    { header: "Adet", align: "right", render: (r) => qty(r.qty) },
                  ]}
                />
              </ChartCard>
            </div>
            <DataTable
              rows={p.table}
              columns={[
                { header: "Ürün", render: (r) => r.name },
                { header: "Adet", align: "right", render: (r) => qty(r.qty) },
                { header: `Satış (${cur})`, align: "right", render: (r) => num(r.sale) },
                { header: `Maliyet (${cur})`, align: "right", render: (r) => num(r.cost) },
                { header: `Kâr (${cur})`, align: "right", render: (r) => num(r.profit) },
                { header: "Marj %", align: "right", render: (r) => num(r.margin_pct, 1) },
                { header: "REQ sayısı", align: "right", render: (r) => r.req_count },
              ]}
            />
            <p className="text-xs text-zinc-500">
              Satış ve maliyet teklif hesabından gelir (ekstra masraflar ürünlere dağıtılmış olarak). Lojistik &apos;ayrı kalem&apos; satırları ürüne dahil değildir.
            </p>
          </div>
        ))}
    </div>
  );
}

function PanelContent() {
  const [data, setData] = useState<PanelData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [cur, setCur] = useState("USD");
  const [briefingOpen, setBriefingOpen] = useState(false);

  useEffect(() => {
    // Para birimi hızlı değiştirilirse eski isteğin yanıtı sonradan gelip yenisinin üzerine yazmasın (yarış): iptal bayrağı
    let cancelled = false;
    api<PanelData>(`/api/panel?currency=${cur}`)
      .then((d) => {
        if (cancelled) return;
        setData(d);
        setError(null);
      })
      .catch((err) => !cancelled && setError(err instanceof Error ? err.message : "Bilinmeyen hata"));
    return () => {
      cancelled = true;
    };
  }, [cur]);

  if (error) return <div className="text-red-400">⚠️ {error}</div>;
  if (!data) return <div className="text-zinc-400">Yükleniyor…</div>;

  const scope = data.scope_all ? "Tüm REQ'lerin özeti" : "Yalnızca gümrük/lojistik aşamasındaki REQ'ler";
  if (data.empty) {
    return (
      <>
        <p className="mb-3 text-sm text-zinc-500">{scope}</p>
        <Callout tone="info">Henüz REQ yok. Talepler sayfasından ilk REQ&apos;yi açın.</Callout>
      </>
    );
  }
  const fin = data.financials;
  const d = data.durations;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-3">
        <p className="flex-1 text-sm text-zinc-500">{scope}</p>
        <button className={btnPrimary} onClick={() => setBriefingOpen(true)}>
          📰 Günlük brifing üret
        </button>
      </div>

      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-5">
        {CARDS.map((c) => (
          <div key={c.key} className="rounded-xl border border-zinc-800 bg-zinc-900 p-4" style={{ borderTopColor: c.color, borderTopWidth: 3 }}>
            <div className="text-[11px] font-semibold uppercase tracking-wide text-zinc-400">{c.label}</div>
            <div className="mt-1 text-3xl font-bold">{data.cards[c.key]}</div>
            <div className="mt-1 text-xs text-zinc-500">{c.hint}</div>
          </div>
        ))}
      </div>
      <p className="-mt-3 text-sm text-zinc-400">
        Tamamlanan: {data.done} · Rafa kaldırılan: {data.shelved}
        {data.lead_time && (
          <>
            {" "}
            · Açılıştan tamamlanmaya ortalama: <b className="text-zinc-200">{data.lead_time}</b>
          </>
        )}
      </p>

      <div className="grid gap-4 lg:grid-cols-2">
        <ChartCard title="Aşama Bazlı Talep Sayısı">
          <VBars items={data.per_stage.map((s) => ({ label: s.label, value: s.count, text: String(s.count), color: STAGE_COLORS[s.key] }))} />
        </ChartCard>
        <ChartCard
          title={`Aşama Bazlı Ortalama Süre (${d.in_hours ? "saat" : "gün"})`}
          note={
            d.slowest
              ? `En uzun bekleme: ${d.slowest.label} (${d.slowest.text}). Süre: aşamaya girişten (1. aşamada REQ'in açılışından) bir sonraki aşamaya geçişe kadar; yalnızca o aşamadan çıkmış REQ'ler.`
              : undefined
          }
        >
          <VBars items={d.rows.map((r, i) => ({ label: r.label, value: d.in_hours ? r.hours : r.days, text: r.text, color: STAGE_COLORS[data.per_stage[i].key] }))} />
        </ChartCard>
      </div>

      {fin && (
        <section className="space-y-4">
          <div className="flex flex-wrap items-center gap-3">
            <h2 className="flex-1 text-lg font-semibold">Teklif &amp; Kâr</h2>
            {/* Seçim, verinin HANGİ PARA BİRİMİNDE gösterileceğidir; tüm REQ'ler güncel kurla bu birime çevrilir */}
            <Segmented options={CURRENCIES.map((c) => ({ key: c, label: c }))} value={cur} onChange={setCur} label="Gösterim para birimi" />
          </div>
          {!fin.priced ? (
            <p className="text-sm text-zinc-500">Henüz fiyatlanmış teklif yok.</p>
          ) : (
            <>
              {fin.rates ? (
                <p className="text-xs text-zinc-500">
                  Tüm teklifler güncel kurla {cur}&apos;ye çevrildi (
                  {(["EUR", "TRY"] as const).filter((c) => c !== cur && fin.rates?.[c]).map((c) => `1 USD = ${fmtRate(fin.rates![c]!)} ${c}`).join(" · ")}
                  ; Avrupa Merkez Bankası, saatlik güncellenir). Rafa kaldırılanlar hariç.
                </p>
              ) : (
                <Callout tone="warn">Canlı döviz kuru alınamadı; yalnızca zaten {cur} olan teklifler gösteriliyor.</Callout>
              )}
              {fin.missing > 0 && <p className="text-xs text-amber-300">⚠️ {fin.missing} teklif çevrilemediği için toplamlara dahil edilmedi.</p>}
              <Financials key={cur} fin={fin} cur={cur} />
            </>
          )}
        </section>
      )}

      <section>
        <h2 className="mb-3 text-lg font-semibold">Son Hareketler</h2>
        <DataTable
          rows={data.recent}
          columns={[
            {
              header: "REQ",
              render: (r) => (
                <Link href={reqHref(r.code)} className="font-medium text-white hover:text-sky-300 hover:underline">
                  {r.code}
                </Link>
              ),
            },
            { header: "Müşteri", render: (r) => r.customer },
            { header: "Yönetici", render: (r) => r.owner },
            { header: "Aşama", render: (r) => r.stage_label },
            ...(fin ? [{ header: "Teklif", align: "right" as const, render: (r: (typeof data.recent)[number]) => money(r.teklif, r.currency) }] : []),
            { header: "Güncelleme", render: (r) => fmtDate(r.updated_at) },
          ]}
        />
      </section>

      {briefingOpen && <BriefingDrawer onClose={() => setBriefingOpen(false)} />}
    </div>
  );
}

export default function DashboardPage() {
  return (
    <AppShell>
      <h1 className="mb-6 text-xl font-semibold">Panel</h1>
      <PanelContent />
    </AppShell>
  );
}
