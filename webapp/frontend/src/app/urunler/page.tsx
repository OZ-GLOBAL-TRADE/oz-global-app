"use client";

import { useEffect, useState } from "react";
import AppShell from "@/components/AppShell";
import EditableTable, { Column } from "@/components/EditableTable";
import ConfirmDialog from "@/components/ConfirmDialog";
import TrashSection from "@/components/TrashSection";
import { btn, btnPrimary } from "@/components/req/Actions";
import { FlashBanner, NumField } from "@/components/req/ui";
import { useAction } from "@/components/useAction";
import { api, ApiError, parseNum, Product, ProductsPayload } from "@/lib/api";

// Streamlit'teki Ürünler sayfasının karşılığı: ürün kataloğu (REQ açarken ürünler buradan seçilir; GTİP gümrük aşamasında
// referans olur). Gümrükçü yalnızca GTİP kodunu düzenleyebilir — sunucu bunu ayrıca zorlar (`editable_fields`).

const field = "w-full rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-1.5 text-sm outline-none focus:border-sky-500";

function AddProduct({ data, busy, onAdd }: { data: ProductsPayload; busy: boolean; onAdd: (body: Record<string, unknown>) => Promise<boolean> }) {
  const [f, setF] = useState({ name: "", category: data.categories[0] ?? "", hs_code: "", supplier: "", last_cost: "", spec: "" });
  const cost = parseNum(f.last_cost);
  const costBad = cost !== null && (Number.isNaN(cost) || cost < 0);
  const set = (k: keyof typeof f) => (v: string) => setF((p) => ({ ...p, [k]: v }));
  // Yazdıkça adı benzer mevcut ürünler gösterilir: aynı ürünü tekrar eklemeyin (birebir aynı ad zaten sunucuda engelleniyor)
  const q = f.name.trim().toLowerCase();
  const similar = q ? data.products.filter((p) => p.name.toLowerCase().includes(q)).slice(0, 8) : [];

  return (
    <details className="rounded-xl border border-zinc-800 px-5 py-3">
      <summary className="cursor-pointer text-sm text-zinc-300">＋ Yeni ürün ekle</summary>
      <div className="mt-4 space-y-3">
        <div>
          <label className="mb-1 block text-xs text-zinc-500">Ürün kodu / adı *</label>
          <input aria-label="Ürün adı" value={f.name} onChange={(e) => set("name")(e.target.value)} className={field} />
          {similar.length > 0 && (
            <div className="mt-2 space-y-0.5 text-xs text-amber-300">
              <div>⚠️ Katalogda benzer ürün(ler) var; aynı ürünü tekrar eklemeyin:</div>
              {similar.map((p) => (
                <div key={p.id} className="text-zinc-400">
                  • <b className="text-zinc-300">{p.name}</b> · {p.category || "-"} · GTİP {p.hs_code || "-"}
                </div>
              ))}
            </div>
          )}
        </div>
        <div className="grid gap-3 md:grid-cols-2">
          <div>
            <label className="mb-1 block text-xs text-zinc-500">Kategori</label>
            <select aria-label="Kategori" value={f.category} onChange={(e) => set("category")(e.target.value)} className={field}>
              {data.categories.map((c) => (
                <option key={c}>{c}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="mb-1 block text-xs text-zinc-500">GTİP</label>
            <input aria-label="GTİP" value={f.hs_code} onChange={(e) => set("hs_code")(e.target.value)} className={field} />
          </div>
        </div>
        <div className="grid gap-3 md:grid-cols-[3fr_1.5fr]">
          <div>
            <label className="mb-1 block text-xs text-zinc-500">Varsayılan tedarikçi (opsiyonel)</label>
            <select aria-label="Varsayılan tedarikçi" value={f.supplier} onChange={(e) => set("supplier")(e.target.value)} className={field}>
              <option value="">-</option>
              {data.suppliers.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="mb-1 block text-xs text-zinc-500">Son alış fiyatı</label>
            <NumField label="Son alış fiyatı" className="w-full" value={f.last_cost} invalid={costBad} onChange={set("last_cost")} />
          </div>
        </div>
        <div>
          <label className="mb-1 block text-xs text-zinc-500">Özellikler</label>
          <textarea aria-label="Özellikler" rows={2} value={f.spec} onChange={(e) => set("spec")(e.target.value)} className={field} />
        </div>
        <button
          className={btnPrimary}
          disabled={busy || !f.name.trim() || costBad}
          onClick={async () => {
            const body = {
              name: f.name, category: f.category, hs_code: f.hs_code, spec: f.spec,
              last_cost: cost === null || Number.isNaN(cost) ? null : cost,
              default_supplier_id: f.supplier ? Number(f.supplier) : null,
            };
            if (await onAdd(body)) setF({ ...f, name: "", hs_code: "", supplier: "", last_cost: "", spec: "" });
          }}
        >
          Ürünü kaydet
        </button>
      </div>
    </details>
  );
}

function UrunlerContent() {
  const [data, setData] = useState<ProductsPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const { busy, flash, run } = useAction();
  const [tick, setTick] = useState(0); // listeyi sunucudan yeniden çekmek için (kayıt hatası / çöp kutusundan geri yükleme sonrası)
  const [deleting, setDeleting] = useState<Product | null>(null);
  const [trashTick, setTrashTick] = useState(0); // her silmede artar → açık çöp kutusu yenilenir
  const refresh = () => setTick((t) => t + 1);

  useEffect(() => {
    api<ProductsPayload>("/api/products")
      .then(setData)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Bilinmeyen hata"));
  }, [tick]);

  const columns: Column<Product>[] = [
    { key: "name", label: "Ürün" }, // ad düzenlenebilir (yalnızca yönetici roller; sunucu çakışmayı denetler)
    { key: "category", label: "Kategori", suggestions: data?.categories },
    { key: "hs_code", label: "GTİP" },
    { key: "last_cost", label: "Son Alış", type: "number" },
    { key: "spec", label: "Özellikler", wide: true },
    { key: "notes", label: "Notlar", wide: true },
  ];

  async function save(changes: Record<string, unknown>[]) {
    const r = await run(
      () => api<ProductsPayload>("/api/products/update", { method: "POST", body: JSON.stringify({ rows: changes }) }),
      (res) => (res.changed ? `${res.changed} alan güncellendi.` : "Değişiklik yok."),
    );
    if (r) setData(r);
    else refresh(); // ad reddedilirse diğer alanlar kaydedilmiş olabilir: listeyi sunucuyla eşitle
    return !!r;
  }

  async function remove(p: Product): Promise<boolean> {
    const r = await run(() => api<ProductsPayload>(`/api/products/${p.id}/delete`, { method: "POST" }), `${p.name} silinenlere taşındı.`);
    if (r) {
      setData(r);
      setTrashTick((n) => n + 1);
    }
    return !!r;
  }

  async function add(body: Record<string, unknown>) {
    const r = await run(() => api<ProductsPayload>("/api/products", { method: "POST", body: JSON.stringify(body) }), (res) => `${res.added?.name} kataloğa eklendi.`);
    if (r) setData(r);
    return !!r;
  }

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-semibold">Ürünler</h1>
        <p className="mt-1 text-sm text-zinc-500">Ürün kataloğu. REQ açarken ürünler buradan seçilir; GTİP kodu gümrük aşamasında referans olur.</p>
      </div>

      <FlashBanner flash={flash} />
      {error && <div className="text-red-400">⚠️ {error}</div>}
      {!data && !error && <div className="text-zinc-400">Yükleniyor…</div>}

      {deleting && (
        <ConfirmDialog title="Silinenlere taşı" confirmLabel="Sil" danger onConfirm={() => remove(deleting)} onClose={() => setDeleting(null)}>
          <p>
            <b className="text-white">{deleting.name}</b> katalogdan kaldırılacak; yeni REQ açarken seçilemez. Silinenler bölümünden geri yüklenebilir.
          </p>
          {deleting.line_count > 0 && (
            <p className="text-amber-300">
              Bu ürün {deleting.line_count} REQ satırında kullanılıyor: satırlar ve ürün adı korunur, REQ&apos;ler bozulmaz.
            </p>
          )}
        </ConfirmDialog>
      )}

      {data && (
        <>
          <EditableTable
            rows={data.products}
            columns={columns}
            editableKeys={data.editable_fields}
            onSave={save}
            busy={busy}
            searchKeys={["name", "category", "hs_code", "spec", "notes"]}
            emptyText="Katalogda ürün yok."
            renderActions={
              data.can_add
                ? (p) => (
                    <button className={btn} aria-label={`Sil: ${p.name}`} disabled={busy} onClick={() => setDeleting(p)}>
                      🗑️
                    </button>
                  )
                : undefined
            }
          />
          {data.editable_fields.length === 1 && <p className="text-xs text-zinc-500">Bu hesap yalnızca GTİP kodunu düzenleyebilir.</p>}
          {data.can_add && <AddProduct data={data} busy={busy} onAdd={add} />}
          {data.can_add && <TrashSection refreshKey={trashTick} kind="products" label="ürünler" onRestored={refresh} />}
        </>
      )}
    </div>
  );
}

export default function UrunlerPage() {
  return (
    <AppShell>
      <UrunlerContent />
    </AppShell>
  );
}
