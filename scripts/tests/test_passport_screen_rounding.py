"""Host checks for the AI Passport rounded-glass mask.

The inset math is checked against an independent square-root formula, not
against a second copy of the C loop. A flush-strip case checks that pixels
outside the glass become black and the rest of the strip is left alone.
"""

import math
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ROUNDING_C = ROOT / "main/boards/folotoy/ai-passport/screen_rounding.c"
ROUNDING_H = ROUNDING_C.with_suffix(".h")

HARNESS = r"""
#include "screen_rounding.h"

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static void dump_span(int32_t width, int32_t height, int32_t radius) {
    for (int32_t y = -1; y <= height; ++y) {
        int32_t x1 = -1;
        int32_t x2 = -1;
        bool ok = passport_rounded_row_span(y, width, height, radius, &x1, &x2);
        printf("%d %d %d %d\n", (int)y, ok ? 1 : 0, (int)x1, (int)x2);
    }
}

static void dump_mask(void) {
    enum { kWidth = 240, kHeight = 320, kRadius = 30, kX1 = 0, kX2 = 39, kY = 0 };
    uint16_t row[40];
    for (int i = 0; i < 40; ++i) {
        row[i] = 0xBEEF;
    }
    passport_mask_rgb565_area((uint8_t*)row, sizeof(row), kX1, kY, kX2, kY,
                              kWidth, kHeight, kRadius);
    for (int i = 0; i < 40; ++i) {
        printf("%04x%s", row[i], i == 39 ? "\n" : " ");
    }

    uint16_t middle[8];
    for (int i = 0; i < 8; ++i) {
        middle[i] = 0x1111;
    }
    passport_mask_rgb565_area((uint8_t*)middle, sizeof(middle), 100, 160, 107, 160,
                              kWidth, kHeight, kRadius);
    for (int i = 0; i < 8; ++i) {
        printf("%04x%s", middle[i], i == 7 ? "\n" : " ");
    }
}

static void dump_rect(const passport_rect_t* rect) {
    if (rect == NULL) {
        printf("none\n");
        return;
    }
    printf("%d %d %d %d\n", (int)rect->x, (int)rect->y, (int)rect->width, (int)rect->height);
}

int main(int argc, char** argv) {
    if (argc == 5 && strcmp(argv[1], "span") == 0) {
        dump_span((int32_t)atoi(argv[2]), (int32_t)atoi(argv[3]), (int32_t)atoi(argv[4]));
        return 0;
    }
    if (argc == 2 && strcmp(argv[1], "mask") == 0) {
        dump_mask();
        return 0;
    }
    if (argc == 5 && strcmp(argv[1], "safe") == 0) {
        passport_rect_t rect;
        if (!passport_glass_safe_rect((int32_t)atoi(argv[2]), (int32_t)atoi(argv[3]),
                                      (int32_t)atoi(argv[4]), &rect)) {
            printf("none\n");
            return 0;
        }
        dump_rect(&rect);
        return 0;
    }
    if (argc == 7 && strcmp(argv[1], "subtitle") == 0) {
        passport_rect_t rect;
        if (!passport_subtitle_viewport((int32_t)atoi(argv[2]), (int32_t)atoi(argv[3]),
                                        (int32_t)atoi(argv[4]), (int32_t)atoi(argv[5]),
                                        (int32_t)atoi(argv[6]), &rect)) {
            printf("none\n");
            return 0;
        }
        dump_rect(&rect);
        return 0;
    }
    if (argc == 9 && strcmp(argv[1], "inside") == 0) {
        passport_rect_t rect = {(int32_t)atoi(argv[5]), (int32_t)atoi(argv[6]),
                                (int32_t)atoi(argv[7]), (int32_t)atoi(argv[8])};
        bool ok = passport_rect_inside_glass(&rect, (int32_t)atoi(argv[2]), (int32_t)atoi(argv[3]),
                                             (int32_t)atoi(argv[4]));
        printf("%d\n", ok ? 1 : 0);
        return 0;
    }
    if (argc == 5 && strcmp(argv[1], "pages") == 0) {
        int32_t content = (int32_t)atoi(argv[2]);
        int32_t viewport = (int32_t)atoi(argv[3]);
        int32_t page = (int32_t)atoi(argv[4]);
        printf("%d %d\n", (int)passport_subtitle_page_count(content, viewport),
               (int)passport_subtitle_page_offset(page, content, viewport));
        return 0;
    }
    if (argc == 2 && strcmp(argv[1], "place") == 0) {
        passport_widget_place_t status;
        passport_status_bar_place(&status);
        printf("status %d %d %d %d\n", (int)status.anchor, (int)status.x, (int)status.y,
               status.scrollable ? 1 : 0);
        passport_rect_t viewport = {0, 186, 240, 104};
        passport_widget_place_t subtitle;
        passport_subtitle_bar_place(&viewport, &subtitle);
        printf("subtitle %d %d %d %d\n", (int)subtitle.anchor, (int)subtitle.x, (int)subtitle.y,
               subtitle.scrollable ? 1 : 0);
        printf("bottom %d\n", (int)passport_bottom_mid_layout_y(320, 104, 186));
        printf("label %d\n", (int)passport_subtitle_label_y(104));
        return 0;
    }
    if (argc == 9 && strcmp(argv[1], "activity") == 0) {
        passport_rect_t safe = {(int32_t)atoi(argv[2]), (int32_t)atoi(argv[3]),
                                (int32_t)atoi(argv[4]), (int32_t)atoi(argv[5])};
        passport_rect_t subtitle = {safe.x, (int32_t)atoi(argv[6]), safe.width, 1};
        passport_rect_t line;
        if (!passport_activity_line(&safe, &subtitle, (int32_t)atoi(argv[7]),
                                    (int32_t)atoi(argv[8]), &line)) {
            printf("none\n");
            return 0;
        }
        dump_rect(&line);
        return 0;
    }
    fprintf(stderr, "usage: span W H R | mask | safe W H R | subtitle W H R LINE HALF | "
                    "inside W H R X Y W H | pages CONTENT VIEW PAGE | place | "
                    "activity SX SY SW SH SUBY LINE RESERVE\n");
    return 2;
}
"""


def reference_span(y, width, height, radius):
    """Largest quarter-circle inset, independent of the C loop."""
    if width <= 0 or height <= 0 or y < 0 or y >= height:
        return None
    if radius <= 0:
        return (0, width - 1)
    radius = min(radius, min(width, height) // 2)
    if radius <= 0 or radius <= y < height - radius:
        return (0, width - 1)
    edge_y = radius - y if y < radius else y - (height - 1 - radius)
    inset = math.isqrt(radius * radius - edge_y * edge_y)
    x1 = max(0, radius - inset)
    x2 = min(width - 1, width - radius + inset - 1)
    if x1 > x2:
        return None
    return (x1, x2)


class PassportScreenRoundingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workdir = tempfile.TemporaryDirectory()
        harness = Path(cls.workdir.name) / "harness.c"
        harness.write_text(HARNESS)
        cls.binary = Path(cls.workdir.name) / "rounding"
        subprocess.check_call(
            [
                "gcc",
                "-std=c11",
                "-Wall",
                "-Wextra",
                "-Werror",
                f"-I{ROUNDING_H.parent}",
                str(ROUNDING_C),
                str(harness),
                "-o",
                str(cls.binary),
            ]
        )

    @classmethod
    def tearDownClass(cls):
        cls.workdir.cleanup()

    def spans(self, width, height, radius):
        output = subprocess.check_output(
            [str(self.binary), "span", str(width), str(height), str(radius)],
            text=True,
        )
        rows = {}
        for line in output.splitlines():
            y, ok, x1, x2 = (int(part) for part in line.split())
            rows[y] = (ok, x1, x2)
        return rows

    def test_passport_glass_matches_quarter_circle(self):
        width, height, radius = 240, 320, 30
        rows = self.spans(width, height, radius)
        self.assertEqual(rows[-1][0], 0)
        self.assertEqual(rows[height][0], 0)
        for y in range(height):
            expected = reference_span(y, width, height, radius)
            ok, x1, x2 = rows[y]
            self.assertEqual((ok, x1, x2), (1, expected[0], expected[1]), y)
        # Top row of a 30 px radius leaves the outer 30 px black.
        self.assertEqual(rows[0][1:], (30, 209))
        # The straight section is the full panel.
        self.assertEqual(rows[radius][1:], (0, width - 1))
        self.assertEqual(rows[height - radius - 1][1:], (0, width - 1))
        # Top and bottom are symmetric.
        self.assertEqual(rows[0][1:], rows[height - 1][1:])
        self.assertEqual(rows[15][1:], rows[height - 1 - 15][1:])

    def test_radius_clamps_and_zero_radius_is_square(self):
        tiny = self.spans(10, 10, 30)
        for y in range(10):
            expected = reference_span(y, 10, 10, 30)
            ok, x1, x2 = tiny[y]
            if expected is None:
                self.assertEqual(ok, 0, y)
            else:
                self.assertEqual((ok, x1, x2), (1, expected[0], expected[1]), y)
        # Radius equal to half the short side leaves the corner rows outside the glass.
        self.assertEqual(tiny[0][0], 0)
        square = self.spans(240, 320, 0)
        self.assertEqual(square[0], (1, 0, 239))
        self.assertEqual(square[319], (1, 0, 239))

    def test_flush_strip_blacks_only_the_corner(self):
        first, middle = subprocess.check_output(
            [str(self.binary), "mask"], text=True
        ).splitlines()
        pixels = [int(word, 16) for word in first.split()]
        # Visible span on y=0 starts at x=30, so a strip covering x=0..39
        # blacks out 0..29 and keeps 30..39.
        self.assertEqual(pixels[:30], [0] * 30)
        self.assertEqual(pixels[30:], [0xBEEF] * 10)
        self.assertEqual([int(word, 16) for word in middle.split()], [0x1111] * 8)

    def _rect(self, *args):
        line = subprocess.check_output([str(self.binary), *args], text=True).strip()
        if line == "none":
            return None
        x, y, w, h = (int(part) for part in line.split())
        return (x, y, w, h)

    def test_safe_rect_is_the_full_width_band(self):
        # 240x320, radius 30: rows 30..289 are the straight section.
        self.assertEqual(self._rect("safe", "240", "320", "30"), (0, 30, 240, 260))
        self.assertEqual(self._rect("safe", "240", "320", "0"), (0, 0, 240, 320))
        # A radius that consumes the short side leaves no full-width row.
        self.assertIsNone(self._rect("safe", "10", "10", "30"))

    def test_subtitle_stays_inside_the_glass_and_below_the_emoji(self):
        # 32 px emoji (half 16) centered at y=160, line height 26.
        # Slice under the emoji is y=176..290 (114 px) -> 4 lines, bottom aligned.
        rect = self._rect("subtitle", "240", "320", "30", "26", "16")
        self.assertEqual(rect, (0, 186, 240, 104))
        rows = self.spans(240, 320, 30)
        x, y, w, h = rect
        for row in range(y, y + h):
            ok, x1, x2 = rows[row]
            self.assertEqual(ok, 1, row)
            self.assertLessEqual(x1, x, row)
            self.assertGreaterEqual(x2, x + w - 1, row)
        self.assertEqual(
            subprocess.check_output(
                [str(self.binary), "inside", "240", "320", "30", "0", "186", "240", "104"],
                text=True,
            ).strip(),
            "1",
        )
        # The top row of the glass is not a safe place for a full-width label.
        self.assertEqual(
            subprocess.check_output(
                [str(self.binary), "inside", "240", "320", "30", "0", "0", "240", "20"],
                text=True,
            ).strip(),
            "0",
        )
        # A line taller than the safe rect does not invent a viewport.
        self.assertIsNone(self._rect("subtitle", "240", "320", "30", "300", "16"))
        # Zero radius uses the whole panel, still in whole lines under the emoji.
        # 320 - 176 = 144 px, 5 lines of 26, bottom aligned at y=190.
        square = self._rect("subtitle", "240", "320", "0", "26", "16")
        self.assertEqual(square, (0, 190, 240, 130))

    def test_status_stays_at_the_top_and_subtitle_is_not_scrolled(self):
        # anchor 1 is top-middle, anchor 0 is top-left. The last field is scrollable.
        status, subtitle, bottom, label = subprocess.check_output(
            [str(self.binary), "place"], text=True
        ).splitlines()
        self.assertEqual(status, "status 1 0 0 0")
        self.assertEqual(subtitle, "subtitle 0 0 186 0")
        # LVGL 9 would lay out BOTTOM_MID plus set_pos(0, 186) at this y, below
        # a 320 px panel, which is what left a scrollbar instead of the text.
        self.assertEqual(bottom, "bottom 402")
        self.assertGreater(int(bottom.split()[1]), 320)
        self.assertEqual(label, "label -104")

    def test_subtitle_pages_clamp_the_last_page(self):
        def pages(content, viewport, page):
            count, offset = (
                int(part)
                for part in subprocess.check_output(
                    [str(self.binary), "pages", str(content), str(viewport), str(page)],
                    text=True,
                ).split()
            )
            return count, offset

        self.assertEqual(pages(104, 104, 0), (1, 0))
        self.assertEqual(pages(0, 104, 0), (1, 0))
        self.assertEqual(pages(105, 104, 0), (2, 0))
        # Last page shows the tail (offset 1) instead of a blank 104 px jump.
        self.assertEqual(pages(105, 104, 1), (2, 1))
        self.assertEqual(pages(300, 104, 2), (3, 196))
        self.assertEqual(pages(300, 104, 99), (3, 196))
        self.assertEqual(pages(300, 104, -1), (3, 0))
        self.assertEqual(pages(300, 0, 0), (1, 0))

    def test_activity_line_sits_between_status_and_subtitle(self):
        # Safe (0, 30, 240, 260), subtitle top y=186, 26 px line, 28 px status row.
        # y = 30 + 28 = 58, and 58 + 26 stays above the subtitle.
        self.assertEqual(
            self._rect("activity", "0", "30", "240", "260", "186", "26", "28"),
            (0, 58, 240, 26),
        )
        # Touching the subtitle top is still inside the gap.
        self.assertEqual(
            self._rect("activity", "0", "30", "240", "260", "84", "26", "28"),
            (0, 58, 240, 26),
        )
        # One pixel of overlap with the subtitle is rejected.
        self.assertIsNone(self._rect("activity", "0", "30", "240", "260", "83", "26", "28"))
        # A line that runs past the safe rect is rejected.
        self.assertIsNone(self._rect("activity", "0", "30", "240", "260", "186", "26", "250"))
        self.assertIsNone(self._rect("activity", "0", "30", "240", "260", "186", "0", "28"))
        self.assertIsNone(self._rect("activity", "0", "30", "240", "260", "186", "26", "-1"))


if __name__ == "__main__":
    unittest.main()
