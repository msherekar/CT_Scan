"""Run CBCT data and LUT processing in one command.
Executes scan parsing first, then LUT parsing, and writes a combined summary."""

from __future__ import annotations

import argparse, json, subprocess
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = BASE_DIR / "output"


def run_cmd(cmd: list[str]) -> dict:
    proc = subprocess.run(cmd, cwd=BASE_DIR, capture_output=True, text=True)
    return {
        "command": " ".join(cmd),
        "returncode": proc.returncode,
        "stdout": proc.stdout.strip(),
        "stderr": proc.stderr.strip(),
    }


def run_scan_steps() -> list[dict]:
    commands = [
        ["python3", "src/read_cbct_files.py", "--batch-folder", "DICOM/48778133/63925984", "--kind", "dcm"],
        ["python3", "src/process_pxv_folders.py"],
    ]
    return [run_cmd(cmd) for cmd in commands]


def run_lut_step() -> dict:
    return run_cmd(["python3", "src/process_lut_templates.py"])


def write_summary(results: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(results, indent=2), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run full CBCT processing pipeline")
    parser.add_argument("--summary-out", default="./output/full_pipeline_summary.json")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    scan_results = run_scan_steps()
    lut_result = run_lut_step()
    results = {
        "status": "ok" if all(r["returncode"] == 0 for r in scan_results + [lut_result]) else "failed",
        "scan_steps": scan_results,
        "lut_step": lut_result,
        "expected_outputs": [
            str(OUTPUT_DIR / "scan_results.json"),
            str(OUTPUT_DIR / "scan_results.csv"),
            str(OUTPUT_DIR / "pxv_summary.json"),
            str(OUTPUT_DIR / "pxv_summary.csv"),
            str(OUTPUT_DIR / "lut_templates.json"),
            str(OUTPUT_DIR / "lut_templates.csv"),
        ],
    }
    summary_path = Path(args.summary_out)
    write_summary(results, summary_path)
    print(json.dumps({"status": results["status"], "summary_out": str(summary_path)}, indent=2))


if __name__ == "__main__":
    main()
