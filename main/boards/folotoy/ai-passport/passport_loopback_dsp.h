#ifndef PASSPORT_LOOPBACK_DSP_H_
#define PASSPORT_LOOPBACK_DSP_H_

#include <cmath>
#include <cstddef>
#include <cstdint>

namespace passport_loopback {
inline constexpr int kRate = 16000;
inline constexpr int kFrames = 160;
// 800 ms log sweep (200..3200 Hz), 200 ms silence; -18 dBFS peak.
inline int16_t Signal(uint32_t frame) {
    const double t = (frame % kRate) / double(kRate);
    if (t >= 0.8) return 0;
    const double a = std::log(16.0) / 0.8;
    const double phase = 2 * 3.141592653589793 * 200 * std::expm1(a * t) / a;
    const double envelope = std::fmin(1.0, std::fmin(t / 0.01, (0.8 - t) / 0.01));
    return static_cast<int16_t>(4000 * envelope * std::sin(phase));
}
struct Correlation {
    int lag = 0;  // positive: mic follows reference
    double peak = 0;
};
inline Correlation Correlate(const int16_t* stereo, int frames, int max_lag) {
    Correlation result;
    for (int lag = -max_lag; lag <= max_lag; ++lag) {
        double xy = 0, xx = 0, yy = 0, sx = 0, sy = 0;
        int n = 0;
        for (int i = max_lag; i < frames - max_lag; ++i) {
            double x = stereo[2 * (i + lag)], y = stereo[2 * i + 1];
            xy += x * y; xx += x * x; yy += y * y; sx += x; sy += y; ++n;
        }
        double vx = xx - sx * sx / n, vy = yy - sy * sy / n;
        double r = vx > 1 && vy > 1 ? (xy - sx * sy / n) / std::sqrt(vx * vy) : 0;
        if (std::fabs(r) > std::fabs(result.peak)) result = {lag, r};
    }
    return result;
}
inline uint32_t Crc32(const uint8_t* data, size_t len) {
    uint32_t crc = 0xffffffff;
    for (size_t i = 0; i < len; ++i) {
        crc ^= data[i];
        for (int bit = 0; bit < 8; ++bit) crc = (crc >> 1) ^ (0xedb88320u & -(crc & 1));
    }
    return ~crc;
}
// Caller supplies 4*((len+2)/3)+1 bytes.
inline void Base64(const uint8_t* data, size_t len, char* out) {
    constexpr char alphabet[] = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    size_t pos = 0;
    for (size_t i = 0; i < len; i += 3) {
        uint32_t v = uint32_t(data[i]) << 16;
        if (i + 1 < len) v |= uint32_t(data[i + 1]) << 8;
        if (i + 2 < len) v |= data[i + 2];
        out[pos++] = alphabet[(v >> 18) & 63]; out[pos++] = alphabet[(v >> 12) & 63];
        out[pos++] = i + 1 < len ? alphabet[(v >> 6) & 63] : '=';
        out[pos++] = i + 2 < len ? alphabet[v & 63] : '=';
    }
    out[pos] = 0;
}
}  // namespace passport_loopback
#endif
