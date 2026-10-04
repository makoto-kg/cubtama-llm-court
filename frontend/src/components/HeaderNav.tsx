"use client";

import Link from "next/link";

import { useAppMode } from "@/hooks/useAppMode";
import { useBgm, useSoundEnabled } from "@/hooks/useSound";

/**
 * 見出しの導線。設定(役割ごとのモデル)は API を使うので、オンラインのときだけ出す。音の切り替えも置く。
 * 見出しはどのページにも出ているので、ここで BGM を流す(ページを移っても曲が途切れない。ADR 0023)。
 */
export function HeaderNav() {
  const [mode] = useAppMode();
  const [sound, setSound] = useSoundEnabled();
  useBgm();
  return (
    <nav className="flex items-center gap-4 text-sm">
      <button
        type="button"
        onClick={() => setSound(!sound)}
        aria-pressed={sound}
        className="hover:underline"
        title="効果音の切り替え"
      >
        {sound ? "♪ 音あり" : "♪ 音なし"}
      </button>
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
