#!/usr/bin/env python3
"""
Prexion LUTTemplate parser
==========================
Reads the XML files in LUTTemplate/Standard/ and LUTTemplate/Other/ and
converts them into VTK vtkColorTransferFunction + vtkPiecewiseFunction pairs
that replicate Prexion's exact volume-rendering appearance.

XML anatomy
-----------
<LUTTemplate Name="CT 3D Bone">
  <Obj Active="1"  CurveID="3"  WW="630"  WL="1435"
       LColor="16777215"  HColor="16777215"  Opacity="1"/>
  ...
  <Light Specular="0"  Shininess="0"  Intensity="1"
         BG_R="0"  BG_G="0"  BG_B="0"/>
  <Img3D WW="2400"  WL="1600"/>
  <Img2D WW="3000"  WL="1200"/>
</LUTTemplate>

CurveID semantics (reverse-engineered)
---------------------------------------
  0  Wide sigmoid / ramp   → 30 % of WW used for opacity rise/fall
  1  Medium ramp           → 15 %
  3  Narrow sharp peak     → 5 %   (dense bone, enamel)
  5  Near-step             → 1 %   (titanium implants at HU ~3060)

Color encoding
--------------
LColor / HColor are 24-bit packed RGB integers (big-endian, no alpha):
  R = (c >> 16) & 0xFF
  G = (c >>  8) & 0xFF
  B =  c        & 0xFF
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

import vtk

# ── paths ─────────────────────────────────────────────────────────────────────
_LUT_ROOT = Path(__file__).resolve().parent.parent / "LUTTemplate"

# Fraction of WW used for opacity ramp per CurveID
_RAMP_FRAC: dict[int, float] = {0: 0.30, 1: 0.15, 3: 0.05, 5: 0.01}


# ── data types ────────────────────────────────────────────────────────────────

@dataclass
class LUTLayer:
    active:   bool
    curve_id: int
    ww:       float                          # HU window width
    wl:       float                          # HU window centre
    lcolor:   tuple[float, float, float]     # normalised RGB at low end
    hcolor:   tuple[float, float, float]     # normalised RGB at high end
    opacity:  float                          # peak alpha


@dataclass
class LUTPreset:
    """One complete Prexion volume-rendering preset."""
    name:      str
    layers:    list[LUTLayer] = field(default_factory=list)

    # 2-D MPR window (used to drive dental_viewer.py's W/L sliders)
    img2d_ww:  float = 3000.0
    img2d_wl:  float = 1200.0

    # 3-D volume window (informational; transfer functions encode this directly)
    img3d_ww:  float = 2400.0
    img3d_wl:  float = 1600.0

    # Lighting
    ambient:   float = 0.20
    diffuse:   float = 0.90
    specular:  float = 0.00
    shininess: float = 0.00          # mapped to VTK SpecularPower × 50

    # Background colour (normalised RGB)
    bg_rgb:    tuple[float, float, float] = (0.0, 0.0, 0.0)

    # Display group ("Standard" / "Other")
    group:     str = "Standard"


# ── helpers ───────────────────────────────────────────────────────────────────

def _rgb(c: int) -> tuple[float, float, float]:
    """24-bit packed RGB → normalised (r, g, b)."""
    return ((c >> 16) & 0xFF) / 255.0, ((c >> 8) & 0xFF) / 255.0, (c & 0xFF) / 255.0


def _parse_xml(path: Path, group: str) -> LUTPreset | None:
    try:
        root = ET.parse(str(path)).getroot()
        lut  = root.find("LUTTemplate")
        if lut is None:
            return None

        preset = LUTPreset(name=path.stem, group=group)

        for obj in lut.findall("Obj"):
            preset.layers.append(LUTLayer(
                active   = obj.get("Active",  "0") == "1",
                curve_id = int(  obj.get("CurveID", "0")),
                ww       = float(obj.get("WW",      "1000")),
                wl       = float(obj.get("WL",      "500")),
                lcolor   = _rgb(int(obj.get("LColor", "16777215"))),
                hcolor   = _rgb(int(obj.get("HColor", "16777215"))),
                opacity  = float(obj.get("Opacity", "0.5")),
            ))

        if (n := lut.find("Img3D")) is not None:
            preset.img3d_ww = float(n.get("WW", 2400))
            preset.img3d_wl = float(n.get("WL", 1600))

        if (n := lut.find("Img2D")) is not None:
            preset.img2d_ww = float(n.get("WW", 3000))
            preset.img2d_wl = float(n.get("WL", 1200))

        if (n := lut.find("Light")) is not None:
            preset.specular  = float(n.get("Specular",  0.0))
            preset.shininess = float(n.get("Shininess", 0.0))
            preset.bg_rgb = (
                float(n.get("BG_R", 0)) / 255.0,
                float(n.get("BG_G", 0)) / 255.0,
                float(n.get("BG_B", 0)) / 255.0,
            )

        return preset

    except Exception as exc:
        print(f"[lut_parser] Warning: skipping {path.name}: {exc}")
        return None


# ── public API ────────────────────────────────────────────────────────────────

def load_all_presets(lut_root: Path = _LUT_ROOT) -> dict[str, LUTPreset]:
    """
    Load every XML in LUTTemplate/Standard/ and LUTTemplate/Other/.
    Returns a dict keyed by filename stem (e.g. "CT 3D Bone", "CT Standard 1").
    """
    result: dict[str, LUTPreset] = {}
    for group in ("Standard", "Other"):
        folder = lut_root / group
        if not folder.exists():
            continue
        for xml_path in sorted(folder.glob("*.xml")):
            p = _parse_xml(xml_path, group)
            if p:
                result[p.name] = p
    return result


def build_vtk_tfns(
    preset: LUTPreset,
) -> tuple[vtk.vtkColorTransferFunction, vtk.vtkPiecewiseFunction]:
    """
    Convert a LUTPreset → (color_transfer_fn, opacity_transfer_fn).

    Each active layer contributes:
      • A colour gradient (LColor → HColor) across its HU window [lo, hi]
      • A trapezoid opacity curve at peak Opacity, with ramp steepness
        determined by CurveID (narrow for dense bone, wide for soft tissue)
    """
    ctf = vtk.vtkColorTransferFunction()
    otf = vtk.vtkPiecewiseFunction()

    # Transparent sentinel below air
    ctf.AddRGBPoint(-1100, 0.0, 0.0, 0.0)
    otf.AddPoint(-1100, 0.0)

    active = [l for l in preset.layers if l.active and l.opacity > 0.0]

    for layer in active:
        lo   = layer.wl - layer.ww / 2.0
        hi   = layer.wl + layer.ww / 2.0
        peak = layer.opacity
        ramp = _RAMP_FRAC.get(layer.curve_id, 0.20)

        # Color: linear gradient from lcolor at lo to hcolor at hi
        ctf.AddRGBPoint(lo, *layer.lcolor)
        ctf.AddRGBPoint(hi, *layer.hcolor)

        # Opacity: trapezoid (or triangle for very narrow windows)
        rise = lo + layer.ww * ramp
        fall = hi - layer.ww * ramp
        if rise >= fall:
            # CurveID=5 or tiny WW — use a triangle centred at wl
            otf.AddPoint(lo,       0.0)
            otf.AddPoint(layer.wl, peak)
            otf.AddPoint(hi,       0.0)
        else:
            otf.AddPoint(lo,   0.0)
            otf.AddPoint(rise, peak)
            otf.AddPoint(fall, peak)
            otf.AddPoint(hi,   0.0)

    # Transparent sentinel above max HU
    ctf.AddRGBPoint(5000, 1.0, 1.0, 1.0)
    otf.AddPoint(5000, 0.0)

    return ctf, otf


def print_preset_table(presets: dict[str, LUTPreset]) -> None:
    """Pretty-print a summary of all loaded presets."""
    print(f"\n{'Name':<26} {'Grp':<9} {'ActLayers':>9}  "
          f"{'Img2D WW/WL':>14}  {'Img3D WW/WL':>14}")
    print("-" * 80)
    for name, p in sorted(presets.items()):
        n_active = sum(1 for l in p.layers if l.active)
        print(
            f"{name:<26} {p.group:<9} {n_active:>9}  "
            f"{p.img2d_ww:>6.0f}/{p.img2d_wl:<6.0f}  "
            f"{p.img3d_ww:>6.0f}/{p.img3d_wl:<6.0f}"
        )
    print()


# ── CLI self-test ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    presets = load_all_presets()
    print(f"Loaded {len(presets)} Prexion LUT presets.")
    print_preset_table(presets)

    # Verify VTK transfer functions build without errors
    for name, preset in presets.items():
        ctf, otf = build_vtk_tfns(preset)
        n_ctf = ctf.GetSize()
        n_otf = otf.GetSize()
        print(f"  {name:<26}  CTF nodes={n_ctf:>3}  OTF nodes={n_otf:>3}")
