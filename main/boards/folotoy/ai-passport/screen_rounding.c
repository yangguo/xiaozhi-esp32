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

bool passport_glass_safe_rect(int32_t width, int32_t height, int32_t radius, passport_rect_t* out) {
    if (out == NULL || width <= 0 || height <= 0) {
        return false;
    }

    int32_t best_y = 0;
    int32_t best_h = 0;
    int32_t run_y = -1;
    for (int32_t y = 0; y < height; ++y) {
        int32_t x1 = 0;
        int32_t x2 = 0;
        const bool full = passport_rounded_row_span(y, width, height, radius, &x1, &x2) &&
                          x1 == 0 && x2 == width - 1;
        if (full) {
            if (run_y < 0) {
                run_y = y;
            }
            continue;
        }
        if (run_y >= 0) {
            const int32_t run_h = y - run_y;
            if (run_h > best_h) {
                best_h = run_h;
                best_y = run_y;
            }
            run_y = -1;
        }
    }
    if (run_y >= 0) {
        const int32_t run_h = height - run_y;
        if (run_h > best_h) {
            best_h = run_h;
            best_y = run_y;
        }
    }
    if (best_h <= 0) {
        return false;
    }
    out->x = 0;
    out->y = best_y;
    out->width = width;
    out->height = best_h;
    return true;
}

// Inclusive x span visible on every row of [y, y + height).
static bool band_visible_span(int32_t y, int32_t band_height, int32_t width, int32_t height,
                              int32_t radius, int32_t* x1, int32_t* x2) {
    if (band_height <= 0 || x1 == NULL || x2 == NULL) {
        return false;
    }
    int32_t left = 0;
    int32_t right = width - 1;
    for (int32_t row = y; row < y + band_height; ++row) {
        int32_t row_x1 = 0;
        int32_t row_x2 = 0;
        if (!passport_rounded_row_span(row, width, height, radius, &row_x1, &row_x2)) {
            return false;
        }
        if (row_x1 > left) {
            left = row_x1;
        }
        if (row_x2 < right) {
            right = row_x2;
        }
    }
    if (left > right) {
        return false;
    }
    *x1 = left;
    *x2 = right;
    return true;
}

bool passport_subtitle_viewport(int32_t screen_width, int32_t screen_height, int32_t radius,
                                int32_t line_height, int32_t emoji_half, passport_rect_t* out) {
    passport_rect_t safe;
    if (out == NULL || line_height <= 0 ||
        !passport_glass_safe_rect(screen_width, screen_height, radius, &safe)) {
        return false;
    }
    if (emoji_half < 0) {
        emoji_half = 0;
    }

    // The emotion image is centered on the full panel, not on the safe rect.
    const int32_t below_emoji = screen_height / 2 + emoji_half;
    int32_t top = below_emoji > safe.y ? below_emoji : safe.y;
    const int32_t bottom = safe.y + safe.height;
    if (top > bottom) {
        top = bottom;
    }
    int32_t lines = (bottom - top) / line_height;
    if (lines < 1) {
        // One line does not fit under the emoji. Park a single line on the
        // bottom of the safe rect so the glyphs still clear the corner mask.
        if (safe.height < line_height) {
            return false;
        }
        lines = 1;
    }
    const int32_t text_height = lines * line_height;
    const int32_t text_y = bottom - text_height;

    int32_t x1 = 0;
    int32_t x2 = 0;
    if (!band_visible_span(text_y, text_height, screen_width, screen_height, radius, &x1, &x2)) {
        return false;
    }
    out->x = x1;
    out->y = text_y;
    out->width = x2 - x1 + 1;
    out->height = text_height;
    return true;
}

bool passport_rect_inside_glass(const passport_rect_t* rect, int32_t screen_width,
                                int32_t screen_height, int32_t radius) {
    if (rect == NULL || rect->width <= 0 || rect->height <= 0) {
        return false;
    }
    int32_t x1 = 0;
    int32_t x2 = 0;
    if (!band_visible_span(rect->y, rect->height, screen_width, screen_height, radius, &x1, &x2)) {
        return false;
    }
    return rect->x >= x1 && rect->x + rect->width - 1 <= x2;
}

bool passport_activity_line(const passport_rect_t* safe, const passport_rect_t* subtitle,
                            int32_t line_height, int32_t top_reserve, passport_rect_t* out) {
    if (out == NULL || safe == NULL || subtitle == NULL || line_height <= 0 || top_reserve < 0 ||
        safe->width <= 0 || safe->height <= 0) {
        return false;
    }
    const int32_t y = safe->y + top_reserve;
    const int32_t bottom = y + line_height;
    if (y < safe->y || bottom > safe->y + safe->height || bottom > subtitle->y) {
        return false;
    }
    out->x = safe->x;
    out->y = y;
    out->width = safe->width;
    out->height = line_height;
    return true;
}

int32_t passport_subtitle_page_count(int32_t content_height, int32_t viewport_height) {
    if (viewport_height <= 0 || content_height <= viewport_height) {
        return 1;
    }
    return (content_height + viewport_height - 1) / viewport_height;
}

void passport_status_bar_place(passport_widget_place_t* out) {
    if (out == NULL) {
        return;
    }
    out->anchor = PASSPORT_ANCHOR_TOP_MID;
    out->x = 0;
    out->y = 0;
    out->scrollable = false;
}

void passport_subtitle_bar_place(const passport_rect_t* viewport, passport_widget_place_t* out) {
    if (out == NULL) {
        return;
    }
    out->anchor = PASSPORT_ANCHOR_TOP_LEFT;
    out->x = viewport != NULL ? viewport->x : 0;
    out->y = viewport != NULL ? viewport->y : 0;
    out->scrollable = false;
}

int32_t passport_subtitle_label_y(int32_t page_offset) {
    return page_offset > 0 ? -page_offset : 0;
}

int32_t passport_bottom_mid_layout_y(int32_t parent_height, int32_t obj_height, int32_t y_ofs) {
    return y_ofs + parent_height - obj_height;
}

int32_t passport_subtitle_page_offset(int32_t page, int32_t content_height,
                                      int32_t viewport_height) {
    if (page < 0 || viewport_height <= 0 || content_height <= viewport_height) {
        return 0;
    }
    const int32_t max_offset = content_height - viewport_height;
    const int64_t offset = (int64_t)page * (int64_t)viewport_height;
    if (offset > max_offset) {
        return max_offset;
    }
    return (int32_t)offset;
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
