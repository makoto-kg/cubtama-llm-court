export function PenaltyGauge({ remaining, max }: { remaining: number; max: number }) {
  return (
    <div className="flex items-center gap-1.5 text-xs lg:gap-2 lg:text-sm" aria-label={`ペナルティゲージ ${remaining}/${max}`}>
      <span className="max-sm:sr-only">ゲージ</span>
      <div className="flex gap-1">
        {Array.from({ length: max }, (_, i) => (
          <span
            key={i}
            className={`h-3 w-4 rounded-sm lg:h-4 lg:w-6 border border-[var(--court-accent)] ${
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
