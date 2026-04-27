"""Process .pxv files from CBCT Data folders and export clean summaries.
Designed for PreXion-style folders with many empty slices and large volumes."""

from __future__ import annotations

import argparse, csv, hashlib, json
from pathlib import Path

DEFAULT_FOLDERS = ["./Data/48778133/63925984", "./Data/48778133/63958736"]


def iter_pxv_files(folder: Path) -> list[Path]:
    return sorted([p for p in folder.rglob("*.pxv") if p.is_file()])


def file_summary(path: Path) -> dict:
    raw = path.read_bytes()
    digest = hashlib.md5(raw).hexdigest() if raw else ""
    return {
        "file_name": path.name,
        "relative_path": str(path),
        "size_bytes": len(raw),
        "is_empty": len(raw) == 0,
        "header_hex_32": raw[:32].hex(" "),
        "md5": digest,
    }


def folder_summary(folder: Path) -> dict:
    files = iter_pxv_files(folder)
    rows = [file_summary(p) for p in files]
    non_empty = [r for r in rows if not r["is_empty"]]
    return {
        "folder": str(folder),
        "total_pxv_files": len(rows),
        "non_empty_pxv_files": len(non_empty),
        "empty_pxv_files": len(rows) - len(non_empty),
        "max_size_bytes": max((r["size_bytes"] for r in rows), default=0),
        "rows": rows,
    }


def write_outputs(all_rows: list[dict], out_json: Path, out_csv: Path) -> None:
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(all_rows, indent=2), encoding="utf-8")
    keys = ["file_name", "relative_path", "size_bytes", "is_empty", "header_hex_32", "md5"]
    with out_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=keys, quoting=csv.QUOTE_ALL)
        writer.writeheader()
        for row in all_rows:
            writer.writerow({k: row.get(k, "") for k in keys})


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Robust .pxv folder processor")
    parser.add_argument("--folders", nargs="+", default=DEFAULT_FOLDERS, help="Relative folder paths")
    parser.add_argument("--json-out", default="./output/pxv_summary.json")
    parser.add_argument("--csv-out", default="./output/pxv_summary.csv")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    per_folder = [folder_summary(Path(folder)) for folder in args.folders]
    all_rows = [row for block in per_folder for row in block["rows"]]
    write_outputs(all_rows, Path(args.json_out), Path(args.csv_out))
    print(json.dumps({"folders": per_folder, "json_out": args.json_out, "csv_out": args.csv_out}, indent=2))


if __name__ == "__main__":
    main()
