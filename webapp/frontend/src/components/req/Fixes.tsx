"use client";

import { useState } from "react";
import ConfirmDialog from "@/components/ConfirmDialog";
import { parseNum, qty, ReqDetail, toInput } from "@/lib/api";
import { Act, btn, btnPrimary } from "./Actions";
import { NumField } from "./ui";

// Düzeltmeler (jarvis/ui/talepler.py: başlıktaki "✏️ Düzelt" popover'ı ve "🔢 Adetleri düzelt"): aşamadan bağımsız,
// yanlış girilen REQ no / para birimi / adetleri, aşamaya geri dönmeden düzeltir. Yetki ve kurallar serviste.

const REQ_NO = /^(.*)_REQ_(\d+)$/;

/** Başlıktaki "✏️ Düzelt" açılır paneli: REQ numarası (yalnızca sayı; önek müşterinin kısa kodu) ve para birimi. */
export function FixMenu({ req, act, busy }: { req: ReqDetail; act: Act; busy: boolean }) {
  const m = req.code.match(REQ_NO);
  const [no, setNo] = useState(m ? m[2].replace(/^0+(?=\d)/, "") : "");
  const [currency, setCurrency] = useState(req.currency);
  const [customerId, setCustomerId] = useState(String(req.customer_id));
  const [delivery, setDelivery] = useState(req.delivery_type);
  const [notes, setNotes] = useState(req.notes);
  if (!req.can_fix) return null;
  const metaChanged = delivery !== req.delivery_type || notes.trim() !== req.notes;
  const n = parseNum(no);
  const noValid = n !== null && Number.isInteger(n) && n >= 1;

  return (
    <details className="relative">
      <summary className={`${btn} cursor-pointer list-none`}>✏️ Düzelt</summary>
      <div className="absolute right-0 z-30 mt-2 max-h-[75vh] w-96 space-y-4 overflow-y-auto rounded-xl border border-zinc-700 bg-zinc-950 p-4 shadow-2xl">
        <p className="text-xs text-zinc-500">Yanlış girilen REQ numarası, para birimi, müşteri, teslimat tipi ya da notu düzeltir; aşamadan bağımsız çalışır.</p>
        {m && (
          <div className="space-y-1">
            <label className="block text-xs text-zinc-500">REQ no ({m[1]}_REQ_…)</label>
            <div className="flex gap-2">
              <NumField label="REQ no" value={no} invalid={!noValid && no !== ""} onChange={setNo} className="w-24" />
              <button
                className={btn}
                disabled={busy || !noValid}
                onClick={() => act("/req-number", { number: n }, { ok: `REQ kodu düzeltildi.` })}
              >
                Kaydet
              </button>
            </div>
            <p className="text-xs text-zinc-500">Önek müşterinin kısa kodudur (Kişiler&apos;den değişir). Müşterinin sonraki REQ&apos;i bu numaradan devam eder.</p>
          </div>
        )}
        <div className="space-y-1">
          <label className="block text-xs text-zinc-500">Para birimi</label>
          <div className="flex gap-2">
            <select
              aria-label="Para birimi"
              value={currency}
              onChange={(e) => setCurrency(e.target.value)}
              className="rounded-lg border border-zinc-700 bg-zinc-900 px-2 py-1 text-sm outline-none focus:border-sky-500"
            >
              {req.currencies.map((c) => (
                <option key={c}>{c}</option>
              ))}
            </select>
            {currency !== req.currency && (
              <button
                className={btnPrimary}
                disabled={busy}
                onClick={() => act("/currency", { currency }, { ok: `Para birimi ${currency} olarak düzeltildi.` })}
              >
                Para birimini düzelt
              </button>
            )}
          </div>
        </div>

        <div className="space-y-1">
          <label className="block text-xs text-zinc-500">Müşteri</label>
          <div className="flex gap-2">
            <select
              aria-label="Müşteri"
              value={customerId}
              disabled={req.customer_change_blocked}
              onChange={(e) => setCustomerId(e.target.value)}
              className="min-w-0 flex-1 rounded-lg border border-zinc-700 bg-zinc-900 px-2 py-1 text-sm outline-none focus:border-sky-500 disabled:opacity-50"
            >
              {req.customer_options.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
            {customerId !== String(req.customer_id) && (
              <button
                className={btnPrimary}
                disabled={busy}
                onClick={() => act("/customer", { customer_id: Number(customerId) }, { ok: "REQ'in müşterisi değiştirildi." })}
              >
                Değiştir
              </button>
            )}
          </div>
          <p className="text-xs text-zinc-500">
            {req.customer_change_blocked
              ? "Bu REQ için teklif ya da teslimat makbuzu oluşturulmuş; müşteriye giden belgelerle tutarsız kalmaması için müşteri değiştirilemez."
              : "REQ kodu değişmez; kodu yeni müşterinin önekine çevirmek için yukarıdaki REQ no alanını kullanın."}
          </p>
        </div>

        <div className="space-y-2">
          <label className="block text-xs text-zinc-500">Teslimat tipi</label>
          <select
            aria-label="Teslimat tipi"
            value={delivery}
            onChange={(e) => setDelivery(e.target.value)}
            className="w-full rounded-lg border border-zinc-700 bg-zinc-900 px-2 py-1 text-sm outline-none focus:border-sky-500"
          >
            {req.delivery_types.map((d) => (
              <option key={d}>{d}</option>
            ))}
          </select>
          <label className="block text-xs text-zinc-500">Not</label>
          <input
            aria-label="REQ notu"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            className="w-full rounded-lg border border-zinc-700 bg-zinc-900 px-2 py-1 text-sm outline-none focus:border-sky-500"
          />
          <button
            className={btn}
            disabled={busy || !metaChanged}
            onClick={() => act("/meta", { delivery_type: delivery, notes }, { ok: "REQ bilgileri güncellendi." })}
          >
            Kaydet
          </button>
          <p className="text-xs text-zinc-500">Teslimat tipi teklif PDF&apos;inde yer alır; değişirse sonraki teklif yeni revizyon (-R2) olur. Hesap otomatik değişmez.</p>
        </div>
      </div>
    </details>
  );
}

/** REQ'i silinenlere taşır (geri yüklenebilir). Kargoya bağlı REQ silinemez; sunucu nedenini söyler. */
export function DeleteReq({ req, act, busy }: { req: ReqDetail; act: Act; busy: boolean }) {
  const [open, setOpen] = useState(false);
  if (!req.can_delete) return null;
  return (
    <>
      <button
        className="rounded-lg border border-red-500/40 px-3 py-1.5 text-sm text-red-300 transition hover:bg-red-500/10 disabled:opacity-50"
        disabled={busy}
        onClick={() => setOpen(true)}
      >
        🗑️ REQ&apos;i sil
      </button>
      {open && (
        <ConfirmDialog
          title="REQ'i silinenlere taşı"
          confirmLabel="Sil"
          onConfirm={() => act("/delete", undefined, { ok: `${req.code} silinenlere taşındı.` })}
          onClose={() => setOpen(false)}
        >
          <p>
            <b className="text-white">{req.code}</b> ({req.customer}) tüm listelerden, aramalardan ve raporlardan kalkar.
          </p>
          <p className="text-zinc-400">Talepler sayfasındaki Silinenler görünümünden geri yüklenebilir. Kalıcı silme yalnızca yöneticide (Admin).</p>
        </ConfirmDialog>
      )}
    </>
  );
}

/** "🔢 Adetleri düzelt": Talep dışındaki aşamalarda (Talep panelinin kendi adet alanı var) adetleri geri dönmeden düzeltir. */
export function QtyFix({ req, act, busy }: { req: ReqDetail; act: Act; busy: boolean }) {
  const [qtys, setQtys] = useState(() => Object.fromEntries(req.lines.map((l) => [l.id, toInput(l.qty)])));
  if (!req.can_fix || req.stage === "talep") return null;
  const bad = (s: string) => {
    const v = parseNum(s);
    return v === null || Number.isNaN(v) || v <= 0;
  };
  const invalid = req.lines.some((l) => bad(qtys[l.id]));
  return (
    <details className="rounded-xl border border-zinc-800 px-5 py-3">
      <summary className="cursor-pointer text-sm text-zinc-300">🔢 Adetleri düzelt</summary>
      <div className="mt-3 space-y-3">
        <p className="text-xs text-zinc-500">
          Yanlış girilen adetleri önceki aşamalara dönmeden düzeltin. Teslim edilen ya da kargoya ayrılan miktarın altına inilemez. Teklif müşteriye
          iletildiyse, yeni teklif PDF&apos;i revizyon (-R2) olarak oluşur.
        </p>
        <ul className="space-y-2">
          {req.lines.map((l) => (
            <li key={l.id} className="flex items-center gap-3 text-sm text-zinc-300">
              <span className="min-w-0 flex-1 truncate" title={l.name}>
                {l.name} <span className="text-zinc-500">(mevcut {qty(l.qty)})</span>
              </span>
              <NumField label={`Adet: ${l.name}`} value={qtys[l.id]} invalid={bad(qtys[l.id])} onChange={(v) => setQtys((q) => ({ ...q, [l.id]: v }))} className="w-24" />
            </li>
          ))}
        </ul>
        <button
          className={btn}
          disabled={busy || invalid}
          onClick={() => act("/qtys", { lines: req.lines.map((l) => ({ id: l.id, qty: parseNum(qtys[l.id]) })) }, { ok: "Adetler güncellendi." })}
        >
          Adetleri kaydet
        </button>
      </div>
    </details>
  );
}
