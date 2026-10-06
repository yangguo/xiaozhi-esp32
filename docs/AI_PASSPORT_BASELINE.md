# AI Passport Baseline (M0 lightweight)

> Local IDF is unavailable (`idf.py` not installed); build/size rows below come from CI workflow `Build AI Passport` until a local IDF 6.1 run exists.

- Fork HEAD: `9753ba28220138eaf68b0b4ea37c7a3ad96deae1`
- Upstream base: `0d576d3d4c049c6f55eaf879725dc23e516511b4`
- Upstream divergence: 10 ahead / 0 behind (measured 2026-10-06)
- Board: `folotoy/ai-passport`, ESP32-C3, 8 MB flash, no PSRAM
- Config: `partitions/v2/8m.csv`, PM enable, wake word off
- CI workflow: `.github/workflows/ai-passport.yml` (unittest + build + `passport_firmware_report.py` + recovery/incremental artifacts)
- CI run: https://github.com/yangguo/xiaozhi-esp32/actions/runs/37420264695 (SHA `9753ba28220138eaf68b0b4ea37c7a3ad96deae1`) — recovery artifact SHA256: `659572548058d2cd7f0bba18a32d611c58f17a2c1f10803a690245dccc664ec2`, app bin bytes: 2370560 (`0x242c00`), free OTA headroom: 693.0 KiB (709632 bytes, `0xad400`, 23% of `0x2f0000` OTA slot free; 3080192 − 2370560 = 709632)
- Static sizes (from `scripts/passport_size_baseline.json`, recorded run 37334194292; live values for run 37420264695 were code 1622262 / data 668032): DRAM used 109716, IRAM used n/a (ESP32-C3 size summary has no IRAM row), flash code 1617508, flash rodata 667552 (flash data; total flash 2285060)
- Runtime heap: NOT MEASURED — internal free, DMA free, largest block, stack HWM all pending真机
- Power: NOT MEASURED — Active/Dim/Soft/Deep currents and 60/360/2160 s timings pending真机
- Voice smoke: NOT DONE — one keypress voice + soft/deep wake voice pending真机
- Blockers: no local ESP-IDF; no power meter hooked up; no device serial captured yet
