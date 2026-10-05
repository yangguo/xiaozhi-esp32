"""Host checks for the AI Passport CI size report and flash artifact layout."""

import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "passport_firmware_report", ROOT / "scripts/passport_firmware_report.py"
)
report = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(report)


LEGACY_SIZE = """
Total sizes:
 DRAM .data size:   14956 bytes
 DRAM .bss  size:   15808 bytes
Used static DRAM:   30764 bytes ( 149972 available, 17.0% used)
Used static IRAM:   83918 bytes (  47154 available, 64.0% used)
      Flash code:  559943 bytes
    Flash rodata:  176736 bytes
Total image size: 1290156 bytes (.bin may be padded larger)
"""

TABLE_SIZE = """
                                 Memory Type Usage Summary
┏━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━┓
┃ Memory Type/Section   ┃ Used [bytes] ┃ Used [%] ┃ Remain [bytes] ┃ Total [bytes] ┃
┡━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━┩
│ Flash Code            │        64442 │          │                │               │
│    .text              │        64442 │          │                │               │
│ IRAM                  │        51711 │    39.45 │          79361 │        131072 │
│    .text              │        50683 │    38.67 │                │               │
│ Flash Data            │        30208 │          │                │               │
│    .rodata            │        29952 │          │                │               │
│ DRAM                  │        10716 │     5.93 │         170020 │        180736 │
│    .data              │         8564 │     4.74 │                │               │
└───────────────────────┴──────────────┴──────────┴────────────────┴───────────────┘
Total image size: 154957 bytes (.bin may be padded larger)
"""

# Real ESP-IDF 6.1 idf.py size transcript for this ESP32-C3 board.
# Instruction RAM is not a separate row.
C3_SIZE = """
                            Memory Type Usage Summary
┏━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━┓
┃ Memory Type/Section ┃ Used [bytes] ┃ Used [%] ┃ Remain [bytes] ┃ Total [bytes] ┃
┡━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━┩
│ Flash Code          │      1617508 │          │                │               │
│    .text            │      1617508 │          │                │               │
│ Flash Data          │       667552 │          │                │               │
│    .rodata          │       666936 │          │                │               │
│    .init_array      │          296 │          │                │               │
│    .appdesc         │          256 │          │                │               │
│    .tbss            │           40 │          │                │               │
│    .tdata           │           24 │          │                │               │
│ DRAM                │       109716 │    34.15 │         211580 │        321296 │
│    .text            │        60004 │    18.68 │                │               │
│    .bss             │        29584 │     9.21 │                │               │
│    .data            │        20128 │     6.26 │                │               │
│ RTC SLOW            │           96 │     1.17 │           8096 │          8192 │
│    .rtc_reserved    │           40 │     0.49 │                │               │
│    .force_slow      │           36 │     0.44 │                │               │
│    .text            │           20 │     0.24 │                │               │
└─────────────────────┴──────────────┴──────────┴────────────────┴───────────────┘
Total image size: 2364912 bytes (.bin may be padded larger)
"""


class PassportSizeParseTests(unittest.TestCase):
    def test_legacy_and_idf61_table_report_the_same_fields(self):
        legacy = report.parse_size_report(LEGACY_SIZE)
        self.assertEqual(legacy["dram_used_bytes"], 30764)
        self.assertEqual(legacy["dram_remain_bytes"], 149972)
        self.assertEqual(legacy["iram_used_bytes"], 83918)
        self.assertEqual(legacy["iram_remain_bytes"], 47154)
        self.assertEqual(legacy["flash_used_bytes"], 559943 + 176736)

        table = report.parse_size_report(TABLE_SIZE)
        self.assertEqual(table["dram_used_bytes"], 10716)
        self.assertEqual(table["dram_remain_bytes"], 170020)
        self.assertEqual(table["iram_used_bytes"], 51711)
        self.assertEqual(table["flash_used_bytes"], 64442 + 30208)
        self.assertEqual(table["image_size_bytes"], 154957)

    def test_esp32c3_summary_without_iram_row(self):
        parsed = report.parse_size_report(C3_SIZE)
        self.assertEqual(parsed["flash_code_bytes"], 1617508)
        self.assertEqual(parsed["flash_data_bytes"], 667552)
        self.assertEqual(parsed["flash_used_bytes"], 1617508 + 667552)
        self.assertEqual(parsed["dram_used_bytes"], 109716)
        self.assertEqual(parsed["dram_remain_bytes"], 211580)
        self.assertEqual(parsed["dram_total_bytes"], 321296)
        self.assertEqual(parsed["dram_used_percent"], 34.15)
        self.assertIsNone(parsed["iram_used_bytes"])
        self.assertIsNone(parsed["iram_remain_bytes"])
        self.assertEqual(parsed["image_size_bytes"], 2364912)

        measured = dict(parsed)
        measured["firmware_bytes"] = 0x241790
        measured["assets_bytes"] = 1000
        failures, warnings = report.evaluate_gates(measured, {"known": False})
        self.assertEqual(failures, [])
        self.assertFalse(any("IRAM remain" in warning for warning in warnings))

        text = report._format_report(measured, failures, warnings)
        self.assertIn("PASSPORT_FLASH_USAGE_BYTES=2285060", text)
        self.assertIn("PASSPORT_DRAM_USAGE_BYTES=109716", text)
        self.assertIn("PASSPORT_DRAM_REMAIN_BYTES=211580", text)
        self.assertIn("PASSPORT_IRAM_USAGE_BYTES=n/a", text)
        self.assertIn("PASSPORT_IRAM_REMAIN_BYTES=n/a", text)
        self.assertIn("PASSPORT_FIRMWARE_SIZE_BYTES=2365328", text)
        self.assertIn("no IRAM row", text)
        self.assertIn("Result: PASS", text)

    def test_missing_iram_still_fails_low_dram_remain(self):
        measured = {
            "dram_used_bytes": 300000,
            "dram_remain_bytes": 1024,
            "iram_used_bytes": None,
            "iram_remain_bytes": None,
            "flash_used_bytes": 1000,
            "firmware_bytes": 1000,
            "assets_bytes": 1,
        }
        failures, _warnings = report.evaluate_gates(measured, {"known": False})
        self.assertTrue(any("DRAM remain" in failure for failure in failures))
        self.assertFalse(any("IRAM" in failure for failure in failures))

    def test_iram_remain_fails_only_when_present(self):
        measured = {
            "dram_used_bytes": 1000,
            "dram_remain_bytes": 100000,
            "iram_used_bytes": 1000,
            "iram_remain_bytes": 100,
            "flash_used_bytes": 1000,
            "firmware_bytes": 1000,
            "assets_bytes": 1,
        }
        failures, _warnings = report.evaluate_gates(measured, {"known": False})
        self.assertTrue(any("IRAM remain" in failure for failure in failures))

    def test_checked_in_baseline_is_unknown(self):
        baseline = report.load_baseline(report.DEFAULT_BASELINE)
        self.assertFalse(baseline["known"])
        self.assertIsNone(baseline["dram_used_bytes"])

    def test_unknown_baseline_does_not_fail_a_modest_image(self):
        measured = {
            "dram_used_bytes": 80000,
            "dram_remain_bytes": 100000,
            "iram_used_bytes": 60000,
            "iram_remain_bytes": 20000,
            "flash_used_bytes": 900000,
            "firmware_bytes": 1_200_000,
            "assets_bytes": 400_000,
        }
        failures, warnings = report.evaluate_gates(measured, {"known": False})
        self.assertEqual(failures, [])
        self.assertTrue(any("baseline is unknown" in warning.lower() for warning in warnings))

    def test_known_baseline_fails_a_dram_regression(self):
        measured = {
            "dram_used_bytes": 90000,
            "dram_remain_bytes": 100000,
            "iram_used_bytes": 60000,
            "iram_remain_bytes": 20000,
            "flash_used_bytes": 900000,
            "firmware_bytes": 1_200_000,
            "assets_bytes": 400_000,
        }
        baseline = {
            "known": True,
            "dram_used_bytes": 80000,
            "iram_used_bytes": 60000,
            "flash_used_bytes": 900000,
            "firmware_bytes": 1_200_000,
            "max_dram_increase_bytes": 8192,
            "max_iram_increase_bytes": 2048,
            "max_flash_increase_bytes": 65536,
            "max_firmware_increase_bytes": 65536,
        }
        failures, _warnings = report.evaluate_gates(measured, baseline)
        self.assertTrue(any("DRAM grew" in failure for failure in failures))

    def test_app_image_larger_than_partition_fails(self):
        measured = {
            "dram_used_bytes": 1000,
            "dram_remain_bytes": 100000,
            "iram_used_bytes": 1000,
            "iram_remain_bytes": 20000,
            "flash_used_bytes": 1000,
            "firmware_bytes": report.APP_PARTITION_BYTES + 1,
            "assets_bytes": 1,
        }
        failures, _warnings = report.evaluate_gates(measured, {"known": False})
        self.assertTrue(any("ota_0" in failure for failure in failures))

    def test_partition_ceilings_match_the_8mb_table(self):
        text = (ROOT / "partitions/v2/8m.csv").read_text(encoding="utf-8")
        self.assertIn("ota_0,    app,  ota_0,   0x20000,   0x2f0000,", text)
        self.assertIn("assets,   data, spiffs,  0x600000,  2M", text)
        self.assertEqual(report.APP_PARTITION_BYTES, 0x2F0000)
        self.assertEqual(report.ASSETS_PARTITION_BYTES, 2 * 1024 * 1024)


class PassportArtifactTests(unittest.TestCase):
    def test_stages_recovery_and_incremental_sets(self):
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            build_dir = Path(directory)
            (build_dir / "bootloader").mkdir()
            (build_dir / "partition_table").mkdir()
            (build_dir / "bootloader/bootloader.bin").write_bytes(b"boot")
            (build_dir / "partition_table/partition-table.bin").write_bytes(b"part")
            (build_dir / "xiaozhi.bin").write_bytes(b"app-image")
            (build_dir / "generated_assets.bin").write_bytes(b"assets")
            (build_dir / "merged-binary.bin").write_bytes(b"merged")
            (build_dir / "flasher_args.json").write_text(
                json.dumps(
                    {
                        "bootloader": {"offset": "0x0", "file": "bootloader/bootloader.bin"},
                        "partition_table": {
                            "offset": "0x8000",
                            "file": "partition_table/partition-table.bin",
                        },
                        "app": {"offset": "0x20000", "file": "xiaozhi.bin"},
                        "flash_files": {
                            "0x0": "bootloader/bootloader.bin",
                            "0x8000": "partition_table/partition-table.bin",
                            "0x20000": "xiaozhi.bin",
                            "0x600000": "generated_assets.bin",
                        },
                    }
                ),
                encoding="utf-8",
            )
            code = report.run_report(build_dir, report.DEFAULT_BASELINE, TABLE_SIZE)
            self.assertEqual(code, 0)
            recovery = build_dir / "passport-artifacts/recovery/merged-binary.bin"
            incremental = build_dir / "passport-artifacts/incremental"
            self.assertEqual(recovery.read_bytes(), b"merged")
            self.assertEqual((incremental / "bootloader.bin").read_bytes(), b"boot")
            self.assertEqual((incremental / "partition-table.bin").read_bytes(), b"part")
            self.assertEqual((incremental / "app.bin").read_bytes(), b"app-image")
            self.assertEqual((incremental / "assets.bin").read_bytes(), b"assets")
            flash_args = (incremental / "flash_args").read_text(encoding="utf-8")
            self.assertIn("0x0 bootloader.bin", flash_args)
            self.assertIn("0x8000 partition-table.bin", flash_args)
            self.assertIn("0x20000 app.bin", flash_args)
            self.assertIn("0x600000 assets.bin", flash_args)
            self.assertIn("--flash-size 8MB", flash_args)
            summary = (incremental / "passport-size-report.txt").read_text(encoding="utf-8")
            self.assertIn("PASSPORT_FLASH_USAGE_BYTES=94650", summary)
            self.assertIn("PASSPORT_DRAM_USAGE_BYTES=10716", summary)
            self.assertIn("PASSPORT_IRAM_USAGE_BYTES=51711", summary)
            self.assertIn("PASSPORT_FIRMWARE_SIZE_BYTES=9", summary)

    def _write_bins(self, build_dir: Path) -> None:
        (build_dir / "bootloader").mkdir()
        (build_dir / "partition_table").mkdir()
        (build_dir / "bootloader/bootloader.bin").write_bytes(b"boot")
        (build_dir / "partition_table/partition-table.bin").write_bytes(b"part")
        (build_dir / "xiaozhi.bin").write_bytes(b"app-image")
        (build_dir / "generated_assets.bin").write_bytes(b"assets")
        (build_dir / "ota_data_initial.bin").write_bytes(b"ota")
        (build_dir / "merged-binary.bin").write_bytes(b"merged")

    def test_idf61_flasher_args_use_partition_table_hyphen(self):
        """IDF 6.1 writes ``partition-table``, not ``partition_table``."""
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            build_dir = Path(directory)
            self._write_bins(build_dir)
            (build_dir / "flasher_args.json").write_text(
                json.dumps(
                    {
                        "write_flash_args": [
                            "--flash-mode",
                            "dio",
                            "--flash-size",
                            "8MB",
                            "--flash-freq",
                            "80m",
                        ],
                        "flash_settings": {
                            "flash_mode": "dio",
                            "flash_size": "8MB",
                            "flash_freq": "80m",
                        },
                        "flash_files": {
                            "0x0": "bootloader/bootloader.bin",
                            "0x8000": "partition_table/partition-table.bin",
                            "0xd000": "ota_data_initial.bin",
                            "0x20000": "xiaozhi.bin",
                            "0x600000": "generated_assets.bin",
                        },
                        "bootloader": {
                            "offset": "0x0",
                            "file": "bootloader/bootloader.bin",
                            "encrypted": "false",
                        },
                        "partition-table": {
                            "offset": "0x8000",
                            "file": "partition_table/partition-table.bin",
                            "encrypted": "false",
                        },
                        "app": {
                            "offset": "0x20000",
                            "file": "xiaozhi.bin",
                            "encrypted": "false",
                        },
                        "otadata": {
                            "offset": "0xd000",
                            "file": "ota_data_initial.bin",
                            "encrypted": "false",
                        },
                        "assets": {
                            "offset": "0x600000",
                            "file": "generated_assets.bin",
                            "encrypted": "false",
                        },
                    }
                ),
                encoding="utf-8",
            )
            code = report.run_report(build_dir, report.DEFAULT_BASELINE, TABLE_SIZE)
            self.assertEqual(code, 0)
            incremental = build_dir / "passport-artifacts/incremental"
            flash_args = (incremental / "flash_args").read_text(encoding="utf-8")
            self.assertIn("--flash-mode dio --flash-size 8MB --flash-freq 80m", flash_args)
            self.assertNotIn("ota_data_initial.bin", flash_args)
            self.assertNotIn("ota.bin", flash_args)
            self.assertEqual((incremental / "app.bin").read_bytes(), b"app-image")
            self.assertEqual((incremental / "assets.bin").read_bytes(), b"assets")
            self.assertTrue((build_dir / "passport-artifacts/recovery/merged-binary.bin").is_file())

    def test_flash_files_alone_are_enough(self):
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            build_dir = Path(directory)
            self._write_bins(build_dir)
            (build_dir / "flasher_args.json").write_text(
                json.dumps(
                    {
                        "flash_files": {
                            "0x0": "bootloader/bootloader.bin",
                            "0x8000": "partition_table/partition-table.bin",
                            "0xd000": "ota_data_initial.bin",
                            "0x20000": "xiaozhi.bin",
                            "0x600000": "generated_assets.bin",
                        }
                    }
                ),
                encoding="utf-8",
            )
            code = report.run_report(build_dir, report.DEFAULT_BASELINE, TABLE_SIZE)
            self.assertEqual(code, 0)
            flash_args = (
                build_dir / "passport-artifacts/incremental/flash_args"
            ).read_text(encoding="utf-8")
            self.assertIn("0x8000 partition-table.bin", flash_args)
            self.assertIn("0x20000 app.bin", flash_args)
            self.assertIn("0x600000 assets.bin", flash_args)

    def test_c3_size_text_stages_artifacts_and_passes(self):
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            build_dir = Path(directory)
            self._write_bins(build_dir)
            (build_dir / "flasher_args.json").write_text(
                json.dumps(
                    {
                        "write_flash_args": [
                            "--flash-mode",
                            "dio",
                            "--flash-size",
                            "8MB",
                            "--flash-freq",
                            "80m",
                        ],
                        "flash_files": {
                            "0x0": "bootloader/bootloader.bin",
                            "0x8000": "partition_table/partition-table.bin",
                            "0xd000": "ota_data_initial.bin",
                            "0x20000": "xiaozhi.bin",
                            "0x600000": "generated_assets.bin",
                        },
                        "bootloader": {"offset": "0x0", "file": "bootloader/bootloader.bin"},
                        "partition-table": {
                            "offset": "0x8000",
                            "file": "partition_table/partition-table.bin",
                        },
                        "app": {"offset": "0x20000", "file": "xiaozhi.bin"},
                        "assets": {"offset": "0x600000", "file": "generated_assets.bin"},
                    }
                ),
                encoding="utf-8",
            )
            code = report.run_report(build_dir, report.DEFAULT_BASELINE, C3_SIZE)
            self.assertEqual(code, 0)
            summary = (
                build_dir / "passport-artifacts/recovery/passport-size-report.txt"
            ).read_text(encoding="utf-8")
            self.assertIn("PASSPORT_IRAM_USAGE_BYTES=n/a", summary)
            self.assertIn("PASSPORT_DRAM_REMAIN_BYTES=211580", summary)
            self.assertIn("Result: PASS", summary)
            self.assertTrue(
                (build_dir / "passport-artifacts/incremental/app.bin").is_file()
            )
            self.assertTrue(
                (build_dir / "passport-artifacts/recovery/merged-binary.bin").is_file()
            )


class PassportBoardConfigTests(unittest.TestCase):
    def test_config_stays_c3_8mb_wake_word_off_pm_on(self):
        config = json.loads(
            (ROOT / "main/boards/folotoy/ai-passport/config.json").read_text(encoding="utf-8")
        )
        self.assertEqual(config["target"], "esp32c3")
        self.assertEqual(config["builds"][0]["name"], "ai-passport")
        append = config["builds"][0]["sdkconfig_append"]
        self.assertIn("CONFIG_ESPTOOLPY_FLASHSIZE_8MB=y", append)
        self.assertIn('CONFIG_PARTITION_TABLE_CUSTOM_FILENAME="partitions/v2/8m.csv"', append)
        self.assertIn("CONFIG_USE_ESP_WAKE_WORD=n", append)
        self.assertIn("CONFIG_PM_ENABLE=y", append)
        joined = "\n".join(append)
        self.assertNotIn("SPIRAM", joined)
        self.assertNotIn("CONFIG_USE_ESP_WAKE_WORD=y", joined)
