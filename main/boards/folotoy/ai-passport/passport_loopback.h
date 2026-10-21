#ifndef PASSPORT_LOOPBACK_H_
#define PASSPORT_LOOPBACK_H_
#include "sdkconfig.h"
#if CONFIG_PASSPORT_ES8311_LOOPBACK_EXP
#include "codecs/es8311_audio_codec.h"
void RunPassportLoopback(Es8311AudioCodec* codec, i2s_chan_handle_t rx, i2s_chan_handle_t tx,
                         const std::atomic<uint32_t>& overflows);
#endif
#endif
