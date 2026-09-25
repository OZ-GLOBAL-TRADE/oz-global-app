import type { ReactNode } from "react";

/** Streamlit'teki st.metric karşılığı. */
export function Metric({ label, value, accent }: { label: string; value: ReactNode; accent?: boolean }) {
  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-900/60 px-4 py-3">
      <div className="text-xs text-zinc-500">{label}</div>
      <div className={`mt-1 text-lg font-semibold ${accent ? "text-emerald-300" : "text-white"}`}>{value}</div>
    </div>
  );
}

export function MetricRow({ children }: { children: ReactNode }) {
  return <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-5">{children}</div>;
}

export function Callout({ tone, children }: { tone: "info" | "warn" | "success"; children: ReactNode }) {
  const styles = {
    info: "border-sky-500/30 bg-sky-500/10 text-sky-200",
    warn: "border-amber-500/30 bg-amber-500/10 text-amber-200",
    success: "border-emerald-500/30 bg-emerald-500/10 text-emerald-200",
  };
  return <div className={`rounded-lg border px-4 py-3 text-sm ${styles[tone]}`}>{children}</div>;
}

/** Ondalıklı sayı girişi (tr-TR: virgül ya da nokta). Değer metin olarak tutulur; çözümleme parseNum ile. */
export function NumField({
  value,
  onChange,
  label,
  invalid,
  className = "w-28",
}: {
  value: string;
  onChange: (v: string) => void;
  label: string;
  invalid?: boolean;
  className?: string;
}) {
  return (
    <input
      inputMode="decimal"
      value={value}
      aria-label={label}
      aria-invalid={invalid || undefined}
      onChange={(e) => onChange(e.target.value)}
      className={`${className} rounded-lg border bg-zinc-900 px-2 py-1 text-right text-sm outline-none focus:border-sky-500 ${
        invalid ? "border-red-500" : "border-zinc-700"
      }`}
    />
  );
}

export type Flash = { tone: "ok" | "err"; lines: string[] } | null;

/** Eylem sonucu bandı: başarıda tek satır, iş kuralı hatasında eksiklerin listesi. */
export function FlashBanner({ flash }: { flash: Flash }) {
  if (!flash) return null;
  const ok = flash.tone === "ok";
  return (
    <div
      role={ok ? "status" : "alert"}
      className={`rounded-lg border px-4 py-3 text-sm ${
        ok ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-200" : "border-red-500/30 bg-red-500/10 text-red-200"
      }`}
    >
      {flash.lines.length === 1 ? (
        flash.lines[0]
      ) : (
        <ul className="list-disc space-y-0.5 pl-5">
          {flash.lines.map((l) => (
            <li key={l}>{l}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

export type Column<T> = { header: string; align?: "right"; render: (row: T) => ReactNode };

/** Salt okunur basit tablo (Streamlit'teki st.dataframe karşılığı). */
export function DataTable<T>({ columns, rows }: { columns: Column<T>[]; rows: T[] }) {
  return (
    <div className="overflow-x-auto rounded-xl border border-zinc-800">
      <table className="w-full text-sm">
        <thead className="bg-zinc-900 text-left text-xs uppercase tracking-wide text-zinc-500">
          <tr>
            {columns.map((c) => (
              <th key={c.header} className={`px-4 py-2.5 ${c.align === "right" ? "text-right" : ""}`}>
                {c.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-zinc-800">
          {rows.map((row, i) => (
            <tr key={i}>
              {columns.map((c) => (
                <td key={c.header} className={`px-4 py-2.5 text-zinc-300 ${c.align === "right" ? "text-right" : ""}`}>
                  {c.render(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function SectionTitle({ children }: { children: ReactNode }) {
  return <h3 className="mb-2 mt-1 text-sm font-semibold text-zinc-200">{children}</h3>;
}
