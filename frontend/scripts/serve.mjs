// 静的ビルド(out/)を配信する小さなサーバー(依存なし)。`npm run serve` / `pnpm serve` で使う。
//
// 環境変数: PORT(既定 8080)、HOST(既定 127.0.0.1)、SERVE_DIR(既定 out)
import { createReadStream } from "node:fs";
import { stat } from "node:fs/promises";
import { createServer } from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
  process.env.SERVE_DIR ?? "out",
);
const port = Number(process.env.PORT ?? 8080);
const host = process.env.HOST ?? "127.0.0.1";

const TYPES = {
  ".html": "text/html; charset=utf-8",
  ".txt": "text/plain; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".mjs": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".webp": "image/webp",
  ".ico": "image/x-icon",
  ".woff2": "font/woff2",
  ".map": "application/json; charset=utf-8",
};

async function isFile(file) {
  try {
    return (await stat(file)).isFile();
  } catch {
    return false;
  }
}

/** URL のパスを out/ 内のファイルに対応づける(out/ の外は指させない)。 */
async function resolve(urlPath) {
  let decoded;
  try {
    decoded = decodeURIComponent(urlPath);
  } catch {
    return null;
  }
  const target = path.resolve(root, "." + path.posix.normalize(decoded));
  if (target !== root && !target.startsWith(root + path.sep)) return null;
  if (decoded.endsWith("/")) {
    const index = path.join(target, "index.html");
    return (await isFile(index)) ? { file: index } : null;
  }
  if (await isFile(target)) return { file: target };
  // trailingSlash: true なので /offline は /offline/ へ転送する
  if (await isFile(path.join(target, "index.html"))) return { redirect: decoded + "/" };
  return null;
}

function send(res, status, file) {
  res.writeHead(status, {
    "Content-Type": TYPES[path.extname(file)] ?? "application/octet-stream",
    "Cache-Control": "no-cache",
  });
  createReadStream(file).pipe(res);
}

const server = createServer(async (req, res) => {
  const url = new URL(req.url ?? "/", "http://localhost");
  const found = req.method === "GET" || req.method === "HEAD" ? await resolve(url.pathname) : null;
  if (found?.redirect) {
    res.writeHead(301, { Location: found.redirect + url.search });
    res.end();
  } else if (found?.file) {
    if (req.method === "HEAD") {
      res.writeHead(200, { "Content-Type": TYPES[path.extname(found.file)] ?? "application/octet-stream" });
      res.end();
    } else {
      send(res, 200, found.file);
    }
  } else {
    const notFound = path.join(root, "404.html");
    if (await isFile(notFound)) send(res, 404, notFound);
    else res.writeHead(404).end("Not Found");
  }
  console.log(`${req.method} ${url.pathname}${url.search} → ${res.statusCode}`);
});

if (!(await isFile(path.join(root, "index.html")))) {
  console.error(`${root} に静的ビルドがありません。先に \`npm run build\` を実行してください。`);
  process.exit(1);
}
server.listen(port, host, () => {
  console.log(`静的ビルドを配信しています: http://${host === "0.0.0.0" ? "localhost" : host}:${port}/ (${root})`);
});
