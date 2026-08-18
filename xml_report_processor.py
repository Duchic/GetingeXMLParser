#!/usr/bin/env python3
"""XML report processor for device cycle XML files.

This script watches an input directory for XML files, converts each file into a
PDF report, and moves the original XML to an archive directory.

Typical usage:
    python xml_report_processor.py --input C:\\incoming \
        --archive C:\\archive \
        --pdf C:\\reports \
        --interval-seconds 600
"""

from __future__ import annotations

import argparse
import logging
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple
from xml.etree import ElementTree as ET

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas


LOGGER = logging.getLogger("xml_report_processor")


def normalize_tag(tag: str | None) -> str:
    if not tag:
        return ""
    return tag.rsplit("}", 1)[-1].lower()


def safe_text(node: ET.Element | None) -> str:
    if node is None:
        return ""
    value = (node.text or "").strip()
    return value


def find_first_by_names(root: ET.Element, names: Iterable[str]) -> str:
    name_set = {n.lower() for n in names}
    for elem in root.iter():
        tag = normalize_tag(elem.tag)
        if tag in name_set:
            text = safe_text(elem)
            if text:
                return text
    return ""


def collect_measurements(root: ET.Element) -> List[Dict[str, str]]:
    """Extract values from a generic XML structure.

    Supports patterns like:
      <Record><Name>Temperature</Name><Value>36.5</Value></Record>
      <Item><Label>Time</Label><Value>12:45</Value></Item>
      <Measurement><Parameter>Cycle</Parameter><Value>OK</Value></Measurement>
    """
    results: List[Dict[str, str]] = []
    name_tags = {"name", "label", "parameter", "key", "field", "title", "code"}
    value_tags = {"value", "amount", "result", "measurement", "reading", "actual"}
    for elem in root.iter():
        if elem is root:
            continue

        children = list(elem)
        if not children:
            continue

        child_map: Dict[str, str] = {}
        for child in children:
            tag = normalize_tag(child.tag)
            text = safe_text(child)
            if tag in name_tags and text:
                child_map["name"] = text
            if tag in value_tags and text:
                child_map["value"] = text
            if tag in {"unit", "units"} and text:
                child_map["unit"] = text

        if child_map.get("name") and child_map.get("value"):
            result = {"name": child_map["name"], "value": child_map["value"]}
            if child_map.get("unit"):
                result["unit"] = child_map["unit"]
            results.append(result)

    # Deduplicate exact name/value pairs while preserving order.
    seen = set()
    deduped: List[Dict[str, str]] = []
    for item in results:
        key = (item.get("name", ""), item.get("value", ""), item.get("unit", ""))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def extract_general_data(root: ET.Element) -> Dict[str, str]:
    data: Dict[str, str] = {}
    candidates = [
        ("Cycle ID", ["cycleid", "cycle_id", "cycleidnumber", "id"]),
        ("Cycle Type", ["cycletype", "cycle_type", "programname", "program", "type"]),
        ("Device", ["device", "devicename", "machine", "machine_name", "unit", "instrument"]),
        ("Status", ["status", "result", "state", "outcome"]),
        ("Date", ["date", "cycle_date", "startdate", "enddate"]),
        ("Start Time", ["starttime", "start_time", "startedat", "begintime"]),
        ("End Time", ["endtime", "end_time", "finishedat", "stoptime"]),
        ("Duration", ["duration", "elapsedtime", "timeelapsed", "cycletime"]),
        ("Operator", ["operator", "user", "user_name"]),
        ("Serial Number", ["serialnumber", "serial_no", "serial", "deviceid"]),
    ]

    for label, tags in candidates:
        value = find_first_by_names(root, tags)
        if value:
            data[label] = value

    if not data:
        for elem in root.iter():
            tag = normalize_tag(elem.tag)
            if tag in {"xml", "root", "document"}:
                continue
            text = safe_text(elem)
            if text and len(text) < 120:
                data.setdefault(tag.replace("_", " ").title(), text)

    return data


def build_pdf_report(pdf_path: Path, source_path: Path, general_data: Dict[str, str], measurements: List[Dict[str, str]]) -> None:
    c = canvas.Canvas(str(pdf_path), pagesize=A4)
    page_width, page_height = A4

    c.setTitle(f"Report for {source_path.name}")
    c.setFont("Helvetica-Bold", 18)
    c.drawString(25 * mm, page_height - 25 * mm, "XML cycle report")

    c.setFont("Helvetica", 10)
    c.drawString(25 * mm, page_height - 35 * mm, f"Source file: {source_path.name}")
    c.drawString(25 * mm, page_height - 42 * mm, f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    y = page_height - 60 * mm
    c.setFont("Helvetica-Bold", 12)
    c.drawString(25 * mm, y, "Basic information")
    y -= 8 * mm

    c.setFont("Helvetica", 10)
    for index, (label, value) in enumerate(general_data.items()):
        if y < 20 * mm:
            c.showPage()
            y = page_height - 25 * mm
        c.drawString(30 * mm, y, f"- {label}: {value}")
        y -= 7 * mm

    if measurements:
        y -= 8 * mm
        if y < 30 * mm:
            c.showPage()
            y = page_height - 25 * mm
        c.setFont("Helvetica-Bold", 12)
        c.drawString(25 * mm, y, "Measured values")
        y -= 8 * mm
        c.setFont("Helvetica", 10)

        for item in measurements:
            if y < 20 * mm:
                c.showPage()
                y = page_height - 25 * mm
            line = f"- {item.get('name', 'Unknown')}: {item.get('value', '')}"
            if item.get("unit"):
                line += f" {item.get('unit')}"
            c.drawString(30 * mm, y, line)
            y -= 7 * mm

    c.save()


def parse_xml_file(xml_path: Path) -> Dict[str, Any]:
    tree = ET.parse(xml_path)
    root = tree.getroot()
    general_data = extract_general_data(root)
    measurements = collect_measurements(root)
    return {
        "general": general_data,
        "measurements": measurements,
        "root_tag": root.tag,
    }


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


def process_xml_file(xml_path: Path, archive_dir: Path, pdf_dir: Path, failed_dir: Path) -> bool:
    try:
        data = parse_xml_file(xml_path)
        pdf_path = pdf_dir / f"{xml_path.stem}.pdf"
        pdf_path = get_unique_destination(pdf_dir, f"{xml_path.stem}.pdf")
        build_pdf_report(pdf_path, xml_path, data["general"], data["measurements"])

        archived_path = get_unique_destination(archive_dir, xml_path.name)
        shutil.move(str(xml_path), str(archived_path))
        LOGGER.info("Processed %s -> %s and %s", xml_path.name, pdf_path.name, archived_path.name)
        return True
    except Exception as exc:  # pragma: no cover - safety path for runtime processing
        failed_path = get_unique_destination(failed_dir, xml_path.name)
        shutil.move(str(xml_path), str(failed_path))
        LOGGER.exception("Failed to process %s; moved to %s", xml_path.name, failed_path)
        print(f"ERROR: {xml_path.name} could not be processed: {exc}", file=sys.stderr)
        return False


def process_directory(input_dir: Path, archive_dir: Path, pdf_dir: Path, failed_dir: Path) -> None:
    ensure_directories(input_dir, archive_dir, pdf_dir, failed_dir)
    xml_files = sorted(input_dir.glob("*.xml"))
    if not xml_files:
        LOGGER.info("No XML files found in %s", input_dir)
        return

    for xml_file in xml_files:
        process_xml_file(xml_file, archive_dir, pdf_dir, failed_dir)


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert XML device files into PDF reports and archive originals.")
    parser.add_argument("--input", type=Path, required=True, help="Folder containing incoming XML files.")
    parser.add_argument("--archive", type=Path, required=True, help="Folder for processed XML files.")
    parser.add_argument("--pdf", type=Path, required=True, help="Folder for generated PDF reports.")
    parser.add_argument("--failed", type=Path, default=None, help="Optional folder for files that could not be processed.")
    parser.add_argument("--interval-seconds", type=int, default=600, help="Polling interval in seconds. Default: 600.")
    parser.add_argument("--once", action="store_true", help="Process current XML files once and exit.")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

    failed_dir = args.failed or args.archive.parent / "failed_xml"
    ensure_directories(args.input, args.archive, args.pdf, failed_dir)

    if args.once:
        process_directory(args.input, args.archive, args.pdf, failed_dir)
        return 0

    while True:
        try:
            process_directory(args.input, args.archive, args.pdf, failed_dir)
        except Exception as exc:  # pragma: no cover - top-level guard
            LOGGER.exception("Unexpected error during processing: %s", exc)

        time.sleep(args.interval_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
