"use client";

import { useCallback, useEffect, useState } from "react";
import { api, ApiError, fmtDate, TrashItem, TrashPayload } from "@/lib/api";
import ConfirmDialog from "./ConfirmDialog";
import { btn } from "./req/Actions";
import { FlashBanner } from "./req/ui";
import { useAction } from "./useAction";

export type TrashKind = "reqs" | "customers" | "suppliers" | "products";

/**
 * Silinenler (çöp kutusu). Geri yükleme yönetici rollerinde; KALICI silme yalnızca Admin'de ve kaydın adını/kodunu yazarak onayla
 * (sunucu her ikisini de ayrıca zorlar). `embedded`: açılır başlık olmadan doğrudan liste (Talepler'in "Silinenler" görünümü).
 * `onRestored`: geri yüklenince üst sayfanın ana listesini yenilemesi için.
 */
export default function TrashSection({
  kind,
  label,
  embedded = false,
  onRestored,
  refreshKey = 0,
}: {
  kind: TrashKind;
  label: string;
  embedded?: boolean;
  onRestored?: () => void;
  /** Üst sayfa her yeni silmede bunu artırır: açık çöp kutusu eski listeyi göstermesin diye yeniden yüklenir. */
  refreshKey?: number;
}) {
  const [open, setOpen] = useState(embedded);
  const [data, setData] = useState<TrashPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [purging, setPurging] = useState<TrashItem | null>(null);
  const { busy, flash, run } = useAction();

  const load = useCallback(() => {
    api<TrashPayload>(`/api/trash/${kind}`)
      .then((d) => {
        setData(d);
        setError(null);
      })
      .catch((err) => setError(err instanceof ApiError ? err.message : "Bilinmeyen hata"));
  }, [kind]);

  // Açılış (ya da tür değişimi) ve açılır bölümün ilk açılışında yükle
  useEffect(() => {
    if (open) load();
  }, [open, load, refreshKey]);

  async function restore(item: TrashItem) {
    const r = await run(
      () => api<TrashPayload>(`/api/trash/${kind}/${encodeURIComponent(item.ident)}/restore`, { method: "POST" }),
      `${item.title} geri yüklendi.`,
    );
    if (r) {
      setData(r);
      onRestored?.();
    }
  }

  async function purge(item: TrashItem, confirm: string): Promise<boolean> {
    const r = await run(
      () => api<TrashPayload>(`/api/trash/${kind}/${encodeURIComponent(item.ident)}/purge`, { method: "POST", body: JSON.stringify({ confirm }) }),
      `${item.title} kalıcı olarak silindi.`,
    );
    if (r) setData(r);
    return !!r;
  }

  const body = (
    <div className="space-y-3">
      <FlashBanner flash={flash} />
      {error && <p className="text-sm text-red-400">⚠️ {error}</p>}
      {!data && !error && <p className="text-sm text-zinc-400">Yükleniyor…</p>}
      {data && data.items.length === 0 && <p className="text-sm text-zinc-500">Silinen kayıt yok.</p>}
      {data && data.items.length > 0 && (
        <ul className="divide-y divide-zinc-800 rounded-xl border border-zinc-800">
          {data.items.map((it) => (
            <li key={it.ident} className="flex flex-wrap items-center gap-3 px-4 py-3 text-sm">
              <div className="min-w-0 flex-1">
                <div className="font-medium text-white">{it.title}</div>
                <div className="text-xs text-zinc-500">
                  {it.subtitle} · silindi {it.deleted_at ? fmtDate(it.deleted_at) : "-"}
                  {it.deleted_by ? ` · ${it.deleted_by}` : ""}
                </div>
                {it.blocked && data.can_purge && <div className="mt-1 text-xs text-amber-300">{it.blocked}</div>}
              </div>
              <button className={btn} disabled={busy} onClick={() => restore(it)}>
                ↩️ Geri yükle
              </button>
              {data.can_purge && (
                <button
                  className="rounded-lg border border-red-500/50 px-3 py-1.5 text-sm text-red-300 transition hover:bg-red-500/10 disabled:opacity-50"
                  disabled={busy || !!it.blocked}
                  title={it.blocked ?? "Geri dönüşsüz"}
                  onClick={() => setPurging(it)}
                >
                  Kalıcı sil
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
      {data && !data.can_purge && data.items.length > 0 && <p className="text-xs text-zinc-500">Kalıcı silme yalnızca yöneticide (Admin).</p>}

      {purging && (
        <ConfirmDialog
          title="Kalıcı olarak sil"
          confirmLabel="Kalıcı olarak sil"
          expectText={purging.title}
          onConfirm={(typed) => purge(purging, typed)}
          onClose={() => setPurging(null)}
        >
          <p>
            <b className="text-white">{purging.title}</b> veritabanından tamamen silinecek. <b className="text-red-300">Bu işlem geri alınamaz.</b>
          </p>
          {kind === "reqs" && <p className="text-xs text-zinc-400">REQ ile birlikte satırları, masrafları, notları, teklif/teslimat kayıtları ve dosyaları da gider.</p>}
        </ConfirmDialog>
      )}
    </div>
  );

  if (embedded) return body;
  return (
    <details className="rounded-xl border border-zinc-800 px-5 py-3" onToggle={(e) => setOpen((e.currentTarget as HTMLDetailsElement).open)}>
      <summary className="cursor-pointer text-sm text-zinc-300">🗑️ Silinenler — {label}</summary>
      <div className="mt-3">{open && body}</div>
    </details>
  );
}
