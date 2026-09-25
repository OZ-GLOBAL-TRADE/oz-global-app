"use client";

import { useState } from "react";
import { parseNum } from "@/lib/api";
import { btn } from "./Actions";
import { NumField } from "./ui";

// Ürün satırı düzenleyicisi + "katalogda olmayan ürün ekle" — hem REQ'in Talep paneli (EditPanels.TalepForm) hem de
// Yeni REQ diyaloğu (NewReqDialog) kullanır; ikisinde de davranış aynı olsun diye tek yerde.

let uidCounter = 0; // yalnızca liste satırı anahtarı için benzersiz kimlik
export const nextUid = () => uidCounter++;

/** `fallbackName`: mevcut bir REQ satırının ürünü katalogdan kalıcı silinmişse (product_id yok) satır yine de adıyla görünür ve korunur. */
export type ItemRow = { uid: number; id: number | null; productId: string; qty: string; fallbackName?: string };

const qtyOf = (s: string): number | null => {
  const n = parseNum(s);
  return n === null || Number.isNaN(n) ? null : n;
};

/** Ürünü seçilmiş bir satırın adedi geçerli bir 0'dan büyük sayı değilse true (ürünü seçilmemiş satırlar kaydedilirken atılır). */
export const rowInvalid = (r: ItemRow): boolean => (!!r.productId || r.id !== null) && (qtyOf(r.qty) ?? 0) <= 0;
export const rowsInvalid = (rows: ItemRow[]): boolean => rows.some(rowInvalid);

export function ItemRows({
  items,
  setItems,
  products,
}: {
  items: ItemRow[];
  setItems: (f: (rows: ItemRow[]) => ItemRow[]) => void;
  products: { id: number; name: string }[];
}) {
  const patch = (u: number, p: Partial<ItemRow>) => setItems((rows) => rows.map((r) => (r.uid === u ? { ...r, ...p } : r)));
  return (
    <div className="space-y-2">
      {items.length === 0 && <p className="text-sm text-zinc-500">Henüz ürün yok; aşağıdan ekleyin.</p>}
      <ul className="space-y-2">
        {items.map((r) => (
          <li key={r.uid} className="flex flex-wrap items-center gap-2">
            <select
              aria-label="Ürün"
              value={r.productId}
              onChange={(e) => patch(r.uid, { productId: e.target.value })}
              className="min-w-64 flex-1 rounded-lg border border-zinc-700 bg-zinc-900 px-2 py-1.5 text-sm outline-none focus:border-sky-500"
            >
              <option value="">{r.id !== null && !r.productId && r.fallbackName ? `${r.fallbackName} (katalogda yok)` : "Ürün seçin…"}</option>
              {products.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
            <NumField label="Adet" value={r.qty} invalid={rowInvalid(r)} onChange={(v) => patch(r.uid, { qty: v })} className="w-24" />
            <button aria-label="Satırı sil" className={btn} onClick={() => setItems((rows) => rows.filter((x) => x.uid !== r.uid))}>
              ✕
            </button>
          </li>
        ))}
      </ul>
      <button className={btn} onClick={() => setItems((rows) => [...rows, { uid: nextUid(), id: null, productId: "", qty: "1" }])}>
        ＋ Ürün ekle
      </button>
    </div>
  );
}

const inputCls = "rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-1.5 text-sm outline-none focus:border-sky-500";

/** "＋ Katalogda olmayan ürün ekle": ürünü kataloğa ekler (REQ'e satır eklemez); başarıda alanlar temizlenir. */
export function CatalogAdd({ onAdd, busy }: { onAdd: (name: string, hsCode: string) => Promise<boolean>; busy: boolean }) {
  const [name, setName] = useState("");
  const [hs, setHs] = useState("");
  return (
    <details className="rounded-xl border border-zinc-800 px-4 py-3">
      <summary className="cursor-pointer text-sm text-zinc-300">＋ Katalogda olmayan ürün ekle</summary>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <input aria-label="Yeni ürün adı" placeholder="Ürün adı" value={name} onChange={(e) => setName(e.target.value)} className={`${inputCls} min-w-56 flex-1`} />
        <input aria-label="GTİP" placeholder="GTİP (opsiyonel)" value={hs} onChange={(e) => setHs(e.target.value)} className={`${inputCls} w-44`} />
        <button
          className={btn}
          disabled={busy || !name.trim()}
          onClick={async () => {
            if (await onAdd(name, hs)) {
              setName("");
              setHs("");
            }
          }}
        >
          Ekle
        </button>
      </div>
      <p className="mt-2 text-xs text-zinc-500">Ürün kataloğa eklenir; yukarıdaki listeden seçip satır olarak ekleyin.</p>
    </details>
  );
}
