export function PenaltyGauge({ remaining, max }: { remaining: number; max: number }) {
  return (
    <div className="flex items-center gap-2 text-sm" aria-label={`ペナルティゲージ ${remaining}/${max}`}>
      <span>ゲージ</span>
      <div className="flex gap-1">
        {Array.from({ length: max }, (_, i) => (
          <span
            key={i}
            className={`h-4 w-6 rounded-sm border border-[var(--court-accent)] ${
              i < remaining ? "bg-[var(--court-accent)]" : "bg-transparent"
            }`}
          />
        ))}
      </div>
      <span className="tabular-nums">
        {Math.max(remaining, 0)}/{max}
      </span>
    </div>
  );
}
