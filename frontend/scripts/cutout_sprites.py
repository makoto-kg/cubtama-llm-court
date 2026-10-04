"""立ち絵の元画像(JPEG・単色の背景)から背景を抜き、透過 PNG にする。

元画像は `.work/`(git 管理外)に置き、出力は `public/assets/`(立ち絵は `characters/`、タイトルロゴは `title.png`)。
口を閉じた版の元画像がある立ち絵は、口まわりだけを切り出した `characters/<立ち絵>_mouth.png` も出力する(口パク用)。
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
OUT = ROOT / "public" / "assets"

# 元画像の名前と出力先(`OUT` からの相対パス)
SPRITES = {name: f"characters/{name}.png" for name in [
    "aya_standard",
    "cub_standard",
    "cub_nervous",
    "cub_lose",
    "tama_standard",
    "tama_igiari",
    "tama_lose",
]}
SPRITES["title"] = "title.png"
# 出力の長辺(px)。立ち絵の表示は最大 256px 幅程度なので、高 DPI でも足りる大きさ。
# タイトルロゴは画面幅いっぱいに出すので大きめにする
MAX_SIDE = 1100
MAX_SIDE_BY_NAME = {"title": 1600}
# 減色後の色数(PNG のパレット。透過も保つ)
COLORS = 256
# 背景色からの距離(RGB)。NEAR 以下は背景、FAR 以上は前景、その間は半透明
NEAR = 26.0
FAR = 60.0
# 縁とつながらない背景のかたまりを抜くときの、距離と最小の面積(画素数の割合)
ISLAND_DIST = 18.0
ISLAND_MIN_AREA = 0.002
# 文字の内側(「て」「ん」のすき間など)も抜く画像。背景色(マゼンタ)が絵に使われていないので、小さなかたまりも抜ける
ISLAND_MIN_AREA_BY_NAME = {"title": 0.00002}
# 口パクの口を閉じた版(立ち絵の名前 → 口を閉じた元画像の名前)。口まわりだけを `characters/<立ち絵>_mouth.png` に切り出す
MOUTH_PATCHES = {"tama_igiari": "tama_igiari_close"}
# 口まわりとみなす色の差(RGB。15px 四方でならした値)・広げる幅(元画像の px)・縁のぼかし(元画像の px)
MOUTH_DIFF = 30.0
MOUTH_GROW = 12
MOUTH_FEATHER = 6.0
# 輪郭を内側へ削る幅(元画像の px)。JPEG のにじみで輪郭の外側に背景色の縁が残る画像に使う
ERODE_BY_NAME = {"title": 2}


def background_color(rgb: np.ndarray) -> np.ndarray:
    """縁の画素の中央値を背景色とする。"""
    border = np.concatenate([rgb[0], rgb[-1], rgb[:, 0], rgb[:, -1]])
    return np.median(border, axis=0)


def transparent(path: Path, island_min_area: float = ISLAND_MIN_AREA, erode: int = 0) -> Image.Image:
    """元画像の背景を抜いた RGBA(元画像と同じ大きさ。切り詰め・縮小・減色の前)。"""
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
        big = np.flatnonzero(sizes >= island_min_area * dist.size) + 1
        background |= ndimage.binary_dilation(np.isin(island_labels, big), iterations=2) & (dist < FAR)

    # 背景の領域の中では距離に応じて透かす(輪郭のなだらかさ)。前景はそのまま不透明
    ramp = np.clip((dist - NEAR) / (FAR - NEAR), 0.0, 1.0)
    alpha = np.where(background, ramp, 1.0)
    # 小さな穴・粒を消し、輪郭を 1px だけぼかす
    solid = ndimage.binary_opening(alpha > 0.5, iterations=2)
    solid = ndimage.binary_fill_holes(solid) | (alpha > 0.5) & ~background
    alpha = np.where(solid, np.maximum(alpha, 0.0), alpha * 0.0)
    if erode:
        alpha = ndimage.grey_erosion(alpha, size=(2 * erode + 1, 2 * erode + 1))
    alpha = ndimage.gaussian_filter(alpha, sigma=0.8)

    # 半透明の輪郭に残る背景色を差し引く(色かぶりを抑える)
    bg = background_color(rgb)
    a = np.clip(alpha, 1e-3, 1.0)[..., None]
    fg = np.where(alpha[..., None] < 0.999, (rgb - bg * (1 - a)) / a, rgb)
    fg = np.clip(fg, 0, 255)
    if erode:
        # 輪郭に残った背景色のにじみを抑える: 半透明の画素は、背景色の成分を前景の暗い色に寄せる
        edge = (alpha < 0.999)[..., None]
        fg = np.where(edge, np.minimum(fg, np.min(fg, axis=2, keepdims=True) + 40), fg)

    rgba = np.dstack([fg, np.clip(alpha, 0, 1) * 255]).astype(np.uint8)
    return Image.fromarray(rgba, "RGBA")


def opaque_bbox(img: Image.Image) -> tuple[int, int, int, int]:
    """絵のある範囲(ほぼ透明な画素を除く)。"""
    bbox = img.getchannel("A").point(lambda v: 255 if v > 8 else 0).getbbox()
    return bbox or (0, 0, img.width, img.height)


def quantize(img: Image.Image) -> Image.Image:
    # 塗りの絵なので 256 色に減らしても見た目はほぼ変わらない(ファイルは 1/5 ほどになる)
    return img.quantize(COLORS, method=Image.Quantize.FASTOCTREE, dither=Image.Dither.FLOYDSTEINBERG)


def cutout(
    path: Path, max_side: int = MAX_SIDE, island_min_area: float = ISLAND_MIN_AREA, erode: int = 0
) -> Image.Image:
    out = transparent(path, island_min_area, erode)
    out = out.crop(opaque_bbox(out))
    out.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    return quantize(out)


def mouth_patch(name: str, closed: str) -> tuple[Image.Image, tuple[int, int]]:
    """口を閉じた版の元画像(`closed`)から、口まわりだけを切り出す(口パクで立ち絵に重ねる)。

    2 枚の元画像は口まわり以外がほぼ同じなので、色の差が大きい顔の中のかたまりを口まわりとする。
    立ち絵(`name`)と同じ範囲で切り詰めて同じ大きさに縮め、立ち絵の中の位置(左上)と一緒に返す。
    """
    opened_path = next(SRC.glob(f"{name}.jp*g"))
    closed_path = next(SRC.glob(f"{closed}.jp*g"))
    opened = transparent(opened_path)
    b = np.asarray(transparent(closed_path)).astype(np.float32)
    # 差は元画像どうしで測る(背景を抜いたあとの透明な画素の色は当てにならない)
    raw_a = np.asarray(Image.open(opened_path).convert("RGB")).astype(np.float32)
    raw_b = np.asarray(Image.open(closed_path).convert("RGB")).astype(np.float32)
    diff = ndimage.uniform_filter(np.linalg.norm(raw_a - raw_b, axis=2), size=15)
    labels, count = ndimage.label(diff > MOUTH_DIFF)
    if not count:
        raise SystemExit(f"{closed}: {name} との差が見つからない")
    # 口まわりは差のかたまりの中でいちばん大きい
    sizes = ndimage.sum(np.ones_like(diff), labels, index=np.arange(1, count + 1))
    region = ndimage.binary_fill_holes(labels == np.argmax(sizes) + 1)
    region = ndimage.binary_dilation(region, iterations=MOUTH_GROW)
    # 縁をなだらかにして、重ねたときに境目が見えないようにする
    feather = ndimage.gaussian_filter(region.astype(np.float32), sigma=MOUTH_FEATHER)
    alpha = b[..., 3] * np.clip(feather * 2 - 0.2, 0.0, 1.0)
    patch = Image.fromarray(np.dstack([b[..., :3], alpha]).astype(np.uint8), "RGBA")

    sprite = opened.crop(opaque_bbox(opened))
    sprite.thumbnail((MAX_SIDE, MAX_SIDE), Image.Resampling.LANCZOS)
    patch = patch.crop(opaque_bbox(opened)).resize(sprite.size, Image.Resampling.LANCZOS)
    box = opaque_bbox(patch)
    return quantize(patch.crop(box)), (box[0], box[1])


def main() -> None:
    for name, rel in SPRITES.items():
        out = cutout(
            next(SRC.glob(f"{name}.jp*g")),
            max_side=MAX_SIDE_BY_NAME.get(name, MAX_SIDE),
            island_min_area=ISLAND_MIN_AREA_BY_NAME.get(name, ISLAND_MIN_AREA),
            erode=ERODE_BY_NAME.get(name, 0),
        )
        dest = OUT / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        out.save(dest, optimize=True)
        print(f"{dest.relative_to(ROOT)}: {out.size[0]}x{out.size[1]}, {dest.stat().st_size // 1024} KiB")
    for name, closed in MOUTH_PATCHES.items():
        patch, (left, top) = mouth_patch(name, closed)
        dest = OUT / "characters" / f"{name}_mouth.png"
        patch.save(dest, optimize=True)
        # 立ち絵の中の位置は `src/assets/manifest.ts` の `closedMouth` に写す
        print(
            f"{dest.relative_to(ROOT)}: {patch.size[0]}x{patch.size[1]} at ({left}, {top}),"
            f" {dest.stat().st_size // 1024} KiB"
        )


if __name__ == "__main__":
    main()
