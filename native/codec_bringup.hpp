// ASIC initialization master for the silicon DAA register device.
#pragma once
#include "silicon_daa.hpp"
#include <vector>
namespace courier::analog {
struct BringUpState {
    int64_t rate=9600,configuration_1=0x10,configuration_2=0,level=0,gpio_configuration=0,index=0,polls=0;
};
struct CodecBringUp {
    size_t references=1;
    void retain(){++references;}
    void release(){if(--references==0)delete this;}
    SiliconDaa &codec;
    BringUpState s;
    std::vector<int32_t> steps;
    explicit CodecBringUp(SiliconDaa &part):codec(part){}
    int step() {
        const int index=int(s.index),line=int(codec.line)-1;
        switch(index) {
        case 0:codec.write(0x3c,0);break;
        case 1:codec.write(line?0x42:0x40,uint16_t(s.rate));break;
        case 2:codec.write(0x3e,0);break;
        case 3:++s.polls;if(codec.readiness()!=(line?0x33:0x0f))return 8;break;
        case 4:codec.write(0x4c,uint16_t(s.gpio_configuration));codec.write(0x4e,0);codec.write(0x50,0);codec.write(0x52,0);break;
        case 5:codec.write(line?0x48:0x46,uint16_t(s.level));break;
        case 6:codec.write(0x5c,uint16_t(s.configuration_1));codec.write(0x62,uint16_t(s.configuration_2));break;
        default:return 0;
        }
        ++s.index;steps.push_back(index+1);return index+1;
    }
    void service(int64_t frames=1) {
        codec.elapse(frames);
        for(int n=0;n<8 && s.index<7;++n)if(step()==8)break;
    }
};
} // namespace courier::analog
