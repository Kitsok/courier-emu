// Register-level Si3021/Si3014 device. Storage is shared with control views.
#pragma once
#include <algorithm>
#include <cstdint>
#include <cstdlib>
#include <iterator>
#include <stdexcept>

namespace courier::analog {
struct SiliconDaa {
    int64_t line=1,revision=4,off_hook=0,line_connected=0,loop_current_ma=0;
    int64_t ring_positive=0,ring_negative=0,receive_overload=0,billing_tone=0;
    int64_t frames=0,resets=0,settling=0,sticky_status=0;
    uint16_t registers[128]{};
    static bool valid(int address) {
        switch(address){case 0x3c:case 0x3e:case 0x40:case 0x42:case 0x46:case 0x48:
        case 0x4c:case 0x4e:case 0x50:case 0x52:case 0x54:case 0x5a:case 0x5c:
        case 0x5e:case 0x62:case 0x64:return true;default:return false;}
    }
    bool powered() const {const int bits=line==1?0xc00:0x3000;return (registers[0x3e]&bits)!=bits;}
    bool pll() const {return registers[line==1?0x40:0x42]!=0;}
    bool link() const {return powered() && pll() && settling>=2;}
    int readiness() const {
        const int power=registers[0x3e];int value=!(power&0x100) && settling>=1?1:0;
        if(!pll())return value;
        if(powered() && settling>=1)value|=2;
        if(settling>=2) {
            if(!(power&(line==1?0x400:0x1000)))value|=line==1?4:16;
            if(!(power&(line==1?0x800:0x2000)))value|=line==1?8:32;
        }
        return value;
    }
    int64_t sense() const {return link()?std::min<int64_t>(15,loop_current_ma>=0?loop_current_ma/6:(loop_current_ma-5)/6):0;}
    int status() const {
        int value=int(sticky_status);
        if(link()) {
            value|=0x40|int(sense()*4);
            if(ring_positive)value|=2;if(ring_negative)value|=1;
            if(receive_overload)value|=0x200;
            if(billing_tone && (registers[0x5c]&0x40))value|=0x100;
        }
        return value;
    }
    void reset() {
        std::fill(std::begin(registers),std::end(registers),0);
        registers[0x3c]=line==1?0x4001:0x8002;registers[0x3e]=0xff00;
        registers[0x46]=line==1?0x8080:0;registers[0x48]=line==2?0x8080:0;
        registers[0x4c]=line==1?0x3f:0xfc00;registers[0x5a]=0x11;registers[0x5c]=0xf010;
        settling=sticky_status=0;++resets;
    }
    void elapse(int64_t count) {
        if(count<=0)return;frames+=count;
        if(powered() || !(registers[0x3e]&0x100))settling=std::min<int64_t>(2,settling+count);
    }
    void hook(bool enabled) {off_hook=enabled;loop_current_ma=enabled && line_connected?25:0;}
    static bool line_register(int address) {return address==0x5c || address==0x5e || address==0x62 || address==0x64;}
    void write(int address,uint16_t value) {
        if(address==0x3c){reset();return;}if(address==0x5a)return;
        if(!valid(address))throw std::invalid_argument("unknown silicon DAA register");
        if(line_register(address) && !link()){sticky_status|=0x80;return;}
        if(address==0x3e){registers[address]=(registers[address]&~0x3f00)|(value&0x3f00);settling=0;return;}
        if(address==0x40 || address==0x42) {
            const int rates[]={7200,8000,8228,8400,9000,9600,10285,12000,13714};int best=7200;
            for(const int rate:rates)if(std::abs(rate-int(value))<std::abs(best-int(value)))best=rate;
            registers[address]=value?uint16_t(best):0;return;
        }
        if(address==0x5e){sticky_status&=(value|~0x380)&0xffff;return;}
        registers[address]=value;
    }
    int read(int address) {
        if(address==0x3e)return (registers[address]&~0xff)|readiness();
        if(address==0x5e){if(!link())sticky_status|=0x80;return status();}
        if(line_register(address) && !link()){sticky_status|=0x80;return 0;}
        if(!valid(address))throw std::invalid_argument("unknown silicon DAA register");
        return registers[address];
    }
};
} // namespace courier::analog
