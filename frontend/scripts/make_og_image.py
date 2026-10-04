"""OGP 画像(SNS で共有したときのカード)を、タイトルロゴと立ち絵から合成する。

入力は `public/assets/`(`scripts/cutout_sprites.py` の出力)。出力は `src/app/opengraph-image.jpg`
(Next.js のファイル規約。pre-commit の上限 500KB に収めるため JPEG。`og:image` / `twitter:image` のタグはビルド時に自動で付く)。
画面のタイトル(`TitleHero`)と同じ配色: 暗い木目の背景に金の放射線、ロゴの下にサブタイトルの帯、
左にタマ検察官(つきつけ)、右にカブ被告(動揺)。サブタイトルの字はヒラギノ角ゴ W9(macOS)で描く。

    uv run --no-project --with pillow --with numpy python scripts/make_og_image.py
"""

import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "public" / "assets"
OUT = ROOT / "src" / "app" / "opengraph-image.jpg"

W, H = 1200, 630
SUBTITLE = "そのトークンに異議あり"  # src/assets/manifest.ts の GAME_SUBTITLE と同じ
FONT = "/System/Library/Fonts/ヒラギノ角ゴシック W9.ttc"


def background() -> Image.Image:
    """縦のグラデーションに、上の金の光と下の赤い光を重ねる(globals.css の .title-hero と同じ配色)。"""
    y, x = np.mgrid[0:H, 0:W].astype(np.float32)
    t = y / (H - 1)
    top, mid, bottom = np.array([36, 18, 12]), np.array([20, 11, 8]), np.array([26, 20, 16])
    k = np.clip(t / 0.55, 0, 1)[..., None]
    k2 = np.clip((t - 0.55) / 0.45, 0, 1)[..., None]
    rgb = np.where(t[..., None] < 0.55, top + (mid - top) * k, mid + (bottom - mid) * k2)

    def glow(cx: float, cy: float, rx: float, ry: float, color: tuple[int, int, int], alpha: float) -> None:
        d = np.sqrt(((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2)
        a = (np.clip(1 - d / 0.7, 0, 1) * alpha)[..., None]
        rgb[:] = rgb * (1 - a) + np.array(color) * a

    glow(W / 2, H * 0.38, W * 0.6, H * 0.6, (255, 196, 90), 0.35)
    glow(W / 2, H, W * 0.9, H * 0.6, (150, 20, 24), 0.55)

    # 金の放射線(中心から離れるほど薄く)
    cx, cy = W / 2, H * 0.4
    ang = (np.degrees(np.arctan2(y - cy, x - cx)) + 360) % 18
    r = np.hypot(x - cx, y - cy) / max(W, H)
    ray = ((ang < 6) * np.clip(1 - r / 0.6, 0, 1) * 0.13)[..., None]
    rgb = rgb * (1 - ray) + np.array([255, 210, 120]) * ray
    return Image.fromarray(rgb.clip(0, 255).astype(np.uint8)).convert("RGBA")


def fit(img: Image.Image, height: int) -> Image.Image:
    return img.resize((round(img.width * height / img.height), height), Image.Resampling.LANCZOS)


def shadow(img: Image.Image, blur: int, opacity: float) -> Image.Image:
    a = img.getchannel("A").point(lambda v: round(v * opacity))
    s = Image.new("RGBA", img.size, (0, 0, 0, 0))
    s.putalpha(a)
    return s.filter(ImageFilter.GaussianBlur(blur))


def paste(canvas: Image.Image, img: Image.Image, xy: tuple[int, int], blur: int = 12) -> None:
    pad = blur * 3
    s = Image.new("RGBA", (img.width + pad * 2, img.height + pad * 2), (0, 0, 0, 0))
    s.alpha_composite(img, (pad, pad))
    canvas.alpha_composite(shadow(s, blur, 0.6), (xy[0] - pad, xy[1] - pad + 6))
    canvas.alpha_composite(img, xy)


def subtitle_band(text: str) -> Image.Image:
    """赤い帯に金縁、白抜きの字(画面の .title-subtitle を静止画にしたもの)。"""
    font = ImageFont.truetype(FONT, 38)
    spacing = 9
    widths = [font.getbbox(c)[2] - font.getbbox(c)[0] for c in text]
    text_w = sum(widths) + spacing * (len(text) - 1)
    bw, bh = text_w + 120, 66
    band = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    d = ImageDraw.Draw(band)
    skew = 18
    d.polygon([(skew, 0), (bw, 0), (bw - skew, bh), (0, bh)], fill=(150, 18, 24, 255))
    d.polygon([(skew, 0), (bw, 0), (bw - skew, bh), (0, bh)], outline=(224, 165, 38, 255), width=3)
    x = (bw - text_w) / 2
    for c, cw in zip(text, widths, strict=True):
        d.text((x - font.getbbox(c)[0], bh / 2), c, font=font, fill=(255, 246, 225), anchor="lm",
               stroke_width=2, stroke_fill=(60, 8, 10))
        x += cw + spacing
    return band


def main() -> None:
    canvas = background()

    tama = fit(Image.open(ASSETS / "characters" / "tama_igiari.png").convert("RGBA"), 400)
    cub = fit(Image.open(ASSETS / "characters" / "cub_nervous.png").convert("RGBA"), 380)
    paste(canvas, cub, (W - cub.width + 10, H - cub.height))
    paste(canvas, tama, (-60, H - tama.height))

    logo = Image.open(ASSETS / "title.png").convert("RGBA")
    logo = logo.resize((760, math.floor(760 * logo.height / logo.width)), Image.Resampling.LANCZOS)
    lx, ly = (W - logo.width) // 2, 34
    paste(canvas, logo, (lx, ly), blur=16)

    band = subtitle_band(SUBTITLE)
    paste(canvas, band, ((W - band.width) // 2, ly + logo.height + 4), blur=8)

    canvas.convert("RGB").save(OUT, quality=88, optimize=True, progressive=True)
    print(f"{OUT.relative_to(ROOT)}: {OUT.stat().st_size // 1024}KB")


if __name__ == "__main__":
    main()
