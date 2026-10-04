import Image from "next/image";

import { GAME_SUBTITLE, GAME_TITLE, TITLE_LOGO, TRIAL_SPRITES } from "@/assets/manifest";

/**
 * タイトル画面の看板: ロゴ・サブタイトルと、タマ検察官がカブ被告に証拠品をつきつける場面。
 * スマホでは縦に積み、広い画面ではロゴと場面を横に並べる。表示だけ(素材・意匠はオリジナル)。
 */
export function TitleHero() {
  const tama = TRIAL_SPRITES.prosecutor.igiari;
  const cub = TRIAL_SPRITES.defendant.nervous;
  return (
    <section className="title-hero relative overflow-hidden rounded-xl">
      <div className="title-rays pointer-events-none absolute left-1/2 top-[22%] aspect-square w-[160%] -translate-x-1/2 -translate-y-1/2 lg:left-[24%] lg:top-1/2 lg:w-[90%]" />
      <div className="relative lg:grid lg:grid-cols-[1fr_1.15fr] lg:items-end lg:gap-2">
        <div className="relative px-3 pt-5 sm:pt-8 lg:self-center lg:pb-8 lg:pt-6">
          <h1 className="mx-auto w-full max-w-2xl">
            <Image
              src={TITLE_LOGO.src}
              alt={GAME_TITLE}
              width={TITLE_LOGO.width}
              height={TITLE_LOGO.height}
              className="title-logo h-auto w-full"
              priority
            />
          </h1>
          <p className="title-subtitle mx-auto -mt-1 w-fit px-6 py-1 text-base font-black tracking-[0.25em] sm:-mt-3 sm:px-10 sm:text-2xl">
            {GAME_SUBTITLE}
          </p>
        </div>
        <div className="title-scene relative mx-auto mt-3 aspect-[16/10] w-full max-w-3xl sm:aspect-[2/1] lg:mt-6 lg:aspect-[16/10]">
          <Image
            src={cub.src}
            alt="動揺するカブ被告"
            width={cub.width}
            height={cub.height}
            className="title-cub absolute bottom-0 right-[3%] h-[88%] w-auto drop-shadow-[0_6px_14px_rgba(0,0,0,0.6)]"
          />
          <Image
            src={tama.src}
            alt="証拠品をつきつけるタマ検察官"
            width={tama.width}
            height={tama.height}
            className="title-tama absolute bottom-0 left-0 h-full w-auto max-w-[66%] object-contain object-left-bottom drop-shadow-[0_6px_14px_rgba(0,0,0,0.6)]"
          />
          <div className="title-floor pointer-events-none absolute inset-x-0 bottom-0 h-[22%]" />
        </div>
      </div>
    </section>
  );
}
