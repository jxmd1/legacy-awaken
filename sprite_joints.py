"""
Sprite Joints: hide the seams where split-sheet body parts overlap.

Each part of a split sprite sheet is drawn with a full outline, so wherever two parts
overlap in the rig you see a dark seam. This script feathers each part's connecting
end: the outline there dissolves into the part's own fill color and the end fades to
transparent over a short distance, so it melts into the part underneath.

Which end of which part fades is set in JOINTS below (or a JSON file with the same
shape passed via --joints). Directions point toward the joint: "top", "bottom",
"left", "right", or a combination such as "bottom-left".

Usage:
  python sprite_joints.py --batch SplitSheetNaruto_harmonized/ SplitSheetNaruto_blended/
  python sprite_joints.py --batch in/ out/ --fade 0.10          # longer fades
  python sprite_joints.py --batch in/ out/ --joints joints.json

Requires: pip install pillow numpy scipy
"""
import argparse, json, os
import numpy as np
from PIL import Image
from scipy import ndimage as nd

# File name (relative to the sheet folder) -> list of joint ends to feather.
JOINTS = {
    "Arm1.png": ["bottom"], "New/Arm1.png": ["bottom"],
    "Arm_2.png": ["top"],
    "LeftArm.png": ["top"],
    "New/ArmRaised.png": ["bottom-left"],
    "Leg1.png": ["top"], "Leg2.png": ["top"], "New/Leg-1.png": ["top"], "New/Leg-2.png": ["top"],
    "Leg3.png": ["top"], "New/LegPouch.png": ["top"],
    "Thigh.png": ["top"], "New/Thigh-1.png": ["top"],
    "WaistExtra.png": ["top"],
}
DIRS = {"top": (0, -1), "bottom": (0, 1), "left": (-1, 0), "right": (1, 0)}


def direction(name):
    v = np.zeros(2)
    for part in name.split("-"):
        v += DIRS[part]
    return v / np.linalg.norm(v)


def smoothstep(t):
    t = np.clip(t, 0, 1)
    return t * t * (3 - 2 * t)


def fill_outline(rgb, dark, keep_mask, iterations=24):
    """Replace dark outline pixels with the color of nearby fill (normalized convolution)."""
    out = rgb.copy()
    valid = (~dark & keep_mask).astype(np.float32)
    for _ in range(iterations):
        num = nd.uniform_filter(out * valid[..., None], size=(5, 5, 1))
        den = nd.uniform_filter(valid, size=5)
        grow = (valid == 0) & (den > 1e-3) & keep_mask
        if not grow.any():
            break
        out[grow] = num[grow] / den[grow][..., None]
        valid = np.where(grow, 1.0, valid)
    return out


def feather(img, ends, fade=0.07, min_px=12, max_px=60):
    a = np.asarray(img.convert("RGBA")).astype(np.float32) / 255.0
    rgb, alpha = a[..., :3], a[..., 3]
    H, W = alpha.shape
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    opaque = alpha > 0.5
    lum = rgb @ np.array([0.299, 0.587, 0.114], np.float32)
    dark = lum < 0.16                          # black outline and interior ink lines
    blend_total = np.zeros((H, W), np.float32)  # 0 = untouched, 1 = fully at the joint end
    for end in ends:
        d = direction(end)
        proj = xx * d[0] + yy * d[1]
        pmax, pmin = proj[opaque].max(), proj[opaque].min()
        length = np.clip((pmax - pmin) * fade, min_px, max_px)
        t = (proj - (pmax - length)) / length    # 0 at start of fade zone, 1 at the extreme end
        blend_total = np.maximum(blend_total, smoothstep(t))
    zone = blend_total > 0
    if not zone.any():
        return img
    filled = fill_outline(rgb, dark, alpha > 0.02)
    k = np.clip(blend_total * 1.6, 0, 1)[..., None]  # outline gone before the alpha is
    rgb2 = rgb * (1 - k) + filled * k
    alpha2 = alpha * (1 - blend_total * 0.98)
    alpha2 = np.where(blend_total >= 0.999, 0, alpha2)
    out = np.concatenate([rgb2, alpha2[..., None]], -1)
    return Image.fromarray((np.clip(out, 0, 1) * 255).round().astype(np.uint8), "RGBA")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("input"); p.add_argument("output")
    p.add_argument("--batch", action="store_true", help="input/output are folders")
    p.add_argument("--joints", help="JSON file mapping file names to joint ends")
    p.add_argument("--fade", type=float, default=0.07, help="fade length as a share of the part's length (default 0.07)")
    p.add_argument("--ends", help="single-file mode: comma-separated ends, e.g. top or bottom-left")
    a = p.parse_args()
    joints = json.load(open(a.joints)) if a.joints else JOINTS
    if a.batch:
        for dp, _, fs in os.walk(a.input):
            for f in sorted(fs):
                if not f.lower().endswith(".png"):
                    continue
                rel = os.path.relpath(os.path.join(dp, f), a.input).replace(os.sep, "/")
                dst = os.path.join(a.output, rel); os.makedirs(os.path.dirname(dst), exist_ok=True)
                im = Image.open(os.path.join(dp, f))
                (feather(im, joints[rel], a.fade) if rel in joints else im.convert("RGBA")).save(dst, optimize=True)
                print(("feathered " + ",".join(joints[rel]) if rel in joints else "unchanged"), rel)
    else:
        ends = a.ends.split(",") if a.ends else joints.get(os.path.basename(a.input), [])
        feather(Image.open(a.input), ends, a.fade).save(a.output, optimize=True)
