"""立ち絵の元画像(JPEG・単色の背景)から背景を抜き、透過 PNG にする。

元画像は `.work/`(git 管理外)に置き、出力は `public/assets/characters/`。
背景は画像の縁から塗りつぶしで求め(縁とつながった背景色の領域)、輪郭はなだらかに透かす。
腕と胴のすき間のように縁とつながらない背景も、背景色にごく近い大きな領域なら抜く。
最後に 256 色(透過つき)に減色して、1 枚を pre-commit の上限(500KB)より十分小さくする。

    uv run --no-project --with pillow --with numpy --with scipy python scripts/cutout_sprites.py
"""

from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / ".work"
OUT = ROOT / "public" / "assets" / "characters"

NAMES = [
    "aya_standard",
    "cub_standard",
    "cub_nervous",
    "cub_lose",
    "tama_standard",
    "tama_igiari",
]
# 出力の長辺(px)。表示は最大 256px 幅程度なので、高 DPI でも足りる大きさ
MAX_SIDE = 1100
# 減色後の色数(PNG のパレット。透過も保つ)
COLORS = 256
# 背景色からの距離(RGB)。NEAR 以下は背景、FAR 以上は前景、その間は半透明
NEAR = 26.0
FAR = 60.0
# 縁とつながらない背景のかたまりを抜くときの、距離と最小の面積(画素数の割合)
ISLAND_DIST = 18.0
ISLAND_MIN_AREA = 0.002


def background_color(rgb: np.ndarray) -> np.ndarray:
    """縁の画素の中央値を背景色とする。"""
    border = np.concatenate([rgb[0], rgb[-1], rgb[:, 0], rgb[:, -1]])
    return np.median(border, axis=0)


def cutout(path: Path) -> Image.Image:
    img = Image.open(path).convert("RGB")
    rgb = np.asarray(img).astype(np.float32)
    # JPEG のノイズと背景のざらつきをならしてから距離を測る
    smooth = ndimage.uniform_filter(rgb, size=(5, 5, 1))
    dist = np.linalg.norm(smooth - background_color(rgb), axis=2)

    # 縁とつながった背景(FAR 未満で塗りつぶし)
    candidate = dist < FAR
    labels, _ = ndimage.label(candidate)
    edge_labels = np.unique(np.concatenate([labels[0], labels[-1], labels[:, 0], labels[:, -1]]))
    edge_labels = edge_labels[edge_labels != 0]
    background = np.isin(labels, edge_labels)

    # 縁とつながらない背景のかたまり(腕のすき間など)
    island = dist < ISLAND_DIST
    island_labels, count = ndimage.label(island & ~background)
    if count:
        sizes = ndimage.sum(island, island_labels, index=np.arange(1, count + 1))
        big = np.flatnonzero(sizes >= ISLAND_MIN_AREA * dist.size) + 1
        background |= ndimage.binary_dilation(np.isin(island_labels, big), iterations=2) & (dist < FAR)

    # 背景の領域の中では距離に応じて透かす(輪郭のなだらかさ)。前景はそのまま不透明
    ramp = np.clip((dist - NEAR) / (FAR - NEAR), 0.0, 1.0)
    alpha = np.where(background, ramp, 1.0)
    # 小さな穴・粒を消し、輪郭を 1px だけぼかす
    solid = ndimage.binary_opening(alpha > 0.5, iterations=2)
    solid = ndimage.binary_fill_holes(solid) | (alpha > 0.5) & ~background
    alpha = np.where(solid, np.maximum(alpha, 0.0), alpha * 0.0)
    alpha = ndimage.gaussian_filter(alpha, sigma=0.8)

    # 半透明の輪郭に残る背景色を差し引く(色かぶりを抑える)
    bg = background_color(rgb)
    a = np.clip(alpha, 1e-3, 1.0)[..., None]
    fg = np.where(alpha[..., None] < 0.999, (rgb - bg * (1 - a)) / a, rgb)
    fg = np.clip(fg, 0, 255)

    rgba = np.dstack([fg, np.clip(alpha, 0, 1) * 255]).astype(np.uint8)
    out = Image.fromarray(rgba, "RGBA")
    bbox = out.getchannel("A").point(lambda v: 255 if v > 8 else 0).getbbox()
    if bbox:
        out = out.crop(bbox)
    out.thumbnail((MAX_SIDE, MAX_SIDE), Image.Resampling.LANCZOS)
    # 塗りの絵なので 256 色に減らしても見た目はほぼ変わらない(ファイルは 1/5 ほどになる)
    return out.quantize(COLORS, method=Image.Quantize.FASTOCTREE, dither=Image.Dither.FLOYDSTEINBERG)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name in NAMES:
        out = cutout(SRC / f"{name}.jpg")
        dest = OUT / f"{name}.png"
        out.save(dest, optimize=True)
        print(f"{dest.relative_to(ROOT)}: {out.size[0]}x{out.size[1]}, {dest.stat().st_size // 1024} KiB")


if __name__ == "__main__":
    main()
