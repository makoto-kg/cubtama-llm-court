import { ByMode, ModeSwitch } from "@/components/ModeSwitch";
import { OfflineCaseList } from "@/components/OfflineCaseList";
import { TitleHero } from "@/components/TitleHero";
import { TitleScreen } from "@/components/TitleScreen";

// ビルドは 1 本。オフライン / オンラインは画面で選ぶ(既定はオフライン。ADR 0018)
export default function Home() {
  return (
    <div className="space-y-6">
      <TitleHero />
      <ModeSwitch />
      <ByMode offline={<OfflineCaseList />} online={<TitleScreen />} />
    </div>
  );
}
