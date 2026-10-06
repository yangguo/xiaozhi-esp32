#include "passport_display.h"

#include "application.h"
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
    ApplyGlassSafeArea();
    EnsureMenu();
}

void PassportDisplay::SetTheme(Theme* theme) {
    LcdDisplay::SetTheme(theme);
    ApplyGlassSafeArea();
    ApplyMenuTheme();
    if (page_ != Page::kClosed) {
        RenderMenu();
    }
}

void PassportDisplay::SetChatMessage(const char* role, const char* content) {
    (void)role;
    // Leaving idle closes the list from the board LED hook, including an empty
    // system line and notify audio before any subtitle. A non-empty message
    // still closes it when the device stays idle (an alert does that).
    if (page_ != Page::kClosed && content != nullptr && content[0] != '\0') {
        CloseMenu();
    }
    LcdDisplay::SetChatMessage(role, content);
    RefreshSubtitlePages();
}

void PassportDisplay::ClearChatMessages() {
    LcdDisplay::ClearChatMessages();
    RefreshSubtitlePages();
}

void PassportDisplay::ApplyGlassSafeArea() {
    if (!IsSetupUICalled() || bottom_bar_ == nullptr || chat_message_label_ == nullptr) {
        return;
    }
    DisplayLockGuard lock(this);
    if (!lock) {
        return;
    }

    const lv_font_t* font = lv_obj_get_style_text_font(chat_message_label_, LV_PART_MAIN);
    int32_t line_height = font != nullptr ? lv_font_get_line_height(font) : 0;
    if (line_height <= 0) {
        font = lv_obj_get_style_text_font(lv_screen_active(), LV_PART_MAIN);
        line_height = font != nullptr ? lv_font_get_line_height(font) : 0;
    }
    if (line_height <= 0) {
        ESP_LOGW(TAG, "Text font has no line height; subtitle viewport unchanged");
        return;
    }
    line_height_ = line_height;

    // Reserve the 32 px collection even when the boot icon is shorter, so the
    // first emotion image does not land on the subtitle.
    int32_t emoji_px = kPassportEmojiSize;
    if (emoji_box_ != nullptr) {
        lv_obj_update_layout(emoji_box_);
        const int32_t box_h = lv_obj_get_height(emoji_box_);
        if (box_h > emoji_px) {
            emoji_px = box_h;
        }
    }

    passport_rect_t safe;
    passport_rect_t subtitle;
    if (!passport_glass_safe_rect(width_, height_, PASSPORT_SCREEN_RADIUS, &safe) ||
        !passport_subtitle_viewport(width_, height_, PASSPORT_SCREEN_RADIUS, line_height,
                                    (emoji_px + 1) / 2, &subtitle)) {
        ESP_LOGW(TAG, "Glass safe area does not fit a subtitle line");
        return;
    }
    if (!passport_rect_inside_glass(&safe, width_, height_, PASSPORT_SCREEN_RADIUS) ||
        !passport_rect_inside_glass(&subtitle, width_, height_, PASSPORT_SCREEN_RADIUS)) {
        ESP_LOGW(TAG, "Computed subtitle rect is outside the glass mask");
        return;
    }
    safe_rect_ = safe;
    subtitle_rect_ = subtitle;

    // The corner caps are the rows above and below the safe rect. Icons and
    // the status line move onto the first full-width row. CLIP replaces the
    // circular scroll so a long status does not animate on every frame.
    if (top_bar_ != nullptr) {
        lv_obj_align(top_bar_, LV_ALIGN_TOP_LEFT, safe.x, safe.y);
    }
    if (status_bar_ != nullptr) {
        lv_obj_align(status_bar_, LV_ALIGN_TOP_LEFT, safe.x, safe.y);
    }
    if (status_label_ != nullptr) {
        lv_label_set_long_mode(status_label_, LV_LABEL_LONG_CLIP);
    }
    if (notification_label_ != nullptr) {
        lv_label_set_long_mode(notification_label_, LV_LABEL_LONG_CLIP);
    }

    lv_obj_update_layout(lv_screen_active());
    top_reserve_ = 0;
    if (status_bar_ != nullptr) {
        top_reserve_ = lv_obj_get_height(status_bar_);
    }
    if (top_bar_ != nullptr && lv_obj_get_height(top_bar_) > top_reserve_) {
        top_reserve_ = lv_obj_get_height(top_bar_);
    }

    // Fixed viewport, wrap, and page by scrolling the label. A vertical
    // LVGL animation would invalidate this region every frame; paging on a
    // 2.5 s timer redraws only when the page changes. Each TTS sentence
    // replaces the label text, and RefreshSubtitlePagesLocked starts again
    // at the top of that sentence.
    lv_obj_set_pos(bottom_bar_, subtitle.x, subtitle.y);
    lv_obj_set_size(bottom_bar_, subtitle.width, subtitle.height);
    lv_obj_set_style_pad_all(bottom_bar_, 0, 0);
    lv_obj_set_scrollbar_mode(bottom_bar_, LV_SCROLLBAR_MODE_OFF);
    lv_obj_set_scroll_dir(bottom_bar_, LV_DIR_VER);
    lv_obj_add_flag(bottom_bar_, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_remove_flag(bottom_bar_, LV_OBJ_FLAG_SCROLL_ELASTIC);
    lv_obj_remove_flag(bottom_bar_, LV_OBJ_FLAG_SCROLL_MOMENTUM);
    lv_obj_remove_flag(bottom_bar_, LV_OBJ_FLAG_SCROLL_CHAIN_VER);

    lv_label_set_long_mode(chat_message_label_, LV_LABEL_LONG_WRAP);
    lv_obj_set_width(chat_message_label_, subtitle.width);
    lv_obj_set_height(chat_message_label_, LV_SIZE_CONTENT);
    lv_obj_set_style_text_align(chat_message_label_, LV_TEXT_ALIGN_CENTER, 0);
    lv_obj_align(chat_message_label_, LV_ALIGN_TOP_MID, 0, 0);
    lv_anim_delete(chat_message_label_, nullptr);

    if (low_battery_popup_ != nullptr) {
        lv_obj_update_layout(low_battery_popup_);
        const int32_t popup_w = lv_obj_get_width(low_battery_popup_);
        const int32_t popup_h = lv_obj_get_height(low_battery_popup_);
        int32_t popup_y = safe.y + safe.height - popup_h;
        if (popup_y < safe.y) {
            popup_y = safe.y;
        }
        lv_obj_set_pos(low_battery_popup_, safe.x + (safe.width - popup_w) / 2, popup_y);
    }

    if (subtitle_timer_ == nullptr) {
        subtitle_timer_ = lv_timer_create(SubtitleTimerCb, kPassportSubtitlePageMs, this);
        if (subtitle_timer_ != nullptr) {
            lv_timer_pause(subtitle_timer_);
        }
    }

    ESP_LOGI(TAG, "Safe area %ldx%ld at (%ld,%ld), subtitle %ldx%ld at (%ld,%ld), line %ld",
             static_cast<long>(safe.width), static_cast<long>(safe.height),
             static_cast<long>(safe.x), static_cast<long>(safe.y),
             static_cast<long>(subtitle.width), static_cast<long>(subtitle.height),
             static_cast<long>(subtitle.x), static_cast<long>(subtitle.y),
             static_cast<long>(line_height));
    PlaceActivityLabelLocked();
    RefreshSubtitlePagesLocked();
}

void PassportDisplay::RefreshSubtitlePages() {
    DisplayLockGuard lock(this);
    if (!lock) {
        return;
    }
    RefreshSubtitlePagesLocked();
}

void PassportDisplay::RefreshSubtitlePagesLocked() {
    if (chat_message_label_ == nullptr || bottom_bar_ == nullptr) {
        return;
    }
    lv_obj_update_layout(bottom_bar_);
    subtitle_content_height_ = lv_obj_get_height(chat_message_label_);
    subtitle_viewport_height_ = lv_obj_get_height(bottom_bar_);
    subtitle_page_count_ =
        passport_subtitle_page_count(subtitle_content_height_, subtitle_viewport_height_);
    subtitle_page_ = 0;
    lv_obj_scroll_to_y(bottom_bar_, 0, LV_ANIM_OFF);

    const bool hidden = lv_obj_has_flag(bottom_bar_, LV_OBJ_FLAG_HIDDEN);
    const bool turn = subtitle_page_count_ > 1 && !hidden && page_ == Page::kClosed;
    if (subtitle_timer_ == nullptr) {
        return;
    }
    if (turn) {
        lv_timer_resume(subtitle_timer_);
        lv_timer_reset(subtitle_timer_);
    } else {
        lv_timer_pause(subtitle_timer_);
    }
}

void PassportDisplay::SubtitleTimerCb(lv_timer_t* timer) {
    // Runs on the LVGL task, which already holds the display lock.
    auto* self = static_cast<PassportDisplay*>(lv_timer_get_user_data(timer));
    if (self != nullptr) {
        self->AdvanceSubtitlePageLocked();
    }
}

void PassportDisplay::AdvanceSubtitlePageLocked() {
    if (subtitle_page_count_ <= 1 || bottom_bar_ == nullptr) {
        return;
    }
    if (page_ != Page::kClosed || lv_obj_has_flag(bottom_bar_, LV_OBJ_FLAG_HIDDEN)) {
        if (subtitle_timer_ != nullptr) {
            lv_timer_pause(subtitle_timer_);
        }
        return;
    }
    subtitle_page_ = (subtitle_page_ + 1) % subtitle_page_count_;
    const int32_t offset = passport_subtitle_page_offset(subtitle_page_, subtitle_content_height_,
                                                         subtitle_viewport_height_);
    lv_obj_scroll_to_y(bottom_bar_, offset, LV_ANIM_OFF);
}

void PassportDisplay::SetStatus(const char* status) {
    // Idle would replace the thinking gap with the clock or "Standby".
    if (activity_ == PassportActivity::kThinking) {
        status = Lang::Strings::PLEASE_WAIT;
    }
    LvglDisplay::SetStatus(status);
    ShowActivityLabel();
}

PassportActivity PassportDisplay::NoteDeviceState(DeviceState state) {
    PassportActivity next = PassportNextActivity(activity_, state);
    if (next == PassportActivity::kThinking && Application::GetInstance().CanEnterSleepMode()) {
        next = PassportActivity::kNone;
    }
    activity_ = next;
    ShowActivityLabel();
    return activity_;
}

void PassportDisplay::ShowActivityLabel() {
    DisplayLockGuard lock(this);
    if (!lock) {
        return;
    }
    ShowActivityLabelLocked();
}

void PassportDisplay::PlaceActivityLabelLocked() {
    if (safe_rect_.width <= 0 || line_height_ <= 0) {
        return;
    }
    passport_rect_t line;
    if (!passport_activity_line(&safe_rect_, &subtitle_rect_, line_height_, top_reserve_, &line) ||
        !passport_rect_inside_glass(&line, width_, height_, PASSPORT_SCREEN_RADIUS)) {
        if (activity_label_ != nullptr) {
            lv_obj_add_flag(activity_label_, LV_OBJ_FLAG_HIDDEN);
        }
        ESP_LOGW(TAG, "Activity line does not fit between the status row and the subtitle");
        return;
    }
    if (activity_label_ == nullptr) {
        activity_label_ = lv_label_create(lv_screen_active());
        lv_obj_set_style_text_align(activity_label_, LV_TEXT_ALIGN_CENTER, 0);
        lv_label_set_long_mode(activity_label_, LV_LABEL_LONG_CLIP);
    }
    lv_obj_set_pos(activity_label_, line.x, line.y);
    lv_obj_set_size(activity_label_, line.width, line.height);
    auto* theme = static_cast<LvglTheme*>(current_theme_);
    if (theme != nullptr) {
        lv_obj_set_style_text_color(activity_label_, theme->text_color(), 0);
    }
    ESP_LOGI(TAG, "Activity line %ldx%ld at (%ld,%ld)", static_cast<long>(line.width),
             static_cast<long>(line.height), static_cast<long>(line.x), static_cast<long>(line.y));
    ShowActivityLabelLocked();
}

void PassportDisplay::ShowActivityLabelLocked() {
    if (activity_label_ == nullptr) {
        return;
    }
    const char* text = nullptr;
    switch (activity_) {
        case PassportActivity::kListening:
            text = Lang::Strings::LISTENING;
            break;
        case PassportActivity::kSpeaking:
            text = Lang::Strings::SPEAKING;
            break;
        case PassportActivity::kThinking:
            text = Lang::Strings::PLEASE_WAIT;
            break;
        case PassportActivity::kNone:
            break;
    }
    // The settings list covers this line. Hide it so a paused subtitle page
    // is not joined by a state chip at the edge of the list.
    if (text == nullptr || page_ != Page::kClosed) {
        lv_obj_add_flag(activity_label_, LV_OBJ_FLAG_HIDDEN);
        return;
    }
    lv_label_set_text(activity_label_, text);
    lv_obj_remove_flag(activity_label_, LV_OBJ_FLAG_HIDDEN);
}

void PassportDisplay::UpdateStatusBar(bool update_all) {
    // The channel can close without another state event. Drop "please wait"
    // once sleep is allowed again, before the idle clock overwrites the line.
    if (activity_ == PassportActivity::kThinking &&
        Application::GetInstance().CanEnterSleepMode()) {
        activity_ = PassportActivity::kNone;
        ShowActivityLabel();
    }
    LcdDisplay::UpdateStatusBar(update_all);
    if (page_ == Page::kClosed || low_battery_popup_ == nullptr) {
        return;
    }
    DisplayLockGuard lock(this);
    if (!lock) {
        return;
    }
    if (!LowBatteryPopupVisible()) {
        return;
    }
    HideMenuLocked();
    RefreshSubtitlePagesLocked();
    ShowActivityLabelLocked();
    ESP_LOGI(TAG, "Settings list closed for low battery");
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

    // Leave the status row visible. This panel still covers the lower glass,
    // including the bottom rounded corners. Left, right, and bottom padding
    // stay at least PASSPORT_SCREEN_RADIUS so the text sits inside the visible
    // area. The top of the panel starts below the upper corner band.
    menu_panel_ = lv_obj_create(lv_screen_active());
    lv_obj_set_size(menu_panel_, width_, height_ > 48 ? height_ - 48 : height_);
    lv_obj_align(menu_panel_, LV_ALIGN_BOTTOM_MID, 0, 0);
    lv_obj_set_style_radius(menu_panel_, 0, 0);
    lv_obj_set_style_border_width(menu_panel_, 0, 0);
    lv_obj_set_style_pad_top(menu_panel_, 12, 0);
    lv_obj_set_style_pad_bottom(menu_panel_, PASSPORT_SCREEN_RADIUS, 0);
    lv_obj_set_style_pad_left(menu_panel_, PASSPORT_SCREEN_RADIUS, 0);
    lv_obj_set_style_pad_right(menu_panel_, PASSPORT_SCREEN_RADIUS, 0);
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

    const int saved_level = static_cast<int>(saved);
    auto* backlight = Board::GetInstance().GetBacklight();
    if (backlight == nullptr) {
        brightness_ = saved_level;
        return;
    }
    const int live = backlight->brightness();
    // MCP writes display/brightness, then the backlight fades toward it. The
    // 60 s dim forces kPassportDimBrightness and soft sleep forces 0,
    // neither of which is stored. While the live level is one of those, or
    // still fading, the next ±10 step uses the saved value.
    const bool temporary_dim =
        live == kPassportDimBrightness && saved_level != kPassportDimBrightness;
    const bool backlight_off = live <= 0;
    const bool fading = live != saved_level;
    if (temporary_dim || backlight_off || fading) {
        brightness_ = saved_level;
        return;
    }
    brightness_ = live;
}

void PassportDisplay::AdjustBrightness(int delta) {
    LoadBrightness();
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
    // The low-battery popup is a sibling. Raising the list would cover it,
    // so drop the list instead and leave the popup on top.
    if (LowBatteryPopupVisible()) {
        HideMenuLocked();
        RefreshSubtitlePagesLocked();
        ShowActivityLabelLocked();
        ESP_LOGI(TAG, "Settings list closed for low battery");
        return;
    }
    lv_label_set_text(menu_label_, text.c_str());
    lv_obj_remove_flag(menu_panel_, LV_OBJ_FLAG_HIDDEN);
    lv_obj_move_foreground(menu_panel_);
    // The list covers the subtitle. Leave the page timer paused until it closes.
    if (subtitle_timer_ != nullptr) {
        lv_timer_pause(subtitle_timer_);
    }
    ShowActivityLabelLocked();
}

void PassportDisplay::OpenMenu() {
    if (menu_panel_ == nullptr) {
        return;
    }
    page_ = Page::kList;
    menu_index_ = 0;
    LoadBrightness();
    RenderMenu();
    if (page_ == Page::kClosed) {
        return;
    }
    ESP_LOGI(TAG, "Settings list open");
}

bool PassportDisplay::LowBatteryPopupVisible() const {
    return low_battery_popup_ != nullptr &&
           !lv_obj_has_flag(low_battery_popup_, LV_OBJ_FLAG_HIDDEN);
}

void PassportDisplay::HideMenuLocked() {
    if (menu_panel_ != nullptr) {
        lv_obj_add_flag(menu_panel_, LV_OBJ_FLAG_HIDDEN);
    }
    page_ = Page::kClosed;
}

void PassportDisplay::CloseMenu() {
    if (page_ == Page::kClosed) {
        return;
    }
    if (menu_panel_ == nullptr) {
        page_ = Page::kClosed;
        return;
    }
    DisplayLockGuard lock(this);
    if (!lock) {
        // Leave page_ open so a later close retries. Clearing it first would
        // report the list shut while the panel is still on screen.
        ESP_LOGW(TAG, "Display lock unavailable, settings list stays open");
        return;
    }
    HideMenuLocked();
    ESP_LOGI(TAG, "Settings list closed");
    RefreshSubtitlePagesLocked();
    ShowActivityLabelLocked();
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
