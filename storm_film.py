"""
Storm-style old film effect for still portraits.

Usage:
  python storm_film.py input.png output.png [--preset medium] [--seed 7] [--no-trim]
  python storm_film.py --batch in_folder out_folder [--preset medium]
  python storm_film.py input.png output.gif --frames 36 --fps 18   (animated; .mp4/.webm need ffmpeg)
      .webm keeps transparency for cutout portraits; --scale 4 upscales for previews
  python storm_film.py box.png box.mp4 --preset icon_soft --frames 36 --weave 0 --render-scale 4
      (whole box, art held still, hairline scratches)
  add --mask auto to keep a baked-in checkerboard background untouched

  python storm_film.py icon.png icon_out.png --preset icon_soft --mask box_mask.png
      (mask: grayscale image, white = apply effect, black = keep original; use it to keep frames/badges crisp)

Presets: light, medium, heavy, icon_grain, icon_soft. Tweak PRESETS below to dial in your house look.
Requires: pip install pillow numpy
"""
import argparse, os, sys
import numpy as np
from PIL import Image, ImageFilter

PRESETS = {
    #           sepia desat fade  grain gsize vign  blur scratches dust  flicker
    "light":  dict(sepia=0.35, desat=0.25, fade=0.05, grain=0.030, gsize=1.3, vignette=0.40, blur=0.3, scratches=1, dust=8,  flicker=0.00),
    "medium": dict(sepia=0.60, desat=0.40, fade=0.08, grain=0.045, gsize=1.5, vignette=0.60, blur=0.5, scratches=3, dust=18, flicker=0.02),
    "heavy":  dict(sepia=0.85, desat=0.60, fade=0.12, grain=0.065, gsize=1.8, vignette=0.85, blur=0.7, scratches=5, dust=35, flicker=0.04),
    # Gentler looks for small unit/box icons
    "icon_grain": dict(sepia=0.00, desat=0.10, fade=0.03, grain=0.028, gsize=1.0, vignette=0.15, blur=0.0, scratches=0, dust=0, flicker=0.00),
    "icon_soft":  dict(sepia=0.25, desat=0.20, fade=0.05, grain=0.032, gsize=1.0, vignette=0.25, blur=0.0, scratches=2, dust=3, flicker=0.00,
                       scratch_dark=0.5, scratch_hold=3, scratch_strength=1.0, scratch_lanes=3, scratch_passes=2,
                       dark_opacity=0.32, dark_soften=0.9, light_opacity=0.32, light_soften=0.9),
    # icon_soft but brighter and more colorful: same grain/scratches, less greying.
    # icon_soft / icon_bright match the "Legacy Soft" / "Legacy Bright" presets in the Legacy Awaken app.
    "icon_bright": dict(sepia=0.12, desat=0.05, fade=0.02, grain=0.032, gsize=1.0, vignette=0.12, blur=0.0, scratches=2, dust=3, flicker=0.00,
                        scratch_dark=0.5, scratch_hold=3, scratch_strength=1.0, scratch_lanes=3, scratch_passes=2, bright=1.06,
                        dark_opacity=0.32, dark_soften=0.9, light_opacity=0.32, light_soften=0.9),
}
# Optional scratch keys (any preset):
#   scratch_dark     0-1  share of lines that are dark (1.0 = all black lines)
#   scratch_hold     frames a line stays before jumping (it still jitters 1px meanwhile)
#   scratch_strength how dark/bright lines get, 0-1
#   bright           overall exposure multiplier (1.0 = unchanged)
#   scratch_chance   0-1  how often each line actually shows (1.0 = always, 0.35 = occasional)
#   scratch_lanes    N    animations only: exactly N lines per loop, one in each of N side-by-side
#                         zones (left/middle/right for 3), each flicking on for scratch_hold frames
#   scratch_passes   how many times each zone fires per loop (2 = twice as busy)
#   (lane mode alternates dark/white lines in proportion to scratch_dark)
#   dark_opacity     0-1  how see-through black lines are (1.0 = solid black)
#   dark_soften      edge feather for black lines (0 = razor sharp)
#   light_opacity / light_soften   same two controls for the white lines

SEPIA = np.array([[.393, .769, .189],
                  [.349, .686, .168],
                  [.272, .534, .131]])


def trim_black_bars(img, thresh=20):
    a = np.asarray(img.convert("L")).astype(float)
    rows = np.where(a.mean(1) > thresh)[0]
    cols = np.where(a.mean(0) > thresh)[0]
    if len(rows) == 0 or len(cols) == 0:
        return img
    return img.crop((cols[0], rows[0], cols[-1] + 1, rows[-1] + 1))


def coarse_noise(h, w, size, rng):
    """Gaussian noise generated at lower res and upscaled = chunkier film grain."""
    sh, sw = max(1, int(h / size)), max(1, int(w / size))
    n = rng.standard_normal((sh, sw)).astype(np.float32)
    n_img = Image.fromarray(((n * 0.25 + 0.5).clip(0, 1) * 255).astype(np.uint8))
    n_img = n_img.resize((w, h), Image.BICUBIC)
    return (np.asarray(n_img).astype(np.float32) / 255.0 - 0.5) * 4.0


def film(img, sepia, desat, fade, grain, gsize, vignette, blur, scratches, dust, flicker, seed=7,
         scratch_dark=0.3, scratch_hold=1, scratch_strength=0.45, scratch_seed=None, unit=1.0, bright=1.0, scratch_chance=1.0,
         scratch_lanes=0, scratch_lane=None, scratch_passes=1, scratch_sign=None,
         dark_opacity=1.0, dark_soften=0.0, light_opacity=1.0, light_soften=0.0):
    """unit = how many output pixels one source pixel covers (set by --render-scale).
    Grain, dust and blur scale with it; scratch lines stay 1 output pixel wide, so they get skinnier."""
    rng = np.random.default_rng(seed)
    img = img.convert("RGB")
    blur *= unit
    gsize = gsize * (unit * 0.6 if unit > 1 else 1)
    if blur > 0:
        img = img.filter(ImageFilter.GaussianBlur(blur))  # old-lens softness
    c = np.asarray(img).astype(np.float32) / 255.0
    h, w, _ = c.shape

    # Color: desaturate, then sepia tone
    lum = c @ np.array([0.299, 0.587, 0.114], dtype=np.float32)
    c = c * (1 - desat) + lum[..., None] * desat
    sep = np.clip(c @ SEPIA.T, 0, 1)
    c = c * (1 - sepia) + sep * sepia

    # Fade: lift blacks, dull whites (aged print)
    c = fade + c * (1 - fade * 1.8)
    c *= bright

    # Grain, stronger in midtones, slightly different per channel
    lum = c @ np.array([0.299, 0.587, 0.114], dtype=np.float32)
    mid = 1.0 - np.abs(lum * 2 - 1) * 0.6
    base = coarse_noise(h, w, gsize, rng)
    for ch in range(3):
        chroma = coarse_noise(h, w, gsize, rng) * 0.25
        c[..., ch] += (base + chroma) * grain * mid

    # Flicker (single frame = slight exposure shift)
    c *= 1.0 + rng.uniform(-1, 1) * flicker

    # Vignette
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    d = np.sqrt(((xx - w / 2) / (w / 2)) ** 2 + ((yy - h / 2) / (h / 2)) ** 2) / np.sqrt(2)
    v = np.clip((d - 0.35) / 0.65, 0, 1) ** 1.6
    c *= (1 - v * vignette)[..., None]

    # Scratches: own layer so dark lines can read properly black.
    # scratch_seed (set by animate) keeps lines in place for scratch_hold frames; they jitter 1px per frame.
    srng = np.random.default_rng(scratch_seed) if scratch_seed is not None else rng
    lines = np.zeros((h, w), np.float32)   # + light line, - dark line
    if scratch_lanes and scratch_lane is not None:
        # Lane mode: at most one line, placed inside its zone; same spot every time that lane fires
        if scratch_lane >= 0:
            lo, hi = 0.08 + 0.84 * scratch_lane / scratch_lanes, 0.08 + 0.84 * (scratch_lane + 1) / scratch_lanes
            x0 = ((lo + hi) / 2 + srng.uniform(-0.2, 0.2) * (hi - lo)) * w   # near the zone's center
            drift = srng.uniform(-0.01, 0.01) * w
            strength = srng.uniform(0.7, 1.0) * scratch_strength
            sign = srng.random()   # keep the draw order stable
            sign = scratch_sign if scratch_sign is not None else (-1 if sign < scratch_dark else 1)
            jx, fl = rng.integers(-1, 2), rng.uniform(0.6, 1.0)
            for y in range(h):
                x = int(x0 + drift * (y / h)) + jx
                if 0 <= x < w:
                    lines[y, x] += sign * strength * fl
        scratches = 0   # skip the random scratches below
    for _ in range(scratches):
        x0 = srng.uniform(0, w)
        drift = srng.uniform(-0.02, 0.02) * w
        y_start, y_end = (0, h) if srng.random() < 0.6 else sorted(srng.uniform(0, h, 2))
        sign = -1 if srng.random() < scratch_dark else 1
        strength = srng.uniform(0.55, 1.0) * scratch_strength
        jx = rng.integers(-1, 2) if scratch_seed is not None else 0
        fl = rng.uniform(0.6, 1.0)                     # per-frame intensity flicker
        if srng.random() >= scratch_chance:            # this line sits out this stretch
            continue
        for y in range(int(y_start), int(y_end)):
            x = int(x0 + drift * (y / h)) + jx
            if 0 <= x < w:
                lines[y, x] += sign * strength * fl
    if unit <= 1:   # at native size soften a touch; at render scale keep hairlines crisp
        l_img = Image.fromarray(((np.clip(lines, -1, 1) * 0.5 + 0.5) * 255).astype(np.uint8))
        lines = (np.asarray(l_img.filter(ImageFilter.GaussianBlur(0.35))).astype(np.float32) / 255 - 0.5) * 2
    light = np.clip(lines, 0, 1)
    if light_soften > 0:  # feather white lines too
        l2 = Image.fromarray((light * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(light_soften * max(unit, 1) / 4))
        light = np.asarray(l2).astype(np.float32) / 255
    c += light[..., None] * 0.6 * light_opacity
    dark = np.clip(-lines, 0, 1)
    if dark_soften > 0:   # feather dark lines so they don't look inked on
        d_img = Image.fromarray((dark * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(dark_soften * max(unit, 1) / 4))
        dark = np.asarray(d_img).astype(np.float32) / 255
    c *= (1 - dark * dark_opacity)[..., None]

    # Dust drawn on a separate layer, then softened so it reads as film, not pixels
    marks = np.zeros((h, w), np.float32)   # +1 = light mark, -1 = dark mark
    for _ in range(dust):
        x, y = rng.uniform(0, w), rng.uniform(0, h)
        r = rng.uniform(0.6, 2.2) * unit
        sign = -1 if rng.random() < 0.65 else 1
        s_ = rng.uniform(0.4, 1.0)
        y0, y1 = int(max(0, y - 3 * r)), int(min(h, y + 3 * r + 1))
        x0_, x1 = int(max(0, x - 3 * r)), int(min(w, x + 3 * r + 1))
        yy2, xx2 = np.mgrid[y0:y1, x0_:x1]
        blob = np.exp(-(((xx2 - x) ** 2 + ((yy2 - y) * rng.uniform(0.5, 1.5)) ** 2) / (2 * r * r)))
        marks[y0:y1, x0_:x1] += sign * s_ * blob
    m_img = Image.fromarray(((np.clip(marks, -1, 1) * 0.5 + 0.5) * 255).astype(np.uint8))
    marks = (np.asarray(m_img.filter(ImageFilter.GaussianBlur(0.5))).astype(np.float32) / 255 - 0.5) * 2
    c += np.clip(marks, 0, 1)[..., None] * 0.35          # light marks
    c *= (1 - np.clip(-marks, 0, 1) * 0.55)[..., None]     # dark marks

    return Image.fromarray((np.clip(c, 0, 1) * 255).astype(np.uint8))


def animate(img, preset, frames=36, seed=7, weave=1, unit=1.0):
    """Render a looping sequence: new grain/dust/flicker each frame plus slight gate weave.
    Accepts RGB or RGBA; RGBA frames keep their transparency."""
    rng = np.random.default_rng(seed)
    has_alpha = img.mode == "RGBA"
    w, h = img.size
    hold = PRESETS[preset].get("scratch_hold", 1)
    lanes = PRESETS[preset].get("scratch_lanes", 0)
    passes = PRESETS[preset].get("scratch_passes", 1)
    dark_share = PRESETS[preset].get("scratch_dark", 1.0)
    if lanes:
        # every zone fires `passes` times per loop; each pass is a shuffled order (never a plain sweep),
        # and the same zone never fires twice in a row across a pass boundary
        prng = np.random.default_rng(seed + 99)
        order = []
        for _ in range(passes):
            for _try in range(50):
                p = [int(v) for v in prng.permutation(lanes)]
                sweep = lanes > 2 and (p == sorted(p) or p == sorted(p, reverse=True))
                if not sweep and (not order or p[0] != order[-1]):
                    break
            order += p
        slots = len(order)
        n_dark = round(slots * dark_share)
        if 0 < dark_share < 1 and abs(dark_share - 0.5) < 1e-6:
            # half and half: each zone alternates black/white on its own appearances, so every side gets both
            seen, signs = {}, []
            for l in order:
                j = seen.get(l, 0); seen[l] = j + 1
                signs.append(-1 if (l + j) % 2 == 0 else 1)
        else:
            signs = [-1 if (k * n_dark) // slots != ((k + 1) * n_dark) // slots else 1 for k in range(slots)]  # spread evenly
        period = frames // slots
        start = max(0, (period - hold) // 2)
        def slot_at(i):
            slot, pos = divmod(i, period)
            return slot if slot < slots and start <= pos < start + hold else -1
        lane_at = lambda i: order[slot_at(i)] if slot_at(i) >= 0 else -1
        sign_at = lambda i: signs[slot_at(i)] if slot_at(i) >= 0 else None
        sseed = lambda i: seed * 31 + max(slot_at(i), 0)
    else:
        lane_at = lambda i: None
        sign_at = lambda i: None
        sseed = lambda i: seed * 31 + i // hold   # same scratch layout for `hold` frames in a row
    out = []
    for i in range(frames):
        dx, dy = (int(v) for v in rng.integers(-weave, weave + 1, 2)) if weave else (0, 0)
        if has_alpha:   # cutout: shift on a transparent canvas, size stays the same
            frame = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            frame.paste(img, (dx, dy))
            f = film(frame.convert("RGB"), seed=seed * 1000 + i, scratch_seed=sseed(i), scratch_lane=lane_at(i), scratch_sign=sign_at(i), unit=unit, **PRESETS[preset])
            f.putalpha(frame.getchannel("A"))
        else:           # opaque: crop a hair inside the edge so the wobble never shows a border
            f = film(img.crop((weave + dx, weave + dy, w - weave + dx, h - weave + dy)),
                     seed=seed * 1000 + i, scratch_seed=sseed(i), scratch_lane=lane_at(i), scratch_sign=sign_at(i), unit=unit, **PRESETS[preset])
        out.append(f)
    return out


def _flatten(f, bg):
    if f.mode != "RGBA":
        return f.convert("RGB")
    base = Image.new("RGB", f.size, bg)
    base.paste(f, mask=f.getchannel("A"))
    return base


def save_animation(frames, dst, fps=18, scale=1, bg=(27, 27, 31), loops=4):
    """.gif / .mp4 are flattened onto bg. .webm keeps transparency (VP9 alpha)."""
    if scale != 1:
        frames = [f.resize((f.width * scale, f.height * scale), Image.NEAREST) for f in frames]
    ext = os.path.splitext(dst)[1].lower()
    if ext == ".gif":
        flat = [_flatten(f, bg) for f in frames]
        flat[0].save(dst, save_all=True, append_images=flat[1:],
                     duration=int(1000 / fps), loop=0, optimize=False)
        return
    import subprocess, tempfile
    keep_alpha = ext == ".webm"
    with tempfile.TemporaryDirectory() as tmp:
        for i, f in enumerate(frames):
            (f if keep_alpha else _flatten(f, bg)).save(os.path.join(tmp, f"f{i:04d}.png"))
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(fps),
               "-stream_loop", str(loops - 1), "-i", os.path.join(tmp, "f%04d.png"),
               "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2"]
        if keep_alpha:
            cmd += ["-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", "-b:v", "0", "-crf", "18", "-auto-alt-ref", "0"]
        else:
            cmd += ["-c:v", "libx264", "-crf", "14", "-pix_fmt", "yuv420p"]
        subprocess.run(cmd + [dst], check=True)


def auto_box_mask(img):
    """Mask of the box itself: flood-fills gray/white checkerboard background in from the edges.
    Interior whites (like the rarity number) are kept because they don't touch the border."""
    from scipy import ndimage as nd
    a = np.asarray(img.convert("RGB")).astype(int)
    sat, v = a.max(2) - a.min(2), a.mean(2)
    checker = (sat < 22) & (v > 110) & (v < 215)
    lab, _ = nd.label(checker)
    edge = set(np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]]))) - {0}
    box = nd.binary_fill_holes(~np.isin(lab, list(edge)))
    box = nd.binary_opening(box, iterations=1)
    return Image.fromarray((box * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(0.6))


def apply_mask(orig, filtered, mask_path):
    mask = mask_path if isinstance(mask_path, Image.Image) else Image.open(mask_path)
    mask = mask.convert("L")
    if mask.size != orig.size:
        mask = mask.resize(orig.size, Image.BILINEAR)
    return Image.composite(filtered, orig.convert(filtered.mode), mask)


def process(src, dst, preset, seed, trim, frames=0, fps=18, mask=None, scale=1, weave=1, render_scale=1):
    raw = Image.open(src)
    has_alpha = raw.mode in ("RGBA", "LA", "P") and raw.convert("RGBA").getchannel("A").getextrema()[0] < 255
    img = raw.convert("RGBA") if has_alpha else raw.convert("RGB")
    if trim and not mask and not has_alpha:   # never trim masked or transparent images
        img = trim_black_bars(img)
    if mask == "auto":     # build the box-shape mask before any resizing
        mask = auto_box_mask(img)
    if render_scale > 1:   # enlarge first so lines/grain are drawn at the final resolution
        img = img.resize((img.width * render_scale, img.height * render_scale), Image.LANCZOS)
    if frames:
        out = animate(img, preset, frames, seed, weave=0 if mask else weave * render_scale, unit=render_scale)
        if mask:
            out = [apply_mask(img, f, mask) for f in out]
        save_animation(out, dst, fps, scale)
    else:
        if has_alpha:
            out = film(img.convert("RGB"), seed=seed, unit=render_scale, **PRESETS[preset])
            out.putalpha(img.getchannel("A"))
        else:
            out = film(img, seed=seed, unit=render_scale, **PRESETS[preset])
        if mask:
            out = apply_mask(img, out, mask)
        if scale != 1:
            out = out.resize((out.width * scale, out.height * scale), Image.NEAREST)
        out.save(dst)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("input")
    p.add_argument("output")
    p.add_argument("--preset", default="medium", choices=PRESETS)
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--no-trim", action="store_true", help="keep black letterbox bars")
    p.add_argument("--batch", action="store_true", help="input/output are folders")
    p.add_argument("--frames", type=int, default=0, help="animate: number of frames (output .gif or .mp4)")
    p.add_argument("--fps", type=int, default=18)
    p.add_argument("--mask", help="grayscale mask (white = effect), or 'auto' to skip a checkerboard background")
    p.add_argument("--scale", type=int, default=1, help="nearest-neighbor upscale AFTER the effect (chunky preview)")
    p.add_argument("--render-scale", type=int, default=1, help="enlarge BEFORE the effect: skinnier lines, finer grain (e.g. 4)")
    p.add_argument("--weave", type=int, default=1, help="projector wobble in px for animations; 0 = art stays still")
    a = p.parse_args()
    if a.batch:
        os.makedirs(a.output, exist_ok=True)
        ext = ".png" if not a.frames else ".gif"
        for f in sorted(os.listdir(a.input)):
            if f.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
                out = os.path.join(a.output, os.path.splitext(f)[0] + ext)
                process(os.path.join(a.input, f), out, a.preset, a.seed, not a.no_trim, a.frames, a.fps, a.mask, a.scale, a.weave, a.render_scale)
                print("done", out)
    else:
        process(a.input, a.output, a.preset, a.seed, not a.no_trim, a.frames, a.fps, a.mask, a.scale, a.weave, a.render_scale)
