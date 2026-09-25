"use client";

import { useEffect, useState, type ReactNode } from "react";
import { btn } from "./req/Actions";

/**
 * Onay penceresi. `expectText` verilirse (kalıcı silme gibi geri dönüşsüz işlemler) kullanıcı o metni AYNEN yazmadan onay düğmesi
 * açılmaz — yanlışlıkla tıklamayı engeller; sunucu da aynı eşleşmeyi ayrıca zorlar. Escape ve "Vazgeç" kapatır.
 */
export default function ConfirmDialog({
  title,
  children,
  confirmLabel,
  danger = true,
  expectText,
  onConfirm,
  onClose,
}: {
  title: string;
  children: ReactNode;
  confirmLabel: string;
  danger?: boolean;
  expectText?: string;
  /** Başarıda true dönerse pencere kapanır; false/hata ise açık kalır (hata mesajı çağıranın bandında görünür). */
  onConfirm: (typed: string) => Promise<boolean>;
  onClose: () => void;
}) {
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const onKey = (ev: KeyboardEvent) => ev.key === "Escape" && !busy && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [busy, onClose]);

  const ready = expectText === undefined || typed.trim() === expectText;

  async function confirm() {
    setBusy(true);
    try {
      if (await onConfirm(typed.trim())) onClose();
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/70 p-4" role="alertdialog" aria-modal="true" aria-label={title}>
      <div className="w-full max-w-md space-y-4 rounded-2xl border border-zinc-700 bg-zinc-950 p-6 shadow-2xl">
        <h2 className="text-lg font-semibold">{title}</h2>
        <div className="space-y-2 text-sm text-zinc-300">{children}</div>
        {expectText !== undefined && (
          <div>
            <label className="mb-1 block text-xs text-zinc-500">
              Onaylamak için şunu aynen yazın: <b className="text-zinc-200">{expectText}</b>
            </label>
            <input
              value={typed}
              onChange={(e) => setTyped(e.target.value)}
              aria-label="Onay metni"
              autoFocus
              className="w-full rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-1.5 text-sm outline-none focus:border-red-500"
            />
          </div>
        )}
        <div className="flex justify-end gap-2">
          <button className={btn} disabled={busy} onClick={onClose}>
            Vazgeç
          </button>
          <button
            disabled={busy || !ready}
            onClick={confirm}
            className={`rounded-lg px-3 py-1.5 text-sm font-medium text-white transition disabled:cursor-not-allowed disabled:opacity-50 ${
              danger ? "bg-red-600 hover:bg-red-500" : "bg-sky-500 hover:bg-sky-400"
            }`}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
