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

// Visible inclusive X span for one screen row of a rounded rectangle.
// Returns false when the row is outside the screen or the span is empty.
bool passport_rounded_row_span(int32_t y, int32_t width, int32_t height, int32_t radius,
                               int32_t* x1, int32_t* x2);

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
