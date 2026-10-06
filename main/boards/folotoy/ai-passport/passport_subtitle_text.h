#ifndef PASSPORT_SUBTITLE_TEXT_H_
#define PASSPORT_SUBTITLE_TEXT_H_

#include <cstddef>
#include <cstring>
#include <string>

// Bounded subtitle text for the Passport glass. The LCD keeps one label, so
// the board caches the latest user STT and the current assistant answer here
// and renders them together. Pure logic, no LVGL/IDF dependency, so host
// tests compile this header directly.
inline constexpr size_t kPassportSubtitleUserMaxBytes = 512;
inline constexpr size_t kPassportSubtitleAssistantMaxBytes = 2048;

struct PassportSubtitles {
    std::string user;
    std::string assistant;
    bool has_user = false;
    bool has_assistant = false;
};

// Cut to max_bytes on a UTF-8 boundary and append "…" (counted in the
// budget) when anything was cut. Never emits U+FFFD.
inline std::string PassportTruncateUtf8(const std::string& text, size_t max_bytes) {
    if (text.size() <= max_bytes) {
        return text;
    }
    static constexpr const char kEllipsis[] = "\xe2\x80\xa6";
    static constexpr size_t kEllipsisBytes = sizeof(kEllipsis) - 1;
    size_t cut = max_bytes > kEllipsisBytes ? max_bytes - kEllipsisBytes : max_bytes;
    while (cut > 0 && (static_cast<unsigned char>(text[cut]) & 0xC0) == 0x80) {
        --cut;
    }
    std::string out = text.substr(0, cut);
    if (max_bytes >= kEllipsisBytes) {
        out += kEllipsis;
    }
    return out;
}

// Returns true when the subtitle changed. Empty content never clears: only
// the next valid STT replaces the user line (and starts a fresh turn by
// clearing the assistant side). Unknown roles return false for the caller
// to pass through to the base display.
inline bool PassportSubtitleUpdate(PassportSubtitles& subs, const char* role, const char* content) {
    if (role == nullptr || content == nullptr || content[0] == '\0') {
        return false;
    }
    if (std::strcmp(role, "user") == 0) {
        subs.user = PassportTruncateUtf8(content, kPassportSubtitleUserMaxBytes);
        subs.assistant.clear();
        subs.has_user = true;
        subs.has_assistant = false;
        return true;
    }
    if (std::strcmp(role, "assistant") == 0) {
        std::string sentence = PassportTruncateUtf8(content, kPassportSubtitleAssistantMaxBytes);
        if (!subs.has_assistant) {
            subs.assistant = sentence;
            subs.has_assistant = true;
        } else {
            subs.assistant =
                PassportTruncateUtf8(subs.assistant + "\n" + sentence, kPassportSubtitleAssistantMaxBytes);
        }
        return true;
    }
    return false;
}

// Combined label text. Single-side states render that side only so a bare
// STT or a bare answer never shows an empty half.
inline std::string PassportSubtitleRender(const PassportSubtitles& subs, const char* user_prefix) {
    const std::string prefix = user_prefix != nullptr ? user_prefix : "";
    if (subs.has_user && subs.has_assistant) {
        return prefix + subs.user + "\n" + subs.assistant;
    }
    if (subs.has_user) {
        return prefix + subs.user;
    }
    if (subs.has_assistant) {
        return subs.assistant;
    }
    return "";
}

#endif  // PASSPORT_SUBTITLE_TEXT_H_
