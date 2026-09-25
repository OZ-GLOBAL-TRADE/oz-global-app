"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api, ApiError, NewReqOptions, parseNum, reqHref } from "@/lib/api";
import { btn, btnPrimary } from "./Actions";
import { CatalogAdd, ItemRow, ItemRows, nextUid, rowsInvalid } from "./ItemRows";
import { Flash, FlashBanner, NumField, SectionTitle } from "./ui";

// Yeni REQ diyaloğu (talepler.py::_new_req_dialog'un karşılığı). Yalnızca açıkken bağlanır → her açılışta temiz başlar.
// Müşteri/ürün seçenekleri sunucudan gelir; yeni müşteri ve katalog ürünü eklemek seçenekleri yeniler, girilenleri silmez.

const field = "w-full rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-1.5 text-sm outline-none focus:border-sky-500";

export default function NewReqDialog({ onClose }: { onClose: () => void }) {
  const router = useRouter();
  const [opts, setOpts] = useState<NewReqOptions | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [flash, setFlash] = useState<Flash>(null);
  const [busy, setBusy] = useState(false);

  const [customerId, setCustomerId] = useState("");
  const [currency, setCurrency] = useState("USD");
  const [delivery, setDelivery] = useState("");
  const [items, setItems] = useState<ItemRow[]>(() => [{ uid: nextUid(), id: null, productId: "", qty: "1" }]);
  const [notes, setNotes] = useState("");
  // yeni müşteri alanları
  const [nc, setNc] = useState({ name: "", short_code: "", req_seq: "0", tax_no: "", address: "" });

  useEffect(() => {
    api<NewReqOptions>("/api/new-req/options")
      .then((o) => {
        setOpts(o);
        setDelivery((d) => d || o.delivery_types[0]);
        setCustomerId((c) => c || (o.customers[0] ? String(o.customers[0].id) : ""));
      })
      .catch((err) => setLoadError(err instanceof ApiError ? err.message : "Bilinmeyen hata"));
  }, []);

  useEffect(() => {
    const onKey = (ev: KeyboardEvent) => ev.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  /** Sunucu çağrısı: hata bandı + meşgul durumu tek yerde. Başarıda sonucu, hatada null döner. */
  async function call<T>(path: string, body: unknown): Promise<T | null> {
    if (busy) return null;
    setBusy(true);
    setFlash(null);
    try {
      return await api<T>(path, { method: "POST", body: JSON.stringify(body) });
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) router.push("/login");
      else setFlash({ tone: "err", lines: err instanceof ApiError ? err.errors : ["Bilinmeyen hata"] });
      return null;
    } finally {
      setBusy(false);
    }
  }

  async function addCustomer() {
    const seq = parseNum(nc.req_seq);
    if (seq === null || Number.isNaN(seq) || seq < 0 || !Number.isInteger(seq)) {
      setFlash({ tone: "err", lines: ["Son REQ no 0 ya da pozitif bir tam sayı olmalı."] });
      return;
    }
    const o = await call<NewReqOptions>("/api/customers", { ...nc, req_seq: seq });
    if (!o) return;
    setOpts(o);
    const created = o.customers.find((c) => c.name === nc.name.split(/\s+/).filter(Boolean).join(" "));
    if (created) setCustomerId(String(created.id));
    setNc({ name: "", short_code: "", req_seq: "0", tax_no: "", address: "" });
    setFlash({ tone: "ok", lines: ["Müşteri eklendi."] });
  }

  async function addProduct(name: string, hs: string): Promise<boolean> {
    const o = await call<NewReqOptions>("/api/catalog-products", { name, hs_code: hs });
    if (!o) return false;
    setOpts(o);
    setFlash({ tone: "ok", lines: [`'${name.trim()}' kataloğa eklendi.`] });
    return true;
  }

  async function create() {
    const res = await call<{ code: string }>("/api/reqs", {
      customer_id: Number(customerId),
      currency,
      delivery_type: delivery,
      notes,
      items: items.map((r) => ({ product_id: r.productId ? Number(r.productId) : null, qty: parseNumOrNull(r.qty) })),
    });
    if (res) router.push(reqHref(res.code));
  }

  const customer = opts?.customers.find((c) => String(c.id) === customerId);
  const hasItem = items.some((r) => r.productId);
  const invalid = !customer || !hasItem || rowsInvalid(items);

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/60 p-4 md:p-10" role="dialog" aria-modal="true" aria-label="Yeni Talep (REQ)">
      <div className="w-full max-w-2xl space-y-5 rounded-2xl border border-zinc-800 bg-zinc-950 p-6 shadow-2xl">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold">Yeni Talep (REQ)</h2>
          <button onClick={onClose} aria-label="Kapat" className="rounded-lg px-2 py-1 text-zinc-400 hover:bg-zinc-800">
            ✕
          </button>
        </div>

        {loadError && <div className="text-red-400">⚠️ {loadError}</div>}
        {!opts && !loadError && <div className="text-zinc-400">Yükleniyor…</div>}

        {opts && (
          <>
            <FlashBanner flash={flash} />

            <details open={opts.customers.length === 0} className="rounded-xl border border-zinc-800 px-4 py-3">
              <summary className="cursor-pointer text-sm text-zinc-300">＋ Yeni müşteri ekle</summary>
              <div className="mt-3 space-y-3">
                <div className="grid gap-3 md:grid-cols-[3fr_1.4fr_1.6fr]">
                  <div>
                    <label className="mb-1 block text-xs text-zinc-500">Müşteri adı</label>
                    <input aria-label="Müşteri adı" value={nc.name} onChange={(e) => setNc({ ...nc, name: e.target.value })} className={field} />
                  </div>
                  <div>
                    <label className="mb-1 block text-xs text-zinc-500">Kısa kod</label>
                    <input aria-label="Kısa kod" value={nc.short_code} onChange={(e) => setNc({ ...nc, short_code: e.target.value })} className={field} />
                  </div>
                  <div>
                    <label className="mb-1 block text-xs text-zinc-500">Son REQ no</label>
                    <NumField label="Son REQ no" className="w-full" value={nc.req_seq} onChange={(v) => setNc({ ...nc, req_seq: v })} />
                  </div>
                </div>
                <p className="text-xs text-zinc-500">
                  Kısa kod boşsa otomatik önerilir (örn. Altınay → ALTN). Son REQ no: Odoo&apos;da bu müşteri için kullanılan son numara; kodlar buradan devam eder.
                </p>
                <div>
                  <label className="mb-1 block text-xs text-zinc-500">Vergi No (VKN/TCKN)</label>
                  <input aria-label="Vergi No" value={nc.tax_no} onChange={(e) => setNc({ ...nc, tax_no: e.target.value })} className={field} />
                </div>
                <div>
                  <label className="mb-1 block text-xs text-zinc-500">Adres</label>
                  <textarea aria-label="Adres" rows={2} value={nc.address} onChange={(e) => setNc({ ...nc, address: e.target.value })} className={field} />
                  <p className="mt-1 text-xs text-zinc-500">Vergi no ve adres teklif PDF&apos;inde müşteri bilgisi altında görünür.</p>
                </div>
                <button className={btn} disabled={busy || !nc.name.trim()} onClick={addCustomer}>
                  Müşteriyi ekle
                </button>
              </div>
            </details>

            {opts.customers.length > 0 && (
              <>
                <div>
                  <label className="mb-1 block text-xs text-zinc-500">Müşteri</label>
                  <select aria-label="Müşteri" value={customerId} onChange={(e) => setCustomerId(e.target.value)} className={field}>
                    {opts.customers.map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.name}
                      </option>
                    ))}
                  </select>
                  {customer && (
                    <p className="mt-1 text-sm text-zinc-400">
                      Kod otomatik verilecek: <b className="text-white">{customer.next_code}</b>
                    </p>
                  )}
                </div>

                <div className="grid gap-4 md:grid-cols-2">
                  <fieldset>
                    <legend className="mb-1 text-xs text-zinc-500">Para birimi</legend>
                    <div className="flex gap-4 text-sm text-zinc-300">
                      {opts.currencies.map((c) => (
                        <label key={c} className="flex items-center gap-2">
                          <input type="radio" name="nr_currency" checked={currency === c} onChange={() => setCurrency(c)} />
                          {c}
                        </label>
                      ))}
                    </div>
                  </fieldset>
                  <fieldset>
                    <legend className="mb-1 text-xs text-zinc-500">Teslimat tipi</legend>
                    <div className="flex flex-wrap gap-4 text-sm text-zinc-300">
                      {opts.delivery_types.map((d) => (
                        <label key={d} className="flex items-center gap-2">
                          <input type="radio" name="nr_delivery" checked={delivery === d} onChange={() => setDelivery(d)} />
                          {d}
                        </label>
                      ))}
                    </div>
                  </fieldset>
                </div>

                <div className="space-y-2">
                  <SectionTitle>Talep edilen ürünler</SectionTitle>
                  <ItemRows items={items} setItems={setItems} products={opts.products} />
                  <CatalogAdd busy={busy} onAdd={addProduct} />
                </div>

                <div>
                  <label className="mb-1 block text-xs text-zinc-500">Not (opsiyonel)</label>
                  <input aria-label="Not" value={notes} onChange={(e) => setNotes(e.target.value)} className={field} />
                </div>

                <button className={`${btnPrimary} w-full py-2`} disabled={busy || invalid} onClick={create}>
                  REQ&apos;yi Aç
                </button>
                {!hasItem && <p className="text-center text-xs text-zinc-500">En az bir ürün seçin.</p>}
              </>
            )}
          </>
        )}
      </div>
    </div>
  );
}

const parseNumOrNull = (s: string): number | null => {
  const n = parseNum(s);
  return n === null || Number.isNaN(n) ? null : n;
};
