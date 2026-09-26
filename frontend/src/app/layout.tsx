import type { Metadata } from "next";
import Link from "next/link";
import type { ReactNode } from "react";

import "./globals.css";

export const metadata: Metadata = {
  title: "llm-court",
  description: "LLM が論戦する法廷バトル ADV",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="ja">
      <body className="min-h-screen">
        <header className="flex items-center justify-between border-b border-[var(--court-wood-light)] bg-[var(--court-wood)] px-4 py-2">
          <Link href="/" className="text-lg font-bold tracking-widest text-[var(--court-accent)]">
            llm-court
          </Link>
          <nav className="flex gap-4 text-sm">
            <Link href="/" className="hover:underline">
              タイトル
            </Link>
            <Link href="/settings/" className="hover:underline">
              設定
            </Link>
          </nav>
        </header>
        <main className="mx-auto max-w-6xl p-4">{children}</main>
      </body>
    </html>
  );
}
