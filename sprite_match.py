"""
Sprite Match: grade clean character sprites so they sit inside a Storm-style
background (muted color, soft lines, fine film texture) instead of looking pasted on.

Usage:
  python sprite_match.py sprite.png out.png
  python sprite_match.py --batch SplitSheetNaruto/ SplitSheetNaruto_matched/
  python sprite_match.py --batch in/ out/ --look storm_bg --strength 0.8

Transparency is kept, folder structure is kept in --batch mode, and the texture is
baked in (static), the same way the background art carries its texture.

Requires: pip install pillow numpy
"""
import argparse, os
import numpy as np
from PIL import Image, ImageFilter

# Looks are measured from a reference screenshot. Values are at the sprite file's own
# resolution; `screen_scale` is how big the sprite appears in game relative to its file
# (0.48 = the head file is drawn about half size), used to size blur and noise.
LOOKS = {
    # Ultimate jutsu backgrounds (stone face / gate scene): neutral-cool grays,
    # whites around 205, soft outlines, fine colored speckle.
    "storm_bg": dict(
        black=10,          # lifted black level (0-255)
        white=208,         # white ceiling (0-255)
        saturation=0.80,   # 1.0 = unchanged
        shadow_cool=6,     # extra blue in the darks
        blur=1.3,          # softness in sprite pixels
        luma_noise=1.4,    # texture strength in sprite pixels (std, 0-255 scale)
        chroma_noise=2.9,  # colored speckle (std per channel)
        screen_scale=0.48,
    ),
}


def match(img, look="storm_bg", strength=1.0, seed=11):
    L = LOOKS[look]
    rgba = img.convert("RGBA")
    a = np.asarray(rgba).astype(np.float32)
    rgb, alpha = a[..., :3], a[..., 3:4] / 255.0

    # soften: blur premultiplied color so edges don't pick up dark fringes
    if L["blur"] > 0:
        pm = np.concatenate([rgb * alpha, alpha * 255], -1).clip(0, 255).astype(np.uint8)
        pm = np.asarray(Image.fromarray(pm, "RGBA").filter(ImageFilter.GaussianBlur(L["blur"] * strength))).astype(np.float32)
        al = pm[..., 3:4] / 255.0
        rgb = np.where(al > 0.004, pm[..., :3] / np.maximum(al, 0.004), rgb)
        alpha = alpha * (1 - 0.35 * strength) + al * 0.35 * strength   # edges soften a little, not a halo

    out = rgb / 255.0
    # saturation
    lum = (out @ np.array([0.299, 0.587, 0.114], np.float32))[..., None]
    sat = 1 + (L["saturation"] - 1) * strength
    out = lum + (out - lum) * sat
    # levels: lifted blacks, dimmer whites
    b, w = L["black"] / 255 * strength, 1 - (1 - L["white"] / 255) * strength
    out = b + out * (w - b)
    # cool shadows
    lum = (out @ np.array([0.299, 0.587, 0.114], np.float32))[..., None]
    out[..., 2:3] += (L["shadow_cool"] / 255) * strength * (1 - lum) ** 2
    # baked texture: shared luma grain + small per-channel speckle
    rng = np.random.default_rng(seed)
    h, wd = out.shape[:2]
    g = rng.standard_normal((h, wd, 1)).astype(np.float32) * L["luma_noise"] / 255
    c = rng.standard_normal((h, wd, 3)).astype(np.float32) * L["chroma_noise"] / 255
    out = out + (g + c) * strength

    res = np.concatenate([np.clip(out, 0, 1) * 255, np.clip(alpha, 0, 1) * 255], -1)
    return Image.fromarray(res.round().astype(np.uint8), "RGBA")


def run(src, dst, look, strength, seed):
    os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
    match(Image.open(src), look, strength, seed).save(dst, optimize=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("input"); p.add_argument("output")
    p.add_argument("--look", default="storm_bg", choices=LOOKS)
    p.add_argument("--strength", type=float, default=1.0, help="0 = untouched, 1 = full match")
    p.add_argument("--seed", type=int, default=11)
    p.add_argument("--batch", action="store_true", help="input/output are folders (subfolders kept)")
    a = p.parse_args()
    if a.batch:
        for dp, _, fs in os.walk(a.input):
            for f in sorted(fs):
                if f.lower().endswith((".png", ".webp")):
                    s = os.path.join(dp, f)
                    d = os.path.join(a.output, os.path.relpath(s, a.input))
                    run(s, os.path.splitext(d)[0] + ".png", a.look, a.strength, a.seed)
                    print("done", d)
    else:
        run(a.input, a.output, a.look, a.strength, a.seed)
