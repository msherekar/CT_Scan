"""Read CBCT .dcm/.pxv files and inspect folder-level datasets.
Supports single-file read, batch export (JSON/CSV), and DICOM slice browsing."""

from __future__ import annotations

import argparse, csv, json
from pathlib import Path

DEFAULT_DCM = Path("./DICOM")
DEFAULT_PXV = Path("./Data")
HEX_PREVIEW_BYTES = 128
TEXT_PREVIEW_BYTES = 256


def _safe_int(value: object) -> int | None:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def read_dcm(path: Path) -> dict:
    try:
        import pydicom  # type: ignore
    except ImportError as exc:
        raise RuntimeError("Install pydicom: pip install pydicom") from exc

    ds = pydicom.dcmread(str(path), stop_before_pixels=True, force=True)
    return {
        "type": "dcm",
        "path": str(path),
        "PatientID": str(getattr(ds, "PatientID", "")),
        "Modality": str(getattr(ds, "Modality", "")),
        "StudyDate": str(getattr(ds, "StudyDate", "")),
        "Rows": _safe_int(getattr(ds, "Rows", None)),
        "Columns": _safe_int(getattr(ds, "Columns", None)),
        "SliceThickness": str(getattr(ds, "SliceThickness", "")),
        "PixelSpacing": str(getattr(ds, "PixelSpacing", "")),
    }


def read_pxv(path: Path) -> dict:
    raw = path.read_bytes()
    head = raw[:HEX_PREVIEW_BYTES].hex(" ")
    text_preview = raw[:TEXT_PREVIEW_BYTES].decode("utf-8", errors="replace")
    return {
        "type": "pxv",
        "path": str(path),
        "size_bytes": len(raw),
        "header_hex_preview": head,
        "text_preview": text_preview,
    }


def list_candidate_files(folder: Path, kind: str) -> list[Path]:
    paths = [p for p in folder.rglob("*") if p.is_file()]
    if kind == "dcm":
        return [p for p in paths if p.suffix.lower() in {".dcm", ""}]
    if kind == "pxv":
        return [p for p in paths if p.suffix.lower() == ".pxv"]
    return paths


def batch_read(folder: Path, kind: str) -> list[dict]:
    records: list[dict] = []
    for path in list_candidate_files(folder, kind):
        try:
            ext = path.suffix.lower()
            if kind == "dcm" or (kind == "auto" and ext in {".dcm", ""}):
                records.append(read_dcm(path))
            elif kind == "pxv" or (kind == "auto" and ext == ".pxv"):
                records.append(read_pxv(path))
        except Exception as exc:  # keep batch processing going
            records.append({"path": str(path), "error": str(exc)})
    return records


def save_batch_outputs(records: list[dict], json_out: Path | None, csv_out: Path | None) -> None:
    if json_out:
        json_out.parent.mkdir(parents=True, exist_ok=True)
        json_out.write_text(json.dumps(records, indent=2), encoding="utf-8")
    if csv_out and records:
        keys: list[str] = sorted({k for record in records for k in record.keys()})
        csv_out.parent.mkdir(parents=True, exist_ok=True)
        with csv_out.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=keys)
            writer.writeheader()
            for row in records:
                writer.writerow(row)


def browse_dicom_series(folder: Path) -> None:
    try:
        import matplotlib.pyplot as plt  # type: ignore
        import pydicom  # type: ignore
    except ImportError as exc:
        raise RuntimeError("Install dependencies: pip install pydicom matplotlib") from exc

    files = [p for p in folder.rglob("*") if p.is_file()]
    slices = []
    for p in files:
        try:
            ds = pydicom.dcmread(str(p), force=True)
            pixels = ds.pixel_array
            index = _safe_int(getattr(ds, "InstanceNumber", None)) or len(slices)
            slices.append((index, pixels, p))
        except Exception:
            continue
    if not slices:
        raise ValueError(f"No readable DICOM slices in: {folder}")

    slices.sort(key=lambda x: x[0])
    stack = [s[1] for s in slices]
    idx = 0
    fig, ax = plt.subplots()
    img = ax.imshow(stack[idx], cmap="gray")
    ax.set_title(f"Slice {idx + 1}/{len(stack)}")

    def refresh() -> None:
        img.set_data(stack[idx])
        ax.set_title(f"Slice {idx + 1}/{len(stack)}")
        fig.canvas.draw_idle()

    def on_key(event) -> None:  # type: ignore[no-untyped-def]
        nonlocal idx
        if event.key in {"right", "down", "n"}:
            idx = min(idx + 1, len(stack) - 1)
        elif event.key in {"left", "up", "p"}:
            idx = max(idx - 1, 0)
        refresh()

    fig.canvas.mpl_connect("key_press_event", on_key)
    plt.show()


def resolve_input(path_arg: str | None, fallback_root: Path, filename: str) -> Path:
    if path_arg:
        return Path(path_arg)
    return fallback_root / filename


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read .dcm and .pxv files")
    parser.add_argument("--input", type=str, default=None, help="Path to .dcm or .pxv")
    parser.add_argument(
        "--kind",
        choices=["auto", "dcm", "pxv"],
        default="auto",
        help="File type. Default: auto by extension",
    )
    parser.add_argument("--default-dcm", type=str, default="00001DCM.dcm")
    parser.add_argument("--default-pxv", type=str, default="00001.pxv")
    parser.add_argument("--batch-folder", type=str, default=None, help="Recursive folder for batch mode")
    parser.add_argument("--json-out", type=str, default="output/scan_results.json")
    parser.add_argument("--csv-out", type=str, default="output/scan_results.csv")
    parser.add_argument("--browse-series", type=str, default=None, help="DICOM folder for video-like browsing")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.browse_series:
        browse_dicom_series(Path(args.browse_series))
        return
    if args.batch_folder:
        records = batch_read(Path(args.batch_folder), args.kind)
        save_batch_outputs(records, Path(args.json_out), Path(args.csv_out))
        print(json.dumps({"records": len(records), "json": args.json_out, "csv": args.csv_out}, indent=2))
        return
    if args.kind == "dcm":
        path = resolve_input(args.input, DEFAULT_DCM, args.default_dcm)
        result = read_dcm(path)
    elif args.kind == "pxv":
        path = resolve_input(args.input, DEFAULT_PXV, args.default_pxv)
        result = read_pxv(path)
    else:
        path = Path(args.input) if args.input else resolve_input(None, DEFAULT_DCM, args.default_dcm)
        ext = path.suffix.lower()
        if ext == ".dcm":
            result = read_dcm(path)
        elif ext == ".pxv":
            result = read_pxv(path)
        else:
            raise ValueError("Use --kind dcm|pxv for unknown file extension")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
