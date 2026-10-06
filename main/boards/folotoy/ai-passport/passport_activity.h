#ifndef PASSPORT_ACTIVITY_H_
#define PASSPORT_ACTIVITY_H_

#include "device_state.h"

// What the Passport glass says about the conversation. There is no
// kDeviceStateThinking: after manual StopListening the device is idle while
// the audio channel stays open, and that gap is the thinking phase.
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

#endif  // PASSPORT_ACTIVITY_H_
