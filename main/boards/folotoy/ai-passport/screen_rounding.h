#ifndef PASSPORT_SCREEN_ROUNDING_H_
#define PASSPORT_SCREEN_ROUNDING_H_

#include <stdbool.h>
#include <stdint.h>

// AI Passport glass radius, in pixels, taken from the official FoloToy adapter
// (lvgl_screen_rounding.h). The mask is applied to the RGB565 flush buffer so
// the C3 does not allocate an LVGL clip-corner ARGB layer.
#define PASSPORT_SCREEN_RADIUS 30

#ifdef __cplusplus
extern "C" {
#endif

// Axis-aligned rectangle. x/y are the top-left corner; width/height are in pixels.
typedef struct {
    int32_t x;
    int32_t y;
    int32_t width;
    int32_t height;
} passport_rect_t;

// Visible inclusive X span for one screen row of a rounded rectangle.
// Returns false when the row is outside the screen or the span is empty.
bool passport_rounded_row_span(int32_t y, int32_t width, int32_t height, int32_t radius,
                               int32_t* x1, int32_t* x2);

// Largest full-width band inside the rounded glass: the longest run of rows
// whose visible span is the entire screen width. Derived from
// passport_rounded_row_span, so a radius change moves the band with the mask.
bool passport_glass_safe_rect(int32_t width, int32_t height, int32_t radius, passport_rect_t* out);

// Subtitle viewport inside the safe rect, below a centered emoji.
// `emoji_half` is half the centered emotion image (0 if there is none).
// The height is a whole number of `line_height` rows, bottom-aligned in the
// slice under the emoji, then narrowed to the rows' common visible span.
// Returns false when a single line does not fit in the safe rect.
bool passport_subtitle_viewport(int32_t screen_width, int32_t screen_height, int32_t radius,
                                int32_t line_height, int32_t emoji_half, passport_rect_t* out);

// True when every pixel of `rect` is inside the rounded glass.
bool passport_rect_inside_glass(const passport_rect_t* rect, int32_t screen_width,
                                int32_t screen_height, int32_t radius);

// One status line inside the safe rect, below `top_reserve` (the status bar)
// and above the subtitle. Returns false when that line would leave the safe
// rect or overlap the subtitle.
bool passport_activity_line(const passport_rect_t* safe, const passport_rect_t* subtitle,
                            int32_t line_height, int32_t top_reserve, passport_rect_t* out);

// How many viewport-sized pages a wrapped block needs. At least 1.
int32_t passport_subtitle_page_count(int32_t content_height, int32_t viewport_height);

// Scroll offset of `page` (0-based). The last page is clamped so the tail
// stays on screen instead of scrolling into empty space.
int32_t passport_subtitle_page_offset(int32_t page, int32_t content_height,
                                      int32_t viewport_height);

// How a screen child is anchored. LVGL 9 treats style x/y as an offset from
// this anchor, so a widget created with bottom-middle alignment cannot be
// moved to an absolute y with lv_obj_set_pos alone.
typedef enum {
    PASSPORT_ANCHOR_TOP_LEFT = 0,
    PASSPORT_ANCHOR_TOP_MID = 1,
} passport_anchor_t;

typedef struct {
    passport_anchor_t anchor;
    int32_t x;
    int32_t y;
    bool scrollable;
} passport_widget_place_t;

// Status and icon row. y is 0: the centered label sits in the visible middle
// of the top row, which the corner mask does not cover.
void passport_status_bar_place(passport_widget_place_t* out);

// Subtitle viewport as an absolute top-left rectangle. Not scrollable: paging
// moves the label instead of scrolling the parent, so LVGL draws no scrollbar.
void passport_subtitle_bar_place(const passport_rect_t* viewport, passport_widget_place_t* out);

// Label y inside that viewport. Negative values clip the lines above this page.
int32_t passport_subtitle_label_y(int32_t page_offset);

// Where LVGL 9 lays out a bottom-middle widget whose style y is `y_ofs`.
// For the Passport viewport this is below the panel, which is why the text
// never appeared in (0, 186, 240, 104).
int32_t passport_bottom_mid_layout_y(int32_t parent_height, int32_t obj_height, int32_t y_ofs);

// Zero RGB565 pixels that fall outside the rounded span. `buf` is one flush
// strip in screen order; `stride` is the row stride in bytes. Coordinates are
// the screen area being flushed (inclusive).
void passport_mask_rgb565_area(uint8_t* buf, uint32_t stride, int32_t x1, int32_t y1, int32_t x2,
                               int32_t y2, int32_t screen_width, int32_t screen_height,
                               int32_t radius);

#ifdef __cplusplus
}
#endif

#endif  // PASSPORT_SCREEN_ROUNDING_H_
