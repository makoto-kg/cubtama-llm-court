import type { NextConfig } from "next";

// SPA として静的にビルドする(`pnpm build` で out/ に出力)。サーバー側で動く機能は使わない。
// 詳細は docs/adr/0011-frontend-mvp.md。
const nextConfig: NextConfig = {
  output: "export",
  // /court → /court/index.html として出力し、静的サーバーでそのまま配信できるようにする
  trailingSlash: true,
  images: { unoptimized: true },
  // サブパスに配信するとき(GitHub Pages の `/<repo>/` など)の接頭辞。既定はルート(ADR 0021)
  basePath: process.env.NEXT_PUBLIC_BASE_PATH || undefined,
};

export default nextConfig;
