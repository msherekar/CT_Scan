#!/usr/bin/env python3
"""
Dental CBCT 3-D viewer — Prexion LUT presets
=============================================
Renders the DICOM volume with transfer functions parsed directly from the
Prexion LUTTemplate XML files, reproducing the exact colour and opacity
appearance of the Prexion viewer.

Usage examples
--------------
  python3 src/visualize_cbct_3d.py
  python3 src/visualize_cbct_3d.py --preset "CT 3D Bone"
  python3 src/visualize_cbct_3d.py --preset "3D Face" --show-slices
  python3 src/visualize_cbct_3d.py --list-presets
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pydicom
import pyvista as pv
import vtk

# ── local ─────────────────────────────────────────────────────────────────────
_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
from lut_parser import LUTPreset, load_all_presets, build_vtk_tfns, print_preset_table

DEFAULT_DICOM = str(_HERE.parent / "DICOM" / "48778133" / "63925984")
DEFAULT_PRESET = "CT 3D Bone"


# ── DICOM loader ──────────────────────────────────────────────────────────────

def load_dicom_volume(
    folder: Path,
) -> tuple[np.ndarray, tuple[float, float, float]]:
    """
    Load sorted DICOM series → float32 array (nx, ny, nz) and spacing (sx, sy, sz).
    Axis order (nx, ny, nz) matches PyVista ImageData dimensions convention.
    """
    slices: list[tuple[int, np.ndarray, tuple]] = []
    for path in sorted(folder.rglob("*.dcm")):
        try:
            ds      = pydicom.dcmread(str(path), force=True)
            arr     = ds.pixel_array.astype(np.float32)
            slope   = float(getattr(ds, "RescaleSlope",     1.0))
            intercept = float(getattr(ds, "RescaleIntercept", 0.0))
            hu      = arr * slope + intercept
            idx     = int(getattr(ds, "InstanceNumber", len(slices)))
            px      = getattr(ds, "PixelSpacing", [1.0, 1.0])
            thick   = float(getattr(ds, "SliceThickness", 1.0))
            slices.append((idx, hu, (float(px[1]), float(px[0]), thick)))
        except Exception:
            continue

    if not slices:
        raise ValueError(f"No readable DICOM slices in {folder}")

    slices.sort(key=lambda s: s[0])
    volume  = np.stack([s[1] for s in slices], axis=-1)   # (nx, ny, nz)
    spacing = slices[0][2]                                 # (sx, sy, sz)
    return volume, spacing


# ── volume build ──────────────────────────────────────────────────────────────

def build_image_data(
    volume: np.ndarray,
    spacing: tuple[float, float, float],
) -> pv.ImageData:
    grid            = pv.ImageData()
    grid.dimensions = np.array(volume.shape)
    grid.spacing    = spacing
    grid.origin     = (0.0, 0.0, 0.0)
    grid.point_data["HU"] = volume.ravel(order="F")
    return grid


# ── rendering ─────────────────────────────────────────────────────────────────

def render(
    grid:        pv.ImageData,
    preset:      LUTPreset,
    show_slices: bool,
    window_size: tuple[int, int] = (1024, 800),
) -> None:
    ctf, otf = build_vtk_tfns(preset)

    # ── PyVista plotter ────────────────────────────────────────────────────────
    pl = pv.Plotter(title=f"Dental CBCT 3D  ·  {preset.name}", window_size=list(window_size))
    pl.set_background(list(preset.bg_rgb))

    # ── VTK volume mapper ──────────────────────────────────────────────────────
    mapper = vtk.vtkGPUVolumeRayCastMapper()
    mapper.SetInputData(grid)
    mapper.SetBlendModeToComposite()
    mapper.SetAutoAdjustSampleDistances(True)

    # ── Volume property from LUT ───────────────────────────────────────────────
    vprop = vtk.vtkVolumeProperty()
    vprop.SetColor(ctf)
    vprop.SetScalarOpacity(otf)
    vprop.SetInterpolationTypeToLinear()
    vprop.ShadeOn()
    vprop.SetAmbient(preset.ambient)
    vprop.SetDiffuse(preset.diffuse)
    vprop.SetSpecular(preset.specular)
    # Prexion shininess [0,1] → VTK SpecularPower [1,128]
    vprop.SetSpecularPower(max(1.0, preset.shininess * 128.0))

    # ── Assemble and add volume ────────────────────────────────────────────────
    vol = vtk.vtkVolume()
    vol.SetMapper(mapper)
    vol.SetProperty(vprop)
    pl.renderer.AddVolume(vol)

    # ── Optional orthogonal slice planes ──────────────────────────────────────
    if show_slices:
        dims = grid.dimensions
        cx   = grid.origin[0] + dims[0] * grid.spacing[0] / 2
        cy   = grid.origin[1] + dims[1] * grid.spacing[1] / 2
        cz   = grid.origin[2] + dims[2] * grid.spacing[2] / 2

        # Use Img3D W/L from the preset for slice display
        img_clim = (
            preset.img3d_wl - preset.img3d_ww / 2,
            preset.img3d_wl + preset.img3d_ww / 2,
        )
        for normal, origin in [
            ([1, 0, 0], [cx, cy, cz]),
            ([0, 1, 0], [cx, cy, cz]),
            ([0, 0, 1], [cx, cy, cz]),
        ]:
            sl = grid.slice(normal=normal, origin=origin)
            pl.add_mesh(sl, scalars="HU", cmap="gray",
                        clim=img_clim, opacity=0.7,
                        show_scalar_bar=False)

    # ── UI text ────────────────────────────────────────────────────────────────
    active_layers = [l for l in preset.layers if l.active]
    layer_info = "  ".join(
        f"L{i+1} HU[{l.wl-l.ww/2:.0f},{l.wl+l.ww/2:.0f}] α={l.opacity}"
        for i, l in enumerate(active_layers)
    )
    pl.add_text(
        f"Preset: {preset.name}\n"
        f"Active layers: {len(active_layers)}\n"
        f"{layer_info}\n"
        f"Drag=rotate  Scroll=zoom  Shift+drag=pan",
        position="lower_left",
        font_size=8,
        color="white" if sum(preset.bg_rgb) < 1.5 else "black",
    )

    pl.add_axes()
    pl.reset_camera()
    pl.show()


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    # Load presets first so we can build --preset choices
    presets = load_all_presets()
    preset_names = sorted(presets.keys())

    parser = argparse.ArgumentParser(
        description="Dental CBCT 3-D viewer with Prexion LUT presets"
    )
    parser.add_argument(
        "--dicom-dir", default=DEFAULT_DICOM,
        help="Path to DICOM series folder",
    )
    parser.add_argument(
        "--preset", default=DEFAULT_PRESET,
        metavar="NAME",
        help=(
            f"Prexion LUT preset name (default: '{DEFAULT_PRESET}'). "
            f"Use --list-presets to see all options."
        ),
    )
    parser.add_argument(
        "--show-slices", action="store_true",
        help="Overlay orthogonal MPR slice planes at volume centre",
    )
    parser.add_argument(
        "--list-presets", action="store_true",
        help="Print all available Prexion presets and exit",
    )
    args = parser.parse_args()

    if args.list_presets:
        print_preset_table(presets)
        return

    # Resolve preset (case-insensitive, partial match supported)
    preset_key = args.preset
    if preset_key not in presets:
        # Try case-insensitive exact match
        lower_map = {k.lower(): k for k in presets}
        if preset_key.lower() in lower_map:
            preset_key = lower_map[preset_key.lower()]
        else:
            # Partial match
            matches = [k for k in presets if preset_key.lower() in k.lower()]
            if len(matches) == 1:
                preset_key = matches[0]
            elif len(matches) > 1:
                print(f"Ambiguous preset '{args.preset}'. Matches: {matches}")
                print(f"Using '{matches[0]}'.")
                preset_key = matches[0]
            else:
                print(f"Unknown preset '{args.preset}'. Available presets:")
                print_preset_table(presets)
                sys.exit(1)

    preset = presets[preset_key]
    print(f"Preset : {preset.name}  ({preset.group})")
    print(f"Img2D  : WW={preset.img2d_ww:.0f}  WL={preset.img2d_wl:.0f}")
    print(f"Img3D  : WW={preset.img3d_ww:.0f}  WL={preset.img3d_wl:.0f}")
    active = [l for l in preset.layers if l.active]
    for i, l in enumerate(active):
        lo, hi = l.wl - l.ww/2, l.wl + l.ww/2
        print(f"  Layer {i+1}: CurveID={l.curve_id}  "
              f"HU [{lo:.0f}, {hi:.0f}]  opacity={l.opacity}")

    print("\nLoading DICOM …", flush=True)
    volume, spacing = load_dicom_volume(Path(args.dicom_dir))
    print(f"  {volume.shape[0]}×{volume.shape[1]}×{volume.shape[2]} voxels  "
          f"spacing {spacing[0]:.3f}×{spacing[1]:.3f}×{spacing[2]:.3f} mm")

    grid = build_image_data(volume, spacing)
    render(grid, preset, args.show_slices)


if __name__ == "__main__":
    main()
