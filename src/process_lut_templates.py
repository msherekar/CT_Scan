"""Parse LUTTemplate presets from PreXion CBCT folders.
Exports structured JSON/CSV summaries, including default LUT selection."""

from __future__ import annotations

import argparse, csv, json, xml.etree.ElementTree as ET
from pathlib import Path

LUT_ROOT = Path("./LUTTemplate")
SECTIONS = ("Standard", "Other")


def parse_kv_file(path: Path) -> dict:
    data = {}
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            data[k.strip()] = v.strip()
    return data


def parse_lut_xml(path: Path, section: str) -> dict:
    root = ET.fromstring(path.read_text(encoding="utf-8", errors="ignore"))
    template = root.find("LUTTemplate")
    objs = template.findall("Obj") if template is not None else []
    light = template.find("Light") if template is not None else None
    img2d = template.find("Img2D") if template is not None else None
    img3d = template.find("Img3D") if template is not None else None
    active = [o for o in objs if o.attrib.get("Active") == "1"]
    return {
        "section": section,
        "file_name": path.name,
        "preset_name": (template.attrib.get("Name") if template is not None else path.stem),
        "date": root.attrib.get("Date", ""),
        "obj_count": len(objs),
        "active_obj_count": len(active),
        "img2d_ww": (img2d.attrib.get("WW", "") if img2d is not None else ""),
        "img2d_wl": (img2d.attrib.get("WL", "") if img2d is not None else ""),
        "img3d_ww": (img3d.attrib.get("WW", "") if img3d is not None else ""),
        "img3d_wl": (img3d.attrib.get("WL", "") if img3d is not None else ""),
        "light_intensity": (light.attrib.get("Intensity", "") if light is not None else ""),
        "light_contrast": (light.attrib.get("Contrast", "") if light is not None else ""),
        "light_bg_rgb": (
            f"{light.attrib.get('BG_R','')},{light.attrib.get('BG_G','')},{light.attrib.get('BG_B','')}"
            if light is not None
            else ""
        ),
        "xml_path": str(path),
    }


def collect_templates(lut_root: Path) -> list[dict]:
    rows = []
    for section in SECTIONS:
        folder = lut_root / section
        for xml_file in sorted(folder.glob("*.xml")):
            rows.append(parse_lut_xml(xml_file, section))
    return rows


def write_csv(rows: list[dict], path: Path) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = sorted(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns, quoting=csv.QUOTE_ALL)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Parse LUTTemplate XML presets")
    parser.add_argument("--lut-root", default=str(LUT_ROOT))
    parser.add_argument("--json-out", default="./output/lut_templates.json")
    parser.add_argument("--csv-out", default="./output/lut_templates.csv")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    lut_root = Path(args.lut_root)
    default_cfg = parse_kv_file(lut_root / "default_lut")
    rows = collect_templates(lut_root)
    listed = {
        sec: (lut_root / sec / "lut_info.txt").read_text(encoding="utf-8", errors="ignore").splitlines()
        for sec in SECTIONS
    }
    result = {"default": default_cfg, "listed_presets": listed, "templates": rows}
    json_path = Path(args.json_out)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    write_csv(rows, Path(args.csv_out))
    print(json.dumps({"templates": len(rows), "json_out": args.json_out, "csv_out": args.csv_out}, indent=2))


if __name__ == "__main__":
    main()
