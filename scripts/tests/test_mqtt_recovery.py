"""Execute production MQTT lifecycle callbacks with deterministic host transport/task stubs."""
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def block(source, start):
    start = source.index(start)
    first = source.index('{', start)
    depth = 1
    end = first + 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[first:end]


class MqttRecoveryTests(unittest.TestCase):
    def test_disconnect_closes_stale_session_on_main_task_and_busy_retry_is_rearmed(self):
        source = (ROOT / 'main/protocols/mqtt_protocol.cc').read_text()
        disconnect = block(source, 'mqtt_->OnDisconnected(')
        retry = block(source, '.callback =')
        harness = r'''
#include <cassert>
#include <atomic>
#include <functional>
#include <memory>
#include <mutex>
#include <vector>
#define ESP_LOGI(...) ((void)0)
#define MQTT_RECONNECT_INTERVAL_MS 60000
using uint32_t=unsigned;
constexpr int kDeviceStateIdle=0, kDeviceStateListening=1, kDeviceStateSpeaking=2, kDeviceStateConnecting=3;
namespace Lang { namespace Strings { const char* SERVER_NOT_CONNECTED="disconnected"; } }
int timer_starts=0;
void esp_timer_start_once(int, long) { ++timer_starts; }
void esp_timer_stop(int) {}
class Application {
public:
 int state=kDeviceStateListening;
 std::vector<std::function<void()>> tasks;
 static Application& GetInstance() { static Application a; return a; }
 int GetDeviceState() { return state; }
 void Schedule(std::function<void()> f) { tasks.push_back(f); }
 void Drain() { while(!tasks.empty()) { auto f=tasks.front();tasks.erase(tasks.begin());f(); } }
};
class MqttProtocol {
public:
 std::shared_ptr<std::atomic<bool>> alive_=std::make_shared<std::atomic<bool>>(true);
 std::atomic<unsigned> mqtt_generation_{1};
 std::function<void()> on_disconnected_;
 std::mutex channel_mutex_;
 std::shared_ptr<int> udp_=std::make_shared<int>(1);
 int reconnect_timer_=1, closed=0, errors=0, connects=0;
 void CloseAudioChannel(bool goodbye=true) { assert(!goodbye); ++closed;udp_.reset();Application::GetInstance().state=kDeviceStateIdle; }
 void SetError(const char*) { ++errors; }
 bool StartMqttClient(bool) { ++connects;return true; }
 void Disconnect() { const unsigned generation=mqtt_generation_; auto fn=[this, generation]() DISCONNECT; fn(); }
};
int main() {
 auto& app=Application::GetInstance(); MqttProtocol p;
 p.Disconnect();
 assert(p.closed==0); // transport callback must not mutate application/UDP directly
 app.Drain(); assert(p.closed==1); assert(p.errors==1); assert(app.state==kDeviceStateIdle);
 auto retry=[](void* arg) RETRY;
 app.state=kDeviceStateListening; timer_starts=0;retry(&p);app.Drain();
 assert(timer_starts==1); assert(p.connects==0);
 app.state=kDeviceStateIdle;retry(&p);app.Drain();assert(p.connects==1);
 // A queued callback from a replaced client must not close a new session.
 p.udp_=std::make_shared<int>(2); app.state=kDeviceStateListening;
 p.Disconnect();++p.mqtt_generation_;app.Drain();assert(p.closed==1);
 // Destruction while a callback is queued must also be safe.
 p.Disconnect();*p.alive_=false;app.Drain();assert(p.closed==1);
}
'''.replace('DISCONNECT', disconnect).replace('RETRY', retry)
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            (p / 'test.cc').write_text(harness)
            subprocess.check_call(['g++', '-std=c++23', str(p / 'test.cc'), '-o', str(p / 'test')])
            subprocess.check_call([str(p / 'test')])



class AudioChannelTimeoutTests(unittest.TestCase):
    def test_timeout_reaches_error_cleanup_for_active_conversation(self):
        source=(ROOT/'main/application.cc').read_text()
        tick=block(source,'if (bits & MAIN_EVENT_CLOCK_TICK)')
        error=block(source,'if (bits & MAIN_EVENT_ERROR)')
        harness=r'''
#include <cassert>
#include <string>
constexpr int kDeviceStateIdle=0,kDeviceStateListening=1,kDeviceStateSpeaking=2,kDeviceStateNotifying=3;
constexpr int MAIN_EVENT_ERROR=1;
int events=0;
void xEventGroupSetBits(int,int bits){events|=bits;}
namespace Lang { namespace Strings {const char* ERROR="error";const char* SERVER_TIMEOUT="timeout";} namespace Sounds {constexpr int OGG_EXCLAMATION=1;} }
struct SystemInfo {static void PrintHeapStats(){}};
struct Display {void UpdateStatusBar(){}};
struct Board {static Board& GetInstance(){static Board b;return b;} Display*GetDisplay(){static Display d;return &d;}};
struct Protocol {bool opened=false;int closed=0;bool IsAudioChannelOpened(){return opened;}void CloseAudioChannel(bool goodbye=true){assert(!goodbye);++closed;}};
struct App {
 int state=kDeviceStateListening,clock_ticks_=0,event_group_=1,alerts=0;
 std::string last_error_message_;Protocol p;Protocol*protocol_=&p;
 int GetDeviceState(){return state;}void SetDeviceState(int s){state=s;}void StopNotification(){}
 void Alert(const char*,const char*,const char*,int){++alerts;}
 void Tick() TICK
 void Error() ERROR
};
int main(){
 for(int state:{kDeviceStateListening,kDeviceStateSpeaking}){
  App a;a.state=state;events=0;a.Tick();assert(events==MAIN_EVENT_ERROR);
  a.Error();assert(a.state==kDeviceStateIdle);assert(a.p.closed==1);assert(a.alerts==1);
 }
 App a;a.p.opened=true;events=0;a.Tick();assert(events==0);
 a.p.opened=false;a.state=kDeviceStateIdle;a.Tick();assert(events==0);
 a.state=kDeviceStateNotifying;a.Tick();assert(events==0);
}
'''.replace('TICK',tick).replace(' void Error() ERROR',' void Error() '+error)
        with tempfile.TemporaryDirectory() as temp:
            d=Path(temp);(d/'test.cc').write_text(harness)
            subprocess.check_call(['g++','-std=c++23',str(d/'test.cc'),'-o',str(d/'test')])
            subprocess.check_call([str(d/'test')])

if __name__ == '__main__':
    unittest.main()
