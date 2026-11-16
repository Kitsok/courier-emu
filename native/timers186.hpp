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
    uint32_t read(uint32_t address,unsigned size,uint64_t instructions,bool grant) {
        if(address<0xff30||address>0xff46||(address&1)||address==0xff44)return UINT32_MAX;
        const unsigned offset=(address-0xff30)/2,field=offset%4;
        auto &timer=slots[offset/4];
        const int64_t now=tick_at(instructions);
        ++revision;++reads;timer.advance(now);
        if(field==3&&grant&&fast&&answers_reads&&!(timer.control&0x20)&&timer.counting()) {
            const int64_t remaining=int64_t(timer.period())-int64_t(timer.count);
            timer.origin-=remaining;granted+=uint64_t(remaining);++accelerated;
            timer.advance(now);
        }
        if(!answers_reads)return UINT32_MAX;
        const auto value=field==0?timer.count:field==1?timer.compare_a:
            field==2?timer.compare_b:timer.control;
        return uint32_t(value)&(size==1?255:65535);
    }
    // 0: unrelated address, 1: handled, 2: T0 compare A needs the Python
    // board-selection callback before its final origin is published.
    unsigned write(uint32_t address, unsigned size, uint64_t value, uint64_t instructions) {
        if (address == 0xff08) {
            ++controller_writes; controller_mask = value & 0x7f; return 1;
        }
        if (address >= 0xff12 && address <= 0xff1e && !(address & 1)) {
            ++controller_writes;
            const uint64_t bit = uint64_t(1) << ((address - 0xff12) / 2);
            controller_mask = (value & 8) ? controller_mask | bit : controller_mask & ~bit;
            return 1;
        }
        if (address < 0xff30 || address > 0xff46 || (address & 1) || address == 0xff44) return 0;
        const unsigned offset = (address - 0xff30) / 2;
        auto &timer = slots[offset / 4];
        const unsigned field = offset % 4;
        ++revision; ++writes;
        timer.advance(tick_at(instructions));
        uint64_t &dest = field == 0 ? timer.count : field == 1 ? timer.compare_a :
            field == 2 ? timer.compare_b : timer.control;
        if (size == 1) value = (dest & 0xff00) | (value & 0xff);
        if (field == 3) {
            uint64_t control = timer.control;
            if (value & 0x4000) control = (control & ~uint64_t(0x8000)) | (value & 0x8000);
            timer.control = (control & ~uint64_t(0x303f)) | (value & 0x303f);
        } else dest = value & 0xffff;
        if (address == 0xff32) return 2;
        timer.origin = tick_at(instructions);
        return 1;
    }
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
