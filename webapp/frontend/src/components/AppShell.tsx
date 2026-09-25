"use client";

import { useEffect, useState } from "react";
import { useRouter, usePathname } from "next/navigation";
import Link from "next/link";
import Logo from "@/components/Logo";
import { api, ApiError, Me } from "@/lib/api";

const NAV = [
  { href: "/", label: "Panel", icon: "📊" },
  { href: "/talepler", label: "Talepler", icon: "📋" },
  { href: "/kisiler", label: "Kişiler", icon: "👥" },
  { href: "/urunler", label: "Ürünler", icon: "📦" },
];

export default function AppShell({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [me, setMe] = useState<Me | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<Me>("/api/me")
      .then(setMe)
      .catch((err) => {
        if (err instanceof ApiError && err.status === 401) router.push("/login");
        else setError(err instanceof Error ? err.message : "Bilinmeyen hata");
      });
  }, [router]);

  async function logout() {
    await api("/api/logout", { method: "POST" });
    router.push("/login");
  }

  if (error) return <div className="p-8 text-red-400">⚠️ {error}</div>;
  if (!me) return <div className="p-8 text-zinc-400">Yükleniyor…</div>;

  return (
    <div className="flex min-h-full bg-zinc-950 text-white">
      <aside className="w-56 shrink-0 border-r border-zinc-800 p-4">
        <Logo className="mb-3 w-full" />
        <div className="mb-6 px-2 text-sm font-semibold text-zinc-300">✨ Jarvis</div>
        <nav className="space-y-1">
          {NAV.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              className={`block rounded-lg px-3 py-2 text-sm transition ${
                (item.href === "/" ? pathname === "/" : pathname === item.href || pathname.startsWith(`${item.href}/`))
                  ? "bg-sky-500/20 text-sky-300"
                  : "text-zinc-300 hover:bg-zinc-900"
              }`}
            >
              {item.icon} {item.label}
            </Link>
          ))}
        </nav>
      </aside>
      {/* min-w-0: geniş tablo/grafik sütunu ekrandan taşırmasın, kendi içinde (overflow-x-auto) kaydırılsın */}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center justify-between border-b border-zinc-800 px-8 py-4">
          <div className="text-sm text-zinc-400">OZ Global Trade</div>
          <div className="flex items-center gap-3 text-sm text-zinc-300">
            <span>{me.name} · {me.role_label}</span>
            <button onClick={logout} className="rounded-lg border border-zinc-700 px-3 py-1.5 hover:bg-zinc-800">
              🚪 Çıkış yap
            </button>
          </div>
        </header>
        <main className="flex-1 p-8">{children}</main>
      </div>
    </div>
  );
}
