// Existing analog ROM DTE adapter, with native queue and character admission.
#pragma once
#include <deque>
#include "serial186.hpp"
#include "dte186.hpp"
namespace courier {
struct ReceiveState {
    uint64_t opened=0,attention_armed=0,started=0,edge_at=0,bit=0,count=0;
};
struct DteReceive {
    ReceiveState &s;
    std::deque<uint8_t> input;
    uint64_t layout[10];
    DteReceive(ReceiveState &state,const uint64_t *values):s(state) {
        std::copy(values,values+10,layout);
    }
    void push(const uint8_t *bytes,size_t size) {
        input.insert(input.end(),bytes,bytes+size);s.count=input.size();
    }
    int pop() {
        if(input.empty())return -1;
        const auto byte=input.front();input.pop_front();s.count=input.size();return byte;
    }
    unsigned advance(uint8_t *m,Serial186 &uart,MachineServiceState &irq,
                     DteWire186 &wire,uint64_t now,unsigned flags) {
        // flags: IF, online mode, off-hook, DSP ready. Layout is discovered
        // by the existing ROM loader, rather than embedding another image.
        if(!(flags&1)||irq.serial_count||input.empty())return 0;
        auto word=[&](uint64_t a){return unsigned(m[a]|unsigned(m[a+1])<<8);};
        auto put=[&](uint64_t a,unsigned v){m[a]=uint8_t(v);m[a+1]=uint8_t(v>>8);};
        const auto callbacks=layout[0];
        unsigned command=word(callbacks+4);
        if(!s.opened && (!(flags&8)||!word(callbacks)||command!=layout[3]
                ||!(m[48]|m[49]|m[50]|m[51])))return 0;
        if(s.opened&&!uart.holding&&!(flags&6)
                &&command!=layout[3]&&command!=layout[4])return 0;
        if(!s.opened) {
            m[layout[5]]=2;put(callbacks,unsigned(layout[2]));
            put(callbacks+4,unsigned(layout[3]));m[layout[6]]&=0xfe;s.opened=1;
        } else if(!uart.holding) {
            if(command!=layout[7])s.attention_armed=0;
            if(command==layout[3]||(command==layout[7]&&!s.attention_armed)) {
                put(callbacks,unsigned(layout[2]));s.attention_armed=command==layout[7];
            }
        }
        if(wire.byte==256) {
            wire.begin(input.front(),now);uart.holding=1;
            s.started=now;s.edge_at=now+150;s.bit=0;return 512;
        }
        if(!wire.complete(int64_t(now)))return 0;
        wire.idle();uart.holding=0;
        command=word(callbacks+4);
        if(command==layout[3]||command==layout[4]||command==layout[7]) {
            put(0x50,unsigned(layout[1]));put(0x52,0x8000);
        }
        uart.control=0x21;
        const auto byte=unsigned(pop());uart.deliver(uint8_t(byte),irq);
        return 256|byte;
    }
};
} // namespace courier
