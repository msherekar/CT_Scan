#!/usr/bin/env python3
"""
Dental CBCT Viewer  ·  4-panel MPR + MIP overview
===================================================
Panels:
  Top-left    : Axial   (superior → inferior)
  Top-right   : Coronal (anterior → posterior)
  Bot-left    : Sagittal (left → right)
  Bot-right   : Coronal MIP (max-intensity projection — full-volume overview)

Controls  ─────────────────────────────────────────────────────────────
  Scroll wheel (in any image panel)
      → navigate slices for that plane
  Left-click (in any MPR panel)
      → place crosshair, sync all three planes
  Right-drag (in any MPR panel)
      → W/L adjustment  (horizontal = WW,  vertical = WL)
  Keyboard shortcuts:
      X / Z     → axial slice  ±1
      V / C     → coronal slice ±1
      N / B     → sagittal slice ±1
      1-5       → presets: 1=Enamel  2=Dentin  3=Bone  4=Soft  5=Full
      T         → launch 3-D PyVista window
      R         → reset all views

Toolbar buttons:
      Enamel / Dentin / Bone / Soft / Full  → 2-D Window-Level presets
      Launch 3D  → opens visualize_cbct_3d.py in a separate process
      Reset      → return to midpoint slices + Enamel preset
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import numpy as np
import pydicom
import matplotlib
import matplotlib.pyplot as plt
import matplotlib.widgets as mwidgets
from matplotlib.gridspec import GridSpec

# ── paths ─────────────────────────────────────────────────────────────────────
_HERE        = Path(__file__).resolve().parent
DEFAULT_DICOM = str(_HERE.parent / "DICOM" / "48778133" / "63925984")
_3D_SCRIPT   = str(_HERE / "visualize_cbct_3d.py")

# ── Prexion LUT presets ───────────────────────────────────────────────────────
sys.path.insert(0, str(_HERE))
try:
    from lut_parser import load_all_presets as _load_luts
    _LUT_PRESETS = _load_luts()
except Exception as _e:
    print(f"[dental_viewer] LUT presets unavailable: {_e}")
    _LUT_PRESETS = {}

# Ordered subset shown in the toolbar (most clinically relevant first)
_TOOLBAR_3D = [
    "CT 3D Bone",       # pure bone/enamel — best for cracks
    "3D Face",          # bone + soft tissue
    "3D General",       # general purpose
    "3D Perio",         # periodontal bone levels
    "CT MIP",           # max-intensity projection style
    "EmbImp1",          # for implant patients
]
# Keep only presets that actually loaded
_TOOLBAR_3D = [n for n in _TOOLBAR_3D if n in _LUT_PRESETS]

# ── Window / Level presets ────────────────────────────────────────────────────
WL_PRESETS: dict[str, tuple[float, float]] = {
    "Enamel":  (1000, 2500),   # narrow, high HU → best for hairline cracks
    "Dentin":  (1200, 1400),
    "Bone":    (2000,  600),
    "Soft":    ( 400,   40),
    "Full":    (4000, 1000),
}

# ── colors ────────────────────────────────────────────────────────────────────
BG       = "#111827"
BG_AX    = "#0f172a"
FG       = "#f3f4f6"
PANEL_C  = {"Axial": "#22c55e", "Coronal": "#f59e0b",
            "Sagittal": "#ec4899", "MIP": "#a78bfa"}
CROSS    = "yellow"


# ═══════════════════════════════════════════════════════════════════════════════
def _load_volume(folder: str) -> tuple[np.ndarray, tuple[float, float, float]]:
    """Load DICOM → float32 array (nz, ny, nx) and spacing (sz, sy, sx)."""
    folder = Path(folder)
    pairs: list[tuple[int, np.ndarray, tuple]] = []
    for f in sorted(folder.glob("*.dcm")):
        try:
            ds  = pydicom.dcmread(str(f), force=True)
            arr = ds.pixel_array.astype(np.float32)
            hu  = arr * float(getattr(ds, "RescaleSlope", 1.0)) \
                      + float(getattr(ds, "RescaleIntercept", 0.0))
            idx = int(getattr(ds, "InstanceNumber", len(pairs)))
            px  = getattr(ds, "PixelSpacing", [1.0, 1.0])
            th  = float(getattr(ds, "SliceThickness", 1.0))
            pairs.append((idx, hu, (th, float(px[0]), float(px[1]))))
        except Exception:
            continue
    if not pairs:
        raise ValueError(f"No readable DICOM slices in {folder}")
    pairs.sort(key=lambda p: p[0])
    vol     = np.stack([p[1] for p in pairs], axis=0)   # (nz, ny, nx)
    spacing = pairs[0][2]                                # (sz, sy, sx)
    return vol, spacing


def _win(img: np.ndarray, ww: float, wl: float) -> np.ndarray:
    lo, hi = wl - ww / 2.0, wl + ww / 2.0
    return np.clip((img - lo) / max(hi - lo, 1e-6), 0.0, 1.0)


# ═══════════════════════════════════════════════════════════════════════════════
class DentalViewer:
    """4-panel CBCT viewer: Axial / Coronal / Sagittal MPR + coronal MIP."""

    def __init__(self, dicom_dir: str):
        self._dicom_dir = dicom_dir
        self.ww, self.wl = WL_PRESETS["Enamel"]
        self._drag: tuple | None = None   # (start_x, start_y, ww0, wl0)

        # ── load ──────────────────────────────────────────────────────────────
        print("Loading DICOM …", flush=True)
        self.vol, self.spacing = _load_volume(dicom_dir)
        self.nz, self.ny, self.nx = self.vol.shape
        self.sz, self.sy, self.sx = self.spacing

        print(
            f"  {self.nx}×{self.ny}×{self.nz} voxels  "
            f"spacing {self.sx:.3f}×{self.sy:.3f}×{self.sz:.3f} mm  "
            f"HU [{self.vol.min():.0f}, {self.vol.max():.0f}]",
            flush=True,
        )

        self.zi = self.nz // 2
        self.yi = self.ny // 2
        self.xi = self.nx // 2

        # pre-compute coronal MIP (slow once, fast after)
        print("Computing MIP …", flush=True)
        self._mip = self.vol.max(axis=1)    # (nz, nx) — max along y

        self._build_figure()
        self._draw_all()
        self._update_dash()

    # ── figure ────────────────────────────────────────────────────────────────

    def _build_figure(self):
        fig = plt.figure(figsize=(14, 10))
        fig.patch.set_facecolor(BG)
        try:
            fig.canvas.manager.set_window_title(
                "Dental CBCT Viewer  ·  Prexion-style"
            )
        except Exception:
            pass
        self.fig = fig

        # 2×2 image grid — bottom raised to make room for 2 toolbar rows
        gs = GridSpec(
            2, 2, figure=fig,
            top=0.96, bottom=0.20,
            left=0.01, right=0.99,
            hspace=0.06, wspace=0.04,
        )
        self.ax_ax  = fig.add_subplot(gs[0, 0])
        self.ax_cor = fig.add_subplot(gs[0, 1])
        self.ax_sag = fig.add_subplot(gs[1, 0])
        self.ax_mip = fig.add_subplot(gs[1, 1])

        for ax, nm in [
            (self.ax_ax,  "Axial"),
            (self.ax_cor, "Coronal"),
            (self.ax_sag, "Sagittal"),
            (self.ax_mip, "MIP"),
        ]:
            ax.set_facecolor(BG_AX)
            ax.tick_params(left=False, bottom=False,
                           labelleft=False, labelbottom=False)
            for sp in ax.spines.values():
                sp.set_edgecolor(PANEL_C[nm])
                sp.set_linewidth(1.5)

        # image handles — created on first draw
        self._im_ax = self._im_cor = self._im_sag = self._im_mip = None

        # crosshair line handles
        self._ch: dict[str, tuple] = {}     # key → (hline, vline)

        # ── bottom toolbar — two rows ─────────────────────────────────────────
        # Row 1 (y=0.005): 2-D W/L presets + Reset
        # Row 2 (y=0.058): Prexion 3-D presets (each launches 3D + syncs 2D W/L)
        bh  = 0.038
        bw  = 0.082
        gap = 0.005

        # Keep references — matplotlib garbage-collects unreferenced widgets
        self._btns: list = []

        def btn(label, x, y, cb, color="#374151", fs=8):
            axi = fig.add_axes([x, y, bw, bh])
            b   = mwidgets.Button(axi, label, color=color, hovercolor="#4b5563")
            b.label.set_color(FG)
            b.label.set_fontsize(fs)
            b.on_clicked(cb)
            self._btns.append(b)
            return b

        # ── Row 1: 2-D W/L presets ────────────────────────────────────────────
        by1 = 0.007
        for i, name in enumerate(WL_PRESETS):
            x   = 0.01 + i * (bw + gap)
            col = "#1e40af" if name == "Enamel" else "#374151"
            btn(name, x, by1, lambda _e, n=name: self._preset(n), color=col)

        xrst = 0.01 + len(WL_PRESETS) * (bw + gap) + 0.01
        btn("Reset", xrst, by1, lambda _: self._reset(), color="#7c3aed")

        # ── Row 2: Prexion 3-D presets ────────────────────────────────────────
        by2 = 0.053
        if _TOOLBAR_3D:
            for i, pname in enumerate(_TOOLBAR_3D):
                x      = 0.01 + i * (bw + gap)
                lut_p  = _LUT_PRESETS[pname]
                label  = pname.replace("CT ", "").replace("3D ", "")   # shorten label
                btn(label, x, by2,
                    lambda _e, n=pname: self._launch_preset_3d(n),
                    color="#0c4a6e", fs=7.5)
        else:
            # Fallback if LUTs didn't load: single generic Launch 3D button
            btn("Launch 3D", 0.01, by2, self._launch_3d, color="#0f766e")

        # ── Status text ───────────────────────────────────────────────────────
        self._status_ax = fig.add_axes([0.56, by1, 0.41, bh])
        self._status_ax.set_facecolor("#1f2937")
        for sp in self._status_ax.spines.values():
            sp.set_visible(False)
        self._status_ax.tick_params(
            left=False, bottom=False, labelleft=False, labelbottom=False
        )
        self._status_txt = self._status_ax.text(
            0.02, 0.5,
            "Left-click → crosshair  |  Right-drag → W/L  |  "
            "Row 2 buttons → Prexion 3D preset",
            transform=self._status_ax.transAxes,
            va="center", ha="left", fontsize=7.5, color="#9ca3af",
        )

        # ── W/L sliders ───────────────────────────────────────────────────────
        # Keep axes refs too — prevents GC
        self._ax_ww = fig.add_axes([0.56, 0.148, 0.41, 0.022])
        self._ax_wl = fig.add_axes([0.56, 0.118, 0.41, 0.022])
        ax_ww, ax_wl = self._ax_ww, self._ax_wl
        for a in (ax_ww, ax_wl):
            a.set_facecolor("#1f2937")

        self._sl_ww = mwidgets.Slider(
            ax_ww, "WW", 50, 5000, valinit=self.ww,
            color="#3b82f6", initcolor="none"
        )
        self._sl_wl = mwidgets.Slider(
            ax_wl, "WL", -1000, 4000, valinit=self.wl,
            color="#10b981", initcolor="none"
        )
        for sl in (self._sl_ww, self._sl_wl):
            sl.label.set_color(FG)
            sl.valtext.set_color(FG)
        self._sl_ww.on_changed(self._slider_cb)
        self._sl_wl.on_changed(self._slider_cb)

        # ── events ────────────────────────────────────────────────────────────
        c = fig.canvas
        c.mpl_connect("scroll_event",         self._on_scroll)
        c.mpl_connect("button_press_event",   self._on_press)
        c.mpl_connect("button_release_event", self._on_release)
        c.mpl_connect("motion_notify_event",  self._on_move)
        c.mpl_connect("key_press_event",      self._on_key)

    # ── drawing ───────────────────────────────────────────────────────────────

    def _draw_all(self):
        nz, ny, nx = self.nz, self.ny, self.nx

        imgs = {
            "ax":  (_win(self.vol[self.zi, :, :], self.ww, self.wl),  self.ax_ax),
            "cor": (_win(self.vol[:, self.yi, :], self.ww, self.wl),  self.ax_cor),
            "sag": (_win(self.vol[:, :, self.xi], self.ww, self.wl), self.ax_sag),
            "mip": (_win(self._mip, self.ww, self.wl),                self.ax_mip),
        }

        for key, (img, ax) in imgs.items():
            attr = f"_im_{key}"
            if getattr(self, attr) is None:
                h = ax.imshow(img, cmap="gray", aspect="auto",
                              interpolation="bilinear", vmin=0, vmax=1,
                              origin="lower")
                setattr(self, attr, h)
                if key != "mip":
                    hl = ax.axhline(0, color=CROSS, alpha=0.7, lw=0.9, visible=False)
                    vl = ax.axvline(0, color=CROSS, alpha=0.7, lw=0.9, visible=False)
                    self._ch[key] = (hl, vl)
                else:
                    # MIP crosshairs (show position in the overview)
                    hl = ax.axhline(0, color=CROSS, alpha=0.5, lw=0.8, ls="--", visible=False)
                    vl = ax.axvline(0, color=CROSS, alpha=0.5, lw=0.8, ls="--", visible=False)
                    self._ch["mip"] = (hl, vl)
            else:
                getattr(self, attr).set_data(img)

        # titles with slice info
        ww, wl = self.ww, self.wl
        self.ax_ax.set_title(
            f"Axial  z={self.zi+1}/{nz}  ·  WW={ww:.0f}  WL={wl:.0f}",
            color=PANEL_C["Axial"], fontsize=8.5, pad=3
        )
        self.ax_cor.set_title(
            f"Coronal  y={self.yi+1}/{ny}  ·  WW={ww:.0f}  WL={wl:.0f}",
            color=PANEL_C["Coronal"], fontsize=8.5, pad=3
        )
        self.ax_sag.set_title(
            f"Sagittal  x={self.xi+1}/{nx}  ·  WW={ww:.0f}  WL={wl:.0f}",
            color=PANEL_C["Sagittal"], fontsize=8.5, pad=3
        )
        self.ax_mip.set_title(
            f"Coronal MIP  (max-intensity projection)",
            color=PANEL_C["MIP"], fontsize=8.5, pad=3
        )

        self._draw_crosshairs()
        self.fig.canvas.draw_idle()

    def _draw_crosshairs(self):
        # Axial (row=y, col=x): v-line at xi, h-line at yi
        if "ax" in self._ch:
            hl, vl = self._ch["ax"]
            hl.set_ydata([self.yi]); hl.set_visible(True)
            vl.set_xdata([self.xi]); vl.set_visible(True)
        # Coronal (row=z, col=x): v-line at xi, h-line at zi
        if "cor" in self._ch:
            hl, vl = self._ch["cor"]
            hl.set_ydata([self.zi]); hl.set_visible(True)
            vl.set_xdata([self.xi]); vl.set_visible(True)
        # Sagittal (row=z, col=y): v-line at yi, h-line at zi
        if "sag" in self._ch:
            hl, vl = self._ch["sag"]
            hl.set_ydata([self.zi]); hl.set_visible(True)
            vl.set_xdata([self.yi]); vl.set_visible(True)
        # MIP overview (row=z, col=x): dashed lines showing current position
        if "mip" in self._ch:
            hl, vl = self._ch["mip"]
            hl.set_ydata([self.zi]); hl.set_visible(True)
            vl.set_xdata([self.xi]); vl.set_visible(True)

    def _update_dash(self):
        hu = float(self.vol[self.zi, self.yi, self.xi])
        wx = self.xi * self.sx
        wy = self.yi * self.sy
        wz = self.zi * self.sz
        txt = (
            f"HU={hu:.0f}   "
            f"x={wx:.1f} y={wy:.1f} z={wz:.1f} mm   "
            f"vox ({self.xi},{self.yi},{self.zi})"
        )
        self._status_txt.set_text(txt)

    # ── which panel did the event land in ────────────────────────────────────

    def _panel(self, event) -> str | None:
        if event.inaxes is self.ax_ax:  return "ax"
        if event.inaxes is self.ax_cor: return "cor"
        if event.inaxes is self.ax_sag: return "sag"
        return None

    # ── event handlers ────────────────────────────────────────────────────────

    def _on_scroll(self, event):
        panel = self._panel(event)
        if panel is None:
            return
        d = 1 if event.button == "up" else -1
        if panel == "ax":
            self.zi = int(np.clip(self.zi + d, 0, self.nz - 1))
        elif panel == "cor":
            self.yi = int(np.clip(self.yi + d, 0, self.ny - 1))
        else:
            self.xi = int(np.clip(self.xi + d, 0, self.nx - 1))
        self._draw_all()
        self._update_dash()

    def _on_press(self, event):
        panel = self._panel(event)
        if panel is None or event.xdata is None:
            return
        if event.button == 1:   # left → set crosshair + sync
            cx = int(round(event.xdata))
            cy = int(round(event.ydata))
            if panel == "ax":
                self.xi = int(np.clip(cx, 0, self.nx - 1))
                self.yi = int(np.clip(cy, 0, self.ny - 1))
            elif panel == "cor":
                self.xi = int(np.clip(cx, 0, self.nx - 1))
                self.zi = int(np.clip(cy, 0, self.nz - 1))
            else:
                self.yi = int(np.clip(cx, 0, self.ny - 1))
                self.zi = int(np.clip(cy, 0, self.nz - 1))
            self._draw_all()
            self._update_dash()
        elif event.button == 3:  # right → start W/L drag
            self._drag = (event.x, event.y, self.ww, self.wl)

    def _on_release(self, event):
        if event.button == 3:
            self._drag = None

    def _on_move(self, event):
        if self._drag is None:
            return
        sx, sy, ww0, wl0 = self._drag
        dx = event.x - sx
        dy = event.y - sy
        self.ww = max(10.0, ww0 + dx * 5.0)   # horiz drag = WW
        self.wl = wl0 - dy * 5.0               # vert drag  = WL
        # Update sliders without double-firing draw
        self._sl_ww.eventson = False
        self._sl_wl.eventson = False
        self._sl_ww.set_val(self.ww)
        self._sl_wl.set_val(self.wl)
        self._sl_ww.eventson = True
        self._sl_wl.eventson = True
        self._draw_all()
        self._update_dash()

    def _on_key(self, event):
        k = event.key
        if   k == "x": self.zi = int(np.clip(self.zi + 1, 0, self.nz - 1))
        elif k == "z": self.zi = int(np.clip(self.zi - 1, 0, self.nz - 1))
        elif k == "v": self.yi = int(np.clip(self.yi + 1, 0, self.ny - 1))
        elif k == "c": self.yi = int(np.clip(self.yi - 1, 0, self.ny - 1))
        elif k == "n": self.xi = int(np.clip(self.xi + 1, 0, self.nx - 1))
        elif k == "b": self.xi = int(np.clip(self.xi - 1, 0, self.nx - 1))
        elif k == "1": self._preset("Enamel")
        elif k == "2": self._preset("Dentin")
        elif k == "3": self._preset("Bone")
        elif k == "4": self._preset("Soft")
        elif k == "5": self._preset("Full")
        elif k == "t": self._launch_3d(None)
        elif k == "r": self._reset()
        else: return
        self._draw_all()
        self._update_dash()

    # ── toolbar callbacks ─────────────────────────────────────────────────────

    def _preset(self, name: str):
        self.ww, self.wl = WL_PRESETS[name]
        self._sl_ww.eventson = False
        self._sl_wl.eventson = False
        self._sl_ww.set_val(self.ww)
        self._sl_wl.set_val(self.wl)
        self._sl_ww.eventson = True
        self._sl_wl.eventson = True
        self._draw_all()
        self._update_dash()

    def _slider_cb(self, _val):
        self.ww = float(self._sl_ww.val)
        self.wl = float(self._sl_wl.val)
        self._draw_all()
        self._update_dash()

    def _reset(self):
        self.zi, self.yi, self.xi = self.nz // 2, self.ny // 2, self.nx // 2
        self._preset("Enamel")

    def _launch_3d(self, _event=None, preset_name: str = "CT 3D Bone"):
        """Open 3-D PyVista viewer in a separate process (macOS-safe)."""
        cmd = [
            sys.executable, _3D_SCRIPT,
            "--dicom-dir", self._dicom_dir,
            "--preset",    preset_name,
            "--show-slices",
        ]
        try:
            subprocess.Popen(cmd)
            print(f"3D viewer launched: preset='{preset_name}'", flush=True)
        except Exception as e:
            print(f"Could not launch 3D viewer: {e}", flush=True)

    def _launch_preset_3d(self, preset_name: str):
        """Launch 3D with a Prexion preset AND sync the 2-D W/L to its Img2D values."""
        lut = _LUT_PRESETS.get(preset_name)
        if lut:
            # Sync 2-D views to Prexion's own Img2D window for this preset
            self.ww = lut.img2d_ww
            self.wl = lut.img2d_wl
            self._sl_ww.eventson = False
            self._sl_wl.eventson = False
            self._sl_ww.set_val(self.ww)
            self._sl_wl.set_val(self.wl)
            self._sl_ww.eventson = True
            self._sl_wl.eventson = True
            self._draw_all()
            self._update_dash()
            self._status_txt.set_text(
                f"Prexion preset '{preset_name}'  "
                f"→  2D W/L set to WW={lut.img2d_ww:.0f} WL={lut.img2d_wl:.0f}  "
                f"(Img2D from LUT)"
            )
            self.fig.canvas.draw_idle()
        self._launch_3d(preset_name=preset_name)

    # ── run ───────────────────────────────────────────────────────────────────

    def run(self):
        plt.show()


# ── entry point ───────────────────────────────────────────────────────────────

def main():
    import argparse
    p = argparse.ArgumentParser(description="Dental CBCT 4-panel MPR viewer")
    p.add_argument("--dicom-dir", default=DEFAULT_DICOM)
    args = p.parse_args()
    DentalViewer(args.dicom_dir).run()


if __name__ == "__main__":
    main()
