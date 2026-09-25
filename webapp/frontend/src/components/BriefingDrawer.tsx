"use client";

import { Fragment, useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { btn } from "./req/Actions";

// Sağdan kayan "📰 Günlük Brifing" paneli. Metin sunucudan gelir (gerçek veriden maddeler + varsa Claude yorumu, Markdown).
// Üretim yalnızca panel açıldığında/"Yeniden üret"e basınca yapılır (her üretim bir Claude çağrısı olabilir → maliyet).

type Briefing = { text: string; generated_at: string };

/** Brifing metnindeki küçük Markdown alt kümesi: **kalın**, _italik_, "- " madde işaretleri, boş satır = paragraf. */
function Inline({ text }: { text: string }) {
  // _italik_ yalnızca kelime sınırında başlayıp biter: "DMS_REQ_03" ya da "CLAUDE_API_KEY" içindeki alt çizgiler italik sayılmaz
  const parts = text.split(/(\*\*[^*]+\*\*|(?<!\w)_.+?_(?!\w))/g).filter(Boolean);
  return (
    <>
      {parts.map((p, i) =>
        p.startsWith("**") ? (
          <b key={i} className="text-white">
            {p.slice(2, -2)}
          </b>
        ) : p.startsWith("_") && p.endsWith("_") && p.length > 2 ? (
          <i key={i} className="text-zinc-500">
            {p.slice(1, -1)}
          </i>
        ) : (
          <Fragment key={i}>{p}</Fragment>
        ),
      )}
    </>
  );
}

function Markdownish({ text }: { text: string }) {
  const blocks: { bullets: string[] | null; text: string }[] = [];
  for (const line of text.split("\n")) {
    const t = line.trim();
    if (!t) continue;
    const m = t.match(/^[-*•]\s+(.*)$/);
    const last = blocks[blocks.length - 1];
    if (m) {
      if (last?.bullets) last.bullets.push(m[1]);
      else blocks.push({ bullets: [m[1]], text: "" });
    } else blocks.push({ bullets: null, text: t.replace(/^#+\s*/, "") });
  }
  return (
    <div className="space-y-3 text-sm text-zinc-300">
      {blocks.map((b, i) =>
        b.bullets ? (
          <ul key={i} className="list-disc space-y-1.5 pl-5">
            {b.bullets.map((x, j) => (
              <li key={j}>
                <Inline text={x} />
              </li>
            ))}
          </ul>
        ) : (
          <p key={i}>
            <Inline text={b.text} />
          </p>
        ),
      )}
    </div>
  );
}

export default function BriefingDrawer({ onClose }: { onClose: () => void }) {
  const [data, setData] = useState<Briefing | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const generate = () => {
    setLoading(true);
    setError(null);
    api<Briefing>("/api/panel/briefing", { method: "POST" })
      .then(setData)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Bilinmeyen hata"))
      .finally(() => setLoading(false));
  };

  // Açılışta bir kez üret (bileşen yalnızca açıkken bağlanır)
  useEffect(() => {
    let cancelled = false;
    api<Briefing>("/api/panel/briefing", { method: "POST" })
      .then((d) => !cancelled && setData(d))
      .catch((err) => !cancelled && setError(err instanceof ApiError ? err.message : "Bilinmeyen hata"))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const onKey = (ev: KeyboardEvent) => ev.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <>
      <div onClick={onClose} className="fixed inset-0 z-40 bg-black/50" />
      <aside role="dialog" aria-label="Günlük Brifing" className="fixed right-0 top-0 z-50 flex h-full w-full max-w-md flex-col border-l border-zinc-800 bg-zinc-950 shadow-2xl">
        <div className="flex items-center justify-between border-b border-zinc-800 px-5 py-4">
          <div>
            <div className="font-semibold">📰 Günlük Brifing</div>
            {data && <div className="text-xs text-zinc-500">{data.generated_at} itibarıyla</div>}
          </div>
          <button onClick={onClose} aria-label="Kapat" className="rounded-lg px-2 py-1 text-zinc-400 hover:bg-zinc-800">
            ✕
          </button>
        </div>
        <div className="flex-1 space-y-4 overflow-y-auto px-5 py-4">
          <button className={btn} disabled={loading} onClick={generate}>
            🔄 Yeniden üret
          </button>
          {loading && <p className="text-sm text-zinc-400">Jarvis brifingi hazırlıyor…</p>}
          {error && <p className="text-sm text-red-400">⚠️ {error}</p>}
          {data && !loading && <Markdownish text={data.text} />}
        </div>
      </aside>
    </>
  );
}
