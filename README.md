# CT_Scan (CBCT utilities)

Python tooling to inspect **PreXion-style** cone-beam CT exports: DICOM metadata, `.pxv` slice folders, and `LUTTemplate` XML presets. Optional viewers use **matplotlib**, **PyVista**, and **VTK**.

**Repository:** [github.com/msherekar/CT_Scan](https://github.com/msherekar/CT_Scan)

## Important disclaimer

This code is for **research, engineering, and offline inspection** only. It is **not** a medical device and must **not** be used for clinical diagnosis or treatment decisions. Vendor viewer software and your institution’s policies govern any clinical use.

## Requirements

- **Python 3.10+** (uses `from __future__ import annotations` and modern typing)
- From the repo root, install what you need:

```bash
# Core: DICOM batch read + LUT XML parsing + PXV summaries
pip install pydicom

# 2D viewers / MPR / dental slice UI
pip install numpy matplotlib pydicom

# 3D volume + LUT presets (pyvista + vtk)
pip install numpy pydicom pyvista vtk
```

## Repository layout

| Path | Role |
|------|------|
| `src/read_cbct_files.py` | Single-file or batch `.dcm` / `.pxv` read; optional DICOM series browser |
| `src/process_pxv_folders.py` | Summarize `.pxv` trees under `Data/` (sizes, empties, hashes) |
| `src/process_lut_templates.py` | Parse `LUTTemplate/**/*.xml` into JSON/CSV |
| `src/run_all.py` | Runs scan steps + LUT step; writes `output/full_pipeline_summary.json` |
| `src/visualize_cbct.py`, `visualize_cbct_3d.py`, `mpr_viewer.py`, `dental_viewer.py` | Visualization entry points |
| `src/lut_parser.py` | LUT XML → VTK transfer functions (used by 3D path) |
| `scripts/` | Git helpers and `set_up_github_repo.sh` |

Large or proprietary trees (`DICOM/`, `Data/`, `LUTTemplate/`, `output/`, etc.) are typically **gitignored**; clone the repo and place your data beside `src/` as your workflow requires.

## Quick start

Run commands from the **repository root** (`CBCT/`).

**Batch DICOM metadata** (requires `pydicom`):

```bash
python3 src/read_cbct_files.py --batch-folder path/to/dicom/folder --kind dcm
```

**Summarize `.pxv` folders** (defaults point at `./Data/...`; override with `--folders`):

```bash
python3 src/process_pxv_folders.py --folders ./Data/your/study
```

**Export LUT presets**:

```bash
python3 src/process_lut_templates.py
```

**Full pipeline** (edit `src/run_all.py` if your DICOM path differs from the baked-in example):

```bash
python3 src/run_all.py
```

**Browse a DICOM series** (matplotlib):

```bash
python3 src/read_cbct_files.py --browse-series path/to/dicom/folder
```

## Windows viewer bundle

`Startup.bat` launches `PrexViewer.exe` next to it. That executable and related media are **not** part of this Python package; they come from the vendor distribution. Use only in line with PreXion’s license and disclaimer (see any included `ReadMe.txt`).

## License

Add a `LICENSE` file if you intend to open-source this repo; until then, all rights reserved unless you state otherwise.
