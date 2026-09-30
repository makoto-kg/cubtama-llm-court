import { ByMode, ModeSwitch } from "@/components/ModeSwitch";
import { OfflineCaseList } from "@/components/OfflineCaseList";
import { TitleScreen } from "@/components/TitleScreen";

// ビルドは 1 本。オフライン / オンラインは画面で選ぶ(既定はオフライン。ADR 0018)
export default function Home() {
  return (
    <div className="space-y-6">
      <section className="py-6 text-center">
        <h1 className="text-4xl font-bold tracking-[0.3em] text-[var(--court-accent)]">法廷論戦</h1>
        <p className="mt-2 text-sm opacity-80">LLM が証拠品をもとに論戦する法廷バトル</p>
      </section>
      <ModeSwitch />
      <ByMode offline={<OfflineCaseList />} online={<TitleScreen />} />
    </div>
  );
}
