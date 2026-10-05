#!/usr/bin/env python3
"""Report AI Passport flash/DRAM/IRAM usage and stage CI flash artifacts.

Runs after ``scripts/build.py`` in the Passport GitHub Actions workflow.
Static DRAM remain is the linker's estimate of heap, not a measured free-heap
number: startup allocations make the runtime heap smaller. A checked-in
baseline is required before a growth delta can fail the build.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path


# partitions/v2/8m.csv: ota_0 is 0x2f0000, assets is 2M at 0x600000.
APP_PARTITION_BYTES = 0x2F0000
ASSETS_PARTITION_BYTES = 2 * 1024 * 1024
# Fail only when static memory is nearly gone. These are absolute ceilings,
# not a comparison with a previous image.
DRAM_REMAIN_FAIL_BYTES = 16 * 1024
IRAM_REMAIN_FAIL_BYTES = 1024
DRAM_REMAIN_WARN_BYTES = 48 * 1024
IRAM_REMAIN_WARN_BYTES = 8 * 1024
FIRMWARE_FAIL_PERCENT = 95
FIRMWARE_WARN_PERCENT = 80

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASELINE = Path(__file__).resolve().parent / "passport_size_baseline.json"

_LEGACY_DRAM = re.compile(
    r"Used static DRAM:\s*(-?\d+)\s+bytes(?:\s*\(\s*(-?\d+)\s+available,\s*([0-9.]+)%\s+used\))?",
    re.IGNORECASE,
)
_LEGACY_IRAM = re.compile(
    r"Used static IRAM:\s*(-?\d+)\s+bytes(?:\s*\(\s*(-?\d+)\s+available,\s*([0-9.]+)%\s+used\))?",
    re.IGNORECASE,
)
_LEGACY_FLASH_CODE = re.compile(r"Flash code:\s*(-?\d+)\s+bytes", re.IGNORECASE)
_LEGACY_FLASH_RODATA = re.compile(r"Flash rodata:\s*(-?\d+)\s+bytes", re.IGNORECASE)
_IMAGE_SIZE = re.compile(r"Total image size:\s*(-?\d+)\s+bytes", re.IGNORECASE)


def _blank_report() -> dict:
    return {
        "flash_used_bytes": None,
        "flash_code_bytes": None,
        "flash_data_bytes": None,
        "dram_used_bytes": None,
        "dram_remain_bytes": None,
        "dram_total_bytes": None,
        "dram_used_percent": None,
        "iram_used_bytes": None,
        "iram_remain_bytes": None,
        "iram_total_bytes": None,
        "iram_used_percent": None,
        "image_size_bytes": None,
    }


def _parse_int(text: str) -> int | None:
    stripped = text.strip().replace(",", "")
    if not stripped or stripped == "-":
        return None
    return int(stripped)


def _parse_float(text: str) -> float | None:
    stripped = text.strip().rstrip("%")
    if not stripped or stripped == "-":
        return None
    return float(stripped)


def _parse_legacy(text: str) -> dict | None:
    dram = _LEGACY_DRAM.search(text)
    iram = _LEGACY_IRAM.search(text)
    flash_code = _LEGACY_FLASH_CODE.search(text)
    flash_data = _LEGACY_FLASH_RODATA.search(text)
    if not (dram and iram and flash_code and flash_data):
        return None
    report = _blank_report()
    report["dram_used_bytes"] = int(dram.group(1))
    report["dram_remain_bytes"] = int(dram.group(2)) if dram.group(2) else None
    report["dram_used_percent"] = float(dram.group(3)) if dram.group(3) else None
    if report["dram_remain_bytes"] is not None:
        report["dram_total_bytes"] = report["dram_used_bytes"] + report["dram_remain_bytes"]
    report["iram_used_bytes"] = int(iram.group(1))
    report["iram_remain_bytes"] = int(iram.group(2)) if iram.group(2) else None
    report["iram_used_percent"] = float(iram.group(3)) if iram.group(3) else None
    if report["iram_remain_bytes"] is not None:
        report["iram_total_bytes"] = report["iram_used_bytes"] + report["iram_remain_bytes"]
    report["flash_code_bytes"] = int(flash_code.group(1))
    report["flash_data_bytes"] = int(flash_data.group(1))
    report["flash_used_bytes"] = report["flash_code_bytes"] + report["flash_data_bytes"]
    image = _IMAGE_SIZE.search(text)
    if image:
        report["image_size_bytes"] = int(image.group(1))
    return report


def _parse_table(text: str) -> dict | None:
    """Parse the IDF 6.1 ``idf.py size`` box table."""
    rows: dict[str, tuple[int | None, float | None, int | None, int | None]] = {}
    for raw in text.splitlines():
        if "│" not in raw and "┃" not in raw:
            continue
        parts = [part.strip() for part in raw.replace("┃", "│").split("│")]
        parts = [part for part in parts if part != ""]
        if len(parts) < 2:
            continue
        name = parts[0]
        if name not in {"DRAM", "IRAM", "Flash Code", "Flash Data"}:
            continue
        used = _parse_int(parts[1]) if len(parts) > 1 else None
        percent = _parse_float(parts[2]) if len(parts) > 2 else None
        remain = _parse_int(parts[3]) if len(parts) > 3 else None
        total = _parse_int(parts[4]) if len(parts) > 4 else None
        rows[name] = (used, percent, remain, total)
    if not {"DRAM", "IRAM", "Flash Code", "Flash Data"} <= rows.keys():
        return None
    report = _blank_report()
    report["dram_used_bytes"], report["dram_used_percent"], report["dram_remain_bytes"], report["dram_total_bytes"] = rows["DRAM"]
    report["iram_used_bytes"], report["iram_used_percent"], report["iram_remain_bytes"], report["iram_total_bytes"] = rows["IRAM"]
    report["flash_code_bytes"] = rows["Flash Code"][0]
    report["flash_data_bytes"] = rows["Flash Data"][0]
    if report["flash_code_bytes"] is None or report["flash_data_bytes"] is None:
        return None
    report["flash_used_bytes"] = report["flash_code_bytes"] + report["flash_data_bytes"]
    image = _IMAGE_SIZE.search(text)
    if image:
        report["image_size_bytes"] = int(image.group(1))
    return report


def parse_size_report(text: str) -> dict:
    report = _parse_legacy(text) or _parse_table(text)
    if report is None or report["dram_used_bytes"] is None or report["iram_used_bytes"] is None:
        raise ValueError("Could not parse Flash, DRAM, and IRAM from idf.py size output")
    if report["flash_used_bytes"] is None:
        raise ValueError("Could not parse flash usage from idf.py size output")
    return report


def load_baseline(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1:
        raise ValueError(f"{path}: expected schema_version 1")
    if not isinstance(data.get("known"), bool):
        raise ValueError(f"{path}: known must be a boolean")
    return data


def _run_size_tool(build_dir: Path) -> str:
    map_file = build_dir / "xiaozhi.map"
    commands = [
        ["idf.py", "size"],
        ["idf_size.py", str(map_file)],
    ]
    errors: list[str] = []
    for command in commands:
        if command[0] == "idf_size.py" and not map_file.is_file():
            continue
        try:
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
            )
        except FileNotFoundError:
            errors.append(f"{command[0]} not found")
            continue
        output = (completed.stdout or "") + ("\n" + completed.stderr if completed.stderr else "")
        if completed.returncode == 0 or "DRAM" in output or "Used static DRAM" in output:
            print(output)
            return output
        errors.append(f"{' '.join(command)} failed ({completed.returncode})")
    raise RuntimeError("idf.py size failed: " + "; ".join(errors))


def _flash_file(build_dir: Path, relative: str) -> Path:
    path = build_dir / relative
    if not path.is_file():
        raise FileNotFoundError(f"Missing flash image {path}")
    return path


def resolve_flash_images(build_dir: Path) -> dict[str, tuple[int, Path]]:
    """Return offset and path for bootloader, partition table, app, and assets."""
    flasher = build_dir / "flasher_args.json"
    if flasher.is_file():
        data = json.loads(flasher.read_text(encoding="utf-8"))
        images: dict[str, tuple[int, Path]] = {}
        for key, label in (
            ("bootloader", "bootloader"),
            ("partition_table", "partition-table"),
            ("app", "app"),
        ):
            entry = data.get(key) or {}
            relative = entry.get("file")
            offset = entry.get("offset")
            if not relative or offset is None:
                raise ValueError(f"{flasher} is missing {key}.file or {key}.offset")
            images[label] = (int(str(offset), 0), _flash_file(build_dir, relative))
        assets = None
        for offset, relative in (data.get("flash_files") or {}).items():
            name = Path(relative).name.lower()
            if "asset" in name:
                assets = (int(str(offset), 0), _flash_file(build_dir, relative))
                break
        if assets is None:
            raise ValueError(f"{flasher} has no assets image")
        images["assets"] = assets
        return images

    return {
        "bootloader": (0x0, _flash_file(build_dir, "bootloader/bootloader.bin")),
        "partition-table": (0x8000, _flash_file(build_dir, "partition_table/partition-table.bin")),
        "app": (0x20000, _flash_file(build_dir, "xiaozhi.bin")),
        "assets": (0x600000, _flash_file(build_dir, "generated_assets.bin")),
    }


def stage_artifacts(build_dir: Path, images: dict[str, tuple[int, Path]], report_text: str, report_json: dict) -> Path:
    root = build_dir / "passport-artifacts"
    recovery = root / "recovery"
    incremental = root / "incremental"
    if root.exists():
        shutil.rmtree(root)
    recovery.mkdir(parents=True)
    incremental.mkdir(parents=True)

    merged = build_dir / "merged-binary.bin"
    if not merged.is_file():
        raise FileNotFoundError(f"Missing full flash image {merged}")
    shutil.copy2(merged, recovery / "merged-binary.bin")

    names = {
        "bootloader": "bootloader.bin",
        "partition-table": "partition-table.bin",
        "app": "app.bin",
        "assets": "assets.bin",
    }
    ordered = sorted(images.items(), key=lambda item: item[1][0])
    args = [
        "--flash_mode dio",
        "--flash_freq 80m",
        "--flash_size 8MB",
    ]
    for label, (offset, source) in ordered:
        filename = names[label]
        shutil.copy2(source, incremental / filename)
        args.append(f"0x{offset:x} {filename}")
    (incremental / "flash_args").write_text("\n".join(args) + "\n", encoding="utf-8")

    for directory in (recovery, incremental):
        (directory / "passport-size-report.txt").write_text(report_text, encoding="utf-8")
        (directory / "passport-size-report.json").write_text(
            json.dumps(report_json, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return root


def evaluate_gates(measured: dict, baseline: dict) -> tuple[list[str], list[str]]:
    """Return (failures, warnings). Failures are absolute or against a known baseline."""
    failures: list[str] = []
    warnings: list[str] = []

    firmware = measured["firmware_bytes"]
    if firmware > APP_PARTITION_BYTES:
        failures.append(
            f"Firmware size {firmware} bytes exceeds the ota_0 partition "
            f"({APP_PARTITION_BYTES} bytes)"
        )
    elif firmware * 100 > APP_PARTITION_BYTES * FIRMWARE_WARN_PERCENT:
        warnings.append(
            f"Firmware size {firmware} bytes is over {FIRMWARE_WARN_PERCENT}% of the "
            f"{APP_PARTITION_BYTES}-byte app partition"
        )
    if firmware * 100 > APP_PARTITION_BYTES * FIRMWARE_FAIL_PERCENT:
        failures.append(
            f"Firmware size {firmware} bytes is over {FIRMWARE_FAIL_PERCENT}% of the "
            f"{APP_PARTITION_BYTES}-byte app partition"
        )

    assets = measured["assets_bytes"]
    if assets > ASSETS_PARTITION_BYTES:
        failures.append(
            f"Assets image {assets} bytes exceeds the assets partition "
            f"({ASSETS_PARTITION_BYTES} bytes)"
        )

    dram_remain = measured.get("dram_remain_bytes")
    iram_remain = measured.get("iram_remain_bytes")
    if dram_remain is None or iram_remain is None:
        warnings.append(
            "DRAM/IRAM remain was not in the size report, so the absolute "
            "memory ceiling was not applied"
        )
    else:
        if dram_remain < DRAM_REMAIN_FAIL_BYTES:
            failures.append(
                f"DRAM remain {dram_remain} bytes is below {DRAM_REMAIN_FAIL_BYTES} "
                "(static estimate of heap is nearly exhausted)"
            )
        elif dram_remain < DRAM_REMAIN_WARN_BYTES:
            warnings.append(
                f"DRAM remain {dram_remain} bytes is below {DRAM_REMAIN_WARN_BYTES}"
            )
        if iram_remain < IRAM_REMAIN_FAIL_BYTES:
            failures.append(
                f"IRAM remain {iram_remain} bytes is below {IRAM_REMAIN_FAIL_BYTES}"
            )
        elif iram_remain < IRAM_REMAIN_WARN_BYTES:
            warnings.append(
                f"IRAM remain {iram_remain} bytes is below {IRAM_REMAIN_WARN_BYTES}"
            )

    if not baseline.get("known"):
        warnings.append(
            "Size baseline is unknown, so the growth gate is not enforced. "
            "Copy this report into scripts/passport_size_baseline.json and set "
            "known to true after the first measured image."
        )
        return failures, warnings

    comparisons = (
        ("dram_used_bytes", "max_dram_increase_bytes", "DRAM"),
        ("iram_used_bytes", "max_iram_increase_bytes", "IRAM"),
        ("flash_used_bytes", "max_flash_increase_bytes", "Flash"),
        ("firmware_bytes", "max_firmware_increase_bytes", "Firmware size"),
    )
    for field, limit_field, label in comparisons:
        current = measured[field]
        reference = baseline.get(field)
        limit = baseline.get(limit_field)
        if reference is None or limit is None:
            failures.append(f"Baseline is marked known but {field} or {limit_field} is missing")
            continue
        growth = current - reference
        if growth > limit:
            failures.append(
                f"{label} grew by {growth} bytes (now {current}, baseline {reference}, "
                f"allowed +{limit})"
            )
    return failures, warnings


def _format_report(measured: dict, failures: list[str], warnings: list[str]) -> str:
    dram_remain = measured.get("dram_remain_bytes")
    iram_remain = measured.get("iram_remain_bytes")
    lines = [
        "AI Passport firmware size report",
        "target: esp32c3  flash: 8MB  psram: no  wake_word: off",
        f"PASSPORT_FLASH_USAGE_BYTES={measured['flash_used_bytes']}",
        f"PASSPORT_DRAM_USAGE_BYTES={measured['dram_used_bytes']}",
        f"PASSPORT_DRAM_REMAIN_BYTES={dram_remain if dram_remain is not None else 'unknown'}",
        f"PASSPORT_IRAM_USAGE_BYTES={measured['iram_used_bytes']}",
        f"PASSPORT_IRAM_REMAIN_BYTES={iram_remain if iram_remain is not None else 'unknown'}",
        f"PASSPORT_FIRMWARE_SIZE_BYTES={measured['firmware_bytes']}",
        f"PASSPORT_ASSETS_SIZE_BYTES={measured['assets_bytes']}",
        (
            f"Flash usage: {measured['flash_used_bytes']} bytes "
            f"(code {measured['flash_code_bytes']}, data {measured['flash_data_bytes']})"
        ),
        (
            f"DRAM usage: {measured['dram_used_bytes']} bytes used, "
            f"{dram_remain if dram_remain is not None else 'unknown'} bytes remain"
        ),
        (
            f"IRAM usage: {measured['iram_used_bytes']} bytes used, "
            f"{iram_remain if iram_remain is not None else 'unknown'} bytes remain"
        ),
        (
            f"Firmware size: {measured['firmware_bytes']} bytes "
            f"(app partition {APP_PARTITION_BYTES} bytes)"
        ),
        "DRAM remain is the static heap estimate from the linker, not measured free heap.",
    ]
    if warnings:
        lines.append("Warnings:")
        lines.extend(f"  {warning}" for warning in warnings)
    if failures:
        lines.append("Failures:")
        lines.extend(f"  {failure}" for failure in failures)
        lines.append("Result: FAIL")
    else:
        lines.append("Result: PASS")
    return "\n".join(lines) + "\n"


def _write_step_summary(report_text: str) -> None:
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary:
        return
    with open(summary, "a", encoding="utf-8") as handle:
        handle.write("## AI Passport firmware size\n\n```\n")
        handle.write(report_text)
        handle.write("```\n")


def build_measured(size_text: str, images: dict[str, tuple[int, Path]]) -> dict:
    parsed = parse_size_report(size_text)
    measured = dict(parsed)
    measured["firmware_bytes"] = images["app"][1].stat().st_size
    measured["assets_bytes"] = images["assets"][1].stat().st_size
    return measured


def run_report(
    build_dir: Path,
    baseline_path: Path,
    size_text: str | None = None,
) -> int:
    images = resolve_flash_images(build_dir)
    if size_text is None:
        size_text = _run_size_tool(build_dir)
    measured = build_measured(size_text, images)
    baseline = load_baseline(baseline_path)
    failures, warnings = evaluate_gates(measured, baseline)
    report_text = _format_report(measured, failures, warnings)
    print(report_text, end="")
    for warning in warnings:
        print(f"::warning::{warning}")
    for failure in failures:
        print(f"::error::{failure}")
    _write_step_summary(report_text)
    stage_artifacts(build_dir, images, report_text, measured)
    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-dir", type=Path, default=Path("build"))
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument(
        "--size-text",
        type=Path,
        help="Parse this idf.py size transcript instead of running the tool",
    )
    args = parser.parse_args(argv)
    size_text = args.size_text.read_text(encoding="utf-8") if args.size_text else None
    try:
        return run_report(args.build_dir, args.baseline, size_text)
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as error:
        print(f"AI Passport firmware size report failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
