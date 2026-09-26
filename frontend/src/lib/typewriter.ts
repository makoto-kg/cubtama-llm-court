/**
 * タイプライター表示で次に見せる文字数。
 *
 * 基本は `charsPerSecond` で進め、表示が目標より大きく遅れているときは追いつくよう加速する
 * (ストリームが速く届いても待たされない)。
 */
export function nextVisibleLength(
  visible: number,
  target: number,
  elapsedMs: number,
  charsPerSecond = 40,
): number {
  if (visible >= target) return target;
  const behind = target - visible;
  const speed = behind > 200 ? charsPerSecond * 6 : behind > 80 ? charsPerSecond * 2 : charsPerSecond;
  const step = Math.max(1, Math.floor((speed * elapsedMs) / 1000));
  return Math.min(target, visible + step);
}
