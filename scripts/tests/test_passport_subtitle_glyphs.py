"""Compile the production Passport glyph-retention policy with host allocators."""
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BOARD = ROOT / "main/boards/folotoy/ai-passport"
DISPLAY_STUB = r'''
#include "passport_subtitle_text.h"
#define ESP_LOGW(...) ((void)0)
class LcdDisplay {
public:
    virtual ~LcdDisplay() = default;
    std::vector<uint32_t> live;
    virtual void ClearTextGlyphs() { live.clear(); }
    virtual bool AddTextGlyphs(const std::vector<TextGlyph>& glyphs, uint8_t) {
        // Mirror the shared non-PSRAM replacement and virtual-clear contract.
        if (glyphs.empty()) { ClearTextGlyphs(); return false; }
        live.clear();
        for (const auto& g : glyphs) live.push_back(g.codepoint);
        return true;
    }
};
class PassportDisplay : public LcdDisplay {
public:
    PassportSubtitles subtitles_;
    PassportSubtitleGlyphs subtitle_glyphs_;
    bool AddTextGlyphs(const std::vector<TextGlyph>&, uint8_t) override;
    void ClearTextGlyphs() override;
};
'''
HARNESS = r'''
#include "passport_subtitle_glyphs.h"
#include <cassert>
#include <string>
bool TextGlyphStorageUsesPsram() { return false; }
TextGlyph glyph(uint32_t cp, size_t bytes = 4) {
    TextGlyph g;
    g.codepoint = cp; g.box_w = 8; g.box_h = bytes;
    g.bitmap.resize(bytes, static_cast<uint8_t>(cp));
    return g;
}
// DISPLAY_METHODS
int main(int argc, char** argv) {
    assert(argc == 2);
    std::string op = argv[1];
    if (op == "display_union") {
        PassportDisplay display;
        display.AddTextGlyphs({glyph(0x4e00)}, 1);
        PassportSubtitleUpdate(display.subtitles_, "user", "一");
        display.AddTextGlyphs({glyph(0x4e01)}, 1);
        PassportSubtitleUpdate(display.subtitles_, "assistant", "丁");
        assert(display.live.size() == 2);
        assert(PassportSubtitleRender(display.subtitles_, "I: ") == "I: 一\n丁");
        display.AddTextGlyphs({}, 0);
        assert(display.live.size() == 2); assert(display.subtitles_.has_user);
        display.ClearTextGlyphs();
        assert(!display.subtitles_.has_user); assert(display.live.empty());
        return 0;
    }
    if (op == "display_empty") {
        PassportDisplay display;
        PassportSubtitleUpdate(display.subtitles_, "user", "hello");
        display.AddTextGlyphs({}, 0);
        assert(display.subtitles_.user == "hello");
        display.AddTextGlyphs({glyph(0x4e00)}, 1);
        display.AddTextGlyphs({glyph(0x4e01)}, 4);
        assert(!display.subtitles_.has_user); assert(display.live.size() == 1);
        return 0;
    }
    PassportSubtitleGlyphs cache;
    assert(!cache.Update({glyph(0x4e00)}, 1));
    if (op == "union") {
        assert(!cache.Update({glyph(0x4e01)}, 1));
        assert(cache.CanReplay()); assert(cache.Glyphs().size() == 2);
        assert(cache.Glyphs()[0].codepoint == 0x4e00);
        assert(cache.Glyphs()[1].codepoint == 0x4e01);
    } else if (op == "empty") {
        assert(!cache.Update({}, 0));
        assert(cache.CanReplay()); assert(cache.Glyphs().size() == 1);
        assert(cache.Bpp() == 1);
    } else if (op == "replace") {
        assert(!cache.Update({glyph(0x4e00, 8)}, 1));
        assert(cache.Glyphs().size() == 1); assert(cache.Glyphs()[0].bitmap.size() == 8);
    } else if (op == "format") {
        assert(cache.Update({glyph(0x4e01)}, 4));
        assert(cache.Glyphs().size() == 1); assert(cache.Bpp() == 4);
    } else if (op == "overflow") {
        assert(cache.Update({glyph(0x4e01, PassportSubtitleGlyphs::kMaxBitmapBytes)}, 1));
        assert(cache.Glyphs().size() == 1); assert(cache.Glyphs()[0].codepoint == 0x4e01);
    } else if (op == "oversized") {
        assert(cache.Update({glyph(0x4e01, PassportSubtitleGlyphs::kMaxBitmapBytes + 1)}, 1));
        assert(!cache.CanReplay()); assert(cache.Glyphs().empty());
        assert(cache.Update({}, 0)); // a previous uncached batch must not survive cache clear
    } else if (op == "count") {
        std::vector<TextGlyph> incoming;
        for (size_t i = 0; i < PassportSubtitleGlyphs::kMaxGlyphs; ++i)
            incoming.push_back(glyph(0x5000 + i));
        assert(cache.Update(incoming, 1));
        assert(cache.Glyphs().size() == PassportSubtitleGlyphs::kMaxGlyphs);
    } else if (op == "clear") {
        cache.Clear(); assert(cache.Glyphs().empty()); assert(!cache.CanReplay());
        assert(!cache.Update({}, 0));
    } else { return 2; }
}
'''

class PassportSubtitleGlyphTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        d = Path(cls.tmp.name)
        (d / "esp_heap_caps.h").write_text("#pragma once\n#include <cstdlib>\n#define MALLOC_CAP_INTERNAL 1\n#define MALLOC_CAP_8BIT 2\n#define MALLOC_CAP_SPIRAM 4\ninline void* heap_caps_malloc(size_t n, unsigned) { return malloc(n); }\ninline void heap_caps_free(void* p) { free(p); }\n")
        (d / "esp_system.h").write_text("#pragma once\n#include <cstdlib>\n[[noreturn]] inline void esp_system_abort(const char*) { abort(); }\n")
        display_source = (BOARD / "passport_display.cc").read_text()
        methods = display_source[display_source.index("bool PassportDisplay::AddTextGlyphs("):
                                 display_source.index("void PassportDisplay::SetChatMessage(")]
        (d / "harness.cc").write_text(HARNESS.replace("// DISPLAY_METHODS", DISPLAY_STUB + methods))
        cls.binary = d / "glyphs"
        subprocess.check_call(["g++", "-std=c++23", "-Wall", "-Wextra", "-Werror",
                               f"-I{d}", f"-I{BOARD}", f"-I{ROOT / 'main'}",
                               str(d / "harness.cc"), "-o", str(cls.binary)])

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_retention_and_reset_boundaries(self):
        for scenario in ("union", "empty", "replace", "format", "overflow", "oversized", "count", "clear", "display_union", "display_empty"):
            with self.subTest(scenario=scenario):
                subprocess.check_call([str(self.binary), scenario])

if __name__ == "__main__":
    unittest.main()
