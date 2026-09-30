"use client";

import Link from "next/link";

import { useAppMode } from "@/hooks/useAppMode";

/** 見出しの導線。設定(役割ごとのモデル)は API を使うので、オンラインのときだけ出す。 */
export function HeaderNav() {
  const [mode] = useAppMode();
  return (
    <nav className="flex gap-4 text-sm">
      <Link href="/" className="hover:underline">
        タイトル
      </Link>
      {mode === "online" && (
        <Link href="/settings/" className="hover:underline">
          設定
        </Link>
      )}
    </nav>
  );
}
