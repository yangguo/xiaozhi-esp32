"""Table-driven host checks for the Passport push-to-talk gesture.

The firmware calls the same functions. A press that is already listening must
not stop on release, and a start that bails must not eat the click.
"""

import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PTT_H = ROOT / "main/boards/folotoy/ai-passport/passport_ptt.h"
MAIN = ROOT / "main"

HARNESS = r"""
#include "passport_ptt.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static bool parse_state(const char* text, DeviceState* out) {
    if (strcmp(text, "idle") == 0) {
        *out = kDeviceStateIdle;
    } else if (strcmp(text, "connecting") == 0) {
        *out = kDeviceStateConnecting;
    } else if (strcmp(text, "listening") == 0) {
        *out = kDeviceStateListening;
    } else if (strcmp(text, "speaking") == 0) {
        *out = kDeviceStateSpeaking;
    } else if (strcmp(text, "starting") == 0) {
        *out = kDeviceStateStarting;
    } else {
        return false;
    }
    return true;
}

static bool parse_phase(const char* text, PassportPttPhase* out) {
    if (strcmp(text, "idle") == 0) {
        *out = PassportPttPhase::kIdle;
    } else if (strcmp(text, "holding") == 0) {
        *out = PassportPttPhase::kHolding;
    } else if (strcmp(text, "active") == 0) {
        *out = PassportPttPhase::kActive;
    } else {
        return false;
    }
    return true;
}

static const char* phase_name(PassportPttPhase phase) {
    switch (phase) {
        case PassportPttPhase::kIdle:
            return "idle";
        case PassportPttPhase::kHolding:
            return "holding";
        case PassportPttPhase::kActive:
            return "active";
    }
    return "idle";
}

static void print_decision(const PassportPttDecision& decision) {
    printf("%s %d %d %d %d\n", phase_name(decision.phase), decision.start_listening ? 1 : 0,
           decision.stop_listening ? 1 : 0, decision.suppress_click ? 1 : 0,
           decision.click_consumed ? 1 : 0);
}

int main(int argc, char** argv) {
    if (argc == 2 && strcmp(argv[1], "arm-ms") == 0) {
        printf("%d\n", kPassportPttArmMs);
        return 0;
    }
    if (argc == 5 && strcmp(argv[1], "down") == 0) {
        DeviceState state;
        if (!parse_state(argv[2], &state)) {
            return 2;
        }
        print_decision(PassportPttPressDown(state, strcmp(argv[3], "menu") == 0,
                                             strcmp(argv[4], "blocked") == 0));
        return 0;
    }
    if (argc == 8 && strcmp(argv[1], "arm") == 0) {
        PassportPttPhase phase;
        DeviceState state;
        if (!parse_phase(argv[2], &phase) || !parse_state(argv[3], &state)) {
            return 2;
        }
        print_decision(PassportPttOnArm(phase, state, strcmp(argv[4], "menu") == 0,
                                         strcmp(argv[5], "blocked") == 0,
                                         strcmp(argv[6], "net") == 0, strcmp(argv[7], "held") == 0));
        return 0;
    }
    if (argc == 3 && strcmp(argv[1], "up") == 0) {
        PassportPttPhase phase;
        if (!parse_phase(argv[2], &phase)) {
            return 2;
        }
        print_decision(PassportPttOnRelease(phase));
        return 0;
    }
    if (argc == 3 && strcmp(argv[1], "click") == 0) {
        print_decision(PassportPttOnClick(strcmp(argv[2], "suppress") == 0));
        return 0;
    }
    if (argc == 3 && strcmp(argv[1], "long") == 0) {
        PassportPttPhase phase;
        if (!parse_phase(argv[2], &phase)) {
            return 2;
        }
        printf("%d\n", PassportPttIgnoresLongPress(phase) ? 1 : 0);
        return 0;
    }
    fprintf(stderr, "usage: arm-ms | down STATE menu|clear blocked|free | "
                    "arm PHASE STATE menu|clear blocked|free net|offline held|up | "
                    "up PHASE | click suppress|pass | long PHASE\n");
    return 2;
}
"""


class PassportPttTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workdir = tempfile.TemporaryDirectory()
        harness = Path(cls.workdir.name) / "harness.cc"
        harness.write_text(HARNESS)
        cls.binary = Path(cls.workdir.name) / "ptt"
        subprocess.check_call(
            [
                "g++",
                "-std=c++23",
                "-Wall",
                "-Wextra",
                "-Werror",
                f"-I{PTT_H.parent}",
                f"-I{MAIN}",
                str(harness),
                "-o",
                str(cls.binary),
            ]
        )

    @classmethod
    def tearDownClass(cls):
        cls.workdir.cleanup()

    def run_ptt(self, *args):
        return subprocess.check_output([str(self.binary), *args], text=True).strip()

    def test_arm_delay_is_a_real_hold_under_the_long_press(self):
        arm_ms = int(self.run_ptt("arm-ms"))
        self.assertGreaterEqual(arm_ms, 800)
        self.assertLess(arm_ms, 2000)
        self.assertEqual(arm_ms, 1000)

    def test_gesture_table(self):
        # phase, start, stop, suppress, click_consumed
        cases = [
            (("down", "idle", "clear", "free"), "holding 0 0 0 0"),
            (("down", "speaking", "clear", "free"), "holding 0 0 0 0"),
            (("down", "listening", "clear", "free"), "idle 0 0 0 0"),
            (("down", "connecting", "clear", "free"), "idle 0 0 0 0"),
            (("down", "starting", "clear", "free"), "idle 0 0 0 0"),
            (("down", "idle", "menu", "free"), "idle 0 0 0 0"),
            (("down", "idle", "clear", "blocked"), "idle 0 0 0 0"),
            (("arm", "holding", "idle", "clear", "free", "net", "held"), "active 1 0 1 0"),
            (("arm", "holding", "speaking", "clear", "free", "net", "held"), "active 1 0 1 0"),
            (("arm", "holding", "listening", "clear", "free", "net", "held"), "idle 0 0 0 0"),
            (("arm", "holding", "connecting", "clear", "free", "net", "held"), "idle 0 0 0 0"),
            (("arm", "holding", "idle", "menu", "free", "net", "held"), "idle 0 0 0 0"),
            (("arm", "holding", "idle", "clear", "free", "offline", "held"), "idle 0 0 0 0"),
            (("arm", "holding", "idle", "clear", "free", "net", "up"), "idle 0 0 0 0"),
            (("arm", "idle", "idle", "clear", "free", "net", "held"), "idle 0 0 0 0"),
            (("up", "active"), "idle 0 1 0 0"),
            (("up", "holding"), "idle 0 0 0 0"),
            (("up", "idle"), "idle 0 0 0 0"),
            (("click", "suppress"), "idle 0 0 0 1"),
            (("click", "pass"), "idle 0 0 0 0"),
            (("long", "active"), "1"),
            (("long", "holding"), "1"),
            (("long", "idle"), "0"),
        ]
        for args, expected in cases:
            with self.subTest(args=args):
                self.assertEqual(self.run_ptt(*args), expected)

    def test_menu_open_never_arms_ptt(self):
        out = self.run_ptt("down", "idle", "menu", "free")
        self.assertEqual(out.split()[0], "idle")

    def test_wake_blocked_press_never_arms(self):
        out = self.run_ptt("down", "idle", "clear", "blocked")
        self.assertEqual(out.split()[0], "idle")

    def test_offline_hold_bails_without_eating_click(self):
        down = self.run_ptt("down", "idle", "clear", "free")
        self.assertEqual(down.split()[0], "holding")
        arm = self.run_ptt("arm", "holding", "idle", "clear", "free", "offline", "held")
        parts = arm.split()
        self.assertEqual(parts[0], "idle")
        self.assertEqual(parts[1], "0")
        self.assertEqual(parts[3], "0", "offline arm must leave the next click unsuppressed")
        click = self.run_ptt("click", "suppress" if parts[3] == "1" else "pass")
        self.assertEqual(click.split()[-1], "0")

    def test_long_press_ignored_while_ptt_active(self):
        self.assertEqual(self.run_ptt("long", "active").strip(), "1")
        self.assertEqual(self.run_ptt("long", "idle").strip(), "0")


if __name__ == "__main__":
    unittest.main()
