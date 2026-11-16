// Shared analog-board interrupt requests and 80186 vector entry.
#pragma once
#include <cstddef>
#include <cstdint>
#include <cstring>

namespace courier {
struct MachineServiceState {
    int64_t console_owed=0,timer_poll_owed=0,last_frame=0;
    uint64_t last_tick=0,ticks=0;
    uint64_t int0_pending=0,int1_pending=0,timer_pending=0,timer_delivered=0,int0_in_service=0,stack_depth=0;
    uint8_t stack[64]{};
    uint64_t external_pending=0,serial_count=0,serial_pending[2]{};
    uint64_t pending_mask=0,irq_enabled=0,irq_entries[5]{};

    uint64_t interrupt_shadow=0;

    void refresh_pending() {
        pending_mask = (external_pending?1:0) | (int0_pending?2:0)
            | (serial_count?4:0) | (int1_pending?8:0) | (timer_pending?16:0);
    }
    void eoi(uint16_t value) {
        if (!stack_depth) return;
        unsigned completed;
        if (value & 0x8000) completed=stack[--stack_depth];
        else {
            completed=value&0x1f;
            for (uint64_t i=0;i<stack_depth;++i) if(stack[i]==completed) {
                std::memmove(stack+i,stack+i+1,stack_depth-i-1);
                --stack_depth;break;
            }
        }
        if(completed==12)int0_in_service=0;
    }
    // 0: no eligible request; 1: entered; -1: a watched vector/stack needs
    // the reference dispatcher. No request or CPU state changes on -1.
    int dispatch(uint32_t *r,uint8_t *memory,std::size_t size,const uint8_t *guard) {
        if(!irq_enabled || !pending_mask || interrupt_shadow || !(r[13]&0x200))return 0;
        unsigned source,vector;
        if(external_pending){source=0;vector=unsigned(external_pending);}
        else if(int0_pending){source=1;vector=unsigned(int0_pending);}
        else if(serial_count){source=2;vector=unsigned(serial_pending[0]);}
        else if(int1_pending){source=3;vector=unsigned(int1_pending);}
        else {source=4;vector=unsigned(timer_pending);}
        if(vector>255 || stack_depth>=64 || vector*4+4>size)return -1;
        for(unsigned k=0;k<4;++k)
            if(!(guard[vector*4+k]&1) || (guard[vector*4+k]&16))return -1;
        uint32_t slots[3];
        for(unsigned k=0;k<3;++k) {
            slots[k]=((r[10]&0xffff)*16+((r[4]-2*(k+1))&0xffff))&0xfffff;
            if(slots[k]+2>size)return -1;
            for(unsigned j=0;j<2;++j)
                if(!(guard[slots[k]+j]&2) || (guard[slots[k]+j]&32))return -1;
        }
        const uint32_t values[3]={r[13],r[9],r[12]};
        for(unsigned k=0;k<3;++k) {
            memory[slots[k]]=uint8_t(values[k]);
            memory[slots[k]+1]=uint8_t(values[k]>>8);
        }
        r[4]=(r[4]-6)&0xffff;
        r[13]&=~uint32_t(0x200);
        r[12]=uint32_t(memory[vector*4]|memory[vector*4+1]<<8);
        r[9]=uint32_t(memory[vector*4+2]|memory[vector*4+3]<<8);
        stack[stack_depth++]=uint8_t(vector);
        switch(source) {
        case 0:external_pending=0;break;
        case 1:int0_pending=0;int0_in_service=1;break;
        case 2:
            if(--serial_count)serial_pending[0]=serial_pending[1];
            break;
        case 3:int1_pending=0;break;
        case 4:timer_pending=0;++timer_delivered;break;
        }
        ++irq_entries[source];refresh_pending();return 1;
    }
};
} // namespace courier
