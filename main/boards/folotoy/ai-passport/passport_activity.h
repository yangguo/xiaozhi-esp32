#ifndef PASSPORT_ACTIVITY_H_
#define PASSPORT_ACTIVITY_H_

#include "device_state.h"

// What the Passport glass says about the conversation. There is no
// kDeviceStateThinking: after manual StopListening the device is idle while
// the audio channel stays open, and that gap is the thinking phase. The
// label for it is Lang::Strings::THINKING.
enum class PassportActivity {
    kNone = 0,
    kListening,
    kThinking,
    kSpeaking,
};

inline PassportActivity PassportNextActivity(PassportActivity current, DeviceState state) {
    switch (state) {
        case kDeviceStateListening:
            return PassportActivity::kListening;
        case kDeviceStateSpeaking:
        case kDeviceStateNotifying:
            return PassportActivity::kSpeaking;
        case kDeviceStateIdle:
            // Release ends listening before the server speaks. A later idle
            // (speaking finished, or the channel closed) clears the chip.
            if (current == PassportActivity::kListening) {
                return PassportActivity::kThinking;
            }
            return PassportActivity::kNone;
        default:
            return PassportActivity::kNone;
    }
}

// Dimmed backlight should come back for a phase the user has to read.
// Connecting has no chip of its own; the status line says "Connecting...".
inline bool PassportActivityWakesScreen(PassportActivity activity, DeviceState state) {
    if (activity != PassportActivity::kNone) {
        return true;
    }
    return state == kDeviceStateConnecting;
}

// Thinking is the idle gap after listening, and only while the audio channel
// is still open. An error alert owns the status line, so it does not enter
// thinking either. CanEnterSleepMode() is the wrong gate: it is also false
// while the codec is busy, which is not what the chip means.
inline PassportActivity PassportResolveActivity(PassportActivity current, DeviceState state,
                                                bool channel_open, bool has_error) {
    const PassportActivity next = PassportNextActivity(current, state);
    if (next != PassportActivity::kThinking) {
        return next;
    }
    if (current != PassportActivity::kListening || !channel_open || has_error) {
        return PassportActivity::kNone;
    }
    return PassportActivity::kThinking;
}

// Channel close while already idle does not emit another state event.
// Drop the chip at that moment instead of waiting until sleep is allowed.
inline bool PassportThinkingClears(PassportActivity current, DeviceState state, bool channel_open) {
    return current == PassportActivity::kThinking && state == kDeviceStateIdle && !channel_open;
}

// The status bar already shows LISTENING, SPEAKING, and THINKING. A second
// chip with the same string is what put 聆听中 on screen twice.
inline bool PassportActivityDuplicatesStatus(PassportActivity activity) {
    return activity == PassportActivity::kListening || activity == PassportActivity::kSpeaking ||
           activity == PassportActivity::kThinking;
}

#endif  // PASSPORT_ACTIVITY_H_
