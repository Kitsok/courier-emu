// Shared authoritative 80186 timer/controller state. Python views and both
// native engines access this storage; no per-batch timer snapshots are needed.
#pragma once
#include <cstdint>
#include <algorithm>
#include <limits>

namespace courier {
struct Timer186 {
    uint64_t index, control, compare_a, compare_b, count;
    int64_t origin;
    uint64_t max_counts;
    uint64_t period() const {
        return (compare_a ? compare_a : 65536)
            + ((control & 2) ? (compare_b ? compare_b : 65536) : 0);
    }
    bool counting() const { return (control & 0x8000) && !(control & 0x0c); }
    void advance(int64_t tick) {
        if (!counting()) { origin = tick; return; }
        if (tick <= origin) return;
        const uint64_t total = count + uint64_t(tick - origin);
        const uint64_t p = period(), wraps = total / p;
        count = total % p; origin = tick;
        if (!wraps) return;
        max_counts += wraps; control |= 0x20;
        if (!(control & 1)) { control &= ~uint64_t(0x8000); count = 0; }
    }
};

struct Timers186 {
    Timer186 slots[3];
    uint64_t instruction_base;
    double ratio;
    uint64_t pending_count, pending[3];
    uint64_t controller_mask, controller_writes;
    uint64_t fast, answers_reads;
    uint64_t granted, accelerated, reads, writes, interrupts, revision;
    uint64_t read_counts[11][2], read_mask, last_read_tick[3];

    int64_t tick_at(uint64_t instructions) const { return int64_t(double(instructions) * ratio); }
    static unsigned vector(unsigned index) { return index == 0 ? 8 : index == 1 ? 18 : 19; }
    void tick(uint64_t instructions) {
        ++revision;
        const int64_t now = tick_at(instructions);
        for (auto &timer : slots) {
            const uint64_t before = timer.max_counts;
            timer.advance(now);
            if (timer.max_counts == before || !(timer.control & 0x2000)) continue;
            const unsigned v = vector(unsigned(timer.index));
            bool present = false;
            for (uint64_t j = 0; j < pending_count; ++j) present |= pending[j] == v;
            if (!present && pending_count < 3) pending[pending_count++] = v;
        }
    }
    uint64_t deadline() const {
        uint64_t first = std::numeric_limits<uint64_t>::max();
        for (const auto &timer : slots) {
            if (!timer.counting()) continue;
            const int64_t due = timer.origin + int64_t(timer.period()) - int64_t(timer.count);
            uint64_t at = due > 0 ? uint64_t(double(due) / ratio) : 0;
            while (at && tick_at(at - 1) >= due) --at;
            while (tick_at(at) < due) ++at;
            first = std::min(first, at);
        }
        return first;
    }
    unsigned pending_interrupt() const {
        return !(controller_mask & 1) && pending_count ? unsigned(pending[0]) : 0;
    }
    unsigned take_interrupt() {
        if (!pending_count) return 0;
        const unsigned v = unsigned(pending[0]);
        for (uint64_t j = 1; j < pending_count; ++j) pending[j-1] = pending[j];
        --pending_count; ++interrupts;
        return v;
    }
};
} // namespace courier
