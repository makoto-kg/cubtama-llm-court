"use client";

import type { ChoiceOption } from "@/api/client";
import { CHOICE_KIND_LABELS } from "@/lib/labels";

const KIND_STYLES: Record<string, string> = {
  contradiction: "border-red-400/60",
  probe: "border-sky-400/60",
  argument: "border-[var(--court-accent)]/60",
};

/** 人間の手番の選択肢。強さは選ぶまでわからない(API が伏せている)。 */
export function ChoicePanel({
  options,
  disabled,
  onChoose,
}: {
  options: ChoiceOption[];
  disabled: boolean;
  onChoose: (id: string) => void;
}) {
  const argumentsOnly = options.every((o) => o.kind === "argument");
  return (
    <div className="space-y-2">
      <p className="font-bold">
        あなたの番です。{argumentsOnly ? "弁論の方針を選んでください" : "つきつける内容を選んでください"}
      </p>
      <ul className="grid gap-2 md:grid-cols-2">
        {options.map((option) => (
          <li key={option.id}>
            <button
              disabled={disabled}
              onClick={() => onChoose(option.id)}
              className={`h-full w-full rounded border-l-4 bg-black/30 p-3 text-left hover:bg-white/10 disabled:opacity-50 ${
                KIND_STYLES[option.kind] ?? ""
              }`}
            >
              <span className="mr-2 rounded bg-white/10 px-1 text-xs">
                {CHOICE_KIND_LABELS[option.kind] ?? option.kind}
              </span>
              <span className="font-bold">{option.label}</span>
              <span className="mt-1 block text-sm opacity-80">{option.pitch}</span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
