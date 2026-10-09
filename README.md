# Legacy Awaken

Storm-style old film look for Blazing legacy units: film grain, dust specks, a light sepia fade, and thin black and white scratch lines that flick across the box art. It comes in two pieces:

- **The app (`index.html`)**: open it in a browser, drop in a box or portrait, tune the look with sliders, and export a video or PNG.
- **The batch script (`storm_film.py`)**: apply the same look to a whole folder of images from the command line.

The usual flow is to dial in a look in the app, copy its settings into the script as a preset, and batch the rest of your units with it.

---

## The app

### Opening it

- **Simplest:** download `index.html` and open it in Chrome, Edge or Firefox. Nothing to install, and it works offline (only the fonts need internet).
- **Hosted:** if this repo has GitHub Pages turned on (Settings → Pages → Deploy from branch → `main` / root), everyone with access can open it at the Pages link. GitHub Pages on a private repo needs a paid GitHub plan.

### Using it

1. **Load an image** with *Open image*, by dragging a file onto the preview, or by pasting (Ctrl+V / ⌘V). It opens with a sample box so you can see the effect immediately.
2. **Pick a preset**:

   | Preset | Use it for |
   | --- | --- |
   | Legacy Bright | Default for legacy unit boxes: colors stay vivid, light grain, soft lines |
   | Legacy Soft | Same, with a warmer, more faded tone |
   | Grain only | Just grain, no lines or dust |
   | Storm flashback | The heavier sepia flashback look from Ultimate Ninja Storm scenes |
   | Old reel (heavy) | Strong damage, for special or "lost memory" units |

3. **Adjust the sliders.** Any change switches the preset to *Custom*, and your settings are remembered in that browser.
4. **Check the timeline** under the preview. It has one cell per frame of the loop: dark cells are black lines, light cells are white lines, and the letter shows which zone the line is in (L, M, R). Click a cell to stop on that frame. Press and hold *Hold for original* to compare against the unfiltered image.
5. **Export:**
   - *Render video* records the loop in real time (4 loops ≈ 8 seconds), shows you the result, then *Save video* downloads it. The format is MP4 where the browser supports recording it (current Chrome and Edge), otherwise WebM.
   - *Save this frame (PNG)* downloads the current frame.

### What the controls do

| Group | Control | Effect |
| --- | --- | --- |
| Color | Sepia tone, Desaturate | How brown and how grey the image gets |
| | Fade | Lifts blacks and dulls whites like an aged print. This is what makes art look "greyed out" |
| | Brightness, Edge darkening | Overall exposure and vignette |
| Grain | Grain amount, Grain size | Noise strength and particle size (size is in pixels of the original image) |
| | Exposure flicker | Small brightness change every frame |
| Scratch lines | Line zones | The box is split into this many side-by-side zones and each zone gets its own line, so lines spread across the whole box |
| | Passes per loop | How many times every zone fires per loop |
| | Line duration | Frames each line stays on screen |
| | Black vs white | Share of lines that are black |
| | Black / White line strength | Opacity of each color |
| | Line softness | Feathering; 0 is a razor-sharp 1px line |
| Dust | Specks per frame, Speck size | Random dust marks, new every frame |
| Motion | Frame rate, Loop length | Speed and length of the loop |
| | Projector wobble | Shakes the whole image by a few pixels. Keep at 0 for box art so the art stays still |
| | Random seed | Different line positions and dust; *Shuffle* picks a new one |
| Output | Render size | 4× gives hairline scratches; 1× keeps the original size |
| | Apply to | *Box only* skips a gray-and-white checkerboard background baked into a screenshot; transparent PNGs keep their transparency either way |

---

## The batch script

### Setup

Python 3.9 or newer, plus ffmpeg on your PATH for MP4 or WebM output.

```bash
pip install -r requirements.txt
```

### Common commands

```bash
# One box, animated, art held still, hairline lines, checkerboard left alone
python storm_film.py box.png box_legacy.mp4 --preset icon_bright --frames 36 --weave 0 --render-scale 4 --mask auto

# A whole folder of boxes as animated GIFs
python storm_film.py --batch boxes/ boxes_legacy/ --preset icon_bright --frames 36 --weave 0 --render-scale 4 --mask auto

# A still PNG
python storm_film.py box.png box_legacy.png --preset icon_bright --mask auto

# A transparent portrait, keeping transparency (WebM supports alpha)
python storm_film.py portrait.png portrait_legacy.webm --preset icon_bright --frames 36 --weave 0
```

### Options

| Option | Meaning |
| --- | --- |
| `--preset` | `icon_bright`, `icon_soft`, `icon_grain` for unit boxes; `light`, `medium`, `heavy` for full scenes |
| `--frames N` | Make an animation of N frames. The output extension picks the format: `.mp4`, `.webm` or `.gif` |
| `--fps N` | Frame rate (default 18) |
| `--render-scale N` | Enlarge before applying the effect, so lines stay 1 px thin at the output size (4 recommended for boxes) |
| `--weave N` | Projector wobble in pixels; `0` keeps the art still |
| `--mask auto` | Skip a baked-in checkerboard background. You can also pass a grayscale mask image (white = effect) |
| `--scale N` | Enlarge after the effect, nearest-neighbor (chunky preview only) |
| `--seed N` | Change line positions and dust |
| `--batch` | Treat input and output as folders |

`icon_bright` and `icon_soft` match *Legacy Bright* and *Legacy Soft* in the app.

### Using your app settings in the script

In the app, open **Use in batch script** at the bottom of the controls and press **Copy preset and command**. Paste the `"legacy_custom": dict(...)` line into the `PRESETS` dictionary near the top of `storm_film.py`, then run the command it gives you. The app and the script use different random number generators, so line positions and dust differ between them, but the look is the same.

---

## Files

```
index.html           Legacy Awaken app (single file, no build step)
storm_film.py        Batch script
requirements.txt     Python packages for the script
examples/sample_box.png   Sample box used to test both
```
