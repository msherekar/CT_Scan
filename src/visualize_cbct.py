"""Visualize CBCT DICOM slices with LUT presets from parsed template JSON.
Loads a DICOM series, applies WW/WL from selected preset, and supports key controls."""

from __future__ import annotations

import argparse, json
from pathlib import Path
import matplotlib.pyplot as plt, numpy as np, pydicom

DEFAULT_DICOM_DIR = Path("./DICOM/48778133/63925984")
DEFAULT_LUT_JSON = Path("./output/lut_templates.json")
KEY_HELP = "Arrows/N/P: slices | ]/[ : preset | H: help"


def load_lut_presets(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    presets = data.get("templates", [])
    default = data.get("default", {})
    tab, item = default.get("TAB_NAME", ""), default.get("ITEM_NAME", "")
    for p in presets:
        p["is_default"] = p.get("section") == tab and p.get("preset_name") == item
    return presets


def load_dicom_stack(folder: Path) -> list[np.ndarray]:
    slices = []
    for file_path in sorted([p for p in folder.rglob("*") if p.is_file()]):
        try:
            ds = pydicom.dcmread(str(file_path), force=True)
            pixels = ds.pixel_array.astype(np.float32)
            idx = int(getattr(ds, "InstanceNumber", len(slices)))
            slices.append((idx, pixels))
        except Exception:
            continue
    if not slices:
        raise ValueError(f"No readable DICOM slices found in {folder}")
    slices.sort(key=lambda x: x[0])
    return [s[1] for s in slices]


def apply_window(image: np.ndarray, ww: float, wl: float) -> np.ndarray:
    lo, hi = wl - ww / 2.0, wl + ww / 2.0
    clipped = np.clip(image, lo, hi)
    return (clipped - lo) / max(hi - lo, 1e-6)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Visualize DICOM series using LUT presets")
    parser.add_argument("--dicom-dir", default=str(DEFAULT_DICOM_DIR))
    parser.add_argument("--lut-json", default=str(DEFAULT_LUT_JSON))
    parser.add_argument("--preset", default=None, help="Optional preset name")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    presets, stack = load_lut_presets(Path(args.lut_json)), load_dicom_stack(Path(args.dicom_dir))
    if not presets:
        raise ValueError("No presets found in LUT JSON")
    default_i = next((i for i, p in enumerate(presets) if p.get("is_default")), 0)
    preset_i = next((i for i, p in enumerate(presets) if p.get("preset_name") == args.preset), default_i)
    slice_i = len(stack) // 2
    fig, ax = plt.subplots(figsize=(7, 7))

    def render() -> None:
        nonlocal slice_i, preset_i
        p = presets[preset_i]
        ww = float(p.get("img2d_ww") or p.get("img3d_ww") or 2000)
        wl = float(p.get("img2d_wl") or p.get("img3d_wl") or 1000)
        shown = apply_window(stack[slice_i], ww, wl)
        ax.clear()
        ax.imshow(shown, cmap="gray", origin="lower")
        ax.set_title(f"{p.get('preset_name')} | Slice {slice_i + 1}/{len(stack)} | WW={ww:.0f} WL={wl:.0f}")
        ax.set_xlabel(KEY_HELP)
        ax.axis("off")
        fig.canvas.draw_idle()

    def on_key(event) -> None:  # type: ignore[no-untyped-def]
        nonlocal slice_i, preset_i
        if event.key in {"right", "down", "n"}:
            slice_i = min(slice_i + 1, len(stack) - 1)
        elif event.key in {"left", "up", "p"}:
            slice_i = max(slice_i - 1, 0)
        elif event.key == "]":
            preset_i = (preset_i + 1) % len(presets)
        elif event.key == "[":
            preset_i = (preset_i - 1) % len(presets)
        elif event.key in {"h", "H"}:
            print(KEY_HELP)
        render()

    fig.canvas.mpl_connect("key_press_event", on_key)
    render()
    plt.show()


if __name__ == "__main__":
    main()
