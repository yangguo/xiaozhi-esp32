#include "passport_display.h"

#include "assets/lang_config.h"
#include "board.h"
#include "lvgl_theme.h"
#include "screen_rounding.h"
#include "settings.h"

#include <esp_log.h>
#include <lvgl.h>

#include <string>

#define TAG "PassportDisp"

namespace {

bool UiInChinese() { return Lang::CODE[0] == 'z' && Lang::CODE[1] == 'h'; }

const char* TextSettings() { return UiInChinese() ? "设置" : "Settings"; }
const char* TextBrightness() { return UiInChinese() ? "亮度" : "Brightness"; }
const char* TextTheme() { return UiInChinese() ? "主题" : "Theme"; }
const char* TextLight() { return UiInChinese() ? "浅色" : "Light"; }
const char* TextDark() { return UiInChinese() ? "深色" : "Dark"; }
const char* TextBack() { return UiInChinese() ? "返回" : "Back"; }
const char* TextListHint() {
    return UiInChinese() ? "短按确认，上下选择\n长按返回"
                         : "OK selects, up/down moves\nHold OK to close";
}
const char* TextBrightnessHint() {
    return UiInChinese() ? "上下调节，短按返回" : "Up/down changes, OK returns";
}

void PassportFlushStart(lv_event_t* event) {
    auto* display = static_cast<lv_display_t*>(lv_event_get_target(event));
    const auto* area = static_cast<const lv_area_t*>(lv_event_get_param(event));
    lv_draw_buf_t* draw_buf = lv_display_get_buf_active(display);
    if (area == nullptr || draw_buf == nullptr || draw_buf->data == nullptr ||
        lv_display_get_color_format(display) != LV_COLOR_FORMAT_RGB565) {
        return;
    }

    const int32_t width = lv_area_get_width(area);
    if (draw_buf->header.stride < static_cast<uint32_t>(width) * sizeof(uint16_t)) {
        return;
    }
    // FLUSH_START reports the area after the display offset is added. The glass
    // math is in panel coordinates; Passport's offset is 0, so this is a no-op there.
    const int32_t dx = lv_display_get_offset_x(display);
    const int32_t dy = lv_display_get_offset_y(display);
    passport_mask_rgb565_area(draw_buf->data, draw_buf->header.stride, area->x1 - dx, area->y1 - dy,
                              area->x2 - dx, area->y2 - dy,
                              lv_display_get_horizontal_resolution(display),
                              lv_display_get_vertical_resolution(display), PASSPORT_SCREEN_RADIUS);
}

}  // namespace

PassportDisplay::PassportDisplay(esp_lcd_panel_io_handle_t panel_io, esp_lcd_panel_handle_t panel,
                                 int width, int height, int offset_x, int offset_y, bool mirror_x,
                                 bool mirror_y, bool swap_xy)
    : SpiLcdDisplay(panel_io, panel, width, height, offset_x, offset_y, mirror_x, mirror_y,
                    swap_xy) {
    if (display_ == nullptr) {
        ESP_LOGE(TAG, "Display was not created; rounded-corner mask not installed");
        return;
    }
    // Mask the RGB565 strip about to be sent. clip_corner would allocate a
    // full-screen ARGB layer, which does not fit this C3. The callback itself
    // runs under the LVGL lock the port already holds for the flush.
    DisplayLockGuard lock(this);
    if (!lock) {
        ESP_LOGW(TAG, "Display lock unavailable, installing the corner mask anyway");
    }
    lv_display_add_event_cb(display_, PassportFlushStart, LV_EVENT_FLUSH_START, nullptr);
    ESP_LOGI(TAG, "Rounded screen mask radius=%d (outer corners black)", PASSPORT_SCREEN_RADIUS);
}

void PassportDisplay::SetupUI() {
    LcdDisplay::SetupUI();
    EnsureMenu();
}

void PassportDisplay::SetTheme(Theme* theme) {
    LcdDisplay::SetTheme(theme);
    ApplyMenuTheme();
    if (page_ != Page::kClosed) {
        RenderMenu();
    }
}

void PassportDisplay::SetChatMessage(const char* role, const char* content) {
    (void)role;
    // A conversation has something to show. Drop the list so it cannot cover it.
    if (page_ != Page::kClosed && content != nullptr && content[0] != '\0') {
        CloseMenu();
    }
    LcdDisplay::SetChatMessage(role, content);
}

bool PassportDisplay::IsMenuOpen() const { return page_ != Page::kClosed; }

void PassportDisplay::EnsureMenu() {
    if (menu_panel_ != nullptr || !IsSetupUICalled()) {
        return;
    }
    DisplayLockGuard lock(this);
    if (!lock) {
        return;
    }

    // Leave the status row visible. The glass corners are outside this padding,
    // so the text stays off the masked pixels.
    menu_panel_ = lv_obj_create(lv_screen_active());
    lv_obj_set_size(menu_panel_, width_, height_ > 48 ? height_ - 48 : height_);
    lv_obj_align(menu_panel_, LV_ALIGN_BOTTOM_MID, 0, 0);
    lv_obj_set_style_radius(menu_panel_, 0, 0);
    lv_obj_set_style_border_width(menu_panel_, 0, 0);
    lv_obj_set_style_pad_top(menu_panel_, 12, 0);
    lv_obj_set_style_pad_bottom(menu_panel_, 24, 0);
    lv_obj_set_style_pad_left(menu_panel_, 24, 0);
    lv_obj_set_style_pad_right(menu_panel_, 24, 0);
    lv_obj_set_scrollbar_mode(menu_panel_, LV_SCROLLBAR_MODE_OFF);
    lv_obj_remove_flag(menu_panel_, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_add_flag(menu_panel_, LV_OBJ_FLAG_HIDDEN);

    menu_label_ = lv_label_create(menu_panel_);
    lv_obj_set_width(menu_label_, lv_pct(100));
    lv_label_set_long_mode(menu_label_, LV_LABEL_LONG_WRAP);
    ApplyMenuThemeLocked();
}

void PassportDisplay::ApplyMenuThemeLocked() {
    auto* theme = static_cast<LvglTheme*>(current_theme_);
    if (menu_panel_ == nullptr || theme == nullptr) {
        return;
    }
    lv_obj_set_style_bg_color(menu_panel_, theme->background_color(), 0);
    lv_obj_set_style_bg_opa(menu_panel_, LV_OPA_COVER, 0);
    lv_obj_set_style_text_color(menu_panel_, theme->text_color(), 0);
    if (menu_label_ != nullptr) {
        lv_obj_set_style_text_color(menu_label_, theme->text_color(), 0);
    }
}

void PassportDisplay::ApplyMenuTheme() {
    if (menu_panel_ == nullptr || current_theme_ == nullptr) {
        return;
    }
    DisplayLockGuard lock(this);
    if (!lock) {
        return;
    }
    ApplyMenuThemeLocked();
}

void PassportDisplay::LoadBrightness() {
    Settings settings("display", false);
    int32_t saved = settings.GetInt("brightness", 75);
    if (saved < 10) {
        saved = 10;
    }
    if (saved > 100) {
        saved = 100;
    }
    brightness_ = static_cast<int>(saved);
}

void PassportDisplay::AdjustBrightness(int delta) {
    int next = brightness_ + delta;
    if (next < 10) {
        next = 10;
    }
    if (next > 100) {
        next = 100;
    }
    if (next == brightness_) {
        return;
    }
    brightness_ = next;
    // Permanent write uses the existing display/brightness NVS key. The dim
    // stage calls SetBrightness without the permanent flag, so it does not
    // overwrite this.
    auto* backlight = Board::GetInstance().GetBacklight();
    if (backlight != nullptr) {
        backlight->SetBrightness(static_cast<uint8_t>(brightness_), true);
    }
}

void PassportDisplay::ToggleTheme() {
    const char* next = "dark";
    if (current_theme_ != nullptr && current_theme_->name() == "dark") {
        next = "light";
    }
    auto* theme = LvglThemeManager::GetInstance().GetTheme(next);
    if (theme == nullptr) {
        return;
    }
    // LcdDisplay::SetTheme persists the existing display/theme NVS key.
    SetTheme(theme);
}

void PassportDisplay::RenderMenu() {
    if (menu_panel_ == nullptr || menu_label_ == nullptr || page_ == Page::kClosed) {
        return;
    }
    const char* theme_name = TextLight();
    if (current_theme_ != nullptr && current_theme_->name() == "dark") {
        theme_name = TextDark();
    }

    std::string text;
    if (page_ == Page::kBrightness) {
        text += TextBrightness();
        text += "\n\n";
        text += std::to_string(brightness_);
        text += "%\n\n";
        text += TextBrightnessHint();
    } else {
        text += TextSettings();
        text += "\n\n";
        const char* items[] = {TextBrightness(), TextTheme(), TextBack()};
        for (int i = 0; i < kItemCount; ++i) {
            text += (i == menu_index_) ? "> " : "  ";
            text += items[i];
            if (i == kItemTheme) {
                text += UiInChinese() ? "：" : ": ";
                text += theme_name;
            }
            text += "\n";
        }
        text += "\n";
        text += TextListHint();
    }

    DisplayLockGuard lock(this);
    if (!lock) {
        return;
    }
    lv_label_set_text(menu_label_, text.c_str());
    lv_obj_remove_flag(menu_panel_, LV_OBJ_FLAG_HIDDEN);
    lv_obj_move_foreground(menu_panel_);
}

void PassportDisplay::OpenMenu() {
    if (menu_panel_ == nullptr) {
        return;
    }
    page_ = Page::kList;
    menu_index_ = 0;
    LoadBrightness();
    RenderMenu();
    ESP_LOGI(TAG, "Settings list open");
}

void PassportDisplay::CloseMenu() {
    if (page_ == Page::kClosed) {
        return;
    }
    page_ = Page::kClosed;
    if (menu_panel_ == nullptr) {
        return;
    }
    DisplayLockGuard lock(this);
    if (!lock) {
        return;
    }
    lv_obj_add_flag(menu_panel_, LV_OBJ_FLAG_HIDDEN);
    ESP_LOGI(TAG, "Settings list closed");
}

void PassportDisplay::HandleMenuAction(MenuAction action) {
    if (page_ == Page::kClosed || action == MenuAction::kIgnore) {
        return;
    }
    if (action == MenuAction::kClose) {
        CloseMenu();
        return;
    }
    if (page_ == Page::kBrightness) {
        if (action == MenuAction::kUp) {
            AdjustBrightness(10);
        } else if (action == MenuAction::kDown) {
            AdjustBrightness(-10);
        } else if (action == MenuAction::kConfirm) {
            page_ = Page::kList;
        }
        RenderMenu();
        return;
    }

    if (action == MenuAction::kUp) {
        menu_index_ = (menu_index_ + kItemCount - 1) % kItemCount;
    } else if (action == MenuAction::kDown) {
        menu_index_ = (menu_index_ + 1) % kItemCount;
    } else if (action == MenuAction::kConfirm) {
        if (menu_index_ == kItemBrightness) {
            page_ = Page::kBrightness;
            LoadBrightness();
        } else if (menu_index_ == kItemTheme) {
            ToggleTheme();
            return;
        } else {
            CloseMenu();
            return;
        }
    }
    RenderMenu();
}
