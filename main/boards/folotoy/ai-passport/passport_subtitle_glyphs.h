#ifndef PASSPORT_SUBTITLE_GLYPHS_H_
#define PASSPORT_SUBTITLE_GLYPHS_H_

#include "display/text_glyph.h"

#include <algorithm>
#include <utility>
#include <vector>

// C3's shared display cache replaces each batch. Replay a small bounded union
// for the accumulated subtitle instead of enabling the shared 64 KiB PSRAM
// retention policy. Overflow/format change starts a fresh subtitle segment.
class PassportSubtitleGlyphs {
public:
    static constexpr size_t kMaxGlyphs = 64;
    static constexpr size_t kMaxBitmapBytes = 8 * 1024;

    // True means the caller must discard old subtitle text before rendering
    // the next message: its glyphs are no longer guaranteed to be available.
    bool Update(const std::vector<TextGlyph>& incoming, uint8_t bpp) {
        if (!incoming.empty() && bpp != 1 && bpp != 4) {
            return false;
        }
        bool reset = unretained_batch_ || (!incoming.empty() && bpp_ != 0 && bpp_ != bpp);
        if (reset) {
            Clear();
        }
        if (incoming.empty()) {
            return reset;
        }
        size_t bytes = 0;
        for (const auto& glyph : incoming) {
            if (glyph.bitmap.size() > kMaxBitmapBytes - bytes) {
                Clear();
                unretained_batch_ = true;
                return true;
            }
            bytes += glyph.bitmap.size();
        }
        if (incoming.size() > kMaxGlyphs) {
            Clear();
            unretained_batch_ = true;
            return true;
        }
        // Compute the merged budget before allocating any bitmap copies.
        size_t count = incoming.size();
        for (const auto& old : glyphs_) {
            auto it = std::find_if(incoming.begin(), incoming.end(), [&](const TextGlyph& g) {
                return g.codepoint == old.codepoint;
            });
            if (it == incoming.end()) {
                ++count;
                bytes += old.bitmap.size();
            }
        }
        if (count > kMaxGlyphs || bytes > kMaxBitmapBytes) {
            Clear();
            reset = true;
        }
        bpp_ = bpp;
        for (const auto& glyph : incoming) {
            auto it = std::find_if(glyphs_.begin(), glyphs_.end(), [&](const TextGlyph& g) {
                return g.codepoint == glyph.codepoint;
            });
            if (it == glyphs_.end()) {
                glyphs_.push_back(glyph);
            } else {
                // A shrinking glyph must release its previous bitmap capacity.
                TextGlyph replacement = glyph;
                *it = std::move(replacement);
            }
        }
        return reset;
    }

    void Clear() {
        std::vector<TextGlyph>().swap(glyphs_);
        bpp_ = 0;
        unretained_batch_ = false;
    }
    bool CanReplay() const { return !glyphs_.empty(); }
    uint8_t Bpp() const { return bpp_; }
    const std::vector<TextGlyph>& Glyphs() const { return glyphs_; }

private:
    std::vector<TextGlyph> glyphs_;
    uint8_t bpp_ = 0;
    bool unretained_batch_ = false;
};

#endif  // PASSPORT_SUBTITLE_GLYPHS_H_
