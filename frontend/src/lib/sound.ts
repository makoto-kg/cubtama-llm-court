/**
 * 効果音(ADR 0023)。音のファイルは使わず、Web Audio API でその場で合成する(すべてオリジナルの音)。
 * - 文字送りの音(`playBlip`): 台詞を打ち出す間、数文字ごとに短く鳴らす「パラパラ」
 * - つきつける音(`playSlam`): 証拠品をつきつけた瞬間の「バシッ」
 *
 * 音を出すかどうかは閲覧者が選び、`localStorage` に覚えておく(既定は出す)。
 */

/** 音の有無を覚えておく `localStorage` のキー(閲覧者ごとの設定)。 */
export const SOUND_STORAGE_KEY = "llm-court:sound";

/** 文字送りの音の最短の間隔(ms)。これより速く文字が出ても、この間隔でしか鳴らさない。 */
export const BLIP_INTERVAL_MS = 55;

/** 保存値を音の有無として読む。未設定・不正な値は「出す」。 */
export function parseSoundEnabled(value: string | null | undefined): boolean {
  return value !== "off";
}

/** 音を鳴らさない文字(空白・句読点・記号)。間や区切りでは音を止め、しゃべっている感じを出す。 */
const SILENT = /[\s、。,.!?！？…・「」『』()()〜ー-]/u;

/**
 * 文字送りの音を鳴らすか。新しく出た文字(`added`)に声を出す文字があり、前に鳴らしてから
 * `BLIP_INTERVAL_MS` 以上たっていれば鳴らす。
 */
export function blipDue(added: string, sinceLastMs: number): boolean {
  if (sinceLastMs < BLIP_INTERVAL_MS) return false;
  return [...added].some((c) => !SILENT.test(c));
}

let enabled: boolean | null = null;
let context: AudioContext | null = null;

export function soundEnabled(): boolean {
  if (enabled === null) {
    try {
      enabled = parseSoundEnabled(window.localStorage.getItem(SOUND_STORAGE_KEY));
    } catch {
      enabled = true;
    }
  }
  return enabled;
}

export function setSoundEnabled(next: boolean): void {
  enabled = next;
  try {
    window.localStorage.setItem(SOUND_STORAGE_KEY, next ? "on" : "off");
  } catch {
    // 保存できなくても、開いている間は切り替える
  }
}

/** 鳴らせるときだけ AudioContext を返す(ブラウザが止めていれば再開を頼む)。 */
function audio(): AudioContext | null {
  if (typeof window === "undefined" || !soundEnabled()) return null;
  try {
    context ??= new AudioContext();
  } catch {
    return null;
  }
  if (context.state === "suspended") void context.resume();
  return context;
}

/** 文字送りの音。高さを少しずつ揺らして、同じ音の繰り返しに聞こえないようにする。 */
export function playBlip(): void {
  const ctx = audio();
  if (!ctx) return;
  const t = ctx.currentTime;
  const osc = ctx.createOscillator();
  const gain = ctx.createGain();
  osc.type = "square";
  osc.frequency.value = 760 + Math.random() * 120;
  gain.gain.setValueAtTime(0.0001, t);
  gain.gain.exponentialRampToValueAtTime(0.045, t + 0.004);
  gain.gain.exponentialRampToValueAtTime(0.0001, t + 0.035);
  osc.connect(gain).connect(ctx.destination);
  osc.start(t);
  osc.stop(t + 0.04);
}

/** つきつける音。はじけるノイズと、低く沈む打撃音を重ねる。 */
export function playSlam(): void {
  const ctx = audio();
  if (!ctx) return;
  const t = ctx.currentTime;

  // はじける音: 短いノイズを高めの帯域に絞り、すぐに減衰させる
  const length = Math.floor(ctx.sampleRate * 0.18);
  const buffer = ctx.createBuffer(1, length, ctx.sampleRate);
  const data = buffer.getChannelData(0);
  for (let i = 0; i < length; i++) data[i] = (Math.random() * 2 - 1) * (1 - i / length) ** 3;
  const noise = ctx.createBufferSource();
  noise.buffer = buffer;
  const band = ctx.createBiquadFilter();
  band.type = "bandpass";
  band.frequency.value = 1800;
  band.Q.value = 0.8;
  const noiseGain = ctx.createGain();
  noiseGain.gain.value = 0.7;
  noise.connect(band).connect(noiseGain).connect(ctx.destination);
  noise.start(t);

  // 打撃音: 低い音を急に下げる
  const thump = ctx.createOscillator();
  const thumpGain = ctx.createGain();
  thump.type = "sine";
  thump.frequency.setValueAtTime(180, t);
  thump.frequency.exponentialRampToValueAtTime(45, t + 0.16);
  thumpGain.gain.setValueAtTime(0.0001, t);
  thumpGain.gain.exponentialRampToValueAtTime(0.6, t + 0.005);
  thumpGain.gain.exponentialRampToValueAtTime(0.0001, t + 0.22);
  thump.connect(thumpGain).connect(ctx.destination);
  thump.start(t);
  thump.stop(t + 0.25);
}
