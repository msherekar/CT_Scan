"""Triple MPR viewer for CBCT DICOM studies.
Shows synchronized axial, coronal, sagittal slices with keyboard controls."""

from __future__ import annotations

import argparse
from pathlib import Path
import matplotlib.pyplot as plt, numpy as np, pydicom

DEFAULT_DICOM_DIR = Path("./DICOM/48778133/63925984")


def load_volume(folder: Path) -> np.ndarray:
    pairs = []
    for p in sorted([x for x in folder.rglob("*") if x.is_file()]):
        try:
            ds = pydicom.dcmread(str(p), force=True)
            arr = ds.pixel_array.astype(np.float32)
            hu = arr * float(getattr(ds, "RescaleSlope", 1.0)) + float(getattr(ds, "RescaleIntercept", 0.0))
            idx = int(getattr(ds, "InstanceNumber", len(pairs)))
            pairs.append((idx, hu))
        except Exception:
            continue
    if not pairs:
        raise ValueError(f"No readable DICOM slices in {folder}")
    pairs.sort(key=lambda x: x[0])
    return np.stack([p[1] for p in pairs], axis=0)  # (z, y, x)


def window_img(img: np.ndarray, ww: float, wl: float) -> np.ndarray:
    lo, hi = wl - ww / 2.0, wl + ww / 2.0
    return np.clip((img - lo) / max(hi - lo, 1e-6), 0.0, 1.0)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Triple MPR viewer (axial/coronal/sagittal)")
    parser.add_argument("--dicom-dir", default=str(DEFAULT_DICOM_DIR))
    parser.add_argument("--ww", type=float, default=2200.0)
    parser.add_argument("--wl", type=float, default=1200.0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    vol = load_volume(Path(args.dicom_dir))
    z, y, x = vol.shape
    zi, yi, xi = z // 2, y // 2, x // 2
    fig, axes = plt.subplots(1, 3, figsize=(14, 5))

    def draw() -> None:
        axes[0].clear()
        axes[1].clear()
        axes[2].clear()
        axial = window_img(vol[zi, :, :], args.ww, args.wl)
        coronal = window_img(vol[:, yi, :], args.ww, args.wl)
        sagittal = window_img(vol[:, :, xi], args.ww, args.wl)
        axes[0].imshow(axial, cmap="gray", origin="lower")
        axes[1].imshow(coronal, cmap="gray", origin="lower")
        axes[2].imshow(sagittal, cmap="gray", origin="lower")
        axes[0].set_title(f"Axial z={zi+1}/{z}")
        axes[1].set_title(f"Coronal y={yi+1}/{y}")
        axes[2].set_title(f"Sagittal x={xi+1}/{x}")
        for ax in axes:
            ax.axis("off")
        fig.suptitle("Z/X: axial | C/V: coronal | B/N: sagittal | [/]: WL | -/=: WW")
        fig.canvas.draw_idle()

    def on_key(event) -> None:  # type: ignore[no-untyped-def]
        nonlocal zi, yi, xi
        if event.key == "x":
            zi = min(zi + 1, z - 1)
        elif event.key == "z":
            zi = max(zi - 1, 0)
        elif event.key == "v":
            yi = min(yi + 1, y - 1)
        elif event.key == "c":
            yi = max(yi - 1, 0)
        elif event.key == "n":
            xi = min(xi + 1, x - 1)
        elif event.key == "b":
            xi = max(xi - 1, 0)
        elif event.key == "]":
            args.wl += 20
        elif event.key == "[":
            args.wl -= 20
        elif event.key == "=":
            args.ww += 50
        elif event.key == "-":
            args.ww = max(50, args.ww - 50)
        draw()

    fig.canvas.mpl_connect("key_press_event", on_key)
    draw()
    plt.show()


if __name__ == "__main__":
    main()
