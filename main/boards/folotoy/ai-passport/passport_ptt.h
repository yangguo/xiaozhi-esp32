#ifndef PASSPORT_PTT_H_
#define PASSPORT_PTT_H_

#include "device_state.h"

#include <stdint.h>

// How long OK must be held before it becomes push-to-talk. 300 ms also
// matched a slow tap and ADC-ladder bounce, and that press then opened a
// manual channel instead of toggling chat. One second is still under the
// button component's 2 s long press, so a long utterance is not cut off.
inline constexpr int kPassportPttArmMs = 1000;

// Idle: no OK gesture. Holding: the arm timer is running. Active: StartListening
// has been committed, so release ends the utterance.
enum class PassportPttPhase {
    kIdle = 0,
    kHolding,
    kActive,
};

// StartListening only changes state from idle (open or resume) and speaking
// (abort, then listen). From listening it is a no-op, and the matching
// StopListening would cut off an auto-mode session a short click already
// started. Connecting and the settings list are not push-to-talk either.
inline bool PassportPttCanArm(DeviceState state, bool menu_open, bool key_blocked) {
    if (key_blocked || menu_open) {
        return false;
    }
    return state == kDeviceStateIdle || state == kDeviceStateSpeaking;
}

struct PassportPttDecision {
    PassportPttPhase phase;
    bool start_listening;
    bool stop_listening;
    bool suppress_click;
    bool click_consumed;
};

inline PassportPttDecision PassportPttPressDown(DeviceState state, bool menu_open,
                                                bool key_blocked) {
    PassportPttDecision decision = {};
    decision.phase = PassportPttCanArm(state, menu_open, key_blocked) ? PassportPttPhase::kHolding
                                                                      : PassportPttPhase::kIdle;
    return decision;
}

// `network_up` is false when this hold would have to open a link and the
// station is down. A bail does not set suppress_click, so the release is
// still a normal tap.
inline PassportPttDecision PassportPttOnArm(PassportPttPhase phase, DeviceState state,
                                            bool menu_open, bool key_blocked, bool network_up,
                                            bool still_held) {
    PassportPttDecision decision = {};
    decision.phase = PassportPttPhase::kIdle;
    if (phase != PassportPttPhase::kHolding || !still_held) {
        return decision;
    }
    if (!PassportPttCanArm(state, menu_open, key_blocked) || !network_up) {
        return decision;
    }
    decision.phase = PassportPttPhase::kActive;
    decision.start_listening = true;
    decision.suppress_click = true;
    return decision;
}

inline PassportPttDecision PassportPttOnRelease(PassportPttPhase phase) {
    PassportPttDecision decision = {};
    decision.phase = PassportPttPhase::kIdle;
    if (phase == PassportPttPhase::kActive) {
        decision.stop_listening = true;
    }
    return decision;
}

inline PassportPttDecision PassportPttOnClick(bool suppress_click) {
    PassportPttDecision decision = {};
    if (suppress_click) {
        decision.click_consumed = true;
    }
    return decision;
}

// A 2 s long press must not cancel a push-to-talk utterance and must not
// open settings. It can still close a list when no gesture is in progress.
inline bool PassportPttIgnoresLongPress(PassportPttPhase phase) {
    return phase != PassportPttPhase::kIdle;
}

#endif  // PASSPORT_PTT_H_
