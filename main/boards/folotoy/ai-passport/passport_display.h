#ifndef PASSPORT_DISPLAY_H_
#define PASSPORT_DISPLAY_H_

#include "display/lcd_display.h"
#include "passport_activity.h"
#include "screen_rounding.h"

// Idle-dim backlight, in percent. The board writes this without saving it.
// The settings list uses the same value so a live reading at this level is
// not stored unless display/brightness is also this level.
inline constexpr int kPassportDimBrightness = 10;

// How long one subtitle page stays up. A timer tick, not a scroll animation,
// so a long sentence does not redraw the panel every frame on this C3.
inline constexpr int kPassportSubtitlePageMs = 2500;

// Emotion images selected for this board in main/CMakeLists.txt
// (noto-color-emoji_32). The subtitle viewport stays below this square,
// or below the live emoji widget when that is taller.
inline constexpr int kPassportEmojiSize = 32;

// SPI LCD for the Passport glass: rounded-corner flush mask plus a small
// settings list. The list does not own a sleep timer; idle power stays with
// the board's PowerSaveTimer.
class PassportDisplay : public SpiLcdDisplay {
public:
    enum class MenuAction {
        kUp,
        kDown,
        kConfirm,
        kClose,
        kIgnore,
    };

    PassportDisplay(esp_lcd_panel_io_handle_t panel_io, esp_lcd_panel_handle_t panel, int width,
                    int height, int offset_x, int offset_y, bool mirror_x, bool mirror_y,
                    bool swap_xy);

    void SetupUI() override;
    void SetTheme(Theme* theme) override;
    void SetStatus(const char* status) override;
    void SetChatMessage(const char* role, const char* content) override;
    void ClearChatMessages() override;
    void UpdateStatusBar(bool update_all = false) override;

    // Device-state hook used by the board. Returns the activity now shown.
    // Thinking is dropped when the device is already allowed to sleep, so a
    // cancelled listen does not sit on "thinking".
    PassportActivity NoteDeviceState(DeviceState state);
    PassportActivity activity() const { return activity_; }

    bool IsMenuOpen() const;
    void OpenMenu();
    void CloseMenu();
    void HandleMenuAction(MenuAction action);

private:
    enum class Page {
        kClosed,
        kList,
        kBrightness,
    };

    static constexpr int kItemBrightness = 0;
    static constexpr int kItemTheme = 1;
    static constexpr int kItemBack = 2;
    static constexpr int kItemCount = 3;

    void ApplyGlassSafeArea();
    void RefreshSubtitlePages();
    // Caller holds the LVGL lock.
    void RefreshSubtitlePagesLocked();
    void AdvanceSubtitlePageLocked();
    static void SubtitleTimerCb(lv_timer_t* timer);
    void PlaceActivityLabelLocked();
    void ShowActivityLabel();
    void ShowActivityLabelLocked();

    void EnsureMenu();
    void ApplyMenuTheme();
    void ApplyMenuThemeLocked();
    void RenderMenu();
    void LoadBrightness();
    void AdjustBrightness(int delta);
    void ToggleTheme();
    // Caller holds the LVGL lock. Hides the panel, then marks the list closed.
    void HideMenuLocked();
    bool LowBatteryPopupVisible() const;

    lv_obj_t* menu_panel_ = nullptr;
    lv_obj_t* menu_label_ = nullptr;
    lv_obj_t* activity_label_ = nullptr;
    PassportActivity activity_ = PassportActivity::kNone;
    lv_timer_t* subtitle_timer_ = nullptr;
    Page page_ = Page::kClosed;
    int menu_index_ = 0;
    int brightness_ = 75;
    int32_t subtitle_page_ = 0;
    int32_t subtitle_page_count_ = 1;
    int32_t subtitle_content_height_ = 0;
    int32_t subtitle_viewport_height_ = 0;
    int32_t line_height_ = 0;
    int32_t top_reserve_ = 0;
    passport_rect_t safe_rect_{};
    passport_rect_t subtitle_rect_{};
};

#endif  // PASSPORT_DISPLAY_H_
