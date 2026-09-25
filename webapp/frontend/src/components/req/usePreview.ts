"use client";

import { useEffect, useState } from "react";
import { api, Preview } from "@/lib/api";

/**
 * Kaydedilmemiş form değerleriyle canlı hesap: değerler değişince (250 ms bekleyip) POST /preview çağırır.
 * Hesap sunucuda (pipeline.calculate_quote) yapılır — frontend'de iş kuralı tekrar yazılmaz. Hiçbir şey kaydetmez.
 * Eski yanıtlar (yarış) yok sayılır. İlk yanıt gelene kadar null döner.
 */
export function usePreview(code: string, payload: object): Preview | null {
  const [data, setData] = useState<Preview | null>(null);
  const body = JSON.stringify(payload); // NaN → null; bağımlılık olarak kararlı bir anahtar

  useEffect(() => {
    let cancelled = false;
    const t = setTimeout(() => {
      api<Preview>(`/api/reqs/${encodeURIComponent(code)}/preview`, { method: "POST", body })
        .then((d) => !cancelled && setData(d))
        .catch(() => {}); // önizleme yardımcıdır; hata ana akışı bozmaz (kaydederken sunucu zaten doğrular)
    }, 250);
    return () => {
      cancelled = true;
      clearTimeout(t);
    };
  }, [code, body]);

  return data;
}
