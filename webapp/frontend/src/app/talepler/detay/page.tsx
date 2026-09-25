"use client";

import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import AppShell from "@/components/AppShell";
import { Act, btn, ReqControls, StageActions } from "@/components/req/Actions";
import { DeleteReq, FixMenu, QtyFix } from "@/components/req/Fixes";
import NotesDrawer from "@/components/req/NotesDrawer";
import StagePanel from "@/components/req/StagePanels";
import { Flash, FlashBanner } from "@/components/req/ui";
import { api, ApiError, fmtDate, Hidden, ReqDetail, reqHref, uploadFile } from "@/lib/api";

const STATUS_PILL: Record<string, string> = {
  aktif: "bg-sky-500/20 text-sky-300",
  tamamlandi: "bg-emerald-500/20 text-emerald-300",
  rafa: "bg-red-500/20 text-red-300",
};

function Stepper({ req }: { req: ReqDetail }) {
  const style = {
    done: "border-emerald-500/40 bg-emerald-500/10 text-emerald-300",
    now: "border-sky-500 bg-sky-500/20 text-sky-200",
    todo: "border-zinc-800 text-zinc-500",
  };
  const mark = { done: "✔", now: "📍", todo: "○" };
  return (
    <div className="grid grid-cols-4 gap-2 lg:grid-cols-8">
      {req.stepper.map((c) => (
        <div key={c.key} className={`rounded-lg border px-2 py-2 text-center text-xs ${style[c.state]}`}>
          <div>{mark[c.state]}</div>
          <div className="mt-0.5">{c.label}</div>
        </div>
      ))}
    </div>
  );
}

function ReqDetailContent({ code }: { code: string }) {
  const router = useRouter();
  const [req, setReq] = useState<ReqDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [notesOpen, setNotesOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [flash, setFlash] = useState<Flash>(null);
  const reqRef = useRef<ReqDetail | null>(null); // son bilinen durum: aşama değişti mi diye karşılaştırmak için
  const busyRef = useRef(false); // çift tıklamada aynı eylemin iki kez gitmesini engeller (state güncellemesi gecikmeli)
  const base = `/api/reqs/${encodeURIComponent(code)}`;

  const apply = useCallback((d: ReqDetail) => {
    const prev = reqRef.current;
    reqRef.current = d;
    setReq(d);
    // İlk yükleme ya da aşama/durum değişince mevcut aşama sekmesine dön (Streamlit'teki _goto_tab); aksi halde seçimi koru
    if (!prev || prev.stage !== d.stage || prev.status !== d.status) setSelected(d.current_stage);
  }, []);

  useEffect(() => {
    api<ReqDetail>(base)
      .then(apply)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Bilinmeyen hata"));
  }, [base, apply]);

  // Başarı bildirimi birkaç saniye sonra kendiliğinden kaybolur; hata kalır (kullanıcı okuyup düzeltsin)
  useEffect(() => {
    if (flash?.tone !== "ok") return;
    const t = setTimeout(() => setFlash(null), 5000);
    return () => clearTimeout(t);
  }, [flash]);

  const run = useCallback(
    async (call: () => Promise<ReqDetail | Hidden>, okMsg?: string): Promise<boolean> => {
      if (busyRef.current) return false;
      busyRef.current = true;
      setBusy(true);
      setFlash(null);
      try {
        const d = await call();
        if ("hidden" in d) {
          // İşlem başarılı ama REQ artık görünmüyor (gümrükçü kendi aşamasını ilerletti ya da REQ silindi): listeye dön;
          // başarı mesajı liste sayfasında gösterilsin diye geçici olarak saklanır
          try {
            if (okMsg) sessionStorage.setItem("jarvis_flash", okMsg);
          } catch {}
          router.push("/talepler");
          return true;
        }
        apply(d);
        // REQ numarası düzeltildiyse eski adres artık çözülmez: yeni koda geç (sayfa yeni kodla yeniden bağlanır)
        if (d.code !== code) router.replace(reqHref(d.code));
        if (okMsg) setFlash({ tone: "ok", lines: [okMsg] });
        return true;
      } catch (err) {
        if (err instanceof ApiError && err.status === 401) {
          router.push("/login");
          return false;
        }
        setFlash({ tone: "err", lines: err instanceof ApiError ? err.errors : ["Bilinmeyen hata"] });
        // Çok adımlı işlemlerde (ör. Sipariş: kaydet + ilerlet) ilk adımlar kaydedilmiş olabilir; ekranı sunucuyla eşitle
        api<ReqDetail>(base).then(apply).catch(() => {});
        return false;
      } finally {
        busyRef.current = false;
        setBusy(false);
      }
    },
    [apply, base, code, router],
  );

  const act: Act = useCallback(
    (path, body, opts) =>
      run(
        () =>
          api<ReqDetail | Hidden>(`${base}${path}`, {
            method: opts?.method ?? "POST",
            body: body === undefined ? undefined : JSON.stringify(body),
          }),
        opts?.ok,
      ),
    [run, base],
  );

  const upload = useCallback(
    (file: File) => run(() => uploadFile<ReqDetail | Hidden>(`${base}/attachments`, file), "Dosya yüklendi."),
    [run, base],
  );

  if (error)
    return (
      <div className="space-y-3">
        <div className="text-red-400">⚠️ {error}</div>
        <Link href="/talepler" className="text-sm text-sky-400 hover:underline">
          ← Talepler
        </Link>
      </div>
    );
  if (!req || !selected) return <div className="text-zinc-400">Yükleniyor…</div>;

  const stageLabel = (key: string) => req.stepper.find((c) => c.key === key)?.label ?? key;
  const stageMark = (key: string) => (req.stepper.find((c) => c.key === key)?.state === "done" ? "✔" : "📍");
  const editable = req.can_edit_current && selected === req.stage;

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start gap-3">
        <div className="min-w-0 flex-1">
          <h1 className="flex items-center gap-3 text-xl font-semibold">
            {req.code}
            <span className={`rounded-full px-2.5 py-0.5 text-xs font-normal ${STATUS_PILL[req.status]}`}>
              {req.status === "aktif" ? req.stage_label : req.status_label}
            </span>
          </h1>
          <p className="mt-1 text-sm text-zinc-500">
            🏢 {req.customer} · 👤 {req.owner} · {req.currency} · {req.delivery_type} · Açılış {fmtDate(req.created_at)} · Son
            güncelleme {fmtDate(req.updated_at)}
          </p>
        </div>
        <FixMenu key={req.updated_at} req={req} act={act} busy={busy} />
        <button onClick={() => setNotesOpen(true)} className={btn}>
          📋 Notlar &amp; Görevler{req.open_tasks > 0 ? ` (${req.open_tasks})` : ""}
        </button>
        <Link href="/talepler" className={btn}>
          ← Talepler
        </Link>
      </div>

      <FlashBanner flash={flash} />

      {req.status === "rafa" && (
        <div className="flex flex-wrap items-center gap-3 rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-200">
          <span className="flex-1">Bu REQ rafa kaldırıldı. Sebep: {req.shelved_reason || "-"}</span>
          {req.can_reopen && (
            <button className={btn} disabled={busy} onClick={() => act("/reopen", undefined, { ok: "REQ yeniden açıldı." })}>
              Yeniden aç
            </button>
          )}
        </div>
      )}

      <Stepper req={req} />

      <div className="flex flex-wrap gap-1 rounded-lg border border-zinc-800 p-1">
        {req.visible_stages.map((key) => (
          <button
            key={key}
            onClick={() => setSelected(key)}
            className={`rounded-md px-3 py-1.5 text-sm transition ${
              selected === key ? "bg-sky-500 text-white" : "text-zinc-400 hover:bg-zinc-900"
            }`}
          >
            {stageMark(key)} {stageLabel(key)}
          </button>
        ))}
      </div>

      {req.status === "aktif" && selected === req.stage && !req.can_edit_current && (
        <p className="text-sm text-zinc-500">
          Bu aşama şu an <b>{req.waiting}</b> tarafında; düzenleme yetkiniz yok.
        </p>
      )}
      {req.status === "aktif" && selected !== req.stage && (
        <p className="text-sm text-zinc-500">Geçmiş aşama, salt okunur. Düzeltmek için aşağıdan &apos;Önceki aşamaya dön&apos;.</p>
      )}

      <div className="rounded-xl border border-zinc-800 p-5">
        <StagePanel stage={selected} req={req} editable={editable} act={act} busy={busy} />
      </div>

      <StageActions req={req} stage={selected} act={act} busy={busy} />

      <QtyFix key={req.updated_at} req={req} act={act} busy={busy} />

      <ReqControls req={req} act={act} busy={busy} />

      <div className="flex justify-end">
        <DeleteReq req={req} act={act} busy={busy} />
      </div>

      <details className="rounded-xl border border-zinc-800 px-5 py-3">
        <summary className="cursor-pointer text-sm text-zinc-300">🕘 Geçmiş ({req.history.length})</summary>
        <ul className="mt-3 space-y-1.5 text-sm text-zinc-400">
          {req.history.map((h, i) => (
            <li key={i}>
              <b className="text-zinc-300">{fmtDate(h.created_at)}</b> · {h.user ?? "-"} — {h.message}
            </li>
          ))}
        </ul>
      </details>

      <NotesDrawer
        req={req}
        open={notesOpen}
        onClose={() => setNotesOpen(false)}
        act={act}
        upload={upload}
        busy={busy}
        flash={flash}
      />
    </div>
  );
}

// Statik dışa aktarmada (cPanel'e düz dosya olarak yüklenen site) bilinmeyen REQ kodları için ayrı sayfa üretilemez;
// bu yüzden kod yol yerine sorgu parametresindedir: /talepler/detay?code=DMH_REQ_04. useSearchParams, Suspense sınırı ister.
function ReqDetailRoute() {
  const code = useSearchParams().get("code") ?? "";
  return (
    <AppShell>
      {code ? (
        // key: başka bir REQ'e geçilince durum (seçili aşama, açık panel) sıfırdan başlasın
        <ReqDetailContent key={code} code={code} />
      ) : (
        <div className="space-y-3">
          <div className="text-red-400">⚠️ REQ kodu belirtilmemiş.</div>
          <Link href="/talepler" className="text-sm text-sky-400 hover:underline">
            ← Talepler
          </Link>
        </div>
      )}
    </AppShell>
  );
}

export default function ReqDetailPage() {
  return (
    <Suspense fallback={<div className="p-8 text-zinc-400">Yükleniyor…</div>}>
      <ReqDetailRoute />
    </Suspense>
  );
}