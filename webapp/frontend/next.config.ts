import type { NextConfig } from "next";

// Canlıda arayüz düz statik dosyalardır (`npm run build` → `out/`), cPanel'in belge kök dizinine yüklenir; sunucuda
// Node çalışmaz. Bu yüzden: "export" (HTML/JS/CSS üretir) ve trailingSlash (Apache'de /talepler → talepler/index.html).
// Statik sitede dinamik yol (/talepler/[kod]) üretilemediği için REQ kodu sorgu parametresindedir (bkz. reqHref).
// API adresi derleme anında NEXT_PUBLIC_API_URL ile gömülür (bkz. ../build_web.cmd).
const nextConfig: NextConfig = {
  output: "export",
  trailingSlash: true,
  images: { unoptimized: true },
};

export default nextConfig;
