// Board settings EEPROM; preserves the existing Microwire model.
#pragma once
#include <cstdint>
#include <cstdio>
#include <cstring>

namespace courier {
struct Microwire93c66 {
    uint8_t data[512]{};
    uint64_t reads=0,writes=0,erases=0,write_enabled=0;
    uint64_t clock=0,selected=0,bits=0,count=0,started=0,opcode=4,address=0;
    uint64_t pending=0,pending_count=0,shift_out=65536,data_out=1,trace_count=0,pio_data_in=0;
    char traces[256][64]{};
    uint64_t pio_reads[8][2]{},pio_read_mask=0;
    uint16_t word(unsigned a) const {a=(a&255)*2;return uint16_t(data[a]|unsigned(data[a+1])<<8);}
    void set_word(unsigned a,unsigned value) {a=(a&255)*2;data[a]=uint8_t(value);data[a+1]=uint8_t(value>>8);}
    template<typename... A> void trace(const char *format,A... args) {
        if(trace_count<256)std::snprintf(traces[trace_count++],64,format,args...);
    }
    void begin() {
        bits=count=started=address=pending=pending_count=0;
        opcode=4;shift_out=65536;data_out=1;
    }
    void end() {
        if(opcode==1&&pending_count==16) {
            if(write_enabled) {
                set_word(unsigned(address),unsigned(pending));++writes;
                trace("write 0x%02x=0x%04x",unsigned(address),unsigned(pending));
            } else trace("write 0x%02x=0x%04x refused",unsigned(address),unsigned(pending));
        }
        opcode=4;shift_out=65536;data_out=1;
    }
    void command() {
        switch(opcode) {
        case 2:shift_out=word(unsigned(address));++reads;data_out=0;
            trace("read 0x%02x=0x%04x",unsigned(address),unsigned(shift_out));break;
        case 1:pending=pending_count=0;break;
        case 3:if(write_enabled)set_word(unsigned(address),65535);++erases;
            trace("erase 0x%02x",unsigned(address));break;
        default:switch((address>>6)&3) {
            case 3:write_enabled=1;trace("write-enable");break;
            case 0:write_enabled=0;trace("write-disable");break;
            case 2:if(write_enabled)std::memset(data,255,sizeof(data));++erases;trace("erase-all");break;
            }
        }
    }
    void rising(bool input) {
        if(shift_out!=65536){data_out=bool(shift_out&0x8000);shift_out=(shift_out<<1)&65535;return;}
        if(!started){if(input){started=1;bits=count=0;}return;}
        bits=((bits<<1)|input)&0xffffffff;++count;
        if(opcode==4){if(count==10){opcode=(bits>>8)&3;address=bits&255;command();}return;}
        pending=((pending<<1)|input)&65535;++pending_count;
    }
    void write_latch(unsigned value) {
        const bool select=value&0x20,new_clock=value&0x40;
        if(!select){if(selected)end();selected=0;clock=new_clock;return;}
        if(!selected)begin();selected=1;
        if(new_clock&&!clock)rising(value&0x10);
        clock=new_clock;
    }
    unsigned read_latch() const {return 8|(data_out?16:0);}
    void port1(unsigned value) {
        write_latch((value&0x20)|((value&4)?0x40:0)|(pio_data_in?0x10:0));
    }
};
} // namespace courier
