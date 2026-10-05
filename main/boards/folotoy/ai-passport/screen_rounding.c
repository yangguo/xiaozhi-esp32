#include "screen_rounding.h"

#include <string.h>

// Quarter-circle inset. Ported from FoloToy/folo-ai-passport-xiaozhi
// main/display/lvgl_screen_rounding.c so the mask matches the official panel.

static int32_t clamp_radius(int32_t width, int32_t height, int32_t radius) {
    if (radius <= 0 || width <= 0 || height <= 0) {
        return 0;
    }
    const int32_t max_radius = (width < height ? width : height) / 2;
    return radius > max_radius ? max_radius : radius;
}

bool passport_rounded_row_span(int32_t y, int32_t width, int32_t height, int32_t radius,
                               int32_t* x1, int32_t* x2) {
    if (x1 == NULL || x2 == NULL || width <= 0 || height <= 0 || y < 0 || y >= height) {
        return false;
    }
    radius = clamp_radius(width, height, radius);
    if (radius <= 0 || (y >= radius && y < height - radius)) {
        *x1 = 0;
        *x2 = width - 1;
        return true;
    }

    const int32_t edge_y = y < radius ? radius - y : y - (height - 1 - radius);
    int32_t inset = 0;
    // int64 products: a large radius must not overflow the comparison. For the
    // Passport radius (30) this is the same inset as a 32-bit multiply.
    while ((int64_t)(inset + 1) * (inset + 1) + (int64_t)edge_y * edge_y <=
           (int64_t)radius * radius) {
        ++inset;
    }
    *x1 = radius - inset;
    *x2 = width - radius + inset - 1;
    if (*x1 < 0) {
        *x1 = 0;
    }
    if (*x2 >= width) {
        *x2 = width - 1;
    }
    return *x1 <= *x2;
}

void passport_mask_rgb565_area(uint8_t* buf, uint32_t stride, int32_t x1, int32_t y1, int32_t x2,
                               int32_t y2, int32_t screen_width, int32_t screen_height,
                               int32_t radius) {
    const int32_t width = x2 - x1 + 1;
    if (buf == NULL || width <= 0 || y2 < y1) {
        return;
    }
    if (stride < (uint32_t)width * sizeof(uint16_t)) {
        return;
    }

    for (int32_t y = y1; y <= y2; ++y) {
        uint16_t* row = (uint16_t*)(buf + (uint32_t)(y - y1) * stride);
        int32_t visible_x1 = 0;
        int32_t visible_x2 = 0;
        if (!passport_rounded_row_span(y, screen_width, screen_height, radius, &visible_x1,
                                       &visible_x2)) {
            memset(row, 0, (size_t)width * sizeof(uint16_t));
            continue;
        }

        // Clear only the part of this flush strip that sticks out of the glass.
        const int32_t clear_left_end = visible_x1 > x2 ? x2 : visible_x1 - 1;
        const int32_t clear_right_start = visible_x2 < x1 ? x1 : visible_x2 + 1;
        for (int32_t x = x1; x <= clear_left_end; ++x) {
            row[x - x1] = 0;
        }
        for (int32_t x = clear_right_start; x <= x2; ++x) {
            row[x - x1] = 0;
        }
    }
}
