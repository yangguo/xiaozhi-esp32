"""Host checks for Passport conversation-phase mapping.

The device has no thinking state. After manual stop the runtime is idle while
the audio channel stays open, and that gap is what the glass calls thinking.
The label is the THINKING string in every locale, not PLEASE_WAIT.
"""

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ACTIVITY_H = ROOT / "main/boards/folotoy/ai-passport/passport_activity.h"
MAIN = ROOT / "main"

HARNESS = r"""
#include "passport_activity.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static bool parse_activity(const char* text, PassportActivity* out) {
    if (strcmp(text, "none") == 0) {
        *out = PassportActivity::kNone;
    } else if (strcmp(text, "listening") == 0) {
        *out = PassportActivity::kListening;
    } else if (strcmp(text, "thinking") == 0) {
        *out = PassportActivity::kThinking;
    } else if (strcmp(text, "speaking") == 0) {
        *out = PassportActivity::kSpeaking;
    } else {
        return false;
    }
    return true;
}

static bool parse_state(const char* text, DeviceState* out) {
    if (strcmp(text, "idle") == 0) {
        *out = kDeviceStateIdle;
    } else if (strcmp(text, "connecting") == 0) {
        *out = kDeviceStateConnecting;
    } else if (strcmp(text, "listening") == 0) {
        *out = kDeviceStateListening;
    } else if (strcmp(text, "speaking") == 0) {
        *out = kDeviceStateSpeaking;
    } else if (strcmp(text, "notifying") == 0) {
        *out = kDeviceStateNotifying;
    } else if (strcmp(text, "starting") == 0) {
        *out = kDeviceStateStarting;
    } else {
        return false;
    }
    return true;
}

static const char* activity_name(PassportActivity activity) {
    switch (activity) {
        case PassportActivity::kNone:
            return "none";
        case PassportActivity::kListening:
            return "listening";
        case PassportActivity::kThinking:
            return "thinking";
        case PassportActivity::kSpeaking:
            return "speaking";
    }
    return "none";
}

int main(int argc, char** argv) {
    if (argc == 6 && strcmp(argv[1], "resolve") == 0) {
        PassportActivity current;
        DeviceState state;
        if (!parse_activity(argv[2], &current) || !parse_state(argv[3], &state)) {
            fprintf(stderr, "unknown activity or state\n");
            return 2;
        }
        const bool channel_open = strcmp(argv[4], "open") == 0;
        const bool has_error = strcmp(argv[5], "error") == 0;
        PassportActivity next = PassportResolveActivity(current, state, channel_open, has_error);
        printf("%s %d\n", activity_name(next), PassportActivityWakesScreen(next, state) ? 1 : 0);
        return 0;
    }
    if (argc == 3 && strcmp(argv[1], "dup") == 0) {
        PassportActivity activity;
        if (!parse_activity(argv[2], &activity)) {
            fprintf(stderr, "unknown activity\n");
            return 2;
        }
        printf("%d\n", PassportActivityDuplicatesStatus(activity) ? 1 : 0);
        return 0;
    }
    if (argc == 5 && strcmp(argv[1], "clear") == 0) {
        PassportActivity current;
        DeviceState state;
        if (!parse_activity(argv[2], &current) || !parse_state(argv[3], &state)) {
            fprintf(stderr, "unknown activity or state\n");
            return 2;
        }
        const bool channel_open = strcmp(argv[4], "open") == 0;
        printf("%d\n", PassportThinkingClears(current, state, channel_open) ? 1 : 0);
        return 0;
    }
    if (argc != 3) {
        fprintf(stderr, "usage: CURRENT STATE | resolve CURRENT STATE open|closed ok|error | "
                        "clear CURRENT STATE open|closed | dup ACTIVITY\n");
        return 2;
    }
    PassportActivity current;
    DeviceState state;
    if (!parse_activity(argv[1], &current) || !parse_state(argv[2], &state)) {
        fprintf(stderr, "unknown activity or state\n");
        return 2;
    }
    PassportActivity next = PassportNextActivity(current, state);
    printf("%s %d\n", activity_name(next), PassportActivityWakesScreen(next, state) ? 1 : 0);
    return 0;
}
"""


class PassportActivityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workdir = tempfile.TemporaryDirectory()
        harness = Path(cls.workdir.name) / "harness.cc"
        harness.write_text(HARNESS)
        cls.binary = Path(cls.workdir.name) / "activity"
        subprocess.check_call(
            [
                "g++",
                "-std=c++23",
                "-Wall",
                "-Wextra",
                "-Werror",
                f"-I{ACTIVITY_H.parent}",
                f"-I{MAIN}",
                str(harness),
                "-o",
                str(cls.binary),
            ]
        )

    @classmethod
    def tearDownClass(cls):
        cls.workdir.cleanup()

    def phase(self, current, state):
        name, wake = subprocess.check_output(
            [str(self.binary), current, state], text=True
        ).split()
        return name, int(wake)

    def test_listening_release_is_thinking_until_a_later_idle(self):
        self.assertEqual(self.phase("none", "listening"), ("listening", 1))
        self.assertEqual(self.phase("listening", "idle"), ("thinking", 1))
        self.assertEqual(self.phase("thinking", "idle"), ("none", 0))
        self.assertEqual(self.phase("thinking", "speaking"), ("speaking", 1))
        self.assertEqual(self.phase("speaking", "idle"), ("none", 0))

    def test_other_states_do_not_invent_a_phase(self):
        self.assertEqual(self.phase("none", "connecting"), ("none", 1))
        self.assertEqual(self.phase("none", "idle"), ("none", 0))
        self.assertEqual(self.phase("none", "starting"), ("none", 0))
        self.assertEqual(self.phase("listening", "speaking"), ("speaking", 1))
        self.assertEqual(self.phase("none", "notifying"), ("speaking", 1))
        self.assertEqual(self.phase("speaking", "listening"), ("listening", 1))
        # A later idle after thinking already cleared stays clear.
        self.assertEqual(self.phase("none", "notifying"), ("speaking", 1))

    def test_every_locale_has_a_thinking_label(self):
        locales = ROOT / "main/assets/locales"
        files = sorted(locales.glob("*/language.json"))
        self.assertGreaterEqual(len(files), 40)
        for path in files:
            strings = json.loads(path.read_text(encoding="utf-8"))["strings"]
            thinking = strings.get("THINKING", "")
            self.assertTrue(thinking, path.parent.name)
            self.assertNotEqual(thinking, strings["STANDBY"], path.parent.name)
            self.assertNotEqual(thinking, strings["LISTENING"], path.parent.name)
            self.assertNotEqual(thinking, strings["SPEAKING"], path.parent.name)
            # ja-JP reuses PLEASE_WAIT: 待機中... is the standby string plus dots.
            if path.parent.name == "ja-JP":
                self.assertEqual(thinking, strings["PLEASE_WAIT"], path.parent.name)
            else:
                self.assertNotEqual(thinking, strings["PLEASE_WAIT"], path.parent.name)
        en = json.loads((locales / "en-US/language.json").read_text(encoding="utf-8"))
        zh = json.loads((locales / "zh-CN/language.json").read_text(encoding="utf-8"))
        ja = json.loads((locales / "ja-JP/language.json").read_text(encoding="utf-8"))
        self.assertEqual(en["strings"]["THINKING"], "Thinking...")
        # 思 and 考 are not in font_noto_sans_basic_20_4. 等 and 待 are.
        self.assertEqual(zh["strings"]["THINKING"], "等待中...")
        self.assertEqual(ja["strings"]["THINKING"], "お待ちください...")
        self.assertNotEqual(ja["strings"]["THINKING"], ja["strings"]["STANDBY"])

    def test_thinking_requires_an_open_channel_and_no_error(self):
        def resolve(current, state, channel, error):
            name, wake = subprocess.check_output(
                [str(self.binary), "resolve", current, state, channel, error], text=True
            ).split()
            return name, int(wake)

        self.assertEqual(resolve("listening", "idle", "open", "ok"), ("thinking", 1))
        self.assertEqual(resolve("listening", "idle", "closed", "ok"), ("none", 0))
        self.assertEqual(resolve("listening", "idle", "open", "error"), ("none", 0))
        self.assertEqual(resolve("speaking", "idle", "open", "ok"), ("none", 0))
        self.assertEqual(
            subprocess.check_output(
                [str(self.binary), "clear", "thinking", "idle", "closed"], text=True
            ).strip(),
            "1",
        )
        self.assertEqual(
            subprocess.check_output(
                [str(self.binary), "clear", "thinking", "idle", "open"], text=True
            ).strip(),
            "0",
        )
        self.assertEqual(
            subprocess.check_output(
                [str(self.binary), "clear", "listening", "idle", "closed"], text=True
            ).strip(),
            "0",
        )

    def test_phase_text_is_not_repeated_beside_the_status_bar(self):
        for name in ("listening", "speaking", "thinking"):
            shown = subprocess.check_output([str(self.binary), "dup", name], text=True).strip()
            self.assertEqual(shown, "1", name)
        self.assertEqual(
            subprocess.check_output([str(self.binary), "dup", "none"], text=True).strip(), "0"
        )

    def test_error_alert_never_enters_thinking(self):
        out = subprocess.check_output(
            [str(self.binary), "resolve", "listening", "idle", "open", "error"], text=True
        )
        self.assertEqual(out.split()[0], "none")

    def test_closed_channel_idle_clears_thinking(self):
        out = subprocess.check_output(
            [str(self.binary), "resolve", "listening", "idle", "closed", "ok"], text=True
        )
        self.assertEqual(out.split()[0], "none")

    def test_abort_mid_listen_returns_to_none(self):
        self.assertEqual(self.phase("listening", "idle"), ("thinking", 1))

    def test_connecting_wakes_screen_without_activity(self):
        self.assertEqual(self.phase("none", "connecting"), ("none", 1))

    def test_thinking_clears_only_on_channel_close(self):
        out_closed = subprocess.check_output(
            [str(self.binary), "clear", "thinking", "idle", "closed"], text=True
        )
        out_open = subprocess.check_output(
            [str(self.binary), "clear", "thinking", "idle", "open"], text=True
        )
        self.assertEqual(out_closed.strip(), "1")
        self.assertEqual(out_open.strip(), "0")


if __name__ == "__main__":
    unittest.main()
