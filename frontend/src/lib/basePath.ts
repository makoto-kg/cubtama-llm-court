/**
 * サブパスに配信するときの接頭辞(例: GitHub Pages の `/<repo>`)。既定は空(ルートに配信)。
 * `next.config.ts` の `basePath` と同じ値。`next/link` には自動で付くが、
 * `next/image` の `src` と `fetch` の URL には付かないので、この関数で付ける(ADR 0021)。
 */
export const BASE_PATH = process.env.NEXT_PUBLIC_BASE_PATH ?? "";

/** ルートからの絶対パス(`/` 始まり)に接頭辞を付ける。 */
export function withBasePath(path: string, base: string = BASE_PATH): string {
  return `${base}${path}`;
}
