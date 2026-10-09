"""
Sprite Harmonize: make every part of a split sprite sheet use the same colors.

Body parts drawn at different times drift apart: one sleeve is more saturated, a
headband is darker, a newer torso is a touch brighter. This script measures each
color family (jacket orange, dark blue, skin, red, hair yellow) in a reference
sprite, then shifts the same family in every other sprite to the reference's lit
and shadow tones. Cel shading, outlines, whites and grays are left alone.

Usage:
  python sprite_harmonize.py --batch SplitSheetNaruto/ SplitSheetNaruto_harmonized/ --reference Torso3.png
  python sprite_harmonize.py --report SplitSheetNaruto/        # just print each part's colors

Requires: pip install pillow numpy
"""
import argparse, os
import numpy as np
from PIL import Image

# color families: center hue (deg), hue half-width, min saturation, min value, max saturation
FAMILIES = {
    "orange": (25, 13, 0.45, 0.35, 1.01),
    "blue":   (218, 18, 0.40, 0.12, 1.01),
    "skin":   (18, 10, 0.12, 0.70, 0.45),
    "red":    (355, 10, 0.45, 0.30, 1.01),
    "yellow": (52, 10, 0.40, 0.55, 1.01),
}
FEATHER_H, FEATHER_S, FEATHER_V = 6.0, 0.08, 0.08   # soft edges of each family's mask


def rgb_to_hsv(rgb):
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    mx, mn = rgb.max(-1), rgb.min(-1); d = mx - mn
    m = d > 1e-6; dd = np.where(m, d, 1)
    rc, gc, bc = (mx - r) / dd, (mx - g) / dd, (mx - b) / dd
    h = np.where(r == mx, bc - gc, np.where(g == mx, 2 + rc - bc, 4 + gc - rc))
    h = np.where(m, (h / 6) % 1 * 360, 0)
    s = np.where(mx > 0, d / np.maximum(mx, 1e-6), 0)
    return h, s, mx


def hsv_to_rgb(h, s, v):
    h6 = (h % 360) / 60; i = np.floor(h6).astype(int) % 6; f = h6 - np.floor(h6)
    p, q, t = v * (1 - s), v * (1 - s * f), v * (1 - s * (1 - f))
    r = np.choose(i, [v, q, p, p, t, v]); g = np.choose(i, [t, v, v, q, p, p]); b = np.choose(i, [p, p, t, v, v, q])
    return np.stack([r, g, b], -1)


def hue_dist(h, c):
    return np.abs(((h - c) + 180) % 360 - 180)


def family_weight(h, s, v, key):
    """Soft 0..1 membership; hard core used for measuring, soft ramp used for editing."""
    c, w, smin, vmin, smax = FAMILIES[key]
    wh = np.clip((w + FEATHER_H - hue_dist(h, c)) / FEATHER_H, 0, 1)
    ws = np.clip((s - smin + FEATHER_S) / FEATHER_S, 0, 1) * np.clip((smax + FEATHER_S - s) / FEATHER_S, 0, 1)
    wv = np.clip((v - vmin + FEATHER_V) / FEATHER_V, 0, 1)
    return wh * ws * wv


def load(path):
    a = np.asarray(Image.open(path).convert("RGBA")).astype(np.float32)
    return a[..., :3] / 255.0, a[..., 3]


def measure(path):
    """Lit and shadow tone (h, s, v) of each color family present in the sprite."""
    rgb, alpha = load(path)
    h, s, v = rgb_to_hsv(rgb)
    out = {}
    for key in FAMILIES:
        core = (family_weight(h, s, v, key) > 0.999) & (alpha > 250)
        if core.sum() < 300:
            continue
        vv = v[core]
        lit, sh = core & (v >= np.percentile(vv, 60)), core & (v <= np.percentile(vv, 20))
        med = lambda m: (float(np.degrees(np.angle(np.mean(np.exp(1j * np.radians(h[m])))))) % 360,
                         float(np.median(s[m])), float(np.median(v[m])))
        out[key] = {"lit": med(lit), "shadow": med(sh), "n": int(core.sum())}
    return out


def harmonize(path, ref):
    rgb, alpha = load(path)
    h, s, v = rgb_to_hsv(rgb)
    mine = measure(path)
    nh, ns, nv = h.copy(), s.copy(), v.copy()
    for key, t in mine.items():
        if key not in ref:
            continue
        R = ref[key]
        w = family_weight(h, s, v, key)
        (h1, s1, v1), (h0, s0, v0) = t["lit"], t["shadow"]
        (H1, S1, V1), (H0, S0, V0) = R["lit"], R["shadow"]
        two_tone = (v1 - v0) > 0.12 and (V1 - V0) > 0.12
        if two_tone:   # map shadow->shadow and lit->lit, so cel shading keeps its steps
            k = np.clip((v - v0) / (v1 - v0), -0.5, 1.5)
            dh = ((H0 - h0 + 180) % 360 - 180) * (1 - k) + ((H1 - h1 + 180) % 360 - 180) * k
            sr = (S0 / max(s0, 1e-3)) * (1 - k) + (S1 / max(s1, 1e-3)) * k
            tv = V0 + (v - v0) * (V1 - V0) / (v1 - v0)
        else:          # one dependable tone: shift hue, scale saturation and brightness
            dh = (H1 - h1 + 180) % 360 - 180
            sr = S1 / max(s1, 1e-3)
            tv = v * (V1 / max(v1, 1e-3))
        nh = nh + dh * w
        ns = ns * (1 + (sr - 1) * w)
        nv = nv + (tv - v) * w
    out = hsv_to_rgb(nh, np.clip(ns, 0, 1), np.clip(nv, 0, 1))
    res = np.concatenate([out * 255, alpha[..., None]], -1)
    return Image.fromarray(np.clip(res, 0, 255).round().astype(np.uint8), "RGBA")


def list_pngs(folder):
    return sorted(os.path.relpath(os.path.join(dp, f), folder)
                  for dp, _, fs in os.walk(folder) for f in fs if f.lower().endswith(".png"))


def fmt(t):
    hx = lambda hsv: "#%02x%02x%02x" % tuple((hsv_to_rgb(np.array(hsv[0]), np.array(hsv[1]), np.array(hsv[2])) * 255).round().astype(int))
    return f"lit {hx(t['lit'])}  shadow {hx(t['shadow'])}"


def report(folder):
    for rel in list_pngs(folder):
        m = measure(os.path.join(folder, rel))
        print(f"{rel:24} " + "   ".join(f"{k}: {fmt(t)}" for k, t in m.items()))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("input", help="sprite folder (or one sprite)")
    p.add_argument("output", nargs="?", help="output folder (or file)")
    p.add_argument("--reference", help="sprite whose colors everything should match (path relative to the input folder, or a full path)")
    p.add_argument("--batch", action="store_true", help="process a whole folder, keeping subfolders")
    p.add_argument("--report", action="store_true", help="only print each sprite's measured colors")
    a = p.parse_args()
    if a.report:
        report(a.input); raise SystemExit
    if not a.reference or not a.output:
        p.error("--reference and an output are required")
    refpath = a.reference if os.path.exists(a.reference) else os.path.join(a.input, a.reference)
    ref = measure(refpath)
    print("reference", refpath, {k: fmt(t) for k, t in ref.items()})
    if a.batch:
        # families the reference doesn't contain (skin, hair...) match the most common value across the set
        allm = [measure(os.path.join(a.input, rel)) for rel in list_pngs(a.input)]
        for key in FAMILIES:
            if key in ref:
                continue
            got = [m[key] for m in allm if key in m]
            if not got:
                continue
            med = lambda part: tuple(float(np.median([g[part][i] for g in got])) for i in range(3))
            ref[key] = {"lit": med("lit"), "shadow": med("shadow"), "n": 0}
            print("consensus", key, fmt(ref[key]))
        for rel in list_pngs(a.input):
            dst = os.path.join(a.output, rel); os.makedirs(os.path.dirname(dst), exist_ok=True)
            harmonize(os.path.join(a.input, rel), ref).save(dst, optimize=True)
            print("done", rel)
    else:
        os.makedirs(os.path.dirname(a.output) or ".", exist_ok=True)
        harmonize(a.input, ref).save(a.output, optimize=True)
