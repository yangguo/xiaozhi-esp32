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

int main(int argc, char** argv) {
    if (argc == 5 && strcmp(argv[1], "span") == 0) {
        dump_span((int32_t)atoi(argv[2]), (int32_t)atoi(argv[3]), (int32_t)atoi(argv[4]));
        return 0;
    }
    if (argc == 2 && strcmp(argv[1], "mask") == 0) {
        dump_mask();
        return 0;
    }
    fprintf(stderr, "usage: span W H R | mask\n");
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


if __name__ == "__main__":
    unittest.main()
