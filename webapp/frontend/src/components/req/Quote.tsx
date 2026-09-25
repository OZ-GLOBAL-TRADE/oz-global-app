import { API_BASE, fmtDate, money, num, qty, QuoteCalc, ReqDetail } from "@/lib/api";
import { Callout, DataTable, Metric, MetricRow, SectionTitle } from "./ui";

// Teklif aşamasının ortak gösterimleri: salt okunur panel de, düzenleme formunun canlı önizlemesi de bunları kullanır.

export function QuoteDocs({ req }: { req: ReqDetail }) {
  const quotes = req.teklif?.quotes ?? [];
  if (quotes.length === 0) return null;
  return (
    <div>
      <SectionTitle>Müşteriye giden teklifler</SectionTitle>
      <ul className="space-y-2">
        {quotes.map((q) => (
          <li key={q.id} className="flex flex-wrap items-center gap-3 rounded-lg border border-zinc-800 px-4 py-2.5 text-sm">
            <span className="font-medium text-white">{q.number}</span>
            <span className="text-zinc-400">{fmtDate(q.issued_at)}</span>
            <span className="text-zinc-300">{money(q.grand_total, q.currency)}</span>
            <span className="text-zinc-500">{q.is_latest ? "güncel" : "eski revizyon"}</span>
            <a
              href={`${API_BASE}/api/quotes/${q.id}/pdf`}
              className="ml-auto rounded-lg border border-zinc-700 px-3 py-1 hover:bg-zinc-800"
            >
              📄 PDF indir
            </a>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Uyarılar + maliyet dağılımı + teklif tutarları + satır tablosu (talepler.py::_panel_teklif'in alt yarısı). */
export function QuoteBreakdown({
  q,
  cur,
  taxEnabled,
  taxPct,
  mode,
  missingUnitCost,
  hint,
  marginPct,
  warnPct,
}: {
  q: QuoteCalc;
  cur: string;
  taxEnabled: boolean;
  taxPct: number;
  mode: string;
  missingUnitCost: boolean;
  hint: string | null;
  marginPct: number | null;
  warnPct: number;
}) {
  return (
    <div className="space-y-4">
      {missingUnitCost && <Callout tone="warn">Bazı ürünlerde birim alış fiyatı yok; teklif eksik hesaplanıyor.</Callout>}
      {marginPct !== null && marginPct > warnPct && (
        <Callout tone="warn">Varsayılan kâr marjı %{qty(marginPct)}: alışılmadık derecede yüksek. Emin misiniz?</Callout>
      )}
      {hint && <Callout tone="warn">{hint}</Callout>}

      <SectionTitle>Maliyet dağılımı</SectionTitle>
      <MetricRow>
        <Metric label="Ürün alış" value={money(q.cost_products, cur)} />
        <Metric label="Gümrük" value={money(q.cost_customs, cur)} />
        <Metric label="Lojistik" value={money(q.cost_logistics, cur)} />
        <Metric label="Diğer masraflar" value={money(q.cost_other, cur)} />
        <Metric label="Toplam maliyet" value={money(q.cost_total, cur)} />
      </MetricRow>

      <SectionTitle>Teklif</SectionTitle>
      <MetricRow>
        <Metric label="Kâr" value={money(q.profit, cur)} />
        <Metric label={taxEnabled ? "Teklif tutarı (KDV hariç)" : "Teklif tutarı (KDV yok)"} value={money(q.total, cur)} accent />
        {taxEnabled && <Metric label={`KDV %${qty(taxPct)}`} value={money(q.tax, cur)} />}
        {taxEnabled && <Metric label="KDV dahil toplam" value={money(q.grand_total, cur)} />}
      </MetricRow>

      <DataTable
        rows={q.rows}
        columns={[
          { header: "Ürün", render: (r) => r.name },
          { header: "Adet", align: "right", render: (r) => qty(r.qty) },
          { header: "Birim Maliyet", align: "right", render: (r) => num(r.unit_cost) },
          { header: "Birim Satış", align: "right", render: (r) => num(r.unit_price) },
          { header: "Satır Toplamı", align: "right", render: (r) => num(r.line_total) },
          { header: "Marj / Fiyat", render: (r) => r.margin_label },
        ]}
      />
      {mode === "ayri" ? (
        <p className="text-xs text-zinc-500">Lojistik ayrı kalem olarak gösteriliyor; ürün birim fiyatları lojistik içermiyor.</p>
      ) : (
        (q.cost_logistics > 0 || q.cost_other > 0) && (
          <p className="text-xs text-zinc-500">
            Lojistik ve ekstra masraflar ürün maliyetlerine oranlı dağıtıldı; her ürün kendi marjıyla fiyatlanır.
          </p>
        )
      )}
    </div>
  );
}
