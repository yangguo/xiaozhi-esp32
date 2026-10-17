"""Table-driven host checks for Passport subtitle text logic.

The firmware calls the same header. The user line survives assistant
sentences until the next valid STT; explicit assistant clears reset answers.
"""

import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SUBTITLE_H = ROOT / "main/boards/folotoy/ai-passport/passport_subtitle_text.h"

HARNESS = r"""
#include "passport_subtitle_text.h"

#include <stdio.h>
#include <string.h>

int main(int argc, char** argv) {
    if (argc == 4 && strcmp(argv[1], "truncate") == 0) {
        printf("%s", PassportTruncateUtf8(argv[2], (size_t)atoi(argv[3])).c_str());
        return 0;
    }
    if (argc >= 3 && strcmp(argv[1], "seq") == 0) {
        PassportSubtitles subs;
        for (int i = 2; i < argc;) {
            if ((strcmp(argv[i], "user") == 0 || strcmp(argv[i], "assistant") == 0) &&
                i + 1 < argc) {
                bool ok = PassportSubtitleUpdate(subs, argv[i], argv[i + 1]);
                printf("updated=%d user=%zu assistant=%zu\n", ok ? 1 : 0, subs.user.size(),
                       subs.assistant.size());
                i += 2;
            } else if (strcmp(argv[i], "render") == 0 && i + 1 < argc) {
                printf("rendered=<<%s>>\n", PassportSubtitleRender(subs, argv[i + 1]).c_str());
                i += 2;
            } else if (strcmp(argv[i], "system") == 0 && i + 1 < argc) {
                bool ok = PassportSubtitleUpdate(subs, argv[i], argv[i + 1]);
                printf("updated=%d user=%zu assistant=%zu\n", ok ? 1 : 0, subs.user.size(),
                       subs.assistant.size());
                i += 2;
            } else {
                fprintf(stderr, "bad op %s\n", argv[i]);
                return 2;
            }
        }
        return 0;
    }
    fprintf(stderr, "usage: truncate TEXT MAX | seq (user|assistant|system TEXT | render PREFIX)...\n");
    return 2;
}
"""


class PassportSubtitleTextTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workdir = tempfile.TemporaryDirectory()
        harness = Path(cls.workdir.name) / "harness.cc"
        harness.write_text(HARNESS)
        cls.binary = Path(cls.workdir.name) / "subtitle"
        subprocess.check_call(
            [
                "g++",
                "-std=c++23",
                "-Wall",
                "-Wextra",
                "-Werror",
                f"-I{SUBTITLE_H.parent}",
                str(harness),
                "-o",
                str(cls.binary),
            ]
        )

    @classmethod
    def tearDownClass(cls):
        cls.workdir.cleanup()

    def truncate(self, text, limit):
        return subprocess.check_output(
            [str(self.binary), "truncate", text, str(limit)], text=True
        )

    def seq(self, *args):
        return subprocess.check_output([str(self.binary), "seq", *args], text=True)

    def test_user_line_is_kept_until_next_valid_stt(self):
        out = self.seq("user", "hello", "assistant", "first", "render", "I: ")
        self.assertIn("rendered=<<I: hello\nfirst>>", out)

    def test_empty_user_never_clears(self):
        out = self.seq("user", "hello", "assistant", "first", "user", "", "render", "I: ")
        self.assertIn("updated=0", out)
        self.assertIn("rendered=<<I: hello\nfirst>>", out)

    def test_new_valid_stt_starts_a_fresh_turn(self):
        out = self.seq(
            "user", "first q", "assistant", "first a", "user", "second q", "render", "I: "
        )
        self.assertIn("rendered=<<I: second q>>", out)

    def test_system_role_is_not_a_subtitle(self):
        out = self.seq("user", "hello", "system", "", "render", "I: ")
        self.assertIn("updated=0", out)
        self.assertIn("rendered=<<I: hello>>", out)

    def test_notification_clear_discards_old_answer_keeps_user(self):
        out = self.seq("user", "question", "assistant", "old answer", "assistant", "",
                       "assistant", "notification", "render", "I: ")
        self.assertIn("rendered=<<I: question\nnotification>>", out)
        self.assertNotIn("old answer", out)

    def test_tiny_and_exact_utf8_budgets(self):
        for text in ("abcdefg", "中中文文", "🎧🎧🎧"):
            for limit in range(10):
                with self.subTest(text=text, limit=limit):
                    cut = self.truncate(text, limit)
                    self.assertLessEqual(len(cut.encode("utf-8")), limit)
                    self.assertNotIn("�", cut)

    def test_assistant_sentences_accumulate(self):
        out = self.seq("assistant", "one", "assistant", "two", "render", "I: ")
        self.assertIn("rendered=<<one\ntwo>>", out)

    def test_user_text_capped_at_512_utf8_safe(self):
        out = self.seq("user", "中" * 200, "render", "I: ")
        line = [l for l in out.splitlines() if l.startswith("updated=")][0]
        n = int(line.split("user=")[1].split()[0])
        self.assertLessEqual(n, 512)
        rendered = out.split("rendered=<<I: ", 1)[1].rsplit(">>", 1)[0]
        self.assertNotIn("�", rendered)
        self.assertTrue(rendered.endswith("…"))

    def test_emoji_survives_the_cut(self):
        cut = self.truncate("🎧" * 200, 512)
        self.assertLessEqual(len(cut.encode("utf-8")), 512)
        self.assertNotIn("�", cut)

    def test_assistant_capped_at_2048(self):
        out = self.seq("assistant", "b" * 3000, "render", "I: ")
        line = [l for l in out.splitlines() if l.startswith("updated=")][0]
        n = int(line.split("assistant=")[1].split()[0])
        self.assertLessEqual(n, 2048)


if __name__ == "__main__":
    unittest.main()
