// Time-based 8N1 DTE input wire, shared with the analog board runtime.
#pragma once
#include <cstdint>

namespace courier {
struct DteWire186 {
    uint64_t bit_instructions=1, byte=256, started=0, edge=0;
    void begin(uint8_t value,uint64_t now) {byte=value;started=now;edge=1;}
    void idle() {byte=256;edge=0;}
    bool take_edge() {const bool value=edge;edge=0;return value;}
    int64_t bit_index(int64_t now) const {
        if(byte==256)return 10;
        const int64_t elapsed=now-int64_t(started), period=int64_t(bit_instructions);
        // Match Python floor division, including diagnostic pre-start reads.
        return elapsed>=0?elapsed/period:-1-((-1-elapsed)/period);
    }
    int level(int64_t now) const {
        const int64_t index=bit_index(now);
        if(byte==256 || index>=9)return 1;
        if(index<0)return -1;
        return index==0?0:int((byte>>(index-1))&1);
    }
    bool complete(int64_t now) const {return byte!=256 && bit_index(now)>=10;}
};
} // namespace courier
