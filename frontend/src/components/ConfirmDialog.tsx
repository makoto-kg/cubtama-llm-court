"use client";

import { useEffect, useRef } from "react";

/**
 * 確認のダイアログ(ブラウザの confirm の代わりに、ゲームの画面に合わせて重ねて出す)。
 * Esc・背景のタップで取り消し。開いたら「取り消し」にフォーカスする(誤って確定しないように)。
 */
export function ConfirmDialog({
  open,
  title,
  message,
  confirmLabel,
  cancelLabel = "やめる",
  onConfirm,
  onCancel,
}: {
  open: boolean;
  title: string;
  message: string;
  confirmLabel: string;
  cancelLabel?: string;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const cancelRef = useRef<HTMLButtonElement>(null);
  // 最新の取り消し処理(親が描画のたびに関数を作り直しても、開いたときだけフォーカスする)
  const onCancelRef = useRef(onCancel);
  useEffect(() => {
    onCancelRef.current = onCancel;
  }, [onCancel]);

  useEffect(() => {
    if (!open) return;
    cancelRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onCancelRef.current();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  if (!open) return null;
  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center bg-black/60 p-0 sm:items-center sm:p-4"
      onClick={onCancel}
      role="alertdialog"
      aria-modal="true"
      aria-labelledby="confirm-title"
      aria-describedby="confirm-message"
    >
      <div
        className="evidence-sheet w-full max-w-md space-y-4 rounded-t-2xl border-t-4 border-[var(--court-accent)] bg-[#241a12] p-5 shadow-2xl sm:rounded-2xl sm:border-4"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 id="confirm-title" className="text-center text-lg font-black tracking-widest text-[var(--court-accent)]">
          {title}
        </h2>
        <p id="confirm-message" className="text-center text-sm leading-relaxed">
          {message}
        </p>
        <div className="grid grid-cols-2 gap-2">
          <button ref={cancelRef} onClick={onCancel} className="rounded-lg border border-[var(--court-accent)] py-3 font-bold">
            {cancelLabel}
          </button>
          <button onClick={onConfirm} className="rounded-lg bg-[var(--court-accent)] py-3 font-bold text-black">
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
