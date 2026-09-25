"use client";

import { useState } from "react";
import type { ReqDetail } from "@/lib/api";

// Yazma eylemleri: aşama ilerletme, müşteri kararı, teklif PDF/iletildi, geri alma, rafa kaldırma, yeniden açma.
// Hepsi backend'in ince endpoint'lerini çağırır; yetki ve iş kuralı hep jarvis.services'te (burada yalnızca
// düğmeleri göstermek/gizlemek için req.can_* bayrakları kullanılır). Veri girişi olan aşama panelleri
// (Talep/Fiyat/Gümrük/Teklif alanları/Teslim makbuzu) sonraki adımda.

export type ActOpts = { method?: string; ok?: string };
/** Bir eylem çalıştırır; başarıda true. Hata gösterimi ve REQ'i yenileme üst bileşende. */
export type Act = (path: string, body?: unknown, opts?: ActOpts) => Promise<boolean>;

export const btn =
  "rounded-lg border border-zinc-700 px-3 py-1.5 text-sm transition hover:bg-zinc-800 disabled:cursor-not-allowed disabled:opacity-50";
export const btnPrimary =
  "rounded-lg bg-sky-500 px-3 py-1.5 text-sm font-medium text-white transition hover:bg-sky-400 disabled:cursor-not-allowed disabled:opacity-50";

/** Sık sebepler açılır listede; "Diğer" seçilince serbest metin kutusu açılır (Streamlit'teki _reason_picker). */
export function ReasonPicker({
  label,
  options,
  onChange,
}: {
  label: string;
  options: string[];
  onChange: (reason: string) => void;
}) {
  const [choice, setChoice] = useState(options[0]);
  const [custom, setCustom] = useState("");
  const isOther = choice === "Diğer";
  return (
    <div className="space-y-2">
      <label className="block text-xs text-zinc-500">{label}</label>
      <select
        value={choice}
        onChange={(e) => {
          setChoice(e.target.value);
          onChange(e.target.value === "Diğer" ? custom : e.target.value);
        }}
        className="w-full rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-1.5 text-sm outline-none focus:border-sky-500"
      >
        {options.map((o) => (
          <option key={o}>{o}</option>
        ))}
      </select>
      {isOther && (
        <input
          value={custom}
          onChange={(e) => {
            setCustom(e.target.value);
            onChange(e.target.value);
          }}
          placeholder="Listede olmayan bir sebep yazın"
          className="w-full rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-1.5 text-sm outline-none focus:border-sky-500"
        />
      )}
    </div>
  );
}

// Talep/Fiyat/Gümrük/Teklif/Sipariş aşamalarının eylemleri (Kaydet, Kaydet ve aktar, PDF, iletildi) kendi formlarında
// (EditPanels.tsx / StagePanels.SiparisForm) — burada tekrarlanmaz. Burada yalnızca formu olmayan geçişler kalır:
// Müşteri Kararı, Lojistik ("sevkiyat tamamlandı") ve Teslim ("REQ'yi tamamla", yalnızca tüm ürünler teslim edilince).
const FORM_STAGES = ["talep", "fiyat", "gumruk", "teklif", "siparis"];

export function StageActions({ req, stage, act, busy }: { req: ReqDetail; stage: string; act: Act; busy: boolean }) {
  const [reason, setReason] = useState(req.shelve_reasons[0]);
  if (stage !== req.stage || !req.can_advance) return null;

  const next = req.next_stage_label;

  if (FORM_STAGES.includes(stage)) return null;
  if (stage === "teslim" && !req.teslim?.all_delivered) return null; // panelde "tam teslim edilince..." bilgisi var

  let content: React.ReactNode;
  if (stage === "karar") {
    content = (
      <div className="grid gap-4 md:grid-cols-2">
        <div>
          <button
            className={btnPrimary}
            disabled={busy}
            onClick={() => act("/decision", { approved: true }, { ok: "Teklif onaylandı, sipariş aşamasına geçildi." })}
          >
            ✅ Müşteri onayladı → Sipariş
          </button>
        </div>
        <div className="space-y-2">
          <ReasonPicker label="Ret sebebi" options={req.shelve_reasons} onChange={setReason} />
          <button
            className={btn}
            disabled={busy}
            onClick={() => act("/decision", { approved: false, reason }, { ok: "REQ rafa kaldırıldı." })}
          >
            ⏸️ Müşteri reddetti → Rafa kaldır
          </button>
        </div>
      </div>
    );
  } else {
    const label =
      stage === "lojistik"
        ? "✅ Sevkiyat tamamlandı → Teslim aşamasına geç"
        : stage === "teslim"
          ? "✅ Tüm ürünler teslim edildi: REQ'yi tamamla"
          : `Sonraki aşamaya aktar${next ? `: ${next}` : ""} →`;
    content = (
      <button
        className={btnPrimary}
        disabled={busy}
        onClick={() => act("/advance", undefined, { ok: next ? "Sonraki aşamaya aktarıldı." : "REQ tamamlandı." })}
      >
        {label}
      </button>
    );
  }

  return (
    <div className="space-y-3 rounded-xl border border-zinc-800 bg-zinc-900/40 p-5">
      {content}
    </div>
  );
}

/** Sayfanın altındaki "Önceki aşamaya dön" / "Rafa kaldır" (Streamlit'teki _controls'ün yönetici kısmı). */
export function ReqControls({ req, act, busy }: { req: ReqDetail; act: Act; busy: boolean }) {
  const [backReason, setBackReason] = useState(req.move_back_reasons[0]);
  const [shelveReason, setShelveReason] = useState(req.shelve_reasons[0]);
  if (!req.can_move_back && !req.can_shelve) return null;
  return (
    <div className="grid gap-3 md:grid-cols-2">
      {req.can_move_back && (
        <details className="rounded-xl border border-zinc-800 px-5 py-3">
          <summary className="cursor-pointer text-sm text-zinc-300">↩️ Önceki aşamaya dön</summary>
          <div className="mt-3 space-y-3">
            <ReasonPicker label="Sebep" options={req.move_back_reasons} onChange={setBackReason} />
            <p className="text-xs text-zinc-500">Sonraki aşamalardaki onaylar (teklif iletildi, müşteri kararı vb.) sıfırlanır.</p>
            <button
              className={btn}
              disabled={busy}
              onClick={() => act("/move-back", { reason: backReason }, { ok: "Önceki aşamaya dönüldü." })}
            >
              Geri al
            </button>
          </div>
        </details>
      )}
      {req.can_shelve && (
        <details className="rounded-xl border border-zinc-800 px-5 py-3">
          <summary className="cursor-pointer text-sm text-zinc-300">⏸️ Rafa kaldır</summary>
          <div className="mt-3 space-y-3">
            <ReasonPicker label="Sebep" options={req.shelve_reasons} onChange={setShelveReason} />
            <button
              className={btn}
              disabled={busy}
              onClick={() => act("/shelve", { reason: shelveReason }, { ok: "REQ rafa kaldırıldı." })}
            >
              Rafa kaldır
            </button>
          </div>
        </details>
      )}
    </div>
  );
}
