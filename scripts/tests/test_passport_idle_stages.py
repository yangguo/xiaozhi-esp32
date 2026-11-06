"""Execute Passport stage methods with fake timers and hardware on the host."""
import pathlib
import shutil
import subprocess
import tempfile
import unittest

from scripts.tests.test_power_save_timer import function

ROOT = pathlib.Path(__file__).resolve().parents[2]
BOARD = ROOT / "main/boards/folotoy/ai-passport/ai_passport_board.cc"


@unittest.skipUnless(shutil.which("c++"), "requires a host C++ compiler")
class PassportIdleStagesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        cls.binary = str(pathlib.Path(cls.tmp.name) / "passport-idle")
        board = BOARD.read_text()
        source = r'''
#include <atomic>
#include <cassert>
#include <cstdint>
#include <functional>
#include <string>
#include <utility>
#include <vector>
#define ESP_LOGI(...)
#define ESP_LOGW(...)
#define ESP_LOGE(...)
#define ESP_ERROR_CHECK(x) assert((x) == 0)
constexpr int ESP_OK = 0, ESP_TIMER_TASK = 0;
using esp_err_t = int;
struct esp_timer_create_args_t {
    void (*callback)(void*); void* arg; int dispatch_method;
    const char* name; bool skip_unhandled_events;
};
struct Timer { esp_timer_create_args_t args{}; bool active = false; };
using esp_timer_handle_t = Timer*;
int64_t now = 0;
int64_t esp_timer_get_time() { return now; }
bool esp_timer_is_active(Timer* t) { return t->active; }
int esp_timer_stop(Timer* t) { t->active = false; return 0; }
int esp_timer_start_periodic(Timer* t, int64_t us) {
    assert(!t->active && us == 1000000); t->active = true; return 0;
}
const char* esp_err_to_name(int) { return "error"; }
struct Audio { void EnableWakeWordDetection(bool) {} };
struct Application {
    bool idle = true; Audio audio; std::vector<std::function<void()>> pending;
    static Application& GetInstance() { static Application app; return app; }
    bool CanEnterSleepMode() { return idle; }
    Audio& GetAudioService() { return audio; }
    void Schedule(std::function<void()> f) { pending.push_back(std::move(f)); }
    void Flush() { auto work = std::move(pending); pending.clear(); for (auto& f : work) f(); }
};
struct Display { void CloseMenu() {} };
struct Backlight { void SetBrightness(int) {} void RestoreBrightness() {} };
struct Battery { void EnterSleep() {} };
struct Slept {};
void esp_deep_sleep_start() { throw Slept{}; }
void esp_restart() { assert(false); }
// BOARD_TIMING_CONSTANTS
struct Passport {
    Timer timer;
    Timer* idle_timer_ = &timer;
    std::atomic<uint32_t> idle_generation_{0};
    std::atomic<int> idle_seconds_{0}, soft_sleep_seconds_{0};
    std::atomic<bool> soft_sleep_active_{false}, deep_sleep_started_{false};
    int64_t last_key_us_ = 0;
    Display display; Display* display_ = &display;
    Battery battery; Battery* battery_ = &battery;
    Backlight light;
    static constexpr int AUDIO_PINS[1] = {0}, I2C_PINS[1] = {0};
    Backlight* GetBacklight() { return &light; }
    void SleepPanel() {} void WakePanel() {} void SetStandbyClock(bool) {}
    void PrepareWakeupSource() {} void SuspendAudio() {}
    void ReleasePins(const int*, unsigned long, const char*) {}
    void PrepareDisplayForDeepSleep() {}
'''
        timing = "\n".join(line for line in board.splitlines() if line.startswith((
            "static constexpr int kSoftSleepSeconds =",
            "static constexpr int kDeepSleepSeconds =",
            "static constexpr int kDeepSleepAfterSoftSleepSeconds =",
            "static constexpr int64_t kIdleTimerPeriodUs =",
        )))
        source = source.replace("// BOARD_TIMING_CONSTANTS", timing)
        for signature in (
            "bool IdleForAtLeast(", "void RearmIdleStages()", "void StopIdleTimer()",
            "void StartIdleTimer()", "bool StageRequestStillCurrent(", "void OnIdleSecond()",
            "void EnterSoftSleep(", "void ExitSoftSleep()", "void EnterDeepSleep(",
        ):
            source += function(board, signature) + "\n"
        source += r'''
    void Tick(int seconds, bool flush = true) {
        for (int i = 0; i < seconds; ++i) {
            now += 1000000;
            if (timer.active) OnIdleSecond();
            if (flush) Application::GetInstance().Flush();
        }
    }
};
int main(int argc, char** argv) {
    Passport p;
    auto& app = Application::GetInstance();
    now = 60000000; p.StartIdleTimer();
    std::string test = argv[1];
    if (test == "deadlines") {
        p.Tick(299); assert(!p.soft_sleep_active_);
        p.Tick(1); assert(p.soft_sleep_active_);
        p.Tick(1799); assert(!p.deep_sleep_started_);
        try { p.Tick(1); assert(false); } catch (const Slept&) {}
        assert(p.deep_sleep_started_ && !p.timer.active);
    } else if (test == "busy") {
        app.idle = false; p.Tick(400); assert(!p.soft_sleep_active_);
        app.idle = true; p.Tick(1); assert(p.soft_sleep_active_);
        assert(p.soft_sleep_seconds_ == 0);
        p.Tick(1799); assert(!p.deep_sleep_started_);
        try { p.Tick(1); assert(false); } catch (const Slept&) {}
    } else if (test == "stale_soft") {
        p.Tick(300, false); assert(!app.pending.empty());
        p.last_key_us_ = now; p.RearmIdleStages(); app.Flush();
        assert(!p.soft_sleep_active_ && !p.timer.active);
    } else if (test == "stale_deep") {
        p.Tick(300); p.Tick(1800, false);
        p.last_key_us_ = now; p.RearmIdleStages(); app.Flush();
        assert(!p.deep_sleep_started_ && !p.timer.active);
        p.ExitSoftSleep(); assert(!p.soft_sleep_active_);
    } else if (test == "idempotent") {
        p.Tick(100); p.StartIdleTimer(); assert(p.idle_seconds_ == 160);
        p.Tick(200); assert(p.soft_sleep_active_);
    } else if (test == "stale_while_timer_restarts") {
        p.Tick(300, false);
        p.last_key_us_ = now; p.RearmIdleStages();
        now += 360000000; p.StartIdleTimer(); app.Flush();
        assert(!p.soft_sleep_active_ && p.timer.active);
        p.Tick(1); assert(p.soft_sleep_active_);
    } else { assert(false); }
}
'''
        path = pathlib.Path(cls.tmp.name) / "passport-idle.cc"
        path.write_text(source)
        subprocess.run(["c++", "-std=c++17", "-Wall", "-Wextra", str(path), "-o", cls.binary],
                       check=True, capture_output=True, text=True)

    def test_stage_deadlines(self):
        subprocess.run([self.binary, "deadlines"], check=True)

    def test_busy_application_retries_and_delays_deep_sleep(self):
        subprocess.run([self.binary, "busy"], check=True)

    def test_key_invalidates_queued_soft_sleep(self):
        subprocess.run([self.binary, "stale_soft"], check=True)

    def test_key_invalidates_queued_deep_sleep(self):
        subprocess.run([self.binary, "stale_deep"], check=True)

    def test_timer_start_does_not_restart_countdown(self):
        subprocess.run([self.binary, "idempotent"], check=True)

    def test_old_request_cannot_enter_new_idle_cycle(self):
        subprocess.run([self.binary, "stale_while_timer_restarts"], check=True)

    def test_both_button_routes_invalidate_stages(self):
        source = function(BOARD.read_text(), "void InitializeButtons()")
        for handler in source.split("OnPressDown([this]() {")[1:]:
            body = handler.split("});", 1)[0]
            self.assertLess(body.index("RearmIdleStages();"), body.index("WakeUpPowerSaveTimer();"))
        self.assertEqual(source.count("RearmIdleStages();"), 2)
