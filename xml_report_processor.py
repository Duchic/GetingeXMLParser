#!/usr/bin/env python3
"""Convert Getinge-style sterilization XML logs into PDF cycle reports.

The XML format used by the device is shaped like:
    <TDOCLOGPACKET>
      <CYCLE>
        <CYCLEDATA>
          <MACHNAME>...</MACHNAME>
          <PROGNAME>...</PROGNAME>
          <PROCSTARTTIME>...</PROCSTARTTIME>
          <LOGDATA>
            <ROW><TIME>...</TIME><CT>...</CT><CP>...</CP></ROW>
            <ROW><PHASE>START</PHASE></ROW>
          </LOGDATA>
        </CYCLEDATA>
      </CYCLE>
    </TDOCLOGPACKET>
"""

from __future__ import annotations

import argparse
import logging
import shutil
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from xml.etree import ElementTree as ET

from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

LOGGER = logging.getLogger("xml_report_processor")


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].upper()


def safe_text(node: Optional[ET.Element]) -> str:
    if node is None or node.text is None:
        return ""
    return node.text.strip()


def parse_decimal(value: str) -> Optional[float]:
    if not value:
        return None
    try:
        return float(value.replace(",", "."))
    except ValueError:
        return None


def extract_cycle_metadata(root: ET.Element) -> Dict[str, str]:
    cycle_data = next((element for element in root.iter() if local_name(element.tag) == "CYCLEDATA"), None)
    if cycle_data is None:
        raise ValueError("No <CYCLEDATA> element found in XML.")

    tags = [
        ("Machine", "MACHNAME"),
        ("Machine ref.", "MACHREFNO"),
        ("Program", "PROGPROGRAM"),
        ("Program name", "PROGNAME"),
        ("Scan number", "PROGSCANNUM"),
        ("Exposure time", "PROGEXPOSURETIME"),
        ("Exposure temp.", "PROGEXPOSURETEMP"),
        ("Batch", "PROCBATCH"),
        ("Cycle", "PROCCYCLE"),
        ("Start time", "PROCSTARTTIME"),
        ("End time", "PROCENDTIME"),
        ("Error code", "PROCNATIVEERROR"),
        ("Error text", "PROCNATIVEERRORTEXT"),
    ]

    result: Dict[str, str] = {}
    for label, tag_name in tags:
        element = next((child for child in cycle_data if local_name(child.tag) == tag_name), None)
        text = safe_text(element)
        if text:
            result[label] = text
    return result


def extract_log_rows(root: ET.Element) -> List[Dict[str, str]]:
    cycle_data = next((element for element in root.iter() if local_name(element.tag) == "CYCLEDATA"), None)
    if cycle_data is None:
        return []

    log_data = next((element for element in cycle_data.iter() if local_name(element.tag) == "LOGDATA"), None)
    if log_data is None:
        return []

    records: List[Dict[str, str]] = []
    current_phase = ""
    discovered_tags = set()

    for row in log_data.iter():
        discovered_tags.add(local_name(row.tag))
        children = list(row)
        direct_values = {local_name(child.tag): safe_text(child) for child in children}
        is_row = local_name(row.tag) == "ROW"
        has_measurements = "TIME" in direct_values and ("CT" in direct_values or "CP" in direct_values)
        if not is_row and not has_measurements:
            continue

        values = direct_values
        if is_row:
            values = {local_name(child.tag): safe_text(child) for child in row.iter() if child is not row}
        phase = values.get("PHASE", "")
        if phase:
            current_phase = phase
            continue

        record: Dict[str, str] = {
            "TIME": values.get("TIME", ""),
            "CT": values.get("CT", ""),
            "CP": values.get("CP", ""),
            "PHASE": current_phase or "N/A",
        }
        if record["TIME"] or record["CT"] or record["CP"]:
            records.append(record)

    if not records:
        LOGGER.warning("No measurement records found. LOGDATA tags: %s", ", ".join(sorted(discovered_tags)))
    return records


def summarize_log_rows(rows: List[Dict[str, str]]) -> Dict[str, Any]:
    numeric_ct = [parse_decimal(item["CT"]) for item in rows if item.get("CT")]
    numeric_cp = [parse_decimal(item["CP"]) for item in rows if item.get("CP")]
    numeric_ct = [value for value in numeric_ct if value is not None]
    numeric_cp = [value for value in numeric_cp if value is not None]

    summary = {
        "record_count": len(rows),
        "phase_count": len({item["PHASE"] for item in rows if item.get("PHASE")}),
        "max_ct": max(numeric_ct) if numeric_ct else None,
        "max_cp": max(numeric_cp) if numeric_cp else None,
    }
    return summary


def add_multiline_text(canvas: canvas.Canvas, x_mm: float, y_mm: float, lines: List[str], font_name: str = "Helvetica", font_size: int = 9, line_gap: float = 5) -> float:
    canvas.setFont(font_name, font_size)
    y = y_mm
    for line in lines:
        if y < 18:
            canvas.showPage()
            canvas.setFont(font_name, font_size)
            y = 290
        canvas.drawString(x_mm * mm, y * mm, line)
        y -= line_gap
    return y


def parse_time_to_minutes(value: str) -> float:
    if not value:
        return 0.0
    try:
        hours, minutes, seconds = (int(part) for part in value.split(":"))
        return hours * 60 + minutes + seconds / 60.0
    except ValueError:
        return 0.0


def draw_barcode_like_pattern(c: canvas.Canvas, x_mm: float, y_mm: float, width_mm: float, height_mm: float) -> None:
    x = x_mm * mm
    y = y_mm * mm
    bar_width = 1.2
    for idx in range(0, 120):
        if idx % 3 == 0:
            c.setFillColorRGB(0, 0, 0)
            c.rect(x + idx * bar_width, y, bar_width, height_mm * mm, stroke=0, fill=1)


def build_pdf_report(pdf_path: Path, source_path: Path, metadata: Dict[str, str], rows: List[Dict[str, str]]) -> None:
    c = canvas.Canvas(str(pdf_path), pagesize=landscape(A4))
    page_width, page_height = landscape(A4)

    c.setTitle(f"Sterilization report - {source_path.name}")
    c.setFillColorRGB(0.12, 0.12, 0.12)

    left_x = 18
    top_y = page_height - 20

    c.setFont("Helvetica-Bold", 26)
    c.drawString(left_x * mm, top_y - 16 * mm, "T-DOC")
    c.setFont("Helvetica-Bold", 13)
    c.drawRightString(page_width - 25 * mm, top_y - 16 * mm, "GETINGE")

    c.setFont("Helvetica", 11)
    c.drawString(left_x * mm, top_y - 34 * mm, "vsázka:")
    c.drawRightString(page_width - 25 * mm, top_y - 34 * mm, "GETINGE")

    draw_barcode_like_pattern(c, 95, 190, 64, 14)

    batch_number = metadata.get("Batch", "-")
    c.setFillColorRGB(0.96, 0.96, 0.96)
    c.rect(18 * mm, 145 * mm, 112 * mm, 32 * mm, stroke=1, fill=1)
    c.setStrokeColorRGB(0, 0, 0)
    c.setFillColorRGB(0, 0, 0)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(24 * mm, 170 * mm, "vsázka")
    c.setFont("Helvetica-Bold", 22)
    c.drawString(24 * mm, 155 * mm, str(batch_number))

    machine = metadata.get("Machine", "-")
    program = metadata.get("Program", "-")
    program_name = metadata.get("Program name", "-")
    cycle = metadata.get("Cycle", "-")
    start_time = metadata.get("Start time", "-")
    end_time = metadata.get("End time", "-")

    c.setFont("Helvetica", 10)
    c.drawString(148 * mm, 176 * mm, f"{machine}")
    c.drawString(148 * mm, 168 * mm, f"Cykl {cycle}")
    c.drawString(148 * mm, 160 * mm, f"program {program}")

    c.setFont("Helvetica", 9)
    c.drawString(148 * mm, 148 * mm, f"{start_time} ")
    c.drawString(200 * mm, 148 * mm, f"{end_time}")

    c.setFont("Helvetica-Bold", 10)
    c.drawString(20 * mm, 123 * mm, "systémová chyba")
    c.setFont("Helvetica-Bold", 10)
    c.drawString(82 * mm, 123 * mm, metadata.get("Error code", "0"))

    chart_x = 20 * mm
    chart_y = 35 * mm
    chart_width = 210 * mm
    chart_height = 70 * mm
    c.setStrokeColorRGB(0.7, 0.7, 0.7)
    c.rect(chart_x, chart_y, chart_width, chart_height, stroke=1, fill=0)

    valid_rows = []
    for row in rows:
        time_value = parse_time_to_minutes(row.get("TIME", ""))
        ct_value = parse_decimal(row.get("CT", ""))
        cp_value = parse_decimal(row.get("CP", ""))
        if row.get("TIME") and ct_value is not None and cp_value is not None:
            valid_rows.append({**row, "_TIME_MINUTES": time_value, "_CT_VALUE": ct_value, "_CP_VALUE": cp_value})

    LOGGER.info("Loaded %d graph rows from %s", len(valid_rows), source_path.name)
    if valid_rows:
        times = [row["_TIME_MINUTES"] for row in valid_rows]
        ct_values = [row["_CT_VALUE"] for row in valid_rows]
        cp_values = [row["_CP_VALUE"] for row in valid_rows]

        x_min, x_max = 0.0, max(60.0, max(times) if times else 60.0)
        y_ct_min, y_ct_max = 60.0, max(140.0, max(ct_values) if ct_values else 140.0)
        y_cp_min, y_cp_max = 0.0, max(3.5, max(cp_values) if cp_values else 3.5)

        def map_x(value: float) -> float:
            return chart_x + (value - x_min) / (x_max - x_min + 1e-9) * chart_width

        def map_ct(value: float) -> float:
            return chart_y + (value - y_ct_min) / (y_ct_max - y_ct_min + 1e-9) * chart_height

        def map_cp(value: float) -> float:
            return chart_y + (value - y_cp_min) / (y_cp_max - y_cp_min + 1e-9) * chart_height

        c.setStrokeColorRGB(0.7, 0.7, 0.7)
        for grid in range(0, 7):
            x = chart_x + (chart_width * grid / 6)
            c.line(x, chart_y, x, chart_y + chart_height)
            y = chart_y + (chart_height * grid / 6)
            c.line(chart_x, y, chart_x + chart_width, y)

        c.setFont("Helvetica", 8)
        for tick in range(0, 7):
            value = x_min + (x_max - x_min) * tick / 6
            c.drawString(chart_x + (chart_width * tick / 6) - 3 * mm, chart_y - 5 * mm, f"{int(value)}")

        c.setFont("Helvetica", 8)
        c.drawRightString(chart_x - 3 * mm, chart_y + chart_height - 3 * mm, "140")
        c.drawRightString(chart_x - 3 * mm, chart_y + chart_height / 2, "100")
        c.drawRightString(chart_x - 3 * mm, chart_y + 3 * mm, "60")

        c.setFont("Helvetica", 8)
        c.drawString(chart_x + chart_width - 16 * mm, chart_y + chart_height + 4 * mm, "min")

        c.setStrokeColorRGB(0.1, 0.5, 0.9)
        c.setFillColorRGB(0.1, 0.5, 0.9)
        points_ct = [(map_x(row["_TIME_MINUTES"]), map_ct(row["_CT_VALUE"])) for row in valid_rows]
        if len(points_ct) > 1:
            c.beginPath()
            c.moveTo(points_ct[0][0], points_ct[0][1])
            for px, py in points_ct[1:]:
                c.lineTo(px, py)
            c.drawPath()

        c.setStrokeColorRGB(0.9, 0.45, 0.0)
        c.setFillColorRGB(0.9, 0.45, 0.0)
        points_cp = [(map_x(row["_TIME_MINUTES"]), map_cp(row["_CP_VALUE"])) for row in valid_rows]
        if len(points_cp) > 1:
            c.beginPath()
            c.moveTo(points_cp[0][0], points_cp[0][1])
            for px, py in points_cp[1:]:
                c.lineTo(px, py)
            c.drawPath()

        c.setFont("Helvetica", 8)
        c.setFillColorRGB(0.1, 0.5, 0.9)
        c.drawString(25 * mm, 96 * mm, "TEPL. VYPOUSTENI")
        c.setFillColorRGB(0.9, 0.45, 0.0)
        c.drawString(110 * mm, 96 * mm, "TLAK V KOMORE")

        c.setFillColorRGB(0.1, 0.5, 0.9)
        c.drawString(25 * mm, 92 * mm, f"Max CT = {max(ct_values):.1f} °C")
        c.setFillColorRGB(0.9, 0.45, 0.0)
        c.drawString(110 * mm, 92 * mm, f"Max CP = {max(cp_values):.3f} bar")

    c.save()


def parse_xml_file(xml_path: Path) -> Dict[str, Any]:
    tree = ET.parse(xml_path)
    root = tree.getroot()
    metadata = extract_cycle_metadata(root)
    rows = extract_log_rows(root)
    return {"metadata": metadata, "rows": rows}


def ensure_directories(*dirs: Path) -> None:
    for directory in dirs:
        directory.mkdir(parents=True, exist_ok=True)


def get_unique_destination(directory: Path, file_name: str) -> Path:
    destination = directory / file_name
    if not destination.exists():
        return destination

    stem = destination.stem
    suffix = destination.suffix
    counter = 1
    while True:
        candidate = directory / f"{stem}_{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def process_xml_file(xml_path: Path, output_dir: Path, failed_dir: Path) -> bool:
    try:
        parsed = parse_xml_file(xml_path)
        if not parsed["rows"]:
            raise ValueError("XML obsahuje 0 logových řádků; PDF nebylo vytvořeno.")

        pdf_path = get_unique_destination(output_dir, f"{xml_path.stem}.pdf")
        build_pdf_report(pdf_path, xml_path, parsed["metadata"], parsed["rows"])

        archived_path = get_unique_destination(output_dir, xml_path.name)
        shutil.move(str(xml_path), str(archived_path))
        LOGGER.info("Processed %s -> %s and archived at %s", xml_path.name, pdf_path.name, archived_path.name)
        return True
    except Exception as exc:  # pragma: no cover
        failed_path = get_unique_destination(failed_dir, xml_path.name)
        shutil.move(str(xml_path), str(failed_path))
        LOGGER.exception("Failed to process %s; moved to %s", xml_path.name, failed_path)
        print(f"ERROR: {xml_path.name} could not be processed: {exc}", file=sys.stderr)
        return False


def process_directory(input_dir: Path, output_dir: Path, failed_dir: Path) -> None:
    ensure_directories(input_dir, output_dir, failed_dir)
    xml_files = sorted(input_dir.glob("*.xml"))
    if not xml_files:
        LOGGER.info("No XML files found in %s", input_dir)
        return

    for xml_file in xml_files:
        process_xml_file(xml_file, output_dir, failed_dir)


def iter_machine_folders(root_dir: Path) -> List[Path]:
    folders: List[Path] = []
    for index in range(1, 10):
        machine_dir = root_dir / f"{index:03d}"
        if machine_dir.exists() and machine_dir.is_dir():
            folders.append(machine_dir)
    return folders


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert sterilization XML logs into PDF reports and archive originals in _edit folders.")
    parser.add_argument("--root", type=Path, default=Path(r"D:\TDOC_Export"), help="Root directory containing machine folders 001..009.")
    parser.add_argument("--input", type=Path, default=None, help="Optional specific input folder to process instead of all 001..009 machine folders.")
    parser.add_argument("--failed", type=Path, default=None, help="Folder for files that could not be processed.")
    parser.add_argument("--interval-seconds", type=int, default=600, help="Polling interval in seconds. Default: 600.")
    parser.add_argument("--once", action="store_true", help="Process current XML files once and exit.")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

    root_dir = args.root
    failed_dir = args.failed or root_dir / "failed_xml"
    ensure_directories(root_dir, failed_dir)

    def process_root_folders() -> None:
        machine_dirs = [args.input] if args.input else iter_machine_folders(root_dir)
        for machine_dir in machine_dirs:
            output_dir = root_dir / f"{machine_dir.name}_edit"
            ensure_directories(machine_dir, output_dir, failed_dir)
            process_directory(machine_dir, output_dir, failed_dir)

    if args.once:
        process_root_folders()
        return 0

    while True:
        try:
            process_root_folders()
        except Exception as exc:  # pragma: no cover
            LOGGER.exception("Unexpected error during processing: %s", exc)
        time.sleep(args.interval_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
