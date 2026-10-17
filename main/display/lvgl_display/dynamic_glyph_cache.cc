#include "dynamic_glyph_cache.h"

#include <esp_log.h>
#include <algorithm>
#include <iterator>

#define TAG "DynamicGlyphCache"

DynamicGlyphCache::DynamicGlyphCache() : retain_between_batches_(TextGlyphStorageUsesPsram()) {}

lv_font_t* DynamicGlyphCache::EnsureFont(const lv_font_t* base_font, uint8_t bpp) {
    if (base_font == nullptr || (bpp != 1 && bpp != 4)) {
        return nullptr;
    }
    bool needs_rebuild = !initialized_;
    if (initialized_ && bpp_ != bpp) {
        entries_.clear();
        use_counter_ = 0;
        needs_rebuild = true;
    }
    bpp_ = bpp;
    font_.get_glyph_dsc = lv_font_get_glyph_dsc_fmt_txt;
    font_.get_glyph_bitmap = lv_font_get_bitmap_fmt_txt;
    font_.release_glyph = nullptr;
    font_.line_height = base_font->line_height;
    font_.base_line = base_font->base_line;
    font_.subpx = LV_FONT_SUBPX_NONE;
    font_.kerning = LV_FONT_KERNING_NONE;
    font_.static_bitmap = 0;
    font_.underline_position = base_font->underline_position;
    font_.underline_thickness = base_font->underline_thickness;
    font_.fallback = nullptr;
    font_.user_data = nullptr;
    font_.dsc = &dsc_;
    initialized_ = true;
    if (needs_rebuild) {
        Rebuild();
    }
    return &font_;
}

size_t DynamicGlyphCache::BitmapBytes() const {
    size_t total = 0;
    for (const auto& entry : entries_) {
        total += entry.bitmap.size();
    }
    return total;
}

bool DynamicGlyphCache::AddGlyphs(const std::vector<TextGlyph>& glyphs) {
    if (!initialized_ || glyphs.empty()) {
        return false;
    }

    bool changed = false;
    if (!retain_between_batches_) {
        changed = !entries_.empty();
        entries_.clear();
        use_counter_ = 0;
    }
    size_t bitmap_bytes = BitmapBytes();
    for (const auto& glyph : glyphs) {
        const size_t expected = (static_cast<size_t>(glyph.box_w) * glyph.box_h * bpp_ + 7) / 8;
        if (glyph.codepoint == 0 || glyph.codepoint > 0x10FFFF || glyph.bitmap.size() != expected) {
            ESP_LOGW(TAG, "Rejected glyph U+%04lX", static_cast<unsigned long>(glyph.codepoint));
            continue;
        }

        auto existing = std::find_if(
            entries_.begin(), entries_.end(),
            [&glyph](const Entry& entry) { return entry.codepoint == glyph.codepoint; });
        const size_t budget = retain_between_batches_ ? kMaxBitmapBytes : 8 * 1024;
        if (expected > budget) {
            ESP_LOGW(TAG, "Skipping glyph larger than bitmap budget");
            continue;
        }
        if (existing != entries_.end()) {
            bitmap_bytes -= existing->bitmap.size();
        } else {
            entries_.emplace_back();
            existing = std::prev(entries_.end());
        }
        existing->codepoint = glyph.codepoint;
        existing->adv_w = glyph.adv_w;
        existing->box_w = glyph.box_w;
        existing->box_h = glyph.box_h;
        existing->ofs_x = glyph.ofs_x;
        existing->ofs_y = glyph.ofs_y;
        existing->bitmap = glyph.bitmap;
        existing->last_use = ++use_counter_;
        bitmap_bytes += glyph.bitmap.size();
        changed = true;
    }

    while (entries_.size() > (retain_between_batches_ ? kMaxGlyphs : 64) ||
           bitmap_bytes > (retain_between_batches_ ? kMaxBitmapBytes : 8 * 1024)) {
        auto oldest = std::min_element(
            entries_.begin(), entries_.end(),
            [](const Entry& a, const Entry& b) { return a.last_use < b.last_use; });
        if (oldest == entries_.end()) {
            break;
        }
        bitmap_bytes -= oldest->bitmap.size();
        entries_.erase(oldest);
    }
    if (changed) {
        return Rebuild();
    }
    return changed;
}

void DynamicGlyphCache::ResetFontData() {
    bitmap_blob_.clear();
    unicode_list_.clear();
    glyph_dsc_.clear();
    cmaps_.clear();
    dsc_.glyph_bitmap = nullptr;
    dsc_.glyph_dsc = &empty_glyph_;
    dsc_.cmaps = nullptr;
    dsc_.cmap_num = 0;
    font_.dsc = &dsc_;
}

void DynamicGlyphCache::Clear() {
    std::vector<Entry>().swap(entries_);
    use_counter_ = 0;
    ResetFontData();
}

bool DynamicGlyphCache::Rebuild() {
    std::sort(entries_.begin(), entries_.end(),
              [](const Entry& a, const Entry& b) { return a.codepoint < b.codepoint; });
    if (entries_.empty()) {
        ResetFontData();
        return true;
    }
    // Allocate exact sizes, with all allocation failures checked. Building into
    // temporary storage leaves the currently installed font valid until commit.
    TextGlyphStorage<uint8_t> bitmaps;
    TextGlyphStorage<uint16_t> unicode;
    TextGlyphStorage<lv_font_fmt_txt_glyph_dsc_t> descriptors;
    TextGlyphStorage<lv_font_fmt_txt_cmap_t> maps;
    size_t range_count = 0;
    uint32_t range_start = 0;
    for (const auto& entry : entries_) {
        if (range_count == 0 || entry.codepoint - range_start > 0xFFFE) {
            ++range_count;
            range_start = entry.codepoint;
        }
    }
    if (!bitmaps.TryResize(BitmapBytes()) || !unicode.TryResize(entries_.size()) ||
        !descriptors.TryResize(entries_.size() + 1) || !maps.TryResize(range_count)) {
        ESP_LOGW(TAG, "Skipping dynamic font: storage unavailable");
        Clear();
        return false;
    }
    size_t bitmap_offset = 0;
    size_t map_index = 0;
    size_t range_begin = 0;
    for (size_t i = 0; i < entries_.size(); ++i) {
        const auto& entry = entries_[i];
        if (i == 0 || entry.codepoint - maps[map_index].range_start > 0xFFFE) {
            if (i != 0) {
                ++map_index;
            }
            range_begin = i;
            auto& map = maps[map_index];
            map.range_start = entry.codepoint;
            map.glyph_id_start = i + 1;
            map.unicode_list = unicode.data() + i;
            map.type = LV_FONT_FMT_TXT_CMAP_SPARSE_TINY;
        }
        auto& map = maps[map_index];
        map.range_length = entry.codepoint - map.range_start + 1;
        map.list_length = i - range_begin + 1;
        unicode[i] = entry.codepoint - map.range_start;
        auto& desc = descriptors[i + 1];
        desc.bitmap_index = bitmap_offset;
        desc.adv_w = entry.adv_w;
        desc.box_w = entry.box_w;
        desc.box_h = entry.box_h;
        desc.ofs_x = entry.ofs_x;
        desc.ofs_y = entry.ofs_y;
        if (!entry.bitmap.empty()) {
            std::memcpy(bitmaps.data() + bitmap_offset, entry.bitmap.data(), entry.bitmap.size());
        }
        bitmap_offset += entry.bitmap.size();
    }
    bitmap_blob_ = std::move(bitmaps);
    unicode_list_ = std::move(unicode);
    glyph_dsc_ = std::move(descriptors);
    cmaps_ = std::move(maps);
    dsc_.glyph_bitmap = bitmap_blob_.data();
    dsc_.glyph_dsc = glyph_dsc_.data();
    dsc_.cmaps = cmaps_.data();
    dsc_.kern_dsc = nullptr;
    dsc_.kern_scale = 0;
    dsc_.cmap_num = cmaps_.size();
    dsc_.bpp = bpp_;
    dsc_.kern_classes = 0;
    dsc_.bitmap_format = LV_FONT_FMT_TXT_PLAIN;
    dsc_.stride = 0;
    font_.dsc = &dsc_;
    return true;
}
