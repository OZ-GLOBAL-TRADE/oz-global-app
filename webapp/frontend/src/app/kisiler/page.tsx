"use client";

import { useEffect, useState } from "react";
import AppShell from "@/components/AppShell";
import EditableTable, { Column } from "@/components/EditableTable";
import ConfirmDialog from "@/components/ConfirmDialog";
import TrashSection from "@/components/TrashSection";
import { btn, btnPrimary } from "@/components/req/Actions";
import { FlashBanner, NumField } from "@/components/req/ui";
import { useAction } from "@/components/useAction";
import { api, ApiError, parseNum, Partner, PartnersPayload } from "@/lib/api";

// Streamlit'teki Kişiler sayfasının karşılığı: müşteri ve tedarikçi kayıtları (REQ açarken müşteriler buradan seçilir;
// Jarvis tedarikçi taramasını bu havuzdan yapar). Ad ve kod alanları düzenlenemez; yetki sunucuda (services).

type Kind = "customers" | "suppliers";

const field = "w-full rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-1.5 text-sm outline-none focus:border-sky-500";

function Label({ children }: { children: string }) {
  return <label className="mb-1 block text-xs text-zinc-500">{children}</label>;
}

function AddCustomer({ kinds, busy, onAdd }: { kinds: string[]; busy: boolean; onAdd: (body: Record<string, unknown>) => Promise<boolean> }) {
  const [f, setF] = useState({ name: "", short_code: "", req_seq: "0", kind: kinds[0] ?? "", tax_no: "", phone: "", email: "", address: "" });
  const seq = parseNum(f.req_seq);
  const seqBad = seq === null || Number.isNaN(seq) || seq < 0 || !Number.isInteger(seq);
  const set = (k: keyof typeof f) => (v: string) => setF((p) => ({ ...p, [k]: v }));
  return (
    <details className="rounded-xl border border-zinc-800 px-5 py-3">
      <summary className="cursor-pointer text-sm text-zinc-300">＋ Yeni müşteri ekle</summary>
      <div className="mt-4 space-y-3">
        <div className="grid gap-3 md:grid-cols-[3fr_1.3fr_1.5fr]">
          <div>
            <Label>Müşteri adı *</Label>
            <input aria-label="Müşteri adı" value={f.name} onChange={(e) => set("name")(e.target.value)} className={field} />
          </div>
          <div>
            <Label>Kısa kod</Label>
            <input aria-label="Kısa kod" value={f.short_code} onChange={(e) => set("short_code")(e.target.value)} className={field} />
          </div>
          <div>
            <Label>Son REQ no</Label>
            <NumField label="Son REQ no" className="w-full" value={f.req_seq} invalid={seqBad} onChange={set("req_seq")} />
          </div>
        </div>
        <p className="text-xs text-zinc-500">
          Kısa kod boşsa otomatik önerilir (örn. Altınay → ALTN); REQ kodu KOD_REQ_01 biçimindedir. Son REQ no: Odoo&apos;da bu müşteri için kullanılan son
          numara; yeni kodlar buradan devam eder.
        </p>
        <div className="grid gap-3 md:grid-cols-3">
          <div>
            <Label>Sektör</Label>
            <select aria-label="Sektör" value={f.kind} onChange={(e) => set("kind")(e.target.value)} className={field}>
              {kinds.map((k) => (
                <option key={k}>{k}</option>
              ))}
            </select>
          </div>
          <div>
            <Label>Vergi No</Label>
            <input aria-label="Vergi No" value={f.tax_no} onChange={(e) => set("tax_no")(e.target.value)} className={field} />
          </div>
          <div>
            <Label>Telefon</Label>
            <input aria-label="Telefon" value={f.phone} onChange={(e) => set("phone")(e.target.value)} className={field} />
          </div>
        </div>
        <div>
          <Label>E-posta</Label>
          <input aria-label="E-posta" value={f.email} onChange={(e) => set("email")(e.target.value)} className={field} />
        </div>
        <div>
          <Label>Adres</Label>
          <textarea aria-label="Adres" rows={2} value={f.address} onChange={(e) => set("address")(e.target.value)} className={field} />
        </div>
        <button
          className={btnPrimary}
          disabled={busy || !f.name.trim() || seqBad}
          onClick={async () => {
            if (await onAdd({ type: "customer", ...f, req_seq: seq })) setF({ ...f, name: "", short_code: "", req_seq: "0", tax_no: "", phone: "", email: "", address: "" });
          }}
        >
          Müşteriyi kaydet
        </button>
      </div>
    </details>
  );
}

function AddSupplier({ categories, busy, onAdd }: { categories: string[]; busy: boolean; onAdd: (body: Record<string, unknown>) => Promise<boolean> }) {
  const [f, setF] = useState({ name: "", category: categories[0] ?? "", keywords: "", country: "", email: "", phone: "", notes: "" });
  const set = (k: keyof typeof f) => (v: string) => setF((p) => ({ ...p, [k]: v }));
  return (
    <details className="rounded-xl border border-zinc-800 px-5 py-3">
      <summary className="cursor-pointer text-sm text-zinc-300">＋ Yeni tedarikçi ekle</summary>
      <div className="mt-4 space-y-3">
        <div className="grid gap-3 md:grid-cols-[3fr_2fr]">
          <div>
            <Label>Tedarikçi firma adı *</Label>
            <input aria-label="Tedarikçi firma adı" value={f.name} onChange={(e) => set("name")(e.target.value)} className={field} />
          </div>
          <div>
            <Label>Kategori</Label>
            <select aria-label="Kategori" value={f.category} onChange={(e) => set("category")(e.target.value)} className={field}>
              {categories.map((k) => (
                <option key={k}>{k}</option>
              ))}
            </select>
          </div>
        </div>
        <div>
          <Label>Anahtar kelimeler</Label>
          <input aria-label="Anahtar kelimeler" value={f.keywords} onChange={(e) => set("keywords")(e.target.value)} className={field} />
          <p className="mt-1 text-xs text-zinc-500">Jarvis&apos;in ürün eşleştirmesi için (örn. Motor, ESC, Pervane).</p>
        </div>
        <div className="grid gap-3 md:grid-cols-3">
          <div>
            <Label>Ülke</Label>
            <input aria-label="Ülke" value={f.country} onChange={(e) => set("country")(e.target.value)} className={field} />
          </div>
          <div>
            <Label>E-posta</Label>
            <input aria-label="E-posta" value={f.email} onChange={(e) => set("email")(e.target.value)} className={field} />
          </div>
          <div>
            <Label>Telefon</Label>
            <input aria-label="Telefon" value={f.phone} onChange={(e) => set("phone")(e.target.value)} className={field} />
          </div>
        </div>
        <div>
          <Label>Notlar / tahmini termin</Label>
          <input aria-label="Notlar" value={f.notes} onChange={(e) => set("notes")(e.target.value)} className={field} />
        </div>
        <button
          className={btnPrimary}
          disabled={busy || !f.name.trim()}
          onClick={async () => {
            if (await onAdd({ type: "supplier", ...f })) setF({ ...f, name: "", keywords: "", country: "", email: "", phone: "", notes: "" });
          }}
        >
          Tedarikçiyi kaydet
        </button>
      </div>
    </details>
  );
}

function KisilerContent() {
  const [kind, setKind] = useState<Kind>("customers");
  const [data, setData] = useState<PartnersPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const { busy, flash, run } = useAction();
  const [tick, setTick] = useState(0); // listeyi sunucudan yeniden çekmek için (kayıt hatası sonrası, çöp kutusundan geri yükleme sonrası)
  const [deleting, setDeleting] = useState<Partner | null>(null);
  const [trashTick, setTrashTick] = useState(0); // her silmede artar → açık çöp kutusu yenilenir
  const refresh = () => setTick((t) => t + 1);

  useEffect(() => {
    let cancelled = false; // sekme hızlı değişirse eski yanıt yenisinin üzerine yazmasın
    api<PartnersPayload>(`/api/partners?type=${kind}`)
      .then((d) => {
        if (cancelled) return;
        setData(d);
        setError(null);
      })
      .catch((err) => !cancelled && setError(err instanceof ApiError ? err.message : "Bilinmeyen hata"));
    return () => {
      cancelled = true;
    };
  }, [kind, tick]);

  // Ad ve müşteri kısa kodu artık düzenlenebilir (sunucu çakışmayı denetler). Kısa kod yalnızca YENİ REQ'leri etkiler;
  // mevcut REQ kodları (ör. TTRA_REQ_17) aynen kalır.
  const customerCols: Column<Partner>[] = [
    { key: "name", label: "Ad" },
    { key: "short_code", label: "Kod" },
    { key: "req_seq", label: "Son REQ No", readOnly: true },
    { key: "kind", label: "Sektör", suggestions: data?.customer_kinds },
    { key: "tax_no", label: "Vergi No" },
    { key: "address", label: "Adres", wide: true },
    { key: "email", label: "E-posta" },
    { key: "phone", label: "Telefon" },
    { key: "notes", label: "Notlar", wide: true },
  ];
  const supplierCols: Column<Partner>[] = [
    { key: "name", label: "Ad" },
    { key: "category", label: "Kategori", suggestions: data?.supplier_categories },
    { key: "keywords", label: "Anahtar Kelimeler", wide: true },
    { key: "country", label: "Ülke" },
    { key: "email", label: "E-posta" },
    { key: "phone", label: "Telefon" },
    { key: "notes", label: "Notlar", wide: true },
  ];
  const editableKeys = data?.can_edit ? (kind === "customers" ? customerCols : supplierCols).filter((c) => !c.readOnly).map((c) => c.key) : [];

  async function save(changes: Record<string, unknown>[]) {
    const r = await run(
      () => api<PartnersPayload>("/api/partners/update", { method: "POST", body: JSON.stringify({ type: kind, rows: changes }) }),
      (res) => (res.changed ? `${res.changed} alan güncellendi.` : "Değişiklik yok."),
    );
    if (r) setData(r);
    else refresh(); // çok alanlı kayıtta ilk adımlar uygulanmış olabilir (ör. ad değişti, kod reddedildi): listeyi sunucuyla eşitle
    return !!r;
  }

  async function remove(p: Partner): Promise<boolean> {
    const r = await run(
      () => api<PartnersPayload>(`/api/partners/${p.id}/delete`, { method: "POST", body: JSON.stringify({ type: kind }) }),
      `${p.name} silinenlere taşındı.`,
    );
    if (r) {
      setData(r);
      setTrashTick((n) => n + 1);
    }
    return !!r;
  }

  async function add(body: Record<string, unknown>) {
    const r = await run(
      () => api<PartnersPayload>("/api/partners", { method: "POST", body: JSON.stringify(body) }),
      (res) => (kind === "customers" ? `${res.added?.name} eklendi (kod: ${res.added?.short_code}).` : `${res.added?.name} eklendi.`),
    );
    if (r) setData(r);
    return !!r;
  }

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-semibold">Kişiler</h1>
        <p className="mt-1 text-sm text-zinc-500">
          Müşteri ve tedarikçi kayıtları. REQ açarken müşteriler buradan seçilir; Jarvis tedarikçi taramasını bu havuzdan yapar.
        </p>
      </div>

      <div role="tablist" aria-label="Kişi türü" className="flex w-fit gap-1 rounded-lg border border-zinc-800 p-1">
        {(["customers", "suppliers"] as const).map((k) => (
          <button
            key={k}
            role="tab"
            aria-selected={kind === k}
            onClick={() => setKind(k)}
            className={`rounded-md px-3 py-1 text-sm transition ${kind === k ? "bg-sky-500 text-white" : "text-zinc-400 hover:bg-zinc-900"}`}
          >
            {k === "customers" ? "Müşteriler" : "Tedarikçiler"}
          </button>
        ))}
      </div>

      <FlashBanner flash={flash} />
      {error && <div className="text-red-400">⚠️ {error}</div>}
      {!data && !error && <div className="text-zinc-400">Yükleniyor…</div>}

      {deleting && (
        <ConfirmDialog
          title="Silinenlere taşı"
          confirmLabel="Sil"
          danger
          onConfirm={() => remove(deleting)}
          onClose={() => setDeleting(null)}
        >
          <p>
            <b className="text-white">{deleting.name}</b> silinenlere taşınacak; listelerden ve yeni REQ açarken seçimden kalkar. Silinenler bölümünden geri
            yüklenebilir.
          </p>
          {kind === "customers" && deleting.req_count > 0 && (
            <p className="text-amber-300">
              Bu müşterinin {deleting.req_count} REQ&apos;i var: REQ&apos;ler silinmez, müşteri adı üzerlerinde görünmeye devam eder.
            </p>
          )}
          {kind === "suppliers" && (deleting.line_count > 0 || deleting.product_count > 0) && (
            <p className="text-amber-300">
              Bu tedarikçi {deleting.line_count} REQ satırında seçili ve {deleting.product_count} ürünün varsayılan tedarikçisi; bu kayıtlar korunur.
            </p>
          )}
        </ConfirmDialog>
      )}

      {data && (
        <>
          <EditableTable
            key={kind}
            rows={data.partners}
            columns={kind === "customers" ? customerCols : supplierCols}
            editableKeys={editableKeys}
            onSave={save}
            busy={busy}
            searchKeys={["name", "short_code", "email", "phone", "kind", "category", "keywords", "country", "tax_no"]}
            emptyText="Kayıt yok."
            renderActions={
              data.can_edit
                ? (p) => (
                    <button className={btn} aria-label={`Sil: ${p.name}`} disabled={busy} onClick={() => setDeleting(p)}>
                      🗑️
                    </button>
                  )
                : undefined
            }
          />
          {data.can_edit && (kind === "customers" ? (
            <AddCustomer kinds={data.customer_kinds} busy={busy} onAdd={add} />
          ) : (
            <AddSupplier categories={data.supplier_categories} busy={busy} onAdd={add} />
          ))}
          {data.can_edit && <TrashSection key={kind} refreshKey={trashTick} kind={kind} label={kind === "customers" ? "müşteriler" : "tedarikçiler"} onRestored={refresh} />}
        </>
      )}
    </div>
  );
}

export default function KisilerPage() {
  return (
    <AppShell>
      <KisilerContent />
    </AppShell>
  );
}
