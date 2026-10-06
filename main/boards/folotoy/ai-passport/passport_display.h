#ifndef PASSPORT_DISPLAY_H_
#define PASSPORT_DISPLAY_H_

#include "display/lcd_display.h"

// Idle-dim backlight, in percent. The board writes this without saving it.
// The settings list uses the same value so a live reading at this level is
// not stored unless display/brightness is also this level.
inline constexpr int kPassportDimBrightness = 10;

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
    void SetChatMessage(const char* role, const char* content) override;
    void UpdateStatusBar(bool update_all = false) override;

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
    Page page_ = Page::kClosed;
    int menu_index_ = 0;
    int brightness_ = 75;
};

#endif  // PASSPORT_DISPLAY_H_
