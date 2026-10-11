#pragma once

#include <esp_heap_caps.h>

#include <algorithm>
#include <atomic>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <limits>
#include <new>
#include <type_traits>
#include <utility>
#include <vector>

bool TextGlyphStorageUsesPsram();

// Fallible, exact-sized storage. Copies retain the same immutable bitmap;
// callers must finish writing a buffer before handing it to another task/cache.
// TryResize detaches, and preserves the previous buffer on allocation failure.
template <typename T>
class TextGlyphStorage {
    static_assert(std::is_trivially_copyable_v<T>);
    struct alignas(std::max(alignof(T), alignof(std::atomic<size_t>))) Storage {
        std::atomic<size_t> references{1};
        size_t count;
        explicit Storage(size_t n) : count(n) {}
    };

public:
    TextGlyphStorage() = default;
    TextGlyphStorage(const TextGlyphStorage& other) : storage_(other.storage_) { Retain(); }
    TextGlyphStorage(TextGlyphStorage&& other) noexcept
        : storage_(std::exchange(other.storage_, nullptr)) {}
    TextGlyphStorage& operator=(TextGlyphStorage other) noexcept {
        swap(other);
        return *this;
    }
    ~TextGlyphStorage() { clear(); }

    bool TryResize(size_t count) {
        if (count == 0) {
            clear();
            return true;
        }
        if (count > (std::numeric_limits<size_t>::max() - sizeof(Storage)) / sizeof(T)) {
            return false;
        }
        uint32_t caps = (TextGlyphStorageUsesPsram() ? MALLOC_CAP_SPIRAM : MALLOC_CAP_INTERNAL) |
                        MALLOC_CAP_8BIT;
        void* memory = heap_caps_malloc(sizeof(Storage) + count * sizeof(T), caps);
        if (memory == nullptr) {
            return false;
        }
        TextGlyphStorage next;
        next.storage_ = new (memory) Storage(count);
        for (size_t i = 0; i < count; ++i) {
            new (next.data() + i) T{};
        }
        if (!empty()) {
            std::memcpy(next.data(), data(), std::min(count, size()) * sizeof(T));
        }
        swap(next);
        return true;
    }
    void clear() {
        if (storage_ && storage_->references.fetch_sub(1, std::memory_order_acq_rel) == 1) {
            storage_->~Storage();
            heap_caps_free(storage_);
        }
        storage_ = nullptr;
    }
    void swap(TextGlyphStorage& other) noexcept { std::swap(storage_, other.storage_); }
    size_t size() const { return storage_ ? storage_->count : 0; }
    bool empty() const { return size() == 0; }
    T* data() { return storage_ ? reinterpret_cast<T*>(storage_ + 1) : nullptr; }
    const T* data() const { return storage_ ? reinterpret_cast<const T*>(storage_ + 1) : nullptr; }
    T* begin() { return data(); }
    T* end() { return storage_ ? data() + size() : nullptr; }
    const T* begin() const { return data(); }
    const T* end() const { return storage_ ? data() + size() : nullptr; }
    T& operator[](size_t i) { return data()[i]; }
    const T& operator[](size_t i) const { return data()[i]; }

private:
    void Retain() {
        if (storage_) {
            storage_->references.fetch_add(1, std::memory_order_relaxed);
        }
    }
    Storage* storage_ = nullptr;
};

struct TextGlyph {
    uint32_t codepoint = 0;
    uint32_t adv_w = 0;
    uint16_t box_w = 0;
    uint16_t box_h = 0;
    int16_t ofs_x = 0;
    int16_t ofs_y = 0;
    TextGlyphStorage<uint8_t> bitmap;
};
