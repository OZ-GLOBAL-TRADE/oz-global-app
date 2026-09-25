"use client";

import { useEffect, useState } from "react";
import { API_BASE, fmtDate, NoteTask, ReqDetail } from "@/lib/api";
import { Act, btn, btnPrimary } from "./Actions";
import { Flash, FlashBanner } from "./ui";

// Sağdan kayan Notlar & Görevler paneli (Streamlit'te st.dialog + CSS hack'iydi; burada gerçek bir çekmece).
// Not ekleme, görev atama/tamamlama/iptal ve dosya yükleme/silme burada; yetki servis katmanında.

/** 🗑️ → "Emin misiniz? Sil / Vazgeç" (iki adım; çekmecenin üstüne ikinci bir pencere açmadan). Yazan kişi ya da yönetici. */
function DeleteNote({ e, act, busy }: { e: NoteTask; act: Act; busy: boolean }) {
  const [sure, setSure] = useState(false);
  if (!e.can_delete) return null;
  if (!sure)
    return (
      <button title="Sil" aria-label={e.kind === "task" ? "Görevi sil" : "Notu sil"} disabled={busy} className={btn} onClick={() => setSure(true)}>
        🗑️
      </button>
    );
  return (
    <span className="flex shrink-0 items-center gap-1 text-xs">
      <span className="text-zinc-400">Silinsin mi?</span>
      <button
        className="rounded-lg bg-red-600 px-2 py-1 text-white hover:bg-red-500 disabled:opacity-50"
        disabled={busy}
        onClick={() => act(`/notes/${e.id}/delete`, undefined, { ok: e.kind === "task" ? "Görev silindi." : "Not silindi." })}
      >
        Sil
      </button>
      <button className={btn} disabled={busy} onClick={() => setSure(false)}>
        Vazgeç
      </button>
    </span>
  );
}

function TaskLine({ e, act, busy }: { e: NoteTask; act: Act; busy: boolean }) {
  const who = e.user ?? "-";
  if (e.kind === "note") {
    return (
      <li className="flex items-start gap-2 text-sm text-zinc-300">
        <div className="min-w-0 flex-1">
          💬 <b className="text-zinc-400">{fmtDate(e.created_at)}</b> · {who} — {e.message}
        </div>
        <DeleteNote e={e} act={act} busy={busy} />
      </li>
    );
  }
  const icon = e.state === "done" ? "✅" : e.state === "cancelled" ? "🚫" : "📌";
  const tail =
    e.state === "done" && e.done_at
      ? ` (tamamlandı ${fmtDate(e.done_at)})`
      : e.state === "cancelled" && e.cancelled_at
        ? ` (iptal edildi ${fmtDate(e.cancelled_at)})`
        : "";
  return (
    <li className={`flex items-start gap-2 text-sm ${e.state === "open" ? "text-zinc-200" : "text-zinc-500"}`}>
      <div className="min-w-0 flex-1">
        {icon} <b className="text-zinc-400">{fmtDate(e.created_at)}</b> · {who} → <b>{e.assignee ?? "-"}</b>: {e.message}
        <i>{tail}</i>
      </div>
      {e.state === "open" && e.can_act && (
        <div className="flex shrink-0 gap-1">
          <button
            title="Tamamlandı"
            aria-label="Görevi tamamla"
            disabled={busy}
            className={btn}
            onClick={() => act(`/tasks/${e.id}/complete`, undefined, { ok: "Görev tamamlandı." })}
          >
            ✅
          </button>
          <button
            title="İptal et"
            aria-label="Görevi iptal et"
            disabled={busy}
            className={btn}
            onClick={() => act(`/tasks/${e.id}/cancel`, undefined, { ok: "Görev iptal edildi." })}
          >
            ✖️
          </button>
        </div>
      )}
      <DeleteNote e={e} act={act} busy={busy} />
    </li>
  );
}

const NO_ASSIGNEE = "";

export default function NotesDrawer({
  req,
  open,
  onClose,
  act,
  upload,
  busy,
  flash,
}: {
  req: ReqDetail;
  open: boolean;
  onClose: () => void;
  act: Act;
  upload: (file: File) => Promise<boolean>;
  busy: boolean;
  flash: Flash;
}) {
  const [text, setText] = useState("");
  const [assignee, setAssignee] = useState(NO_ASSIGNEE);
  const [fileKey, setFileKey] = useState(0); // yüklemeden sonra dosya girişini sıfırlamak için
  const [file, setFile] = useState<File | null>(null);

  useEffect(() => {
    if (!open) return;
    const onKey = (ev: KeyboardEvent) => ev.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  async function saveNote() {
    const isTask = assignee !== NO_ASSIGNEE;
    const ok = await act("/notes", { text, assignee_id: isTask ? Number(assignee) : null }, { ok: isTask ? "Görev atandı." : "Not eklendi." });
    if (ok) setText("");
  }

  async function doUpload() {
    if (!file) return;
    if (await upload(file)) {
      setFile(null);
      setFileKey((k) => k + 1);
    }
  }

  return (
    <>
      <div
        onClick={onClose}
        className={`fixed inset-0 z-40 bg-black/50 transition-opacity ${open ? "opacity-100" : "pointer-events-none opacity-0"}`}
      />
      <aside
        aria-hidden={!open}
        className={`fixed right-0 top-0 z-50 flex h-full w-full max-w-md flex-col border-l border-zinc-800 bg-zinc-950 shadow-2xl transition-transform duration-200 ${
          open ? "translate-x-0" : "translate-x-full"
        }`}
      >
        <div className="flex items-center justify-between border-b border-zinc-800 px-5 py-4">
          <div>
            <div className="font-semibold">📋 Notlar &amp; Görevler</div>
            <div className="text-xs text-zinc-500">{req.code}</div>
          </div>
          <button onClick={onClose} aria-label="Kapat" className="rounded-lg px-2 py-1 text-zinc-400 hover:bg-zinc-800">
            ✕
          </button>
        </div>

        <div className="flex-1 space-y-6 overflow-y-auto px-5 py-4">
          <FlashBanner flash={flash} />

          <section className="space-y-2">
            <label className="block text-xs text-zinc-500">Not ekle ya da görev ata</label>
            <input
              value={text}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && !busy && saveNote()}
              placeholder="Örn: Çin ofisi fiyatı WeChat'ten iletti"
              className="w-full rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-1.5 text-sm outline-none focus:border-sky-500"
            />
            <div className="flex gap-2">
              <select
                value={assignee}
                onChange={(e) => setAssignee(e.target.value)}
                aria-label="Kime (opsiyonel)"
                className="min-w-0 flex-1 rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-1.5 text-sm outline-none focus:border-sky-500"
              >
                <option value={NO_ASSIGNEE}>Not (kimseye atama)</option>
                {req.assignable_users.map((u) => (
                  <option key={u.id} value={u.id}>
                    {u.name}
                  </option>
                ))}
              </select>
              <button className={btnPrimary} disabled={busy || !text.trim()} onClick={saveNote}>
                Kaydet
              </button>
            </div>
            <p className="text-xs text-zinc-500">Yalnızca bu REQ&apos;i zaten görebilen kullanıcılara görev atanabilir.</p>
          </section>

          <section>
            {req.notes_tasks.length === 0 ? (
              <p className="text-sm text-zinc-500">Henüz not ya da görev yok.</p>
            ) : (
              <ul className="space-y-3">
                {req.notes_tasks.map((e) => (
                  <TaskLine key={e.id} e={e} act={act} busy={busy} />
                ))}
              </ul>
            )}
          </section>

          <section className="space-y-3">
            <h3 className="text-sm font-semibold">📎 Dosyalar</h3>
            {req.attachments.length === 0 ? (
              <p className="text-sm text-zinc-500">Henüz dosya yüklenmedi.</p>
            ) : (
              <ul className="space-y-2">
                {req.attachments.map((a) => (
                  <li key={a.id} className="flex items-center gap-2 text-sm">
                    <span className="min-w-0 flex-1 truncate text-zinc-300" title={a.filename}>
                      {a.filename} <span className="text-zinc-500">({Math.max(1, Math.round(a.size / 1024))} KB)</span>
                    </span>
                    <a href={`${API_BASE}/api/attachments/${a.id}`} className={`${btn} shrink-0`}>
                      İndir
                    </a>
                    <button
                      className={`${btn} shrink-0`}
                      disabled={busy}
                      onClick={() => act(`/attachments/${a.id}`, undefined, { method: "DELETE", ok: "Dosya silindi." })}
                    >
                      Sil
                    </button>
                  </li>
                ))}
              </ul>
            )}
            <div className="flex items-center gap-2">
              <input
                key={fileKey}
                type="file"
                aria-label="Dosya seç"
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                className="min-w-0 flex-1 text-xs text-zinc-400 file:mr-3 file:rounded-lg file:border file:border-zinc-700 file:bg-transparent file:px-3 file:py-1.5 file:text-sm file:text-zinc-200"
              />
              <button className={btn} disabled={busy || !file} onClick={doUpload}>
                Yükle
              </button>
            </div>
            <p className="text-xs text-zinc-500">En fazla 10 MB.</p>
          </section>
        </div>
      </aside>
    </>
  );
}
