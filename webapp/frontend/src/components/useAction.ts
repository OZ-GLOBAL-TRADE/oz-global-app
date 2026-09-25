"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { ApiError } from "@/lib/api";
import type { Flash } from "./req/ui";

/**
 * Sayfa düzeyi eylem yardımcısı (Kişiler/Ürünler): tek seferde bir eylem (çift tıklamayı engeller), hata/başarı bandı,
 * 401'de girişe yönlendirme. `run(çağrı, başarıMesajı?)` çağrının sonucunu döner; hatada null (mesaj bantta görünür).
 */
export function useAction() {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [flash, setFlash] = useState<Flash>(null);
  const busyRef = useRef(false);

  // Başarı bandı kendiliğinden kaybolur; hata kalır (okuyup düzeltsin)
  useEffect(() => {
    if (flash?.tone !== "ok") return;
    const t = setTimeout(() => setFlash(null), 5000);
    return () => clearTimeout(t);
  }, [flash]);

  const run = useCallback(
    async <T,>(call: () => Promise<T>, okMsg?: string | ((r: T) => string)): Promise<T | null> => {
      if (busyRef.current) return null;
      busyRef.current = true;
      setBusy(true);
      setFlash(null);
      try {
        const result = await call();
        if (okMsg) setFlash({ tone: "ok", lines: [typeof okMsg === "function" ? okMsg(result) : okMsg] });
        return result;
      } catch (err) {
        if (err instanceof ApiError && err.status === 401) router.push("/login");
        else setFlash({ tone: "err", lines: err instanceof ApiError ? err.errors : ["Bilinmeyen hata"] });
        return null;
      } finally {
        busyRef.current = false;
        setBusy(false);
      }
    },
    [router],
  );

  return { busy, flash, setFlash, run };
}
