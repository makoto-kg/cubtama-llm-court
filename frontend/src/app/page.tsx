import Link from "next/link";

import { OfflineCaseList } from "@/components/OfflineCaseList";
import { TitleScreen } from "@/components/TitleScreen";
import { OFFLINE_ONLY } from "@/lib/offline/config";

export default function Home() {
  return (
    <div className="space-y-6">
      <section className="py-6 text-center">
        <h1 className="text-4xl font-bold tracking-[0.3em] text-[var(--court-accent)]">法廷論戦</h1>
        <p className="mt-2 text-sm opacity-80">LLM が証拠品をもとに論戦する法廷バトル</p>
      </section>
      {OFFLINE_ONLY ? (
        <OfflineCaseList />
      ) : (
        <>
          <TitleScreen />
          <p className="text-center text-sm">
            <Link href="/offline/" className="underline">
              オフラインで遊ぶ(バックエンド・LLM サーバー不要の裁判)
            </Link>
          </p>
        </>
      )}
    </div>
  );
}
