import type { ReactNode } from "react";

// Bağımlılıksız, erişilebilir (her çubuğun aria-label'ı var) küçük grafikler — Panel için yeterli; grafik kütüphanesi
// (recharts/plotly) eklemek yerine bilerek CSS ile çizildi. Değerler her zaman çubuğun yanında/üstünde yazıyla da görünür.

export const STAGE_COLORS: Record<string, string> = {
  talep: "#64748B",
  fiyat: "#0EA5E9",
  gumruk: "#8B5CF6",
  teklif: "#F59E0B",
  karar: "#EC4899",
  siparis: "#10B981",
  lojistik: "#14B8A6",
  teslim: "#22C55E",
};

export const SERIES_COLORS = { offer: "#38BDF8", profit: "#34D399" };

export type Bar = { label: string; value: number; text: string; color?: string };

/** Dikey çubuklar (aşama başına sayı/süre, aylık REQ sayısı). Tüm değerler 0 ise çubuk çizilmez, yalnızca yazılar kalır. */
export function VBars({ items, height = 150 }: { items: Bar[]; height?: number }) {
  const max = Math.max(0, ...items.map((i) => i.value));
  // Toplam yükseklik: çubuk alanı + değer yazısı için 2 satırlık yer (uzun süre metinleri "3 saat 29 dk" dar sütunda sarılır)
  // + alt etiket için 2 satırlık yer. Yer ayrılmazsa en yüksek çubuğun yazısı kartın başlığına taşar.
  return (
    <div className="flex items-end gap-2" style={{ height: height + 36 + 40 }} role="list">
      {items.map((i) => (
        <div key={i.label} role="listitem" aria-label={`${i.label}: ${i.text}`} className="flex min-w-0 flex-1 flex-col items-center justify-end">
          <div className="mb-1 flex h-8 w-full items-end justify-center text-center text-xs leading-tight text-zinc-300">{i.text}</div>
          <div
            className="w-full rounded-t"
            style={{ height: max > 0 ? Math.max(i.value > 0 ? 3 : 0, (i.value / max) * height) : 0, background: i.color ?? "#38BDF8" }}
          />
          <div className="mt-1 h-8 w-full text-center text-[10px] leading-tight text-zinc-500" title={i.label}>
            <span className="line-clamp-2">{i.label}</span>
          </div>
        </div>
      ))}
    </div>
  );
}

export type Series = { key: string; name: string; color: string };
export type GroupRow = { label: string; values: Record<string, { value: number; text: string }> };

/** Yatay gruplu çubuklar (yönetici/müşteri başına teklif ve kâr gibi). Her satırda seri başına bir çubuk. */
export function GroupedHBars({ rows, series }: { rows: GroupRow[]; series: Series[] }) {
  const max = Math.max(0, ...rows.flatMap((r) => series.map((s) => r.values[s.key]?.value ?? 0)));
  return (
    <div className="space-y-3">
      <div className="flex gap-4 text-xs text-zinc-400" aria-hidden>
        {series.map((s) => (
          <span key={s.key} className="flex items-center gap-1.5">
            <span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: s.color }} />
            {s.name}
          </span>
        ))}
      </div>
      {rows.map((r) => (
        <div key={r.label} className="grid grid-cols-[minmax(0,10rem)_1fr] items-center gap-3">
          <div className="truncate text-sm text-zinc-300" title={r.label}>
            {r.label}
          </div>
          <div className="space-y-1">
            {series.map((s) => {
              const v = r.values[s.key];
              const value = v?.value ?? 0;
              return (
                <div key={s.key} className="flex items-center gap-2" aria-label={`${r.label} ${s.name}: ${v?.text ?? "-"}`}>
                  <div className="h-3 rounded-r" style={{ width: max > 0 ? `${Math.max(value > 0 ? 1 : 0, (Math.max(value, 0) / max) * 100)}%` : 0, background: s.color, maxWidth: "calc(100% - 6rem)" }} />
                  <span className="whitespace-nowrap text-xs text-zinc-400">{v?.text ?? "-"}</span>
                </div>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}

export function ChartCard({ title, children, note }: { title: string; children: ReactNode; note?: ReactNode }) {
  return (
    <section className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-4">
      <h3 className="mb-3 text-sm font-semibold text-zinc-200">{title}</h3>
      {children}
      {note && <p className="mt-3 text-xs text-zinc-500">{note}</p>}
    </section>
  );
}
