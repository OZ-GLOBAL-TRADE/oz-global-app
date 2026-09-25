"use client";

import { useMemo, useState, type ReactNode } from "react";
import { parseNum, toInput } from "@/lib/api";
import { btn, btnPrimary } from "./req/Actions";

// Streamlit'teki st.data_editor + "💾 Değişiklikleri kaydet" deseninin karşılığı (Kişiler ve Ürünler sayfaları).
// Hücreler metin olarak tutulur; yalnızca DEĞİŞEN hücreler kaydedilir (sunucu her satır için yalnızca değişen alanları alır),
// değişen hücre vurgulanır, "Vazgeç" hepsini geri alır. Büyük kataloglar için 100'er satır gösterilir + arama kutusu.

export type Column<T> = {
  key: keyof T & string;
  label: string;
  /** Yalnızca gösterilir, düzenlenemez (ad, kod vb.) */
  readOnly?: boolean;
  type?: "text" | "number";
  /** Serbest metin kalır; yalnızca öneri listesi (datalist) sunar — Streamlit'teki metin hücresi gibi */
  suggestions?: string[];
  wide?: boolean;
};

const PAGE = 100;

type Row = { id: number };

export default function EditableTable<T extends Row>({
  rows,
  columns,
  editableKeys,
  onSave,
  busy,
  searchKeys,
  emptyText,
  renderActions,
}: {
  rows: T[];
  columns: Column<T>[];
  /** Sunucunun bu kullanıcı için izin verdiği alanlar (ör. gümrükçüde yalnızca GTİP); boşsa tablo salt okunur */
  editableKeys: string[];
  onSave: (changes: Record<string, unknown>[]) => Promise<boolean>;
  busy: boolean;
  searchKeys: (keyof T & string)[];
  emptyText: string;
  /** Satır sonu "İşlem" sütunu (ör. 🗑️ Sil düğmesi). Verilmezse sütun çizilmez. */
  renderActions?: (row: T) => ReactNode;
}) {
  const [edits, setEdits] = useState<Record<number, Record<string, string>>>({});
  const [query, setQuery] = useState("");
  const [shown, setShown] = useState(PAGE);

  const original = (r: T, c: Column<T>): string => {
    const v = r[c.key] as unknown;
    return c.type === "number" ? toInput(v as number | null) : v === null || v === undefined ? "" : String(v);
  };
  const isEditable = (c: Column<T>) => !c.readOnly && editableKeys.includes(c.key);
  const value = (r: T, c: Column<T>) => edits[r.id]?.[c.key] ?? original(r, c);
  const changed = (r: T, c: Column<T>) => edits[r.id]?.[c.key] !== undefined && edits[r.id][c.key] !== original(r, c);
  const invalidNum = (r: T, c: Column<T>) => {
    if (c.type !== "number" || !changed(r, c)) return false;
    const n = parseNum(value(r, c));
    return n !== null && (Number.isNaN(n) || n < 0);
  };

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return rows;
    return rows.filter((r) => searchKeys.some((k) => String(r[k] ?? "").toLowerCase().includes(q)));
  }, [rows, query, searchKeys]);

  const changedCount = rows.reduce((n, r) => n + columns.filter((c) => changed(r, c)).length, 0);
  const hasInvalid = rows.some((r) => columns.some((c) => invalidNum(r, c)));

  async function save() {
    const changes: Record<string, unknown>[] = [];
    for (const r of rows) {
      const row: Record<string, unknown> = { id: r.id };
      for (const c of columns) {
        if (!changed(r, c)) continue;
        const raw = value(r, c);
        if (c.type === "number") {
          const n = parseNum(raw);
          row[c.key] = n === null ? null : n;
        } else row[c.key] = raw;
      }
      if (Object.keys(row).length > 1) changes.push(row);
    }
    if (await onSave(changes)) setEdits({});
  }

  if (rows.length === 0) return <p className="text-sm text-zinc-500">{emptyText}</p>;
  const listId = (c: Column<T>) => `dl-${c.key}`;
  const canEditAny = columns.some(isEditable);

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-3">
        <input
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setShown(PAGE);
          }}
          placeholder="Tabloda ara…"
          aria-label="Tabloda ara"
          className="w-64 rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-1.5 text-sm outline-none focus:border-sky-500"
        />
        <span className="text-xs text-zinc-500">
          {filtered.length} kayıt{query ? ` (toplam ${rows.length})` : ""}
        </span>
      </div>

      {columns.filter((c) => c.suggestions).map((c) => (
        <datalist key={c.key} id={listId(c)}>
          {c.suggestions!.map((o) => (
            <option key={o} value={o} />
          ))}
        </datalist>
      ))}

      <div className="overflow-x-auto rounded-xl border border-zinc-800">
        <table className="w-full text-sm">
          <thead className="bg-zinc-900 text-left text-xs uppercase tracking-wide text-zinc-500">
            <tr>
              {columns.map((c) => (
                <th key={c.key} className={`px-3 py-2.5 ${c.type === "number" ? "text-right" : ""}`}>
                  {c.label}
                </th>
              ))}
              {renderActions && <th className="px-3 py-2.5 text-right">İşlem</th>}
            </tr>
          </thead>
          <tbody className="divide-y divide-zinc-800">
            {filtered.slice(0, shown).map((r) => (
              <tr key={r.id}>
                {columns.map((c) => (
                  <td key={c.key} className={`px-3 py-1.5 ${c.type === "number" ? "text-right" : ""}`}>
                    {isEditable(c) ? (
                      <input
                        value={value(r, c)}
                        aria-label={`${c.label}: ${(r as unknown as { name?: string }).name ?? r.id}`}
                        aria-invalid={invalidNum(r, c) || undefined}
                        list={c.suggestions ? listId(c) : undefined}
                        inputMode={c.type === "number" ? "decimal" : undefined}
                        onChange={(e) => setEdits((prev) => ({ ...prev, [r.id]: { ...prev[r.id], [c.key]: e.target.value } }))}
                        className={`${c.wide ? "w-72" : c.type === "number" ? "w-28 text-right" : "w-44"} rounded border bg-zinc-900 px-2 py-1 outline-none focus:border-sky-500 ${
                          invalidNum(r, c) ? "border-red-500" : changed(r, c) ? "border-amber-400" : "border-zinc-800"
                        }`}
                      />
                    ) : (
                      <span className={c.key === "name" ? "font-medium text-white" : "text-zinc-300"}>{original(r, c) || (c.readOnly ? "-" : "")}</span>
                    )}
                  </td>
                ))}
                {renderActions && <td className="px-3 py-1.5 text-right">{renderActions(r)}</td>}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {filtered.length > shown && (
        <button className={btn} onClick={() => setShown((n) => n + PAGE)}>
          Daha fazla göster ({filtered.length - shown} kayıt daha)
        </button>
      )}

      {canEditAny ? (
        <div className="flex flex-wrap items-center gap-3">
          <button className={btnPrimary} disabled={busy || changedCount === 0 || hasInvalid} onClick={save}>
            💾 Değişiklikleri kaydet{changedCount > 0 ? ` (${changedCount})` : ""}
          </button>
          {changedCount > 0 && (
            <button className={btn} disabled={busy} onClick={() => setEdits({})}>
              Vazgeç
            </button>
          )}
          {hasInvalid && <span className="text-xs text-red-300">Geçersiz ya da negatif bir sayı var; kırmızı alanı düzeltin.</span>}
        </div>
      ) : (
        <p className="text-xs text-zinc-500">Bu tabloyu düzenleme yetkiniz yok.</p>
      )}
    </div>
  );
}
