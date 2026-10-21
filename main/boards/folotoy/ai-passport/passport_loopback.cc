#include "passport_loopback.h"
#if CONFIG_PASSPORT_ES8311_LOOPBACK_EXP
#include "passport_loopback_dsp.h"
#include <esp_log.h>
#include <esp_timer.h>
#include <freertos/queue.h>
#include <freertos/task.h>
#include <algorithm>
#include <atomic>
#include <cstdio>
#include <memory>
#include <new>

namespace {
using namespace passport_loopback;
struct Block {
    uint32_t seq;
    int16_t pcm[kFrames * 2];
};
struct Experiment {
    i2s_chan_handle_t rx, tx;
    QueueHandle_t queue = nullptr;
    std::atomic<bool> stop{false}, capture_done{false}, playback_done{false};
    std::atomic<uint32_t> capture_errors{0}, export_drops{0}, tx_errors{0}, captured{0};
};
void Capture(void* arg) {
    auto* e = static_cast<Experiment*>(arg);
    Block b{};
    uint32_t total = CONFIG_PASSPORT_LOOPBACK_SECONDS * 100;
    for (b.seq = 0; b.seq < total && !e->stop; ++b.seq) {
        size_t bytes = 0;
        esp_err_t err = i2s_channel_read(e->rx, b.pcm, sizeof(b.pcm), &bytes, 100);
        if (err != ESP_OK || bytes != sizeof(b.pcm)) {
            ++e->capture_errors;
            // Fixed sequence represents an attempted 10 ms block, not proof of sample continuity.
            continue;
        }
        ++e->captured;
        if (xQueueSend(e->queue, &b, 0) != pdTRUE) ++e->export_drops;
    }
    e->capture_done = true;
    vTaskDelete(nullptr);
}
void Playback(void* arg) {
    auto* e = static_cast<Experiment*>(arg);
    int16_t pcm[kFrames * 2];
    for (uint32_t frame = 0; frame < CONFIG_PASSPORT_LOOPBACK_SECONDS * kRate && !e->stop;
         frame += kFrames) {
        for (int i = 0; i < kFrames; ++i) pcm[2*i] = pcm[2*i+1] = Signal(frame+i);
        size_t bytes = 0;
        if (i2s_channel_write(e->tx, pcm, sizeof(pcm), &bytes, 100) != ESP_OK ||
            bytes != sizeof(pcm)) ++e->tx_errors;
    }
    e->playback_done = true;
    vTaskDelete(nullptr);
}
}  // namespace

void RunPassportLoopback(Es8311AudioCodec* codec, i2s_chan_handle_t rx, i2s_chan_handle_t tx,
                         const std::atomic<uint32_t>& overflows) {
    using namespace passport_loopback;
    auto e = std::unique_ptr<Experiment>(new (std::nothrow) Experiment);
    if (!e) return;
    e->rx = rx; e->tx = tx;
    // Eight 10 ms blocks, ~5.2 KB, independent of experiment duration. No capture waits on UART.
    e->queue = xQueueCreate(8, sizeof(Block));
    if (!e->queue) return;
    const int normal_rate = codec->input_sample_rate();
    const uint32_t overflow_start = overflows.load();
    codec->SetLoopbackRate(kRate);
    // Flush stale RX DMA from the previous 24 kHz stream before measurement.
    Block b{};
    for (int i = 0; i < 12; ++i) {
        size_t bytes;
        i2s_channel_read(rx, b.pcm, sizeof(b.pcm), &bytes, 20);
    }
    printf("LBK_BEGIN rate=16000 channels=2 bits=16 block_frames=160 seconds=%d "
           "mapping=ADCL_mic_DACR_ref volume=%d gain=%.1f\n",
           CONFIG_PASSPORT_LOOPBACK_SECONDS, codec->output_volume(), codec->input_gain());
    bool capture = xTaskCreate(Capture, "lbk_rx", 3072, e.get(), 8, nullptr) == pdPASS;
    bool playback = capture && xTaskCreate(Playback, "lbk_tx", 3072, e.get(), 7, nullptr) == pdPASS;
    if (!capture) e->capture_done = true;
    if (!playback) { e->playback_done = true; e->stop = true; }
    if (!playback) ESP_LOGE("Loopback", "Task allocation failed; run invalid");
    uint32_t second = 0, count = 0, window_count = 0;
    double mic_sq = 0, ref_sq = 0;
    int16_t window[640 * 2]{};
#if CONFIG_PASSPORT_LOOPBACK_EXPORT_PCM
    char encoded[4 * ((sizeof(b.pcm) + 2) / 3) + 1];
#endif
    auto report = [&]() {
        auto c = window_count == 640 ? Correlate(window, 640, 160) : Correlation{};
        printf("LBK_STAT sec=%lu mic_rms=%.3f ref_rms=%.3f lag_samples=%d lag_ms=%.3f "
               "corr=%.6f valid=%d captured=%lu capture_errors=%lu export_drops=%lu "
               "rx_overflows=%lu tx_errors=%lu lost_samples=unknown\n",
               static_cast<unsigned long>(second), std::sqrt(mic_sq / std::max<uint32_t>(1u,count)),
               std::sqrt(ref_sq / std::max<uint32_t>(1u,count)), c.lag, c.lag * 1000.0/kRate, c.peak,
               window_count == 640 && std::fabs(c.peak) > 0.2,
               static_cast<unsigned long>(e->captured.load()),
               static_cast<unsigned long>(e->capture_errors.load()),
               static_cast<unsigned long>(e->export_drops.load()),
               static_cast<unsigned long>(overflows.load() - overflow_start),
               static_cast<unsigned long>(e->tx_errors.load()));
    };
    int64_t deadline = esp_timer_get_time() + (CONFIG_PASSPORT_LOOPBACK_SECONDS + 3LL)*1000000;
    while (!e->capture_done || uxQueueMessagesWaiting(e->queue)) {
        if (esp_timer_get_time() > deadline) e->stop = true;
        if (xQueueReceive(e->queue, &b, pdMS_TO_TICKS(20)) != pdTRUE) continue;
        if (b.seq / 100 != second) {
            report(); second = b.seq / 100; count = window_count = 0; mic_sq = ref_sq = 0;
        }
        for (int i = 0; i < kFrames; ++i) {
            mic_sq += double(b.pcm[2*i])*b.pcm[2*i];
            ref_sq += double(b.pcm[2*i+1])*b.pcm[2*i+1]; ++count;
        }
        // A contiguous 40 ms window during the sweep, maximum lag +/-10 ms.
        if (b.seq % 100 >= 40 && b.seq % 100 < 44) {
            if (window_count == (b.seq % 100 - 40)*kFrames) {
                std::copy_n(b.pcm, kFrames*2, window + window_count*2);
                window_count += kFrames;
            }
        }
#if CONFIG_PASSPORT_LOOPBACK_EXPORT_PCM
        auto* raw = reinterpret_cast<const uint8_t*>(b.pcm);  // ESP32-C3 is little endian.
        Base64(raw, sizeof(b.pcm), encoded);
        printf("LBK %lu %u %08lx %s\n", static_cast<unsigned long>(b.seq),
               unsigned(sizeof(b.pcm)), static_cast<unsigned long>(Crc32(raw, sizeof(b.pcm))), encoded);
#endif
    }
    report();
    e->stop = true;
    while (!e->capture_done || !e->playback_done) vTaskDelay(pdMS_TO_TICKS(10));
    printf("LBK_END blocks=%d captured=%lu capture_errors=%lu export_drops=%lu "
           "rx_overflows=%lu tx_errors=%lu\n", CONFIG_PASSPORT_LOOPBACK_SECONDS * 100,
           static_cast<unsigned long>(e->captured.load()),
           static_cast<unsigned long>(e->capture_errors.load()),
           static_cast<unsigned long>(e->export_drops.load()),
           static_cast<unsigned long>(overflows.load() - overflow_start),
           static_cast<unsigned long>(e->tx_errors.load()));
    codec->SetLoopbackRate(normal_rate);
    codec->EnableInput(false);
    codec->EnableOutput(false);
    vQueueDelete(e->queue);
}
#endif
