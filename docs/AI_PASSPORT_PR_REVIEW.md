# AI Passport PR review follow-up — 2026-10-11

## Integration order and gates

1. PR #4 (`p0-closeout`) was merged after its current-head GitHub Actions build passed: merge commit `53f1fd86ab3702df8342195576f893b6d280d313`. Its patch changes tests and historical baseline only.
2. PR #5 (`passport/subtitles`) has been synchronized with the merged `main`. Its remaining diff contains the subtitle implementation, regression tests and this review record.
3. Keep PR #5 and its branch until the synchronized-head GitHub Actions build and physical display/audio/heap checks pass. Do not interpret an old successful build or an empty check list as current acceptance.
4. Delete the remote feature branches only after integration. Preserve unrelated local documentation edits before local branch cleanup.

## PR #4: three review findings addressed

- Offline PTT test now asserts the actual arm decision's `suppress_click` and propagates it into the next click instead of forcing `pass`.
- Abort test now exercises the closed-channel activity resolver and Thinking cleanup instead of expecting Thinking from a normal release.
- Removed the Python-only UTF-8 truncation test: PR #4 contains no production truncation implementation. Production helper coverage belongs to PR #5.
- Baseline document explicitly labels the October 6 measurements as historical, not acceptance of the later upstream merge.

Validation: 140 host tests passed. Injected regressions (offline click suppression and ignoring channel closure) each fail the corrected test. No firmware behavior changes are introduced by this review-fix commit.

## PR #5: subtitle lifecycle and dynamic glyphs

- Explicit `assistant` empty content clears the cached answer and preserves the latest user STT. A later notification starts with a fresh answer. Empty user/system messages retain their existing semantics.
- Corrected the UTF-8 truncator when the budget is exactly the three-byte ellipsis size. Tests exercise the production C++ helper with Chinese, emoji, and budgets from zero to nine bytes.
- Passport re-pushes a bounded union of dynamic glyph batches before rendering accumulated text. Empty incoming batches retain the union rather than invoking the shared no-PSRAM cache-clear path.
- The board-owned union holds at most **64 glyphs / 8 KiB of bitmap data**. When the merged union exceeds either limit, or bpp changes, discard the previous subtitle segment before showing the next message. This intentionally prioritizes readable current text over retaining text with missing glyphs; the retained STT can also disappear at this fallback boundary.
- A single batch larger than the board retention limit is passed to the existing shared display cache as a standalone segment. It is not duplicated in the board cache; its text is reset before the following batch. This does not expand the shared cache's existing limits.
- Explicit glyph invalidation clears board subtitle state too. Ordinary empty glyph batches with only built-in-font text do not erase STT.

Validation: 151 host tests passed. The glyph harness compiles the production policy and the actual `PassportDisplay::AddTextGlyphs` / `ClearTextGlyphs` method bodies, using host allocator stubs and a fake shared display with the no-PSRAM replacement contract. Ten scenarios cover union replay, empty batches, replacement, bpp changes, both limits, oversized batches, and display dispatch. An injected batch-replacement regression fails the display union scenario. Touched C++ files pass clang-format checks.

These host checks do not compile all ESP-IDF/LVGL integration or demonstrate physical rendering. The 8 KiB bound applies to the additional retained bitmap data, not total heap usage: protocol input, glyph descriptors, shared cache entries and its rebuilt font also consume memory.

## GitHub Actions restored and build evidence

On October 11, Actions were restored through the signed-in repository Actions page's **I understand my workflows, go ahead and re-enable them** button. The page confirmed **Actions Enabled**; workflow dispatch then succeeded. The repository/workflow permissions APIs alone had not lifted the fork suspension.

- PR #4 head `190efe63f4cb308f38f0c802671a6710275410d5`: [run 38107985183](https://github.com/yangguo/xiaozhi-esp32/actions/runs/38107985183) passed host tests, ESP-IDF 6.1 firmware build, firmware size gate and artifact upload. App size: 2,370,784 B; app partition: 3,080,192 B; remaining: 709,408 B. Static DRAM usage: 109,716 B; the linker estimate is not live free heap.
- PR #5 head `e7850d6a305727d150fa0bd20c2c1792ba804679`: [run 38107987874](https://github.com/yangguo/xiaozhi-esp32/actions/runs/38107987874) passed the same gates. The subsequent main merge did not change its source tree. The final synchronized/documented head still needs its own CI result.

Use GitHub Actions only for firmware builds; no local Docker build was performed.

## Physical acceptance status

No Passport USB device was detected on this host. The visible `/dev/cu.usbmodem2020_12_222` identifies as LDR2001 (VID 0x2d79 / PID 0x0003), so it is excluded from Passport testing. An earlier candidate connection attempt produced no ESP32 data and created no flash backup. No flash write was attempted.

Connect and wake the Passport, verify its USB identity and installed firmware, then follow the checklist below. If it currently runs a chess/game app, confirm switching back to XiaoZhi before replacing that application. Hardware acceptance remains **NOT TESTED**.

## PR #5 physical acceptance checklist

- Use current-head GitHub Actions incremental `app.bin` after firmware size/report checks pass; back up the device and write only the established application partition to preserve configuration. Flashing is a separate authorized operation.
- Two user turns, multiple assistant sentences, Chinese/English/Japanese/emoji, and characters supplied through dynamic glyphs: STT and prior sentences remain readable while within the retention budget.
- A sentence with no pushed glyphs after a sentence with pushed glyphs must preserve older glyphs.
- Consecutive notifications with no STT between them: no old notification text reappears.
- Exercise glyph budget and bpp fallback: a fresh segment appears without referencing discarded glyphs.
- Long answers paginate within the rounded viewport; verify transitions between listening, thinking, speaking, timeout and idle.
- Record free/minimum heap during at least 100 conversation/notification cycles, listening/playback continuity, and dim/soft/deep sleep behavior. Compare against the historical baseline, and retain a known-good app image for rollback.
