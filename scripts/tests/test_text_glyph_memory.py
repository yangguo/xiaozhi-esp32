"""Exercise actual glyph storage under deterministic allocation failure."""
import subprocess
import tempfile
import unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]

class GlyphMemoryTests(unittest.TestCase):
    def test_copy_and_allocation_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            d = Path(temp)
            (d / 'esp_heap_caps.h').write_text('''#pragma once
#include <cstdlib>
#define MALLOC_CAP_INTERNAL 1
#define MALLOC_CAP_8BIT 2
#define MALLOC_CAP_SPIRAM 4
inline bool fail_alloc=false;
inline int allocations=0;
inline void* heap_caps_malloc(size_t n, unsigned) { if(fail_alloc)return nullptr;++allocations;return malloc(n); }
inline void heap_caps_free(void* p) { free(p); }
''')
            (d / 'esp_system.h').write_text('#pragma once\n#include <cstdlib>\n[[noreturn]] inline void esp_system_abort(const char*) { abort(); }\n')
            (d / 'test.cc').write_text('''#include "display/text_glyph.h"
#include <cassert>
#include <string>
bool TextGlyphStorageUsesPsram(){return false;}
template<class B> bool Resize(B& b,size_t n) {
 if constexpr(requires { b.TryResize(n); }) return b.TryResize(n);
 else { b.resize(n);return true; }
}
int main(int argc,char**argv) {
 assert(argc==2);std::string mode=argv[1];TextGlyph g;
 if(mode=="failure") {fail_alloc=true;assert(!Resize(g.bitmap,1024));assert(g.bitmap.empty());}
 else {
  assert(Resize(g.bitmap,1024));g.bitmap.data()[0]=42;int before=allocations;
  TextGlyph copy=g;assert(allocations==before);assert(copy.bitmap.data()==g.bitmap.data());
  assert(copy.bitmap.data()[0]==42);
  fail_alloc=true;assert(!Resize(g.bitmap,2048));assert(g.bitmap.size()==1024);assert(copy.bitmap.data()[0]==42);
 }
}
''')
            binary = d / 'test'
            subprocess.check_call(['g++','-std=c++23',f'-I{d}',f'-I{ROOT / "main"}',str(d/'test.cc'),'-o',str(binary)])
            for scenario in ('failure','copy'):
                with self.subTest(scenario=scenario):
                    subprocess.check_call([str(binary), scenario])


class DynamicFontMemoryTests(unittest.TestCase):
    def test_every_font_storage_failure_degrades_and_recovers(self):
        with tempfile.TemporaryDirectory() as temp:
            d = Path(temp)
            (d/'display.h').write_text('#pragma once\n#include "display/text_glyph.h"\n')
            (d/'esp_heap_caps.h').write_text('''#pragma once
#include <cstdlib>
#define MALLOC_CAP_INTERNAL 1
#define MALLOC_CAP_8BIT 2
#define MALLOC_CAP_SPIRAM 4
inline int fail_at=0, allocations=0;
inline void* heap_caps_malloc(size_t n,unsigned){if(++allocations==fail_at)return nullptr;return malloc(n);}
inline void heap_caps_free(void*p){free(p);}
''')
            (d/'esp_log.h').write_text('#pragma once\n#define ESP_LOGW(...) ((void)0)\n')
            (d/'esp_system.h').write_text('#pragma once\n#include <cstdlib>\n[[noreturn]] inline void esp_system_abort(const char*){abort();}\n')
            (d/'lvgl.h').write_text('''#pragma once
#include <cstdint>
constexpr int LV_FONT_SUBPX_NONE=0,LV_FONT_KERNING_NONE=0,LV_FONT_FMT_TXT_PLAIN=0,LV_FONT_FMT_TXT_CMAP_SPARSE_TINY=0;
inline void lv_font_get_glyph_dsc_fmt_txt(){}
inline void lv_font_get_bitmap_fmt_txt(){}
struct lv_font_fmt_txt_glyph_dsc_t {uint32_t bitmap_index=0,adv_w=0,box_w=0,box_h=0;int16_t ofs_x=0,ofs_y=0;};
struct lv_font_fmt_txt_cmap_t {uint32_t range_start=0;uint16_t range_length=0,glyph_id_start=0;const uint16_t*unicode_list=nullptr;const void*glyph_id_ofs_list=nullptr;uint16_t list_length=0;int type=0;};
struct lv_font_fmt_txt_dsc_t {const uint8_t*glyph_bitmap=nullptr;const lv_font_fmt_txt_glyph_dsc_t*glyph_dsc=nullptr;const lv_font_fmt_txt_cmap_t*cmaps=nullptr;void*kern_dsc=nullptr;int kern_scale=0,cmap_num=0,bpp=0,kern_classes=0,bitmap_format=0,stride=0;};
struct lv_font_t {void(*get_glyph_dsc)()=nullptr;void(*get_glyph_bitmap)()=nullptr;void(*release_glyph)()=nullptr;int line_height=20,base_line=0,subpx=0,kerning=0,static_bitmap=0,underline_position=0,underline_thickness=0;const lv_font_t*fallback=nullptr;void*user_data=nullptr;const void*dsc=nullptr;};
''')
            (d/'test.cc').write_text('''#include "display/lvgl_display/dynamic_glyph_cache.h"
#include <cassert>
bool has_psram=false;
bool TextGlyphStorageUsesPsram(){return has_psram;}
int main(){
 lv_font_t base;
 for(int nth=1;nth<=4;++nth){
  fail_at=0;TextGlyph g;g.codepoint=0x4e00;g.box_w=8;g.box_h=8;
  assert(g.bitmap.TryResize(8));g.bitmap.data()[0]=42;
  DynamicGlyphCache cache;lv_font_t*font=cache.EnsureFont(&base,1);
  fail_at=allocations+nth;assert(!cache.AddGlyphs({g}));
  auto*dsc=static_cast<const lv_font_fmt_txt_dsc_t*>(font->dsc);
  assert(dsc->cmap_num==0);assert(dsc->glyph_bitmap==nullptr);
  fail_at=0;assert(cache.AddGlyphs({g}));dsc=static_cast<const lv_font_fmt_txt_dsc_t*>(font->dsc);
  assert(dsc->cmap_num==1);assert(dsc->glyph_bitmap[0]==42);
  cache.Clear();assert(dsc->cmap_num==0);
 }
 // Separate Unicode ranges retain valid pointers after the temporary build.
 DynamicGlyphCache cache;auto*font=cache.EnsureFont(&base,1);
 TextGlyph a,b;a.codepoint=1;b.codepoint=0x10000;
 assert(cache.AddGlyphs({a,b}));auto*dsc=static_cast<const lv_font_fmt_txt_dsc_t*>(font->dsc);
 assert(dsc->cmap_num==2);assert(dsc->cmaps[1].unicode_list[0]==0);
 // A no-PSRAM batch cannot bypass the bitmap cap with one large glyph.
 cache.Clear();TextGlyph large;large.codepoint=2;large.box_w=256;large.box_h=512;
 assert(large.bitmap.TryResize(16384));assert(!cache.AddGlyphs({large}));
 has_psram=true;DynamicGlyphCache retained;auto*pf=retained.EnsureFont(&base,1);
 assert(retained.AddGlyphs({a}));assert(retained.AddGlyphs({b}));
 auto*pd=static_cast<const lv_font_fmt_txt_dsc_t*>(pf->dsc);assert(pd->cmap_num==2);
 retained.Clear();assert(pd->cmap_num==0);
}
''')
            binary=d/'test'
            subprocess.check_call(['g++','-std=c++23','-Wall','-Wextra','-Werror',f'-I{d}',f'-I{ROOT / "main"}',str(d/'test.cc'),str(ROOT/'main/display/lvgl_display/dynamic_glyph_cache.cc'),'-o',str(binary)])
            subprocess.check_call([str(binary)])

if __name__ == '__main__': unittest.main()
