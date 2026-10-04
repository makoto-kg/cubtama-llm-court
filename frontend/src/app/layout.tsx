import type { Metadata } from "next";
import Link from "next/link";
import type { ReactNode } from "react";

import { GAME_SUBTITLE, GAME_TITLE } from "@/assets/manifest";
import { HeaderNav } from "@/components/HeaderNav";

import "./globals.css";

const TITLE = `${GAME_TITLE} — ${GAME_SUBTITLE}`;
const DESCRIPTION = "LLM が論戦する法廷バトル ADV";

// OGP の画像(`opengraph-image.jpg`。`scripts/make_og_image.py` で作る)は絶対 URL が要るので、
// 配信先のオリジンを `NEXT_PUBLIC_SITE_URL` で渡す。basePath は含めない(画像の URL には Next.js が付ける)。
// 未設定ならローカルの開発サーバー
export const metadata: Metadata = {
  metadataBase: new URL(process.env.NEXT_PUBLIC_SITE_URL || "http://localhost:3000"),
  title: TITLE,
  description: DESCRIPTION,
  openGraph: {
    type: "website",
    locale: "ja_JP",
    siteName: GAME_TITLE,
    title: TITLE,
    description: DESCRIPTION,
  },
  twitter: {
    card: "summary_large_image",
    title: TITLE,
    description: DESCRIPTION,
  },
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="ja">
      <body className="min-h-screen">
        <header className="flex items-center justify-between border-b border-[var(--court-wood-light)] bg-[var(--court-wood)] px-4 py-2">
          <Link href="/" className="text-lg font-bold tracking-widest text-[var(--court-accent)]">
            llm-court
          </Link>
          <HeaderNav />
        </header>
        <main className="mx-auto max-w-6xl p-4">{children}</main>
      </body>
    </html>
  );
}
