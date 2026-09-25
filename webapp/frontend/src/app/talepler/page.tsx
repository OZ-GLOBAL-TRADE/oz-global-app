"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import AppShell from "@/components/AppShell";
import { btn } from "@/components/req/Actions";
import NewReqDialog from "@/components/req/NewReqDialog";
import TrashSection from "@/components/TrashSection";
import { FlashBanner, Flash } from "@/components/req/ui";
import { api, ApiError, downloadPost, fmtDate, money, ReqList, ReqRow, reqHref } from "@/lib/api";

const STATUS_TABS: { key: string; label: string }[] = [
  { key: "aktif", label: "Aktif" },
  { key: "tamamlanan", label: "Tamamlanan" },
  { key: "rafa", label: "Rafa Kaldırılan" },
  { key: "tumu", label: "Tümü" },
];

type View = "liste" | "asama" | "cop";
const VIEWS: { key: View; label: string }[] = [
  { key: "liste", label: "Liste" },
  { key: "asama", label: "Aşama Görünümü" },
];

function statusPill(status: string) {
  const map: Record<string, string> = {
    aktif: "bg-sky-500/20 text-sky-300",
    tamamlandi: "bg-emerald-500/20 text-emerald-300",
    rafa: "bg-red-500/20 text-red-300",
  };
  return map[status] || "bg-zinc-700 text-zinc-300";
}


/** Aşama Görünümü (Kanban): her aktif REQ kendi aşama sütununda; tamamlanan/rafa kaldırılanlar altta açılır listede. */
function Board({ data }: { data: ReqList }) {
  const active = data.reqs.filter((r) => r.status === "aktif");
  const closed = data.reqs.filter((r) => r.status !== "aktif");
  const card = (r: ReqRow) => (
    <Link key={r.code} href={reqHref(r.code)} className="block rounded-lg border border-zinc-800 bg-zinc-900/60 px-3 py-2 text-sm hover:border-sky-500">
      <div className="font-medium text-white">{r.code}</div>
      <div className="text-xs text-zinc-400">{r.customer}</div>
      {data.can_view_amount && r.teklif !== null && <div className="mt-1 text-xs text-zinc-300">{money(r.teklif, r.currency)}</div>}
    </Link>
  );
  return (
    <div className="space-y-4">
      <div className="grid gap-3 md:grid-cols-4 xl:grid-cols-8">
        {data.stages.map((st) => {
          const items = active.filter((r) => r.stage === st.key);
          return (
            <section key={st.key} aria-label={st.label} className="min-w-0 space-y-2">
              <h3 className="flex items-center justify-between rounded-lg bg-zinc-900 px-3 py-2 text-xs font-semibold text-zinc-300">
                <span className="truncate">{st.label}</span>
                <span className="ml-2 rounded-full bg-zinc-800 px-2 py-0.5 text-zinc-400">{items.length}</span>
              </h3>
              {items.map(card)}
            </section>
          );
        })}
      </div>
      {closed.length > 0 && (
        <details className="rounded-xl border border-zinc-800 px-5 py-3">
          <summary className="cursor-pointer text-sm text-zinc-300">Tamamlanan / Rafa kaldırılan ({closed.length})</summary>
          <ul className="mt-3 flex flex-wrap gap-2">
            {closed.map((r) => (
              <li key={r.code}>
                <Link href={reqHref(r.code)} className={`${btn} inline-block`}>
                  {r.code} · {r.stage_label}
                </Link>
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

function TaleplerContent() {
  const router = useRouter();
  const [data, setData] = useState<ReqList | null>(null);
  const [status, setStatus] = useState("aktif");
  const [view, setView] = useState<View>("liste");
  const [q, setQ] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [newOpen, setNewOpen] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [exporting, setExporting] = useState(false);
  const [flash, setFlash] = useState<Flash>(() => {
    // Başka bir sayfadan (REQ silme, gümrükçünün aşama ilerletmesi) dönüldüyse orada saklanan başarı mesajını göster
    try {
      const m = sessionStorage.getItem("jarvis_flash");
      if (m) {
        sessionStorage.removeItem("jarvis_flash");
        return { tone: "ok", lines: [m] };
      }
    } catch {}
    return null;
  });
  const [reload, setReload] = useState(0); // Silinenler'den geri yüklenince listeyi yenilemek için

  // Aşama Görünümü tüm durumları getirir (tamamlanan/rafa altta gösterilir); durum sekmeleri yalnızca Liste'de geçerli
  const fetchStatus = view === "asama" ? "tumu" : status;
  useEffect(() => {
    const handle = setTimeout(() => {
      api<ReqList>(`/api/reqs?status=${fetchStatus}&q=${encodeURIComponent(q)}`)
        .then((d) => {
          setData(d);
          setError(null);
        })
        .catch((err) => setError(err instanceof Error ? err.message : "Bilinmeyen hata"));
    }, 200); // arama kutusunda her tuşta değil, yazma durunca sorgula
    return () => clearTimeout(handle);
  }, [fetchStatus, q, reload]);

  // Yalnızca ekranda görünen seçili satırlar sayılır/indirilir (filtre değişince gizlenen seçim sessizce dışarıda kalmasın)
  const visibleSelected = data ? data.reqs.filter((r) => selected.has(r.code)) : [];
  const allChecked = !!data && data.reqs.length > 0 && visibleSelected.length === data.reqs.length;

  function toggle(code: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (!next.delete(code)) next.add(code);
      return next;
    });
  }

  async function exportSelected() {
    setExporting(true);
    setFlash(null);
    try {
      await downloadPost("/api/reqs/export", { codes: visibleSelected.map((r) => r.code) }, "talepler.xlsx");
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) router.push("/login");
      else setFlash({ tone: "err", lines: err instanceof ApiError ? err.errors : ["İndirme başarısız."] });
    } finally {
      setExporting(false);
    }
  }

  return (
    <>
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <h1 className="text-xl font-semibold">Talepler</h1>
        <div className="flex gap-1 rounded-lg border border-zinc-800 p-1">
          {VIEWS.map((v) => (
            <button
              key={v.key}
              onClick={() => setView(v.key)}
              className={`rounded-md px-3 py-1 text-sm transition ${view === v.key ? "bg-sky-500 text-white" : "text-zinc-400 hover:bg-zinc-900"}`}
            >
              {v.label}
            </button>
          ))}
        </div>
        {data?.can_create && (
          <button
            onClick={() => setView("cop")}
            className={`rounded-lg border px-3 py-1 text-sm transition ${view === "cop" ? "border-sky-500 bg-sky-500 text-white" : "border-zinc-800 text-zinc-400 hover:bg-zinc-900"}`}
          >
            🗑️ Silinenler
          </button>
        )}
        {view === "liste" && (
          <div className="flex gap-1 rounded-lg border border-zinc-800 p-1">
            {STATUS_TABS.map((t) => (
              <button
                key={t.key}
                onClick={() => setStatus(t.key)}
                className={`rounded-md px-3 py-1 text-sm transition ${
                  status === t.key ? "bg-sky-500 text-white" : "text-zinc-400 hover:bg-zinc-900"
                }`}
              >
                {t.label}
              </button>
            ))}
          </div>
        )}
        {data?.can_create && (
          <button
            onClick={() => setNewOpen(true)}
            className="rounded-lg bg-sky-500 px-3 py-1.5 text-sm font-medium text-white transition hover:bg-sky-400"
          >
            ＋ Yeni REQ
          </button>
        )}
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="REQ kodu, müşteri veya ürün ara…"
          className="ml-auto w-72 rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-1.5 text-sm outline-none focus:border-sky-500"
        />
      </div>

      <div className="mb-3">
        <FlashBanner flash={flash} />
      </div>
      {error && <div className="text-red-400">⚠️ {error}</div>}
      {!data && !error && <div className="text-zinc-400">Yükleniyor…</div>}
      {data && data.reqs.length === 0 && view !== "cop" && <div className="text-zinc-400">Bu filtrede REQ yok.</div>}

      {view === "cop" && (
        <div className="space-y-2">
          <p className="text-sm text-zinc-500">Silinen REQ&apos;ler burada durur; geri yüklenebilir. Kalıcı silme yalnızca yöneticide (Admin) ve REQ kodunu yazarak onayla.</p>
          <TrashSection kind="reqs" label="REQ'ler" embedded onRestored={() => setReload((n) => n + 1)} />
        </div>
      )}

      {data && data.reqs.length > 0 && view === "asama" && <Board data={data} />}

      {data && data.reqs.length > 0 && view === "liste" && (
        <>
          <div className="overflow-hidden rounded-xl border border-zinc-800">
            <table className="w-full text-sm">
              <thead className="bg-zinc-900 text-left text-xs uppercase tracking-wide text-zinc-500">
                <tr>
                  <th className="w-10 px-4 py-3">
                    <input
                      type="checkbox"
                      aria-label="Tümünü seç"
                      checked={allChecked}
                      onChange={() =>
                        setSelected((prev) => {
                          const next = new Set(prev);
                          data.reqs.forEach((r) => (allChecked ? next.delete(r.code) : next.add(r.code)));
                          return next;
                        })
                      }
                    />
                  </th>
                  <th className="px-4 py-3">REQ</th>
                  <th className="px-4 py-3">Müşteri</th>
                  <th className="px-4 py-3">Yönetici</th>
                  <th className="px-4 py-3">Aşama</th>
                  <th className="px-4 py-3">Kimde</th>
                  <th className="px-4 py-3 text-right">Kalem</th>
                  {data.can_view_amount && <th className="px-4 py-3 text-right">Teklif</th>}
                  <th className="px-4 py-3">Güncelleme</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-800">
                {data.reqs.map((r) => (
                  <tr key={r.code} onClick={() => router.push(reqHref(r.code))} className="cursor-pointer hover:bg-zinc-900/60">
                    {/* onay kutusu satır tıklamasını (ayrıntıyı açma) tetiklemesin — kullanıcı şikayeti: "kutucuğa tıklayınca beni talebe atıyor" */}
                    <td className="px-4 py-3" onClick={(e) => e.stopPropagation()}>
                      <input type="checkbox" aria-label={`Seç: ${r.code}`} checked={selected.has(r.code)} onChange={() => toggle(r.code)} />
                    </td>
                    <td className="px-4 py-3 font-medium text-white">
                      <Link href={reqHref(r.code)} className="hover:text-sky-300 hover:underline">
                        {r.code}
                      </Link>
                    </td>
                    <td className="px-4 py-3 text-zinc-300">{r.customer}</td>
                    <td className="px-4 py-3 text-zinc-300">{r.owner}</td>
                    <td className="px-4 py-3">
                      <span className={`rounded-full px-2 py-0.5 text-xs ${statusPill(r.status)}`}>{r.stage_label}</span>
                    </td>
                    <td className="px-4 py-3 text-zinc-400">{r.waiting || "-"}</td>
                    <td className="px-4 py-3 text-right text-zinc-300">{r.line_count}</td>
                    {data.can_view_amount && <td className="px-4 py-3 text-right text-zinc-300">{money(r.teklif, r.currency)}</td>}
                    <td className="px-4 py-3 text-zinc-500">{fmtDate(r.updated_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-3">
            <button className={btn} disabled={visibleSelected.length === 0 || exporting} onClick={exportSelected}>
              ⬇️ Seçilenleri indir{visibleSelected.length > 0 ? ` (${visibleSelected.length} REQ)` : ""}
            </button>
            <span className="text-xs text-zinc-600">Ayrıntı için bir satıra tıklayın; kutucuklarla birden fazla REQ seçip Excel&apos;e aktarabilirsiniz.</span>
          </div>
        </>
      )}
      {newOpen && <NewReqDialog onClose={() => setNewOpen(false)} />}
    </>
  );
}

export default function TaleplerPage() {
  return (
    <AppShell>
      <TaleplerContent />
    </AppShell>
  );
}
